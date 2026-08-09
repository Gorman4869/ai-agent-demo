from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Protocol, runtime_checkable

from backend.app.agent.cancellation import CancellationToken
from backend.app.domain.run import RunFailure, RunStatus
from backend.app.tools import ToolExecutionContext


_EVENT_TYPE_PATTERN = re.compile(
    r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+"
)
_TERMINAL_STATUSES = frozenset(
    {RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED}
)
_MAX_PROMPT_CONTEXT_BYTES = 32_000
_CHECKPOINT_OWNER_PATTERN = re.compile(r"runtime-owner-v1-[0-9a-f]{64}")
_CHECKPOINT_THREAD_PATTERN = re.compile(r"runtime-thread-v1-[0-9a-f]{64}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _require_runtime_identifier(value: str, *, field_name: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
    ):
        raise ValueError(f"{field_name} has an invalid format")
    return value


def _require_runtime_scope_identifier(
    value: str,
    *,
    field_name: str,
) -> str:
    checked = _require_runtime_identifier(value, field_name=field_name)
    if any(
        character.isspace() or not character.isprintable()
        for character in checked
    ):
        raise ValueError(f"{field_name} has an invalid format")
    return checked


def _checkpoint_digest(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, byteorder="big"))
        digest.update(encoded)
    return digest.hexdigest()


def _validate_prompt_context(prompt_context: str | None) -> str | None:
    if prompt_context is None:
        return None
    if (
        not isinstance(prompt_context, str)
        or not prompt_context.strip()
        or len(prompt_context.encode("utf-8")) > _MAX_PROMPT_CONTEXT_BYTES
        or any(
            not character.isprintable() and character not in "\r\n\t"
            for character in prompt_context
        )
    ):
        raise ValueError("prompt_context has an invalid format")
    return prompt_context


@dataclass(frozen=True)
class RuntimeCheckpointContext:
    """Trusted owner and thread binding for one checkpointed run."""

    owner_scope: str = field(repr=False)
    thread_id: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.owner_scope, str)
            or _CHECKPOINT_OWNER_PATTERN.fullmatch(self.owner_scope) is None
        ):
            raise ValueError("owner_scope has an invalid format")
        if (
            not isinstance(self.thread_id, str)
            or _CHECKPOINT_THREAD_PATTERN.fullmatch(self.thread_id) is None
        ):
            raise ValueError("thread_id has an invalid format")

    @classmethod
    def for_run(cls, *, run_id: str, owner_id: str) -> RuntimeCheckpointContext:
        checked_run_id = _require_runtime_identifier(
            run_id,
            field_name="run_id",
        )
        checked_owner_id = _require_runtime_identifier(
            owner_id,
            field_name="owner_id",
        )
        owner_digest = _checkpoint_digest(
            "runtime-owner-v1",
            checked_owner_id,
        )
        owner_scope = f"runtime-owner-v1-{owner_digest}"
        thread_digest = _checkpoint_digest(
            "runtime-thread-v1",
            owner_scope,
            checked_run_id,
        )
        return cls(
            owner_scope=owner_scope,
            thread_id=f"runtime-thread-v1-{thread_digest}",
        )

    def belongs_to(self, run_id: str) -> bool:
        checked_run_id = _require_runtime_identifier(
            run_id,
            field_name="run_id",
        )
        expected_digest = _checkpoint_digest(
            "runtime-thread-v1",
            self.owner_scope,
            checked_run_id,
        )
        return hmac.compare_digest(
            self.thread_id,
            f"runtime-thread-v1-{expected_digest}",
        )

    def belongs_to_owner(self, owner_id: str) -> bool:
        checked_owner_id = _require_runtime_identifier(
            owner_id,
            field_name="owner_id",
        )
        expected_digest = _checkpoint_digest(
            "runtime-owner-v1",
            checked_owner_id,
        )
        return hmac.compare_digest(
            self.owner_scope,
            f"runtime-owner-v1-{expected_digest}",
        )


