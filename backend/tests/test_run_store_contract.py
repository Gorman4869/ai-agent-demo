from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from backend.app.domain.run import RunFailure, RunRecord, RunStatus
from backend.app.stores import (
    ConcurrentWriteError,
    EventConflictError,
    EventStore,
    IdempotencyConflictError,
    InMemoryEventStore,
    InMemoryRunStore,
    InvalidRunTransitionError,
    RunConflictError,
    RunNotFoundError,
    RunStore,
    StartCommit,
    StartCommitResult,
    StoreUnavailableError,
    TerminalCommit,
    TerminalCommitResult,
)


NOW = datetime(2026, 7, 16, 4, 0, tzinfo=UTC)
STORE_NOW = NOW + timedelta(minutes=1)


class RunStoreContract:
    """Adapter-independent contract; database fixtures subclass this mixin."""

    async def asyncSetUp(self) -> None:
        self.run_store, self.event_store = await self.create_store_pair()

    async def create_store_pair(self) -> tuple[RunStore, EventStore]:
        raise NotImplementedError

    async def test_create_get_and_list_are_owner_isolated(self) -> None:
        run = _new_run()

        created = await self.run_store.create(run)

        self.assertTrue(created.created)
        self.assertEqual(run, created.record)
        self.assertEqual(run, await self.run_store.get(run.id, owner_id="owner-1"))
        self.assertIsNone(await self.run_store.get(run.id, owner_id="owner-2"))
        self.assertEqual(
            (run,),
            await self.run_store.list_for_session(
                run.session_id,
                owner_id="owner-1",
            ),
        )
        self.assertEqual(
            (),
            await self.run_store.list_for_session(
                run.session_id,
                owner_id="owner-2",
            ),
        )

    async def test_same_idempotency_key_and_request_returns_existing_snapshot(self) -> None:
        original = _new_run(run_id="run-original")
        await self.run_store.create(original)
        running = await self.run_store.transition(
            original.id,
            owner_id=original.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )
        replay = _new_run(run_id="run-replay")

        result = await self.run_store.create(replay)

        self.assertFalse(result.created)
        self.assertEqual(running, result.record)
        self.assertEqual("run-original", result.record.id)
        self.assertEqual(1, result.record.version)

    async def test_same_key_with_different_request_conflicts_without_leaking_data(
        self,
    ) -> None:
        secret_input = "secret original input"
        secret_key = "secret-idempotency-key"
        await self.run_store.create(
            _new_run(input_text=secret_input, idempotency_key=secret_key)
        )

        with self.assertRaises(IdempotencyConflictError) as raised:
            await self.run_store.create(
                _new_run(
                    run_id="run-conflict",
                    input_text="different private input",
                    idempotency_key=secret_key,
                )
            )

        message = str(raised.exception)
        self.assertEqual("idempotency_conflict", raised.exception.code)
        self.assertNotIn(secret_input, message)
        self.assertNotIn(secret_key, message)
        self.assertNotIn("different private input", message)

    async def test_same_key_for_different_owner_creates_independent_runs(self) -> None:
        first = await self.run_store.create(
            _new_run(run_id="run-owner-1", owner_id="owner-1")
        )
        second = await self.run_store.create(
            _new_run(run_id="run-owner-2", owner_id="owner-2")
        )

        self.assertTrue(first.created)
        self.assertTrue(second.created)
        self.assertNotEqual(first.record.id, second.record.id)

    async def test_duplicate_run_id_is_a_stable_conflict(self) -> None:
        await self.run_store.create(_new_run())

        with self.assertRaises(RunConflictError) as raised:
            await self.run_store.create(
                _new_run(idempotency_key="another-key", input_text="another input")
            )

        self.assertEqual("run_conflict", raised.exception.code)

    async def test_concurrent_idempotent_create_has_one_winner(self) -> None:
        candidates = [
            _new_run(run_id=f"run-{index}")
            for index in range(20)
        ]

        results = await asyncio.gather(
            *(self.run_store.create(candidate) for candidate in candidates)
        )

        self.assertEqual(1, sum(result.created for result in results))
        self.assertEqual(1, len({result.record.id for result in results}))

    async def test_concurrent_same_key_different_requests_do_not_overwrite(
        self,
    ) -> None:
        candidates = [
            _new_run(
                run_id=f"run-{index}",
                input_text="request-a" if index % 2 == 0 else "request-b",
            )
            for index in range(20)
        ]

        results = await asyncio.gather(
            *(self.run_store.create(candidate) for candidate in candidates),
            return_exceptions=True,
        )
        created = [
            result
            for result in results
            if not isinstance(result, BaseException) and result.created
        ]
        conflicts = [
            result
            for result in results
            if isinstance(result, IdempotencyConflictError)
        ]

        self.assertEqual(1, len(created))
        self.assertEqual(10, len(conflicts))
        stored = await self.run_store.list_for_session(
            "session-1",
            owner_id="owner-1",
        )
        self.assertEqual(1, len(stored))

    async def test_same_key_in_another_session_is_a_request_conflict(self) -> None:
        await self.run_store.create(_new_run())

        with self.assertRaises(IdempotencyConflictError):
            await self.run_store.create(
                _new_run(
                    run_id="run-other-session",
                    session_id="session-2",
                )
            )

    async def test_transition_uses_owner_and_version_compare_and_set(self) -> None:
        run = _new_run()
        await self.run_store.create(run)

        running = await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )

        self.assertEqual(1, running.version)
        with self.assertRaises(ConcurrentWriteError) as stale:
            await self.run_store.transition(
                run.id,
                owner_id=run.owner_id,
                expected_version=0,
                target_status=RunStatus.CANCELLED,
                error_code="cancelled_by_user",
            )
        self.assertEqual("concurrent_write", stale.exception.code)

        with self.assertRaises(RunNotFoundError) as hidden:
            await self.run_store.transition(
                run.id,
                owner_id="other-owner",
                expected_version=1,
                target_status=RunStatus.CANCELLED,
                error_code="cancelled_by_user",
            )
        self.assertEqual("run_not_found", hidden.exception.code)

    async def test_terminal_run_cannot_be_changed(self) -> None:
        run = _new_run()
        await self.run_store.create(run)
        running = await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )
        completed = await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=running.version,
            target_status=RunStatus.COMPLETED,
            answer="done",
        )

        with self.assertRaises(InvalidRunTransitionError) as invalid:
            await self.run_store.transition(
                run.id,
                owner_id=run.owner_id,
                expected_version=completed.version,
                target_status=RunStatus.RUNNING,
            )
        self.assertEqual("invalid_run_transition", invalid.exception.code)

    async def test_completed_and_cancelled_compare_and_set_have_one_winner(
        self,
    ) -> None:
        run = _new_run()
        await self.run_store.create(run)
        running = await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )

        results = await asyncio.gather(
            self.run_store.transition(
                run.id,
                owner_id=run.owner_id,
                expected_version=running.version,
                target_status=RunStatus.COMPLETED,
                answer="done",
            ),
            self.run_store.transition(
                run.id,
                owner_id=run.owner_id,
                expected_version=running.version,
                target_status=RunStatus.CANCELLED,
                error_code="cancelled_by_user",
            ),
            return_exceptions=True,
        )

        self.assertEqual(1, sum(isinstance(result, RunRecord) for result in results))
        self.assertEqual(
            1,
            sum(isinstance(result, ConcurrentWriteError) for result in results),
        )

    async def test_start_commit_writes_running_state_and_event_together(
        self,
    ) -> None:
        run = _new_run()
        await self.run_store.create(run)
        command = StartCommit(
            run_id=run.id,
            owner_id=run.owner_id,
            expected_version=run.version,
            event_id="lifecycle-started",
            event_data={"status": "running", "runtime": "manual"},
        )

        first = await self.event_store.commit_start(command)
        replay = await self.event_store.commit_start(command)
        stored = await self.run_store.get(run.id, owner_id=run.owner_id)
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertIsInstance(first, StartCommitResult)
        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(RunStatus.RUNNING, stored.status)
        self.assertEqual(["run.started"], [event.type for event in events])
        self.assertEqual(first.record, replay.record)
        self.assertEqual(first.event, replay.event)

    async def test_terminal_commit_writes_run_and_matching_event_together(
        self,
    ) -> None:
        run = _new_run()
        await self.run_store.create(run)
        running = await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )

        result = await self.event_store.commit_terminal(
            TerminalCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=running.version,
                target_status=RunStatus.COMPLETED,
                event_id="terminal-completed",
                event_data={"status": "completed"},
                answer="done",
            )
        )
        stored_run = await self.run_store.get(run.id, owner_id=run.owner_id)
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertIsInstance(result, TerminalCommitResult)
        self.assertTrue(result.created)
        self.assertEqual(RunStatus.COMPLETED, stored_run.status)
        self.assertEqual("done", stored_run.answer)
        self.assertEqual(["run.completed"], [event.type for event in events])
        self.assertEqual(result.record, stored_run)
        self.assertEqual(result.event, events[-1])

    async def test_terminal_commit_exact_replay_is_idempotent(self) -> None:
        run = _new_run()
        await self.run_store.create(run)
        running = await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )
        command = TerminalCommit(
            run_id=run.id,
            owner_id=run.owner_id,
            expected_version=running.version,
            target_status=RunStatus.FAILED,
            event_id="terminal-failed",
            event_data={"status": "failed", "failure_code": "runtime_failed"},
            failure=RunFailure(
                code="runtime_failed",
                category="runtime",
                public_message="Runtime failed",
            ),
        )

        first = await self.event_store.commit_terminal(command)
        replay = await self.event_store.commit_terminal(command)
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertTrue(first.created)
        self.assertFalse(replay.created)
        self.assertEqual(first.record, replay.record)
        self.assertEqual(first.event, replay.event)
        self.assertEqual(1, len(events))

    async def test_concurrent_exact_terminal_replay_creates_one_event(self) -> None:
        run = _new_run()
        await self.run_store.create(run)
        running = await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )
        command = TerminalCommit(
            run_id=run.id,
            owner_id=run.owner_id,
            expected_version=running.version,
            target_status=RunStatus.COMPLETED,
            event_id="terminal-concurrent-replay",
            event_data={"status": "completed"},
            answer="done",
        )

        first, second = await asyncio.gather(
            self.event_store.commit_terminal(command),
            self.event_store.commit_terminal(command),
        )
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual([False, True], sorted([first.created, second.created]))
        self.assertEqual(first.record, second.record)
        self.assertEqual(first.event, second.event)
        self.assertEqual(1, len(events))

    async def test_terminal_event_id_reuse_with_changed_outcome_conflicts(
        self,
    ) -> None:
        run = _new_run()
        await self.run_store.create(run)
        running = await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )
        original = TerminalCommit(
            run_id=run.id,
            owner_id=run.owner_id,
            expected_version=running.version,
            target_status=RunStatus.COMPLETED,
            event_id="terminal-stable",
            event_data={"status": "completed"},
            answer="first",
        )
        await self.event_store.commit_terminal(original)

        for changed in (
            TerminalCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=running.version,
                target_status=RunStatus.COMPLETED,
                event_id="terminal-stable",
                event_data={"status": "completed", "changed": True},
                answer="first",
            ),
            TerminalCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=running.version,
                target_status=RunStatus.COMPLETED,
                event_id="terminal-stable",
                event_data={"status": "completed"},
                answer="second",
            ),
        ):
            with self.subTest(answer=changed.answer, data=changed.event_data):
                with self.assertRaises(EventConflictError):
                    await self.event_store.commit_terminal(changed)

    async def test_competing_terminal_commits_leave_only_the_winner_event(
        self,
    ) -> None:
        run = _new_run()
        await self.run_store.create(run)
        running = await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )
        results = await asyncio.gather(
            self.event_store.commit_terminal(
                TerminalCommit(
                    run_id=run.id,
                    owner_id=run.owner_id,
                    expected_version=running.version,
                    target_status=RunStatus.COMPLETED,
                    event_id="terminal-completed",
                    event_data={"status": "completed"},
                    answer="done",
                )
            ),
            self.event_store.commit_terminal(
                TerminalCommit(
                    run_id=run.id,
                    owner_id=run.owner_id,
                    expected_version=running.version,
                    target_status=RunStatus.CANCELLED,
                    event_id="terminal-cancelled",
                    event_data={"status": "cancelled"},
                    failure=RunFailure(
                        code="cancelled_by_user",
                        category="cancellation",
                        public_message="Run cancelled",
                    ),
                )
            ),
            return_exceptions=True,
        )
        stored = await self.run_store.get(run.id, owner_id=run.owner_id)
        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual(
            1,
            sum(isinstance(result, TerminalCommitResult) for result in results),
        )
        self.assertEqual(
            1,
            sum(isinstance(result, ConcurrentWriteError) for result in results),
        )
        self.assertEqual(1, len(events))
        self.assertEqual(f"run.{stored.status.value}", events[0].type)

    async def test_concurrent_append_assigns_unique_increasing_sequences(
        self,
    ) -> None:
        run = _new_run()
        await self.run_store.create(run)

        results = await asyncio.gather(
            *(
                self.event_store.append(
                    event_id=f"event-{index}",
                    run_id=run.id,
                    owner_id=run.owner_id,
                    event_type="model.delta",
                    data={"index": index},
                )
                for index in range(50)
            )
        )
        stored = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        returned_sequences = sorted(result.event.sequence for result in results)
        stored_sequences = [event.sequence for event in stored]
        self.assertEqual(50, len(set(returned_sequences)))
        self.assertTrue(
            all(
                previous < current
                for previous, current in zip(
                    returned_sequences,
                    returned_sequences[1:],
                )
            )
        )
        self.assertEqual(returned_sequences, stored_sequences)
        self.assertTrue(all(result.created for result in results))

    async def test_event_sequence_is_scoped_to_each_run(self) -> None:
        first_run = _new_run(run_id="run-1", idempotency_key="key-1")
        second_run = _new_run(run_id="run-2", idempotency_key="key-2")
        await self.run_store.create(first_run)
        await self.run_store.create(second_run)

        first = await self.event_store.append(
            event_id="event-1",
            run_id=first_run.id,
            owner_id=first_run.owner_id,
            event_type="model.started",
            data={},
        )
        second = await self.event_store.append(
            event_id="event-1",
            run_id=second_run.id,
            owner_id=second_run.owner_id,
            event_type="model.started",
            data={},
        )

        self.assertEqual(1, first.event.sequence)
        self.assertEqual(1, second.event.sequence)

    async def test_event_id_replay_is_idempotent_but_changed_payload_conflicts(
        self,
    ) -> None:
        run = _new_run()
        await self.run_store.create(run)
        first = await self.event_store.append(
            event_id="event-1",
            run_id=run.id,
            owner_id=run.owner_id,
            event_type="model.started",
            data={"attempt": 1},
        )

        replay = await self.event_store.append(
            event_id="event-1",
            run_id=run.id,
            owner_id=run.owner_id,
            event_type="model.started",
            data={"attempt": 1},
        )

        self.assertFalse(replay.created)
        self.assertEqual(first.event, replay.event)
        with self.assertRaises(EventConflictError) as raised:
            await self.event_store.append(
                event_id="event-1",
                run_id=run.id,
                owner_id=run.owner_id,
                event_type="model.started",
                data={"attempt": 2},
            )
        self.assertEqual("event_conflict", raised.exception.code)

    async def test_concurrent_same_event_id_creates_one_event(self) -> None:
        run = _new_run()
        await self.run_store.create(run)

        results = await asyncio.gather(
            *(
                self.event_store.append(
                    event_id="event-stable",
                    run_id=run.id,
                    owner_id=run.owner_id,
                    event_type="model.started",
                    data={"attempt": 1},
                )
                for _ in range(20)
            )
        )
        stored = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual(1, sum(result.created for result in results))
        self.assertEqual({1}, {result.event.sequence for result in results})
        self.assertEqual(1, len(stored))

    async def test_terminal_run_rejects_new_events_but_allows_commit_replay(
        self,
    ) -> None:
        run = _new_run()
        await self.run_store.create(run)
        running = await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )
        command = TerminalCommit(
            run_id=run.id,
            owner_id=run.owner_id,
            expected_version=running.version,
            target_status=RunStatus.COMPLETED,
            event_id="event-final",
            event_data={"status": "completed"},
            answer="done",
        )
        final_event = await self.event_store.commit_terminal(command)

        replay = await self.event_store.commit_terminal(command)
        self.assertFalse(replay.created)
        self.assertEqual(final_event.event, replay.event)

        with self.assertRaises(InvalidRunTransitionError):
            await self.event_store.append(
                event_id="event-too-late",
                run_id=run.id,
                owner_id=run.owner_id,
                event_type="model.delta",
                data={"text": "late"},
            )

    async def test_ordinary_append_rejects_owned_lifecycle_events(self) -> None:
        run = _new_run()
        await self.run_store.create(run)

        for event_type in (
            "run.started",
            "run.completed",
            "run.failed",
            "run.cancelled",
        ):
            with self.subTest(event_type=event_type):
                with self.assertRaises(ValueError):
                    await self.event_store.append(
                        event_id=f"ordinary-{event_type}",
                        run_id=run.id,
                        owner_id=run.owner_id,
                        event_type=event_type,
                        data={},
                    )

    async def test_event_append_and_read_hide_unknown_or_other_owner_runs(self) -> None:
        run = _new_run()
        await self.run_store.create(run)

        for run_id, owner_id in (
            (run.id, "other-owner"),
            ("missing-run", run.owner_id),
        ):
            with self.subTest(run_id=run_id, owner_id=owner_id):
                with self.assertRaises(RunNotFoundError):
                    await self.event_store.append(
                        event_id="hidden-event",
                        run_id=run_id,
                        owner_id=owner_id,
                        event_type="model.started",
                        data={},
                    )
                self.assertEqual(
                    (),
                    await self.event_store.list_for_run(
                        run_id,
                        owner_id=owner_id,
                    ),
                )

    async def test_event_pagination_uses_sequence_not_time(self) -> None:
        run = _new_run()
        await self.run_store.create(run)
        for index in range(5):
            await self.event_store.append(
                event_id=f"event-{index}",
                run_id=run.id,
                owner_id=run.owner_id,
                event_type="model.delta",
                data={"index": index},
            )

        events = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
            after_sequence=2,
            limit=2,
        )

        self.assertEqual([3, 4], [event.sequence for event in events])
        with self.assertRaises(ValueError):
            await self.event_store.list_for_run(
                run.id,
                owner_id=run.owner_id,
                after_sequence=-1,
            )
        with self.assertRaises(ValueError):
            await self.event_store.list_for_run(
                run.id,
                owner_id=run.owner_id,
                limit=0,
            )

    async def test_event_payload_is_a_store_owned_snapshot(self) -> None:
        run = _new_run()
        await self.run_store.create(run)
        payload = {"nested": {"value": 1}}

        created = await self.event_store.append(
            event_id="event-1",
            run_id=run.id,
            owner_id=run.owner_id,
            event_type="model.started",
            data=payload,
        )
        payload["nested"]["value"] = 2
        created.event.data["nested"]["value"] = 3
        stored = await self.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual(1, stored[0].data["nested"]["value"])

    async def test_event_payload_must_be_bounded_json(self) -> None:
        run = _new_run()
        await self.run_store.create(run)

        for payload in (
            {"value": float("nan")},
            {"value": object()},
            {"value": "x" * 65_000},
        ):
            with self.subTest(payload_type=type(payload["value"]).__name__):
                with self.assertRaises(ValueError):
                    await self.event_store.append(
                        event_id="event-invalid",
                        run_id=run.id,
                        owner_id=run.owner_id,
                        event_type="model.started",
                        data=payload,
                    )

        with self.assertRaises(ValueError):
            await self.event_store.append(
                event_id="transport-heartbeat",
                run_id=run.id,
                owner_id=run.owner_id,
                event_type="run.heartbeat",
                data={},
            )


