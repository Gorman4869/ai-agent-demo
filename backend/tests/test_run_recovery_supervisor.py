from __future__ import annotations

import asyncio
import unittest
from datetime import timedelta

from backend.app.services.run_recovery import (
    RunRecoveryResult,
    RunRecoveryStatus,
)
from backend.app.services.run_recovery_supervisor import (
    RunRecoverySupervisor,
    RunRecoverySupervisorLifecycleError,
    RunRecoverySupervisorState,
)
from backend.app.stores import StoreUnavailableError


FAST_INTERVAL = timedelta(milliseconds=5)
RECOVERY_TTL = timedelta(seconds=3)


class _RecordingRecoveryService:
    def __init__(self) -> None:
        self.calls: list[tuple[int, timedelta]] = []
        self.active_count = 0
        self.max_active_count = 0
        self.first_scan_completed = asyncio.Event()
        self.two_scans_completed = asyncio.Event()

    async def scan_once(
        self,
        *,
        limit: int,
        recovery_ttl: timedelta,
    ) -> tuple[RunRecoveryResult, ...]:
        self.calls.append((limit, recovery_ttl))
        self.active_count += 1
        self.max_active_count = max(self.max_active_count, self.active_count)
        try:
            await asyncio.sleep(0.02)
        finally:
            self.active_count -= 1
        self.first_scan_completed.set()
        if len(self.calls) >= 2:
            self.two_scans_completed.set()
        return ()


class _BlockingRecoveryService:
    def __init__(self) -> None:
        self.call_count = 0
        self.started = asyncio.Event()
        self.cleaned_up = asyncio.Event()

    async def scan_once(
        self,
        *,
        limit: int,
        recovery_ttl: timedelta,
    ) -> tuple[RunRecoveryResult, ...]:
        self.call_count += 1
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cleaned_up.set()
        return ()


class _SlowCancellationCleanupService:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cleanup_started = asyncio.Event()
        self.cleanup_finished = asyncio.Event()

    async def scan_once(
        self,
        *,
        limit: int,
        recovery_ttl: timedelta,
    ) -> tuple[RunRecoveryResult, ...]:
        self.started.set()
        try:
            await asyncio.Event().wait()
        finally:
            self.cleanup_started.set()
            try:
                await asyncio.Event().wait()
            finally:
                self.cleanup_finished.set()
        return ()


class _StoreFailureThenSuccessService:
    def __init__(self, *, item_failure: bool = False) -> None:
        self.item_failure = item_failure
        self.call_count = 0
        self.recovered = asyncio.Event()

    async def scan_once(
        self,
        *,
        limit: int,
        recovery_ttl: timedelta,
    ) -> tuple[RunRecoveryResult, ...]:
        self.call_count += 1
        if self.call_count == 1:
            if not self.item_failure:
                raise StoreUnavailableError()
            return (
                RunRecoveryResult(
                    run_id="failed-run",
                    status=RunRecoveryStatus.FAILED,
                    error_code="store_unavailable",
                ),
            )
        self.recovered.set()
        return ()


class _UnexpectedFailureService:
    def __init__(self) -> None:
        self.failed = asyncio.Event()

    async def scan_once(
        self,
        *,
        limit: int,
        recovery_ttl: timedelta,
    ) -> tuple[RunRecoveryResult, ...]:
        self.failed.set()
        raise ValueError("programmer error")


