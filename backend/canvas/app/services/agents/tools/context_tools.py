"""Agent context self-management tools.

Context compaction is stored as session-level derived data. It never overwrites
node content or original conversation messages.
"""
from __future__ import annotations

import json
import re
from functools import partial
from typing import Optional

from langchain_core.tools import StructuredTool
from pydantic import BaseModel, Field

from app.config import settings
from app.models.node import Node
from app.models.session import SupervisorMessage


_CITATION_RE = re.compile(r"\[C(\d+)\]")
_ROUGH_CHARS_PER_TOKEN = 3


def _get_db():
    from app.database import SessionLocal
    return SessionLocal()


def _get_context() -> dict:
    try:
        from app.services.agents.supervisor import get_context
        return get_context()
    except Exception:
        return {}


def _current_session_id() -> str | None:
    return _get_context().get("session_id")


def _current_work_id() -> str | None:
    return _get_context().get("work_id")


def _current_model_name() -> str | None:
    pref = _get_context().get("model_pref") or {}
    return pref.get("primary") or settings.default_model


def _rough_token_count(text: str) -> int:
    return max(1, (len(text or "") + _ROUGH_CHARS_PER_TOKEN - 1) // _ROUGH_CHARS_PER_TOKEN)


def _citation_ids_in_text(text: str) -> set[str]:
    return {f"C{m.group(1)}" for m in _CITATION_RE.finditer(text or "")}


def _compact_message_for_llm(message: dict) -> str:
    meta = message.get("meta") if isinstance(message.get("meta"), dict) else {}
    context_pack_id = message.get("id", "")
    token_count = meta.get("estimated_tokens")
    citation_count = len(meta.get("citations") or [])
    header = (
        "## 已压缩的历史上下文\n"
        f"context_pack_id: {context_pack_id}\n"
        f"estimated_tokens: {token_count}\n"
        f"citation_count: {citation_count}\n\n"
        "以下内容替代压缩标记之前的原始对话历史。每条 [C...] 都可用 "
        "`resolve_context_source` 回查原始节点或消息。除非确需核对原文，"
        "不要重新读取已被压缩的长上下文。\n\n"
    )
    return header + (message.get("content") or "")


class GetContextWindowStatusInput(BaseModel):
    planned_chars: int = Field(default=0, description="预计还要注入的上下文字符数，可为 0。")
    reserved_output_tokens: int = Field(default=8000, description="计划为模型输出预留的 token 数。")
    model_name: Optional[str] = Field(default=None, description="模型名；省略时使用当前主模型。")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


class CreateContextCompactionInput(BaseModel):
    summary: str = Field(
        description=(
            "agent 自己生成的压缩上下文。重要事实必须带 [C1]、[C2] 等下标引用，"
            "每个引用都必须在 citations 中声明来源。"
        ),
    )
    citations: list[dict] = Field(
        description=(
            "引用映射列表。每项含 citation_id（如 C1）以及 source_type=node/message；"
            "node 需提供 node_id，message 需提供 message_ids。"
        ),
    )
    reason: Optional[str] = Field(default=None, description="为什么需要压缩上下文。")


class ResolveContextSourceInput(BaseModel):
    context_pack_id: Optional[str] = Field(default=None, description="压缩包 ID；省略时读取当前 session 最新压缩包。")
    citation_id: str = Field(description="要回查的引用 ID，如 C4。")
    mode: str = Field(default="excerpt", description="返回模式：summary / excerpt / full。默认 excerpt。")
    query: Optional[str] = Field(default=None, description="需要核对的关键词或问题，用于 excerpt 定位。")
    max_chars: int = Field(default=4000, description="最多返回字符数。")
    reason: Optional[str] = Field(default=None, description="调用此工具的原因（仅用于日志分析）")


def _get_context_window_status_sync(
    planned_chars=0,
    reserved_output_tokens=8000,
    model_name=None,
    reason=None,
):
    from app.services.session_store import session_store

    session_id = _current_session_id()
    effective_model = model_name or _current_model_name()
    context_limit = settings.get_model_context_window(effective_model)
    latest_usage = _get_context().get("last_llm_usage")
    if not latest_usage and session_id:
        latest_usage = session_store.latest_usage_metadata(session_id)
    last_input = int((latest_usage or {}).get("input_tokens") or 0)
    planned_tokens = _rough_token_count("x" * max(0, int(planned_chars or 0)))
    remaining = None
    over_budget = False
    if context_limit is not None:
        remaining = context_limit - last_input - int(reserved_output_tokens or 0)
        over_budget = planned_tokens > remaining

    return json.dumps({
        "success": True,
        "model": effective_model,
        "context_limit_tokens": context_limit,
        "latest_usage": latest_usage,
        "last_input_tokens": last_input,
        "reserved_output_tokens": reserved_output_tokens,
        "planned_chars": planned_chars,
        "estimated_planned_tokens": planned_tokens,
        "remaining_context_tokens": remaining,
        "over_budget": over_budget,
        "suggestion": "上下文过长，建议调用 create_context_compaction。" if over_budget else "当前预算足够。",
    }, ensure_ascii=False)


def _validate_citations(db, session_id: str, work_id: str | None, summary: str, citations: list[dict]) -> tuple[list[dict], list[str]]:
    errors: list[str] = []
    normalized: list[dict] = []
    seen: set[str] = set()

    declared_ids = set()
    for i, citation in enumerate(citations or []):
        if not isinstance(citation, dict):
            errors.append(f"citations[{i}] 必须是对象")
            continue
        cid = str(citation.get("citation_id") or "").strip()
        if not re.fullmatch(r"C\d+", cid):
            errors.append(f"citations[{i}] citation_id 必须形如 C1")
            continue
        if cid in seen:
            errors.append(f"重复 citation_id: {cid}")
            continue
        seen.add(cid)
        declared_ids.add(cid)

        source_type = str(citation.get("source_type") or "").strip()
        if source_type == "node":
            node_id = str(citation.get("node_id") or "").strip()
            node = db.query(Node).filter(Node.id == node_id).first()
            if not node:
                errors.append(f"{cid} 指向的 node 不存在: {node_id}")
                continue
            if work_id and node.work_id != work_id:
                errors.append(f"{cid} 指向的 node 不属于当前作品: {node_id}")
                continue
            normalized.append({
                "citation_id": cid,
                "source_type": "node",
                "node_id": node.id,
                "title": node.title,
                "node_type": node.type,
                "note": citation.get("note") or "",
            })
            continue

        if source_type == "message":
            ids = citation.get("message_ids") or []
            if not isinstance(ids, list) or not ids:
                errors.append(f"{cid} message 来源必须提供 message_ids")
                continue
            rows = (
                db.query(SupervisorMessage)
                .filter(SupervisorMessage.session_id == session_id)
                .filter(SupervisorMessage.id.in_([str(mid) for mid in ids]))
                .all()
            )
            found = {row.id for row in rows}
            missing = [mid for mid in ids if str(mid) not in found]
            if missing:
                errors.append(f"{cid} 指向的 message 不存在或不属于当前 session: {missing}")
                continue
            normalized.append({
                "citation_id": cid,
                "source_type": "message",
                "message_ids": [str(mid) for mid in ids],
                "note": citation.get("note") or "",
            })
            continue

        errors.append(f"{cid} source_type 只能是 node 或 message")

    used_ids = _citation_ids_in_text(summary)
    missing_mapping = sorted(used_ids - declared_ids)
    if missing_mapping:
        errors.append(f"summary 中的引用缺少 citations 映射: {missing_mapping}")

    return normalized, errors


def _create_context_compaction_sync(summary, citations, reason=None):
    from app.services.session_store import session_store

    session_id = _current_session_id()
    work_id = _current_work_id()
    if not session_id:
        return json.dumps({"success": False, "error": "当前上下文缺少 session_id"}, ensure_ascii=False)
    if not (summary or "").strip():
        return json.dumps({"success": False, "error": "summary 不能为空"}, ensure_ascii=False)

    db = _get_db()
    try:
        latest = (
            db.query(SupervisorMessage)
            .filter(SupervisorMessage.session_id == session_id)
            .order_by(SupervisorMessage.sort_order.desc())
            .first()
        )
        marker_sort_order = latest.sort_order if latest else -1
        normalized, errors = _validate_citations(db, session_id, work_id, summary, citations or [])
        if errors:
            return json.dumps({"success": False, "error": errors[0], "validation_errors": errors}, ensure_ascii=False)

        pack = session_store.add_context_compaction(
            session_id,
            content=summary,
            meta={
                "reason": reason or "",
                "marker_sort_order": marker_sort_order,
                "citations": normalized,
                "estimated_tokens": _rough_token_count(summary),
            },
            work_id=work_id,
        )
        if not pack:
            return json.dumps({"success": False, "error": "保存压缩上下文失败"}, ensure_ascii=False)
        return json.dumps({
            "success": True,
            "context_pack_id": pack["id"],
            "marker_sort_order": marker_sort_order,
            "estimated_tokens": _rough_token_count(summary),
            "citation_count": len(normalized),
            "message": "已创建压缩上下文；之后加载该 session 时，压缩点之前的历史会由此压缩包替代。",
        }, ensure_ascii=False)
    finally:
        db.close()


def _find_pack(db, session_id: str, context_pack_id: str | None):
    query = db.query(SupervisorMessage).filter(
        SupervisorMessage.session_id == session_id,
        SupervisorMessage.role == "assistant",
    )
    if context_pack_id:
        query = query.filter(SupervisorMessage.id == context_pack_id)
        row = query.first()
        if row and isinstance(row.meta, dict) and row.meta.get("type") == "context_compaction":
            return row
        return None
    rows = query.order_by(SupervisorMessage.sort_order.desc()).all()
    for row in rows:
        if isinstance(row.meta, dict) and row.meta.get("type") == "context_compaction":
            return row
    return None


def _excerpt(text: str, query: str | None, max_chars: int) -> str:
    text = text or ""
    max_chars = max(200, min(int(max_chars or 4000), 20000))
    if not query:
        return text[:max_chars]
    lower = text.lower()
    for part in str(query).split():
        idx = lower.find(part.lower())
        if idx >= 0:
            start = max(0, idx - max_chars // 2)
            end = min(len(text), start + max_chars)
            return text[start:end]
    return text[:max_chars]


def _resolve_context_source_sync(context_pack_id=None, citation_id="", mode="excerpt", query=None, max_chars=4000, reason=None):
    session_id = _current_session_id()
    if not session_id:
        return json.dumps({"success": False, "error": "当前上下文缺少 session_id"}, ensure_ascii=False)
    cid = str(citation_id or "").strip()
    db = _get_db()
    try:
        pack = _find_pack(db, session_id, context_pack_id)
        if not pack:
            return json.dumps({"success": False, "error": "未找到压缩上下文包"}, ensure_ascii=False)
        citations = (pack.meta or {}).get("citations") or []
        citation = next((c for c in citations if c.get("citation_id") == cid), None)
        if not citation:
            return json.dumps({"success": False, "error": f"压缩包中没有引用 {cid}"}, ensure_ascii=False)

        source_type = citation.get("source_type")
        if source_type == "node":
            node = db.query(Node).filter(Node.id == citation.get("node_id")).first()
            if not node:
                return json.dumps({"success": False, "error": "引用的节点已不存在"}, ensure_ascii=False)
            full = node.content or ""
            content = full if mode == "full" else _excerpt(full, query, max_chars)
            if mode == "summary":
                content = citation.get("note") or _excerpt(full, query, max_chars)
            return json.dumps({
                "success": True,
                "context_pack_id": pack.id,
                "citation_id": cid,
                "source": {"type": "node", "node_id": node.id, "node_type": node.type, "title": node.title},
                "content": content,
                "chars": len(content),
            }, ensure_ascii=False)

        if source_type == "message":
            rows = (
                db.query(SupervisorMessage)
                .filter(SupervisorMessage.session_id == session_id)
                .filter(SupervisorMessage.id.in_(citation.get("message_ids") or []))
                .order_by(SupervisorMessage.sort_order)
                .all()
            )
            full = "\n\n".join(f"{row.role}: {row.content}" for row in rows)
            content = full if mode == "full" else _excerpt(full, query, max_chars)
            if mode == "summary":
                content = citation.get("note") or _excerpt(full, query, max_chars)
            return json.dumps({
                "success": True,
                "context_pack_id": pack.id,
                "citation_id": cid,
                "source": {"type": "message", "message_ids": [row.id for row in rows]},
                "content": content,
                "chars": len(content),
            }, ensure_ascii=False)

        return json.dumps({"success": False, "error": f"不支持的 source_type: {source_type}"}, ensure_ascii=False)
    finally:
        db.close()


async def _get_context_window_status_async(planned_chars=0, reserved_output_tokens=8000, model_name=None, reason=None):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(_get_context_window_status_sync, planned_chars, reserved_output_tokens, model_name, reason),
    )


async def _create_context_compaction_async(summary, citations, reason=None):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, partial(_create_context_compaction_sync, summary, citations, reason))


