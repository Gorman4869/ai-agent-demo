from __future__ import annotations

import asyncio
import hashlib
import json
import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from types import MappingProxyType
from typing import Literal, Protocol, cast

from backend.app.advanced.review_tools import (
    MULTISOURCE_REVIEW_VERSION,
    REVIEW_TOOL_NAMES,
    AsyncReviewToolRegistry,
    ReviewDecision,
    ReviewImageEvidence,
    ReviewPageEvidence,
    ReviewPolicyEvidence,
    ReviewPublicationResult,
    ReviewPublisher,
    ReviewScenarioLimits,
    create_review_publication_command,
)
from backend.app.advanced.review_publication import ReviewPublicationStore
from backend.app.agent import (
    RuntimeApprovalDecision,
    RuntimeApprovalPause,
    RuntimeApprovalResume,
    RuntimeControl,
    RuntimeEvent,
    RuntimeEventSink,
    RuntimeOutcome,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.domain.run import (
    RunFailure,
    RunStatus,
    ToolExecution,
    ToolExecutionStatus,
)
from backend.app.reliability import stable_run_failure
from backend.app.stores import ConcurrentWriteError, ToolExecutionStore
from backend.app.tools import ToolExecutionContext, ToolHandlerError, ToolResult


REVIEW_EVIDENCE_SCHEMA = "review-evidence-v1"
REVIEW_SOURCE_ORDER = ("image", "policy", "page")

_RESOURCE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}")
_REVIEW_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_RUN_BINDINGS = 32
_MAX_POLICY_TOPIC_BYTES = 512
_MAX_CITATION_REFS = 3

ReviewSourceKind = Literal["image", "policy", "page"]
ReviewEvidenceStatus = Literal["verified", "degraded"]


@dataclass(frozen=True)
class ReviewRunSpec:
    """Trusted application-owned inputs for one review Run."""

    review_id: str
    expected_revision: int
    image_asset_id: str
    policy_topic: str = field(repr=False)
    page_fixture_id: str
    requested_decision: ReviewDecision
    scenario_version: Literal["multisource-review-v1"] = (
        MULTISOURCE_REVIEW_VERSION
    )

    def __post_init__(self) -> None:
        _require_identifier(self.review_id, _REVIEW_ID, "review id")
        if (
            isinstance(self.expected_revision, bool)
            or not isinstance(self.expected_revision, int)
            or self.expected_revision < 1
        ):
            raise ValueError("review expected revision must be positive")
        _require_identifier(
            self.image_asset_id,
            _RESOURCE_ID,
            "image asset id",
        )
        _require_identifier(
            self.page_fixture_id,
            _RESOURCE_ID,
            "page fixture id",
        )
        if (
            not isinstance(self.policy_topic, str)
            or not self.policy_topic
            or self.policy_topic != self.policy_topic.strip()
            or len(self.policy_topic.encode("utf-8")) > _MAX_POLICY_TOPIC_BYTES
        ):
            raise ValueError("review policy topic is invalid")
        if self.requested_decision not in {
            "approve",
            "reject",
            "needs_review",
        }:
            raise ValueError("review decision is invalid")
        if self.scenario_version != MULTISOURCE_REVIEW_VERSION:
            raise ValueError("review scenario version is invalid")


@dataclass(frozen=True)
class ReviewRunBinding:
    run_id: str
    owner_id: str = field(repr=False)
    spec: ReviewRunSpec = field(repr=False)

    def __post_init__(self) -> None:
        _require_scope_identifier(self.run_id, "review run id")
        _require_scope_identifier(self.owner_id, "review owner id")
        if not isinstance(self.spec, ReviewRunSpec):
            raise ValueError("review run spec is invalid")


