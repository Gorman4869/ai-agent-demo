from __future__ import annotations

import unittest

from backend.app.advanced.review_publication import (
    InMemoryReviewPublicationStore,
)
from backend.app.advanced.review_tools import ReviewPublicationCommand
from backend.app.tools import ToolHandlerError


class InMemoryReviewPublicationStoreTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.store = InMemoryReviewPublicationStore(
            {
                ("owner-1", "review-1"): 3,
                ("owner-2", "review-1"): 8,
            }
        )

    async def test_publish_reconcile_and_business_key_replay(self) -> None:
        command = _command()

        first = await self.store.publish(command)
        replay = await self.store.publish(command)
        reconciled = await self.store.reconcile(command)

        self.assertEqual(first, replay)
        self.assertEqual(first, reconciled)
        self.assertEqual(4, first.revision)
        self.assertNotIn("private-owner", repr(self.store))

    async def test_revision_conflict_is_content_free(self) -> None:
        await self.store.publish(_command())

        with self.assertRaises(ToolHandlerError) as raised:
            await self.store.publish(
                _command(idempotency_key="b" * 64)
            )

        self.assertEqual("review_revision_conflict", raised.exception.code)
        self.assertNotIn("review-1", str(raised.exception))

    async def test_owner_scopes_are_independent(self) -> None:
        first = await self.store.publish(_command())
        second = await self.store.publish(
            _command(
                owner_id="owner-2",
                expected_revision=8,
                idempotency_key="c" * 64,
            )
        )

        self.assertEqual(4, first.revision)
        self.assertEqual(9, second.revision)
        self.assertNotEqual(first.publication_id, second.publication_id)

    async def test_reconcile_missing_does_not_publish(self) -> None:
        self.assertIsNone(await self.store.reconcile(_command()))
        published = await self.store.publish(_command())
        self.assertEqual(4, published.revision)


def _command(
    *,
    owner_id: str = "owner-1",
    expected_revision: int = 3,
    idempotency_key: str = "a" * 64,
) -> ReviewPublicationCommand:
    return ReviewPublicationCommand(
        owner_id=owner_id,
        run_id="run-1",
        review_id="review-1",
        expected_revision=expected_revision,
        requested_decision="approve",
        evidence_bundle_digest="d" * 64,
        idempotency_key=idempotency_key,
    )


if __name__ == "__main__":
    unittest.main()
