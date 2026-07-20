from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from backend.app.domain.run import (
    RunFailure,
    RunRecord,
    RunStatus,
    StoredRunEvent,
)


class StoreError(RuntimeError):
    """Stable application-facing storage error without adapter details."""

    code = "store_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class RunNotFoundError(StoreError):
    code = "run_not_found"


class IdempotencyConflictError(StoreError):
    code = "idempotency_conflict"


class RunConflictError(StoreError):
    code = "run_conflict"


class InvalidRunTransitionError(StoreError):
    code = "invalid_run_transition"


class ConcurrentWriteError(StoreError):
    code = "concurrent_write"


class EventConflictError(StoreError):
    code = "event_conflict"


class StoreUnavailableError(StoreError):
    code = "store_unavailable"


@dataclass(frozen=True)
class CreateRunResult:
    record: RunRecord
    created: bool


@dataclass(frozen=True)
class AppendEventResult:
    event: StoredRunEvent
    created: bool


@dataclass(frozen=True)
class StartCommit:
    """One retryable command for starting a Run with its first event."""

    run_id: str
    owner_id: str
    expected_version: int
    event_id: str
    event_data: Mapping[str, object] = field(repr=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.run_id, "run_id"),
            (self.owner_id, "owner_id"),
            (self.event_id, "event_id"),
        ):
            _require_command_identifier(value, label)
        _require_expected_version(self.expected_version)
        if not isinstance(self.event_data, Mapping):
            raise ValueError("start event data must be a mapping")
        object.__setattr__(self, "event_data", dict(self.event_data))

    @property
    def event_type(self) -> str:
        return "run.started"


@dataclass(frozen=True)
class StartCommitResult:
    record: RunRecord
    event: StoredRunEvent
    created: bool


class RunStartCommitter(Protocol):
    async def commit_start(self, command: StartCommit) -> StartCommitResult:
        """Commit queued-to-running state and run.started as one operation."""
        ...


@dataclass(frozen=True)
class PauseCommit:
    """One retryable running-to-waiting approval lifecycle commit."""

    run_id: str
    owner_id: str
    expected_version: int
    event_id: str
    event_data: Mapping[str, object] = field(repr=False)
    step: int = 0

    def __post_init__(self) -> None:
        _validate_nonterminal_command(self, label="pause")

    @property
    def event_type(self) -> str:
        return "run.waiting_approval"


@dataclass(frozen=True)
class ResumeCommit:
    """One retryable waiting-to-running approval lifecycle commit."""

    run_id: str
    owner_id: str
    expected_version: int
    event_id: str
    event_data: Mapping[str, object] = field(repr=False)
    step: int = 0

    def __post_init__(self) -> None:
        _validate_nonterminal_command(self, label="resume")

    @property
    def event_type(self) -> str:
        return "run.resumed"


@dataclass(frozen=True)
class LifecycleCommitResult:
    record: RunRecord
    event: StoredRunEvent
    created: bool


class ApprovalLifecycleCommitter(Protocol):
    async def commit_pause(self, command: PauseCommit) -> LifecycleCommitResult:
        """Commit running-to-waiting and its approval event atomically."""
        ...

    async def commit_resume(self, command: ResumeCommit) -> LifecycleCommitResult:
        """Commit waiting-to-running and its resume event atomically."""
        ...


@dataclass(frozen=True)
class TerminalCommit:
    """One retryable command for atomically settling a durable Run."""

    run_id: str
    owner_id: str
    expected_version: int
    target_status: RunStatus
    event_id: str
    event_data: Mapping[str, object] = field(repr=False)
    step: int = 0
    answer: str | None = field(default=None, repr=False)
    failure: RunFailure | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.run_id, "run_id"),
            (self.owner_id, "owner_id"),
            (self.event_id, "event_id"),
        ):
            _require_command_identifier(value, label)
        _require_expected_version(self.expected_version)
        try:
            target_status = RunStatus(self.target_status)
        except (TypeError, ValueError):
            raise ValueError("terminal target status is not supported") from None
        if not target_status.is_terminal:
            raise ValueError("terminal commit requires a terminal target status")
        if (
            not isinstance(self.step, int)
            or isinstance(self.step, bool)
            or self.step < 0
        ):
            raise ValueError("terminal event step must be a non-negative integer")
        if not isinstance(self.event_data, Mapping):
            raise ValueError("terminal event data must be a mapping")
        if target_status is RunStatus.COMPLETED:
            if not isinstance(self.answer, str) or not self.answer.strip():
                raise ValueError("completed terminal commit requires an answer")
            if self.failure is not None:
                raise ValueError("completed terminal commit cannot contain a failure")
        else:
            if self.answer is not None:
                raise ValueError("failed terminal commit cannot contain an answer")
            if not isinstance(self.failure, RunFailure):
                raise ValueError("failed terminal commit requires a failure")
        object.__setattr__(self, "target_status", target_status)
        object.__setattr__(self, "event_data", dict(self.event_data))

    @property
    def event_type(self) -> str:
        return f"run.{self.target_status.value}"


