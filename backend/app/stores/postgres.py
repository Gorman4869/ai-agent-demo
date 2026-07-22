from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any

from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from psycopg import AsyncConnection, Error as PsycopgError
from psycopg.rows import DictRow, dict_row
from psycopg.types.json import Jsonb
from psycopg_pool import AsyncConnectionPool, PoolTimeout

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
    LifecycleCommitResult,
    PauseCommit,
    ResumeCommit,
    RunConflictError,
    RunNotFoundError,
    StartCommit,
    StartCommitResult,
    StoreError,
    StoreUnavailableError,
    TerminalCommit,
    TerminalCommitResult,
)
from backend.app.stores.postgres_migrations import apply_postgres_migrations


Clock = Callable[[], datetime]
Pool = AsyncConnectionPool[AsyncConnection[DictRow]]

_RUN_COLUMNS = """
    id,
    session_id,
    owner_id,
    runtime,
    model_provider,
    model,
    input_text,
    idempotency_key_digest,
    request_digest,
    status,
    version,
    created_at,
    updated_at,
    started_at,
    finished_at,
    answer,
    failure_code,
    failure_category,
    failure_message,
    failure_retryable,
    failure_internal_ref,
    failure_step
"""


class PostgresPersistence:
    """Own one async pool shared by Stores and the LangGraph checkpointer."""

    def __init__(self, pool: Pool, *, clock: Clock | None = None) -> None:
        self.pool = pool
        self.run_store = PostgresRunStore(pool, clock=clock)
        self.event_store = PostgresEventStore(
            self.run_store,
            pool,
            clock=clock,
        )
        self.checkpointer = AsyncPostgresSaver(pool)

    @classmethod
    async def open(
        cls,
        conninfo: str,
        *,
        clock: Clock | None = None,
        min_size: int = 1,
        max_size: int = 4,
        timeout: float = 10.0,
    ) -> PostgresPersistence:
        if not isinstance(conninfo, str) or not conninfo.strip():
            raise ValueError("PostgreSQL conninfo must not be empty")
        pool: Pool = AsyncConnectionPool(
            conninfo=conninfo,
            min_size=min_size,
            max_size=max_size,
            open=False,
            timeout=timeout,
            kwargs={
                "autocommit": True,
                "prepare_threshold": 0,
                "row_factory": dict_row,
            },
        )
        try:
            await pool.open(wait=True, timeout=timeout)
        except asyncio.CancelledError:
            raise
        except (PsycopgError, PoolTimeout, OSError):
            await pool.close()
            raise StoreUnavailableError() from None
        return cls(pool, clock=clock)

    async def setup(self) -> None:
        await apply_postgres_migrations(self.pool)
        try:
            await self.checkpointer.setup()
        except asyncio.CancelledError:
            raise
        except PsycopgError:
            raise StoreUnavailableError() from None

    async def close(self) -> None:
        await self.pool.close()

    async def __aenter__(self) -> PostgresPersistence:
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