class ReviewRunCatalog:
    """Immutable owner-scoped request lookup keyed by durable Run ID."""

    def __init__(self, bindings: Mapping[str, ReviewRunBinding]) -> None:
        if not isinstance(bindings, Mapping):
            raise TypeError("review run bindings must use a mapping")
        if len(bindings) < 1 or len(bindings) > _MAX_RUN_BINDINGS:
            raise ValueError("review run bindings must be bounded and non-empty")
        copied: dict[str, ReviewRunBinding] = {}
        for run_id, binding in bindings.items():
            if not isinstance(binding, ReviewRunBinding) or run_id != binding.run_id:
                raise ValueError("review run binding mapping is invalid")
            copied[run_id] = binding
        self._bindings = MappingProxyType(copied)

    def resolve(self, run_id: str, *, owner_id: str) -> ReviewRunSpec | None:
        binding = self._bindings.get(run_id)
        if binding is None or binding.owner_id != owner_id:
            return None
        return binding.spec


@dataclass(frozen=True)
class ReviewEvidenceRecord:
    review_id: str
    source_kind: ReviewSourceKind
    source_ref: str
    content_sha256: str
    content_bytes: int
    trust: str
    status: ReviewEvidenceStatus
    citation_refs: tuple[str, ...] = ()
    schema: Literal["review-evidence-v1"] = REVIEW_EVIDENCE_SCHEMA

    def __post_init__(self) -> None:
        _require_identifier(self.review_id, _REVIEW_ID, "review id")
        if self.source_kind not in REVIEW_SOURCE_ORDER:
            raise ValueError("review evidence source kind is invalid")
        _require_identifier(
            self.source_ref,
            _SHA256 if self.source_kind == "policy" else _RESOURCE_ID,
            "evidence source ref",
        )
        _require_identifier(self.content_sha256, _SHA256, "evidence digest")
        if (
            isinstance(self.content_bytes, bool)
            or not isinstance(self.content_bytes, int)
            or self.content_bytes < 0
        ):
            raise ValueError("review evidence byte count is invalid")
        expected_trust = {
            "image": "untrusted_visual_data",
            "policy": "retrieved_policy_data",
            "page": "untrusted_page_data",
        }[self.source_kind]
        if self.trust != expected_trust:
            raise ValueError("review evidence trust is invalid")
        if self.status not in {"verified", "degraded"}:
            raise ValueError("review evidence status is invalid")
        if self.source_kind != "image" and self.status != "verified":
            raise ValueError("only image evidence may be degraded")
        if (
            not isinstance(self.citation_refs, tuple)
            or len(self.citation_refs) > _MAX_CITATION_REFS
        ):
            raise ValueError("review evidence citation refs are invalid")
        for citation_ref in self.citation_refs:
            _require_scope_identifier(citation_ref, "citation ref")
        if self.schema != REVIEW_EVIDENCE_SCHEMA:
            raise ValueError("review evidence schema is invalid")

    def event_data(self) -> dict[str, object]:
        data: dict[str, object] = {
            "schema": self.schema,
            "review_id": self.review_id,
            "source_kind": self.source_kind,
            "source_ref": self.source_ref,
            "content_sha256": self.content_sha256,
            "content_bytes": self.content_bytes,
            "trust": self.trust,
            "status": self.status,
        }
        if self.citation_refs:
            data["citation_refs"] = list(self.citation_refs)
        return data


@dataclass(frozen=True)
class ReviewEvidenceBundle:
    review_id: str
    records: tuple[ReviewEvidenceRecord, ...] = field(repr=False)
    digest: str = field(init=False)
    schema: Literal["review-evidence-bundle-v1"] = (
        "review-evidence-bundle-v1"
    )

    def __post_init__(self) -> None:
        _require_identifier(self.review_id, _REVIEW_ID, "review id")
        if self.schema != "review-evidence-bundle-v1":
            raise ValueError("review evidence bundle schema is invalid")
        if (
            not isinstance(self.records, tuple)
            or not all(
                isinstance(record, ReviewEvidenceRecord)
                for record in self.records
            )
            or tuple(record.source_kind for record in self.records)
            != REVIEW_SOURCE_ORDER
            or any(record.review_id != self.review_id for record in self.records)
        ):
            raise ValueError("review evidence bundle is invalid")
        encoded = _canonical_json_bytes(
            {
                "schema": self.schema,
                "scenario_version": MULTISOURCE_REVIEW_VERSION,
                "review_id": self.review_id,
                "records": [record.event_data() for record in self.records],
            }
        )
        object.__setattr__(self, "digest", hashlib.sha256(encoded).hexdigest())


