from __future__ import annotations

import asyncio
import unittest
from contextlib import ExitStack
from datetime import timedelta
from unittest.mock import AsyncMock, patch

from backend.app.postgres_execution import (
    PostgresExecutionComposition,
    PostgresExecutionCompositionLifecycleError,
    PostgresExecutionCompositionState,
)
from backend.app.services.run_coordinator import RunCoordinator
from backend.app.stores import StoreUnavailableError
from backend.app.stores.postgres import PostgresPersistence


class _Runtime:
    async def run(self, request, *, emit, control):
        del request, emit, control
        raise AssertionError("unit composition runtime must not execute")


class _FakePersistence:
    def __init__(
        self,
        events: list[str],
        *,
        setup_error: Exception | None = None,
        block_setup: bool = False,
    ) -> None:
        self.events = events
        self.setup_error = setup_error
        self.block_setup = block_setup
        self.setup_started = asyncio.Event()
        self.run_store = object()
        self.event_store = object()
        self.run_lease_store = object()
        self.tool_execution_store = object()
        self.async_memory_store = object()

    async def setup(self) -> None:
        self.events.append("persistence.setup")
        self.setup_started.set()
        if self.block_setup:
            await asyncio.Event().wait()
        if self.setup_error is not None:
            raise self.setup_error

    async def close(self) -> None:
        self.events.append("persistence.close")


class _FakeSupervisor:
    def __init__(
        self,
        events: list[str],
        *,
        start_error: Exception | None = None,
        close_error: Exception | None = None,
        block_close: bool = False,
    ) -> None:
        self.events = events
        self.start_error = start_error
        self.close_error = close_error
        self.block_close = block_close
        self.close_started = asyncio.Event()
        self.close_cleaned_up = asyncio.Event()

    async def start(self) -> None:
        self.events.append("supervisor.start")
        if self.start_error is not None:
            raise self.start_error

    async def close(self) -> None:
        self.events.append("supervisor.close")
        self.close_started.set()
        try:
            if self.block_close:
                await asyncio.Event().wait()
            if self.close_error is not None:
                raise self.close_error
        finally:
            self.close_cleaned_up.set()


