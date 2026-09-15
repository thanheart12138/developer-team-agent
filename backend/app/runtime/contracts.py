"""模型请求、结果和工具调用的运行时契约。"""

from dataclasses import dataclass, field
from typing import Callable, Literal


@dataclass
class ToolCall:
    call_id: str
    tool_name: str
    parameters: dict


@dataclass
class ToolResult:
    call_id: str
    tool_name: str
    status: Literal["succeeded", "failed"]
    output: dict = field(default_factory=dict)
    error: str | None = None


@dataclass
class ModelRequest:
    instructions: str
    input: str
    context: dict
    tools: list[dict]
    request_id: str
    on_delta: Callable[[str], None] | None = None


@dataclass
class ModelResult:
    request_id: str
    message_id: int
    text: str
    actions: list[ToolCall]
    finish_reason: Literal["completed", "tool_calls", "failed"]
    raw_response: dict = field(default_factory=dict)