class ReviewBudgetExceeded(RuntimeError):
    code = "review_budget_exceeded"

    def __init__(self) -> None:
        super().__init__(self.code)


class ReviewToolCallBudget:
    """Per-invocation call ledger for the fixed four-tool scenario."""

    def __init__(self, limits: ReviewScenarioLimits) -> None:
        if not isinstance(limits, ReviewScenarioLimits):
            raise TypeError("review scenario limits are required")
        self._limits = limits
        self._counts: dict[str, int] = {}
        self._total = 0
        self._side_effects = 0

    @property
    def total(self) -> int:
        return self._total

    @property
    def side_effects(self) -> int:
        return self._side_effects

    def count(self, tool_name: str) -> int:
        return self._counts.get(tool_name, 0)

    def claim(self, tool_name: str, *, side_effect: bool = False) -> None:
        if tool_name not in REVIEW_TOOL_NAMES:
            raise ReviewBudgetExceeded()
        next_total = self._total + 1
        next_count = self.count(tool_name) + 1
        next_side_effects = self._side_effects + int(side_effect)
        if (
            next_total > self._limits.max_tool_calls
            or next_count > self._limits.max_calls_per_tool
            or next_side_effects > self._limits.max_side_effect_calls
        ):
            raise ReviewBudgetExceeded()
        self._total = next_total
        self._counts[tool_name] = next_count
        self._side_effects = next_side_effects


class ReviewRuntimeRegistry(Protocol):
    @property
    def limits(self) -> ReviewScenarioLimits: ...

    @property
    def publisher(self) -> ReviewPublisher: ...

    async def execute(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        context: ToolExecutionContext | None = None,
        call_id: str | None = None,
    ) -> ToolResult: ...


