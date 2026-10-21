from __future__ import annotations

import asyncio
import copy
import hashlib
import json
import math
import re
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Literal, Protocol, cast

from backend.app.advanced.browser_agent import BrowserAgent
from backend.app.advanced.browser_driver import BrowserDriver
from backend.app.advanced.harness import PolicyViolation, content_digest
from backend.app.advanced.multimodal import MultimodalVisionAgent
from backend.app.knowledge.rag import Citation, KnowledgeBase
from backend.app.tools import (
    ToolDefinition,
    ToolExecutionContext,
    ToolHandlerError,
    ToolRegistry,
    ToolResult,
    ToolRisk,
)


MULTISOURCE_REVIEW_VERSION = "multisource-review-v1"
REVIEWER_ROLE = "reviewer"
REVIEW_TOOL_NAMES = (
    "inspect_image",
    "search_review_policy",
    "read_fixture_page",
    "publish_review",
)

_RESOURCE_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}")
_REVIEW_ID = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,127}")
_SHA256 = re.compile(r"[0-9a-f]{64}")
_MAX_RESOURCES = 32
_MAX_POLICY_TOPIC_BYTES = 512
_MAX_POLICY_RESULTS = 3
_POLICY_ALLOWED = object()
ReviewDecision = Literal["approve", "reject", "needs_review"]


