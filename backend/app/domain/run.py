from __future__ import annotations

import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal


RuntimeName = Literal["manual", "agents_sdk", "langgraph"]
ModelProviderName = Literal["mock", "openai"]

_RUNTIME_NAMES = frozenset({"manual", "agents_sdk", "langgraph"})
_MODEL_PROVIDER_NAMES = frozenset({"mock", "openai"})
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_EVENT_TYPE_PATTERN = re.compile(
    r"[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+"
)
_MAX_RUN_CONTENT_BYTES = 200_000
_MAX_EVENT_DATA_BYTES = 64_000
_MAX_TOOL_DATA_BYTES = 64_000
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 10_000
_MISSING = object()


class RunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }


class ToolExecutionStatus(StrEnum):
    PENDING = "pending"
    WAITING_APPROVAL = "waiting_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    UNKNOWN = "unknown"

    @property
    def is_terminal(self) -> bool:
        return self in {
            ToolExecutionStatus.COMPLETED,
            ToolExecutionStatus.FAILED,
            ToolExecutionStatus.CANCELLED,
            ToolExecutionStatus.UNKNOWN,
        }


class CostSource(StrEnum):
    PROVIDER = "provider"
    CONFIGURED_PRICING = "configured_pricing"
    UNKNOWN = "unknown"


class InvalidRunTransition(ValueError):
    """Raised when a Run or tool execution crosses an invalid state edge."""

    def __init__(self) -> None:
        super().__init__("invalid state transition")


@dataclass(frozen=True)
class RunFailure:
    """Bounded, user-safe failure details without an exception or stack trace."""

    code: str
    category: str
    public_message: str = field(repr=False)
    retryable: bool = False
    internal_ref: str | None = None
    step: int | None = None

    def __post_init__(self) -> None:
        _require_identifier(self.code, "failure code", max_length=100)
        _require_identifier(self.category, "failure category", max_length=100)
        _require_content(
            self.public_message,
            "failure public message",
            max_bytes=2_000,
        )
        if not isinstance(self.retryable, bool):
            raise ValueError("failure retryable must be a boolean")
        if self.internal_ref is not None:
            _require_identifier(
                self.internal_ref,
                "failure internal reference",
                max_length=200,
            )
        if self.step is not None:
            _require_nonnegative_int(self.step, "failure step")