class PostgresRunStore:
    def __init__(self, pool: Pool, *, clock: Clock | None = None) -> None:
        self._pool = pool
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create(self, record: RunRecord) -> CreateRunResult:
        if record.status is not RunStatus.QUEUED or record.version != 0:
            raise ValueError("a new run must be queued at version zero")
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    result = await connection.execute(
                        f"""
                        INSERT INTO agent_runs ({_RUN_COLUMNS})
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT DO NOTHING
                        RETURNING {_RUN_COLUMNS}
                        """,
                        _run_parameters(record),
                    )
                    row = await result.fetchone()
                    if row is not None:
                        await connection.execute(
                            """
                            INSERT INTO agent_run_event_sequences (
                                run_id,
                                next_sequence
                            ) VALUES (%s, 1)
                            """,
                            (record.id,),
                        )
                        return CreateRunResult(
                            record=_row_to_run(row),
                            created=True,
                        )

                    existing_result = await connection.execute(
                        f"""
                        SELECT {_RUN_COLUMNS}
                        FROM agent_runs
                        WHERE owner_id = %s
                          AND idempotency_key_digest = %s
                        """,
                        (record.owner_id, record.idempotency_key_digest),
                    )
                    existing = await existing_result.fetchone()
                    if existing is not None:
                        existing_record = _row_to_run(existing)
                        if existing_record.request_digest != record.request_digest:
                            raise IdempotencyConflictError()
                        return CreateRunResult(
                            record=existing_record,
                            created=False,
                        )

                    id_result = await connection.execute(
                        "SELECT 1 FROM agent_runs WHERE id = %s",
                        (record.id,),
                    )
                    if await id_result.fetchone() is not None:
                        raise RunConflictError()
                    raise StoreUnavailableError()
        except StoreError:
            raise
        except asyncio.CancelledError:
            raise
        except PsycopgError:
            raise StoreUnavailableError() from None

    async def get(
        self,
        run_id: str,
        *,
        owner_id: str,
    ) -> RunRecord | None:
        try:
            async with self._pool.connection() as connection:
                result = await connection.execute(
                    f"""
                    SELECT {_RUN_COLUMNS}
                    FROM agent_runs
                    WHERE id = %s AND owner_id = %s
                    """,
                    (run_id, owner_id),
                )
                row = await result.fetchone()
                return _row_to_run(row) if row is not None else None
        except asyncio.CancelledError:
            raise
        except PsycopgError:
            raise StoreUnavailableError() from None

    async def list_for_session(
        self,
        session_id: str,
        *,
        owner_id: str,
    ) -> tuple[RunRecord, ...]:
        try:
            async with self._pool.connection() as connection:
                result = await connection.execute(
                    f"""
                    SELECT {_RUN_COLUMNS}
                    FROM agent_runs
                    WHERE session_id = %s AND owner_id = %s
                    ORDER BY created_at, id
                    """,
                    (session_id, owner_id),
                )
                return tuple(_row_to_run(row) for row in await result.fetchall())
        except asyncio.CancelledError:
            raise
        except PsycopgError:
            raise StoreUnavailableError() from None

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
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    current = await _select_owned_run_for_update(
                        connection,
                        run_id=run_id,
                        owner_id=owner_id,
                    )
                    if current is None:
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
                    await _update_run(connection, updated)
                    return updated
        except StoreError:
            raise
        except asyncio.CancelledError:
            raise
        except PsycopgError:
            raise StoreUnavailableError() from None


