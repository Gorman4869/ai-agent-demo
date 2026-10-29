from __future__ import annotations

import asyncio
import hashlib
import unittest
from dataclasses import replace
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.app.advanced.review_runtime import MultisourceReviewRuntime, ReviewEvidenceBundle
from backend.app.api.review_projection import project_review_snapshot
from backend.app.container import ApplicationContainer
from backend.app.domain.run import RunFailure, RunRecord, RunStatus, StoredRunEvent
from backend.app.main import create_app
from backend.app.security import Principal, StaticTokenAuthenticator
from backend.app.settings import Settings
from backend.app.stores import InMemoryEventStore, InMemoryRunStore, InMemoryToolExecutionStore
from backend.app.tools import InMemoryApprovalStore, ToolExecutionContext
from backend.tests.test_review_runtime import (
    NOW, OWNER_ID, RUN_ID, _RecordingPublicationStore, _RecordingRegistry,
    _records, _run_catalog,
)


class _ProjectionRegistry(_RecordingRegistry):
    async def execute(self, name, arguments, **kwargs):
        result = await super().execute(name, arguments, **kwargs)
        if name == "search_review_policy" and result.ok:
            result = replace(result, value=replace(
                result.value,
                policy_topic_sha256=hashlib.sha256(
                    arguments["policy_topic"].encode("utf-8")
                ).hexdigest(),
            ))
        return result


def _run() -> RunRecord:
    return RunRecord.create(
        run_id=RUN_ID, session_id="review-session", owner_id=OWNER_ID,
        runtime="manual", input_text="review", idempotency_key="review-projection-key",
        created_at=NOW,
    )


def _event(sequence: int, event_type: str, data: dict) -> StoredRunEvent:
    return StoredRunEvent(
        id=f"event-{sequence}", run_id=RUN_ID, sequence=sequence,
        type=event_type, data=data, created_at=NOW,
    )


def _events() -> tuple[StoredRunEvent, ...]:
    records = _records()
    return (
        *(_event(i, "review.evidence.recorded", r.event_data())
          for i, r in enumerate(records, start=1)),
        _event(4, "review.result", {
            "schema": "review-result-v1", "scenario_version": "multisource-review-v1",
            "review_id": "review-1", "outcome": "published",
            "evidence_refs": [r.source_ref for r in records],
            "evidence_bundle_digest": ReviewEvidenceBundle("review-1", records).digest,
            "publication": {"publication_id": "publication-1", "revision": 4, "status": "published"},
            "usage": {"provider": None, "total_tokens": None, "estimated_cost": None,
                      "currency": None, "cost_source": "unknown"},
            "private": "must not leak",
        }),
    )


class ReviewProjectionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.completed = _run().transition_to(RunStatus.RUNNING, at=NOW).transition_to(
            RunStatus.COMPLETED, at=NOW, answer="done"
        )

    def test_published_projection_rebuilds_bundle_and_excludes_extra_content(self) -> None:
        snapshot = project_review_snapshot(self.completed, _events())
        self.assertEqual("published", snapshot.outcome)
        self.assertEqual(3, len(snapshot.evidence))
        self.assertEqual(4, snapshot.publication.revision)
        self.assertIsNone(snapshot.usage.total_tokens)
        self.assertNotIn("must not leak", snapshot.model_dump_json())

    def test_result_without_complete_evidence_cannot_claim_publication(self) -> None:
        events = _events()
        snapshot = project_review_snapshot(self.completed, (events[0], events[-1]))
        self.assertEqual("needs_attention", snapshot.outcome)
        self.assertIsNone(snapshot.publication)

    def test_wrong_bundle_refs_and_usage_fail_closed(self) -> None:
        events = _events()
        for field, value in (
            ("evidence_bundle_digest", "0" * 64),
            ("evidence_refs", ["other"]),
            ("usage", {"total_tokens": 999}),
            ("publication", {"publication_id": "publication-1", "revision": True, "status": "published"}),
        ):
            with self.subTest(field=field):
                invalid = replace(events[-1], data={**events[-1].data, field: value})
                snapshot = project_review_snapshot(self.completed, (*events[:3], invalid))
                self.assertEqual("needs_attention", snapshot.outcome)
                self.assertIsNone(snapshot.publication)

    def test_invalid_later_result_keeps_last_valid_result(self) -> None:
        events = _events()
        invalid = _event(5, "review.result", {"schema": "wrong"})
        self.assertEqual("published", project_review_snapshot(self.completed, (*events, invalid)).outcome)

    def test_running_run_and_malformed_evidence_cannot_claim_publication(self) -> None:
        running = _run().transition_to(RunStatus.RUNNING, at=NOW)
        self.assertEqual("in_progress", project_review_snapshot(running, _events()).outcome)
        events = _events()
        malformed = replace(events[1], data={**events[1].data, "trust": "system"})
        snapshot = project_review_snapshot(self.completed, (events[0], malformed, *events[2:]))
        self.assertEqual(1, len(snapshot.evidence))
        self.assertIsNone(snapshot.publication)

    def test_other_run_and_non_review_runs_have_no_projection(self) -> None:
        self.assertIsNone(project_review_snapshot(self.completed, ()))
        self.assertIsNone(project_review_snapshot(self.completed, tuple(
            replace(e, run_id="other-run") for e in _events()
        )))

    def test_failure_codes_map_to_attention_or_failure(self) -> None:
        running = _run().transition_to(RunStatus.RUNNING, at=NOW)
        for code, expected in (("tool_result_unknown", "needs_attention"),
                               ("approval_rejected", "needs_attention"),
                               ("review_budget_exceeded", "failed")):
            failed = running.transition_to(RunStatus.FAILED, at=NOW, failure=RunFailure(
                code=code, category="tool", public_message="stopped"
            ))
            self.assertEqual(expected, project_review_snapshot(failed, _events()[:1]).outcome)


