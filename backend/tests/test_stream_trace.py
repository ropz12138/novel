"""UI_GAP_TRACE 日志 helper 单元测试。"""

from __future__ import annotations

import logging

from app.services.stream_trace import (
    PREFIX,
    gap_log,
    gap_log_sse_emit,
    gap_trace_from_config,
)


def test_gap_log_includes_prefix_and_fields(caplog):
    caplog.set_level(logging.INFO)
    gap_log("http_start", t0=0.0, route="start", message_len=12)
    assert any(PREFIX in rec.message and "phase=http_start" in rec.message for rec in caplog.records)


def test_gap_log_sse_emit_stage_start(caplog):
    caplog.set_level(logging.INFO)
    gap_log_sse_emit(
        "stage_start",
        {"stage": "thinking", "label": "AI 思考中"},
        session_id="sess-1",
        t0=0.0,
    )
    msg = caplog.records[-1].message
    assert PREFIX in msg
    assert "event=stage_start" in msg
    assert "stage=thinking" in msg
    assert "label=AI 思考中" in msg


def test_gap_log_sse_emit_supervisor_stream(caplog):
    caplog.set_level(logging.INFO)
    gap_log_sse_emit(
        "supervisor_stream",
        {"chunk": "你好", "phase": "reasoning"},
        session_id="sess-2",
        t0=0.0,
    )
    msg = caplog.records[-1].message
    assert "stream_phase=reasoning" in msg
    assert "chunk_len=2" in msg


def test_gap_trace_from_config():
    t0, session_id = gap_trace_from_config(
        {"configurable": {"gap_trace_t0": 1.23, "supervisor_session_id": "abc"}}
    )
    assert t0 == 1.23
    assert session_id == "abc"

    t0_none, session_none = gap_trace_from_config(None)
    assert t0_none is None
    assert session_none is None
