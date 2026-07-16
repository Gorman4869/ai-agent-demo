from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime

from backend.app.agent import RuntimeEvent, RuntimeResult
from backend.app.domain.run import RunFailure, RunRecord, RunStatus, StoredRunEvent
from backend.app.services.run_coordinator import (
    EventNotifier,
    PersistentEventEmitter,
    RunCoordinator,
)
from backend.app.stores import (
    InMemoryEventStore,
    InMemoryRunStore,
    RunNotFoundError,
    StoreUnavailableError,
)


NOW = datetime(2026, 7, 16, 5, 0, tzinfo=UTC)


class RunCoordinatorTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.run_store = InMemoryRunStore()
        self.event_store = InMemoryEventStore(self.run_store)

    async def test_success_persists_in_order_and_notifies_after_commit(self) -> None:
        run = await self._create_run()
        runtime = StaticRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="done", step=2),
            events=(
                RuntimeEvent(
                    type="model.completed",
                    step=2,
                    data={"model_call": 1},
                ),
            ),
        )
        notifier = InspectingNotifier(self.run_store, self.event_store, run)
        coordinator = self._coordinator(runtime, notifier=notifier)

        result = await coordinator.execute(run.id, owner_id=run.owner_id)
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual("done", result.answer)
        self.assertEqual(
            ["run.started", "model.completed", "run.completed"],
            [event.type for event in events],
        )
        self.assertEqual([1, 2, 3], [event.sequence for event in events])
        self.assertEqual(
            [
                ("run.started", RunStatus.RUNNING),
                ("model.completed", RunStatus.RUNNING),
                ("run.completed", RunStatus.COMPLETED),
            ],
            notifier.observations,
        )

    async def test_notifier_failure_does_not_rollback_or_fail_the_run(self) -> None:
        run = await self._create_run()
        runtime = StaticRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="done")
        )
        coordinator = self._coordinator(runtime, notifier=FailingNotifier())

        result = await coordinator.execute(run.id, owner_id=run.owner_id)
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual(["run.started", "run.completed"], _types(events))

    async def test_start_commit_failure_changes_nothing_and_starts_no_runtime(
        self,
    ) -> None:
        run_store = InMemoryRunStore()
        event_store = FailingStartEventStore(run_store)
        run = _new_run()
        await run_store.create(run)
        runtime = StaticRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="must-not-run")
        )
        notifier = RecordingNotifier()
        coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={"manual": runtime},
            notifier=notifier,
            run_timeout_ms=1_000,
        )

        with self.assertRaises(StoreUnavailableError):
            await coordinator.execute(run.id, owner_id=run.owner_id)

        self.assertEqual(0, runtime.calls)
        self.assertEqual([], notifier.events)
        self.assertEqual(
            RunStatus.QUEUED,
            (await run_store.get(run.id, owner_id=run.owner_id)).status,
        )

    async def test_progress_store_unavailable_fails_closed_for_recovery(self) -> None:
        run_store = InMemoryRunStore()
        event_store = FailingProgressEventStore(run_store)
        run = _new_run()
        await run_store.create(run)
        runtime = StaticRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="must-not-settle"),
            events=(RuntimeEvent(type="model.completed", step=1, data={}),),
        )
        notifier = RecordingNotifier()
        coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={"manual": runtime},
            notifier=notifier,
            run_timeout_ms=1_000,
        )

        with self.assertRaises(StoreUnavailableError):
            await coordinator.execute(run.id, owner_id=run.owner_id)

        stored = await run_store.get(run.id, owner_id=run.owner_id)
        events = await event_store.list_for_run(run.id, owner_id=run.owner_id)
        self.assertEqual(RunStatus.RUNNING, stored.status)
        self.assertEqual(["run.started"], _types(events))
        self.assertEqual(["run.started"], [event.type for event in notifier.events])

    async def test_unknown_runtime_fails_closed_with_a_safe_terminal_event(
        self,
    ) -> None:
        run = await self._create_run(runtime="langgraph")
        configured = StaticRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="wrong")
        )
        coordinator = self._coordinator(configured)

        result = await coordinator.execute(run.id, owner_id=run.owner_id)
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("runtime_not_configured", result.failure.code)
        self.assertEqual(0, configured.calls)
        self.assertEqual(["run.started", "run.failed"], _types(events))

    async def test_runtime_exception_is_normalized_without_secret_leak(self) -> None:
        run = await self._create_run()
        secret = "runtime-exception-secret"
        coordinator = self._coordinator(RaisingRuntime(secret))

        result = await coordinator.execute(run.id, owner_id=run.owner_id)
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("runtime_execution_failed", result.failure.code)
        self.assertNotIn(secret, result.failure.public_message)
        self.assertNotIn(secret, repr(events))

    async def test_total_timeout_cancels_runtime_before_terminal_commit(self) -> None:
        run = await self._create_run()
        runtime = SleepingRuntime()
        coordinator = self._coordinator(runtime, run_timeout_ms=20)

        result = await asyncio.wait_for(
            coordinator.execute(run.id, owner_id=run.owner_id),
            timeout=1,
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("run_timeout", result.failure.code)
        self.assertTrue(runtime.cancelled.is_set())
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )
        self.assertEqual(["run.started", "run.failed"], _types(events))

    async def test_pre_runtime_delay_consumes_the_total_execution_budget(self) -> None:
        run = await self._create_run()
        runtime = StaticRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="must-not-run")
        )
        coordinator = self._coordinator(
            runtime,
            notifier=SlowStartNotifier(),
            run_timeout_ms=10,
        )

        result = await coordinator.execute(run.id, owner_id=run.owner_id)

        self.assertEqual(0, runtime.calls)
        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("run_timeout", result.failure.code)

    async def test_user_cancel_wins_before_a_late_completed_result(self) -> None:
        run = await self._create_run()
        runtime = CancellationAwareRuntime()
        coordinator = self._coordinator(runtime)
        execution = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)

        accepted = await coordinator.cancel(run.id, owner_id=run.owner_id)
        result = await asyncio.wait_for(execution, timeout=1)

        self.assertTrue(accepted)
        self.assertEqual(RunStatus.CANCELLED, result.status)
        self.assertEqual("cancelled_by_user", result.failure.code)
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )
        self.assertEqual("run.cancelled", events[-1].type)

    async def test_cancel_and_completed_settlement_use_store_cas_as_arbiter(
        self,
    ) -> None:
        run_store = InMemoryRunStore()
        event_store = BarrierTerminalEventStore(run_store)
        run = _new_run()
        await run_store.create(run)
        runtime = StaticRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="too late")
        )
        coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={"manual": runtime},
            run_timeout_ms=1_000,
        )
        execution = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(event_store.completed_entered.wait(), timeout=1)

        accepted = await coordinator.cancel(run.id, owner_id=run.owner_id)
        event_store.release_completed.set()
        result = await asyncio.wait_for(execution, timeout=1)
        events = await event_store.list_for_run(run.id, owner_id=run.owner_id)

        self.assertTrue(accepted)
        self.assertEqual(RunStatus.CANCELLED, result.status)
        self.assertEqual(
            ["run.started", "run.cancelled"],
            [event.type for event in events],
        )

    async def test_cancel_during_blocked_append_returns_durable_winner(self) -> None:
        run_store = InMemoryRunStore()
        event_store = BarrierProgressEventStore(run_store)
        run = _new_run()
        await run_store.create(run)
        runtime = StaticRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="too late"),
            events=(RuntimeEvent(type="model.completed", step=1, data={}),),
        )
        coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={"manual": runtime},
            run_timeout_ms=1_000,
        )
        execution = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(event_store.append_entered.wait(), timeout=1)

        accepted = await coordinator.cancel(run.id, owner_id=run.owner_id)
        event_store.release_append.set()
        result = await asyncio.wait_for(execution, timeout=1)

        self.assertTrue(accepted)
        self.assertEqual(RunStatus.CANCELLED, result.status)
        events = await event_store.list_for_run(run.id, owner_id=run.owner_id)
        self.assertEqual(["run.started", "run.cancelled"], _types(events))

    async def test_concurrent_queued_cancel_is_idempotent(self) -> None:
        run = await self._create_run()
        coordinator = self._coordinator(
            StaticRuntime(RuntimeResult(status=RunStatus.COMPLETED, answer="unused"))
        )

        results = await asyncio.gather(
            coordinator.cancel(run.id, owner_id=run.owner_id),
            coordinator.cancel(run.id, owner_id=run.owner_id),
        )
        stored = await self.run_store.get(run.id, owner_id=run.owner_id)
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertIn(True, results)
        self.assertEqual(RunStatus.CANCELLED, stored.status)
        self.assertEqual(["run.cancelled"], _types(events))

    async def test_cancelled_runtime_cannot_append_a_late_progress_event(self) -> None:
        run = await self._create_run()
        runtime = LateEmitterRuntime()
        coordinator = self._coordinator(runtime)
        execution = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)

        await coordinator.cancel(run.id, owner_id=run.owner_id)
        result = await asyncio.wait_for(execution, timeout=1)
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual(RunStatus.CANCELLED, result.status)
        self.assertEqual(["run.started", "run.cancelled"], _types(events))

    async def test_concurrent_execute_calls_share_one_runtime_invocation(self) -> None:
        run = await self._create_run()
        runtime = GatedRuntime()
        coordinator = self._coordinator(runtime)
        first = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)
        second = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.sleep(0)

        runtime.release.set()
        first_result, second_result = await asyncio.gather(first, second)

        self.assertEqual(1, runtime.calls)
        self.assertEqual(first_result, second_result)
        replay = await coordinator.execute(run.id, owner_id=run.owner_id)
        self.assertEqual(first_result, replay)
        self.assertEqual(1, runtime.calls)

    async def test_two_coordinators_share_the_durable_start_claim(self) -> None:
        run_store = InMemoryRunStore()
        event_store = BarrierStartEventStore(run_store)
        run = _new_run()
        await run_store.create(run)
        runtime = GatedRuntime()
        first_coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={"manual": runtime},
            run_timeout_ms=1_000,
        )
        second_coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={"manual": runtime},
            run_timeout_ms=1_000,
        )

        first = asyncio.create_task(
            first_coordinator.execute(run.id, owner_id=run.owner_id)
        )
        second = asyncio.create_task(
            second_coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)
        runtime.release.set()
        first_result, second_result = await asyncio.gather(first, second)

        self.assertEqual(1, runtime.calls)
        self.assertEqual(RunStatus.COMPLETED, first_result.status)
        self.assertEqual(first_result, second_result)
        events = await event_store.list_for_run(run.id, owner_id=run.owner_id)
        self.assertEqual(["run.started", "run.completed"], _types(events))

    async def test_cancelling_one_waiter_does_not_cancel_shared_execution(self) -> None:
        run = await self._create_run()
        runtime = GatedRuntime()
        coordinator = self._coordinator(runtime)
        first = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)
        second = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.sleep(0)

        first.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first
        runtime.release.set()
        result = await asyncio.wait_for(second, timeout=1)

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual(1, runtime.calls)

    async def test_owner_mismatch_is_indistinguishable_from_missing_run(self) -> None:
        run = await self._create_run()
        coordinator = self._coordinator(
            StaticRuntime(RuntimeResult(status=RunStatus.COMPLETED, answer="done"))
        )

        with self.assertRaises(RunNotFoundError):
            await coordinator.execute(run.id, owner_id="other-owner")

    async def _create_run(self, *, runtime: str = "manual") -> RunRecord:
        run = _new_run(runtime=runtime)
        await self.run_store.create(run)
        return run

    def _coordinator(
        self,
        runtime,
        *,
        notifier: EventNotifier | None = None,
        run_timeout_ms: int = 1_000,
    ) -> RunCoordinator:
        return RunCoordinator(
            run_store=self.run_store,
            event_store=self.event_store,
            runtimes={"manual": runtime},
            notifier=notifier,
            run_timeout_ms=run_timeout_ms,
        )