@dataclass(frozen=True)
class RunRecord:
    """Immutable snapshot of one durable Agent run.

    The raw idempotency key is never retained. ``request_digest`` is based on
    versioned canonical JSON so every Store implementation can enforce the
    same replay semantics.
    """

    id: str
    session_id: str
    owner_id: str
    runtime: RuntimeName
    model_provider: ModelProviderName
    model: str
    input_text: str = field(repr=False)
    idempotency_key_digest: str = field(repr=False)
    request_digest: str = field(repr=False)
    status: RunStatus
    version: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    answer: str | None = field(default=None, repr=False)
    failure: RunFailure | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_identifier(self.id, "run id")
        _require_identifier(self.session_id, "session id")
        _require_identifier(self.owner_id, "owner id")
        if self.runtime not in _RUNTIME_NAMES:
            raise ValueError("runtime is not supported")
        if self.model_provider not in _MODEL_PROVIDER_NAMES:
            raise ValueError("model provider is not supported")
        _require_identifier(self.model, "model", max_length=200)
        _require_content(
            self.input_text,
            "run input",
            max_bytes=_MAX_RUN_CONTENT_BYTES,
        )
        _require_digest(self.idempotency_key_digest, "idempotency key digest")
        _require_digest(self.request_digest, "request digest")
        status = _as_run_status(self.status)
        version = _require_nonnegative_int(self.version, "run version")
        created_at = _as_utc(self.created_at, "run created_at")
        updated_at = _as_utc(self.updated_at, "run updated_at")
        started_at = _as_optional_utc(self.started_at, "run started_at")
        finished_at = _as_optional_utc(self.finished_at, "run finished_at")

        if updated_at < created_at:
            raise ValueError("run updated_at must not precede created_at")
        if started_at is not None and (
            started_at < created_at or started_at > updated_at
        ):
            raise ValueError("run started_at is outside the run lifetime")
        if finished_at is not None and (
            finished_at < created_at or finished_at > updated_at
        ):
            raise ValueError("run finished_at is outside the run lifetime")

        if status is RunStatus.QUEUED:
            if version != 0 or started_at is not None:
                raise ValueError("a queued run must be an unstarted version zero")
        else:
            if version == 0:
                raise ValueError("a transitioned run requires a positive version")
        if status in {
            RunStatus.RUNNING,
            RunStatus.WAITING_APPROVAL,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
        }:
            if started_at is None:
                raise ValueError("an active run requires started_at")
        if (
            started_at is not None
            and finished_at is not None
            and finished_at < started_at
        ):
            raise ValueError("run finished_at must not precede started_at")

        if status is RunStatus.COMPLETED:
            if self.answer is None:
                raise ValueError("a completed run requires an answer")
            _require_content(
                self.answer,
                "run answer",
                max_bytes=_MAX_RUN_CONTENT_BYTES,
            )
            if self.failure is not None:
                raise ValueError("a completed run must not contain a failure")
        elif status in {RunStatus.FAILED, RunStatus.CANCELLED}:
            if self.failure is None:
                raise ValueError("a failed or cancelled run requires a failure")
            if self.answer is not None:
                raise ValueError("a failed or cancelled run must not contain an answer")
        elif self.answer is not None or self.failure is not None:
            raise ValueError("a non-terminal run must not contain an outcome")

        if status.is_terminal:
            if finished_at is None:
                raise ValueError("a terminal run requires finished_at")
        elif finished_at is not None:
            raise ValueError("a non-terminal run must not contain finished_at")

        object.__setattr__(self, "status", status)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "finished_at", finished_at)

    @classmethod
    def create(
        cls,
        *,
        run_id: str,
        session_id: str,
        owner_id: str,
        runtime: RuntimeName,
        input_text: str,
        idempotency_key: str,
        created_at: datetime,
        model_provider: ModelProviderName = "mock",
        model: str = "mock",
        request_options: Mapping[str, object] | None = None,
    ) -> RunRecord:
        _require_identifier(run_id, "run id")
        _require_identifier(session_id, "session id")
        _require_identifier(owner_id, "owner id")
        if runtime not in _RUNTIME_NAMES:
            raise ValueError("runtime is not supported")
        if model_provider not in _MODEL_PROVIDER_NAMES:
            raise ValueError("model provider is not supported")
        _require_identifier(model, "model", max_length=200)
        _require_content(
            input_text,
            "run input",
            max_bytes=_MAX_RUN_CONTENT_BYTES,
        )
        _require_secret_key(idempotency_key, "idempotency key")
        normalized_options = _normalize_json_mapping(
            {} if request_options is None else request_options,
            "request options",
            max_bytes=_MAX_EVENT_DATA_BYTES,
        )
        request_payload = {
            "schema": "run-request-v1",
            "session_id": session_id,
            "runtime": runtime,
            "model_provider": model_provider,
            "model": model,
            "input": input_text,
            "options": normalized_options,
        }
        return cls(
            id=run_id,
            session_id=session_id,
            owner_id=owner_id,
            runtime=runtime,
            model_provider=model_provider,
            model=model,
            input_text=input_text,
            idempotency_key_digest=_digest_text(idempotency_key),
            request_digest=_digest_json(request_payload),
            status=RunStatus.QUEUED,
            version=0,
            created_at=created_at,
            updated_at=created_at,
        )

    def transition_to(
        self,
        target_status: RunStatus | str,
        *,
        at: datetime,
        answer: str | None = None,
        failure: RunFailure | None = None,
        error_code: str | None = None,
        public_message: str | None = None,
    ) -> RunRecord:
        target = _as_run_status(target_status)
        if target not in _RUN_TRANSITIONS[self.status]:
            raise InvalidRunTransition()
        if target is not RunStatus.COMPLETED and answer is not None:
            raise ValueError("only a completed run may contain an answer")

        occurred_at = _as_utc(at, "run transition time")
        if occurred_at < self.updated_at:
            raise ValueError("run transition time must not move backwards")

        resolved_failure = failure
        if target in {RunStatus.FAILED, RunStatus.CANCELLED}:
            if failure is not None and (
                error_code is not None or public_message is not None
            ):
                raise ValueError("provide either failure or error fields")
            if resolved_failure is None:
                if error_code is None:
                    raise ValueError("a failed or cancelled run requires error_code")
                resolved_failure = RunFailure(
                    code=error_code,
                    category=(
                        "cancellation"
                        if target is RunStatus.CANCELLED
                        else "execution"
                    ),
                    public_message=public_message
                    or (
                        "Run cancelled"
                        if target is RunStatus.CANCELLED
                        else "Run failed"
                    ),
                )
        elif failure is not None or error_code is not None or public_message is not None:
            raise ValueError("only failed or cancelled runs may contain a failure")

        started_at = self.started_at
        if target is RunStatus.RUNNING and started_at is None:
            started_at = occurred_at
        return replace(
            self,
            status=target,
            version=self.version + 1,
            updated_at=occurred_at,
            started_at=started_at,
            finished_at=occurred_at if target.is_terminal else None,
            answer=answer if target is RunStatus.COMPLETED else None,
            failure=resolved_failure,
        )

    def safe_summary(self) -> dict[str, object]:
        """Return a log-safe projection without content or request digests."""
        return {
            "id": self.id,
            "session_id": self.session_id,
            "owner_id": self.owner_id,
            "runtime": self.runtime,
            "model_provider": self.model_provider,
            "model": self.model,
            "status": self.status.value,
            "version": self.version,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": (
                self.started_at.isoformat()
                if self.started_at is not None
                else None
            ),
            "finished_at": (
                self.finished_at.isoformat()
                if self.finished_at is not None
                else None
            ),
            "has_answer": self.answer is not None,
            "failure_code": self.failure.code if self.failure is not None else None,
        }


