"""项目摘要中间件：沿用 Deep Agents 的压缩事件，关闭参数截断和超窗改写。"""
from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from deepagents.backends.protocol import BackendProtocol
from deepagents.middleware.summarization import (
    SummarizationMiddleware,
    SummarizationToolMiddleware,
    _is_context_overflow,
)
from langchain.agents.middleware.types import ModelRequest, ModelResponse
from langchain_core.exceptions import ContextOverflowError
from langchain_core.language_models import BaseChatModel


class _UnrecoveredContextOverflow(Exception):
    def __init__(self, original: BaseException) -> None:
        self.original = original
        super().__init__(str(original))


class NovelSummarizationMiddleware(SummarizationMiddleware):
    """自动压缩使用公开摘要实现，但超窗时直接失败，不截断工具参数。"""

    def __init__(self, model: BaseChatModel, *, backend: BackendProtocol, on_compaction=None) -> None:
        self._on_compaction = on_compaction
        super().__init__(
            model,
            backend=backend,
            trigger=("fraction", 0.75),
            keep=("fraction", 0.10),
            trim_tokens_to_summarize=None,
            truncate_args_settings=None,
        )

    def wrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
    ) -> ModelResponse | Any:
        def guarded(req: ModelRequest) -> ModelResponse:
            try:
                return handler(req)
            except Exception as exc:
                if _is_context_overflow(exc):
                    raise _UnrecoveredContextOverflow(exc) from exc
                raise

        try:
            response = super().wrap_model_call(request, guarded)
            self._persist_compaction(response)
            return response
        except _UnrecoveredContextOverflow as wrapped:
            raise wrapped.original from wrapped

    async def awrap_model_call(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
    ) -> ModelResponse | Any:
        async def guarded(req: ModelRequest) -> ModelResponse:
            try:
                return await handler(req)
            except Exception as exc:
                if _is_context_overflow(exc):
                    raise _UnrecoveredContextOverflow(exc) from exc
                raise

        try:
            response = await super().awrap_model_call(request, guarded)
            self._persist_compaction(response)
            return response
        except _UnrecoveredContextOverflow as wrapped:
            raise wrapped.original from wrapped

    def _call_with_budget(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], ModelResponse],
        *,
        error: Exception | None = None,
        rejected: ModelRequest | None = None,
    ) -> tuple[ModelResponse, list]:
        del rejected
        self._reject_clipped_retry(request, error)
        return handler(request), []

    async def _acall_with_budget(
        self,
        request: ModelRequest,
        handler: Callable[[ModelRequest], Awaitable[ModelResponse]],
        *,
        error: Exception | None = None,
        rejected: ModelRequest | None = None,
    ) -> tuple[ModelResponse, list]:
        del rejected
        self._reject_clipped_retry(request, error)
        return await handler(request), []

    def _reject_clipped_retry(self, request: ModelRequest, error: Exception | None) -> None:
        if error is not None:
            raise error
        if self._over_budget(request):
            raise ContextOverflowError("上下文超过模型输入窗口，本次调用已停止。")

    def _persist_compaction(self, response) -> None:
        command = getattr(response, "command", None)
        update = getattr(command, "update", None)
        if self._on_compaction and isinstance(update, dict) and update.get("_summarization_event"):
            self._on_compaction(update)


class NovelSummarizationToolMiddleware(SummarizationToolMiddleware):
    def _build_compact_result(self, *args, **kwargs):
        command = super()._build_compact_result(*args, **kwargs)
        update = getattr(command, "update", None)
        callback = getattr(self._summarization, "_on_compaction", None)
        if callback and isinstance(update, dict):
            callback(update)
        return command


def build_novel_summarization_middleware(
    model: BaseChatModel,
    backend: BackendProtocol,
    *,
    on_compaction=None,
) -> tuple[NovelSummarizationMiddleware, SummarizationToolMiddleware]:
    summarization = NovelSummarizationMiddleware(
        model, backend=backend, on_compaction=on_compaction,
    )
    return summarization, NovelSummarizationToolMiddleware(summarization, system_prompt=None)
