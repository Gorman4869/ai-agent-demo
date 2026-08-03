from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from backend.app.domain.run import (
    InvalidRunTransition,
    ToolExecution,
    ToolExecutionStatus,
)
from backend.app.stores.base import StoreError


_TOOL_RESULT_MISSING = object()


class ToolExecutionNotFoundError(StoreError):
    code = "tool_execution_not_found"


class ToolExecutionConflictError(StoreError):
    code = "tool_execution_conflict"


class InvalidToolExecutionTransitionError(StoreError):
    code = "invalid_tool_execution_transition"


@dataclass(frozen=True)
class CreateToolExecutionResult:
    record: ToolExecution
    created: bool


class ToolExecutionStore(Protocol):
    """Owner-bound async persistence for durable tool result arbitration."""

    async def create(
        self,
        record: ToolExecution,
        *,
        owner_id: str,
    ) -> CreateToolExecutionResult:
        """Create or replay one pending execution without retaining raw data."""
        ...

    async def get(
        self,
        execution_id: str,
        *,
        owner_id: str,
    ) -> ToolExecution | None:
        ...

    async def list_for_run(
        self,
        run_id: str,
        *,
        owner_id: str,
    ) -> tuple[ToolExecution, ...]:
        ...

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
        """Apply one version-CAS claim or settlement."""
        ...


def _require_new_tool_execution(record: ToolExecution) -> None:
    if (
        not isinstance(record, ToolExecution)
        or record.status is not ToolExecutionStatus.PENDING
        or record.version != 0
    ):
        raise ValueError("a new tool execution must be pending at version zero")


def _require_expected_version(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise ValueError("expected_version must be a non-negative integer")
    return value


def _idempotency_replay_matches(
    existing: ToolExecution,
    candidate: ToolExecution,
) -> bool:
    return (
        existing.run_id == candidate.run_id
        and existing.tool_name == candidate.tool_name
        and existing.arguments_digest == candidate.arguments_digest
        and existing.idempotency_key_digest
        == candidate.idempotency_key_digest
        and existing.side_effecting == candidate.side_effecting
    )


def _call_replay_matches(
    existing: ToolExecution,
    candidate: ToolExecution,
) -> bool:
    return (
        existing.run_id == candidate.run_id
        and existing.tool_call_id == candidate.tool_call_id
        and existing.tool_name == candidate.tool_name
        and existing.arguments_digest == candidate.arguments_digest
        and existing.idempotency_key_digest
        == candidate.idempotency_key_digest
        and existing.side_effecting == candidate.side_effecting
        and existing.attempt == candidate.attempt
    )


def _transition_tool_execution(
    current: ToolExecution,
    target_status: ToolExecutionStatus | str,
    *,
    at: datetime,
    result: object = _TOOL_RESULT_MISSING,
    result_summary: str | None = None,
    error_code: str | None = None,
    public_message: str | None = None,
) -> ToolExecution:
    try:
        if result is _TOOL_RESULT_MISSING:
            return current.transition_to(
                target_status,
                at=at,
                result_summary=result_summary,
                error_code=error_code,
                public_message=public_message,
            )
        return current.transition_to(
            target_status,
            at=at,
            result=result,
            result_summary=result_summary,
            error_code=error_code,
            public_message=public_message,
        )
    except InvalidRunTransition:
        raise InvalidToolExecutionTransitionError() from None


__all__ = [
    "CreateToolExecutionResult",
    "InvalidToolExecutionTransitionError",
    "ToolExecutionConflictError",
    "ToolExecutionNotFoundError",
    "ToolExecutionStore",
]
