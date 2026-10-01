"""LLM 原始流日志保留完整 SSE 行。"""
import logging

from services.llm.llm_raw_log import LLMRawLog


def test_stream_line_keeps_full_sse_line(caplog):
    raw_log = LLMRawLog(provider="openai", model="glm-5.3-flash", mode="stream")
    line = "data: " + ("x" * 500)

    with caplog.at_level(logging.DEBUG, logger="llm.raw"):
        raw_log.stream_line(line)

    assert len(caplog.records) == 1
    assert line in caplog.records[0].getMessage()
