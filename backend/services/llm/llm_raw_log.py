import logging
from typing import Any

logger = logging.getLogger("llm.raw")

class LLMRawLog:
    def __init__(self, provider: str, model: str, mode: str) -> None:
        self.provider = provider
        self.model = model
        self.mode = mode

    def request(self, url: str, payload: dict[str, Any]) -> None:
        logger.debug("LLM Request [%s/%s] %s -> %s", self.provider, self.model, self.mode, url)

    def stream_line(self, line: str) -> None:
        logger.debug("LLM SSE [%s/%s] %s", self.provider, self.model, line[:200])

    def raw_response(self, content: bytes, status_code: int) -> None:
        logger.debug(f"LLM Response [{self.provider}/{self.model}] status={status_code} bytes={len(content)}")

    def finish(self) -> None:
        pass

    def fail(self, exc: Exception) -> None:
        logger.error(f"LLM Call Failed [{self.provider}/{self.model}] mode={self.mode}: {exc}")
