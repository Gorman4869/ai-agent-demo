from __future__ import annotations

import struct
import unittest
import zlib
from collections.abc import Sequence
from dataclasses import dataclass, field

from backend.app.advanced.browser_agent import BrowserAction, BrowserAgent
from backend.app.advanced.browser_driver import BrowserDriverRun, BrowserObservation
from backend.app.advanced.multimodal import MultimodalVisionAgent, OfflineVisionModel
from backend.app.advanced.harness import PolicyViolation
from backend.app.advanced.review_tools import (
    MULTISOURCE_REVIEW_VERSION,
    BrowserReviewPageReader,
    ReviewImageAsset,
    ReviewImageEvidence,
    ReviewPageEvidence,
    ReviewPageFixture,
    ReviewPolicyEvidence,
    ReviewPublicationCommand,
    ReviewPublicationResult,
    ReviewResourceCatalog,
    ReviewScenarioLimits,
    create_multisource_review_registry,
)
from backend.app.knowledge import Document, InMemoryKnowledgeBase
from backend.app.reliability import failure_spec
from backend.app.tools import (
    InMemoryApprovalStore,
    ToolExecutionContext,
    ToolHandlerError,
    ToolRisk,
)


_ORIGIN = "https://review.fixture.test"
_PAGE_URL = _ORIGIN + "/policy"
_EVIDENCE_DIGEST = "a" * 64


class ReviewToolContractTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.driver = _RecordingBrowserDriver()
        self.publisher = _RecordingPublisher()
        knowledge = InMemoryKnowledgeBase(chunk_size=80, overlap=10)
        for index in range(4):
            knowledge.add(
                Document(
                    id=f"policy-{index}",
                    title=f"Review policy {index}",
                    content=f"agent review disclosure rule evidence section {index}",
                    source=f"policy://review/{index}",
                )
            )
        self.registry = create_multisource_review_registry(
            catalog=ReviewResourceCatalog(
                images={
                    "hero-image": ReviewImageAsset(
                        "hero-image",
                        "reviewer-1",
                        _png(),
                    ),
                },
                pages={
                    "policy-page": ReviewPageFixture(
                        "policy-page",
                        "reviewer-1",
                        _PAGE_URL,
                    ),
                },
            ),
            vision_agent=MultimodalVisionAgent(
                OfflineVisionModel(),
                timeout_ms=500,
            ),
            knowledge_base=knowledge,
            page_reader=BrowserReviewPageReader(
                BrowserAgent(allowed_origins=[_ORIGIN]),
                self.driver,
            ),
            publisher=self.publisher,
        )
        self.reviewer = ToolExecutionContext(
            principal_id="reviewer-1",
            roles=frozenset({"reviewer"}),
            run_id="review-run-1",
        )

    async def test_registry_exposes_only_four_bounded_tools_to_reviewer(self) -> None:
        self.assertEqual((), self.registry.definitions())

        definitions = self.registry.definitions(context=self.reviewer)

        self.assertEqual(
            (
                "inspect_image",
                "search_review_policy",
                "read_fixture_page",
                "publish_review",
            ),
            tuple(definition.name for definition in definitions),
        )
        publish = definitions[-1]
        self.assertEqual(ToolRisk.HIGH, publish.risk_level)
        self.assertTrue(publish.has_side_effects)
        self.assertTrue(publish.requires_approval)
        self.assertTrue(publish.approval_required)
        self.assertEqual(ReviewScenarioLimits(), self.registry.limits)
        self.assertEqual(4, self.registry.limits.max_tool_calls)

        definitions[0].input_schema["properties"]["image_asset_id"][
            "pattern"
        ] = ".*"
        rejected = await self.registry.execute(
            "inspect_image",
            {"image_asset_id": "../../private"},
            context=self.reviewer,
        )
        self.assertEqual("invalid_arguments", rejected.error_code)

    async def test_inspect_image_uses_server_owned_png_and_hides_content(self) -> None:
        result = await self.registry.execute(
            "inspect_image",
            {"image_asset_id": "hero-image"},
            context=self.reviewer,
        )

        self.assertTrue(result.ok)
        self.assertIsInstance(result.value, ReviewImageEvidence)
        self.assertEqual("verified", result.value.status)
        self.assertEqual("untrusted_visual_data", result.value.trust)
        self.assertFalse(result.value.can_authorize_actions)
        self.assertEqual("offline", result.value.provider)
        self.assertNotIn("PNG validation completed", repr(result.value))

    async def test_resource_ids_cannot_be_replaced_with_paths_urls_or_bytes(self) -> None:
        cases = (
            (
                "inspect_image",
                {"image_asset_id": "hero-image", "path": "C:/private.png"},
            ),
            (
                "inspect_image",
                {"image_asset_id": "hero-image", "image": b"raw"},
            ),
            (
                "read_fixture_page",
                {"page_fixture_id": "policy-page", "url": "https://evil.test"},
            ),
            (
                "read_fixture_page",
                {"page_fixture_id": "policy-page", "selector": "body"},
            ),
        )

        for tool_name, arguments in cases:
            with self.subTest(tool_name=tool_name, arguments=arguments):
                result = await self.registry.execute(
                    tool_name,
                    arguments,
                    context=self.reviewer,
                )
                self.assertFalse(result.ok)
                self.assertEqual("invalid_arguments", result.error_code)

        self.assertEqual(0, self.driver.executions)

    async def test_unknown_server_owned_resource_fails_closed(self) -> None:
        for tool_name, arguments in (
            ("inspect_image", {"image_asset_id": "missing-image"}),
            ("read_fixture_page", {"page_fixture_id": "missing-page"}),
        ):
            with self.subTest(tool_name=tool_name):
                result = await self.registry.execute(
                    tool_name,
                    arguments,
                    context=self.reviewer,
                )
                self.assertFalse(result.ok)
                self.assertEqual("review_asset_not_found", result.error_code)

        cross_owner = await self.registry.execute(
            "inspect_image",
            {"image_asset_id": "hero-image"},
            context=ToolExecutionContext(
                principal_id="reviewer-2",
                roles=frozenset({"reviewer"}),
                run_id="review-run-2",
            ),
        )
        self.assertEqual("review_asset_not_found", cross_owner.error_code)

    async def test_policy_search_uses_real_knowledge_base_and_caps_citations(self) -> None:
        result = await self.registry.execute(
            "search_review_policy",
            {"policy_topic": "agent review disclosure rule"},
            context=self.reviewer,
        )

        self.assertTrue(result.ok)
        self.assertIsInstance(result.value, ReviewPolicyEvidence)
        self.assertEqual(3, len(result.value.citations))
        self.assertTrue(all(item.score > 0 for item in result.value.citations))
        self.assertNotIn("disclosure rule evidence", repr(result.value))

    async def test_policy_search_rejects_no_evidence_and_utf8_byte_overflow(self) -> None:
        no_evidence = await self.registry.execute(
            "search_review_policy",
            {"policy_topic": "完全无关词条"},
            context=self.reviewer,
        )
        byte_overflow = await self.registry.execute(
            "search_review_policy",
            {"policy_topic": "审" * 300},
            context=self.reviewer,
        )

        self.assertEqual("review_policy_no_evidence", no_evidence.error_code)
        self.assertEqual("review_budget_exceeded", byte_overflow.error_code)

    async def test_page_reader_calls_browser_boundary_with_server_owned_url(self) -> None:
        result = await self.registry.execute(
            "read_fixture_page",
            {"page_fixture_id": "policy-page"},
            context=self.reviewer,
        )

        self.assertTrue(result.ok)
        self.assertIsInstance(result.value, ReviewPageEvidence)
        self.assertEqual(1, self.driver.validations)
        self.assertEqual(1, self.driver.executions)
        self.assertEqual(_PAGE_URL, self.driver.actions[0].url)
        self.assertFalse(result.value.network_access)
        self.assertNotIn(_PAGE_URL, repr(result.value))
        self.assertNotIn("private fixture body", repr(result.value))

    async def test_page_drift_is_normalized_without_retry(self) -> None:
        self.driver.failure_code = "browser_page_changed"

        result = await self.registry.execute(
            "read_fixture_page",
            {"page_fixture_id": "policy-page"},
            context=self.reviewer,
        )

        self.assertFalse(result.ok)
        self.assertEqual("review_page_changed", result.error_code)
        self.assertEqual(1, self.driver.executions)

    async def test_publish_requires_reviewer_run_and_exact_approval(self) -> None:
        arguments = _publish_arguments()
        viewer = await self.registry.execute(
            "publish_review",
            arguments,
            context=ToolExecutionContext(
                principal_id="viewer-1",
                roles=frozenset({"viewer"}),
                run_id="review-run-1",
            ),
            call_id="publish-1",
        )
        missing_run = await self.registry.execute(
            "publish_review",
            arguments,
            context=ToolExecutionContext(
                principal_id="reviewer-1",
                roles=frozenset({"reviewer"}),
            ),
            call_id="publish-1",
        )
        missing_approval = await self.registry.execute(
            "publish_review",
            arguments,
            context=self.reviewer,
            call_id="publish-1",
        )

        self.assertEqual("permission_denied", viewer.error_code)
        self.assertEqual("review_evidence_invalid", missing_run.error_code)
        self.assertEqual("approval_required", missing_approval.error_code)
        self.assertEqual([], self.publisher.commands)

    async def test_publish_binds_arguments_and_derives_hidden_idempotency_key(self) -> None:
        arguments = _publish_arguments()
        approvals = InMemoryApprovalStore()
        approvals.grant(
            principal_id=self.reviewer.principal_id,
            run_id=self.reviewer.run_id,
            tool_call_id="publish-1",
            tool_name="publish_review",
            arguments=arguments,
        )
        context = ToolExecutionContext(
            principal_id=self.reviewer.principal_id,
            roles=self.reviewer.roles,
            run_id=self.reviewer.run_id,
            approval_store=approvals,
        )

        published = await self.registry.execute(
            "publish_review",
            arguments,
            context=context,
            call_id="publish-1",
        )
        replay = await self.registry.execute(
            "publish_review",
            arguments,
            context=context,
            call_id="publish-1",
        )

        self.assertTrue(published.ok)
        self.assertEqual("publication-1", published.value.publication_id)
        self.assertEqual("approval_required", replay.error_code)
        self.assertEqual(1, len(self.publisher.commands))
        command = self.publisher.commands[0]
        self.assertIsInstance(command, ReviewPublicationCommand)
        self.assertEqual(MULTISOURCE_REVIEW_VERSION, command.scenario_version)
        self.assertEqual(64, len(command.idempotency_key))
        self.assertNotIn(command.owner_id, repr(command))
        self.assertNotIn(command.idempotency_key, repr(command))

    async def test_changed_evidence_digest_cannot_reuse_publish_approval(self) -> None:
        approved_arguments = _publish_arguments()
        approvals = InMemoryApprovalStore()
        approvals.grant(
            principal_id=self.reviewer.principal_id,
            run_id=self.reviewer.run_id,
            tool_call_id="publish-1",
            tool_name="publish_review",
            arguments=approved_arguments,
        )
        context = ToolExecutionContext(
            principal_id=self.reviewer.principal_id,
            roles=self.reviewer.roles,
            run_id=self.reviewer.run_id,
            approval_store=approvals,
        )
        changed_arguments = dict(approved_arguments)
        changed_arguments["evidence_bundle_digest"] = "b" * 64

        result = await self.registry.execute(
            "publish_review",
            changed_arguments,
            context=context,
            call_id="publish-1",
        )

        self.assertEqual("approval_required", result.error_code)
        self.assertEqual([], self.publisher.commands)

    async def test_publisher_failure_uses_stable_content_free_code(self) -> None:
        self.publisher.failure_code = "review_revision_conflict"
        arguments = _publish_arguments()
        approvals = InMemoryApprovalStore()
        approvals.grant(
            principal_id=self.reviewer.principal_id,
            run_id=self.reviewer.run_id,
            tool_call_id="publish-1",
            tool_name="publish_review",
            arguments=arguments,
        )

        result = await self.registry.execute(
            "publish_review",
            arguments,
            context=ToolExecutionContext(
                principal_id=self.reviewer.principal_id,
                roles=self.reviewer.roles,
                run_id=self.reviewer.run_id,
                approval_store=approvals,
            ),
            call_id="publish-1",
        )

        self.assertFalse(result.ok)
        self.assertEqual("review_revision_conflict", result.error_code)
        self.assertNotIn("review-1", result.error_message)

    async def test_unknown_publish_result_is_never_marked_replay_safe(self) -> None:
        self.publisher.failure_code = "tool_result_unknown"
        arguments = _publish_arguments()
        approvals = InMemoryApprovalStore()
        approvals.grant(
            principal_id=self.reviewer.principal_id,
            run_id=self.reviewer.run_id,
            tool_call_id="publish-unknown",
            tool_name="publish_review",
            arguments=arguments,
        )

        result = await self.registry.execute(
            "publish_review",
            arguments,
            context=ToolExecutionContext(
                principal_id=self.reviewer.principal_id,
                roles=self.reviewer.roles,
                run_id=self.reviewer.run_id,
                approval_store=approvals,
            ),
            call_id="publish-unknown",
        )

        self.assertFalse(result.ok)
        self.assertEqual("tool_result_unknown", result.error_code)
        self.assertTrue(result.result_unknown)
        self.assertFalse(result.retryable)

    async def test_publish_timeout_and_io_are_result_unknown_not_retryable(self) -> None:
        arguments = _publish_arguments()

        for failure_code, expected_code in (
            ("raise_timeout", "tool_timeout"),
            ("raise_io", "tool_io_error"),
        ):
            with self.subTest(failure_code=failure_code):
                self.publisher.failure_code = failure_code
                approvals = InMemoryApprovalStore()
                call_id = f"publish-{failure_code}"
                approvals.grant(
                    principal_id=self.reviewer.principal_id,
                    run_id=self.reviewer.run_id,
                    tool_call_id=call_id,
                    tool_name="publish_review",
                    arguments=arguments,
                )
                result = await self.registry.execute(
                    "publish_review",
                    arguments,
                    context=ToolExecutionContext(
                        principal_id=self.reviewer.principal_id,
                        roles=self.reviewer.roles,
                        run_id=self.reviewer.run_id,
                        approval_store=approvals,
                    ),
                    call_id=call_id,
                )

                self.assertFalse(result.ok)
                self.assertEqual(expected_code, result.error_code)
                self.assertTrue(result.result_unknown)
                self.assertFalse(result.retryable)