_RUN_TRANSITIONS: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.QUEUED: frozenset({RunStatus.RUNNING, RunStatus.CANCELLED}),
    RunStatus.RUNNING: frozenset(
        {
            RunStatus.WAITING_APPROVAL,
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.CANCELLED,
        }
    ),
    RunStatus.WAITING_APPROVAL: frozenset(
        {RunStatus.RUNNING, RunStatus.FAILED, RunStatus.CANCELLED}
    ),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.FAILED: frozenset(),
    RunStatus.CANCELLED: frozenset(),
}


@dataclass(frozen=True)
class StoredRunEvent:
    """One immutable event envelope with a mutable, detached JSON snapshot."""

    id: str
    run_id: str
    sequence: int
    type: str
    data: dict[str, object] = field(repr=False)
    created_at: datetime
    step: int = 0

    def __post_init__(self) -> None:
        _require_identifier(self.id, "event id")
        _require_identifier(self.run_id, "event run id")
        sequence = _require_positive_int(self.sequence, "event sequence")
        _require_event_type(self.type)
        step = _require_nonnegative_int(self.step, "event step")
        normalized_data = _normalize_json_mapping(
            self.data,
            "event data",
            max_bytes=_MAX_EVENT_DATA_BYTES,
        )
        created_at = _as_utc(self.created_at, "event created_at")

        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "step", step)
        object.__setattr__(self, "data", normalized_data)
        object.__setattr__(self, "created_at", created_at)

    def snapshot(self) -> StoredRunEvent:
        """Return an envelope whose nested JSON cannot mutate this instance."""
        return StoredRunEvent(
            id=self.id,
            run_id=self.run_id,
            sequence=self.sequence,
            type=self.type,
            step=self.step,
            data=self.data,
            created_at=self.created_at,
        )


