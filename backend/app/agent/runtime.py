from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from backend.app.agent.cancellation import CancellationToken
from backend.app.domain.run import RunFailure, RunStatus
from backend.app.tools import ToolExecutionContext


_EVENT_TYPE_PATTERN = re.compile(
    r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+"
)
_TERMINAL_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
)


@dataclass(frozen=True)
class RuntimeRequest:
    """One content-bearing command passed from the coordinator to a Runtime."""

    run_id: str
    input_text: str = field(repr=False)
    execution_context: ToolExecutionContext | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        if (
            not isinstance(self.run_id, str)
            or not self.run_id
            or self.run_id != self.run_id.strip()
            or len(self.run_id) > 200
        ):
            raise ValueError("run_id has an invalid format")
        if not isinstance(self.input_text, str) or not self.input_text.strip():
            raise ValueError("input_text must not be empty")


@dataclass(frozen=True)
class RuntimeControl:
    """Cooperative signals shared with one Runtime invocation."""

    cancellation_token: CancellationToken = field(repr=False, compare=False)


@dataclass(frozen=True)
class RuntimeEvent:
    """A non-lifecycle event awaiting persistence by the application layer."""

    type: str
    step: int
    data: Mapping[str, object] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.type, str)
            or _EVENT_TYPE_PATTERN.fullmatch(self.type) is None
        ):
            raise ValueError("runtime event type has an invalid format")
        if self.type.startswith("run."):
            raise ValueError("run lifecycle events belong to the coordinator")
        if (
            not isinstance(self.step, int)
            or isinstance(self.step, bool)
            or self.step < 0
        ):
            raise ValueError("runtime event step must be a non-negative integer")
        if not isinstance(self.data, Mapping):
            raise ValueError("runtime event data must be a mapping")
        object.__setattr__(self, "data", dict(self.data))


@dataclass(frozen=True)
class RuntimeResult:
    """Normalized terminal outcome independent of any model SDK."""

    status: RunStatus
    answer: str | None = field(default=None, repr=False)
    failure: RunFailure | None = field(default=None, repr=False)
    step: int = 0

    def __post_init__(self) -> None:
        try:
            status = RunStatus(self.status)
        except (TypeError, ValueError):
            raise ValueError("runtime result status is not supported") from None
        if status not in _TERMINAL_STATUSES:
            raise ValueError("runtime result must be terminal")
        if (
            not isinstance(self.step, int)
            or isinstance(self.step, bool)
            or self.step < 0
        ):
            raise ValueError("runtime result step must be a non-negative integer")
        if status is RunStatus.COMPLETED:
            if not isinstance(self.answer, str) or not self.answer.strip():
                raise ValueError("completed runtime result requires an answer")
            if self.failure is not None:
                raise ValueError("completed runtime result must not contain a failure")
        else:
            if self.answer is not None:
                raise ValueError("failed runtime result must not contain an answer")
            if self.failure is None:
                raise ValueError("failed runtime result requires a failure")
        object.__setattr__(self, "status", status)


class RuntimeEventSink(Protocol):
    async def __call__(self, event: RuntimeEvent) -> None:
        ...


class AgentRuntime(Protocol):
    async def run(
        self,
        request: RuntimeRequest,
        *,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeResult:
        ...


__all__ = [
    "AgentRuntime",
    "RuntimeControl",
    "RuntimeEvent",
    "RuntimeEventSink",
    "RuntimeRequest",
    "RuntimeResult",
]
