from __future__ import annotations

import asyncio
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from backend.app.domain.run import RunFailure


class RetryOperation(StrEnum):
    MODEL = "model"
    TOOL = "tool"
    MCP = "mcp"
    STORE = "store"


@dataclass(frozen=True)
class FailureSpec:
    """One content-free error classification owned by the application."""

    code: str
    category: str
    public_message: str
    retryable: bool


_FAILURE_SPECS = {
    spec.code: spec
    for spec in (
        FailureSpec(
            "provider_rate_limited",
            "provider",
            "Model provider rate limit was reached",
            True,
        ),
        FailureSpec(
            "provider_timeout",
            "timeout",
            "Model provider timed out",
            True,
        ),
        FailureSpec(
            "provider_unavailable",
            "provider",
            "Model provider is unavailable",
            True,
        ),
        FailureSpec(
            "provider_auth_failed",
            "provider",
            "Model provider authentication failed",
            False,
        ),
        FailureSpec(
            "provider_request_rejected",
            "provider",
            "Model provider rejected the request",
            False,
        ),
        FailureSpec(
            "provider_invalid_response",
            "provider",
            "Model provider returned an invalid response",
            False,
        ),
        FailureSpec(
            "mcp_timeout",
            "timeout",
            "MCP tool request timed out",
            True,
        ),
        FailureSpec(
            "mcp_disconnected",
            "mcp",
            "MCP tool connection is unavailable",
            True,
        ),
        FailureSpec(
            "mcp_remote_error",
            "mcp",
            "MCP tool reported a failure",
            False,
        ),
        FailureSpec(
            "mcp_invalid_response",
            "mcp",
            "MCP tool returned an invalid response",
            False,
        ),
        FailureSpec(
            "mcp_request_rejected",
            "validation",
            "MCP tool request was rejected",
            False,
        ),
        FailureSpec(
            "store_unavailable",
            "storage",
            "Persistent storage is unavailable",
            True,
        ),
        FailureSpec(
            "store_operation_timeout",
            "timeout",
            "Persistent storage operation timed out",
            True,
        ),
        FailureSpec(
            "tool_timeout",
            "tool",
            "Tool execution timed out",
            True,
        ),
        FailureSpec(
            "tool_io_error",
            "tool",
            "Tool I/O failed",
            True,
        ),
        FailureSpec(
            "run_timeout",
            "timeout",
            "Run timed out",
            False,
        ),
        FailureSpec(
            "cancelled_by_user",
            "cancellation",
            "Run cancelled",
            False,
        ),
        FailureSpec(
            "max_steps_exceeded",
            "budget",
            "Agent exceeded the maximum step budget",
            False,
        ),
        FailureSpec(
            "model_call_budget_exceeded",
            "budget",
            "Model call budget was exhausted",
            False,
        ),
    )
}

RETRYABLE_OPERATION_FAILURE_CODES = frozenset(
    code for code, spec in _FAILURE_SPECS.items() if spec.retryable
)


def failure_spec(code: str) -> FailureSpec:
    try:
        return _FAILURE_SPECS[code]
    except (KeyError, TypeError):
        raise ValueError("error code is not registered") from None


def stable_run_failure(code: str, *, step: int | None = None) -> RunFailure:
    spec = failure_spec(code)
    return RunFailure(
        code=spec.code,
        category=spec.category,
        public_message=spec.public_message,
        retryable=spec.retryable,
        step=step,
    )


