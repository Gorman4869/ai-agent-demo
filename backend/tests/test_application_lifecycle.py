from __future__ import annotations

import asyncio
import unittest
from unittest.mock import AsyncMock

from backend.app.application_lifecycle import (
    ApplicationAdmission,
    ApplicationAdmissionState,
    ApplicationLifecycle,
    ApplicationLifecycleState,
    ApplicationNotAcceptingError,
    ApplicationRunCommands,
)
from backend.app.integrations.mcp import McpClientState


class _RecordingMcpClients:
    def __init__(
        self,
        events: list[str],
        *,
        start_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.start_error = start_error
        self.state = McpClientState.CREATED

    async def start(self) -> None:
        self.events.append("mcp.start")
        if self.start_error is not None:
            self.state = McpClientState.FAILED
            raise self.start_error
        self.state = McpClientState.RUNNING

    async def close(self) -> None:
        self.events.append("mcp.close")
        self.state = McpClientState.CLOSED


class _RecordingComposition:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    async def close(self) -> None:
        self.events.append("composition.close")


class ApplicationAdmissionTest(unittest.IsolatedAsyncioTestCase):
    async def test_close_stops_new_work_and_waits_for_active_work(self) -> None:
        admission = ApplicationAdmission()
        await admission.start()
        entered = asyncio.Event()
        release = asyncio.Event()

        async def active_work() -> None:
            async with admission.admit():
                entered.set()
                await release.wait()

        work = asyncio.create_task(active_work())
        await entered.wait()
        closing = asyncio.create_task(admission.close())
        while admission.state is ApplicationAdmissionState.ACCEPTING:
            await asyncio.sleep(0)

        self.assertEqual(ApplicationAdmissionState.QUIESCING, admission.state)
        self.assertFalse(closing.done())
        with self.assertRaises(ApplicationNotAcceptingError):
            async with admission.admit():
                self.fail("quiescing admission accepted new work")

        release.set()
        await work
        await closing
        self.assertEqual(ApplicationAdmissionState.CLOSED, admission.state)

    async def test_concurrent_close_calls_share_the_same_drain(self) -> None:
        admission = ApplicationAdmission(accepting=True)

        await asyncio.gather(admission.close(), admission.close())

        self.assertEqual(ApplicationAdmissionState.CLOSED, admission.state)


class ApplicationLifecycleTest(unittest.IsolatedAsyncioTestCase):
    async def test_start_and_close_use_fixed_resource_order(self) -> None:
        events = ["composition.open"]
        admission = ApplicationAdmission()
        mcp = _RecordingMcpClients(events)
        composition = _RecordingComposition(events)
        lifecycle = ApplicationLifecycle(
            admission=admission,
            mcp_clients=mcp,  # type: ignore[arg-type]
            execution_composition=composition,
        )

        await lifecycle.start()
        await lifecycle.close()

        self.assertEqual(
            [
                "composition.open",
                "mcp.start",
                "composition.close",
                "mcp.close",
            ],
            events,
        )
        self.assertEqual(ApplicationLifecycleState.CLOSED, lifecycle.state)

    async def test_shutdown_drains_admission_before_closing_resources(self) -> None:
        events: list[str] = []
        admission = ApplicationAdmission()
        lifecycle = ApplicationLifecycle(
            admission=admission,
            mcp_clients=_RecordingMcpClients(events),  # type: ignore[arg-type]
            execution_composition=_RecordingComposition(events),
        )
        await lifecycle.start()
        release = asyncio.Event()
        entered = asyncio.Event()

        async def active_work() -> None:
            async with admission.admit():
                entered.set()
                await release.wait()

        work = asyncio.create_task(active_work())
        await entered.wait()
        closing = asyncio.create_task(lifecycle.close())
        await asyncio.sleep(0)

        self.assertEqual(["mcp.start"], events)
        release.set()
        await work
        await closing
        self.assertEqual(
            ["mcp.start", "composition.close", "mcp.close"],
            events,
        )

    async def test_mcp_start_failure_rolls_back_open_composition(self) -> None:
        events = ["composition.open"]
        lifecycle = ApplicationLifecycle(
            admission=ApplicationAdmission(),
            mcp_clients=_RecordingMcpClients(  # type: ignore[arg-type]
                events,
                start_error=RuntimeError("mcp failed"),
            ),
            execution_composition=_RecordingComposition(events),
        )

        with self.assertRaisesRegex(RuntimeError, "mcp failed"):
            await lifecycle.start()

        self.assertEqual(
            ["composition.open", "mcp.start", "composition.close"],
            events,
        )
        self.assertEqual(ApplicationLifecycleState.FAILED, lifecycle.state)

    async def test_close_before_start_releases_owned_resources(self) -> None:
        events = ["composition.open"]
        lifecycle = ApplicationLifecycle(
            admission=ApplicationAdmission(),
            mcp_clients=_RecordingMcpClients(events),  # type: ignore[arg-type]
            execution_composition=_RecordingComposition(events),
        )

        await lifecycle.close()

        self.assertEqual(
            ["composition.open", "composition.close", "mcp.close"],
            events,
        )


class ApplicationRunCommandsTest(unittest.IsolatedAsyncioTestCase):
    async def test_commands_are_rejected_after_admission_closes(self) -> None:
        admission = ApplicationAdmission(accepting=True)
        coordinator = AsyncMock()
        commands = ApplicationRunCommands(
            coordinator,  # type: ignore[arg-type]
            admission,
        )
        await admission.close()

        with self.assertRaises(ApplicationNotAcceptingError):
            await commands.cancel("run-1", owner_id="owner-1")

        coordinator.cancel.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
