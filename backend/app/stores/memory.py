from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from itertools import islice

from backend.app.domain.run import (
    InvalidRunTransition,
    RunFailure,
    RunRecord,
    RunStatus,
    StoredRunEvent,
)
from backend.app.stores.base import (
    AppendEventResult,
    ConcurrentWriteError,
    CreateRunResult,
    EventConflictError,
    IdempotencyConflictError,
    InvalidRunTransitionError,
    RunConflictError,
    RunNotFoundError,
)


Clock = Callable[[], datetime]


class InMemoryRunStore:
    """Single-event-loop adapter with atomic in-memory Run operations."""

    def __init__(self, *, clock: Clock | None = None) -> None:
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = asyncio.Lock()
        self._runs: dict[str, RunRecord] = {}
        self._idempotency_index: dict[tuple[str, str], str] = {}

    async def create(self, record: RunRecord) -> CreateRunResult:
        if record.status is not RunStatus.QUEUED or record.version != 0:
            raise ValueError("a new run must be queued at version zero")
        idempotency_scope = (record.owner_id, record.idempotency_key_digest)
        async with self._lock:
            existing_id = self._idempotency_index.get(idempotency_scope)
            if existing_id is not None:
                existing = self._runs[existing_id]
                if existing.request_digest != record.request_digest:
                    raise IdempotencyConflictError()
                return CreateRunResult(record=existing, created=False)
            if record.id in self._runs:
                raise RunConflictError()
            self._runs[record.id] = record
            self._idempotency_index[idempotency_scope] = record.id
            return CreateRunResult(record=record, created=True)

    async def get(
        self,
        run_id: str,
        *,
        owner_id: str,
    ) -> RunRecord | None:
        async with self._lock:
            return self._get_owned_unlocked(run_id, owner_id=owner_id)

    async def list_for_session(
        self,
        session_id: str,
        *,
        owner_id: str,
    ) -> tuple[RunRecord, ...]:
        async with self._lock:
            records = (
                record
                for record in self._runs.values()
                if record.session_id == session_id and record.owner_id == owner_id
            )
            return tuple(
                sorted(records, key=lambda record: (record.created_at, record.id))
            )

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
        if (
            not isinstance(expected_version, int)
            or isinstance(expected_version, bool)
            or expected_version < 0
        ):
            raise ValueError("expected_version must be a non-negative integer")
        async with self._lock:
            current = self._runs.get(run_id)
            if current is None or current.owner_id != owner_id:
                raise RunNotFoundError()
            if current.version != expected_version:
                raise ConcurrentWriteError()
            try:
                updated = current.transition_to(
                    target_status,
                    at=self._clock(),
                    answer=answer,
                    failure=failure,
                    error_code=error_code,
                    public_message=public_message,
                )
            except InvalidRunTransition:
                raise InvalidRunTransitionError() from None
            self._runs[run_id] = updated
            return updated

    def _get_owned_unlocked(
        self,
        run_id: str,
        *,
        owner_id: str,
    ) -> RunRecord | None:
        """Read one record while the caller owns this adapter's lock."""
        record = self._runs.get(run_id)
        if record is None or record.owner_id != owner_id:
            return None
        return record


class InMemoryEventStore:
    """Append-only, owner-aware event history for one asyncio event loop.

    The Store never waits on model, tool, network, or subscriber work while its
    lock is held. Append uses the fixed Run-lock then Event-lock order so a
    terminal transition cannot race past its final status check. Atomic Run
    transition plus terminal-event commit still belongs to a unit of work.
    """

    def __init__(
        self,
        run_store: InMemoryRunStore,
        *,
        clock: Clock | None = None,
    ) -> None:
        self._run_store = run_store
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = asyncio.Lock()
        self._events: dict[str, list[StoredRunEvent]] = {}
        self._event_ids: dict[tuple[str, str], StoredRunEvent] = {}
        self._next_sequence: dict[str, int] = {}

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
        if event_type in {"heartbeat", "run.heartbeat"}:
            raise ValueError("heartbeat events are transport-only")

        candidate = StoredRunEvent(
            id=event_id,
            run_id=run_id,
            sequence=1,
            type=event_type,
            data=dict(data),
            step=step,
            created_at=self._clock(),
        )
        event_key = (run_id, event_id)
        async with self._run_store._lock:
            run = self._run_store._get_owned_unlocked(
                run_id,
                owner_id=owner_id,
            )
            if run is None:
                raise RunNotFoundError()
            async with self._lock:
                existing = self._event_ids.get(event_key)
                if existing is not None:
                    if (
                        existing.type != candidate.type
                        or existing.step != candidate.step
                        or existing.data != candidate.data
                    ):
                        raise EventConflictError()
                    return AppendEventResult(
                        event=existing.snapshot(),
                        created=False,
                    )
                if run.status.is_terminal:
                    raise InvalidRunTransitionError()

                sequence = self._next_sequence.get(run_id, 1)
                stored = StoredRunEvent(
                    id=candidate.id,
                    run_id=run_id,
                    sequence=sequence,
                    type=candidate.type,
                    data=candidate.data,
                    step=candidate.step,
                    created_at=candidate.created_at,
                )
                self._events.setdefault(run_id, []).append(stored)
                self._event_ids[event_key] = stored
                self._next_sequence[run_id] = sequence + 1
                return AppendEventResult(event=stored.snapshot(), created=True)

    async def list_for_run(
        self,
        run_id: str,
        *,
        owner_id: str,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> tuple[StoredRunEvent, ...]:
        if (
            not isinstance(after_sequence, int)
            or isinstance(after_sequence, bool)
            or after_sequence < 0
        ):
            raise ValueError("after_sequence must be a non-negative integer")
        if (
            not isinstance(limit, int)
            or isinstance(limit, bool)
            or not 1 <= limit <= 500
        ):
            raise ValueError("limit must be between 1 and 500")
        run = await self._run_store.get(run_id, owner_id=owner_id)
        if run is None:
            return ()
        async with self._lock:
            events = self._events.get(run_id, ())
            return tuple(
                event.snapshot()
                for event in islice(
                    (
                        item
                        for item in events
                        if item.sequence > after_sequence
                    ),
                    limit,
                )
            )
