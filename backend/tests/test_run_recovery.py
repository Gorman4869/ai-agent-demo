from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from backend.app.domain import RunFailure, RunRecord, RunStatus, ToolExecution
from backend.app.domain.run import ToolExecutionStatus
from backend.app.services.run_recovery import (
    RunRecoveryService,
    RunRecoveryStatus,
)
from backend.app.stores import (
    InMemoryEventStore,
    InMemoryRunLeaseStore,
    InMemoryRunStore,
    InMemoryToolExecutionStore,
    PauseCommit,
    StartCommit,
    StoreUnavailableError,
    TerminalCommit,
)


RECOVERY_NOW = datetime(2026, 8, 3, 7, 0, tzinfo=UTC)


class _MutableClock:
    def __init__(self) -> None:
        self.now = RECOVERY_NOW

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class _FailingTerminalEventStore:
    async def commit_terminal(self, command: TerminalCommit):
        raise StoreUnavailableError()


class RunRecoveryServiceTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.clock = _MutableClock()
        self.token_sequence = 0
        self.run_store = InMemoryRunStore(clock=self.clock)
        self.event_store = InMemoryEventStore(
            self.run_store,
            clock=self.clock,
        )
        self.tool_store = InMemoryToolExecutionStore(
            self.run_store,
            clock=self.clock,
        )
        self.lease_store = InMemoryRunLeaseStore(
            self.run_store,
            clock=self.clock,
            token_factory=self._token_factory,
        )
        self.service = RunRecoveryService(
            run_store=self.run_store,
            event_store=self.event_store,
            tool_execution_store=self.tool_store,
            run_lease_store=self.lease_store,
        )

    async def test_expired_running_run_and_tools_fail_closed(self) -> None:
        run = await self._create_running_run()
        pending = await self._create_tool("pending")
        waiting = await self._create_tool("waiting")
        running = await self._create_tool("running")
        completed = await self._create_tool("completed")
        await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=timedelta(seconds=5),
        )
        self.clock.advance(timedelta(seconds=6))

        results = await self.service.scan_once(
            recovery_ttl=timedelta(seconds=30)
        )

        self.assertEqual(1, len(results))
        self.assertEqual(RunRecoveryStatus.RECOVERED, results[0].status)
        self.assertEqual(1, results[0].unknown_tool_count)
        self.assertEqual(2, results[0].cancelled_tool_count)
        stored_run = await self.run_store.get(run.id, owner_id=run.owner_id)
        self.assertEqual(RunStatus.FAILED, stored_run.status)
        self.assertEqual("run_orphaned", stored_run.failure.code)
        self.assertFalse(stored_run.failure.retryable)
        self.assertEqual(
            ToolExecutionStatus.CANCELLED,
            (await self.tool_store.get(pending.id, owner_id=run.owner_id)).status,
        )
        self.assertEqual(
            ToolExecutionStatus.CANCELLED,
            (await self.tool_store.get(waiting.id, owner_id=run.owner_id)).status,
        )
        self.assertEqual(
            ToolExecutionStatus.UNKNOWN,
            (await self.tool_store.get(running.id, owner_id=run.owner_id)).status,
        )
        self.assertEqual(
            ToolExecutionStatus.COMPLETED,
            (await self.tool_store.get(completed.id, owner_id=run.owner_id)).status,
        )
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )
        self.assertEqual(["run.started", "run.failed"], [item.type for item in events])
        self.assertEqual(
            (),
            await self.lease_store.claim_expired(
                limit=10,
                ttl=timedelta(seconds=30),
            ),
        )

    async def test_terminal_run_only_cleans_up_its_stale_lease(self) -> None:
        run = await self._create_running_run()
        await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=timedelta(seconds=5),
        )
        await self.event_store.commit_terminal(
            TerminalCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=run.version,
                target_status=RunStatus.COMPLETED,
                event_id="terminal-before-recovery",
                event_data={"status": "completed"},
                answer="completed elsewhere",
            )
        )
        self.clock.advance(timedelta(seconds=6))

        results = await self.service.scan_once()

        self.assertEqual(RunRecoveryStatus.ALREADY_TERMINAL, results[0].status)
        stored = await self.run_store.get(run.id, owner_id=run.owner_id)
        self.assertEqual(RunStatus.COMPLETED, stored.status)
        self.assertEqual("completed elsewhere", stored.answer)
        self.assertEqual(
            (),
            await self.lease_store.claim_expired(
                limit=10,
                ttl=timedelta(seconds=30),
            ),
        )

    async def test_waiting_approval_run_is_not_failed_by_recovery(self) -> None:
        run = await self._create_running_run()
        pending = await self._create_tool("pending")
        await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=timedelta(seconds=5),
        )
        await self.event_store.commit_pause(
            PauseCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=run.version,
                event_id="waiting-before-recovery",
                event_data={"status": "waiting_approval"},
            )
        )
        self.clock.advance(timedelta(seconds=6))

        results = await self.service.scan_once()

        self.assertEqual(RunRecoveryStatus.NOT_RUNNING, results[0].status)
        stored = await self.run_store.get(run.id, owner_id=run.owner_id)
        self.assertEqual(RunStatus.WAITING_APPROVAL, stored.status)
        self.assertEqual(
            ToolExecutionStatus.PENDING,
            (await self.tool_store.get(pending.id, owner_id=run.owner_id)).status,
        )

    async def test_partial_store_failure_converges_on_the_next_scan(self) -> None:
        run = await self._create_running_run()
        running = await self._create_tool("running")
        await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=timedelta(seconds=5),
        )
        self.clock.advance(timedelta(seconds=6))
        failing = RunRecoveryService(
            run_store=self.run_store,
            event_store=_FailingTerminalEventStore(),
            tool_execution_store=self.tool_store,
            run_lease_store=self.lease_store,
        )

        first = await failing.scan_once(
            recovery_ttl=timedelta(seconds=5)
        )

        self.assertEqual(RunRecoveryStatus.FAILED, first[0].status)
        self.assertEqual("store_unavailable", first[0].error_code)
        self.assertEqual(
            ToolExecutionStatus.UNKNOWN,
            (await self.tool_store.get(running.id, owner_id=run.owner_id)).status,
        )
        self.assertEqual(
            RunStatus.RUNNING,
            (await self.run_store.get(run.id, owner_id=run.owner_id)).status,
        )

        self.clock.advance(timedelta(seconds=6))
        second = await self.service.scan_once()

        self.assertEqual(RunRecoveryStatus.RECOVERED, second[0].status)
        self.assertEqual(0, second[0].unknown_tool_count)
        self.assertEqual(
            RunStatus.FAILED,
            (await self.run_store.get(run.id, owner_id=run.owner_id)).status,
        )

    async def _create_running_run(self) -> RunRecord:
        run = RunRecord.create(
            run_id="recovery-run",
            session_id="recovery-session",
            owner_id="recovery-owner",
            runtime="manual",
            input_text="private recovery input",
            idempotency_key="recovery-run-key",
            created_at=self.clock(),
        )
        await self.run_store.create(run)
        return (
            await self.event_store.commit_start(
                StartCommit(
                    run_id=run.id,
                    owner_id=run.owner_id,
                    expected_version=run.version,
                    event_id="recovery-run-started",
                    event_data={"status": "running", "runtime": "manual"},
                )
            )
        ).record

    async def _create_tool(self, status: str) -> ToolExecution:
        execution = ToolExecution.create(
            execution_id=f"tool-{status}",
            run_id="recovery-run",
            tool_call_id=f"call-{status}",
            tool_name="publish_report",
            arguments={"document_id": status},
            side_effecting=True,
            idempotency_key=f"tool-key-{status}",
            created_at=self.clock(),
        )
        await self.tool_store.create(execution, owner_id="recovery-owner")
        if status == "pending":
            return execution
        if status == "waiting":
            return await self.tool_store.transition(
                execution.id,
                owner_id="recovery-owner",
                expected_version=execution.version,
                target_status=ToolExecutionStatus.WAITING_APPROVAL,
            )
        running = await self.tool_store.transition(
            execution.id,
            owner_id="recovery-owner",
            expected_version=execution.version,
            target_status=ToolExecutionStatus.RUNNING,
        )
        if status == "running":
            return running
        if status == "completed":
            return await self.tool_store.transition(
                execution.id,
                owner_id="recovery-owner",
                expected_version=running.version,
                target_status=ToolExecutionStatus.COMPLETED,
                result={"private": "private-result"},
                result_summary="already completed",
            )
        raise ValueError("unsupported test tool status")

    def _token_factory(self) -> str:
        self.token_sequence += 1
        return f"recovery-token-{self.token_sequence:049d}"


if __name__ == "__main__":
    unittest.main()
