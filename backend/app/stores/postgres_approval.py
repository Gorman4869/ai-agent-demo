from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

from psycopg import Connection, Error as PsycopgError
from psycopg.rows import DictRow
from psycopg.types.json import Jsonb
from psycopg_pool import ConnectionPool, PoolTimeout

from backend.app.stores.base import StoreUnavailableError
from backend.app.tools import (
    ApprovalDecision,
    ApprovalResolutionError,
    ApprovalResolutionStatus,
    ApprovalResponse,
    ToolApproval,
    ToolApprovalRequest,
    ToolApprovalResolution,
    copy_tool_arguments,
    tool_arguments_digest,
)


ApprovalClock = Callable[[], datetime]
SyncPool = ConnectionPool[Connection[DictRow]]

_REQUEST_COLUMNS = """
    id,
    run_id,
    principal_id,
    tool_call_id,
    tool_name,
    arguments_digest,
    arguments,
    expires_at,
    response,
    resolution_status,
    created_at,
    resolved_at
"""


class PostgresApprovalStore:
    """Persist exact approval bindings and private arguments in PostgreSQL."""

    def __init__(
        self,
        pool: SyncPool,
        *,
        clock: ApprovalClock | None = None,
    ) -> None:
        self._pool = pool
        self._clock = clock or (lambda: datetime.now(UTC))

    def grant(
        self,
        *,
        principal_id: str,
        run_id: str | None = None,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        expires_at: datetime | None = None,
    ) -> ToolApproval:
        checked_expiry = (
            _aware_utc(expires_at, "approval expires_at")
            if expires_at is not None
            else None
        )
        approval = ToolApproval(
            id=str(uuid4()),
            principal_id=_required_name(principal_id, "principal_id"),
            run_id=(
                _required_name(run_id, "run_id")
                if run_id is not None
                else None
            ),
            tool_call_id=_required_name(tool_call_id, "tool_call_id"),
            tool_name=_required_name(tool_name, "tool_name"),
            arguments_digest=tool_arguments_digest(arguments),
            expires_at=checked_expiry,
        )
        try:
            with self._pool.connection() as connection:
                with connection.transaction():
                    result = connection.execute(
                        """
                        INSERT INTO tool_approval_grants (
                            id,
                            principal_id,
                            run_id,
                            tool_call_id,
                            tool_name,
                            arguments_digest,
                            expires_at,
                            consumed_at,
                            created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, NULL, %s)
                        ON CONFLICT DO NOTHING
                        RETURNING id
                        """,
                        (
                            approval.id,
                            approval.principal_id,
                            approval.run_id or "",
                            approval.tool_call_id,
                            approval.tool_name,
                            approval.arguments_digest,
                            approval.expires_at,
                            _aware_utc(self._clock(), "approval clock"),
                        ),
                    )
                    if result.fetchone() is None:
                        raise ValueError(
                            "an approval already exists for this exact tool call"
                        )
                    return approval
        except ValueError:
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def request(
        self,
        *,
        run_id: str,
        principal_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        expires_in: timedelta | None = None,
    ) -> ToolApprovalRequest:
        if expires_in is not None and (
            not isinstance(expires_in, timedelta)
            or expires_in <= timedelta(0)
        ):
            raise ValueError("approval expires_in must be positive")
        checked_run_id = _required_name(run_id, "run_id")
        checked_principal_id = _required_name(principal_id, "principal_id")
        checked_call_id = _required_name(tool_call_id, "tool_call_id")
        checked_tool_name = _required_name(tool_name, "tool_name")
        detached_arguments = copy_tool_arguments(arguments)
        digest = tool_arguments_digest(detached_arguments)
        now = _aware_utc(self._clock(), "approval clock")
        approval_id = str(uuid4())
        expires_at = now + expires_in if expires_in is not None else None
        parameters = (
            approval_id,
            checked_run_id,
            checked_principal_id,
            checked_call_id,
            checked_tool_name,
            digest,
            Jsonb(detached_arguments),
            expires_at,
            now,
        )
        binding = (
            checked_run_id,
            checked_principal_id,
            checked_call_id,
            checked_tool_name,
            digest,
        )
        try:
            with self._pool.connection() as connection:
                with connection.transaction():
                    result = connection.execute(
                        f"""
                        INSERT INTO tool_approval_requests (
                            id,
                            run_id,
                            principal_id,
                            tool_call_id,
                            tool_name,
                            arguments_digest,
                            arguments,
                            expires_at,
                            response,
                            resolution_status,
                            created_at,
                            resolved_at
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s,
                            NULL, NULL, %s, NULL
                        )
                        ON CONFLICT (
                            run_id,
                            principal_id,
                            tool_call_id,
                            tool_name,
                            arguments_digest
                        ) DO NOTHING
                        RETURNING {_REQUEST_COLUMNS}
                        """,
                        parameters,
                    )
                    row = result.fetchone()
                    if row is None:
                        existing = connection.execute(
                            f"""
                            SELECT {_REQUEST_COLUMNS}
                            FROM tool_approval_requests
                            WHERE run_id = %s
                              AND principal_id = %s
                              AND tool_call_id = %s
                              AND tool_name = %s
                              AND arguments_digest = %s
                            """,
                            binding,
                        ).fetchone()
                        if existing is None:
                            raise StoreUnavailableError()
                        row = existing
                    return _row_to_request(row)
        except StoreUnavailableError:
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def resolve(
        self,
        *,
        approval_id: str,
        run_id: str,
        principal_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments_digest: str,
        decision: ApprovalResponse | str,
    ) -> ToolApprovalResolution:
        response = _approval_response(decision)
        checked_id = _required_name(approval_id, "approval_id")
        binding = (
            _required_name(run_id, "run_id"),
            _required_name(principal_id, "principal_id"),
            _required_name(tool_call_id, "tool_call_id"),
            _required_name(tool_name, "tool_name"),
            arguments_digest,
        )
        try:
            with self._pool.connection() as connection:
                with connection.transaction():
                    row = connection.execute(
                        f"""
                        SELECT {_REQUEST_COLUMNS}
                        FROM tool_approval_requests
                        WHERE id = %s
                        FOR UPDATE
                        """,
                        (checked_id,),
                    ).fetchone()
                    if row is None or row["principal_id"] != binding[1]:
                        raise ApprovalResolutionError(
                            "approval_request_not_found"
                        )
                    request = _row_to_request(row)
                    if _request_key(request) != binding:
                        raise ApprovalResolutionError(
                            "approval_binding_mismatch"
                        )
                    if row["resolution_status"] is not None:
                        if row["response"] != response.value:
                            raise ApprovalResolutionError(
                                "approval_decision_conflict"
                            )
                        return _row_to_resolution(row)

                    now = _aware_utc(self._clock(), "approval clock")
                    status = (
                        ApprovalResolutionStatus.EXPIRED
                        if request.expires_at is not None
                        and now >= request.expires_at
                        else (
                            ApprovalResolutionStatus.APPROVED
                            if response is ApprovalResponse.APPROVE
                            else ApprovalResolutionStatus.REJECTED
                        )
                    )
                    updated = connection.execute(
                        f"""
                        UPDATE tool_approval_requests
                        SET response = %s,
                            resolution_status = %s,
                            resolved_at = %s
                        WHERE id = %s
                        RETURNING {_REQUEST_COLUMNS}
                        """,
                        (response.value, status.value, now, checked_id),
                    ).fetchone()
                    if updated is None:
                        raise StoreUnavailableError()
                    if status is ApprovalResolutionStatus.APPROVED:
                        connection.execute(
                            """
                            INSERT INTO tool_approval_grants (
                                id,
                                principal_id,
                                run_id,
                                tool_call_id,
                                tool_name,
                                arguments_digest,
                                expires_at,
                                consumed_at,
                                created_at
                            ) VALUES (
                                %s, %s, %s, %s, %s, %s, %s, NULL, %s
                            )
                            ON CONFLICT (
                                principal_id,
                                run_id,
                                tool_call_id,
                                tool_name,
                                arguments_digest
                            ) DO UPDATE SET
                                id = EXCLUDED.id,
                                expires_at = EXCLUDED.expires_at,
                                consumed_at = NULL,
                                created_at = EXCLUDED.created_at
                            """,
                            (
                                request.id,
                                request.principal_id,
                                request.run_id,
                                request.tool_call_id,
                                request.tool_name,
                                request.arguments_digest,
                                request.expires_at,
                                now,
                            ),
                        )
                    return _row_to_resolution(updated)
        except (ApprovalResolutionError, StoreUnavailableError):
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def get_resolution(
        self,
        *,
        approval_id: str,
        run_id: str,
        principal_id: str,
    ) -> ToolApprovalResolution | None:
        try:
            with self._pool.connection() as connection:
                row = connection.execute(
                    f"""
                    SELECT {_REQUEST_COLUMNS}
                    FROM tool_approval_requests
                    WHERE id = %s
                      AND run_id = %s
                      AND principal_id = %s
                      AND resolution_status IS NOT NULL
                    """,
                    (approval_id, run_id, principal_id),
                ).fetchone()
                return _row_to_resolution(row) if row is not None else None
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def approved_arguments(
        self,
        resolution: ToolApprovalResolution,
    ) -> dict[str, Any]:
        if resolution.status is not ApprovalResolutionStatus.APPROVED:
            raise ApprovalResolutionError("approval_not_approved")
        try:
            with self._pool.connection() as connection:
                row = connection.execute(
                    f"""
                    SELECT {_REQUEST_COLUMNS}
                    FROM tool_approval_requests
                    WHERE id = %s
                    """,
                    (resolution.request.id,),
                ).fetchone()
                if (
                    row is None
                    or row["resolution_status"] is None
                    or _row_to_resolution(row) != resolution
                ):
                    raise ApprovalResolutionError(
                        "approval_resolution_mismatch"
                    )
                arguments = row["arguments"]
                if not isinstance(arguments, Mapping):
                    raise ApprovalResolutionError(
                        "approval_arguments_unavailable"
                    )
                return copy_tool_arguments(arguments)
        except ApprovalResolutionError:
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def consume(
        self,
        *,
        principal_id: str,
        run_id: str | None = None,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> ApprovalDecision:
        binding = (
            principal_id,
            run_id or "",
            tool_call_id,
            tool_name,
            tool_arguments_digest(arguments),
        )
        try:
            with self._pool.connection() as connection:
                with connection.transaction():
                    row = connection.execute(
                        """
                        SELECT id, expires_at, consumed_at
                        FROM tool_approval_grants
                        WHERE principal_id = %s
                          AND run_id = %s
                          AND tool_call_id = %s
                          AND tool_name = %s
                          AND arguments_digest = %s
                        FOR UPDATE
                        """,
                        binding,
                    ).fetchone()
                    if row is None:
                        return ApprovalDecision(
                            False,
                            "exact_call_approval_missing",
                        )
                    if row["consumed_at"] is not None:
                        return ApprovalDecision(
                            False,
                            "approval_already_consumed",
                        )
                    now = _aware_utc(self._clock(), "approval clock")
                    if row["expires_at"] is not None and now >= row["expires_at"]:
                        return ApprovalDecision(False, "approval_expired")
                    connection.execute(
                        """
                        UPDATE tool_approval_grants
                        SET consumed_at = %s
                        WHERE id = %s
                        """,
                        (now, row["id"]),
                    )
                    return ApprovalDecision(True, "approved")
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None


def _row_to_request(row: Mapping[str, Any]) -> ToolApprovalRequest:
    return ToolApprovalRequest(
        id=row["id"],
        run_id=row["run_id"],
        principal_id=row["principal_id"],
        tool_call_id=row["tool_call_id"],
        tool_name=row["tool_name"],
        arguments_digest=row["arguments_digest"].strip(),
        expires_at=row["expires_at"],
    )


def _row_to_resolution(row: Mapping[str, Any]) -> ToolApprovalResolution:
    status = row["resolution_status"]
    if status is None:
        raise ApprovalResolutionError("approval_resolution_missing")
    return ToolApprovalResolution(
        request=_row_to_request(row),
        status=ApprovalResolutionStatus(status),
    )


def _request_key(
    request: ToolApprovalRequest,
) -> tuple[str, str, str, str, str]:
    return (
        request.run_id,
        request.principal_id,
        request.tool_call_id,
        request.tool_name,
        request.arguments_digest,
    )


def _approval_response(value: ApprovalResponse | str) -> ApprovalResponse:
    if isinstance(value, bool):
        raise ValueError("approval decision must be approve or reject")
    try:
        return ApprovalResponse(value)
    except (TypeError, ValueError):
        raise ValueError("approval decision must be approve or reject") from None


def _required_name(value: str, label: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be a string")
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} must not be empty")
    return normalized


def _aware_utc(value: datetime, label: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


__all__ = ["PostgresApprovalStore"]