@dataclass(frozen=True)
class RuntimeContextIdentity:
    """Trusted owner and session identity for application context lookup."""

    owner_id: str = field(repr=False)
    session_id: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_runtime_scope_identifier(
            self.owner_id,
            field_name="context owner_id",
        )
        _require_runtime_scope_identifier(
            self.session_id,
            field_name="context session_id",
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
    prompt_context: str | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    checkpoint_context: RuntimeCheckpointContext | None = field(
        default=None,
        repr=False,
        compare=False,
    )
    context_identity: RuntimeContextIdentity | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        _require_runtime_identifier(self.run_id, field_name="run_id")
        if not isinstance(self.input_text, str) or not self.input_text.strip():
            raise ValueError("input_text must not be empty")
        _validate_prompt_context(self.prompt_context)
        if self.checkpoint_context is not None:
            if not isinstance(
                self.checkpoint_context,
                RuntimeCheckpointContext,
            ):
                raise ValueError("checkpoint_context has an invalid format")
            if not self.checkpoint_context.belongs_to(self.run_id):
                raise ValueError("checkpoint_context does not belong to run_id")
        if self.context_identity is not None:
            if not isinstance(self.context_identity, RuntimeContextIdentity):
                raise ValueError("context_identity has an invalid format")
            if (
                self.checkpoint_context is not None
                and not self.checkpoint_context.belongs_to_owner(
                    self.context_identity.owner_id
                )
            ):
                raise ValueError(
                    "context_identity does not match checkpoint owner"
                )


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


class RuntimeApprovalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True)
class RuntimeApprovalPause:
    """Safe metadata for one server-owned approval interrupt."""

    approval_id: str
    tool_call_id: str
    tool_name: str
    arguments_digest: str = field(repr=False)
    expires_at: datetime | None = None
    step: int = 0

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.approval_id, "approval_id"),
            (self.tool_call_id, "tool_call_id"),
            (self.tool_name, "tool_name"),
        ):
            _require_runtime_identifier(value, field_name=field_name)
        if (
            not isinstance(self.arguments_digest, str)
            or _SHA256_PATTERN.fullmatch(self.arguments_digest) is None
        ):
            raise ValueError("arguments_digest has an invalid format")
        if self.expires_at is not None and (
            not isinstance(self.expires_at, datetime)
            or self.expires_at.tzinfo is None
            or self.expires_at.utcoffset() is None
        ):
            raise ValueError("expires_at must be timezone-aware")
        if (
            not isinstance(self.step, int)
            or isinstance(self.step, bool)
            or self.step < 0
        ):
            raise ValueError("approval pause step must be a non-negative integer")
        if self.expires_at is not None:
            object.__setattr__(self, "expires_at", self.expires_at.astimezone(UTC))


@dataclass(frozen=True)
class RuntimeApprovalResume:
    """Server-resolved decision passed to a resumable Runtime."""

    approval_id: str
    tool_call_id: str
    tool_name: str
    arguments_digest: str = field(repr=False)
    decision: RuntimeApprovalDecision

    def __post_init__(self) -> None:
        for value, field_name in (
            (self.approval_id, "approval_id"),
            (self.tool_call_id, "tool_call_id"),
            (self.tool_name, "tool_name"),
        ):
            _require_runtime_identifier(value, field_name=field_name)
        if (
            not isinstance(self.arguments_digest, str)
            or _SHA256_PATTERN.fullmatch(self.arguments_digest) is None
        ):
            raise ValueError("arguments_digest has an invalid format")
        try:
            decision = RuntimeApprovalDecision(self.decision)
        except (TypeError, ValueError):
            raise ValueError("approval decision is not supported") from None
        object.__setattr__(self, "decision", decision)


RuntimeOutcome = RuntimeResult | RuntimeApprovalPause


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
    ) -> RuntimeOutcome:
        ...


@runtime_checkable
class ApprovalResumableRuntime(AgentRuntime, Protocol):
    async def resume(
        self,
        request: RuntimeRequest,
        *,
        approval: RuntimeApprovalResume,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeOutcome:
        ...


__all__ = [
    "AgentRuntime",
    "ApprovalResumableRuntime",
    "RuntimeApprovalDecision",
    "RuntimeApprovalPause",
    "RuntimeApprovalResume",
    "RuntimeCheckpointContext",
    "RuntimeContextIdentity",
    "RuntimeControl",
    "RuntimeEvent",
    "RuntimeEventSink",
    "RuntimeOutcome",
    "RuntimeRequest",
    "RuntimeResult",
]