class PersistentEventEmitterTest(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_event_is_persisted_once_and_notified_once(self) -> None:
        run_store = InMemoryRunStore()
        event_store = InMemoryEventStore(run_store)
        run = _new_run()
        await run_store.create(run)
        await run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )
        notifier = RecordingNotifier()
        ids = iter(("stable-event", "stable-event"))
        emitter = PersistentEventEmitter(
            event_store=event_store,
            run_id=run.id,
            owner_id=run.owner_id,
            notifier=notifier,
            event_id_factory=lambda event, ordinal: next(ids),
        )
        event = RuntimeEvent(type="model.completed", step=1, data={"call": 1})

        first = await emitter.emit(event)
        replay = await emitter.emit(event)

        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(1, len(notifier.events))


class StaticRuntime:
    def __init__(
        self,
        result: RuntimeResult,
        *,
        events: tuple[RuntimeEvent, ...] = (),
    ) -> None:
        self.result = result
        self.events = events
        self.calls = 0

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, control
        self.calls += 1
        for event in self.events:
            await emit(event)
        return self.result


class RaisingRuntime:
    def __init__(self, message: str) -> None:
        self.message = message

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit, control
        raise RuntimeError(self.message)


class SleepingRuntime:
    def __init__(self) -> None:
        self.cancelled = asyncio.Event()

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit, control
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


class CancellationAwareRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit
        self.started.set()
        while not control.cancellation_token.is_cancelled:
            await asyncio.sleep(0)
        return RuntimeResult(status=RunStatus.COMPLETED, answer="too late")


class LateEmitterRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request
        self.started.set()
        while not control.cancellation_token.is_cancelled:
            await asyncio.sleep(0)
        await emit(RuntimeEvent(type="model.completed", step=1, data={}))
        return RuntimeResult(status=RunStatus.COMPLETED, answer="too late")


class GatedRuntime:
    def __init__(self) -> None:
        self.calls = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit, control
        self.calls += 1
        self.started.set()
        await self.release.wait()
        return RuntimeResult(status=RunStatus.COMPLETED, answer="done")


class RecordingNotifier:
    def __init__(self) -> None:
        self.events: list[StoredRunEvent] = []

    async def notify(self, event: StoredRunEvent) -> None:
        self.events.append(event)


class FailingNotifier:
    async def notify(self, event: StoredRunEvent) -> None:
        del event
        raise RuntimeError("subscriber failed")


class SlowStartNotifier:
    async def notify(self, event: StoredRunEvent) -> None:
        if event.type == "run.started":
            await asyncio.sleep(0.03)


class InspectingNotifier:
    def __init__(self, run_store, event_store, run: RunRecord) -> None:
        self.run_store = run_store
        self.event_store = event_store
        self.run = run
        self.observations: list[tuple[str, RunStatus]] = []

    async def notify(self, event: StoredRunEvent) -> None:
        events = await self.event_store.list_for_run(
            self.run.id,
            owner_id=self.run.owner_id,
        )
        current = await self.run_store.get(
            self.run.id,
            owner_id=self.run.owner_id,
        )
        if event not in events or current is None:
            raise AssertionError("notification happened before persistence")
        self.observations.append((event.type, current.status))


