from __future__ import annotations

import hashlib
from dataclasses import dataclass


class PolicyViolation(RuntimeError):
    """Reject an unsafe advanced-Agent action with a stable category."""

    def __init__(self, code: str, detail: str) -> None:
        super().__init__(detail)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class SafetyLimits:
    max_actions: int = 12
    max_input_bytes: int = 1_000_000
    max_output_bytes: int = 100_000

    def __post_init__(self) -> None:
        for field_name in ("max_actions", "max_input_bytes", "max_output_bytes"):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")


class SafetyBudget:
    """Track deterministic action and byte limits for one Agent run."""

    def __init__(self, limits: SafetyLimits | None = None) -> None:
        self._limits = limits or SafetyLimits()
        self._actions = 0
        self._input_bytes = 0
        self._output_bytes = 0

    def consume(
        self,
        *,
        actions: int = 1,
        input_bytes: int = 0,
        output_bytes: int = 0,
    ) -> None:
        usage = (actions, input_bytes, output_bytes)
        if any(isinstance(value, bool) or not isinstance(value, int) for value in usage):
            raise TypeError("budget usage must use integers")
        if any(value < 0 for value in usage):
            raise ValueError("budget usage must not be negative")
        next_actions = self._actions + actions
        next_input_bytes = self._input_bytes + input_bytes
        next_output_bytes = self._output_bytes + output_bytes
        if next_actions > self._limits.max_actions:
            raise PolicyViolation("action_budget_exceeded", "action budget exceeded")
        if next_input_bytes > self._limits.max_input_bytes:
            raise PolicyViolation("input_budget_exceeded", "input byte budget exceeded")
        if next_output_bytes > self._limits.max_output_bytes:
            raise PolicyViolation("output_budget_exceeded", "output byte budget exceeded")
        self._actions = next_actions
        self._input_bytes = next_input_bytes
        self._output_bytes = next_output_bytes

    @property
    def actions(self) -> int:
        return self._actions

    @property
    def input_bytes(self) -> int:
        return self._input_bytes

    @property
    def output_bytes(self) -> int:
        return self._output_bytes

    @property
    def remaining_output_bytes(self) -> int:
        return self._limits.max_output_bytes - self._output_bytes


def content_digest(content: bytes | str) -> str:
    payload = content.encode("utf-8") if isinstance(content, str) else content
    return hashlib.sha256(payload).hexdigest()
