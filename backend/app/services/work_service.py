import json
import logging
import re
import time
import asyncio
from pathlib import Path

from fastapi import HTTPException, status
from langchain_core.prompts import PromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.config import settings
from app.models.work_model import Chapter, Character, User, Work
from app.services.agent_log_service import log_event, new_session_id
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

logger = logging.getLogger(__name__)
OUTLINE_STREAM_TIMEOUT_S = 45
OUTLINE_FALLBACK_TIMEOUT_S = 45

# Hardcoded demo user until auth is implemented
DEMO_USER_ID = "00000000-0000-0000-0000-000000000001"


def _llm_message_text(ai_msg) -> str:
    raw = getattr(ai_msg, "content", "") or ""
    if isinstance(raw, list):
        parts: list[str] = []
        for block in raw:
            if isinstance(block, str):
                parts.append(block)
            elif isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
        raw = "".join(parts)
    return raw.strip()


def _strip_markdown_json_fence(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```\s*$", "", text)
    return text.strip()


def _extract_balanced_json_object(text: str) -> str | None:
    """Take outermost {...} by brace depth; respects quoted strings and escapes."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_str = False
    escape = False
    for i in range(start, len(text)):
        c = text[i]
        if escape:
            escape = False
            continue
        if in_str:
            if c == "\\":
                escape = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
            continue
        if c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _repair_trailing_commas(blob: str) -> str:
    s = blob
    for _ in range(5):
        prev = s
        s = re.sub(r",(\s*})", r"\1", s)
        s = re.sub(r",(\s*\])", r"\1", s)
        if s == prev:
            break
    return s


def _repair_unquoted_values(blob: str) -> str:
    """Fix bare values like `"age": ？（外表约四十）` → `"age": "？（外表约四十）"`.

    Only matches values that don't start with a JSON literal (`"`, digit, `true`,
    `false`, `null`, `{`, `[`, `-`) or whitespace. The whitespace exclusion prevents
    the regex from backtracking past the ``\\s*`` after the colon and matching
    already-quoted values as bare values.

    Repeats until stable (max 5 iterations) so that values in nested objects are
    also caught, but cannot infinite-loop.
    """
    pat = re.compile(
        r'("[\w]+")\s*:\s*'                         # "key" : with flexible spacing
        r'(?!(\s|"|\d|true|false|null|\[|\{|-))'    # NOT whitespace or a valid JSON value
        r'([^,\]\}]+?)'                              # bare value (non-greedy)
        r'(?=\s*[,}\]\n])'                           # lookahead: comma / close / newline
    )
    s = blob
    for _ in range(5):
        prev = s
        s = pat.sub(r'\1: "\3"', s)
        if s == prev:
            break
    return s


def _loads_outline_json_candidates(text: str) -> dict:
    """Try several tolerant parsing strategies; raises JSONDecodeError from last attempt if all fail."""
    text = _strip_markdown_json_fence(text)
    blobs: list[str] = [text]
    sliced = _extract_balanced_json_object(text)
    if sliced and sliced not in blobs:
        blobs.append(sliced)

    last_err: json.JSONDecodeError | None = None
    for blob in blobs:
        for candidate in (
            blob,
            _repair_trailing_commas(blob),
            _repair_unquoted_values(blob),
            _repair_trailing_commas(_repair_unquoted_values(blob)),
        ):
            try:
                data = json.loads(candidate)
                if isinstance(data, dict):
                    return data
                raise ValueError("LLM JSON root must be an object")
            except json.JSONDecodeError as e:
                last_err = e
                continue
    assert last_err is not None
    raise last_err


def _parse_json_from_llm_message(ai_msg) -> dict:
    """Parse outline JSON from model response (fences, preamble, trailing commas)."""
    text = _llm_message_text(ai_msg)
    return _loads_outline_json_candidates(text)


def _parse_json_from_llm_message_content(text: str) -> dict:
    """Parse outline JSON from raw text content (for streaming where ai_msg is unavailable)."""
    return _loads_outline_json_candidates(text)


def _log_json_decode_context(exc: json.JSONDecodeError, text: str) -> None:
    pos = getattr(exc, "pos", None)
    if pos is None:
        logger.error("outline JSON error %s; body_len=%s", exc, len(text))
        return
    a = max(0, pos - 120)
    b = min(len(text), pos + 120)
    snippet = text[a:b].replace("\n", "\\n")
    logger.error(
        "outline JSON error %s at pos=%s (line=%s col=%s); context …%s…",
        exc,
        pos,
        getattr(exc, "lineno", "?"),
        getattr(exc, "colno", "?"),
        snippet,
    )


def _ensure_demo_user(db: Session) -> None:
    if not db.query(User).filter_by(id=DEMO_USER_ID).first():
        db.add(User(
            id=DEMO_USER_ID,
            username="创作者",
            email="demo@novel.local",
            password_hash="no-login",
        ))
        db.commit()


# DEPRECATED: _ChatEditOutput is no longer used by chat_edit / chat_edit_async.
# These methods now use native Tool-Calling; operations are collected from AIMessage.tool_calls.
class _ChatEditOutput(BaseModel):
    assistant_message: str
    operations: list[dict]


# DEPRECATED: _normalize_operation_args is no longer needed by chat_edit / chat_edit_async.
# Tool-Calling mode produces well-structured tool_calls directly from the LLM API.
def _normalize_operation_args(operations: list[dict]) -> list[dict]:
    """Ensure each operation has a flat ``args`` dict.

    LLMs return tool parameters in various formats:
    - Flat top-level: ``{"tool": "...", "name": "嬴萧", "fields": {...}}``
    - Using ``arguments`` instead of ``args``: ``{"tool": "...", "arguments": {...}}``
    - Extra nesting: ``{"tool": "...", "args": {"parameters": {...}}}``
    - Correct: ``{"tool": "...", "args": {"name": "嬴萧", "fields": {...}}}``

    This helper normalises all variants to the last form.
    """
    _NESTED_KEYS = {"parameters", "params", "args", "arguments"}
    result = []
    for op in operations:
        op = dict(op)  # shallow copy

        # Step 1: If "arguments" exists instead of "args", rename it
        if "arguments" in op and "args" not in op:
            op["args"] = op.pop("arguments")

        # Step 2: Collect args
        args = op.get("args")

        # Step 3: If args is missing, promote top-level extras into args
        if not args or not isinstance(args, dict):
            known = {"tool", "args", "arguments"}
            extras = {k: v for k, v in op.items() if k not in known}
            if extras:
                op["args"] = extras
                for k in extras:
                    op.pop(k, None)
            else:
                op["args"] = {}
            args = op["args"]

        # Step 4: Flatten single nested key like {"parameters": {...}}
        if isinstance(args, dict) and len(args) == 1:
            inner_key = next(iter(args))
            if inner_key in _NESTED_KEYS and isinstance(args[inner_key], dict):
                op["args"] = args[inner_key]

        result.append(op)
    return result


class WorkService:
    def __init__(self) -> None:
        base_model = ChatOpenAI(
            model=settings.llm_model,
            api_key=settings.llm_api_key,
            base_url=settings.llm_base_url,
            temperature=0.7,
            request_timeout=(10, 60),
            max_retries=0,
        )
        self.chat_model = base_model
        # Outline: use JSON mode + normalization — strict tool schemas reject common LLM field aliases (title vs development_node, etc.)
        self.outline_json_llm = base_model.bind(
            response_format={"type": "json_object"},
            max_tokens=4096,
            extra_body={"enable_thinking": False},
        )
        # NOTE: chat_edit_model (with_structured_output) removed — chat_edit / chat_edit_async
        # now use native Tool-Calling via self.chat_model.bind_tools(ALL_OUTLINE_TOOLS).
        # chapter_chat_model kept for backward compatibility with deprecated chapter_chat_edit API.
        self.chapter_chat_model = base_model.with_structured_output(ChapterChatResponse, strict=True)

    def _read_prompt(self, file_name: str) -> str:
        path = PROMPT_DIR / file_name
        return path.read_text(encoding="utf-8")

    @staticmethod
    def _normalize_outline_result(result: dict) -> dict:
        def _s(val: object, default: str = "") -> str:
            """Coerce any value to str; None → default."""
            if val is None:
                return default
            return str(val)

        story = result.get("story") or {}
        timeline = result.get("timeline") or []
        branches = result.get("branches") or []
        foreshadowing = result.get("foreshadowing") or []

        normalized_story = {
            "title": _s(story.get("title"), "未命名作品"),
            "genre": _s(story.get("genre"), "未分类"),
            "volume": _s(story.get("volume"), "第一卷"),
        }

        normalized_timeline = []
        for idx, node in enumerate(timeline, start=1):
            legacy_mainline = node.get("mainline")
            legacy_summary = legacy_mainline if isinstance(legacy_mainline, str) else ""
            normalized_timeline.append(
                {
                    "id": _s(node.get("id"), f"N{idx}"),
                    "order": node.get("order") or idx,
                    "development_node": _s(
                        node.get("development_node")
                        or node.get("title")
                        or node.get("content"),
                        "主线推进",
                    ),
                    "summary": _s(
                        node.get("summary")
                        or node.get("description")
                        or legacy_summary
                        or node.get("content"),
                        "主线阶段推进",
                    ),
                    "time_node": _s(
                        node.get("time_node") or node.get("phase"), f"阶段{idx}"
                    ),
                    "chapter_start": int(node.get("chapter_start", idx * 10 - 9)),
                    "chapter_end": int(node.get("chapter_end", idx * 10)),
                }
            )

        fallback_attach = normalized_timeline[0]["id"] if normalized_timeline else "N1"
        normalized_branches = []
        for idx, node in enumerate(branches, start=1):
            normalized_branches.append(
                {
                    "id": _s(node.get("id"), f"B{idx}"),
                    "name": _s(
                        node.get("name") or node.get("title"), f"支线{idx}"
                    ),
                    "attach_to": _s(node.get("attach_to"), fallback_attach),
                    "side": node.get("side")
                    if node.get("side") in {"left", "right"}
                    else ("left" if idx % 2 else "right"),
                    "chapter_start": int(node.get("chapter_start", idx * 10 - 9)),
                    "chapter_end": int(node.get("chapter_end", idx * 10)),
                    "summary": _s(
                        node.get("summary")
                        or node.get("content")
                        or node.get("description")
                        or node.get("name")
                        or node.get("title"),
                        "支线推进",
                    ),
                }
            )

        normalized_foreshadowing = []
        for idx, node in enumerate(foreshadowing, start=1):
            normalized_foreshadowing.append(
                {
                    "id": _s(node.get("id"), f"F{idx}"),
                    "plant_node": _s(node.get("plant_node"), fallback_attach),
                    "payoff_node": _s(node.get("payoff_node"), fallback_attach),
                    "content": _s(node.get("content"), "伏笔待回收"),
                }
            )

        characters = result.get("characters") or []
        normalized_characters = []
        for idx, char in enumerate(characters, start=1):
            normalized_characters.append({
                "name": _s(char.get("name"), f"角色{idx}"),
                "role_type": _s(char.get("role_type"), "配角"),
                "gender": _s(char.get("gender")),
                "age": _s(char.get("age")),
                "appearance": _s(char.get("appearance")),
                "personality": _s(char.get("personality")),
                "background": _s(char.get("background")),
                "skills": _s(char.get("skills")),
                "current_status": _s(char.get("current_status"), "存活"),
                "current_goal": _s(char.get("current_goal")),
                "first_chapter": int(char.get("first_chapter", 1)),
            })

        return {
            "story": normalized_story,
            "timeline": normalized_timeline,
            "branches": normalized_branches,
            "foreshadowing": normalized_foreshadowing,
            "characters": normalized_characters,
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
                    "summary": args.get("summary", ""),
                    "time_node": args.get("time_node", f"阶段{len(timeline) + 1}"),
                    "chapter_start": int(args.get("chapter_start", 1)),
                    "chapter_end": int(args.get("chapter_end", 10)),
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
            **outline,
            "story": story,
            "timeline": timeline,
            "branches": branches,
            "foreshadowing": foreshadowing,
        }

    def generate_outline(
        self, payload: OutlineQuickGenerateRequest, db: Session
    ) -> OutlineGenerateResponse:
        _ensure_demo_user(db)

        template = self._read_prompt("work_generate_outline.txt")
        prompt = PromptTemplate.from_template(template)

        chain = prompt | self.outline_json_llm
        try:
            tags_str = "、".join(payload.tags) if payload.tags else "无特殊要求"
            ai_msg = chain.invoke(
                {
                    "idea": payload.idea.strip(),
                    "tags": tags_str,
                }
            )
            try:
                result_dict = _parse_json_from_llm_message(ai_msg)
            except (json.JSONDecodeError, ValueError) as parse_exc:
                db.rollback()
                preview = _llm_message_text(ai_msg)
                if isinstance(parse_exc, json.JSONDecodeError):
                    _log_json_decode_context(parse_exc, preview)
                else:
                    logger.error(
                        "outline JSON decode failed: %s; content_preview=%r",
                        parse_exc,
                        preview[:2500],
                    )
                meta = getattr(ai_msg, "response_metadata", None) or {}
                if meta.get("finish_reason") == "length":
                    logger.error(
                        "outline: finish_reason=length — output likely truncated "
                        "(provider max_tokens or context limit)"
                    )
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"LLM outline generation failed: invalid JSON — {parse_exc}",
                ) from parse_exc
            normalized = self._normalize_outline_result(result_dict)
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

            # Create character records from outline
            characters_data = normalized.get("characters", [])
            for char_data in characters_data:
                char = Character(
                    work_id=work.id,
                    name=char_data.get("name", ""),
                    role_type=char_data.get("role_type", "配角"),
                    gender=char_data.get("gender", ""),
                    age=char_data.get("age", ""),
                    appearance=char_data.get("appearance", ""),
                    personality=char_data.get("personality", ""),
                    background=char_data.get("background", ""),
                    skills=char_data.get("skills", ""),
                    current_status=char_data.get("current_status", "存活"),
                    current_goal=char_data.get("current_goal", ""),
                    first_chapter=char_data.get("first_chapter", 1),
                    last_chapter=char_data.get("first_chapter"),
                )
                db.add(char)
            db.commit()

            return OutlineGenerateResponse(outline_tree=outline_tree, work_id=work.id)
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"LLM outline generation failed: {exc}"
            ) from exc

    async def generate_outline_stream(self, payload: OutlineQuickGenerateRequest, emit):
        """Stream outline generation progress via SSE, then return the final result.

        Yields SSE events:
        - outline_status
        - outline_tree_progress
        - outline_done
        - error
        """
        from app.core.database import SessionLocal
        db = SessionLocal()
        t_total = time.perf_counter()
        try:
            logger.info(
                "work.generate_outline_stream begin idea_len=%s tags_count=%s",
                len(payload.idea or ""), len(payload.tags or [])
            )
            _ensure_demo_user(db)
            emit("outline_status", {"phase": "generating", "message": "AI 正在生成大纲草案..."})

            template = self._read_prompt("work_generate_outline.txt")
            prompt = PromptTemplate.from_template(template)

            chain = prompt | self.outline_json_llm
            tags_str = "、".join(payload.tags) if payload.tags else "无特殊要求"

            raw_output = ""
            emitted_non_empty_chunk = False
            chunk_count = 0
            non_empty_chunk_count = 0
            t_stream = time.perf_counter()
            stream_timed_out = False
            try:
                async with asyncio.timeout(OUTLINE_STREAM_TIMEOUT_S):
                    async for chunk in chain.astream({
                        "idea": payload.idea.strip(),
                        "tags": tags_str,
                    }):
                        chunk_count += 1
                        text = chunk.content if hasattr(chunk, "content") else str(chunk)
                        if text:
                            raw_output += text
                            emitted_non_empty_chunk = True
                            non_empty_chunk_count += 1
            except TimeoutError:
                stream_timed_out = True
                emit("outline_status", {"phase": "generating", "message": "生成耗时较长，正在切换稳态模式..."})
                logger.warning(
                    "work.generate_outline_stream stream_timeout timeout_s=%s chunks=%s non_empty_chunks=%s",
                    OUTLINE_STREAM_TIMEOUT_S, chunk_count, non_empty_chunk_count
                )
            logger.info(
                "work.generate_outline_stream stream_done elapsed_ms=%.1f chunks=%s non_empty_chunks=%s raw_len=%s",
                (time.perf_counter() - t_stream) * 1000,
                chunk_count,
                non_empty_chunk_count,
                len(raw_output),
            )

            # Some providers stream reasoning-only deltas with empty `content` in OpenAI-compatible mode.
            # In that case LangChain chunks can be empty throughout; fallback to non-stream call to get final JSON.
            if stream_timed_out or not emitted_non_empty_chunk or not raw_output.strip():
                logger.warning(
                    "work.generate_outline_stream stream_empty_fallback triggered chunks=%s raw_len=%s",
                    chunk_count, len(raw_output)
                )
                t_fallback = time.perf_counter()
                try:
                    async with asyncio.timeout(OUTLINE_FALLBACK_TIMEOUT_S):
                        ai_msg = await chain.ainvoke({
                            "idea": payload.idea.strip(),
                            "tags": tags_str,
                        })
                except TimeoutError as exc:
                    emit("error", {"message": f"大纲生成超时（>{OUTLINE_FALLBACK_TIMEOUT_S}s）"})
                    logger.error(
                        "work.generate_outline_stream fallback_timeout timeout_s=%s",
                        OUTLINE_FALLBACK_TIMEOUT_S
                    )
                    return
                raw_output = _llm_message_text(ai_msg)
                logger.info(
                    "work.generate_outline_stream fallback_done elapsed_ms=%.1f raw_len=%s",
                    (time.perf_counter() - t_fallback) * 1000,
                    len(raw_output),
                )
            emit("outline_status", {"phase": "parsing", "message": "正在解析并构建大纲树..."})

            # Parse the accumulated JSON
            try:
                t_parse = time.perf_counter()
                result_dict = _parse_json_from_llm_message_content(raw_output)
                logger.info(
                    "work.generate_outline_stream parse_done elapsed_ms=%.1f keys=%s",
                    (time.perf_counter() - t_parse) * 1000,
                    list(result_dict.keys()) if isinstance(result_dict, dict) else "n/a",
                )
            except (json.JSONDecodeError, ValueError) as parse_exc:
                _log_json_decode_context(parse_exc, raw_output) if isinstance(parse_exc, json.JSONDecodeError) else logger.error("outline parse failed: %s", parse_exc)
                emit("error", {"message": f"大纲解析失败: {parse_exc}"})
                return

            normalized = self._normalize_outline_result(result_dict)
            outline_tree = OutlineTreeData.model_validate(normalized)
            story = normalized["story"]
            logger.info(
                "work.generate_outline_stream normalize_done timeline=%s branches=%s foreshadowing=%s characters=%s",
                len(normalized.get("timeline", [])),
                len(normalized.get("branches", [])),
                len(normalized.get("foreshadowing", [])),
                len(normalized.get("characters", [])),
            )

            emit("outline_tree_progress", {
                "section": "story",
                "index": 1,
                "total": 1,
                "node": story,
            })
            for i, node in enumerate(normalized.get("timeline", []), start=1):
                emit("outline_tree_progress", {
                    "section": "timeline",
                    "index": i,
                    "total": len(normalized.get("timeline", [])),
                    "node": node,
                })
            for i, node in enumerate(normalized.get("branches", []), start=1):
                emit("outline_tree_progress", {
                    "section": "branches",
                    "index": i,
                    "total": len(normalized.get("branches", [])),
                    "node": node,
                })
            for i, node in enumerate(normalized.get("foreshadowing", []), start=1):
                emit("outline_tree_progress", {
                    "section": "foreshadowing",
                    "index": i,
                    "total": len(normalized.get("foreshadowing", [])),
                    "node": node,
                })
            for i, node in enumerate(normalized.get("characters", []), start=1):
                emit("outline_tree_progress", {
                    "section": "characters",
                    "index": i,
                    "total": len(normalized.get("characters", [])),
                    "node": node,
                })
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
            t_db = time.perf_counter()
            db.commit()
            db.refresh(work)

            # Create character records from outline
            characters_data = normalized.get("characters", [])
            for char_data in characters_data:
                char = Character(
                    work_id=work.id,
                    name=char_data.get("name", ""),
                    role_type=char_data.get("role_type", "配角"),
                    gender=char_data.get("gender", ""),
                    age=char_data.get("age", ""),
                    appearance=char_data.get("appearance", ""),
                    personality=char_data.get("personality", ""),
                    background=char_data.get("background", ""),
                    skills=char_data.get("skills", ""),
                    current_status=char_data.get("current_status", "存活"),
                    current_goal=char_data.get("current_goal", ""),
                    first_chapter=char_data.get("first_chapter", 1),
                    last_chapter=char_data.get("first_chapter"),
                )
                db.add(char)
            db.commit()
            logger.info(
                "work.generate_outline_stream db_done elapsed_ms=%.1f work_id=%s chars=%s",
                (time.perf_counter() - t_db) * 1000,
                work.id,
                len(characters_data),
            )

            emit("outline_done", {
                "work_id": work.id,
                "title": story["title"],
                "outline_tree": normalized,
            })
            logger.info(
                "work.generate_outline_stream done total_ms=%.1f work_id=%s",
                (time.perf_counter() - t_total) * 1000,
                work.id,
            )
        except Exception as exc:
            logger.exception("outline streaming failed")
            emit("error", {"message": str(exc)})
        finally:
            db.close()

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
        self, work_id: str, user_message: str, history: list[dict], db: Session,
        session_id: str | None = None,
    ) -> ChatEditResponse:
        """Synchronous outline chat edit using Tool-Calling loop."""
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        from app.services.outline_tools import ALL_OUTLINE_TOOLS

        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")

        from app.services.session_service import create_session, touch_session, get_session
        if session_id:
            existing = get_session(db, session_id)
            if not existing:
                session_id = None
        if not session_id:
            session_id = new_session_id()

        # Ensure a session record exists
        chat_s = get_session(db, session_id)
        if not chat_s:
            create_session(
                db, work_id=work_id, session_id=session_id,
            )
        else:
            touch_session(db, session_id)

        # Log user message
        log_event(db, work_id=work_id, session_id=session_id,
                  session_type="outline_chat", role="user", content=user_message)

        current_outline = json.dumps(work.outline_tree, ensure_ascii=False, indent=2)
        history_str = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history
        ) if history else "（无）"

        # Build characters context
        from app.models.work_model import Character
        characters = db.query(Character).filter_by(work_id=work_id).order_by(Character.first_chapter).all()
        characters_info = self._format_characters_for_prompt(characters)

        # Build system prompt
        template = self._read_prompt("outline_system.txt")
        system_text = template.format(
            current_outline=current_outline,
            characters_info=characters_info,
            history=history_str,
            user_message=user_message.strip(),
        )

        # Prepare mutable outline_tree for tools to modify in-place
        outline_tree = work.outline_tree
        tools_map = {t.name: t for t in ALL_OUTLINE_TOOLS}
        tool_config = {
            "configurable": {
                "outline_tree": outline_tree,
                "db": db,
                "work_id": work_id,
            },
        }

        # Build message list
        messages = [
            SystemMessage(content=system_text),
            HumanMessage(content=user_message.strip()),
        ]

        # LLM bound with tools
        llm_with_tools = self.chat_model.bind_tools(ALL_OUTLINE_TOOLS)

        all_operations = []
        max_iterations = 10

        try:
            for _ in range(max_iterations):
                ai_msg = llm_with_tools.invoke(messages)
                messages.append(ai_msg)

                # No tool_calls → LLM is done
                if not ai_msg.tool_calls:
                    break

                # Execute each tool_call sequentially
                for tc in ai_msg.tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    tool_call_id = tc["id"]

                    all_operations.append({
                        "tool": tool_name,
                        "args": tool_args,
                    })

                    tool_fn = tools_map.get(tool_name)
                    if tool_fn:
                        try:
                            result = tool_fn.invoke(tool_args, config=tool_config)
                            tool_response = str(result)
                        except Exception as tool_exc:
                            tool_response = f"工具执行错误: {tool_exc}"
                            logger.warning("Tool %s execution error: %s", tool_name, tool_exc)
                    else:
                        tool_response = f"未知工具: {tool_name}"

                    messages.append(
                        ToolMessage(content=tool_response, tool_call_id=tool_call_id)
                    )

            # Extract assistant message
            assistant_message = ""
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    assistant_message = msg.content
                    break
            if not assistant_message:
                assistant_message = "已完成修改。" if all_operations else "请告诉我你想修改什么？"

            # Save updated outline
            from sqlalchemy.orm.attributes import flag_modified

            updated_outline = tool_config["configurable"]["outline_tree"]
            story = updated_outline.get("story", {})
            work.outline_tree = updated_outline
            flag_modified(work, "outline_tree")
            work.title = story.get("title", work.title)
            work.genre = story.get("genre", work.genre)
            db.commit()

            # Log assistant response
            log_event(db, work_id=work_id, session_id=session_id,
                      session_type="outline_chat", role="assistant",
                      content=assistant_message,
                      meta={"operations": all_operations})

            return ChatEditResponse(
                assistant_message=assistant_message,
                operations=all_operations,
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

    async def chat_edit_async(
        self, work_id: str, user_message: str, history: list[dict], db: Session,
        session_id: str | None = None,
        dry_run: bool = False,
    ) -> ChatEditResponse:
        """Async outline chat edit using Tool-Calling loop.

        Replaces the old JSON output approach (with_structured_output) with native
        LLM tool-calling, eliminating field name inconsistencies (e.g. 'name' vs 'tool').

        Args:
            dry_run: 如果为 True，工具正常执行但最后不 commit。
                     调用方负责在确认后 commit 或 rollback。
        """
        from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

        from app.services.outline_tools import ALL_OUTLINE_TOOLS

        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")

        from app.services.session_service import create_session, touch_session, get_session
        if session_id:
            existing = get_session(db, session_id)
            if not existing:
                session_id = None
        if not session_id:
            session_id = new_session_id()

        chat_s = get_session(db, session_id)
        if not chat_s:
            create_session(
                db, work_id=work_id, session_id=session_id,
            )
        else:
            touch_session(db, session_id)

        log_event(db, work_id=work_id, session_id=session_id,
                  session_type="outline_chat", role="user", content=user_message)

        current_outline = json.dumps(work.outline_tree, ensure_ascii=False, indent=2)
        history_str = "\n".join(
            f"{m.get('role', 'user')}: {m.get('content', '')}" for m in history
        ) if history else "（无）"

        from app.models.work_model import Character
        characters = db.query(Character).filter_by(work_id=work_id).order_by(Character.first_chapter).all()
        characters_info = self._format_characters_for_prompt(characters)

        # Build system prompt
        template = self._read_prompt("outline_system.txt")
        system_text = template.format(
            current_outline=current_outline,
            characters_info=characters_info,
            history=history_str,
            user_message=user_message.strip(),
        )

        # Prepare mutable outline_tree for tools to modify in-place
        outline_tree = work.outline_tree
        tools_map = {t.name: t for t in ALL_OUTLINE_TOOLS}
        tool_config = {
            "configurable": {
                "outline_tree": outline_tree,
                "db": db,
                "work_id": work_id,
            },
        }

        # Build message list
        messages = [
            SystemMessage(content=system_text),
            HumanMessage(content=user_message.strip()),
        ]

        # LLM bound with tools
        llm_with_tools = self.chat_model.bind_tools(ALL_OUTLINE_TOOLS)

        all_operations = []
        max_iterations = 10

        try:
            for _ in range(max_iterations):
                ai_msg = await llm_with_tools.ainvoke(messages)
                messages.append(ai_msg)

                # No tool_calls → LLM is done, extract text response
                if not ai_msg.tool_calls:
                    break

                # Execute each tool_call sequentially (outline_tree is shared mutable state)
                for tc in ai_msg.tool_calls:
                    tool_name = tc["name"]
                    tool_args = tc["args"]
                    tool_call_id = tc["id"]

                    # Record operation for response
                    all_operations.append({
                        "tool": tool_name,
                        "args": tool_args,
                    })

                    # Execute the tool
                    tool_fn = tools_map.get(tool_name)
                    if tool_fn:
                        try:
                            result = tool_fn.invoke(tool_args, config=tool_config)
                            tool_response = str(result)
                        except Exception as tool_exc:
                            tool_response = f"工具执行错误: {tool_exc}"
                            logger.warning("Tool %s execution error: %s", tool_name, tool_exc)
                    else:
                        tool_response = f"未知工具: {tool_name}"

                    messages.append(
                        ToolMessage(content=tool_response, tool_call_id=tool_call_id)
                    )

            # Extract assistant message from the last AI response
            assistant_message = ""
            for msg in reversed(messages):
                if isinstance(msg, AIMessage) and msg.content:
                    assistant_message = msg.content
                    break
            if not assistant_message:
                assistant_message = "已完成修改。" if all_operations else "请告诉我你想修改什么？"

            # Save updated outline (tools modified it in-place via config)
            from sqlalchemy.orm.attributes import flag_modified

            updated_outline = tool_config["configurable"]["outline_tree"]
            story = updated_outline.get("story", {})
            work.outline_tree = updated_outline
            flag_modified(work, "outline_tree")
            work.title = story.get("title", work.title)
            work.genre = story.get("genre", work.genre)

            if dry_run:
                # dry_run 模式：flush 到数据库事务中但不 commit，
                # 调用方负责在用户确认后 commit 或 rollback
                db.flush()
            else:
                db.commit()

                log_event(db, work_id=work_id, session_id=session_id,
                          session_type="outline_chat", role="assistant",
                          content=assistant_message,
                          meta={"operations": all_operations})

            return ChatEditResponse(
                assistant_message=assistant_message,
                operations=all_operations,
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
    def _format_characters_for_prompt(characters) -> str:
        """Format characters list into a readable string for the prompt."""
        if not characters:
            return "（暂无角色）"
        lines = []
        for c in characters:
            parts = [f"**{c.name}**（{c.role_type}）"]
            if c.gender:
                parts.append(f"  性别：{c.gender}")
            if c.age:
                parts.append(f"  年龄：{c.age}")
            if c.appearance:
                parts.append(f"  外貌：{c.appearance}")
            if c.personality:
                parts.append(f"  性格：{c.personality}")
            if c.background:
                parts.append(f"  背景：{c.background}")
            if c.skills:
                parts.append(f"  能力：{c.skills}")
            if c.current_status:
                parts.append(f"  状态：{c.current_status}")
            if c.current_goal:
                parts.append(f"  目的：{c.current_goal}")
            if c.last_location:
                parts.append(f"  位置：{c.last_location}")
            if c.notes:
                parts.append(f"  备注：{c.notes}")
            lines.append("\n".join(parts))
        return "\n\n".join(lines)

    @staticmethod
    def _apply_character_operations(work_id: str, operations: list[dict], db: Session):
        """Apply character-related operations from LLM output."""
        from app.models.work_model import Character

        for op in operations:
            tool = op.get("tool", "")
            args = op.get("args", {})

            if tool == "update_character":
                name = args.get("name", "")
                fields = args.get("fields", {})
                char = db.query(Character).filter_by(work_id=work_id, name=name).first()
                if char and fields:
                    for k, v in fields.items():
                        if hasattr(char, k) and k not in ("id", "work_id", "created_at", "updated_at"):
                            setattr(char, k, v)

            elif tool == "add_character":
                name = args.get("name", "")
                if name:
                    existing = db.query(Character).filter_by(work_id=work_id, name=name).first()
                    if not existing:
                        char = Character(
                            work_id=work_id,
                            name=name,
                            role_type=args.get("role_type", "配角"),
                            gender=args.get("gender", ""),
                            age=args.get("age", ""),
                            appearance=args.get("appearance", ""),
                            personality=args.get("personality", ""),
                            background=args.get("background", ""),
                            skills=args.get("skills", ""),
                            current_status=args.get("current_status", "存活"),
                            current_goal=args.get("current_goal", ""),
                            first_chapter=int(args.get("first_chapter", 1)),
                            notes=args.get("notes", ""),
                        )
                        db.add(char)

            elif tool == "delete_character":
                name = args.get("name", "")
                if name:
                    char = db.query(Character).filter_by(work_id=work_id, name=name).first()
                    if char:
                        db.delete(char)

    @staticmethod
    def _find_chapter_outline(outline_tree: dict, chapter_number: int) -> str:
        """Extract the outline info relevant to a specific chapter number."""
        timeline = outline_tree.get("timeline", [])
        branches = outline_tree.get("branches", [])

        relevant = []
        for node in timeline:
            if node.get("chapter_start", 0) <= chapter_number <= node.get("chapter_end", 0):
                summary = node.get("summary") or (node.get("mainline") if isinstance(node.get("mainline"), str) else "")
                relevant.append(f"[主线] {node.get('time_node', '')}：{node.get('development_node', '')}。{summary}（第{node['chapter_start']}-{node['chapter_end']}章）")
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
                chapter.status = "草稿"
            else:
                chapter = Chapter(
                    work_id=work_id,
                    chapter_number=chapter_number,
                    title=title or f"第{chapter_number}章",
                    content=body,
                    status="草稿",
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
            chapter.status = "已保存"
        db.commit()
        db.refresh(chapter)
        return ChapterOut.model_validate(chapter)

    # DEPRECATED: chapter_chat_edit is no longer actively called by the frontend.
    # The SupervisorAgent's edit_chapter tool uses EditChapterAgent instead.
    # This method is retained for API backward compatibility.
    def chapter_chat_edit(
        self,
        work_id: str,
        chapter_number: int,
        user_message: str,
        history: list[dict],
        db: Session,
    ) -> ChapterChatResponse:
        """Use LLM to edit chapter content via conversation (DEPRECATED — use edit_chapter via SupervisorAgent)."""
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")

        session_id = new_session_id()

        # Log user message
        log_event(db, work_id=work_id, session_id=session_id,
                  session_type="chapter_chat", role="user",
                  content=user_message, chapter_number=chapter_number)

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

        template = self._read_prompt("work_chapter_chat_edit.txt")
        prompt = PromptTemplate.from_template(template)

        chain = prompt | self.chapter_chat_model
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

            # result is already ChapterChatResponse instance
            result_dict = result.model_dump() if hasattr(result, "model_dump") else dict(result)
            assistant_message = result_dict.get("assistant_message", "已完成修改。")
            proposed_content = result_dict.get("proposed_content", current_content)
            proposed_title = result_dict.get("proposed_title")

            # Log assistant response
            log_event(db, work_id=work_id, session_id=session_id,
                      session_type="chapter_chat", role="assistant",
                      content=assistant_message, chapter_number=chapter_number,
                      meta={"proposed_title": proposed_title,
                            "proposed_content_preview": (proposed_content or "")[:300]})

            return ChapterChatResponse(
                assistant_message=assistant_message,
                proposed_content=proposed_content,
                proposed_title=proposed_title if proposed_title else None,
            )
        except HTTPException:
            raise
        except Exception as exc:  # noqa: BLE001
            log_event(db, work_id=work_id, session_id=session_id,
                      session_type="chapter_chat", role="system",
                      content=f"错误：{exc}", chapter_number=chapter_number)
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
        # Self-heal historical inconsistency: characters table vs outline_tree.characters
        chars = (
            db.query(Character)
            .filter_by(work_id=work_id)
            .order_by(Character.first_chapter.asc(), Character.created_at.asc())
            .all()
        )
        outline = work.outline_tree or {}
        outline_chars = [
            {
                "name": c.name or "",
                "role_type": c.role_type or "",
                "gender": c.gender or "",
                "age": c.age or "",
                "appearance": c.appearance or "",
                "personality": c.personality or "",
                "background": c.background or "",
                "skills": c.skills or "",
                "current_status": c.current_status or "",
                "current_goal": c.current_goal or "",
                "first_chapter": c.first_chapter or 1,
            }
            for c in chars
        ]
        if outline.get("characters") != outline_chars:
            outline["characters"] = outline_chars
            work.outline_tree = outline
            flag_modified(work, "outline_tree")
            db.commit()
            db.refresh(work)
        return WorkOut.model_validate(work)

    @staticmethod
    def delete_work(work_id: str, db: Session) -> None:
        work = db.query(Work).filter_by(id=work_id).first()
        if not work:
            raise HTTPException(status_code=404, detail="作品不存在")
        db.delete(work)
        db.commit()
