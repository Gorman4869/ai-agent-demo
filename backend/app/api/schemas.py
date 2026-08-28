from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class HealthResponse(BaseModel):
    status: Literal["ok"]


class SessionResponse(BaseModel):
    id: str
    created_at: datetime
    access_token: str | None = None


class RunRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4_000)
    timeout_ms: int = Field(default=30_000, ge=100, le=120_000)


class RunResponse(BaseModel):
    id: str
    session_id: str
    status: Literal["completed", "failed"]
    answer: str | None
    event_types: list[str]
    error: str | None = None


class DurableRunRequest(BaseModel):
    """Public input for the M12 durable Run API."""

    message: str = Field(min_length=1, max_length=4_000)
    session_id: str | None = Field(default=None, min_length=1, max_length=200)

    @field_validator("message")
    @classmethod
    def validate_message(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("message must not be blank")
        return value

    @field_validator("session_id")
    @classmethod
    def validate_session_id(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if value != value.strip() or any(
            character.isspace() or not character.isprintable()
            for character in value
        ):
            raise ValueError("session_id has an invalid format")
        return value


class DurableRunErrorResponse(BaseModel):
    code: str
    category: str
    retryable: bool


class DurableRunResponse(BaseModel):
    id: str
    run_id: str
    session_id: str
    status: Literal[
        "queued",
        "running",
        "waiting_approval",
        "completed",
        "failed",
        "cancelled",
    ]
    answer: str | None = None
    citations: list[EvidenceResponse] = Field(default_factory=list)
    usage: ModelUsageResponse | None = None
    error: DurableRunErrorResponse | None = None
    created_at: datetime
    updated_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    session_capability: str | None = None


class ApprovalDecisionRequest(BaseModel):
    decision: Literal["approve", "reject"]


class DocumentRequest(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100_000)
    source: str = Field(min_length=1, max_length=500)


class DocumentResponse(BaseModel):
    id: str
    chunk_count: int


class ResearchRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4_000)

    @field_validator("question")
    @classmethod
    def validate_question(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("question must not be blank")
        return value


class EvidenceResponse(BaseModel):
    title: str
    source: str
    excerpt: str
    score: float


class ResearchResponse(BaseModel):
    approved: bool
    answer: str
    critique: str
    evidence: list[EvidenceResponse]


class MemoryRequest(BaseModel):
    key: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=2_000)
    scope: Literal["session", "user"]
    approved: bool = False


class MemoryResponse(BaseModel):
    id: str
    owner_id: str
    key: str
    value: str
    scope: Literal["session", "user"]


class MemoryFactResponse(MemoryResponse):
    version: int = Field(ge=0)


class MemoryCorrectionRequest(BaseModel):
    expected_version: int = Field(ge=0)
    value: str = Field(min_length=1, max_length=2_000)
    approved: bool = False

    @field_validator("value")
    @classmethod
    def validate_value(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("value must not be blank")
        return value


class MemoryFactAuditResponse(BaseModel):
    fact_id: str
    version: int = Field(ge=0)
    action: Literal["created", "corrected", "deleted"]
    value_digest: str = Field(
        min_length=64,
        max_length=64,
        pattern=r"^[0-9a-f]{64}$",
    )


class RunErrorResponse(BaseModel):
    category: str
    event_type: str | None
    step: int | None


class ModelUsageResponse(BaseModel):
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: float | None


class RunObservationResponse(BaseModel):
    run_id: str
    status: str
    duration_ms: float
    event_count: int
    event_counts: dict[str, int]
    model_duration_ms: float
    tool_duration_ms: float
    tool_durations_ms: dict[str, float]
    usage: ModelUsageResponse | None
    error_count: int
    errors: list[RunErrorResponse]


class EvalFailureResponse(BaseModel):
    check: str
    expected: str
    actual: str


class EvalCaseResponse(BaseModel):
    case_id: str
    passed: bool
    observation: RunObservationResponse
    failures: list[EvalFailureResponse]


class EvalReportResponse(BaseModel):
    batch_id: str
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate: float
    results: list[EvalCaseResponse]
