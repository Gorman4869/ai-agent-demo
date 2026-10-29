from __future__ import annotations

import time
import asyncio
import unittest

from fastapi.testclient import TestClient

from backend.app.advanced.browser_agent import BrowserAgent
from backend.app.advanced.multimodal import MultimodalVisionAgent, OfflineVisionModel
from backend.app.advanced.review_application import create_review_app
from backend.app.advanced.review_publication import InMemoryReviewPublicationStore
from backend.app.advanced.review_tools import (
    BrowserReviewPageReader, ReviewImageAsset, ReviewPageFixture,
    ReviewResourceCatalog, create_multisource_review_registry,
)
from backend.app.knowledge import Document, InMemoryKnowledgeBase
from backend.app.main import create_app
from backend.app.security import Principal, StaticTokenAuthenticator
from backend.app.settings import Settings
from backend.tests.test_review_tools import _png, _RecordingBrowserDriver, _ORIGIN, _PAGE_URL


class ReviewApplicationTest(unittest.TestCase):
    def setUp(self) -> None:
        knowledge = InMemoryKnowledgeBase()
        knowledge.add(Document(
            id="policy-1", title="Review rule", content="review disclosure evidence",
            source="policy://review",
        ))
        self.driver = _RecordingBrowserDriver()
        registry = create_multisource_review_registry(
            catalog=ReviewResourceCatalog(
                images={"hero-image": ReviewImageAsset("hero-image", "reviewer-1", _png())},
                pages={"policy-page": ReviewPageFixture("policy-page", "reviewer-1", _PAGE_URL)},
            ),
            vision_agent=MultimodalVisionAgent(OfflineVisionModel(), timeout_ms=500),
            knowledge_base=knowledge,
            page_reader=BrowserReviewPageReader(BrowserAgent(allowed_origins=[_ORIGIN]), self.driver),
            publisher=InMemoryReviewPublicationStore({("reviewer-1", "review-1"): 3}),
        )
        app = create_review_app(
            registry=registry,
            authenticator=StaticTokenAuthenticator({
                "review-token": Principal("reviewer-1", roles=frozenset({"reviewer"})),
                "reader-token": Principal("reader-1"),
            }),
        )
        self.client = TestClient(app)
        self.client.__enter__()
        self.addCleanup(self.client.__exit__, None, None, None)
        self.headers = {"Authorization": "Bearer review-token", "Idempotency-Key": "review-create-key"}
        self.body = {
            "review_id": "review-1", "expected_revision": 3,
            "image_asset_id": "hero-image", "policy_topic": "review disclosure",
            "page_fixture_id": "policy-page", "requested_decision": "approve",
        }

    def _create_and_wait(self):
        created = self.client.post("/api/durable/reviews", json=self.body, headers=self.headers)
        self.assertEqual(202, created.status_code, created.text)
        run_id = created.json()["id"]
        for _ in range(100):
            response = self.client.get(f"/api/durable/runs/{run_id}", headers=self.headers)
            if response.json()["status"] != "running" and response.json()["status"] != "queued":
                return response.json()
            time.sleep(0.01)
        self.fail("review did not leave running within bounded wait")

    def test_create_real_tools_approve_and_replay_same_run(self) -> None:
        waiting = self._create_and_wait()
        self.assertEqual("waiting_approval", waiting["status"])
        self.assertEqual(3, len(waiting["review"]["evidence"]))
        # Read the same stored waiting event without holding an open SSE stream.
        events = asyncio.run(self.client.app.state.container.event_store.list_for_run(
            waiting["id"], owner_id="reviewer-1",
        ))
        approval_id = events[-1].data["approval_id"]
        approved = self.client.post(
            f"/api/durable/runs/{waiting['id']}/approvals/{approval_id}",
            json={"decision": "approve"}, headers=self.headers,
        )
        self.assertEqual(200, approved.status_code, approved.text)
        self.assertEqual("published", approved.json()["review"]["outcome"])
        replay = self.client.post("/api/durable/reviews", json=self.body, headers=self.headers)
        self.assertEqual(waiting["id"], replay.json()["id"])
        self.assertEqual("published", replay.json()["review"]["outcome"])
        stream = self.client.get(f"/api/durable/runs/{waiting['id']}/events", headers=self.headers)
        self.assertIn("review.evidence.recorded", stream.text)
        self.assertIn("review.result", stream.text)
        self.assertIn("run.completed", stream.text)

    def test_created_run_can_be_rejected_and_is_owner_scoped(self) -> None:
        waiting = self._create_and_wait()
        path = f"/api/durable/runs/{waiting['id']}"
        self.assertEqual(404, self.client.get(path, headers={"Authorization": "Bearer reader-token"}).status_code)
        events = asyncio.run(self.client.app.state.container.event_store.list_for_run(
            waiting["id"], owner_id="reviewer-1",
        ))
        rejected = self.client.post(
            f"{path}/approvals/{events[-1].data['approval_id']}",
            json={"decision": "reject"}, headers=self.headers,
        )
        self.assertEqual("needs_attention", rejected.json()["review"]["outcome"])
        self.assertIsNone(rejected.json()["review"]["publication"])

    def test_every_business_field_participates_in_idempotency(self) -> None:
        first = self._create_and_wait()
        for field, value in (
            ("review_id", "review-2"), ("expected_revision", 4),
            ("image_asset_id", "other-image"), ("policy_topic", "other topic"),
            ("page_fixture_id", "other-page"), ("requested_decision", "reject"),
        ):
            with self.subTest(field=field):
                result = self.client.post("/api/durable/reviews", json={**self.body, field: value}, headers=self.headers)
                self.assertEqual(409, result.status_code)
        self.assertEqual("waiting_approval", first["status"])

    def test_authentication_role_key_and_control_fields(self) -> None:
        for headers, body, expected in (
            ({}, self.body, 401),
            ({"Authorization": "Bearer reader-token", "Idempotency-Key": "review-create-key"}, self.body, 403),
            ({"Authorization": "Bearer review-token"}, self.body, 400),
            (self.headers, {**self.body, "owner_id": "attacker"}, 422),
            (self.headers, {**self.body, "expected_revision": True}, 422),
            (self.headers, {**self.body, "image_asset_id": "../private"}, 422),
        ):
            with self.subTest(expected=expected, body=body):
                self.assertEqual(expected, self.client.post("/api/durable/reviews", json=body, headers=headers).status_code)

    def test_missing_asset_fails_without_publication(self) -> None:
        self.body["image_asset_id"] = "missing-image"
        failed = self._create_and_wait()
        self.assertEqual("failed", failed["status"])
        self.assertEqual("review_asset_not_found", failed["error"]["code"])
        self.assertIsNone(failed["review"])

    def test_default_app_does_not_enable_review_create(self) -> None:
        with TestClient(create_app(settings=Settings.from_environment({}))) as client:
            self.assertEqual(404, client.post("/api/durable/reviews", json=self.body).status_code)


if __name__ == "__main__":
    unittest.main()
