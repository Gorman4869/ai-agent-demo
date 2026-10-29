from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace

from backend.app.advanced.review_application import InMemoryReviewRuns
from backend.app.stores import IdempotencyConflictError
from backend.tests.test_review_runtime import _RecordingRegistry, _RecordingPublicationStore, _run_spec


class ReviewRequestStoreContract:
    async def asyncSetUp(self) -> None:
        self.store = await self.create_store()

    async def create_store(self):
        raise NotImplementedError

    async def test_create_resolve_and_same_key_replay(self) -> None:
        first = await self.store.create(_run_spec(), owner_id="reviewer-1", idempotency_key="review-request-key")
        second = await self.store.create(_run_spec(), owner_id="reviewer-1", idempotency_key="review-request-key")
        self.assertTrue(first.created)
        self.assertFalse(second.created)
        self.assertEqual(first.record, second.record)
        self.assertEqual(_run_spec(), await self.store.resolve(first.record.id, owner_id="reviewer-1"))
        self.assertNotIn(_run_spec().policy_topic, repr(first))

    async def test_changed_business_field_conflicts(self) -> None:
        await self.store.create(_run_spec(), owner_id="reviewer-1", idempotency_key="review-request-key")
        for field, value in (
            ("review_id", "review-2"), ("expected_revision", 4),
            ("image_asset_id", "image-2"), ("policy_topic", "changed topic"),
            ("page_fixture_id", "page-2"), ("requested_decision", "reject"),
        ):
            with self.subTest(field=field), self.assertRaises(IdempotencyConflictError):
                await self.store.create(replace(_run_spec(), **{field: value}), owner_id="reviewer-1", idempotency_key="review-request-key")

    async def test_missing_and_cross_owner_are_indistinguishable(self) -> None:
        first = await self.store.create(_run_spec(), owner_id="reviewer-1", idempotency_key="review-request-key")
        self.assertIsNone(await self.store.resolve(first.record.id, owner_id="other-owner"))
        self.assertIsNone(await self.store.resolve("missing-run", owner_id="reviewer-1"))

    async def test_concurrent_create_has_one_winner_and_complete_binding(self) -> None:
        results = await asyncio.gather(*(
            self.store.create(_run_spec(), owner_id="reviewer-1", idempotency_key="review-request-key")
            for _ in range(2)
        ))
        self.assertEqual(1, sum(result.created for result in results))
        self.assertEqual(results[0].record.id, results[1].record.id)
        self.assertEqual(_run_spec(), await self.store.resolve(results[0].record.id, owner_id="reviewer-1"))


class InMemoryReviewRequestStoreTest(ReviewRequestStoreContract, unittest.IsolatedAsyncioTestCase):
    async def create_store(self):
        return InMemoryReviewRuns(_RecordingRegistry(publisher=_RecordingPublicationStore()))