class RunRecoverySupervisorTest(unittest.IsolatedAsyncioTestCase):
    async def test_scans_serially_and_passes_bounded_settings(self) -> None:
        service = _RecordingRecoveryService()
        supervisor = self._supervisor(
            service,
            scan_limit=7,
            recovery_ttl=RECOVERY_TTL,
        )

        await supervisor.start()
        await asyncio.wait_for(service.two_scans_completed.wait(), timeout=1)
        await supervisor.close()

        self.assertEqual(1, service.max_active_count)
        self.assertGreaterEqual(len(service.calls), 2)
        self.assertTrue(all(call == (7, RECOVERY_TTL) for call in service.calls))
        self.assertEqual(RunRecoverySupervisorState.CLOSED, supervisor.state)

    async def test_repeated_start_uses_one_background_task(self) -> None:
        service = _BlockingRecoveryService()
        supervisor = self._supervisor(service)

        await supervisor.start()
        await supervisor.start()
        await asyncio.wait_for(service.started.wait(), timeout=1)
        await supervisor.close()

        self.assertEqual(1, service.call_count)

    async def test_close_cancels_inflight_scan_and_waits_for_cleanup(self) -> None:
        service = _BlockingRecoveryService()
        supervisor = self._supervisor(service)
        await supervisor.start()
        await asyncio.wait_for(service.started.wait(), timeout=1)

        await asyncio.wait_for(supervisor.close(), timeout=1)

        self.assertTrue(service.cleaned_up.is_set())
        self.assertEqual(RunRecoverySupervisorState.CLOSED, supervisor.state)

    async def test_close_interrupts_periodic_wait(self) -> None:
        service = _RecordingRecoveryService()
        supervisor = self._supervisor(
            service,
            scan_interval=timedelta(seconds=30),
        )
        await supervisor.start()
        await asyncio.wait_for(service.first_scan_completed.wait(), timeout=1)

        await asyncio.wait_for(supervisor.close(), timeout=0.1)

        self.assertEqual(RunRecoverySupervisorState.CLOSED, supervisor.state)

    async def test_cancelled_close_propagates_after_worker_cleanup(self) -> None:
        service = _SlowCancellationCleanupService()
        supervisor = self._supervisor(service)
        await supervisor.start()
        await asyncio.wait_for(service.started.wait(), timeout=1)
        closing = asyncio.create_task(supervisor.close())
        await asyncio.wait_for(service.cleanup_started.wait(), timeout=1)

        self.assertEqual(RunRecoverySupervisorState.CLOSING, supervisor.state)
        with self.assertRaises(RunRecoverySupervisorLifecycleError):
            await supervisor.start()
        closing.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await closing

        self.assertTrue(service.cleanup_finished.is_set())
        self.assertEqual(RunRecoverySupervisorState.CLOSED, supervisor.state)

    async def test_claim_store_error_does_not_stop_the_next_scan(self) -> None:
        service = _StoreFailureThenSuccessService()
        supervisor = self._supervisor(service)

        with self.assertLogs("run.recovery.supervisor", level="WARNING") as captured:
            await supervisor.start()
            await asyncio.wait_for(service.recovered.wait(), timeout=1)
            await supervisor.close()

        self.assertGreaterEqual(service.call_count, 2)
        self.assertIsNone(supervisor.last_error_code)
        self.assertEqual(
            ["WARNING:run.recovery.supervisor:Run recovery scan failed"],
            captured.output,
        )

    async def test_item_store_error_does_not_stop_the_next_scan(self) -> None:
        service = _StoreFailureThenSuccessService(item_failure=True)
        supervisor = self._supervisor(service)

        with self.assertLogs("run.recovery.supervisor", level="WARNING") as captured:
            await supervisor.start()
            await asyncio.wait_for(service.recovered.wait(), timeout=1)
            await supervisor.close()

        self.assertGreaterEqual(service.call_count, 2)
        self.assertIsNone(supervisor.last_error_code)
        self.assertEqual(
            ["WARNING:run.recovery.supervisor:Run recovery scan incomplete"],
            captured.output,
        )

    async def test_unexpected_failure_is_not_swallowed(self) -> None:
        service = _UnexpectedFailureService()
        supervisor = self._supervisor(service)
        await supervisor.start()
        await asyncio.wait_for(service.failed.wait(), timeout=1)
        await asyncio.sleep(0)

        with self.assertRaisesRegex(ValueError, "programmer error"):
            await supervisor.close()

        self.assertEqual(RunRecoverySupervisorState.FAILED, supervisor.state)

    async def test_close_before_start_is_idempotent_and_prevents_restart(
        self,
    ) -> None:
        supervisor = self._supervisor(_RecordingRecoveryService())

        await supervisor.close()
        await supervisor.close()

        self.assertEqual(RunRecoverySupervisorState.CLOSED, supervisor.state)
        with self.assertRaises(RunRecoverySupervisorLifecycleError) as raised:
            await supervisor.start()
        self.assertEqual("invalid_state", raised.exception.code)

    def test_invalid_settings_fail_before_start(self) -> None:
        service = _RecordingRecoveryService()
        cases = (
            {"scan_interval": timedelta(0)},
            {"scan_interval": 1},
            {"scan_limit": 0},
            {"scan_limit": 101},
            {"scan_limit": True},
            {"recovery_ttl": timedelta(0)},
            {"recovery_ttl": timedelta(days=1, microseconds=1)},
            {"recovery_ttl": 1},
        )

        for values in cases:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    self._supervisor(service, **values)

    def _supervisor(
        self,
        service,
        *,
        scan_interval: timedelta = FAST_INTERVAL,
        scan_limit: int = 5,
        recovery_ttl: timedelta = RECOVERY_TTL,
    ) -> RunRecoverySupervisor:
        return RunRecoverySupervisor(
            service=service,
            scan_interval=scan_interval,
            scan_limit=scan_limit,
            recovery_ttl=recovery_ttl,
        )


if __name__ == "__main__":
    unittest.main()