@dataclass(frozen=True)
class ExponentialBackoff:
    initial_delay_ms: int
    max_delay_ms: int
    multiplier: int = 2

    def __post_init__(self) -> None:
        for value, label in (
            (self.initial_delay_ms, "initial_delay_ms"),
            (self.max_delay_ms, "max_delay_ms"),
            (self.multiplier, "multiplier"),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{label} must be a non-negative integer")
        if self.max_delay_ms < self.initial_delay_ms:
            raise ValueError("max_delay_ms must not be less than initial_delay_ms")
        if self.multiplier < 1:
            raise ValueError("multiplier must be at least one")

    def delay_ms(self, retry_number: int) -> int:
        if (
            not isinstance(retry_number, int)
            or isinstance(retry_number, bool)
            or retry_number < 1
        ):
            raise ValueError("retry_number must be a positive integer")
        delay = self.initial_delay_ms * (self.multiplier ** (retry_number - 1))
        return min(delay, self.max_delay_ms)


@dataclass(frozen=True)
class RetrySafety:
    operation: RetryOperation
    idempotent: bool
    replay_safe: bool
    side_effecting: bool = False
    persistent_idempotency_key: bool = False
    result_unknown: bool = False

    def __post_init__(self) -> None:
        try:
            operation = RetryOperation(self.operation)
        except (TypeError, ValueError):
            raise ValueError("retry operation is not supported") from None
        for value, label in (
            (self.idempotent, "idempotent"),
            (self.replay_safe, "replay_safe"),
            (self.side_effecting, "side_effecting"),
            (self.persistent_idempotency_key, "persistent_idempotency_key"),
            (self.result_unknown, "result_unknown"),
        ):
            if not isinstance(value, bool):
                raise ValueError(f"{label} must be a boolean")
        object.__setattr__(self, "operation", operation)


@dataclass(frozen=True)
class RetryDecision:
    retry: bool
    delay_ms: int
    reason: str


def decide_retry(
    failure: RunFailure,
    *,
    safety: RetrySafety,
    retry_number: int,
    max_retries: int,
    backoff: ExponentialBackoff,
    remaining_budget_ms: int | None = None,
) -> RetryDecision:
    """Return a fail-closed retry decision for one completed attempt."""

    if not isinstance(failure, RunFailure):
        raise ValueError("failure must be RunFailure")
    if not isinstance(safety, RetrySafety):
        raise ValueError("safety must be RetrySafety")
    if (
        not isinstance(retry_number, int)
        or isinstance(retry_number, bool)
        or retry_number < 1
    ):
        raise ValueError("retry_number must be a positive integer")
    if (
        not isinstance(max_retries, int)
        or isinstance(max_retries, bool)
        or max_retries < 0
    ):
        raise ValueError("max_retries must be a non-negative integer")
    if remaining_budget_ms is not None and (
        not isinstance(remaining_budget_ms, int)
        or isinstance(remaining_budget_ms, bool)
        or remaining_budget_ms < 0
    ):
        raise ValueError("remaining_budget_ms must be non-negative")

    if not failure.retryable:
        return RetryDecision(False, 0, "failure_not_retryable")
    if retry_number > max_retries:
        return RetryDecision(False, 0, "retry_budget_exhausted")
    if safety.side_effecting and not safety.persistent_idempotency_key:
        return RetryDecision(False, 0, "persistent_idempotency_key_required")
    if safety.result_unknown and not safety.replay_safe:
        return RetryDecision(False, 0, "result_unknown")
    if not safety.idempotent or not safety.replay_safe:
        return RetryDecision(False, 0, "operation_not_replay_safe")

    delay_ms = backoff.delay_ms(retry_number)
    if (
        remaining_budget_ms is not None
        and delay_ms >= remaining_budget_ms
    ):
        return RetryDecision(False, 0, "time_budget_exhausted")
    return RetryDecision(True, delay_ms, "retry_allowed")


class CancellationSignal(Protocol):
    @property
    def is_cancelled(self) -> bool: ...


async def wait_for_retry_delay(
    delay_ms: int,
    *,
    cancellation: CancellationSignal,
    poll_interval_ms: int = 25,
) -> bool:
    """Wait cooperatively and return True when cancellation wins."""

    for value, label in (
        (delay_ms, "delay_ms"),
        (poll_interval_ms, "poll_interval_ms"),
    ):
        if (
            not isinstance(value, int)
            or isinstance(value, bool)
            or value < 0
        ):
            raise ValueError(f"{label} must be a non-negative integer")
    if poll_interval_ms < 1:
        raise ValueError("poll_interval_ms must be positive")
    if cancellation.is_cancelled:
        return True
    remaining = delay_ms / 1_000
    while remaining > 0:
        interval = min(remaining, poll_interval_ms / 1_000)
        await asyncio.sleep(interval)
        if cancellation.is_cancelled:
            return True
        remaining -= interval
    return cancellation.is_cancelled


__all__ = [
    "ExponentialBackoff",
    "FailureSpec",
    "RETRYABLE_OPERATION_FAILURE_CODES",
    "RetryDecision",
    "RetryOperation",
    "RetrySafety",
    "decide_retry",
    "failure_spec",
    "stable_run_failure",
    "wait_for_retry_delay",
]