@dataclass(frozen=True)
class UsageRecord:
    """Provider usage for exactly one model call within a Run."""

    id: str
    run_id: str
    sequence: int
    provider: str
    model: str
    input_tokens: int
    output_tokens: int
    total_tokens: int
    duration_ms: float
    estimated_cost_usd: Decimal | None
    cost_source: CostSource | str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_identifier(self.id, "usage id")
        _require_identifier(self.run_id, "usage run id")
        sequence = _require_positive_int(self.sequence, "usage sequence")
        _require_identifier(self.provider, "usage provider", max_length=100)
        _require_identifier(self.model, "usage model", max_length=200)
        input_tokens = _require_nonnegative_int(
            self.input_tokens,
            "usage input_tokens",
        )
        output_tokens = _require_nonnegative_int(
            self.output_tokens,
            "usage output_tokens",
        )
        total_tokens = _require_nonnegative_int(
            self.total_tokens,
            "usage total_tokens",
        )
        if total_tokens != input_tokens + output_tokens:
            raise ValueError(
                "usage total_tokens must equal input_tokens + output_tokens"
            )
        duration_ms = _require_nonnegative_number(
            self.duration_ms,
            "usage duration_ms",
        )
        try:
            cost_source = CostSource(self.cost_source)
        except (TypeError, ValueError):
            raise ValueError("usage cost_source is not supported") from None
        if self.estimated_cost_usd is None:
            if cost_source is not CostSource.UNKNOWN:
                raise ValueError("unknown usage cost requires unknown cost_source")
        else:
            if not isinstance(self.estimated_cost_usd, Decimal):
                raise ValueError("usage estimated cost must use Decimal")
            if (
                not self.estimated_cost_usd.is_finite()
                or self.estimated_cost_usd < 0
            ):
                raise ValueError("usage estimated cost must be finite and non-negative")
            if cost_source is CostSource.UNKNOWN:
                raise ValueError("known usage cost requires a known cost_source")
        created_at = _as_utc(self.created_at, "usage created_at")

        object.__setattr__(self, "sequence", sequence)
        object.__setattr__(self, "input_tokens", input_tokens)
        object.__setattr__(self, "output_tokens", output_tokens)
        object.__setattr__(self, "total_tokens", total_tokens)
        object.__setattr__(self, "duration_ms", duration_ms)
        object.__setattr__(self, "cost_source", cost_source)
        object.__setattr__(self, "created_at", created_at)


