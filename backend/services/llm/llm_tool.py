from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass
class ToolCallFinished:
    tool_name: str
    call_id: str
    arguments: dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolStreamEvent:
    kind: Literal["text", "thinking", "tool_call", "tool_call_delta", "usage", "audio"]
    text: str = ""
    tool_call: ToolCallFinished | None = None
    usage: dict[str, int] | None = None
    audio: bytes = b""
    index: int | None = None
