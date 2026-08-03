from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, Callable

from psycopg import AsyncConnection, Error as PsycopgError
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from backend.app.domain.run import ToolExecution, ToolExecutionStatus
from backend.app.stores.base import (
    ConcurrentWriteError,
    IdempotencyConflictError,
    RunNotFoundError,
    StoreError,
    StoreUnavailableError,
)
from backend.app.stores.tool_execution import (
    CreateToolExecutionResult,
    InvalidToolExecutionTransitionError,
    ToolExecutionConflictError,
    ToolExecutionNotFoundError,
    _call_replay_matches,
    _idempotency_replay_matches,
    _require_expected_version,
    _require_new_tool_execution,
    _TOOL_RESULT_MISSING,
    _transition_tool_execution,
)


Clock = Callable[[], datetime]
Pool = AsyncConnectionPool[AsyncConnection[DictRow]]

_TOOL_COLUMNS = """
    id,
    run_id,
    tool_call_id,
    tool_name,
    arguments_digest,
    idempotency_key_digest,
    side_effecting,
    status,
    version,
    attempt,
    created_at,
    updated_at,
    started_at,
    finished_at,
    result_digest,
    result_summary,
    error_code,
    public_message
"""


class PostgresToolExecutionStore:
    """Persist owner-bound tool claims and single terminal settlements."""

    def __init__(self, pool: Pool, *, clock: Clock | None = None) -> None:
        self._pool = pool
        self._clock = clock or (lambda: datetime.now(UTC))

    async def create(
        self,
        record: ToolExecution,
        *,
        owner_id: str,
    ) -> CreateToolExecutionResult:
        _require_new_tool_execution(record)
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    run_status = await _select_owned_run_status_for_update(
                        connection,
                        run_id=record.run_id,
                        owner_id=owner_id,
                    )
                    if run_status is None:
                        raise RunNotFoundError()
                    replay = await _select_create_replay(connection, record)
                    if replay is not None:
                        return CreateToolExecutionResult(
                            record=replay,
                            created=False,
                        )
                    if run_status != "running":
                        raise InvalidToolExecutionTransitionError()
                    result = await connection.execute(
                        f"""
                        INSERT INTO tool_executions ({_TOOL_COLUMNS})
                        VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s,
                            %s, %s, %s, %s, %s, %s, %s, %s, %s
                        )
                        ON CONFLICT DO NOTHING
                        RETURNING {_TOOL_COLUMNS}
                        """,
                        _tool_parameters(record),
                    )
                    row = await result.fetchone()
                    if row is not None:
                        return CreateToolExecutionResult(
                            record=_row_to_tool_execution(row),
                            created=True,
                        )
                    replay = await _select_create_replay(connection, record)
                    if replay is not None:
                        return CreateToolExecutionResult(
                            record=replay,
                            created=False,
                        )
                    raise StoreUnavailableError()
        except StoreError:
            raise
        except asyncio.CancelledError:
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    async def get(
        self,
        execution_id: str,
        *,
        owner_id: str,
    ) -> ToolExecution | None:
        try:
            async with self._pool.connection() as connection:
                result = await connection.execute(
                    f"""
                    SELECT {_qualified_tool_columns('tool_executions')}
                    FROM tool_executions
                    JOIN agent_runs
                      ON agent_runs.id = tool_executions.run_id
                    WHERE tool_executions.id = %s
                      AND agent_runs.owner_id = %s
                    """,
                    (execution_id, owner_id),
                )
                row = await result.fetchone()
                return _row_to_tool_execution(row) if row is not None else None
        except asyncio.CancelledError:
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    async def list_for_run(
        self,
        run_id: str,
        *,
        owner_id: str,
    ) -> tuple[ToolExecution, ...]:
        try:
            async with self._pool.connection() as connection:
                result = await connection.execute(
                    f"""
                    SELECT {_qualified_tool_columns('tool_executions')}
                    FROM tool_executions
                    JOIN agent_runs
                      ON agent_runs.id = tool_executions.run_id
                    WHERE tool_executions.run_id = %s
                      AND agent_runs.owner_id = %s
                    ORDER BY tool_executions.created_at, tool_executions.id
                    """,
                    (run_id, owner_id),
                )
                return tuple(
                    _row_to_tool_execution(row)
                    for row in await result.fetchall()
                )
        except asyncio.CancelledError:
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    async def transition(
        self,
        execution_id: str,
        *,
        owner_id: str,
        expected_version: int,
        target_status: ToolExecutionStatus | str,
        result: object = _TOOL_RESULT_MISSING,
        result_summary: str | None = None,
        error_code: str | None = None,
        public_message: str | None = None,
    ) -> ToolExecution:
        _require_expected_version(expected_version)
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    current = await _select_owned_tool_for_update(
                        connection,
                        execution_id=execution_id,
                        owner_id=owner_id,
                    )
                    if current is None:
                        raise ToolExecutionNotFoundError()
                    if current.version != expected_version:
                        raise ConcurrentWriteError()
                    updated = _transition_tool_execution(
                        current,
                        target_status,
                        at=self._clock(),
                        result=result,
                        result_summary=result_summary,
                        error_code=error_code,
                        public_message=public_message,
                    )
                    await connection.execute(
                        """
                        UPDATE tool_executions
                        SET status = %s,
                            version = %s,
                            updated_at = %s,
                            started_at = %s,
                            finished_at = %s,
                            result_digest = %s,
                            result_summary = %s,
                            error_code = %s,
                            public_message = %s
                        WHERE id = %s
                        """,
                        (
                            updated.status.value,
                            updated.version,
                            updated.updated_at,
                            updated.started_at,
                            updated.finished_at,
                            updated.result_digest,
                            updated.result_summary,
                            updated.error_code,
                            updated.public_message,
                            updated.id,
                        ),
                    )
                    return updated
        except StoreError:
            raise
        except asyncio.CancelledError:
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None