class PostgresEventStore:
    def __init__(
        self,
        run_store: PostgresRunStore,
        pool: Pool,
        *,
        clock: Clock | None = None,
    ) -> None:
        if run_store._pool is not pool:
            raise ValueError("PostgreSQL Run and Event Stores must share one pool")
        self._run_store = run_store
        self._pool = pool
        self._clock = clock or (lambda: datetime.now(UTC))

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
        if event_type == "run.started":
            raise ValueError("run.started requires commit_start")
        if event_type in {"run.completed", "run.failed", "run.cancelled"}:
            raise ValueError("terminal lifecycle events require commit_terminal")
        if event_type == "run.waiting_approval":
            raise ValueError("run.waiting_approval requires commit_pause")
        if event_type == "run.resumed":
            raise ValueError("run.resumed requires commit_resume")
        candidate = _event_candidate(
            event_id=event_id,
            run_id=run_id,
            event_type=event_type,
            data=data,
            step=step,
            created_at=self._clock(),
        )
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    run = await _select_owned_run_for_update(
                        connection,
                        run_id=run_id,
                        owner_id=owner_id,
                    )
                    if run is None:
                        raise RunNotFoundError()
                    existing = await _select_event(
                        connection,
                        run_id=run_id,
                        event_id=event_id,
                    )
                    if existing is not None:
                        if not _event_content_matches(existing, candidate):
                            raise EventConflictError()
                        return AppendEventResult(event=existing, created=False)
                    if run.status.is_terminal:
                        raise InvalidRunTransitionError()
                    stored = await _insert_event(connection, candidate)
                    return AppendEventResult(event=stored, created=True)
        except StoreError:
            raise
        except asyncio.CancelledError:
            raise
        except PsycopgError:
            raise StoreUnavailableError() from None

    async def commit_start(self, command: StartCommit) -> StartCommitResult:
        record, event, created = await self._commit_lifecycle(
            command,
            target_status=RunStatus.RUNNING,
        )
        return StartCommitResult(record=record, event=event, created=created)

    async def commit_pause(self, command: PauseCommit) -> LifecycleCommitResult:
        record, event, created = await self._commit_lifecycle(
            command,
            target_status=RunStatus.WAITING_APPROVAL,
        )
        return LifecycleCommitResult(record=record, event=event, created=created)

    async def commit_resume(self, command: ResumeCommit) -> LifecycleCommitResult:
        record, event, created = await self._commit_lifecycle(
            command,
            target_status=RunStatus.RUNNING,
        )
        return LifecycleCommitResult(record=record, event=event, created=created)

    async def commit_terminal(
        self,
        command: TerminalCommit,
    ) -> TerminalCommitResult:
        record, event, created = await self._commit_lifecycle(
            command,
            target_status=command.target_status,
        )
        return TerminalCommitResult(record=record, event=event, created=created)

    async def _commit_lifecycle(
        self,
        command: StartCommit | PauseCommit | ResumeCommit | TerminalCommit,
        *,
        target_status: RunStatus,
    ) -> tuple[RunRecord, StoredRunEvent, bool]:
        candidate = _event_candidate(
            event_id=command.event_id,
            run_id=command.run_id,
            event_type=command.event_type,
            data=command.event_data,
            step=getattr(command, "step", 0),
            created_at=self._clock(),
        )
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    current = await _select_owned_run_for_update(
                        connection,
                        run_id=command.run_id,
                        owner_id=command.owner_id,
                    )
                    if current is None:
                        raise RunNotFoundError()
                    existing = await _select_event(
                        connection,
                        run_id=command.run_id,
                        event_id=command.event_id,
                    )
                    if existing is not None:
                        if not _lifecycle_replay_matches(
                            command,
                            current=current,
                            existing=existing,
                            candidate=candidate,
                            target_status=target_status,
                        ):
                            raise EventConflictError()
                        return current, existing, False
                    if current.version != command.expected_version:
                        raise ConcurrentWriteError()
                    try:
                        updated = current.transition_to(
                            target_status,
                            at=candidate.created_at,
                            answer=(
                                command.answer
                                if isinstance(command, TerminalCommit)
                                else None
                            ),
                            failure=(
                                command.failure
                                if isinstance(command, TerminalCommit)
                                else None
                            ),
                        )
                    except InvalidRunTransition:
                        raise InvalidRunTransitionError() from None
                    await _update_run(connection, updated)
                    stored = await _insert_event(connection, candidate)
                    return updated, stored, True
        except StoreError:
            raise
        except asyncio.CancelledError:
            raise
        except PsycopgError:
            raise StoreUnavailableError() from None

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
        try:
            async with self._pool.connection() as connection:
                run_result = await connection.execute(
                    "SELECT 1 FROM agent_runs WHERE id = %s AND owner_id = %s",
                    (run_id, owner_id),
                )
                if await run_result.fetchone() is None:
                    return ()
                result = await connection.execute(
                    """
                    SELECT id, run_id, sequence, type, data, step, created_at
                    FROM agent_run_events
                    WHERE run_id = %s AND sequence > %s
                    ORDER BY sequence
                    LIMIT %s
                    """,
                    (run_id, after_sequence, limit),
                )
                return tuple(_row_to_event(row) for row in await result.fetchall())
        except asyncio.CancelledError:
            raise
        except PsycopgError:
            raise StoreUnavailableError() from None


async def _select_owned_run_for_update(
    connection: AsyncConnection[DictRow],
    *,
    run_id: str,
    owner_id: str,
) -> RunRecord | None:
    result = await connection.execute(
        f"""
        SELECT {_RUN_COLUMNS}
        FROM agent_runs
        WHERE id = %s AND owner_id = %s
        FOR UPDATE
        """,
        (run_id, owner_id),
    )
    row = await result.fetchone()
    return _row_to_run(row) if row is not None else None


async def _update_run(
    connection: AsyncConnection[DictRow],
    record: RunRecord,
) -> None:
    await connection.execute(
        """
        UPDATE agent_runs
        SET status = %s,
            version = %s,
            updated_at = %s,
            started_at = %s,
            finished_at = %s,
            answer = %s,
            failure_code = %s,
            failure_category = %s,
            failure_message = %s,
            failure_retryable = %s,
            failure_internal_ref = %s,
            failure_step = %s
        WHERE id = %s
        """,
        (
            record.status.value,
            record.version,
            record.updated_at,
            record.started_at,
            record.finished_at,
            record.answer,
            record.failure.code if record.failure is not None else None,
            record.failure.category if record.failure is not None else None,
            (
                record.failure.public_message
                if record.failure is not None
                else None
            ),
            record.failure.retryable if record.failure is not None else None,
            record.failure.internal_ref if record.failure is not None else None,
            record.failure.step if record.failure is not None else None,
            record.id,
        ),
    )


async def _select_event(
    connection: AsyncConnection[DictRow],
    *,
    run_id: str,
    event_id: str,
) -> StoredRunEvent | None:
    result = await connection.execute(
        """
        SELECT id, run_id, sequence, type, data, step, created_at
        FROM agent_run_events
        WHERE run_id = %s AND id = %s
        """,
        (run_id, event_id),
    )
    row = await result.fetchone()
    return _row_to_event(row) if row is not None else None