@dataclass(frozen=True)
class ToolExecution:
    """Durable tool-call metadata without raw arguments or unbounded output."""

    id: str
    run_id: str
    tool_call_id: str
    tool_name: str
    arguments_digest: str = field(repr=False)
    idempotency_key_digest: str | None = field(repr=False)
    side_effecting: bool
    status: ToolExecutionStatus
    version: int
    attempt: int
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    result_digest: str | None = field(default=None, repr=False)
    result_summary: str | None = field(default=None, repr=False)
    error_code: str | None = None
    public_message: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        _require_identifier(self.id, "tool execution id")
        _require_identifier(self.run_id, "tool execution run id")
        _require_identifier(self.tool_call_id, "tool call id")
        _require_identifier(self.tool_name, "tool name", max_length=200)
        _require_digest(self.arguments_digest, "tool arguments digest")
        if self.idempotency_key_digest is not None:
            _require_digest(
                self.idempotency_key_digest,
                "tool idempotency key digest",
            )
        if not isinstance(self.side_effecting, bool):
            raise ValueError("tool side_effecting must be a boolean")
        if self.side_effecting and self.idempotency_key_digest is None:
            raise ValueError("a side-effecting tool requires an idempotency key")
        status = _as_tool_status(self.status)
        version = _require_nonnegative_int(self.version, "tool version")
        attempt = _require_positive_int(self.attempt, "tool attempt")
        created_at = _as_utc(self.created_at, "tool created_at")
        updated_at = _as_utc(self.updated_at, "tool updated_at")
        started_at = _as_optional_utc(self.started_at, "tool started_at")
        finished_at = _as_optional_utc(self.finished_at, "tool finished_at")
        if updated_at < created_at:
            raise ValueError("tool updated_at must not precede created_at")
        if started_at is not None and (
            started_at < created_at or started_at > updated_at
        ):
            raise ValueError("tool started_at is outside the execution lifetime")
        if finished_at is not None and (
            finished_at < created_at or finished_at > updated_at
        ):
            raise ValueError("tool finished_at is outside the execution lifetime")
        if (
            started_at is not None
            and finished_at is not None
            and finished_at < started_at
        ):
            raise ValueError("tool finished_at must not precede started_at")
        if self.result_digest is not None:
            _require_digest(self.result_digest, "tool result digest")
        if self.result_summary is not None:
            _require_content(
                self.result_summary,
                "tool result summary",
                max_bytes=2_000,
            )
        if self.error_code is not None:
            _require_identifier(self.error_code, "tool error code", max_length=100)
        if self.public_message is not None:
            _require_content(
                self.public_message,
                "tool public message",
                max_bytes=2_000,
            )

        if status in {
            ToolExecutionStatus.RUNNING,
            ToolExecutionStatus.COMPLETED,
            ToolExecutionStatus.UNKNOWN,
        } and started_at is None:
            raise ValueError("a started tool execution requires started_at")
        if status is ToolExecutionStatus.PENDING:
            if version != 0:
                raise ValueError("a pending tool execution must be version zero")
        elif version == 0:
            raise ValueError("a transitioned tool execution requires a positive version")
        if status.is_terminal:
            if finished_at is None:
                raise ValueError("a terminal tool execution requires finished_at")
        elif finished_at is not None:
            raise ValueError("a non-terminal tool execution cannot be finished")

        if status is ToolExecutionStatus.COMPLETED:
            if self.result_digest is None or self.result_summary is None:
                raise ValueError("a completed tool execution requires a bounded result")
            if self.error_code is not None or self.public_message is not None:
                raise ValueError("a completed tool execution must not contain an error")
        elif status in {
            ToolExecutionStatus.FAILED,
            ToolExecutionStatus.CANCELLED,
            ToolExecutionStatus.UNKNOWN,
        }:
            if self.error_code is None:
                raise ValueError("an unsuccessful tool execution requires error_code")
            if self.result_digest is not None or self.result_summary is not None:
                raise ValueError("an unsuccessful tool execution cannot contain a result")
        elif any(
            value is not None
            for value in (
                self.result_digest,
                self.result_summary,
                self.error_code,
                self.public_message,
            )
        ):
            raise ValueError("a non-terminal tool execution cannot contain an outcome")

        object.__setattr__(self, "status", status)
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "attempt", attempt)
        object.__setattr__(self, "created_at", created_at)
        object.__setattr__(self, "updated_at", updated_at)
        object.__setattr__(self, "started_at", started_at)
        object.__setattr__(self, "finished_at", finished_at)

    @classmethod
    def create(
        cls,
        *,
        execution_id: str,
        run_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, object],
        created_at: datetime,
        side_effecting: bool = False,
        idempotency_key: str | None = None,
        attempt: int = 1,
    ) -> ToolExecution:
        normalized_arguments = _normalize_json_mapping(
            arguments,
            "tool arguments",
            max_bytes=_MAX_TOOL_DATA_BYTES,
        )
        if idempotency_key is not None:
            _require_secret_key(idempotency_key, "tool idempotency key")
        return cls(
            id=execution_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments_digest=_digest_json(normalized_arguments),
            idempotency_key_digest=(
                _digest_text(idempotency_key)
                if idempotency_key is not None
                else None
            ),
            side_effecting=side_effecting,
            status=ToolExecutionStatus.PENDING,
            version=0,
            attempt=attempt,
            created_at=created_at,
            updated_at=created_at,
        )

    def transition_to(
        self,
        target_status: ToolExecutionStatus | str,
        *,
        at: datetime,
        result: object = _MISSING,
        result_summary: str | None = None,
        error_code: str | None = None,
        public_message: str | None = None,
    ) -> ToolExecution:
        target = _as_tool_status(target_status)
        if target not in _TOOL_TRANSITIONS[self.status]:
            raise InvalidRunTransition()
        occurred_at = _as_utc(at, "tool transition time")
        if occurred_at < self.updated_at:
            raise ValueError("tool transition time must not move backwards")

        started_at = self.started_at
        if target is ToolExecutionStatus.RUNNING and started_at is None:
            started_at = occurred_at

        result_digest: str | None = None
        if target is ToolExecutionStatus.COMPLETED:
            if result_summary is None:
                raise ValueError("a completed tool execution requires result_summary")
            _require_content(
                result_summary,
                "tool result summary",
                max_bytes=2_000,
            )
            result_payload = (
                result
                if result is not _MISSING
                else {"safe_summary": result_summary}
            )
            normalized_result = _normalize_json_payload(
                result_payload,
                "tool result",
                max_bytes=_MAX_TOOL_DATA_BYTES,
            )
            result_digest = _digest_json(normalized_result)
        elif result is not _MISSING or result_summary is not None:
            raise ValueError("only a completed tool execution may contain a result")

        if target in {
            ToolExecutionStatus.FAILED,
            ToolExecutionStatus.CANCELLED,
            ToolExecutionStatus.UNKNOWN,
        }:
            if error_code is None:
                if target is ToolExecutionStatus.CANCELLED:
                    error_code = "tool_cancelled"
                else:
                    raise ValueError("an unsuccessful tool execution requires error_code")
        elif error_code is not None or public_message is not None:
            raise ValueError("only an unsuccessful tool execution may contain an error")

        return replace(
            self,
            status=target,
            version=self.version + 1,
            updated_at=occurred_at,
            started_at=started_at,
            finished_at=occurred_at if target.is_terminal else None,
            result_digest=result_digest,
            result_summary=(
                result_summary
                if target is ToolExecutionStatus.COMPLETED
                else None
            ),
            error_code=error_code,
            public_message=public_message,
        )

    def safe_summary(self) -> dict[str, object]:
        """Return metadata suitable for logs without arguments or results."""
        return {
            "id": self.id,
            "run_id": self.run_id,
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "side_effecting": self.side_effecting,
            "status": self.status.value,
            "version": self.version,
            "attempt": self.attempt,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "started_at": (
                self.started_at.isoformat()
                if self.started_at is not None
                else None
            ),
            "finished_at": (
                self.finished_at.isoformat()
                if self.finished_at is not None
                else None
            ),
            "error_code": self.error_code,
        }


