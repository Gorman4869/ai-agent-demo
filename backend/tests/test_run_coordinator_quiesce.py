from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from backend.app.agent import RuntimeResult
from backend.app.domain.run import RunRecord, RunStatus
from backend.app.services.run_coordinator import (
    RunCoordinator,
    RunCoordinatorAdmissionError,
    RunCoordinatorState,
)
from backend.app.stores import (
    InMemoryEventStore,
    InMemoryRunLeaseStore,
    InMemoryRunStore,
)
from backend.app.tools import (
    ApprovalResponse,
    InMemoryApprovalStore,
    ToolExecutionContext,
)


NOW = datetime(2026, 8, 8, 5, 0, tzinfo=UTC)


class RunCoordinatorQuiesceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.run_store = InMemoryRunStore()
        self.event_store = InMemoryEventStore(self.run_store)
        self.lease_store = RecordingLeaseStore(self.run_store)

    async def test_idle_quiesce_is_idempotent_and_rejects_new_admission(
        self,
    ) -> None:
        run = await self._create_run("idle-quiesce-run")
        coordinator = self._coordinator(GatedRuntime())

        await coordinator.quiesce(timeout_ms=10)
        await coordinator.quiesce(timeout_ms=10)

        self.assertEqual(RunCoordinatorState.QUIESCED, coordinator.state)
        with self.assertRaises(RunCoordinatorAdmissionError) as execute_error:
            await coordinator.execute(run.id, owner_id=run.owner_id)
        self.assertEqual("coordinator_not_accepting", execute_error.exception.code)

        context = ToolExecutionContext(
            principal_id=run.owner_id,
            approval_store=InMemoryApprovalStore(),
        )
        with self.assertRaises(RunCoordinatorAdmissionError):
            await coordinator.resume_approval(
                run.id,
                owner_id=run.owner_id,
                approval_id="approval-id",
                tool_call_id="tool-call-id",
                tool_name="publish_report",
                arguments_digest="arguments-digest",
                decision=ApprovalResponse.APPROVE,
                execution_context=context,
            )

    async def test_quiesce_waits_for_active_run_and_rejects_new_execute(
        self,
    ) -> None:
        run = await self._create_run("graceful-drain-run")
        rejected = await self._create_run("rejected-during-drain-run")
        runtime = GatedRuntime()
        coordinator = self._coordinator(runtime)
        execution = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)

        quiescing = asyncio.create_task(coordinator.quiesce(timeout_ms=1_000))
        await _wait_for_state(coordinator, RunCoordinatorState.QUIESCING)
        with self.assertRaises(RunCoordinatorAdmissionError):
            await coordinator.execute(rejected.id, owner_id=rejected.owner_id)
        self.assertFalse(quiescing.done())

        runtime.release.set()
        result = await asyncio.wait_for(execution, timeout=1)
        await asyncio.wait_for(quiescing, timeout=1)

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual(1, self.lease_store.release_calls)
        self.assertEqual(RunCoordinatorState.QUIESCED, coordinator.state)

    async def test_quiesce_timeout_abandons_running_run_and_lease_for_recovery(
        self,
    ) -> None:
        run = await self._create_run("quiesce-timeout-run")
        runtime = BlockingRuntime()
        coordinator = self._coordinator(runtime, lease_ttl_ms=40)
        execution = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)
        await asyncio.wait_for(self.lease_store.heartbeat_seen.wait(), timeout=1)

        await coordinator.quiesce(timeout_ms=10)
        with self.assertRaises(asyncio.CancelledError):
            await execution

        heartbeat_calls = self.lease_store.heartbeat_calls
        await asyncio.sleep(0.02)
        stored = await self.run_store.get(run.id, owner_id=run.owner_id)
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )
        self.assertTrue(runtime.cancelled.is_set())
        self.assertEqual(RunStatus.RUNNING, stored.status)
        self.assertEqual(["run.started"], [event.type for event in events])
        self.assertEqual(0, self.lease_store.release_calls)
        self.assertEqual(heartbeat_calls, self.lease_store.heartbeat_calls)

        await asyncio.sleep(0.04)
        claimed = await self.lease_store.claim_expired(
            limit=1,
            ttl=timedelta(seconds=1),
        )
        self.assertEqual(1, len(claimed))
        await self.lease_store.release(claimed[0])

    async def test_cancelling_quiesce_waiter_finishes_cleanup_then_propagates(
        self,
    ) -> None:
        run = await self._create_run("cancelled-quiesce-waiter-run")
        runtime = BlockingRuntime()
        coordinator = self._coordinator(runtime)
        execution = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)

        waiter = asyncio.create_task(coordinator.quiesce(timeout_ms=10))
        await _wait_for_state(coordinator, RunCoordinatorState.QUIESCING)
        waiter.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(waiter, timeout=1)
        with self.assertRaises(asyncio.CancelledError):
            await execution

        stored = await self.run_store.get(run.id, owner_id=run.owner_id)
        self.assertEqual(RunCoordinatorState.QUIESCED, coordinator.state)
        self.assertTrue(runtime.cancelled.is_set())
        self.assertEqual(RunStatus.RUNNING, stored.status)

    async def test_concurrent_quiesce_calls_share_one_graceful_drain(self) -> None:
        run = await self._create_run("concurrent-quiesce-run")
        runtime = GatedRuntime()
        coordinator = self._coordinator(runtime)
        execution = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)

        first = asyncio.create_task(coordinator.quiesce(timeout_ms=1_000))
        second = asyncio.create_task(coordinator.quiesce(timeout_ms=10))
        await _wait_for_state(coordinator, RunCoordinatorState.QUIESCING)
        runtime.release.set()

        await asyncio.gather(first, second)
        result = await execution
        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual(1, self.lease_store.release_calls)
        self.assertEqual(RunCoordinatorState.QUIESCED, coordinator.state)

    async def test_quiesce_timeout_must_be_a_positive_integer(self) -> None:
        coordinator = self._coordinator(GatedRuntime())

        for timeout_ms in (0, -1, True, 1.5):
            with self.subTest(timeout_ms=timeout_ms):
                with self.assertRaises(ValueError):
                    await coordinator.quiesce(timeout_ms=timeout_ms)

        self.assertEqual(RunCoordinatorState.ACCEPTING, coordinator.state)

    async def _create_run(self, run_id: str) -> RunRecord:
        run = RunRecord.create(
            run_id=run_id,
            session_id="quiesce-session",
            owner_id="quiesce-owner",
            runtime="manual",
            input_text="private quiesce input",
            idempotency_key=f"{run_id}-key",
            created_at=NOW,
        )
        await self.run_store.create(run)
        return run

    def _coordinator(
        self,
        runtime,
        *,
        lease_ttl_ms: int = 100,
    ) -> RunCoordinator:
        return RunCoordinator(
            run_store=self.run_store,
            event_store=self.event_store,
            runtimes={"manual": runtime},
            run_lease_store=self.lease_store,
            run_timeout_ms=1_000,
            lease_ttl_ms=lease_ttl_ms,
            lease_heartbeat_interval_ms=5,
        )


class GatedRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit, control
        self.started.set()
        await self.release.wait()
        return RuntimeResult(status=RunStatus.COMPLETED, answer="done")


class BlockingRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit, control
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class RecordingLeaseStore(InMemoryRunLeaseStore):
    def __init__(self, run_store: InMemoryRunStore) -> None:
        super().__init__(run_store)
        self.heartbeat_calls = 0
        self.release_calls = 0
        self.heartbeat_seen = asyncio.Event()

    async def heartbeat(self, lease, **kwargs):
        heartbeat = await super().heartbeat(lease, **kwargs)
        self.heartbeat_calls += 1
        self.heartbeat_seen.set()
        return heartbeat

    async def release(self, lease):
        await super().release(lease)
        self.release_calls += 1


async def _wait_for_state(
    coordinator: RunCoordinator,
    state: RunCoordinatorState,
) -> None:
    deadline = asyncio.get_running_loop().time() + 1
    while asyncio.get_running_loop().time() < deadline:
        if coordinator.state is state:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"Coordinator did not reach {state.value}")


if __name__ == "__main__":
    unittest.main()
