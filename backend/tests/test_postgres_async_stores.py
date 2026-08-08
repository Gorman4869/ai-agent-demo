from __future__ import annotations

import asyncio
import threading
import unittest
from unittest.mock import patch

from backend.app.domain import Message
from backend.app.stores.postgres import PostgresPersistence
from backend.app.stores.postgres_async import (
    AsyncPostgresApprovalStore,
    AsyncPostgresMemoryStore,
    PostgresSyncStoreBridge,
    PostgresSyncStoreBridgeState,
    PostgresSyncStoreLifecycleError,
    PostgresSyncStoreTimeoutError,
)


class _BlockingMemoryStore:
    def __init__(self) -> None:
        self.entered = threading.Event()
        self.release = threading.Event()
        self.message_calls = 0
        self.append_calls = 0

    def messages(self, session_id: str) -> tuple[Message, ...]:
        del session_id
        self.message_calls += 1
        self.entered.set()
        self.release.wait()
        return (Message(role="assistant", content="fixture"),)

    def append_message(self, session_id: str, message: Message) -> None:
        del session_id, message
        self.append_calls += 1
        self.entered.set()
        self.release.wait()


class _RecordingApprovalStore:
    def __init__(self) -> None:
        self.request_calls = 0
        self.arguments = None

    def request(self, **kwargs):
        self.request_calls += 1
        self.arguments = kwargs["arguments"]
        return "approval-request"


class _FakeAsyncPool:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def close(self) -> None:
        self.events.append("async_pool.close")


class _FakeSyncPool:
    max_size = 1

    def __init__(self, events: list[str]) -> None:
        self.events = events

    def close(self) -> None:
        self.events.append("sync_pool.close")


class _OpeningAsyncPool(_FakeAsyncPool):
    async def open(self, *, wait: bool, timeout: float) -> None:
        del wait, timeout
        self.events.append("async_pool.open")


class _OpeningSyncPool(_FakeSyncPool):
    def __init__(self, events: list[str]) -> None:
        super().__init__(events)
        self.entered = threading.Event()
        self.release = threading.Event()

    def open(self, *, wait: bool, timeout: float) -> None:
        del wait, timeout
        self.events.append("sync_pool.open.started")
        self.entered.set()
        self.release.wait()
        self.events.append("sync_pool.open.finished")


class _FailingSyncPool(_FakeSyncPool):
    def close(self) -> None:
        super().close()
        raise RuntimeError("sync-pool-close-failed")


class PostgresSyncStoreBridgeTest(unittest.IsolatedAsyncioTestCase):
    async def test_configuration_requires_positive_integers(self) -> None:
        for kwargs in (
            {"max_workers": 0, "operation_timeout_ms": 10},
            {"max_workers": True, "operation_timeout_ms": 10},
            {"max_workers": 1, "operation_timeout_ms": 0},
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):
                    PostgresSyncStoreBridge(**kwargs)

    async def test_blocking_store_does_not_block_the_event_loop(self) -> None:
        store = _BlockingMemoryStore()
        bridge = self._bridge(timeout_ms=1_000)
        facade = AsyncPostgresMemoryStore(store, bridge)
        task = asyncio.create_task(facade.messages("session-1"))
        try:
            await _wait_thread_event(store.entered)
            pulse = asyncio.Event()
            asyncio.get_running_loop().call_soon(pulse.set)

            await asyncio.wait_for(pulse.wait(), timeout=0.1)
            self.assertFalse(task.done())
        finally:
            store.release.set()
            await task
            await bridge.close()

    async def test_queued_timeout_cancels_write_before_it_starts(self) -> None:
        memory = _BlockingMemoryStore()
        approval = _RecordingApprovalStore()
        bridge = self._bridge(timeout_ms=40)
        memory_facade = AsyncPostgresMemoryStore(memory, bridge)
        approval_facade = AsyncPostgresApprovalStore(approval, bridge)
        blocker = asyncio.create_task(memory_facade.messages("session-1"))
        try:
            await _wait_thread_event(memory.entered)
            with self.assertRaises(PostgresSyncStoreTimeoutError) as raised:
                await approval_facade.request(
                    run_id="run-1",
                    principal_id="owner-1",
                    tool_call_id="call-1",
                    tool_name="publish_report",
                    arguments={"document_id": "document-1"},
                )

            self.assertFalse(raised.exception.result_unknown)
            self.assertEqual(0, approval.request_calls)
        finally:
            memory.release.set()
            with self.assertRaises(PostgresSyncStoreTimeoutError) as blocker_error:
                await blocker
            self.assertTrue(blocker_error.exception.result_unknown)
            await bridge.close()
        self.assertEqual(0, approval.request_calls)

    async def test_running_timeout_is_result_unknown_and_not_retried(self) -> None:
        memory = _BlockingMemoryStore()
        bridge = self._bridge(timeout_ms=40)
        facade = AsyncPostgresMemoryStore(memory, bridge)
        task = asyncio.create_task(
            facade.append_message(
                "session-1",
                Message(role="user", content="fixture"),
            )
        )
        try:
            await _wait_thread_event(memory.entered)
            with self.assertRaises(PostgresSyncStoreTimeoutError) as raised:
                await task

            self.assertTrue(raised.exception.result_unknown)
            self.assertEqual(1, memory.append_calls)
        finally:
            memory.release.set()
            await bridge.close()
        self.assertEqual(1, memory.append_calls)

    async def test_caller_cancellation_keeps_running_worker_owned_until_close(
        self,
    ) -> None:
        memory = _BlockingMemoryStore()
        bridge = self._bridge(timeout_ms=1_000)
        facade = AsyncPostgresMemoryStore(memory, bridge)
        operation = asyncio.create_task(facade.messages("session-1"))
        await _wait_thread_event(memory.entered)

        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation
        closing = asyncio.create_task(bridge.close())
        await _wait_bridge_state(
            bridge,
            PostgresSyncStoreBridgeState.QUIESCING,
        )

        with self.assertRaises(PostgresSyncStoreLifecycleError):
            await facade.messages("session-2")
        self.assertFalse(closing.done())
        memory.release.set()
        await asyncio.wait_for(closing, timeout=1)
        self.assertEqual(PostgresSyncStoreBridgeState.QUIESCED, bridge.state)
        self.assertEqual(1, memory.message_calls)
        await bridge.close()

    async def test_arguments_are_detached_before_a_queued_worker_runs(self) -> None:
        memory = _BlockingMemoryStore()
        approval = _RecordingApprovalStore()
        bridge = self._bridge(timeout_ms=1_000)
        memory_facade = AsyncPostgresMemoryStore(memory, bridge)
        approval_facade = AsyncPostgresApprovalStore(approval, bridge)
        blocker = asyncio.create_task(memory_facade.messages("session-1"))
        await _wait_thread_event(memory.entered)
        arguments = {"options": {"publish": True}}
        request = asyncio.create_task(
            approval_facade.request(
                run_id="run-1",
                principal_id="owner-1",
                tool_call_id="call-1",
                tool_name="publish_report",
                arguments=arguments,
            )
        )
        await asyncio.sleep(0)
        arguments["options"]["publish"] = False
        memory.release.set()
        try:
            self.assertEqual("approval-request", await request)
            self.assertEqual({"options": {"publish": True}}, approval.arguments)
        finally:
            await blocker
            await bridge.close()

    def _bridge(self, *, timeout_ms: int) -> PostgresSyncStoreBridge:
        return PostgresSyncStoreBridge(
            max_workers=1,
            operation_timeout_ms=timeout_ms,
        )


class PostgresPersistenceSyncLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_cancelled_open_waits_for_sync_worker_before_cleanup(self) -> None:
        events: list[str] = []
        async_pool = _OpeningAsyncPool(events)
        sync_pool = _OpeningSyncPool(events)
        with (
            patch(
                "backend.app.stores.postgres.AsyncConnectionPool",
                return_value=async_pool,
            ),
            patch(
                "backend.app.stores.postgres.ConnectionPool",
                return_value=sync_pool,
            ),
        ):
            opening = asyncio.create_task(
                PostgresPersistence.open("postgresql://private-connection")
            )
            await _wait_thread_event(sync_pool.entered)
            opening.cancel()
            await asyncio.sleep(0)
            self.assertFalse(opening.done())
            self.assertEqual(
                ["async_pool.open", "sync_pool.open.started"],
                events,
            )

            sync_pool.release.set()
            with self.assertRaises(asyncio.CancelledError):
                await asyncio.wait_for(opening, timeout=1)

        self.assertEqual(
            [
                "async_pool.open",
                "sync_pool.open.started",
                "sync_pool.open.finished",
                "sync_pool.close",
                "async_pool.close",
            ],
            events,
        )

    async def test_sync_pool_close_failure_still_closes_async_pool(self) -> None:
        events: list[str] = []
        async_pool = _FakeAsyncPool(events)
        sync_pool = _FailingSyncPool(events)
        with patch(
            "backend.app.stores.postgres.AsyncPostgresSaver",
            return_value=object(),
        ):
            persistence = PostgresPersistence(
                async_pool,
                sync_pool,
                sync_store_workers=1,
            )

        with self.assertRaisesRegex(RuntimeError, "sync-pool-close-failed"):
            await persistence.close()

        self.assertEqual(
            ["sync_pool.close", "async_pool.close"],
            events,
        )

    async def test_close_waits_for_sync_worker_before_closing_both_pools(
        self,
    ) -> None:
        events: list[str] = []
        async_pool = _FakeAsyncPool(events)
        sync_pool = _FakeSyncPool(events)
        with patch(
            "backend.app.stores.postgres.AsyncPostgresSaver",
            return_value=object(),
        ):
            persistence = PostgresPersistence(
                async_pool,
                sync_pool,
                sync_store_workers=1,
                sync_operation_timeout_ms=1_000,
            )
        blocking = _BlockingMemoryStore()
        persistence.async_memory_store = AsyncPostgresMemoryStore(
            blocking,
            persistence.sync_store_bridge,
        )
        operation = asyncio.create_task(
            persistence.async_memory_store.messages("session-1")
        )
        await _wait_thread_event(blocking.entered)

        closing = asyncio.create_task(persistence.close())
        await _wait_bridge_state(
            persistence.sync_store_bridge,
            PostgresSyncStoreBridgeState.QUIESCING,
        )
        self.assertEqual([], events)
        self.assertFalse(closing.done())

        blocking.release.set()
        self.assertEqual(
            (Message(role="assistant", content="fixture"),),
            await operation,
        )
        await asyncio.wait_for(closing, timeout=1)
        self.assertEqual(
            ["sync_pool.close", "async_pool.close"],
            events,
        )


async def _wait_thread_event(event: threading.Event) -> None:
    reached = await asyncio.wait_for(asyncio.to_thread(event.wait, 1), timeout=1.1)
    if not reached:
        raise AssertionError("worker did not reach the expected boundary")


async def _wait_bridge_state(
    bridge: PostgresSyncStoreBridge,
    expected: PostgresSyncStoreBridgeState,
) -> None:
    for _ in range(100):
        if bridge.state is expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"bridge did not enter {expected.value}")


if __name__ == "__main__":
    unittest.main()
