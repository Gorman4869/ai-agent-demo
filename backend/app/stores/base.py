from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
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


class EventStore(Protocol):
    """Append-only event contract; sequence and time belong to the Store.

    An Event ID replay with identical content returns the original event.
    Changed content uses ``EventConflictError``. Missing and non-owned Runs use
    ``RunNotFoundError``. A new event after a terminal Run uses
    ``InvalidRunTransitionError``; replay of an already stored event is valid.
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
