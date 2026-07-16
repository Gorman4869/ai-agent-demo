from __future__ import annotations

from collections import deque
from typing import Iterable, Sequence

from backend.app.domain import Message, ModelDecision
from backend.app.tools import ToolDefinition


class MockModel:
    """A deterministic model adapter used for learning and offline tests."""

    def __init__(self, decisions: Iterable[ModelDecision]) -> None:
        self._decisions = deque(decisions)

    def decide(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> ModelDecision:
        del messages, tools
        if not self._decisions:
            raise RuntimeError("MockModel has no scripted decision left")
        return self._decisions.popleft()