class InMemoryRunStoreContractTest(
    RunStoreContract,
    unittest.IsolatedAsyncioTestCase,
):
    async def create_store_pair(self) -> tuple[RunStore, EventStore]:
        run_store = InMemoryRunStore(clock=lambda: STORE_NOW)
        return run_store, InMemoryEventStore(
            run_store,
            clock=lambda: STORE_NOW,
        )

    async def test_memory_append_has_no_gap_when_all_fifty_writes_commit(
        self,
    ) -> None:
        run = _new_run()
        await self.run_store.create(run)

        results = await asyncio.gather(
            *(
                self.event_store.append(
                    event_id=f"memory-event-{index}",
                    run_id=run.id,
                    owner_id=run.owner_id,
                    event_type="model.delta",
                    data={"index": index},
                )
                for index in range(50)
            )
        )

        self.assertEqual(
            list(range(1, 51)),
            sorted(result.event.sequence for result in results),
        )

    async def test_memory_terminal_fault_before_publish_changes_neither_store(
        self,
    ) -> None:
        class FaultingEventStore(InMemoryEventStore):
            def _before_terminal_publish(self) -> None:
                raise StoreUnavailableError()

        run_store = InMemoryRunStore(clock=lambda: STORE_NOW)
        event_store = FaultingEventStore(run_store, clock=lambda: STORE_NOW)
        run = _new_run()
        await run_store.create(run)
        running = await run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=0,
            target_status=RunStatus.RUNNING,
        )

        with self.assertRaises(StoreUnavailableError):
            await event_store.commit_terminal(
                TerminalCommit(
                    run_id=run.id,
                    owner_id=run.owner_id,
                    expected_version=running.version,
                    target_status=RunStatus.COMPLETED,
                    event_id="terminal-completed",
                    event_data={"status": "completed"},
                    answer="done",
                )
            )

        self.assertEqual(
            RunStatus.RUNNING,
            (await run_store.get(run.id, owner_id=run.owner_id)).status,
        )
        self.assertEqual(
            (),
            await event_store.list_for_run(run.id, owner_id=run.owner_id),
        )

    async def test_memory_start_fault_before_publish_changes_neither_store(
        self,
    ) -> None:
        class FaultingEventStore(InMemoryEventStore):
            def _before_start_publish(self) -> None:
                raise StoreUnavailableError()

        run_store = InMemoryRunStore(clock=lambda: STORE_NOW)
        event_store = FaultingEventStore(run_store, clock=lambda: STORE_NOW)
        run = _new_run()
        await run_store.create(run)

        with self.assertRaises(StoreUnavailableError):
            await event_store.commit_start(
                StartCommit(
                    run_id=run.id,
                    owner_id=run.owner_id,
                    expected_version=run.version,
                    event_id="lifecycle-started",
                    event_data={"status": "running"},
                )
            )

        self.assertEqual(
            RunStatus.QUEUED,
            (await run_store.get(run.id, owner_id=run.owner_id)).status,
        )
        self.assertEqual(
            (),
            await event_store.list_for_run(run.id, owner_id=run.owner_id),
        )


def _new_run(
    *,
    run_id: str = "run-1",
    session_id: str = "session-1",
    owner_id: str = "owner-1",
    runtime: str = "manual",
    input_text: str = "hello",
    idempotency_key: str = "key-1",
) -> RunRecord:
    return RunRecord.create(
        run_id=run_id,
        session_id=session_id,
        owner_id=owner_id,
        runtime=runtime,
        input_text=input_text,
        idempotency_key=idempotency_key,
        created_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
