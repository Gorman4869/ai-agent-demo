from __future__ import annotations

import asyncio
import hmac
from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any

from psycopg import AsyncConnection, Error as PsycopgError
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from backend.app.stores.base import (
    InvalidRunTransitionError,
    RunNotFoundError,
    StoreError,
    StoreUnavailableError,
)
from backend.app.stores.run_lease import (
    LeaseToken,
    RunLease,
    RunLeaseLostError,
    RunLeaseMode,
    RunLeaseUnavailableError,
    TokenFactory,
    _StoredRunLease,
    _issue_token,
    _require_lease,
    _require_scan_limit,
    _require_ttl,
    _to_handle,
    _token_digest,
)


Pool = AsyncConnectionPool[AsyncConnection[DictRow]]

_LEASE_COLUMNS = """
    run_id,
    mode,
    lease_token_digest,
    version,
    acquired_at,
    heartbeat_at,
    expires_at
"""


class PostgresRunLeaseStore:
    """Use database time and row locks for execution/recovery leases."""

    def __init__(
        self,
        pool: Pool,
        *,
        token_factory: TokenFactory | None = None,
    ) -> None:
        self._pool = pool
        self._token_factory = token_factory

    async def acquire(
        self,
        run_id: str,
        *,
        owner_id: str,
        ttl: timedelta,
    ) -> RunLease:
        ttl = _require_ttl(ttl)
        token = _issue_token(self._token_factory)
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    run_status = await _select_owned_run_status_for_update(
                        connection,
                        run_id=run_id,
                        owner_id=owner_id,
                    )
                    if run_status is None:
                        raise RunNotFoundError()
                    if run_status != "running":
                        raise InvalidRunTransitionError()
                    existing = await connection.execute(
                        "SELECT 1 FROM agent_run_leases WHERE run_id = %s",
                        (run_id,),
                    )
                    if await existing.fetchone() is not None:
                        raise RunLeaseUnavailableError()
                    now = await _database_now(connection)
                    result = await connection.execute(
                        f"""
                        INSERT INTO agent_run_leases ({_LEASE_COLUMNS})
                        VALUES (%s, %s, %s, 0, %s, %s, %s)
                        RETURNING {_LEASE_COLUMNS}
                        """,
                        (
                            run_id,
                            RunLeaseMode.EXECUTION.value,
                            _token_digest(token),
                            now,
                            now,
                            now + ttl,
                        ),
                    )
                    row = await result.fetchone()
                    if row is None:
                        raise StoreUnavailableError()
                    return _row_to_handle(
                        row,
                        owner_id=owner_id,
                        token=token,
                    )
        except StoreError:
            raise
        except asyncio.CancelledError:
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    async def heartbeat(
        self,
        lease: RunLease,
        *,
        ttl: timedelta,
    ) -> RunLease:
        lease = _require_lease(lease)
        ttl = _require_ttl(ttl)
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    current = await _select_owned_lease_for_update(
                        connection,
                        run_id=lease.run_id,
                        owner_id=lease.owner_id,
                    )
                    now = await _database_now(connection)
                    if (
                        current is None
                        or current["run_status"] != "running"
                        or not _row_matches_lease(current, lease)
                        or current["expires_at"] <= now
                    ):
                        raise RunLeaseLostError()
                    result = await connection.execute(
                        f"""
                        UPDATE agent_run_leases
                        SET version = version + 1,
                            heartbeat_at = %s,
                            expires_at = %s
                        WHERE run_id = %s
                        RETURNING {_LEASE_COLUMNS}
                        """,
                        (now, now + ttl, lease.run_id),
                    )
                    row = await result.fetchone()
                    if row is None:
                        raise RunLeaseLostError()
                    return _row_to_handle(
                        row,
                        owner_id=lease.owner_id,
                        token=lease.token,
                    )
        except StoreError:
            raise
        except asyncio.CancelledError:
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    async def release(self, lease: RunLease) -> None:
        lease = _require_lease(lease)
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    current = await _select_owned_lease_for_update(
                        connection,
                        run_id=lease.run_id,
                        owner_id=lease.owner_id,
                    )
                    now = await _database_now(connection)
                    if (
                        current is None
                        or not _row_matches_lease(current, lease)
                        or current["expires_at"] <= now
                    ):
                        raise RunLeaseLostError()
                    await connection.execute(
                        "DELETE FROM agent_run_leases WHERE run_id = %s",
                        (lease.run_id,),
                    )
        except StoreError:
            raise
        except asyncio.CancelledError:
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    async def claim_expired(
        self,
        *,
        limit: int,
        ttl: timedelta,
    ) -> tuple[RunLease, ...]:
        limit = _require_scan_limit(limit)
        ttl = _require_ttl(ttl)
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    now = await _database_now(connection)
                    result = await connection.execute(
                        f"""
                        SELECT
                            {_qualified_lease_columns('agent_run_leases')},
                            agent_runs.owner_id AS owner_id
                        FROM agent_run_leases
                        JOIN agent_runs
                          ON agent_runs.id = agent_run_leases.run_id
                        WHERE agent_run_leases.expires_at <= %s
                        ORDER BY
                            agent_run_leases.expires_at,
                            agent_run_leases.run_id
                        LIMIT %s
                        FOR UPDATE OF agent_run_leases SKIP LOCKED
                        """,
                        (now, limit),
                    )
                    rows = await result.fetchall()
                    claimed: list[RunLease] = []
                    for current in rows:
                        token = _issue_token(self._token_factory)
                        updated_result = await connection.execute(
                            f"""
                            UPDATE agent_run_leases
                            SET mode = %s,
                                lease_token_digest = %s,
                                version = version + 1,
                                acquired_at = %s,
                                heartbeat_at = %s,
                                expires_at = %s
                            WHERE run_id = %s
                            RETURNING {_LEASE_COLUMNS}
                            """,
                            (
                                RunLeaseMode.RECOVERY.value,
                                _token_digest(token),
                                now,
                                now,
                                now + ttl,
                                current["run_id"],
                            ),
                        )
                        updated = await updated_result.fetchone()
                        if updated is None:
                            raise StoreUnavailableError()
                        claimed.append(
                            _row_to_handle(
                                updated,
                                owner_id=current["owner_id"],
                                token=token,
                            )
                        )
                    return tuple(claimed)
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