@dataclass(frozen=True)
class ReviewScenarioLimits:
    max_tool_calls: int = 4
    max_calls_per_tool: int = 1
    max_side_effect_calls: int = 1
    max_policy_topic_bytes: int = _MAX_POLICY_TOPIC_BYTES
    max_policy_results: int = _MAX_POLICY_RESULTS

    def __post_init__(self) -> None:
        for field_name in (
            "max_tool_calls",
            "max_calls_per_tool",
            "max_side_effect_calls",
            "max_policy_topic_bytes",
            "max_policy_results",
        ):
            value = getattr(self, field_name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.max_tool_calls != len(REVIEW_TOOL_NAMES):
            raise ValueError("review scenario requires exactly four tool calls")
        if self.max_calls_per_tool != 1 or self.max_side_effect_calls != 1:
            raise ValueError("review scenario permits one call per tool and one side effect")
        if self.max_policy_results > _MAX_POLICY_RESULTS:
            raise ValueError("review policy result limit exceeds the reviewed maximum")


@dataclass(frozen=True)
class ReviewImageAsset:
    id: str
    owner_id: str = field(repr=False)
    png: bytes = field(repr=False)

    def __post_init__(self) -> None:
        _require_identifier(self.id, _RESOURCE_ID, "image asset id")
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise ValueError("review image owner id is invalid")
        if not isinstance(self.png, bytes) or not self.png:
            raise ValueError("review image asset must contain PNG bytes")


@dataclass(frozen=True)
class ReviewPageFixture:
    id: str
    owner_id: str = field(repr=False)
    url: str = field(repr=False)

    def __post_init__(self) -> None:
        _require_identifier(self.id, _RESOURCE_ID, "page fixture id")
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise ValueError("review page owner id is invalid")
        if (
            not isinstance(self.url, str)
            or not self.url
            or self.url != self.url.strip()
        ):
            raise ValueError("review page fixture URL is invalid")


class ReviewResourceCatalog:
    """Immutable server-owned image and page lookup."""

    def __init__(
        self,
        *,
        images: Mapping[str, ReviewImageAsset],
        pages: Mapping[str, ReviewPageFixture],
    ) -> None:
        self._images = _freeze_resources(images, ReviewImageAsset, "image")
        self._pages = _freeze_resources(pages, ReviewPageFixture, "page")

    def image(self, resource_id: str, *, owner_id: str) -> ReviewImageAsset | None:
        resource = self._images.get(resource_id)
        return resource if resource is not None and resource.owner_id == owner_id else None

    def page(self, resource_id: str, *, owner_id: str) -> ReviewPageFixture | None:
        resource = self._pages.get(resource_id)
        return resource if resource is not None and resource.owner_id == owner_id else None


@dataclass(frozen=True)
class ReviewImageEvidence:
    image_asset_id: str
    status: Literal["verified", "degraded"]
    image_sha256: str
    output_sha256: str | None
    output_bytes: int
    summary: str | None = field(repr=False)
    uncertainties: tuple[str, ...] = field(repr=False)
    visual_text_sha256: str
    visual_text_bytes: int
    provider: str
    model: str
    offline: bool
    failure_code: str | None = None
    trust: Literal["untrusted_visual_data"] = "untrusted_visual_data"
    can_authorize_actions: Literal[False] = False


@dataclass(frozen=True)
class ReviewPolicyCitation:
    document_id: str
    title: str
    source: str
    chunk_index: int
    excerpt: str = field(repr=False)
    excerpt_sha256: str
    excerpt_bytes: int
    score: float


@dataclass(frozen=True)
class ReviewPolicyEvidence:
    policy_topic_sha256: str
    policy_topic_bytes: int
    citations: tuple[ReviewPolicyCitation, ...] = field(repr=False)
    trust: Literal["retrieved_policy_data"] = "retrieved_policy_data"


@dataclass(frozen=True)
class ReviewPageEvidence:
    page_fixture_id: str
    page_digest: str
    content_sha256: str
    content_bytes: int
    title: str = field(repr=False)
    text: str = field(repr=False)
    visible_element_ids: tuple[str, ...]
    driver: str
    network_access: bool
    trust: Literal["untrusted_page_data"] = "untrusted_page_data"


@dataclass(frozen=True)
class ReviewPublicationCommand:
    owner_id: str = field(repr=False)
    run_id: str
    review_id: str
    expected_revision: int
    requested_decision: ReviewDecision
    evidence_bundle_digest: str
    idempotency_key: str = field(repr=False)
    scenario_version: Literal["multisource-review-v1"] = MULTISOURCE_REVIEW_VERSION

    def __post_init__(self) -> None:
        if not isinstance(self.owner_id, str) or not self.owner_id.strip():
            raise ValueError("publication owner id is invalid")
        if not isinstance(self.run_id, str) or not self.run_id.strip():
            raise ValueError("publication run id is invalid")
        _require_identifier(self.review_id, _REVIEW_ID, "review id")
        if (
            isinstance(self.expected_revision, bool)
            or not isinstance(self.expected_revision, int)
            or self.expected_revision < 1
        ):
            raise ValueError("publication expected revision must be positive")
        if self.requested_decision not in {"approve", "reject", "needs_review"}:
            raise ValueError("publication decision is invalid")
        _require_identifier(
            self.evidence_bundle_digest,
            _SHA256,
            "evidence bundle digest",
        )
        _require_identifier(self.idempotency_key, _SHA256, "idempotency key")
        if self.scenario_version != MULTISOURCE_REVIEW_VERSION:
            raise ValueError("publication scenario version is invalid")


@dataclass(frozen=True)
class ReviewPublicationResult:
    publication_id: str
    revision: int
    status: Literal["published"] = "published"

    def __post_init__(self) -> None:
        _require_identifier(self.publication_id, _REVIEW_ID, "publication id")
        if (
            isinstance(self.revision, bool)
            or not isinstance(self.revision, int)
            or self.revision < 1
        ):
            raise ValueError("publication revision must be a positive integer")
        if self.status != "published":
            raise ValueError("publication status is invalid")


@dataclass(frozen=True)
class ReviewToolSpec:
    name: str
    description: str
    input_schema: Mapping[str, object]
    allowed_roles: frozenset[str]
    risk_level: ToolRisk
    has_side_effects: bool
    requires_approval: bool

    @property
    def approval_required(self) -> bool:
        return (
            self.requires_approval
            or self.has_side_effects
            or self.risk_level is ToolRisk.HIGH
        )


class ReviewPublisher(Protocol):
    async def publish(
        self,
        command: ReviewPublicationCommand,
    ) -> ReviewPublicationResult: ...


class BrowserReviewPageReader:
    """Read one server-owned fixture through the existing Browser boundary."""

    def __init__(self, agent: BrowserAgent, driver: BrowserDriver) -> None:
        self._agent = agent
        self._driver = driver

    async def read(self, fixture: ReviewPageFixture) -> ReviewPageEvidence:
        try:
            plan = self._agent.validate_plan(
                [
                    {
                        "id": "review-page-navigate",
                        "kind": "navigate",
                        "url": fixture.url,
                    }
                ]
            )
            result = await asyncio.to_thread(
                self._agent.run_with_driver,
                plan,
                driver=self._driver,
            )
        except PolicyViolation as error:
            code = (
                "review_page_changed"
                if error.code in {"browser_page_changed", "browser_element_missing"}
                else "review_evidence_invalid"
            )
            raise ToolHandlerError(code) from None
        observation = result.observation
        if result.network_access:
            raise ToolHandlerError("review_evidence_invalid")
        encoded_content = json.dumps(
            {"title": observation.title, "text": observation.text},
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return ReviewPageEvidence(
            page_fixture_id=fixture.id,
            page_digest=observation.page_digest,
            content_sha256=hashlib.sha256(encoded_content).hexdigest(),
            content_bytes=len(encoded_content),
            title=observation.title,
            text=observation.text,
            visible_element_ids=observation.visible_element_ids,
            driver=result.driver,
            network_access=result.network_access,
        )


AsyncReviewToolHandler = Callable[
    [dict[str, object], ToolExecutionContext],
    Awaitable[object],
]


class AsyncReviewToolRegistry:
    """Async portfolio registry with existing schema, RBAC, and approval policy."""

    def __init__(
        self,
        definitions: tuple[ToolDefinition, ...],
        handlers: Mapping[str, AsyncReviewToolHandler],
        *,
        limits: ReviewScenarioLimits,
    ) -> None:
        if tuple(definition.name for definition in definitions) != REVIEW_TOOL_NAMES:
            raise ValueError("review registry requires the four versioned tools")
        if set(handlers) != set(REVIEW_TOOL_NAMES):
            raise ValueError("review registry handler set is incomplete")
        policy_registry = ToolRegistry()
        for definition in definitions:
            policy_registry.register(definition)
        self._policy_registry = policy_registry
        self._handlers = MappingProxyType(dict(handlers))
        self._limits = limits

    @property
    def limits(self) -> ReviewScenarioLimits:
        return self._limits

    def definitions(
        self,
        *,
        context: ToolExecutionContext | None = None,
    ) -> tuple[ReviewToolSpec, ...]:
        return tuple(
            ReviewToolSpec(
                name=definition.name,
                description=definition.description,
                input_schema=MappingProxyType(
                    copy.deepcopy(definition.input_schema)
                ),
                allowed_roles=definition.allowed_roles,
                risk_level=definition.risk_level,
                has_side_effects=definition.has_side_effects,
                requires_approval=definition.requires_approval,
            )
            for definition in self._policy_registry.definitions(context=context)
        )

    async def execute(
        self,
        name: str,
        arguments: dict[str, object],
        *,
        context: ToolExecutionContext | None = None,
        call_id: str | None = None,
    ) -> ToolResult:
        execution_context = context or ToolExecutionContext()
        if name == "publish_review" and execution_context.run_id is None:
            return _failed_result(name, "review_evidence_invalid")
        gate = self._policy_registry.execute(
            name,
            arguments,
            context=execution_context,
            call_id=call_id,
        )
        if not gate.ok:
            return gate
        if gate.value is not _POLICY_ALLOWED:
            return _failed_result(name, "review_evidence_invalid")
        try:
            value = await self._handlers[name](arguments, execution_context)
        except asyncio.CancelledError:
            raise
        except ToolHandlerError as error:
            result_unknown = (
                error.result_unknown
                or name == "publish_review"
                and error.code
                in {"tool_result_unknown", "tool_timeout", "tool_io_error"}
            )
            return ToolResult(
                ok=False,
                error_code=error.code,
                error_message=f"Tool adapter failed: {name}",
                retryable=error.retryable and not result_unknown,
                result_unknown=result_unknown,
            )
        except TimeoutError:
            return ToolResult(
                ok=False,
                error_code="tool_timeout",
                error_message=f"Tool timed out: {name}",
                retryable=name != "publish_review",
                result_unknown=name == "publish_review",
            )
        except OSError:
            return ToolResult(
                ok=False,
                error_code="tool_io_error",
                error_message=f"Tool I/O error: {name}",
                retryable=name != "publish_review",
                result_unknown=name == "publish_review",
            )
        except (TypeError, ValueError):
            return _failed_result(name, "review_evidence_invalid")
        return ToolResult(ok=True, value=value)


def create_multisource_review_registry(
    *,
    catalog: ReviewResourceCatalog,
    vision_agent: MultimodalVisionAgent,
    knowledge_base: KnowledgeBase,
    page_reader: BrowserReviewPageReader,
    publisher: ReviewPublisher,
    limits: ReviewScenarioLimits | None = None,
) -> AsyncReviewToolRegistry:
    resolved_limits = limits or ReviewScenarioLimits()
    definitions = _review_tool_definitions(resolved_limits)

    async def inspect_image(
        arguments: dict[str, object],
        _context: ToolExecutionContext,
    ) -> ReviewImageEvidence:
        asset_id = _argument_string(arguments, "image_asset_id")
        asset = catalog.image(asset_id, owner_id=_context.principal_id)
        if asset is None:
            raise ToolHandlerError("review_asset_not_found")
        result = await vision_agent.inspect(asset.png, media_type="image/png")
        observation = result.observation
        if observation is None:
            failure_code = result.failure.code if result.failure is not None else None
            return ReviewImageEvidence(
                image_asset_id=asset.id,
                status="degraded",
                image_sha256=result.inspection.image.sha256,
                output_sha256=None,
                output_bytes=0,
                summary=None,
                uncertainties=(),
                visual_text_sha256=result.inspection.visual_text.sha256,
                visual_text_bytes=result.inspection.visual_text.byte_length,
                provider=vision_agent.provider,
                model=vision_agent.model,
                offline=vision_agent.offline,
                failure_code=failure_code,
            )
        return ReviewImageEvidence(
            image_asset_id=asset.id,
            status="verified",
            image_sha256=observation.image.sha256,
            output_sha256=observation.output_sha256,
            output_bytes=observation.output_byte_length,
            summary=observation.summary,
            uncertainties=observation.uncertainties,
            visual_text_sha256=observation.visual_text.sha256,
            visual_text_bytes=observation.visual_text.byte_length,
            provider=observation.provider,
            model=observation.model,
            offline=observation.offline,
        )

    async def search_review_policy(
        arguments: dict[str, object],
        _context: ToolExecutionContext,
    ) -> ReviewPolicyEvidence:
        topic = _argument_string(arguments, "policy_topic")
        topic_bytes = topic.encode("utf-8")
        if len(topic_bytes) > resolved_limits.max_policy_topic_bytes:
            raise ToolHandlerError("review_budget_exceeded")
        results = knowledge_base.search(
            topic,
            limit=resolved_limits.max_policy_results,
        )
        if not results:
            raise ToolHandlerError("review_policy_no_evidence")
        citations = tuple(
            _review_policy_citation(result.citation, result.score)
            for result in results
        )
        return ReviewPolicyEvidence(
            policy_topic_sha256=hashlib.sha256(topic_bytes).hexdigest(),
            policy_topic_bytes=len(topic_bytes),
            citations=citations,
        )

    async def read_fixture_page(
        arguments: dict[str, object],
        _context: ToolExecutionContext,
    ) -> ReviewPageEvidence:
        fixture_id = _argument_string(arguments, "page_fixture_id")
        fixture = catalog.page(fixture_id, owner_id=_context.principal_id)
        if fixture is None:
            raise ToolHandlerError("review_asset_not_found")
        return await page_reader.read(fixture)

    async def publish_review(
        arguments: dict[str, object],
        context: ToolExecutionContext,
    ) -> ReviewPublicationResult:
        if context.run_id is None:
            raise ToolHandlerError("review_evidence_invalid")
        review_id = _argument_string(arguments, "review_id")
        expected_revision = _argument_integer(arguments, "expected_revision")
        decision = _argument_string(arguments, "requested_decision")
        evidence_digest = _argument_string(arguments, "evidence_bundle_digest")
        command = ReviewPublicationCommand(
            owner_id=context.principal_id,
            run_id=context.run_id,
            review_id=review_id,
            expected_revision=expected_revision,
            requested_decision=cast(ReviewDecision, decision),
            evidence_bundle_digest=evidence_digest,
            idempotency_key=_publication_idempotency_key(
                owner_id=context.principal_id,
                review_id=review_id,
                expected_revision=expected_revision,
                requested_decision=decision,
                evidence_bundle_digest=evidence_digest,
            ),
        )
        return await publisher.publish(command)

    return AsyncReviewToolRegistry(
        definitions,
        {
            "inspect_image": inspect_image,
            "search_review_policy": search_review_policy,
            "read_fixture_page": read_fixture_page,
            "publish_review": publish_review,
        },
        limits=resolved_limits,
    )


def _review_tool_definitions(
    limits: ReviewScenarioLimits,
) -> tuple[ToolDefinition, ...]:
    reviewed_role = frozenset({REVIEWER_ROLE})
    resource_property = {
        "type": "string",
        "minLength": 1,
        "maxLength": 64,
        "pattern": _RESOURCE_ID.pattern,
    }
    return (
        ToolDefinition(
            name="inspect_image",
            description="Inspect one server-owned review PNG as untrusted evidence.",
            input_schema={
                "type": "object",
                "properties": {"image_asset_id": resource_property},
                "required": ["image_asset_id"],
            },
            handler=_policy_marker,
            allowed_roles=reviewed_role,
        ),
        ToolDefinition(
            name="search_review_policy",
            description="Search the bounded server-owned review policy corpus.",
            input_schema={
                "type": "object",
                "properties": {
                    "policy_topic": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": limits.max_policy_topic_bytes,
                    }
                },
                "required": ["policy_topic"],
            },
            handler=_policy_marker,
            allowed_roles=reviewed_role,
        ),
        ToolDefinition(
            name="read_fixture_page",
            description="Read one server-owned browser fixture without public network.",
            input_schema={
                "type": "object",
                "properties": {"page_fixture_id": resource_property},
                "required": ["page_fixture_id"],
            },
            handler=_policy_marker,
            allowed_roles=reviewed_role,
        ),
        ToolDefinition(
            name="publish_review",
            description="Publish one approved review with exact evidence binding.",
            input_schema={
                "type": "object",
                "properties": {
                    "review_id": {
                        "type": "string",
                        "minLength": 1,
                        "maxLength": 128,
                        "pattern": _REVIEW_ID.pattern,
                    },
                    "expected_revision": {"type": "integer", "minimum": 1},
                    "requested_decision": {
                        "type": "string",
                        "enum": ["approve", "reject", "needs_review"],
                    },
                    "evidence_bundle_digest": {
                        "type": "string",
                        "pattern": _SHA256.pattern,
                    },
                },
                "required": [
                    "review_id",
                    "expected_revision",
                    "requested_decision",
                    "evidence_bundle_digest",
                ],
            },
            handler=_policy_marker,
            allowed_roles=reviewed_role,
            risk_level=ToolRisk.HIGH,
            has_side_effects=True,
            requires_approval=True,
        ),
    )


def _policy_marker(_arguments: dict[str, object]) -> object:
    return _POLICY_ALLOWED


def _failed_result(tool_name: str, code: str) -> ToolResult:
    error = ToolHandlerError(code)
    return ToolResult(
        ok=False,
        error_code=error.code,
        error_message=f"Tool adapter failed: {tool_name}",
        retryable=error.retryable,
        result_unknown=error.result_unknown,
    )


def _review_policy_citation(
    citation: Citation,
    score: float,
) -> ReviewPolicyCitation:
    if not isinstance(citation, Citation) or not math.isfinite(score) or score < 0:
        raise ToolHandlerError("review_evidence_invalid")
    excerpt_bytes = citation.excerpt.encode("utf-8")
    return ReviewPolicyCitation(
        document_id=citation.document_id,
        title=citation.title,
        source=citation.source,
        chunk_index=citation.chunk_index,
        excerpt=citation.excerpt,
        excerpt_sha256=hashlib.sha256(excerpt_bytes).hexdigest(),
        excerpt_bytes=len(excerpt_bytes),
        score=score,
    )


def _publication_idempotency_key(
    *,
    owner_id: str,
    review_id: str,
    expected_revision: int,
    requested_decision: str,
    evidence_bundle_digest: str,
) -> str:
    payload = json.dumps(
        {
            "scenario_version": MULTISOURCE_REVIEW_VERSION,
            "owner_scope_digest": content_digest(owner_id),
            "review_id": review_id,
            "expected_revision": expected_revision,
            "requested_decision": requested_decision,
            "evidence_bundle_digest": evidence_bundle_digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _freeze_resources(
    resources: Mapping[str, object],
    expected_type: type,
    label: str,
) -> Mapping[str, object]:
    if not isinstance(resources, Mapping):
        raise TypeError(f"review {label} resources must use a mapping")
    if len(resources) < 1 or len(resources) > _MAX_RESOURCES:
        raise ValueError(f"review {label} resources must be bounded and non-empty")
    copied: dict[str, object] = {}
    for resource_id, resource in resources.items():
        if not isinstance(resource, expected_type) or resource_id != resource.id:
            raise ValueError(f"review {label} resource mapping is invalid")
        copied[resource_id] = resource
    return MappingProxyType(copied)


def _argument_string(arguments: Mapping[str, object], field_name: str) -> str:
    value = arguments.get(field_name)
    if not isinstance(value, str) or not value:
        raise ToolHandlerError("review_evidence_invalid")
    return value


def _argument_integer(arguments: Mapping[str, object], field_name: str) -> int:
    value = arguments.get(field_name)
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ToolHandlerError("review_evidence_invalid")
    return value


def _require_identifier(value: str, pattern: re.Pattern[str], label: str) -> None:
    if not isinstance(value, str) or pattern.fullmatch(value) is None:
        raise ValueError(f"{label} is invalid")


__all__ = [
    "AsyncReviewToolRegistry",
    "BrowserReviewPageReader",
    "MULTISOURCE_REVIEW_VERSION",
    "REVIEWER_ROLE",
    "REVIEW_TOOL_NAMES",
    "ReviewDecision",
    "ReviewImageAsset",
    "ReviewImageEvidence",
    "ReviewPageEvidence",
    "ReviewPageFixture",
    "ReviewPolicyCitation",
    "ReviewPolicyEvidence",
    "ReviewPublicationCommand",
    "ReviewPublicationResult",
    "ReviewPublisher",
    "ReviewResourceCatalog",
    "ReviewScenarioLimits",
    "ReviewToolSpec",
    "create_multisource_review_registry",
]
