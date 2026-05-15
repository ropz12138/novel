"""Edit Chapter Agent — 封装章节正文修改逻辑，返回 diff"""

import difflib
from pathlib import Path

from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from sqlalchemy.orm import Session

from app.core.config import settings
from app.models.work_model import Chapter, Work
from app.services.work_service import WorkService

PROMPT_DIR = Path(__file__).resolve().parent / "prompts"


def _build_diff(old: str, new: str) -> list[dict]:
    """生成逐行 diff，格式类似 git diff。

    返回列表，每项：
      {"type": "context"|"added"|"removed", "line": "...", "line_no": int}
    """
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)

    sm = difflib.SequenceMatcher(None, old_lines, new_lines)
    result = []
    old_no = 0
    new_no = 0

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == "equal":
            for k in range(i1, i2):
                old_no += 1
                new_no += 1
                result.append({"type": "context", "line": old_lines[k].rstrip("\n"), "old_no": old_no, "new_no": new_no})
        elif tag == "replace":
            for k in range(i1, i2):
                old_no += 1
                result.append({"type": "removed", "line": old_lines[k].rstrip("\n"), "old_no": old_no})
            for k in range(j1, j2):
                new_no += 1
                result.append({"type": "added", "line": new_lines[k].rstrip("\n"), "new_no": new_no})
        elif tag == "insert":
            for k in range(j1, j2):
                new_no += 1
                result.append({"type": "added", "line": new_lines[k].rstrip("\n"), "new_no": new_no})
        elif tag == "delete":
            for k in range(i1, i2):
                old_no += 1
                result.append({"type": "removed", "line": old_lines[k].rstrip("\n"), "old_no": old_no})

    return result


def _summarize_diff(diff: list[dict]) -> dict:
    """统计 diff 摘要"""
    added = sum(1 for d in diff if d["type"] == "added")
    removed = sum(1 for d in diff if d["type"] == "removed")
    return {"lines_added": added, "lines_removed": removed, "total_changes": added + removed}


class EditChapterAgent:
    """章节编辑 Agent — 用 LLM 修改章节正文并返回 diff"""

    def __init__(self, emit):
        self.emit = emit
        self.work_service = WorkService()

    async def edit(
        self,
        work_id: str,
        chapter_number: int,
        user_message: str,
        db: Session,
        emit_diff_event: bool = True,
    ) -> dict:
        """编辑章节正文，返回 diff 和修改后全文。

        Returns:
            {
                "old_content": str,
                "new_content": str,
                "diff": [...],
                "summary": {"lines_added": int, "lines_removed": int},
                "accepted": bool,  # 需要前端确认
            }
        """
        # 1. 读取现有章节
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            self.emit("error", {"message": "作品不存在"})
            return {"error": "作品不存在"}

        chapter = db.query(Chapter).filter_by(
            work_id=work_id, chapter_number=chapter_number
        ).first()
        if not chapter or not chapter.content:
            self.emit("error", {"message": f"第{chapter_number}章尚未生成正文，无法编辑"})
            return {"error": "章节不存在或无正文"}

        old_content = chapter.content
        self.emit("stage_start", {"stage": "edit_chapter", "label": f"修改第{chapter_number}章"})

        # 2. 构建上下文
        ws = WorkService()
        outline_tree = work.outline_tree or {}
        story_info = str(outline_tree.get("story", {}))
        chapter_outline = ws._find_chapter_outline(outline_tree, chapter_number)

        # 3. 调用 LLM
        template = (PROMPT_DIR / "edit_chapter.txt").read_text(encoding="utf-8")
        prompt = PromptTemplate.from_template(template)
        llm = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.7,
            streaming=True,
        )
        chain = prompt | llm

        new_content = ""
        async for chunk in chain.astream({
            "story_info": story_info,
            "chapter_outline": chapter_outline or "（无大纲信息）",
            "current_content": old_content,
            "user_message": user_message,
        }):
            text = chunk.content if hasattr(chunk, "content") else str(chunk)
            new_content += text
            self.emit("edit_chapter_stream", {"chunk": text})

        new_content = new_content.strip()

        # 4. 生成 diff
        diff = _build_diff(old_content, new_content)
        summary = _summarize_diff(diff)

        if emit_diff_event:
            self.emit("edit_chapter_diff", {
                "diff": diff,
                "summary": summary,
                "old_content": old_content,
                "new_content": new_content,
                "chapter_number": chapter_number,
            })

        return {
            "old_content": old_content,
            "new_content": new_content,
            "diff": diff,
            "summary": summary,
        }

    def accept_edit(
        self,
        work_id: str,
        chapter_number: int,
        new_content: str,
        db: Session,
        emit_event: bool = True,
    ) -> dict:
        """用户接受修改 — 将新内容写入数据库"""
        chapter = db.query(Chapter).filter_by(
            work_id=work_id, chapter_number=chapter_number
        ).first()
        if not chapter:
            return {"error": "章节不存在"}

        chapter.content = new_content
        chapter.status = "已保存"
        db.commit()
        db.refresh(chapter)

        word_count = len(new_content.replace("\n", "").replace(" ", ""))
        if emit_event:
            self.emit("edit_chapter_accepted", {
                "chapter_number": chapter_number,
                "title": chapter.title,
                "word_count": word_count,
            })
        return {"success": True, "title": chapter.title, "word_count": word_count}