class FailingStartEventStore(InMemoryEventStore):
    def _before_start_publish(self) -> None:
        raise StoreUnavailableError()


class FailingProgressEventStore(InMemoryEventStore):
    async def append(self, **kwargs):
        del kwargs
        raise StoreUnavailableError()


class BarrierTerminalEventStore(InMemoryEventStore):
    def __init__(self, run_store) -> None:
        super().__init__(run_store)
        self.completed_entered = asyncio.Event()
        self.release_completed = asyncio.Event()

    async def commit_terminal(self, command):
        if command.target_status is RunStatus.COMPLETED:
            self.completed_entered.set()
            await self.release_completed.wait()
        return await super().commit_terminal(command)


class BarrierProgressEventStore(InMemoryEventStore):
    def __init__(self, run_store) -> None:
        super().__init__(run_store)
        self.append_entered = asyncio.Event()
        self.release_append = asyncio.Event()

    async def append(self, **kwargs):
        if kwargs.get("event_type") == "model.completed":
            self.append_entered.set()
            await self.release_append.wait()
        return await super().append(**kwargs)


class BarrierStartEventStore(InMemoryEventStore):
    def __init__(self, run_store) -> None:
        super().__init__(run_store)
        self._arrivals = 0
        self._release_start = asyncio.Event()

    async def commit_start(self, command):
        self._arrivals += 1
        if self._arrivals >= 2:
            self._release_start.set()
        await self._release_start.wait()
        return await super().commit_start(command)


def _new_run(*, runtime: str = "manual") -> RunRecord:
    return RunRecord.create(
        run_id="run-1",
        session_id="session-1",
        owner_id="owner-1",
        runtime=runtime,
        input_text="hello",
        idempotency_key="idempotency-key",
        created_at=NOW,
    )


def _types(events: tuple[StoredRunEvent, ...]) -> list[str]:
    return [event.type for event in events]


if __name__ == "__main__":
    unittest.main()