async def _select_owned_run_status_for_update(
    connection: AsyncConnection[DictRow],
    *,
    run_id: str,
    owner_id: str,
) -> str | None:
    result = await connection.execute(
        """
        SELECT status
        FROM agent_runs
        WHERE id = %s AND owner_id = %s
        FOR UPDATE
        """,
        (run_id, owner_id),
    )
    row = await result.fetchone()
    return row["status"] if row is not None else None


async def _select_create_replay(
    connection: AsyncConnection[DictRow],
    candidate: ToolExecution,
) -> ToolExecution | None:
    if candidate.idempotency_key_digest is not None:
        result = await connection.execute(
            f"""
            SELECT {_TOOL_COLUMNS}
            FROM tool_executions
            WHERE run_id = %s
              AND tool_name = %s
              AND idempotency_key_digest = %s
            """,
            (
                candidate.run_id,
                candidate.tool_name,
                candidate.idempotency_key_digest,
            ),
        )
        row = await result.fetchone()
        if row is not None:
            existing = _row_to_tool_execution(row)
            if not _idempotency_replay_matches(existing, candidate):
                raise IdempotencyConflictError()
            return existing

    result = await connection.execute(
        f"SELECT {_TOOL_COLUMNS} FROM tool_executions WHERE id = %s",
        (candidate.id,),
    )
    row = await result.fetchone()
    if row is not None:
        existing = _row_to_tool_execution(row)
        if not _call_replay_matches(existing, candidate):
            raise ToolExecutionConflictError()
        return existing

    result = await connection.execute(
        f"""
        SELECT {_TOOL_COLUMNS}
        FROM tool_executions
        WHERE run_id = %s AND tool_call_id = %s
        """,
        (candidate.run_id, candidate.tool_call_id),
    )
    row = await result.fetchone()
    if row is None:
        return None
    existing = _row_to_tool_execution(row)
    if not _call_replay_matches(existing, candidate):
        raise ToolExecutionConflictError()
    return existing


async def _select_owned_tool_for_update(
    connection: AsyncConnection[DictRow],
    *,
    execution_id: str,
    owner_id: str,
) -> ToolExecution | None:
    result = await connection.execute(
        f"""
        SELECT {_qualified_tool_columns('tool_executions')}
        FROM tool_executions
        JOIN agent_runs ON agent_runs.id = tool_executions.run_id
        WHERE tool_executions.id = %s AND agent_runs.owner_id = %s
        FOR UPDATE OF tool_executions
        """,
        (execution_id, owner_id),
    )
    row = await result.fetchone()
    return _row_to_tool_execution(row) if row is not None else None


def _qualified_tool_columns(table: str) -> str:
    return ",\n    ".join(
        f"{table}.{column.strip()} AS {column.strip()}"
        for column in _TOOL_COLUMNS.split(",")
    )


def _tool_parameters(record: ToolExecution) -> tuple[object, ...]:
    return (
        record.id,
        record.run_id,
        record.tool_call_id,
        record.tool_name,
        record.arguments_digest,
        record.idempotency_key_digest,
        record.side_effecting,
        record.status.value,
        record.version,
        record.attempt,
        record.created_at,
        record.updated_at,
        record.started_at,
        record.finished_at,
        record.result_digest,
        record.result_summary,
        record.error_code,
        record.public_message,
    )


def _row_to_tool_execution(row: Mapping[str, Any]) -> ToolExecution:
    return ToolExecution(
        id=row["id"],
        run_id=row["run_id"],
        tool_call_id=row["tool_call_id"],
        tool_name=row["tool_name"],
        arguments_digest=row["arguments_digest"].strip(),
        idempotency_key_digest=(
            row["idempotency_key_digest"].strip()
            if row["idempotency_key_digest"] is not None
            else None
        ),
        side_effecting=row["side_effecting"],
        status=row["status"],
        version=row["version"],
        attempt=row["attempt"],
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        result_digest=(
            row["result_digest"].strip()
            if row["result_digest"] is not None
            else None
        ),
        result_summary=row["result_summary"],
        error_code=row["error_code"],
        public_message=row["public_message"],
    )


__all__ = ["PostgresToolExecutionStore"]