class MultisourceReviewRuntime:
    """Prepare one same-Run evidence bundle and pause before publication."""

    def __init__(
        self,
        *,
        registry: ReviewRuntimeRegistry,
        run_catalog: ReviewRunCatalog,
        tool_execution_store: ToolExecutionStore,
        approval_ttl: timedelta = timedelta(minutes=15),
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(registry, AsyncReviewToolRegistry) and not (
            hasattr(registry, "execute")
            and hasattr(registry, "limits")
            and hasattr(registry, "publisher")
        ):
            raise TypeError("review runtime registry is invalid")
        if not isinstance(run_catalog, ReviewRunCatalog):
            raise TypeError("review run catalog is invalid")
        if not (
            hasattr(tool_execution_store, "create")
            and hasattr(tool_execution_store, "get")
            and hasattr(tool_execution_store, "transition")
        ):
            raise TypeError("review tool execution store is invalid")
        if not hasattr(registry.publisher, "reconcile"):
            raise TypeError("review publication store is invalid")
        if not isinstance(approval_ttl, timedelta) or approval_ttl <= timedelta(0):
            raise ValueError("review approval ttl must be positive")
        self._registry = registry
        self._run_catalog = run_catalog
        self._tool_execution_store = tool_execution_store
        self._publication_store = cast(ReviewPublicationStore, registry.publisher)
        self._approval_ttl = approval_ttl
        self._clock = clock or (lambda: datetime.now(UTC))

    async def run(
        self,
        request: RuntimeRequest,
        *,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeOutcome:
        context = _review_execution_context(request)
        if context is None:
            return _failed_result("review_evidence_invalid", step=0)
        approval_store = context.approval_store
        if approval_store is None:
            return _authorization_failure("approval_context_required", step=0)
        spec = self._run_catalog.resolve(
            request.run_id,
            owner_id=context.principal_id,
        )
        if spec is None:
            return _failed_result("review_asset_not_found", step=0)
        if control.cancellation_token.is_cancelled:
            return _cancelled_result(control, step=0)

        budget = ReviewToolCallBudget(self._registry.limits)
        records: list[ReviewEvidenceRecord] = []
        calls = (
            ("inspect_image", {"image_asset_id": spec.image_asset_id}),
            ("search_review_policy", {"policy_topic": spec.policy_topic}),
            ("read_fixture_page", {"page_fixture_id": spec.page_fixture_id}),
        )
        for step, (tool_name, arguments) in enumerate(calls, start=1):
            if control.cancellation_token.is_cancelled:
                return _cancelled_result(control, step=step - 1)
            try:
                budget.claim(tool_name)
            except ReviewBudgetExceeded:
                return _failed_result("review_budget_exceeded", step=step)
            result = await self._registry.execute(
                tool_name,
                arguments,
                context=context,
                call_id=_tool_call_id(request.run_id, tool_name),
            )
            if not result.ok:
                return _tool_failure_result(result, step=step)
            try:
                record = _evidence_record(
                    review_id=spec.review_id,
                    tool_name=tool_name,
                    value=result.value,
                )
            except (TypeError, ValueError):
                return _failed_result("review_evidence_invalid", step=step)
            records.append(record)
            await emit(
                RuntimeEvent(
                    type="review.evidence.recorded",
                    step=step,
                    data=record.event_data(),
                )
            )
            if (
                tool_name == "inspect_image"
                and record.status == "degraded"
                and spec.requested_decision == "approve"
            ):
                return _failed_result("review_evidence_invalid", step=step)

        try:
            bundle = ReviewEvidenceBundle(spec.review_id, tuple(records))
            budget.claim("publish_review", side_effect=True)
        except (ReviewBudgetExceeded, TypeError, ValueError):
            return _failed_result("review_budget_exceeded", step=4)
        arguments: dict[str, object] = {
            "review_id": spec.review_id,
            "expected_revision": spec.expected_revision,
            "requested_decision": spec.requested_decision,
            "evidence_bundle_digest": bundle.digest,
        }
        call_id = _publish_call_id(request.run_id, bundle.digest)
        try:
            command = create_review_publication_command(arguments, context)
            candidate = _new_tool_execution(
                request.run_id,
                call_id=call_id,
                arguments=arguments,
                idempotency_key=command.idempotency_key,
                created_at=self._clock(),
            )
            created = await self._tool_execution_store.create(
                candidate,
                owner_id=context.principal_id,
            )
        except (TypeError, ValueError):
            return _failed_result("review_evidence_invalid", step=4)
        try:
            approval = approval_store.request(
                run_id=request.run_id,
                principal_id=context.principal_id,
                tool_call_id=call_id,
                tool_name="publish_review",
                arguments=arguments,
                expires_in=self._approval_ttl,
            )
        except ValueError:
            if created.record.status is ToolExecutionStatus.PENDING:
                await self._tool_execution_store.transition(
                    created.record.id,
                    owner_id=context.principal_id,
                    expected_version=created.record.version,
                    target_status=ToolExecutionStatus.CANCELLED,
                    error_code="review_evidence_invalid",
                    public_message="Review approval request could not be created",
                )
            return _failed_result("review_evidence_invalid", step=4)
        execution = created.record
        if execution.status is ToolExecutionStatus.PENDING:
            execution = await self._tool_execution_store.transition(
                execution.id,
                owner_id=context.principal_id,
                expected_version=execution.version,
                target_status=ToolExecutionStatus.WAITING_APPROVAL,
            )
        if execution.status is not ToolExecutionStatus.WAITING_APPROVAL:
            return _failed_result("review_evidence_invalid", step=4)
        return RuntimeApprovalPause(
            approval_id=approval.id,
            tool_call_id=approval.tool_call_id,
            tool_name=approval.tool_name,
            arguments_digest=approval.arguments_digest,
            expires_at=approval.expires_at,
            step=4,
        )

    async def resume(
        self,
        request: RuntimeRequest,
        *,
        approval: RuntimeApprovalResume,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeOutcome:
        context = _review_execution_context(request)
        if context is None or context.approval_store is None:
            return _authorization_failure("approval_context_required", step=4)
        spec = self._run_catalog.resolve(
            request.run_id,
            owner_id=context.principal_id,
        )
        if spec is None:
            return _failed_result("review_asset_not_found", step=4)
        resolution = context.approval_store.get_resolution(
            approval_id=approval.approval_id,
            run_id=request.run_id,
            principal_id=context.principal_id,
        )
        if resolution is None or not _approval_matches(approval, resolution):
            return _approval_resolution_failure(step=4)
        execution = await self._tool_execution_store.get(
            _execution_id(approval.tool_call_id),
            owner_id=context.principal_id,
        )
        if execution is None or not _execution_matches_approval(
            execution,
            request.run_id,
            approval,
        ):
            return _failed_result("review_evidence_invalid", step=4)
        if approval.decision is RuntimeApprovalDecision.REJECTED:
            return await self._settle_approval_failure(
                execution,
                owner_id=context.principal_id,
                code="approval_rejected",
                public_message="Review publication was rejected",
            )
        if approval.decision is RuntimeApprovalDecision.EXPIRED:
            return await self._settle_approval_failure(
                execution,
                owner_id=context.principal_id,
                code="approval_expired",
                public_message="Review publication approval expired",
            )
        try:
            arguments = context.approval_store.approved_arguments(resolution)
            if not _arguments_match_spec(arguments, spec):
                return _failed_result("review_evidence_invalid", step=4)
            command = create_review_publication_command(arguments, context)
            candidate = _new_tool_execution(
                request.run_id,
                call_id=approval.tool_call_id,
                arguments=arguments,
                idempotency_key=command.idempotency_key,
                created_at=execution.created_at,
            )
        except (TypeError, ValueError):
            return _failed_result("review_evidence_invalid", step=4)
        if not _execution_matches_candidate(execution, candidate):
            return _failed_result("review_evidence_invalid", step=4)
        if execution.status is ToolExecutionStatus.COMPLETED:
            try:
                publication = await self._publication_store.reconcile(command)
            except (ToolHandlerError, TimeoutError, OSError):
                publication = None
            if publication is None:
                return _failed_result("tool_result_unknown", step=4)
            return await _published_result(
                spec,
                command.evidence_bundle_digest,
                publication,
                emit=emit,
            )
        if execution.status is ToolExecutionStatus.UNKNOWN:
            return _failed_result("tool_result_unknown", step=4)
        if execution.status in {
            ToolExecutionStatus.FAILED,
            ToolExecutionStatus.CANCELLED,
        }:
            return _execution_failure_result(execution, step=4)
        if execution.status is not ToolExecutionStatus.WAITING_APPROVAL:
            return _failed_result("review_evidence_invalid", step=4)
        if control.cancellation_token.is_cancelled:
            await self._tool_execution_store.transition(
                execution.id,
                owner_id=context.principal_id,
                expected_version=execution.version,
                target_status=ToolExecutionStatus.CANCELLED,
                error_code="tool_cancelled",
                public_message="Review publication was cancelled",
            )
            return _cancelled_result(control, step=4)
        try:
            running = await self._tool_execution_store.transition(
                execution.id,
                owner_id=context.principal_id,
                expected_version=execution.version,
                target_status=ToolExecutionStatus.RUNNING,
            )
        except ConcurrentWriteError:
            winner = await self._tool_execution_store.get(
                execution.id,
                owner_id=context.principal_id,
            )
            if winner is not None and winner.status is ToolExecutionStatus.COMPLETED:
                try:
                    publication = await self._publication_store.reconcile(command)
                except (ToolHandlerError, TimeoutError, OSError):
                    publication = None
                if publication is not None:
                    return await _published_result(
                        spec,
                        command.evidence_bundle_digest,
                        publication,
                        emit=emit,
                    )
            return _failed_result("tool_result_unknown", step=4)
        try:
            result = await self._registry.execute(
                "publish_review",
                arguments,
                context=context,
                call_id=approval.tool_call_id,
            )
        except asyncio.CancelledError:
            await self._settle_unknown(running, owner_id=context.principal_id)
            raise
        if result.ok and isinstance(result.value, ReviewPublicationResult):
            publication = result.value
        elif result.result_unknown:
            try:
                publication = await self._publication_store.reconcile(command)
            except (ToolHandlerError, TimeoutError, OSError):
                publication = None
            if publication is None:
                await self._settle_unknown(
                    running,
                    owner_id=context.principal_id,
                )
                return _failed_result("tool_result_unknown", step=4)
        else:
            code = result.error_code or "review_evidence_invalid"
            failed = await self._tool_execution_store.transition(
                running.id,
                owner_id=context.principal_id,
                expected_version=running.version,
                target_status=ToolExecutionStatus.FAILED,
                error_code=code,
                public_message="Review publication failed",
            )
            return _execution_failure_result(failed, step=4)
        completed = await self._tool_execution_store.transition(
            running.id,
            owner_id=context.principal_id,
            expected_version=running.version,
            target_status=ToolExecutionStatus.COMPLETED,
            result={
                "publication_id": publication.publication_id,
                "revision": publication.revision,
                "status": publication.status,
                "evidence_bundle_digest": command.evidence_bundle_digest,
            },
            result_summary="review publication confirmed",
        )
        if completed.status is not ToolExecutionStatus.COMPLETED:
            return _failed_result("tool_result_unknown", step=4)
        return await _published_result(
            spec,
            command.evidence_bundle_digest,
            publication,
            emit=emit,
        )

    async def _settle_approval_failure(
        self,
        execution: ToolExecution,
        *,
        owner_id: str,
        code: str,
        public_message: str,
    ) -> RuntimeResult:
        if execution.status is ToolExecutionStatus.WAITING_APPROVAL:
            execution = await self._tool_execution_store.transition(
                execution.id,
                owner_id=owner_id,
                expected_version=execution.version,
                target_status=ToolExecutionStatus.FAILED,
                error_code=code,
                public_message=public_message,
            )
        return _execution_failure_result(execution, step=4)

    async def _settle_unknown(
        self,
        execution: ToolExecution,
        *,
        owner_id: str,
    ) -> ToolExecution:
        return await self._tool_execution_store.transition(
            execution.id,
            owner_id=owner_id,
            expected_version=execution.version,
            target_status=ToolExecutionStatus.UNKNOWN,
            error_code="tool_result_unknown",
            public_message="Review publication result could not be confirmed",
        )


def _new_tool_execution(
    run_id: str,
    *,
    call_id: str,
    arguments: Mapping[str, object],
    idempotency_key: str,
    created_at: datetime,
) -> ToolExecution:
    return ToolExecution.create(
        execution_id=_execution_id(call_id),
        run_id=run_id,
        tool_call_id=call_id,
        tool_name="publish_review",
        arguments=arguments,
        created_at=created_at,
        side_effecting=True,
        idempotency_key=idempotency_key,
    )


def _execution_id(call_id: str) -> str:
    return f"review-execution-{_length_prefixed_digest(call_id)[:32]}"


def _approval_matches(approval: RuntimeApprovalResume, resolution: object) -> bool:
    request = getattr(resolution, "request", None)
    status = getattr(resolution, "status", None)
    return (
        request is not None
        and request.id == approval.approval_id
        and request.tool_call_id == approval.tool_call_id
        and request.tool_name == approval.tool_name
        and request.arguments_digest == approval.arguments_digest
        and getattr(status, "value", None) == approval.decision.value
    )


def _execution_matches_approval(
    execution: ToolExecution,
    run_id: str,
    approval: RuntimeApprovalResume,
) -> bool:
    return (
        execution.run_id == run_id
        and execution.tool_call_id == approval.tool_call_id
        and execution.tool_name == approval.tool_name
        and execution.arguments_digest == approval.arguments_digest
        and execution.side_effecting
    )


def _execution_matches_candidate(
    execution: ToolExecution,
    candidate: ToolExecution,
) -> bool:
    return (
        execution.id == candidate.id
        and execution.run_id == candidate.run_id
        and execution.tool_call_id == candidate.tool_call_id
        and execution.tool_name == candidate.tool_name
        and execution.arguments_digest == candidate.arguments_digest
        and execution.idempotency_key_digest
        == candidate.idempotency_key_digest
        and execution.side_effecting == candidate.side_effecting
    )


def _arguments_match_spec(
    arguments: Mapping[str, object],
    spec: ReviewRunSpec,
) -> bool:
    return (
        set(arguments)
        == {
            "review_id",
            "expected_revision",
            "requested_decision",
            "evidence_bundle_digest",
        }
        and arguments.get("review_id") == spec.review_id
        and arguments.get("expected_revision") == spec.expected_revision
        and arguments.get("requested_decision") == spec.requested_decision
        and isinstance(arguments.get("evidence_bundle_digest"), str)
        and _SHA256.fullmatch(arguments["evidence_bundle_digest"]) is not None
    )


def _approval_resolution_failure(*, step: int) -> RuntimeResult:
    return RuntimeResult(
        status=RunStatus.FAILED,
        failure=RunFailure(
            code="approval_resolution_invalid",
            category="authorization",
            public_message="Review publication approval is invalid",
            step=step,
        ),
        step=step,
    )


def _execution_failure_result(
    execution: ToolExecution,
    *,
    step: int,
) -> RuntimeResult:
    code = execution.error_code or "review_evidence_invalid"
    if code in {"approval_rejected", "approval_expired", "tool_cancelled"}:
        category = (
            "cancellation" if code == "tool_cancelled" else "authorization"
        )
        public_message = execution.public_message or "Review publication stopped"
        failure = RunFailure(
            code=code,
            category=category,
            public_message=public_message,
            step=step,
        )
    else:
        try:
            failure = stable_run_failure(code, step=step)
        except ValueError:
            failure = stable_run_failure("review_evidence_invalid", step=step)
    return RuntimeResult(status=RunStatus.FAILED, failure=failure, step=step)


async def _published_result(
    spec: ReviewRunSpec,
    evidence_bundle_digest: str,
    publication: ReviewPublicationResult,
    *,
    emit: RuntimeEventSink,
) -> RuntimeResult:
    data: dict[str, object] = {
        "schema": "review-result-v1",
        "scenario_version": MULTISOURCE_REVIEW_VERSION,
        "review_id": spec.review_id,
        "outcome": "published",
        "evidence_refs": [
            spec.image_asset_id,
            hashlib.sha256(spec.policy_topic.encode("utf-8")).hexdigest(),
            spec.page_fixture_id,
        ],
        "evidence_bundle_digest": evidence_bundle_digest,
        "publication": {
            "publication_id": publication.publication_id,
            "revision": publication.revision,
            "status": publication.status,
        },
        "usage": {
            "provider": None,
            "total_tokens": None,
            "estimated_cost": None,
            "currency": None,
            "cost_source": "unknown",
        },
    }
    await emit(RuntimeEvent(type="review.result", step=4, data=data))
    return RuntimeResult(
        status=RunStatus.COMPLETED,
        answer=_canonical_json_bytes(data).decode("utf-8"),
        step=4,
    )


def _review_execution_context(
    request: RuntimeRequest,
) -> ToolExecutionContext | None:
    context = request.execution_context
    identity = request.context_identity
    if (
        context is None
        or identity is None
        or context.principal_id != identity.owner_id
    ):
        return None
    try:
        return context.for_run(request.run_id)
    except ValueError:
        return None


def _evidence_record(
    *,
    review_id: str,
    tool_name: str,
    value: object,
) -> ReviewEvidenceRecord:
    if tool_name == "inspect_image" and isinstance(value, ReviewImageEvidence):
        return ReviewEvidenceRecord(
            review_id=review_id,
            source_kind="image",
            source_ref=value.image_asset_id,
            content_sha256=value.output_sha256 or value.image_sha256,
            content_bytes=value.output_bytes,
            trust=value.trust,
            status=value.status,
        )
    if tool_name == "search_review_policy" and isinstance(
        value,
        ReviewPolicyEvidence,
    ):
        citations = [
            {
                "document_id": citation.document_id,
                "title": citation.title,
                "source": citation.source,
                "chunk_index": citation.chunk_index,
                "excerpt_sha256": citation.excerpt_sha256,
                "excerpt_bytes": citation.excerpt_bytes,
                "score": citation.score,
            }
            for citation in value.citations
        ]
        if not citations or any(
            not math.isfinite(citation["score"]) for citation in citations
        ):
            raise ValueError("review policy evidence is invalid")
        encoded = _canonical_json_bytes(
            {
                "policy_topic_sha256": value.policy_topic_sha256,
                "policy_topic_bytes": value.policy_topic_bytes,
                "citations": citations,
            }
        )
        return ReviewEvidenceRecord(
            review_id=review_id,
            source_kind="policy",
            source_ref=value.policy_topic_sha256,
            content_sha256=hashlib.sha256(encoded).hexdigest(),
            content_bytes=len(encoded),
            trust=value.trust,
            status="verified",
            citation_refs=tuple(
                citation.document_id for citation in value.citations
            ),
        )
    if tool_name == "read_fixture_page" and isinstance(
        value,
        ReviewPageEvidence,
    ):
        return ReviewEvidenceRecord(
            review_id=review_id,
            source_kind="page",
            source_ref=value.page_fixture_id,
            content_sha256=value.content_sha256,
            content_bytes=value.content_bytes,
            trust=value.trust,
            status="verified",
        )
    raise TypeError("review tool result is invalid")


def _tool_failure_result(result: ToolResult, *, step: int) -> RuntimeResult:
    code = result.error_code or "review_evidence_invalid"
    try:
        failure = stable_run_failure(code, step=step)
    except ValueError:
        if code == "permission_denied":
            failure = RunFailure(
                code=code,
                category="authorization",
                public_message="Review tool is not available to this principal",
                step=step,
            )
        else:
            failure = stable_run_failure("review_evidence_invalid", step=step)
    return RuntimeResult(
        status=RunStatus.FAILED,
        failure=failure,
        step=step,
    )


def _failed_result(code: str, *, step: int) -> RuntimeResult:
    return RuntimeResult(
        status=RunStatus.FAILED,
        failure=stable_run_failure(code, step=step),
        step=step,
    )


def _authorization_failure(code: str, *, step: int) -> RuntimeResult:
    return RuntimeResult(
        status=RunStatus.FAILED,
        failure=RunFailure(
            code=code,
            category="authorization",
            public_message="Trusted review approval context is required",
            step=step,
        ),
        step=step,
    )


def _cancelled_result(
    control: RuntimeControl,
    *,
    step: int,
) -> RuntimeResult:
    reason = control.cancellation_token.reason
    code = (
        reason
        if reason in {"cancelled_by_user", "client_disconnected"}
        else "run_cancelled"
    )
    return RuntimeResult(
        status=RunStatus.CANCELLED,
        failure=RunFailure(
            code=code,
            category="cancellation",
            public_message="Run cancelled",
            step=step,
        ),
        step=step,
    )


def _tool_call_id(run_id: str, tool_name: str) -> str:
    digest = _length_prefixed_digest(
        MULTISOURCE_REVIEW_VERSION,
        run_id,
        tool_name,
    )
    return f"review-{tool_name}-{digest[:24]}"


def _publish_call_id(run_id: str, bundle_digest: str) -> str:
    digest = _length_prefixed_digest(
        MULTISOURCE_REVIEW_VERSION,
        run_id,
        "publish_review",
        bundle_digest,
    )
    return f"review-publish-{digest[:32]}"


def _length_prefixed_digest(*parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, "big"))
        digest.update(encoded)
    return digest.hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _require_identifier(
    value: str,
    pattern: re.Pattern[str],
    label: str,
) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


def _require_scope_identifier(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
        or any(
            character.isspace() or not character.isprintable()
            for character in value
        )
    ):
        raise ValueError(f"{label} is invalid")


__all__ = [
    "MultisourceReviewRuntime",
    "REVIEW_EVIDENCE_SCHEMA",
    "REVIEW_SOURCE_ORDER",
    "ReviewBudgetExceeded",
    "ReviewEvidenceBundle",
    "ReviewEvidenceRecord",
    "ReviewRunBinding",
    "ReviewRunCatalog",
    "ReviewRunSpec",
    "ReviewToolCallBudget",
]