class ReviewFailureCatalogTest(unittest.TestCase):
    def test_adr_0044_failure_codes_are_registered_and_not_retryable(self) -> None:
        for code in (
            "review_asset_not_found",
            "review_policy_no_evidence",
            "review_page_changed",
            "review_evidence_invalid",
            "review_revision_conflict",
            "review_budget_exceeded",
            "tool_result_unknown",
        ):
            with self.subTest(code=code):
                self.assertFalse(failure_spec(code).retryable)


@dataclass
class _RecordingBrowserDriver:
    validations: int = 0
    executions: int = 0
    actions: tuple[BrowserAction, ...] = ()
    failure_code: str | None = None

    def validate(self, actions: Sequence[BrowserAction]) -> None:
        self.validations += 1

    def execute(self, actions: Sequence[BrowserAction]) -> BrowserDriverRun:
        self.executions += 1
        self.actions = tuple(actions)
        if self.failure_code is not None:
            raise PolicyViolation(self.failure_code, "private driver detail")
        return BrowserDriverRun(
            actions=(),
            observation=BrowserObservation(
                origin=_ORIGIN,
                page_digest="c" * 64,
                visible_element_ids=("policy-body",),
                screenshot_sha256="d" * 64,
                screenshot_bytes=8,
                url=_PAGE_URL,
                title="Private fixture title",
                text="private fixture body",
                screenshot_png=b"\x89PNG\r\n\x1a\n",
            ),
        )


