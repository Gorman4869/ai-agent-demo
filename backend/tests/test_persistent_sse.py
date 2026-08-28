from __future__ import annotations

import asyncio
import json
import unittest
from datetime import UTC, datetime
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend.app.agent import RuntimeEvent, RuntimeResult
from backend.app.container import ApplicationContainer
from backend.app.domain.run import RunRecord, RunStatus
from backend.app.main import _durable_event_stream, create_app
from backend.app.security import Principal, StaticTokenAuthenticator
from backend.app.settings import Settings
from backend.app.stores import StartCommit, TerminalCommit


class DurableEventStreamTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.container = ApplicationContainer.create(
            settings=Settings.from_environment({})
        )

    async def test_replays_ordered_history_after_cursor_then_closes_terminal(self) -> None:
        run = await self._seed_terminal_run()

        chunks = [
            chunk
            async for chunk in _durable_event_stream(
                self.container,
                run_id=run.id,
                owner_id=run.owner_id,
                after_sequence=1,
            )
        ]

        self.assertEqual(2, len(chunks))
        self.assertTrue(chunks[0].startswith("id: 2\nevent: tool.completed\n"))
        self.assertTrue(chunks[1].startswith("id: 3\nevent: run.completed\n"))
        payload = _sse_data(chunks[1])
        self.assertEqual(run.id, payload["run_id"])
        self.assertEqual(3, payload["sequence"])
        self.assertEqual("done", payload["data"]["answer"])

    async def test_live_committed_event_wakes_stream_reader(self) -> None:
        run = await self._create_run()
        stream = _durable_event_stream(
            self.container,
            run_id=run.id,
            owner_id=run.owner_id,
            after_sequence=0,
        )
        next_chunk = asyncio.create_task(anext(stream))
        await asyncio.sleep(0)

        started = await self.container.event_store.commit_start(
            StartCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=0,
                event_id="sse-started",
                event_data={"status": "running", "runtime": "manual"},
            )
        )
        await self.container.event_notifier.notify(started.event)

        chunk = await asyncio.wait_for(next_chunk, timeout=0.2)
        self.assertTrue(chunk.startswith("id: 1\nevent: run.started\n"))
        self.assertEqual("running", _sse_data(chunk)["data"]["status"])
        await stream.aclose()

    async def test_coordinator_execution_is_observable_before_terminal_close(self) -> None:
        runtime = GateRuntime()
        container = ApplicationContainer.create(
            settings=Settings.from_environment({}),
            runtimes={"manual": runtime},
        )
        run = RunRecord.create(
            run_id="durable-sse-coordinator-run",
            session_id="durable-sse-coordinator-session",
            owner_id="durable-sse-owner",
            runtime="manual",
            input_text="hello",
            idempotency_key="durable-sse-coordinator-key",
            created_at=datetime.now(UTC),
        )
        await container.run_store.create(run)
        stream = _durable_event_stream(
            container,
            run_id=run.id,
            owner_id=run.owner_id,
            after_sequence=0,
        )
        execution = asyncio.create_task(
            container.run_coordinator.execute(run.id, owner_id=run.owner_id)
        )

        first = await asyncio.wait_for(anext(stream), timeout=0.2)
        second = await asyncio.wait_for(anext(stream), timeout=0.2)
        self.assertIn("event: run.started", first)
        self.assertIn("event: model.output.delta", second)
        self.assertFalse(execution.done())

        runtime.release.set()
        completed = await asyncio.wait_for(execution, timeout=0.2)
        terminal = await asyncio.wait_for(anext(stream), timeout=0.2)
        self.assertEqual(RunStatus.COMPLETED, completed.status)
        self.assertIn("event: run.completed", terminal)
        with self.assertRaises(StopAsyncIteration):
            await anext(stream)

    async def test_slow_stream_reader_does_not_block_coordinator(self) -> None:
        runtime = GateRuntime()
        container = ApplicationContainer.create(
            settings=Settings.from_environment({}),
            runtimes={"manual": runtime},
        )
        run = RunRecord.create(
            run_id="durable-sse-slow-reader-run",
            session_id="durable-sse-slow-reader-session",
            owner_id="durable-sse-owner",
            runtime="manual",
            input_text="hello",
            idempotency_key="durable-sse-slow-reader-key",
            created_at=datetime.now(UTC),
        )
        await container.run_store.create(run)
        stream = _durable_event_stream(
            container,
            run_id=run.id,
            owner_id=run.owner_id,
            after_sequence=0,
        )
        execution = asyncio.create_task(
            container.run_coordinator.execute(run.id, owner_id=run.owner_id)
        )

        first = await asyncio.wait_for(anext(stream), timeout=0.2)
        self.assertIn("event: run.started", first)
        runtime.release.set()
        completed = await asyncio.wait_for(execution, timeout=0.2)
        await stream.aclose()

        self.assertEqual(RunStatus.COMPLETED, completed.status)

    async def test_heartbeat_does_not_consume_business_sequence(self) -> None:
        run = await self._create_run()
        with (
            patch("backend.app.main._DURABLE_SSE_HEARTBEAT_SECONDS", 0.01),
            patch("backend.app.main._DURABLE_SSE_STORE_RECHECK_SECONDS", 0.005),
        ):
            stream = _durable_event_stream(
                self.container,
                run_id=run.id,
                owner_id=run.owner_id,
                after_sequence=0,
            )
            heartbeat = await asyncio.wait_for(anext(stream), timeout=0.2)
            await stream.aclose()

        self.assertEqual(": heartbeat\n\n", heartbeat)
        events = await self.container.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )
        self.assertEqual((), events)

    async def test_disconnecting_stream_does_not_cancel_or_mutate_run(self) -> None:
        run = await self._create_run()
        with (
            patch("backend.app.main._DURABLE_SSE_HEARTBEAT_SECONDS", 0.01),
            patch("backend.app.main._DURABLE_SSE_STORE_RECHECK_SECONDS", 0.005),
        ):
            stream = _durable_event_stream(
                self.container,
                run_id=run.id,
                owner_id=run.owner_id,
                after_sequence=0,
            )
            await anext(stream)
            await stream.aclose()

        current = await self.container.run_store.get(run.id, owner_id=run.owner_id)
        events = await self.container.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )
        self.assertIsNotNone(current)
        self.assertEqual(RunStatus.QUEUED, current.status)
        self.assertEqual((), events)

    async def _create_run(self) -> RunRecord:
        run = RunRecord.create(
            run_id="durable-sse-run",
            session_id="durable-sse-session",
            owner_id="durable-sse-owner",
            runtime="manual",
            input_text="hello",
            idempotency_key="durable-sse-key",
            created_at=datetime.now(UTC),
        )
        await self.container.run_store.create(run)
        return run

    async def _seed_terminal_run(self) -> RunRecord:
        run = await self._create_run()
        started = await self.container.event_store.commit_start(
            StartCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=0,
                event_id="sse-started",
                event_data={"status": "running", "runtime": "manual"},
            )
        )
        await self.container.event_store.append(
            event_id="sse-tool-completed",
            run_id=run.id,
            owner_id=run.owner_id,
            event_type="tool.completed",
            data={"tool_name": "convert_temperature"},
            step=1,
        )
        await self.container.event_store.commit_terminal(
            TerminalCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=started.record.version,
                target_status=RunStatus.COMPLETED,
                event_id="sse-completed",
                event_data={"status": "completed", "answer": "done"},
                answer="done",
            )
        )
        return run


class DurableEventStreamApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.owner = Principal("sse-user-one")
        self.container = ApplicationContainer.create(
            settings=Settings.from_environment({}),
            authenticator=StaticTokenAuthenticator(
                {
                    "sse-user-one-token": self.owner,
                    "sse-user-two-token": Principal("sse-user-two"),
                }
            ),
        )
        self.client = TestClient(create_app(container=self.container))
        self.run = asyncio.run(self._seed_terminal_run())

    def test_api_reconnect_replays_only_events_after_cursor(self) -> None:
        response = self.client.get(
            f"/api/durable/runs/{self.run.id}/events?after=1",
            headers={"Authorization": "Bearer sse-user-one-token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertTrue(response.headers["content-type"].startswith("text/event-stream"))
        self.assertNotIn("id: 1", response.text)
        self.assertIn("id: 2\nevent: tool.completed", response.text)
        self.assertIn("id: 3\nevent: run.completed", response.text)

    def test_api_hides_non_owned_run_and_rejects_invalid_cursor(self) -> None:
        other_owner = self.client.get(
            f"/api/durable/runs/{self.run.id}/events",
            headers={"Authorization": "Bearer sse-user-two-token"},
        )
        invalid_cursor = self.client.get(
            f"/api/durable/runs/{self.run.id}/events?after=-1",
            headers={"Authorization": "Bearer sse-user-one-token"},
        )

        self.assertEqual(404, other_owner.status_code)
        self.assertEqual(422, invalid_cursor.status_code)

    async def _seed_terminal_run(self) -> RunRecord:
        run = RunRecord.create(
            run_id="durable-sse-api-run",
            session_id="durable-sse-api-session",
            owner_id=self.owner.principal_id,
            runtime="manual",
            input_text="hello",
            idempotency_key="durable-sse-api-key",
            created_at=datetime.now(UTC),
        )
        await self.container.run_store.create(run)
        started = await self.container.event_store.commit_start(
            StartCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=0,
                event_id="api-sse-started",
                event_data={"status": "running", "runtime": "manual"},
            )
        )
        await self.container.event_store.append(
            event_id="api-sse-tool-completed",
            run_id=run.id,
            owner_id=run.owner_id,
            event_type="tool.completed",
            data={"tool_name": "convert_temperature"},
            step=1,
        )
        await self.container.event_store.commit_terminal(
            TerminalCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=started.record.version,
                target_status=RunStatus.COMPLETED,
                event_id="api-sse-completed",
                event_data={"status": "completed", "answer": "done"},
                answer="done",
            )
        )
        return run


def _sse_data(chunk: str) -> dict[str, object]:
    line = next(line for line in chunk.splitlines() if line.startswith("data: "))
    return json.loads(line.removeprefix("data: "))


class GateRuntime:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, control
        await emit(
            RuntimeEvent(
                type="model.output.delta",
                step=1,
                data={"text": "partial"},
            )
        )
        await self.release.wait()
        return RuntimeResult(status=RunStatus.COMPLETED, answer="done", step=1)