async def _select_owned_lease_for_update(
    connection: AsyncConnection[DictRow],
    *,
    run_id: str,
    owner_id: str,
) -> Mapping[str, Any] | None:
    run_status = await _select_owned_run_status_for_update(
        connection,
        run_id=run_id,
        owner_id=owner_id,
    )
    if run_status is None:
        return None
    result = await connection.execute(
        f"""
        SELECT {_qualified_lease_columns('agent_run_leases')}
        FROM agent_run_leases
        WHERE agent_run_leases.run_id = %s
        FOR UPDATE
        """,
        (run_id,),
    )
    row = await result.fetchone()
    if row is None:
        return None
    current = dict(row)
    current["run_status"] = run_status
    return current


async def _database_now(connection: AsyncConnection[DictRow]) -> datetime:
    result = await connection.execute(
        "SELECT clock_timestamp() AS database_now"
    )
    row = await result.fetchone()
    if row is None:
        raise StoreUnavailableError()
    return row["database_now"]


def _row_matches_lease(row: Mapping[str, Any], lease: RunLease) -> bool:
    return (
        row["version"] == lease.version
        and hmac.compare_digest(
            row["lease_token_digest"].strip(),
            _token_digest(lease.token),
        )
    )


def _qualified_lease_columns(table: str) -> str:
    return ",\n                            ".join(
        f"{table}.{column.strip()} AS {column.strip()}"
        for column in _LEASE_COLUMNS.split(",")
    )


def _row_to_handle(
    row: Mapping[str, Any],
    *,
    owner_id: str,
    token: LeaseToken,
) -> RunLease:
    stored = _StoredRunLease(
        run_id=row["run_id"],
        mode=RunLeaseMode(row["mode"]),
        token_digest=row["lease_token_digest"].strip(),
        version=row["version"],
        acquired_at=row["acquired_at"],
        heartbeat_at=row["heartbeat_at"],
        expires_at=row["expires_at"],
    )
    return _to_handle(stored, owner_id=owner_id, token=token)


__all__ = ["PostgresRunLeaseStore"]