class ReviewProjectionApiTest(unittest.TestCase):
    def setUp(self) -> None:
        run_store = InMemoryRunStore()
        event_store = InMemoryEventStore(run_store)
        self.publisher = _RecordingPublicationStore()
        registry = _ProjectionRegistry(publisher=self.publisher)
        runtime = MultisourceReviewRuntime(
            registry=registry, run_catalog=_run_catalog(),
            tool_execution_store=InMemoryToolExecutionStore(run_store),
            clock=lambda: datetime.now(UTC),
        )
        self.container = ApplicationContainer.create(
            settings=Settings.from_environment({}),
            run_store=run_store, event_store=event_store,
            runtimes={"manual": runtime}, approval_store=InMemoryApprovalStore(),
            authenticator=StaticTokenAuthenticator({
                "review-token": Principal(OWNER_ID, roles=frozenset({"reviewer"})),
                "other-token": Principal("other-owner"),
            }),
        )
        asyncio.run(self._pause())
        self.client = TestClient(create_app(container=self.container))
        self.headers = {"Authorization": "Bearer review-token"}

    async def _pause(self) -> None:
        await self.container.run_store.create(_run())
        await self.container.run_coordinator.execute(
            RUN_ID, owner_id=OWNER_ID, execution_context=ToolExecutionContext(
                principal_id=OWNER_ID, roles=frozenset({"reviewer"}),
                approval_store=self.container.approval_store,
            ),
        )
        events = await self.container.event_store.list_for_run(RUN_ID, owner_id=OWNER_ID)
        self.approval_id = events[-1].data["approval_id"]

    def test_http_approval_and_fresh_app_read_share_same_review(self) -> None:
        path = f"/api/durable/runs/{RUN_ID}"
        waiting = self.client.get(path, headers=self.headers)
        self.assertEqual(200, waiting.status_code)
        self.assertEqual("waiting_approval", waiting.json()["review"]["outcome"])
        response = self.client.post(
            f"{path}/approvals/{self.approval_id}", json={"decision": "approve"}, headers=self.headers
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("published", response.json()["review"]["outcome"])
        fresh = TestClient(create_app(container=self.container))
        self.assertEqual(response.json()["review"], fresh.get(path, headers=self.headers).json()["review"])
        self.assertEqual(1, self.publisher.publish_calls)

    def test_rejection_and_cross_owner_snapshot(self) -> None:
        path = f"/api/durable/runs/{RUN_ID}"
        denied = self.client.get(path, headers={"Authorization": "Bearer other-token"})
        self.assertEqual(404, denied.status_code)
        response = self.client.post(
            f"{path}/approvals/{self.approval_id}", json={"decision": "reject"}, headers=self.headers
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("needs_attention", response.json()["review"]["outcome"])
        self.assertIsNone(response.json()["review"]["publication"])
        self.assertEqual(0, self.publisher.publish_calls)

    def test_unknown_result_is_visible_without_a_publication(self) -> None:
        self.publisher.failure_mode = "unknown_without_commit"
        response = self.client.post(
            f"/api/durable/runs/{RUN_ID}/approvals/{self.approval_id}",
            json={"decision": "approve"}, headers=self.headers,
        )
        self.assertEqual(200, response.status_code)
        self.assertEqual("tool_result_unknown", response.json()["error"]["code"])
        self.assertEqual("needs_attention", response.json()["review"]["outcome"])
        self.assertIsNone(response.json()["review"]["publication"])
        self.assertEqual(1, self.publisher.publish_calls)


if __name__ == "__main__":
    unittest.main()
