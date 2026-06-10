"""前端「思考中...」空档排查：统一 trace 日志。

grep 示例:
  grep UI_GAP_TRACE /path/to/backend-dev.log
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)

PREFIX = "[UI_GAP_TRACE]"


def _fmt_fields(fields: dict[str, Any]) -> str:
    if not fields:
        return ""
    parts: list[str] = []
    for key, value in fields.items():
        text = str(value)
        if len(text) > 200:
            text = text[:200] + "..."
        parts.append(f"{key}={text}")
    return " ".join(parts)


def gap_log(
    phase: str,
    *,
    session_id: str | None = None,
    t0: float | None = None,
    **fields: Any,
) -> None:
    """记录带相对耗时的排查日志。t0 为 HTTP 请求或任务启动时的 perf_counter。"""
    elapsed_ms = (time.perf_counter() - t0) * 1000 if t0 is not None else -1.0
    extra = _fmt_fields(fields)
    if elapsed_ms >= 0:
        logger.info(
            "%s session_id=%s phase=%s elapsed_ms=%.1f %s",
            PREFIX,
            session_id or "-",
            phase,
            elapsed_ms,
            extra,
        )
    else:
        logger.info(
            "%s session_id=%s phase=%s %s",
            PREFIX,
            session_id or "-",
            phase,
            extra,
        )


def gap_log_sse_emit(
    event: str,
    data: dict[str, Any] | None,
    *,
    session_id: str | None,
    t0: float,
) -> None:
    """每次向后端 queue 推送 SSE 事件时调用。"""
    payload = data or {}
    fields: dict[str, Any] = {"event": event}
    if event == "stage_start":
        fields["stage"] = payload.get("stage")
        fields["label"] = payload.get("label")
    elif event == "supervisor_stream":
        fields["stream_phase"] = payload.get("phase", "content")
        chunk = payload.get("chunk") or ""
        fields["chunk_len"] = len(chunk)
        if chunk:
            fields["chunk_preview"] = chunk[:40]
    elif event in ("write_stream", "edit_chapter_stream", "thinking_stream"):
        fields["stream_phase"] = payload.get("phase", "content")
        chunk = payload.get("chunk") or ""
        fields["chunk_len"] = len(chunk)
    elif event == "tool_executed":
        fields["tool"] = payload.get("tool")
    elif event == "error":
        fields["message"] = payload.get("message")
    gap_log("sse_emit", session_id=session_id, t0=t0, **fields)


def gap_trace_from_config(config) -> tuple[float | None, str | None]:
    """从 LangGraph RunnableConfig 读取 trace 上下文。"""
    if not config:
        return None, None
    cfg = config.get("configurable") or {}
    return cfg.get("gap_trace_t0"), cfg.get("supervisor_session_id")
