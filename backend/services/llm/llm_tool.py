from dataclasses import dataclass, field
import json
import inspect
from typing import Any, Callable, Literal

@dataclass
class ToolCallFinished:
    tool_name: str
    call_id: str
    arguments: dict[str, Any] = field(default_factory=dict)

@dataclass
class ToolCallResult:
    tool_name: str
    content: str
    is_error: bool = False
    error_message: str | None = None
    pause_agent: bool = False

    def to_json_content(self) -> str:
        if self.is_error:
            return json.dumps({"status": "error", "error": self.error_message or self.content}, ensure_ascii=False)
        return self.content

@dataclass
class ToolStreamEvent:
    kind: Literal["text", "thinking", "tool_call"]
    text: str = ""
    tool_call: ToolCallFinished | None = None

@dataclass
class ToolLoopEvent:
    kind: Literal["text", "thinking", "tool_call", "tool_result", "interaction_required"]
    text: str = ""
    tool_call: ToolCallFinished | None = None
    tool_result: ToolCallResult | None = None

def build_tool_error_result(tool_name: str, error_message: str) -> ToolCallResult:
    return ToolCallResult(
        tool_name=tool_name,
        content=json.dumps({"error": error_message}, ensure_ascii=False),
        is_error=True,
        error_message=error_message,
    )

class ToolRegistry:
    """工具注册中心，用于管理和执行 Agent 工具。"""

    def __init__(self) -> None:
        self._tools: dict[str, Callable[..., Any]] = {}
        self._schemas: dict[str, dict[str, Any]] = {}

    def register(self, name: str, description: str, parameters: dict[str, Any], handler: Callable[..., Any]) -> None:
        self._tools[name] = handler
        self._schemas[name] = {
            "type": "function",
            "function": {
                "name": name,
                "description": description,
                "parameters": parameters,
            },
        }

    def get_openai_tools(self) -> list[dict[str, Any]]:
        return list(self._schemas.values())

    async def execute(self, name: str, arguments: dict[str, Any], call_id: str = "") -> ToolCallResult:
        if name not in self._tools:
            return build_tool_error_result(name, f"未找到工具: {name}")
        handler = self._tools[name]
        try:
            if inspect.iscoroutinefunction(handler):
                result = await handler(**arguments)
            else:
                result = handler(**arguments)

            if isinstance(result, ToolCallResult):
                return result

            content_str = json.dumps(result, ensure_ascii=False) if not isinstance(result, str) else result
            return ToolCallResult(tool_name=name, content=content_str)
        except Exception as exc:
            return build_tool_error_result(name, f"执行工具 {name} 出错: {exc}")