_TOOL_TRANSITIONS: dict[ToolExecutionStatus, frozenset[ToolExecutionStatus]] = {
    ToolExecutionStatus.PENDING: frozenset(
        {
            ToolExecutionStatus.WAITING_APPROVAL,
            ToolExecutionStatus.RUNNING,
            ToolExecutionStatus.CANCELLED,
        }
    ),
    ToolExecutionStatus.WAITING_APPROVAL: frozenset(
        {
            ToolExecutionStatus.RUNNING,
            ToolExecutionStatus.FAILED,
            ToolExecutionStatus.CANCELLED,
        }
    ),
    ToolExecutionStatus.RUNNING: frozenset(
        {
            ToolExecutionStatus.COMPLETED,
            ToolExecutionStatus.FAILED,
            ToolExecutionStatus.CANCELLED,
            ToolExecutionStatus.UNKNOWN,
        }
    ),
    ToolExecutionStatus.COMPLETED: frozenset(),
    ToolExecutionStatus.FAILED: frozenset(),
    ToolExecutionStatus.CANCELLED: frozenset(),
    ToolExecutionStatus.UNKNOWN: frozenset(),
}


def _as_run_status(value: RunStatus | str) -> RunStatus:
    try:
        return RunStatus(value)
    except (TypeError, ValueError):
        raise ValueError("run status is not supported") from None


def _as_tool_status(value: ToolExecutionStatus | str) -> ToolExecutionStatus:
    try:
        return ToolExecutionStatus(value)
    except (TypeError, ValueError):
        raise ValueError("tool execution status is not supported") from None


def _require_identifier(
    value: object,
    label: str,
    *,
    max_length: int = 200,
) -> str:
    if not isinstance(value, str) or not value or len(value) > max_length:
        raise ValueError(f"{label} has an invalid format")
    if value != value.strip() or any(
        character.isspace()
        or unicodedata.category(character).startswith("C")
        for character in value
    ):
        raise ValueError(f"{label} has an invalid format")
    return value


def _require_event_type(value: object) -> str:
    event_type = _require_identifier(value, "event type", max_length=100)
    if _EVENT_TYPE_PATTERN.fullmatch(event_type) is None:
        raise ValueError("event type must use lowercase dot-separated segments")
    return event_type