async def _resolve_context_source_async(context_pack_id=None, citation_id="", mode="excerpt", query=None, max_chars=4000, reason=None):
    import asyncio
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        partial(_resolve_context_source_sync, context_pack_id, citation_id, mode, query, max_chars, reason),
    )


get_context_window_status = StructuredTool.from_function(
    coroutine=_get_context_window_status_async,
    func=_get_context_window_status_sync,
    name="get_context_window_status",
    description="查看当前模型上下文上限、最近一次 LLM usage 和预计上下文预算，决定是否需要压缩历史。",
    args_schema=GetContextWindowStatusInput,
)

create_context_compaction = StructuredTool.from_function(
    coroutine=_create_context_compaction_async,
    func=_create_context_compaction_sync,
    name="create_context_compaction",
    description=(
        "创建 session 级压缩上下文包。调用后，该压缩包会替代压缩点之前的历史；"
        "summary 中的关键信息必须带 [C1] 这类引用，并在 citations 里映射到原始 node/message。"
    ),
    args_schema=CreateContextCompactionInput,
)

resolve_context_source = StructuredTool.from_function(
    coroutine=_resolve_context_source_async,
    func=_resolve_context_source_sync,
    name="resolve_context_source",
    description="根据压缩上下文中的 [C...] 引用，按需回查原始节点或消息的摘要、摘录或全文。",
    args_schema=ResolveContextSourceInput,
)


context_tools = [
    get_context_window_status,
    create_context_compaction,
    resolve_context_source,
]