@dataclass(frozen=True)
class TerminalCommitResult:
    record: RunRecord
    event: StoredRunEvent
    created: bool


class TerminalRunCommitter(Protocol):
    async def commit_terminal(
        self,
        command: TerminalCommit,
    ) -> TerminalCommitResult:
        """Commit terminal state and its matching event as one operation."""
        ...


class RunStore(Protocol):
    """Async Run persistence contract shared by memory and database adapters.

    Invalid caller values use ``ValueError``. Storage semantics use the stable
    ``StoreError`` subclasses defined in this module, never driver exceptions.
    Owner mismatch and a missing Run are deliberately indistinguishable.
    """

    async def create(self, record: RunRecord) -> CreateRunResult:
        """Create or replay a Run; idempotency conflict wins before ID conflict."""
        ...

    async def get(
        self,
        run_id: str,
        *,
        owner_id: str,
    ) -> RunRecord | None:
        """Return the owned Run, or None for missing and non-owned IDs."""
        ...

    async def list_for_session(
        self,
        session_id: str,
        *,
        owner_id: str,
    ) -> tuple[RunRecord, ...]:
        ...

    async def transition(
        self,
        run_id: str,
        *,
        owner_id: str,
        expected_version: int,
        target_status: RunStatus | str,
        answer: str | None = None,
        failure: RunFailure | None = None,
        error_code: str | None = None,
        public_message: str | None = None,
    ) -> RunRecord:
        """Apply one version-CAS transition or raise a stable Store error."""
        ...


class EventStore(
    RunStartCommitter,
    ApprovalLifecycleCommitter,
    TerminalRunCommitter,
    Protocol,
):
    """Append-only event contract; sequence and time belong to the Store.

    An Event ID replay with identical content returns the original event.
    Changed content uses ``EventConflictError``. Missing and non-owned Runs use
    ``RunNotFoundError``. A new event after a terminal Run uses
    ``InvalidRunTransitionError``; replay of an already stored progress event
    is valid. Owned lifecycle events use ``commit_start`` or
    ``commit_terminal`` instead of ordinary append.
    """

    async def append(
        self,
        *,
        event_id: str,
        run_id: str,
        owner_id: str,
        event_type: str,
        data: Mapping[str, object],
        step: int = 0,
    ) -> AppendEventResult:
        ...

    async def list_for_run(
        self,
        run_id: str,
        *,
        owner_id: str,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> tuple[StoredRunEvent, ...]:
        ...


def _require_command_identifier(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
    ):
        raise ValueError(f"{label} has an invalid format")


def _require_expected_version(value: object) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError("expected_version must be a non-negative integer")


def _validate_nonterminal_command(
    command: PauseCommit | ResumeCommit,
    *,
    label: str,
) -> None:
    for value, field_name in (
        (command.run_id, "run_id"),
        (command.owner_id, "owner_id"),
        (command.event_id, "event_id"),
    ):
        _require_command_identifier(value, field_name)
    _require_expected_version(command.expected_version)
    if (
        not isinstance(command.step, int)
        or isinstance(command.step, bool)
        or command.step < 0
    ):
        raise ValueError(f"{label} event step must be a non-negative integer")
    if not isinstance(command.event_data, Mapping):
        raise ValueError(f"{label} event data must be a mapping")
    object.__setattr__(command, "event_data", dict(command.event_data))