def _require_content(
    value: object,
    label: str,
    *,
    max_bytes: int,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must not be empty")
    try:
        content_size = len(value.encode("utf-8"))
    except UnicodeError:
        raise ValueError(f"{label} contains invalid Unicode") from None
    if content_size > max_bytes:
        raise ValueError(f"{label} exceeds the size limit")
    return value


def _require_secret_key(value: object, label: str) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{label} has an invalid format")
    try:
        key_size = len(value.encode("utf-8"))
    except UnicodeError:
        raise ValueError(f"{label} has an invalid format") from None
    if key_size > 512 or any(
        character.isspace()
        or unicodedata.category(character).startswith("C")
        for character in value
    ):
        raise ValueError(f"{label} has an invalid format")
    return value


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{label} must be a SHA-256 digest")
    return value


def _require_nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _require_positive_int(value: object, label: str) -> int:
    result = _require_nonnegative_int(value, label)
    if result == 0:
        raise ValueError(f"{label} must be positive")
    return result


def _require_nonnegative_number(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{label} must be a finite non-negative number")
    result = float(value)
    if not math.isfinite(result) or result < 0:
        raise ValueError(f"{label} must be a finite non-negative number")
    return result


def _as_utc(value: object, label: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _as_optional_utc(value: object, label: str) -> datetime | None:
    return None if value is None else _as_utc(value, label)


def _digest_text(value: str) -> str:
    try:
        payload = value.encode("utf-8")
    except UnicodeError:
        raise ValueError("digest input contains invalid Unicode") from None
    return hashlib.sha256(payload).hexdigest()


def _digest_json(value: object) -> str:
    try:
        payload = json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        payload.encode("utf-8")
    except (TypeError, UnicodeError, ValueError):
        raise ValueError("digest input must be canonical JSON") from None
    return _digest_text(payload)


def _normalize_json_mapping(
    value: object,
    label: str,
    *,
    max_bytes: int,
) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    normalized = _normalize_json_payload(
        value,
        label,
        max_bytes=max_bytes,
    )
    if not isinstance(normalized, dict):
        raise ValueError(f"{label} must be a JSON object")
    return normalized


def _normalize_json_payload(
    value: object,
    label: str,
    *,
    max_bytes: int,
) -> object:
    try:
        normalized = _normalize_json_value(value, set())
        payload = json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        payload_size = len(payload.encode("utf-8"))
    except (RecursionError, TypeError, UnicodeError, ValueError):
        raise ValueError(f"{label} must contain bounded JSON values") from None
    if payload_size > max_bytes:
        raise ValueError(f"{label} exceeds the size limit")
    return normalized


def _normalize_json_value(
    value: object,
    active_ids: set[int],
    depth: int = 0,
    node_count: list[int] | None = None,
) -> object:
    if node_count is None:
        node_count = [0]
    node_count[0] += 1
    if depth > _MAX_JSON_DEPTH or node_count[0] > _MAX_JSON_NODES:
        raise ValueError("JSON value exceeds structural limits")
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("JSON numbers must be finite")
        return value
    if isinstance(value, Mapping):
        container_id = id(value)
        if container_id in active_ids:
            raise ValueError("JSON values must not be cyclic")
        active_ids.add(container_id)
        try:
            normalized: dict[str, object] = {}
            for key, item in value.items():
                if not isinstance(key, str):
                    raise ValueError("JSON object keys must be strings")
                normalized[key] = _normalize_json_value(
                    item,
                    active_ids,
                    depth + 1,
                    node_count,
                )
            return normalized
        finally:
            active_ids.remove(container_id)
    if isinstance(value, (list, tuple)):
        container_id = id(value)
        if container_id in active_ids:
            raise ValueError("JSON values must not be cyclic")
        active_ids.add(container_id)
        try:
            return [
                _normalize_json_value(
                    item,
                    active_ids,
                    depth + 1,
                    node_count,
                )
                for item in value
            ]
        finally:
            active_ids.remove(container_id)
    raise ValueError("value is not JSON serializable")
