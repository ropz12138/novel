import json
from pathlib import Path

from fastapi import HTTPException, status
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.work_model import Chapter, User, Work
from app.schemas.work_schema import (
    ChapterChatResponse,
    ChapterGenerateResponse,
    ChapterOut,
    ChapterUpdateRequest,
    ChatEditResponse,
    OutlineGenerateResponse,
    OutlineQuickGenerateRequest,
    OutlineTreeData,
    WorkOut,
)

PROMPT_DIR = Path(__file__).resolve().parent / "prompt_templates"

# Hardcoded demo user until auth is implemented
DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"


def _ensure_demo_user(db: Session) -> None:
    if not db.query(User).filter_by(id=DEMO_USER_ID).first():
        db.add(User(
            id=DEMO_USER_ID,
            username="创作者",
            email="demo@novel.local",
            password_hash="no-login",
        ))
        db.commit()


class _ChatEditOutput(BaseModel):
    assistant_message: str
    operations: list[dict]


class WorkService:
    def __init__(self) -> None:
        self.chat_model = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.7,
        )

    def _read_prompt(self, file_name: str) -> str:
        path = PROMPT_DIR / file_name
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _normalize_outline_result(result: dict) -> dict:
        story = result.get("story") or {}
        timeline = result.get("timeline") or []
        branches = result.get("branches") or []
        foreshadowing = result.get("foreshadowing") or []

        normalized_story = {
            "title": story.get("title", "未命名作品"),
            "genre": story.get("genre", "未分类"),
            "volume": story.get("volume", "第一卷"),
        }

        normalized_timeline = []
        for idx, node in enumerate(timeline, start=1):
            normalized_timeline.append(
                {
                    "id": node.get("id") or f"N{idx}",
                    "order": node.get("order") or idx,
                    "development_node": node.get("development_node") or node.get("title") or node.get("content") or "主线推进",
                    "time_node": node.get("time_node") or node.get("phase") or f"阶段{idx}",
                    "chapter_start": int(node.get("chapter_start", idx * 10 - 9)),
                    "chapter_end": int(node.get("chapter_end", idx * 10)),
                    "mainline": bool(node.get("mainline", True)),
                }
            )

        fallback_attach = normalized_timeline[0]["id"] if normalized_timeline else "N1"
        normalized_branches = []
        for idx, node in enumerate(branches, start=1):
            normalized_branches.append(
                {
                    "id": node.get("id") or f"B{idx}",
                    "name": node.get("name") or node.get("title") or f"支线{idx}",
                    "attach_to": node.get("attach_to") or fallback_attach,
                    "side": node.get("side") if node.get("side") in {"left", "right"} else ("left" if idx % 2 else "right"),
                    "chapter_start": int(node.get("chapter_start", idx * 10 - 9)),
                    "chapter_end": int(node.get("chapter_end", idx * 10)),
                    "summary": node.get("summary") or node.get("content") or node.get("name") or "支线推进",
                }
            )

        normalized_foreshadowing = []
        for idx, node in enumerate(foreshadowing, start=1):
            normalized_foreshadowing.append(
                {
                    "id": node.get("id") or f"F{idx}",
                    "plant_node": node.get("plant_node") or fallback_attach,
                    "payoff_node": node.get("payoff_node") or fallback_attach,
                    "content": node.get("content") or "伏笔待回收",
                }
            )

        return {
            "story": normalized_story,
            "timeline": normalized_timeline,
            "branches": normalized_branches,
            "foreshadowing": normalized_foreshadowing,
        }

    @staticmethod
    def _apply_operations(outline: dict, operations: list[dict]) -> dict:
        """Apply a list of tool-call operations to an outline tree."""
        timeline = outline.get("timeline", [])
        branches = outline.get("branches", [])
        foreshadowing = outline.get("foreshadowing", [])
        story = outline.get("story", {})

        for op in operations:
            tool = op.get("tool", "")
            args = op.get("args", {})

            if tool == "add_timeline_node":
                new_id = f"N{len(timeline) + 1}"
                order = args.get("order", len(timeline) + 1)
                timeline.append({
                    "id": new_id,
                    "order": order,
                    "development_node": args.get("development_node", "新主线节点"),
                    "time_node": args.get("time_node", f"阶段{len(timeline) + 1}"),
                    "chapter_start": int(args.get("chapter_start", 1)),
                    "chapter_end": int(args.get("chapter_end", 10)),
                    "mainline": True,
                })
                # Re-sort by order
                timeline.sort(key=lambda n: n.get("order", 0))

            elif tool == "add_branch_node":
                new_id = f"B{len(branches) + 1}"
                branches.append({
                    "id": new_id,
                    "attach_to": args.get("attach_to", timeline[0]["id"] if timeline else "N1"),
                    "side": args.get("side", "right"),
                    "name": args.get("name", "新支线"),
                    "summary": args.get("summary", ""),
                    "chapter_start": int(args.get("chapter_start", 1)),
                    "chapter_end": int(args.get("chapter_end", 10)),
                })

            elif tool == "update_node":
                node_id = args.get("node_id", "")
                fields = args.get("fields", {})
                # Search in timeline, branches, foreshadowing
                for node_list in [timeline, branches, foreshadowing]:
                    for node in node_list:
                        if node.get("id") == node_id:
                            node.update(fields)
                            break

            elif tool == "delete_node":
                node_id = args.get("node_id", "")
                timeline = [n for n in timeline if n.get("id") != node_id]
                branches = [n for n in branches if n.get("id") != node_id]
                foreshadowing = [n for n in foreshadowing if n.get("id") != node_id]

            elif tool == "update_story":
                fields = args.get("fields", {})
                story.update(fields)

        return {
            "story": story,
            "timeline": timeline,
            "branches": branches,
            "foreshadowing": foreshadowing,
        }

    def generate_outline(
        self, payload: OutlineQuickGenerateRequest, db: Session
    ) -> OutlineGenerateResponse:
        _ensure_demo_user(db)

        parser = JsonOutputParser(pydantic_object=OutlineTreeData)
        template = self._read_prompt("work_generate_outline.txt")
        prompt = PromptTemplate.from_template(template)

        chain = prompt | self.chat_model | parser
        try:
            tags_str = "、".join(payload.tags) if payload.tags else "无特殊要求"
            result = chain.invoke(
                {
                    "format_instructions": parser.get_format_instructions(),
                    "idea": payload.idea.strip(),
                    "tags": tags_str,
                }
            )
            normalized = self._normalize_outline_result(result)
            outline_tree = OutlineTreeData.model_validate(normalized)

            story = normalized["story"]
            work = Work(
                user_id=DEMO_USER_ID,
                title=story["title"],
                genre=story["genre"],
                idea=payload.idea.strip(),
                tags=payload.tags,
                outline_tree=normalized,
                status="草稿",
            )
            db.add(work)
            db.commit()
            db.refresh(work)

            return OutlineGenerateResponse(outline_tree=outline_tree, work_id=work.id)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM outline generation failed: {exc}"
            ) from exc

    def update_outline(self, work_id: str, outline_tree: dict, db: Session) -> WorkOut:
        """Directly save an outline tree (from user inline editing)."""
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")

        story = outline_tree.get("story", {})
        work.outline_tree = outline_tree
        work.title = story.get("title", work.title)
        work.genre = story.get("genre", work.genre)
        db.commit()
        db.refresh(work)
        return WorkOut.model_validate(work)

    def chat_edit(
        self, work_id: str, user_message: str, history: list[dict], db: Session
    ) -> ChatEditResponse:
        """Use LLM to edit the outline via tool-call operations."""
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")

        current_outline = json.dumps(work.outline_tree, ensure_ascii=False, indent=2)
        history_str = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history
        ) if history else "（无）"

        parser = JsonOutputParser(pydantic_object=_ChatEditOutput)
        template = self._read_prompt("work_chat_edit.txt")
        prompt = PromptTemplate.from_template(template)

        chain = prompt | self.chat_model | parser
        try:
            result = chain.invoke(
                {
                    "format_instructions": parser.get_format_instructions(),
                    "current_outline": current_outline,
                    "history": history_str,
                    "user_message": user_message.strip(),
                }
            )

            assistant_message = result.get("assistant_message", "已完成修改。")
            operations = result.get("operations", [])

            # Apply operations to the current outline
            updated_outline = self._apply_operations(work.outline_tree, operations)

            # Save to DB
            story = updated_outline.get("story", {})
            work.outline_tree = updated_outline
            work.title = story.get("title", work.title)
            work.genre = story.get("genre", work.genre)
            db.commit()

            return ChatEditResponse(
                assistant_message=assistant_message,
                operations=operations,
                outline_tree=updated_outline,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM chat edit failed: {exc}"
            ) from exc

    @staticmethod
    def _find_chapter_outline(outline_tree: dict, chapter_number: int) -> str:
        """Extract the outline info relevant to a specific chapter number."""
        timeline = outline_tree.get("timeline", [])
        branches = outline_tree.get("branches", [])

        relevant = []
        for node in timeline:
            if node.get("chapter_start", 0) <= chapter_number <= node.get("chapter_end", 0):
                relevant.append(f"[主线] {node.get('time_node', '')}：{node.get('development_node', '')}（第{node['chapter_start']}-{node['chapter_end']}章）")
        for node in branches:
            if node.get("chapter_start", 0) <= chapter_number <= node.get("chapter_end", 0):
                relevant.append(f"[支线·{node.get('name', '')}] {node.get('summary', '')}（第{node['chapter_start']}-{node['chapter_end']}章）")

        return "\n".join(relevant) if relevant else "（无匹配纲要，请根据整体大纲自行推进）"

    def generate_chapter(self, work_id: str, chapter_number: int, db: Session) -> ChapterGenerateResponse:
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")

        outline_tree = work.outline_tree

        # Collect previous chapters' content (up to 3 most recent before this one)
        prev_chapters = (
            db.query(Chapter)
            .filter_by(work_id=work_id)
            .filter(Chapter.chapter_number < chapter_number)
            .filter(Chapter.content != "")
            .order_by(Chapter.chapter_number.desc())
            .limit(3)
            .all()
        )
        prev_chapters.reverse()

        previous_text = ""
        if prev_chapters:
            parts = []
            for ch in prev_chapters:
                summary = ch.content[:800] + ("..." if len(ch.content) > 800 else "")
                parts.append(f"--- 第{ch.chapter_number}章 {ch.title} ---\n{summary}")
            previous_text = "\n\n".join(parts)
        else:
            previous_text = "（这是第一章，暂无前文）"

        story_info = json.dumps(outline_tree.get("story", {}), ensure_ascii=False)
        outline_text = json.dumps(outline_tree, ensure_ascii=False, indent=2)
        chapter_outline = self._find_chapter_outline(outline_tree, chapter_number)

        template = self._read_prompt("work_generate_chapter.txt")
        prompt = PromptTemplate.from_template(template)

        chain = prompt | self.chat_model
        try:
            result = chain.invoke({
                "story_info": story_info,
                "outline_tree": outline_text,
                "chapter_number": str(chapter_number),
                "chapter_outline": chapter_outline,
                "previous_chapters": previous_text,
            })

            content = result.content if hasattr(result, "content") else str(result)

            # Extract title from first line if it matches "第X章 ..." pattern
            lines = content.strip().split("\n", 1)
            title = ""
            body = content.strip()
            if lines and lines[0].startswith("第") and "章" in lines[0][:10]:
                title = lines[0].strip()
                body = lines[1].strip() if len(lines) > 1 else ""

            # Upsert: update if exists, create if not
            chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
            if chapter:
                chapter.title = title or chapter.title
                chapter.content = body
                chapter.status = "已生成"
            else:
                chapter = Chapter(
                    work_id=work_id,
                    chapter_number=chapter_number,
                    title=title or f"第{chapter_number}章",
                    content=body,
                    status="已生成",
                )
                db.add(chapter)

            db.commit()
            db.refresh(chapter)
            return ChapterGenerateResponse(chapter=ChapterOut.model_validate(chapter))
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM chapter generation failed: {exc}"
            ) from exc

    @staticmethod
    def list_chapters(work_id: str, db: Session) -> list[ChapterOut]:
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        chapters = (
            db.query(Chapter)
            .filter_by(work_id=work_id)
            .order_by(Chapter.chapter_number)
            .all()
        )
        return [ChapterOut.model_validate(c) for c in chapters]

    @staticmethod
    def get_chapter(work_id: str, chapter_number: int, db: Session) -> ChapterOut:
        chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        return ChapterOut.model_validate(chapter)

    @staticmethod
    def update_chapter(work_id: str, chapter_number: int, payload: ChapterUpdateRequest, db: Session) -> ChapterOut:
        chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
        if not chapter:
            raise HTTPException(status_code=404, detail="章节不存在")
        if payload.title is not None:
            chapter.title = payload.title
        if payload.content is not None:
            chapter.content = payload.content
            chapter.status = "已编辑"
        db.commit()
        db.refresh(chapter)
        return ChapterOut.model_validate(chapter)

    def chapter_chat_edit(
        self,
        work_id: str,
        chapter_number: int,
        user_message: str,
        history: list[dict],
        db: Session,
    ) -> ChapterChatResponse:
        """Use LLM to edit chapter content via conversation."""
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")

        chapter = db.query(Chapter).filter_by(work_id=work_id, chapter_number=chapter_number).first()
        current_content = chapter.content if chapter else ""
        current_title = chapter.title if chapter else ""

        outline_tree = work.outline_tree
        story_info = json.dumps(outline_tree.get("story", {}), ensure_ascii=False)
        outline_text = json.dumps(outline_tree, ensure_ascii=False, indent=2)
        chapter_outline = self._find_chapter_outline(outline_tree, chapter_number)

        history_str = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history
        ) if history else "（无）"

        parser = JsonOutputParser(pydantic_object=ChapterChatResponse)
        template = self._read_prompt("work_chapter_chat_edit.txt")
        prompt = PromptTemplate.from_template(template)

        chain = prompt | self.chat_model | parser
        try:
            result = chain.invoke({
                "story_info": story_info,
                "outline_tree": outline_text,
                "chapter_number": str(chapter_number),
                "chapter_outline": chapter_outline,
                "current_content": current_content or "（尚未生成正文）",
                "history": history_str,
                "user_message": user_message.strip(),
            })

            assistant_message = result.get("assistant_message", "已完成修改。")
            proposed_content = result.get("proposed_content", current_content)
            proposed_title = result.get("proposed_title")

            return ChapterChatResponse(
                assistant_message=assistant_message,
                proposed_content=proposed_content,
                proposed_title=proposed_title if proposed_title else None,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM chapter chat edit failed: {exc}"
            ) from exc

    @staticmethod
    def list_works(db: Session) -> list[WorkOut]:
        _ensure_demo_user(db)
        works = (
            db.query(Work)
            .filter_by(user_id=DEMO_USER_ID)
            .order_by(Work.created_at.desc())
            .all()
        )
        return [WorkOut.model_validate(w) for w in works]

    @staticmethod
    def get_work(work_id: str, db: Session) -> WorkOut:
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        return WorkOut.model_validate(work)

    @staticmethod
    def delete_work(work_id: str, db: Session) -> None:
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        db.delete(work)
        db.commit()