async def _insert_event(
    connection: AsyncConnection[DictRow],
    candidate: StoredRunEvent,
) -> StoredRunEvent:
    sequence_result = await connection.execute(
        """
        UPDATE agent_run_event_sequences
        SET next_sequence = next_sequence + 1
        WHERE run_id = %s
        RETURNING next_sequence - 1 AS sequence
        """,
        (candidate.run_id,),
    )
    sequence_row = await sequence_result.fetchone()
    if sequence_row is None:
        raise StoreUnavailableError()
    stored = StoredRunEvent(
        id=candidate.id,
        run_id=candidate.run_id,
        sequence=sequence_row["sequence"],
        type=candidate.type,
        data=candidate.data,
        step=candidate.step,
        created_at=candidate.created_at,
    )
    await connection.execute(
        """
        INSERT INTO agent_run_events (
            id,
            run_id,
            sequence,
            type,
            data,
            step,
            created_at
        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
        """,
        (
            stored.id,
            stored.run_id,
            stored.sequence,
            stored.type,
            Jsonb(stored.data),
            stored.step,
            stored.created_at,
        ),
    )
    return stored


def _event_candidate(
    *,
    event_id: str,
    run_id: str,
    event_type: str,
    data: Mapping[str, object],
    step: int,
    created_at: datetime,
) -> StoredRunEvent:
    return StoredRunEvent(
        id=event_id,
        run_id=run_id,
        sequence=1,
        type=event_type,
        data=dict(data),
        step=step,
        created_at=created_at,
    )


def _event_content_matches(
    existing: StoredRunEvent,
    candidate: StoredRunEvent,
) -> bool:
    return (
        existing.type == candidate.type
        and existing.step == candidate.step
        and existing.data == candidate.data
    )


def _lifecycle_replay_matches(
    command: StartCommit | PauseCommit | ResumeCommit | TerminalCommit,
    *,
    current: RunRecord,
    existing: StoredRunEvent,
    candidate: StoredRunEvent,
    target_status: RunStatus,
) -> bool:
    if not _event_content_matches(existing, candidate):
        return False
    if isinstance(command, StartCommit):
        return (
            current.status is not RunStatus.QUEUED
            and current.version >= command.expected_version + 1
            and current.started_at is not None
        )
    if isinstance(command, TerminalCommit):
        return (
            current.status is target_status
            and current.version == command.expected_version + 1
            and current.answer == command.answer
            and current.failure == command.failure
        )
    return current.version >= command.expected_version + 1


def _run_parameters(record: RunRecord) -> tuple[object, ...]:
    failure = record.failure
    return (
        record.id,
        record.session_id,
        record.owner_id,
        record.runtime,
        record.model_provider,
        record.model,
        record.input_text,
        record.idempotency_key_digest,
        record.request_digest,
        record.status.value,
        record.version,
        record.created_at,
        record.updated_at,
        record.started_at,
        record.finished_at,
        record.answer,
        failure.code if failure is not None else None,
        failure.category if failure is not None else None,
        failure.public_message if failure is not None else None,
        failure.retryable if failure is not None else None,
        failure.internal_ref if failure is not None else None,
        failure.step if failure is not None else None,
    )


def _row_to_run(row: Mapping[str, Any]) -> RunRecord:
    failure = None
    if row["failure_code"] is not None:
        failure = RunFailure(
            code=row["failure_code"],
            category=row["failure_category"],
            public_message=row["failure_message"],
            retryable=row["failure_retryable"],
            internal_ref=row["failure_internal_ref"],
            step=row["failure_step"],
        )
    return RunRecord(
        id=row["id"],
        session_id=row["session_id"],
        owner_id=row["owner_id"],
        runtime=row["runtime"],
        model_provider=row["model_provider"],
        model=row["model"],
        input_text=row["input_text"],
        idempotency_key_digest=row["idempotency_key_digest"].strip(),
        request_digest=row["request_digest"].strip(),
        status=row["status"],
        version=row["version"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        answer=row["answer"],
        failure=failure,
    )


def _row_to_event(row: Mapping[str, Any]) -> StoredRunEvent:
    return StoredRunEvent(
        id=row["id"],
        run_id=row["run_id"],
        sequence=row["sequence"],
        type=row["type"],
        data=row["data"],
        step=row["step"],
        created_at=row["created_at"],
    )


__all__ = [
    "PostgresEventStore",
    "PostgresPersistence",
    "PostgresRunStore",
]
