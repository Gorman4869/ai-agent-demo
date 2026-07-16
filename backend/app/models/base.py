from __future__ import annotations

from typing import Protocol, Sequence

from backend.app.domain import Message, ModelDecision
from backend.app.tools import ToolDefinition


class RetryableModelError(RuntimeError):
    """A transient provider failure that may be retried within a fixed limit."""


class ChatModel(Protocol):
    def decide(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> ModelDecision:
        """Return a final answer or one structured tool call."""
