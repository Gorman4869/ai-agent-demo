from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


Role = Literal["system", "user", "assistant", "tool"]


@dataclass(frozen=True)
class Message:
    role: Role
    content: str
    name: str | None = None
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelDecision:
    """Exactly one of final_answer and tool_call must be present."""

    final_answer: str | None = None
    tool_call: ToolCall | None = None

    def __post_init__(self) -> None:
        if (self.final_answer is None) == (self.tool_call is None):
            raise ValueError("ModelDecision requires exactly one outcome")


@dataclass(frozen=True)
class AgentEvent:
    type: str
    step: int
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelUsage:
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None = None

    def __post_init__(self) -> None:
        if min(self.input_tokens, self.output_tokens, self.total_tokens) < 0:
            raise ValueError("token usage must not be negative")
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total_tokens must equal input_tokens + output_tokens")
        if self.estimated_cost_usd is not None and self.estimated_cost_usd < 0:
            raise ValueError("estimated_cost_usd must not be negative")


@dataclass(frozen=True)
class AgentRunResult:
    status: Literal["completed", "failed"]
    final_answer: str | None
    messages: tuple[Message, ...]
    events: tuple[AgentEvent, ...]
    error: str | None = None
    usage: ModelUsage | None = None
