from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from backend.app.tools import (
    ApprovalResolutionError,
    ApprovalResolutionStatus,
    ApprovalResponse,
    ApprovalStore,
    InMemoryApprovalStore,
    ToolApprovalResolution,
)


APPROVAL_NOW = datetime(2026, 8, 3, 2, 0, tzinfo=UTC)


class ApprovalStoreContract:
    """Adapter-independent approval contract for memory and PostgreSQL."""

    async def asyncSetUp(self) -> None:
        self.now = APPROVAL_NOW
        self.approval_store = await self.create_approval_store()

    async def create_approval_store(self) -> ApprovalStore:
        raise NotImplementedError

    async def test_request_is_idempotent_and_private_arguments_are_detached(
        self,
    ) -> None:
        arguments = {
            "document_id": "fixture-document",
            "options": {"publish": True},
        }
        request = self._request(arguments=arguments)
        arguments["options"]["publish"] = False

        replay = self._request(
            arguments={
                "document_id": "fixture-document",
                "options": {"publish": True},
            }
        )
        resolution = self._resolve(request.id, request.arguments_digest)

        self.assertEqual(request, replay)
        self.assertEqual(
            {
                "document_id": "fixture-document",
                "options": {"publish": True},
            },
            self.approval_store.approved_arguments(resolution),
        )

    async def test_changed_arguments_create_a_distinct_request(self) -> None:
        first = self._request(arguments={"document_id": "one"})
        second = self._request(arguments={"document_id": "two"})

        self.assertNotEqual(first.id, second.id)
        self.assertNotEqual(first.arguments_digest, second.arguments_digest)

    async def test_approved_request_consumes_exactly_once(self) -> None:
        request = self._request()
        resolution = self._resolve(request.id, request.arguments_digest)

        first = self._consume()
        second = self._consume()

        self.assertEqual(ApprovalResolutionStatus.APPROVED, resolution.status)
        self.assertTrue(first.approved)
        self.assertEqual("approved", first.reason)
        self.assertFalse(second.approved)
        self.assertEqual("approval_already_consumed", second.reason)

    async def test_rejection_persists_without_private_argument_access(self) -> None:
        request = self._request()
        resolution = self._resolve(
            request.id,
            request.arguments_digest,
            decision=ApprovalResponse.REJECT,
        )

        self.assertEqual(ApprovalResolutionStatus.REJECTED, resolution.status)
        with self.assertRaises(ApprovalResolutionError) as raised:
            self.approval_store.approved_arguments(resolution)
        self.assertEqual("approval_not_approved", raised.exception.code)
        self.assertEqual(
            "exact_call_approval_missing",
            self._consume().reason,
        )

    async def test_forged_resolution_cannot_read_pending_arguments(self) -> None:
        request = self._request()
        forged = ToolApprovalResolution(
            request=request,
            status=ApprovalResolutionStatus.APPROVED,
        )

        with self.assertRaises(ApprovalResolutionError) as raised:
            self.approval_store.approved_arguments(forged)

        self.assertEqual("approval_resolution_mismatch", raised.exception.code)

    async def test_expiry_is_derived_from_the_store_clock(self) -> None:
        request = self._request(expires_in=timedelta(seconds=1))
        self.now += timedelta(seconds=1)

        resolution = self._resolve(request.id, request.arguments_digest)

        self.assertEqual(ApprovalResolutionStatus.EXPIRED, resolution.status)
        self.assertEqual(
            "exact_call_approval_missing",
            self._consume().reason,
        )

    async def test_owner_and_binding_mismatches_fail_closed(self) -> None:
        request = self._request()

        with self.assertRaises(ApprovalResolutionError) as hidden:
            self.approval_store.resolve(
                approval_id=request.id,
                run_id=request.run_id,
                principal_id="other-owner",
                tool_call_id=request.tool_call_id,
                tool_name=request.tool_name,
                arguments_digest=request.arguments_digest,
                decision=ApprovalResponse.APPROVE,
            )
        with self.assertRaises(ApprovalResolutionError) as mismatch:
            self.approval_store.resolve(
                approval_id=request.id,
                run_id=request.run_id,
                principal_id=request.principal_id,
                tool_call_id="changed-call",
                tool_name=request.tool_name,
                arguments_digest=request.arguments_digest,
                decision=ApprovalResponse.APPROVE,
            )

        self.assertEqual("approval_request_not_found", hidden.exception.code)
        self.assertEqual("approval_binding_mismatch", mismatch.exception.code)

    async def test_resolution_replay_is_stable_and_conflict_is_rejected(
        self,
    ) -> None:
        request = self._request()
        first = self._resolve(request.id, request.arguments_digest)
        replay = self._resolve(request.id, request.arguments_digest)

        self.assertEqual(first, replay)
        with self.assertRaises(ApprovalResolutionError) as raised:
            self._resolve(
                request.id,
                request.arguments_digest,
                decision=ApprovalResponse.REJECT,
            )
        self.assertEqual("approval_decision_conflict", raised.exception.code)

    async def test_direct_grant_is_run_bound_and_single_use(self) -> None:
        self.approval_store.grant(
            principal_id="owner-1",
            run_id="run-1",
            tool_call_id="call-1",
            tool_name="publish_report",
            arguments={"document_id": "fixture-document"},
        )

        wrong_run = self._consume(run_id="run-2")
        allowed = self._consume()

        self.assertFalse(wrong_run.approved)
        self.assertEqual("exact_call_approval_missing", wrong_run.reason)
        self.assertTrue(allowed.approved)

    async def test_concurrent_consume_has_one_winner(self) -> None:
        request = self._request()
        self._resolve(request.id, request.arguments_digest)

        first, second = await asyncio.gather(
            asyncio.to_thread(self._consume),
            asyncio.to_thread(self._consume),
        )

        self.assertEqual(1, sum(item.approved for item in (first, second)))
        self.assertEqual(
            {"approved", "approval_already_consumed"},
            {first.reason, second.reason},
        )

    async def test_oversized_private_arguments_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self._request(arguments={"content": "x" * 64_001})

    def _request(
        self,
        *,
        arguments: dict[str, object] | None = None,
        expires_in: timedelta | None = None,
    ):
        return self.approval_store.request(
            run_id="run-1",
            principal_id="owner-1",
            tool_call_id="call-1",
            tool_name="publish_report",
            arguments=(
                arguments
                if arguments is not None
                else {"document_id": "fixture-document"}
            ),
            expires_in=expires_in,
        )

    def _resolve(
        self,
        approval_id: str,
        arguments_digest: str,
        *,
        decision: ApprovalResponse = ApprovalResponse.APPROVE,
    ):
        return self.approval_store.resolve(
            approval_id=approval_id,
            run_id="run-1",
            principal_id="owner-1",
            tool_call_id="call-1",
            tool_name="publish_report",
            arguments_digest=arguments_digest,
            decision=decision,
        )

    def _consume(self, *, run_id: str = "run-1"):
        return self.approval_store.consume(
            principal_id="owner-1",
            run_id=run_id,
            tool_call_id="call-1",
            tool_name="publish_report",
            arguments={"document_id": "fixture-document"},
        )


class InMemoryApprovalStoreContractTest(
    ApprovalStoreContract,
    unittest.IsolatedAsyncioTestCase,
):
    async def create_approval_store(self) -> ApprovalStore:
        return InMemoryApprovalStore(clock=lambda: self.now)


if __name__ == "__main__":
    unittest.main()