@dataclass
class _RecordingPublisher:
    commands: list[ReviewPublicationCommand] = field(default_factory=list)
    failure_code: str | None = None

    async def publish(
        self,
        command: ReviewPublicationCommand,
    ) -> ReviewPublicationResult:
        self.commands.append(command)
        if self.failure_code == "raise_timeout":
            raise TimeoutError
        if self.failure_code == "raise_io":
            raise OSError
        if self.failure_code is not None:
            raise ToolHandlerError(self.failure_code)
        return ReviewPublicationResult("publication-1", revision=2)


def _publish_arguments() -> dict[str, object]:
    return {
        "review_id": "review-1",
        "expected_revision": 1,
        "requested_decision": "approve",
        "evidence_bundle_digest": _EVIDENCE_DIGEST,
    }


def _png(*, width: int = 1, height: int = 1) -> bytes:
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    raw_scanline = b"\x00" + b"\x00\x00\x00\x00" * width
    return (
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", ihdr)
        + _chunk(b"IDAT", zlib.compress(raw_scanline * height))
        + _chunk(b"IEND", b"")
    )


def _chunk(kind: bytes, data: bytes) -> bytes:
    payload = kind + data
    return (
        len(data).to_bytes(4, "big")
        + payload
        + (zlib.crc32(payload) & 0xFFFFFFFF).to_bytes(4, "big")
    )


if __name__ == "__main__":
    unittest.main()
