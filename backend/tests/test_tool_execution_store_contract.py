from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from backend.app.domain import RunRecord, RunStatus, ToolExecution
from backend.app.domain.run import ToolExecutionStatus
from backend.app.stores import (
    ConcurrentWriteError,
    IdempotencyConflictError,
    InMemoryRunStore,
    InMemoryToolExecutionStore,
    InvalidToolExecutionTransitionError,
    RunNotFoundError,
    RunStore,
    ToolExecutionConflictError,
    ToolExecutionNotFoundError,
    ToolExecutionStore,
)


TOOL_NOW = datetime(2026, 8, 3, 5, 0, tzinfo=UTC)
TOOL_STORE_NOW = TOOL_NOW + timedelta(minutes=1)


class ToolExecutionStoreContract:
    """Adapter-independent result-arbitration contract."""

    async def asyncSetUp(self) -> None:
        self.run_store, self.tool_store = await self.create_store_bundle()

    async def create_store_bundle(
        self,
    ) -> tuple[RunStore, ToolExecutionStore]:
        raise NotImplementedError

    async def test_create_get_and_list_are_owner_isolated(self) -> None:
        run = await self._create_run()
        execution = _new_execution()

        created = await self.tool_store.create(
            execution,
            owner_id=run.owner_id,
        )

        self.assertTrue(created.created)
        self.assertEqual(execution, created.record)
        self.assertEqual(
            execution,
            await self.tool_store.get(execution.id, owner_id=run.owner_id),
        )
        self.assertIsNone(
            await self.tool_store.get(execution.id, owner_id="owner-2")
        )
        self.assertEqual(
            (execution,),
            await self.tool_store.list_for_run(
                run.id,
                owner_id=run.owner_id,
            ),
        )
        self.assertEqual(
            (),
            await self.tool_store.list_for_run(run.id, owner_id="owner-2"),
        )

    async def test_create_requires_an_owned_run(self) -> None:
        await self._create_run()

        with self.assertRaises(RunNotFoundError):
            await self.tool_store.create(
                _new_execution(),
                owner_id="owner-2",
            )
        with self.assertRaises(RunNotFoundError):
            await self.tool_store.create(
                _new_execution(run_id="missing-run"),
                owner_id="owner-1",
            )

        queued = RunRecord.create(
            run_id="queued-run",
            session_id="session-1",
            owner_id="owner-1",
            runtime="manual",
            input_text="private queued input",
            idempotency_key="queued-run-key",
            created_at=TOOL_NOW,
        )
        await self.run_store.create(queued)
        with self.assertRaises(InvalidToolExecutionTransitionError):
            await self.tool_store.create(
                _new_execution(
                    execution_id="queued-execution",
                    run_id=queued.id,
                    tool_call_id="queued-call",
                    idempotency_key="queued-tool-key",
                ),
                owner_id=queued.owner_id,
            )

    async def test_idempotency_replay_returns_the_existing_state(self) -> None:
        run = await self._create_run()
        original = _new_execution()
        await self.tool_store.create(original, owner_id=run.owner_id)
        running = await self.tool_store.transition(
            original.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=ToolExecutionStatus.RUNNING,
        )

        replay = await self.tool_store.create(
            _new_execution(
                execution_id="execution-replay",
                tool_call_id="call-replay",
                attempt=2,
            ),
            owner_id=run.owner_id,
        )

        self.assertFalse(replay.created)
        self.assertEqual(running, replay.record)
        self.assertEqual(original.id, replay.record.id)

    async def test_changed_idempotent_request_conflicts_without_secrets(
        self,
    ) -> None:
        run = await self._create_run()
        await self.tool_store.create(
            _new_execution(arguments={"document_id": "private-original"}),
            owner_id=run.owner_id,
        )

        with self.assertRaises(IdempotencyConflictError) as raised:
            await self.tool_store.create(
                _new_execution(
                    execution_id="execution-conflict",
                    tool_call_id="call-conflict",
                    arguments={"document_id": "private-changed"},
                ),
                owner_id=run.owner_id,
            )

        self.assertEqual("idempotency_conflict", raised.exception.code)
        self.assertNotIn("private-original", str(raised.exception))
        self.assertNotIn("private-changed", str(raised.exception))
        self.assertNotIn("private-idempotency-key", str(raised.exception))

    async def test_call_replay_and_conflicts_are_stable(self) -> None:
        run = await self._create_run()
        original = _new_execution(
            side_effecting=False,
            idempotency_key=None,
        )
        await self.tool_store.create(original, owner_id=run.owner_id)

        replay = await self.tool_store.create(
            _new_execution(
                execution_id="execution-same-call",
                side_effecting=False,
                idempotency_key=None,
            ),
            owner_id=run.owner_id,
        )
        self.assertFalse(replay.created)
        self.assertEqual(original, replay.record)

        with self.assertRaises(ToolExecutionConflictError):
            await self.tool_store.create(
                _new_execution(
                    execution_id="execution-call-conflict",
                    arguments={"document_id": "changed"},
                    side_effecting=False,
                    idempotency_key=None,
                ),
                owner_id=run.owner_id,
            )
        with self.assertRaises(ToolExecutionConflictError):
            await self.tool_store.create(
                _new_execution(
                    tool_call_id="different-call",
                    arguments={"document_id": "changed"},
                    side_effecting=False,
                    idempotency_key=None,
                ),
                owner_id=run.owner_id,
            )

    async def test_waiting_claim_and_completed_result_use_version_cas(
        self,
    ) -> None:
        run = await self._create_run()
        execution = _new_execution()
        await self.tool_store.create(execution, owner_id=run.owner_id)

        waiting = await self.tool_store.transition(
            execution.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=ToolExecutionStatus.WAITING_APPROVAL,
        )
        running = await self.tool_store.transition(
            execution.id,
            owner_id=run.owner_id,
            expected_version=waiting.version,
            target_status=ToolExecutionStatus.RUNNING,
        )
        completed = await self.tool_store.transition(
            execution.id,
            owner_id=run.owner_id,
            expected_version=running.version,
            target_status=ToolExecutionStatus.COMPLETED,
            result={"private": "private-result"},
            result_summary="document published",
        )

        self.assertEqual(ToolExecutionStatus.COMPLETED, completed.status)
        self.assertEqual(3, completed.version)
        self.assertEqual(64, len(completed.result_digest or ""))
        self.assertEqual("document published", completed.result_summary)
        self.assertNotIn("private-result", repr(completed))
        with self.assertRaises(InvalidToolExecutionTransitionError):
            await self.tool_store.transition(
                execution.id,
                owner_id=run.owner_id,
                expected_version=completed.version,
                target_status=ToolExecutionStatus.RUNNING,
            )

    async def test_concurrent_claim_has_one_winner(self) -> None:
        run = await self._create_run()
        execution = _new_execution()
        await self.tool_store.create(execution, owner_id=run.owner_id)

        results = await asyncio.gather(
            *(
                self.tool_store.transition(
                    execution.id,
                    owner_id=run.owner_id,
                    expected_version=0,
                    target_status=ToolExecutionStatus.RUNNING,
                )
                for _ in range(2)
            ),
            return_exceptions=True,
        )

        self.assertEqual(
            1,
            sum(isinstance(item, ToolExecution) for item in results),
        )
        self.assertEqual(
            1,
            sum(isinstance(item, ConcurrentWriteError) for item in results),
        )

    async def test_concurrent_terminal_settlement_has_one_winner(self) -> None:
        run = await self._create_run()
        execution = _new_execution()
        await self.tool_store.create(execution, owner_id=run.owner_id)
        running = await self.tool_store.transition(
            execution.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=ToolExecutionStatus.RUNNING,
        )

        results = await asyncio.gather(
            *(
                self.tool_store.transition(
                    execution.id,
                    owner_id=run.owner_id,
                    expected_version=running.version,
                    target_status=ToolExecutionStatus.COMPLETED,
                    result={"private": label},
                    result_summary=label,
                )
                for label in ("first settlement", "second settlement")
            ),
            return_exceptions=True,
        )

        settled = [item for item in results if isinstance(item, ToolExecution)]
        conflicts = [
            item for item in results if isinstance(item, ConcurrentWriteError)
        ]
        self.assertEqual(1, len(settled))
        self.assertEqual(1, len(conflicts))
        self.assertEqual(
            settled[0],
            await self.tool_store.get(execution.id, owner_id=run.owner_id),
        )

    async def test_running_execution_can_only_recover_as_unknown(self) -> None:
        run = await self._create_run()
        execution = _new_execution()
        await self.tool_store.create(execution, owner_id=run.owner_id)
        running = await self.tool_store.transition(
            execution.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=ToolExecutionStatus.RUNNING,
        )
        unknown = await self.tool_store.transition(
            execution.id,
            owner_id=run.owner_id,
            expected_version=running.version,
            target_status=ToolExecutionStatus.UNKNOWN,
            error_code="tool_result_unknown",
            public_message="Tool result could not be confirmed",
        )

        replay = await self.tool_store.create(
            _new_execution(
                execution_id="execution-unknown-replay",
                tool_call_id="call-unknown-replay",
            ),
            owner_id=run.owner_id,
        )

        self.assertEqual(ToolExecutionStatus.UNKNOWN, unknown.status)
        self.assertFalse(replay.created)
        self.assertEqual(unknown, replay.record)
        with self.assertRaises(InvalidToolExecutionTransitionError):
            await self.tool_store.transition(
                execution.id,
                owner_id=run.owner_id,
                expected_version=unknown.version,
                target_status=ToolExecutionStatus.COMPLETED,
                result_summary="must not replay",
            )

    async def test_failure_before_start_and_terminal_run_are_fail_closed(
        self,
    ) -> None:
        run = await self._create_run()
        execution = _new_execution()
        await self.tool_store.create(execution, owner_id=run.owner_id)
        waiting = await self.tool_store.transition(
            execution.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=ToolExecutionStatus.WAITING_APPROVAL,
        )
        failed = await self.tool_store.transition(
            execution.id,
            owner_id=run.owner_id,
            expected_version=waiting.version,
            target_status=ToolExecutionStatus.FAILED,
            error_code="approval_rejected",
            public_message="Approval rejected",
        )

        self.assertIsNone(failed.started_at)
        self.assertIsNotNone(failed.finished_at)
        with self.assertRaises(ToolExecutionNotFoundError):
            await self.tool_store.transition(
                execution.id,
                owner_id="owner-2",
                expected_version=failed.version,
                target_status=ToolExecutionStatus.RUNNING,
            )

        await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=run.version,
            target_status=RunStatus.CANCELLED,
            error_code="run_cancelled",
            public_message="Run cancelled",
        )
        replay = await self.tool_store.create(
            _new_execution(
                execution_id="terminal-replay",
                tool_call_id="terminal-replay-call",
            ),
            owner_id=run.owner_id,
        )
        self.assertFalse(replay.created)
        self.assertEqual(failed, replay.record)
        with self.assertRaises(InvalidToolExecutionTransitionError):
            await self.tool_store.create(
                _new_execution(
                    execution_id="terminal-execution",
                    run_id=run.id,
                    tool_call_id="terminal-call",
                    idempotency_key="terminal-tool-key",
                ),
                owner_id=run.owner_id,
            )

    async def _create_run(
        self,
        *,
        run_id: str = "run-1",
        owner_id: str = "owner-1",
        idempotency_key: str = "run-key",
    ) -> RunRecord:
        run = RunRecord.create(
            run_id=run_id,
            session_id="session-1",
            owner_id=owner_id,
            runtime="manual",
            input_text="private run input",
            idempotency_key=idempotency_key,
            created_at=TOOL_NOW,
        )
        await self.run_store.create(run)
        return await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )


class InMemoryToolExecutionStoreContractTest(
    ToolExecutionStoreContract,
    unittest.IsolatedAsyncioTestCase,
):
    async def create_store_bundle(
        self,
    ) -> tuple[RunStore, ToolExecutionStore]:
        run_store = InMemoryRunStore(clock=lambda: TOOL_STORE_NOW)
        return (
            run_store,
            InMemoryToolExecutionStore(
                run_store,
                clock=lambda: TOOL_STORE_NOW,
            ),
        )


def _new_execution(
    *,
    execution_id: str = "execution-1",
    run_id: str = "run-1",
    tool_call_id: str = "call-1",
    arguments: dict[str, object] | None = None,
    side_effecting: bool = True,
    idempotency_key: str | None = "private-idempotency-key",
    attempt: int = 1,
) -> ToolExecution:
    return ToolExecution.create(
        execution_id=execution_id,
        run_id=run_id,
        tool_call_id=tool_call_id,
        tool_name="publish_report",
        arguments=(
            arguments
            if arguments is not None
            else {"document_id": "fixture-document"}
        ),
        side_effecting=side_effecting,
        idempotency_key=idempotency_key,
        attempt=attempt,
        created_at=TOOL_NOW,
    )


if __name__ == "__main__":
    unittest.main()