class PostgresExecutionCompositionTest(unittest.IsolatedAsyncioTestCase):
    async def test_open_and_close_follow_owned_resource_order(self) -> None:
        events: list[str] = []
        persistence = _FakePersistence(events)
        supervisor = _FakeSupervisor(events)

        composition = await self._open(persistence, supervisor)

        self.assertEqual(PostgresExecutionCompositionState.RUNNING, composition.state)
        self.assertIs(composition.persistence, persistence)
        self.assertIsInstance(composition.runtimes["manual"], _Runtime)
        self.assertIs(composition.recovery_supervisor, supervisor)
        self.assertIsInstance(composition.coordinator, RunCoordinator)
        quiesce = AsyncMock(
            side_effect=lambda **kwargs: events.append("coordinator.quiesce")
        )
        with patch.object(composition.coordinator, "quiesce", new=quiesce):
            await composition.close()

        self.assertEqual(
            [
                "persistence.setup",
                "supervisor.start",
                "coordinator.quiesce",
                "supervisor.close",
                "persistence.close",
            ],
            events,
        )
        quiesce.assert_awaited_once_with(timeout_ms=5_000)
        self.assertEqual(PostgresExecutionCompositionState.CLOSED, composition.state)

    async def test_runtime_factory_runs_after_setup_and_exposes_runtimes(
        self,
    ) -> None:
        events: list[str] = []
        persistence = _FakePersistence(events)
        runtime = _Runtime()

        def runtime_factory(resolved_persistence):
            self.assertIs(persistence, resolved_persistence)
            events.append("runtime_factory")
            return {"manual": runtime}

        with self._patch_components(
            persistence,
            _FakeSupervisor(events),
        ):
            composition = await PostgresExecutionComposition.open(
                "postgresql://private-connection",
                runtime_factory=runtime_factory,
            )

        self.assertEqual(
            ["persistence.setup", "runtime_factory", "supervisor.start"],
            events,
        )
        self.assertIs(runtime, composition.runtimes["manual"])

    async def test_runtime_factory_failure_closes_persistence(self) -> None:
        events: list[str] = []
        persistence = _FakePersistence(events)

        def broken_factory(_persistence):
            events.append("runtime_factory")
            raise RuntimeError("runtime-factory-failed")

        with self._patch_components(
            persistence,
            _FakeSupervisor(events),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "runtime-factory-failed",
            ):
                await PostgresExecutionComposition.open(
                    "postgresql://private-connection",
                    runtime_factory=broken_factory,
                )

        self.assertEqual(
            ["persistence.setup", "runtime_factory", "persistence.close"],
            events,
        )

    async def test_runtime_factory_invalid_result_closes_persistence(
        self,
    ) -> None:
        events: list[str] = []
        persistence = _FakePersistence(events)

        with self._patch_components(
            persistence,
            _FakeSupervisor(events),
        ):
            with self.assertRaisesRegex(ValueError, "returned no runtimes"):
                await PostgresExecutionComposition.open(
                    "postgresql://private-connection",
                    runtime_factory=lambda _persistence: None,
                )

        self.assertEqual(
            ["persistence.setup", "persistence.close"],
            events,
        )

    async def test_exactly_one_runtime_source_is_required_before_open(
        self,
    ) -> None:
        opened = AsyncMock()

        with patch.object(PostgresPersistence, "open", new=opened):
            with self.assertRaisesRegex(ValueError, "exactly one"):
                await PostgresExecutionComposition.open(
                    "postgresql://private-connection",
                )
            with self.assertRaisesRegex(ValueError, "exactly one"):
                await PostgresExecutionComposition.open(
                    "postgresql://private-connection",
                    runtimes={"manual": _Runtime()},
                    runtime_factory=lambda _persistence: {
                        "manual": _Runtime()
                    },
                )

        opened.assert_not_awaited()

    async def test_repeated_close_is_idempotent(self) -> None:
        events: list[str] = []
        composition = await self._open(
            _FakePersistence(events),
            _FakeSupervisor(events),
        )

        await composition.close()
        await composition.close()

        self.assertEqual(1, events.count("supervisor.close"))
        self.assertEqual(1, events.count("persistence.close"))

    async def test_context_manager_closes_the_composition(self) -> None:
        events: list[str] = []
        composition = await self._open(
            _FakePersistence(events),
            _FakeSupervisor(events),
        )

        async with composition as entered:
            self.assertIs(composition, entered)

        self.assertEqual(PostgresExecutionCompositionState.CLOSED, composition.state)
        with self.assertRaises(PostgresExecutionCompositionLifecycleError):
            async with composition:
                self.fail("closed composition must not be re-entered")

    async def test_setup_failure_closes_opened_persistence(self) -> None:
        events: list[str] = []
        persistence = _FakePersistence(
            events,
            setup_error=StoreUnavailableError(),
        )
        supervisor = _FakeSupervisor(events)

        with self.assertRaises(StoreUnavailableError):
            await self._open(persistence, supervisor)

        self.assertEqual(
            ["persistence.setup", "persistence.close"],
            events,
        )

    async def test_cancelled_setup_closes_persistence_and_propagates(self) -> None:
        events: list[str] = []
        persistence = _FakePersistence(events, block_setup=True)
        supervisor = _FakeSupervisor(events)

        with self._patch_components(persistence, supervisor):
            opening = asyncio.create_task(
                PostgresExecutionComposition.open(
                    "postgresql://private-connection",
                    runtimes={"manual": _Runtime()},
                )
            )
            await asyncio.wait_for(persistence.setup_started.wait(), timeout=1)
            opening.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await opening

        self.assertEqual(
            ["persistence.setup", "persistence.close"],
            events,
        )

    async def test_invalid_supervisor_config_closes_persistence(self) -> None:
        events: list[str] = []
        persistence = _FakePersistence(events)
        opened = AsyncMock(return_value=persistence)

        with patch.object(PostgresPersistence, "open", new=opened):
            with self.assertRaises(ValueError):
                await PostgresExecutionComposition.open(
                    "postgresql://private-connection",
                    runtimes={"manual": _Runtime()},
                    recovery_scan_interval=timedelta(0),
                )

        self.assertEqual(
            ["persistence.setup", "persistence.close"],
            events,
        )

    async def test_invalid_quiesce_timeout_opens_no_persistence(self) -> None:
        opened = AsyncMock()

        with patch.object(PostgresPersistence, "open", new=opened):
            with self.assertRaises(ValueError):
                await PostgresExecutionComposition.open(
                    "postgresql://private-connection",
                    runtimes={"manual": _Runtime()},
                    coordinator_quiesce_timeout_ms=0,
                )

        opened.assert_not_awaited()

    async def test_supervisor_start_failure_closes_all_owned_resources(self) -> None:
        events: list[str] = []
        supervisor = _FakeSupervisor(
            events,
            start_error=RuntimeError("supervisor-start-failed"),
        )

        with self.assertRaisesRegex(RuntimeError, "supervisor-start-failed"):
            await self._open(_FakePersistence(events), supervisor)

        self.assertEqual(
            [
                "persistence.setup",
                "supervisor.start",
                "supervisor.close",
                "persistence.close",
            ],
            events,
        )

    async def test_supervisor_close_failure_still_closes_persistence(self) -> None:
        events: list[str] = []
        supervisor = _FakeSupervisor(
            events,
            close_error=RuntimeError("supervisor-close-failed"),
        )
        composition = await self._open(_FakePersistence(events), supervisor)

        with self.assertRaisesRegex(RuntimeError, "supervisor-close-failed"):
            await composition.close()

        self.assertEqual(
            ["supervisor.close", "persistence.close"],
            events[-2:],
        )
        self.assertEqual(PostgresExecutionCompositionState.FAILED, composition.state)

    async def test_cancelled_close_cleans_both_owned_resources(self) -> None:
        events: list[str] = []
        supervisor = _FakeSupervisor(events, block_close=True)
        composition = await self._open(_FakePersistence(events), supervisor)
        closing = asyncio.create_task(composition.close())
        await asyncio.wait_for(supervisor.close_started.wait(), timeout=1)

        closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closing

        self.assertTrue(supervisor.close_cleaned_up.is_set())
        self.assertEqual("persistence.close", events[-1])
        self.assertEqual(PostgresExecutionCompositionState.CLOSED, composition.state)

    async def test_cancelled_quiesce_closes_remaining_owned_resources(self) -> None:
        events: list[str] = []
        composition = await self._open(
            _FakePersistence(events),
            _FakeSupervisor(events),
        )
        quiesce = AsyncMock(side_effect=asyncio.CancelledError())

        with patch.object(composition.coordinator, "quiesce", new=quiesce):
            with self.assertRaises(asyncio.CancelledError):
                await composition.close()

        self.assertEqual(
            ["supervisor.close", "persistence.close"],
            events[-2:],
        )
        self.assertEqual(PostgresExecutionCompositionState.CLOSED, composition.state)

    async def test_quiesce_failure_does_not_close_persistence_under_active_work(
        self,
    ) -> None:
        events: list[str] = []
        composition = await self._open(
            _FakePersistence(events),
            _FakeSupervisor(events),
        )
        quiesce = AsyncMock(side_effect=RuntimeError("quiesce-failed"))

        with patch.object(composition.coordinator, "quiesce", new=quiesce):
            with self.assertRaisesRegex(RuntimeError, "quiesce-failed"):
                await composition.close()

        self.assertEqual("supervisor.close", events[-1])
        self.assertNotIn("persistence.close", events)
        self.assertEqual(PostgresExecutionCompositionState.FAILED, composition.state)

    async def _open(
        self,
        persistence: _FakePersistence,
        supervisor: _FakeSupervisor,
    ) -> PostgresExecutionComposition:
        with self._patch_components(persistence, supervisor):
            return await PostgresExecutionComposition.open(
                "postgresql://private-connection",
                runtimes={"manual": _Runtime()},
            )

    def _patch_components(
        self,
        persistence: _FakePersistence,
        supervisor: _FakeSupervisor,
    ) -> ExitStack:
        opened = AsyncMock(return_value=persistence)
        stack = ExitStack()
        stack.enter_context(patch.object(PostgresPersistence, "open", new=opened))
        stack.enter_context(
            patch(
                "backend.app.postgres_execution.RunRecoverySupervisor",
                return_value=supervisor,
            )
        )
        return stack


if __name__ == "__main__":
    unittest.main()
