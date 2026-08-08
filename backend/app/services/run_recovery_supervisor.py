from __future__ import annotations

import asyncio
import logging
from datetime import timedelta
from enum import StrEnum

from backend.app.services.run_recovery import (
    RunRecoveryService,
    RunRecoveryStatus,
)
from backend.app.stores import StoreError


LOGGER = logging.getLogger("run.recovery.supervisor")


class RunRecoverySupervisorState(StrEnum):
    CREATED = "created"
    RUNNING = "running"
    CLOSING = "closing"
    FAILED = "failed"
    CLOSED = "closed"


class RunRecoverySupervisorLifecycleError(RuntimeError):
    code = "invalid_state"

    def __init__(self) -> None:
        super().__init__(self.code)


class RunRecoverySupervisor:
    """Run one serialized recovery scan loop for an explicit application owner."""

    def __init__(
        self,
        *,
        service: RunRecoveryService,
        scan_interval: timedelta = timedelta(seconds=5),
        scan_limit: int = 25,
        recovery_ttl: timedelta = timedelta(seconds=30),
    ) -> None:
        if not isinstance(scan_interval, timedelta):
            raise ValueError("scan_interval must be a positive timedelta")
        if scan_interval <= timedelta(0):
            raise ValueError("scan_interval must be positive")
        if isinstance(scan_limit, bool) or not isinstance(scan_limit, int):
            raise ValueError("scan_limit must be a positive integer")
        if not 1 <= scan_limit <= 100:
            raise ValueError("scan_limit must be between 1 and 100")
        if not isinstance(recovery_ttl, timedelta):
            raise ValueError("recovery_ttl must be a positive timedelta")
        if not timedelta(0) < recovery_ttl <= timedelta(days=1):
            raise ValueError("recovery_ttl must be between zero and one day")

        self._service = service
        self._scan_interval_seconds = scan_interval.total_seconds()
        self._scan_limit = scan_limit
        self._recovery_ttl = recovery_ttl
        self._state = RunRecoverySupervisorState.CREATED
        self._last_error_code: str | None = None
        self._task: asyncio.Task[None] | None = None

    @property
    def state(self) -> RunRecoverySupervisorState:
        return self._state

    @property
    def last_error_code(self) -> str | None:
        return self._last_error_code

    async def start(self) -> None:
        if self._state is RunRecoverySupervisorState.RUNNING:
            return
        if self._state is not RunRecoverySupervisorState.CREATED:
            raise RunRecoverySupervisorLifecycleError()

        self._state = RunRecoverySupervisorState.RUNNING
        self._task = asyncio.create_task(
            self._run_loop(),
            name="run-recovery-supervisor",
        )

    async def close(self) -> None:
        if self._state is RunRecoverySupervisorState.CLOSED:
            return
        if self._state is RunRecoverySupervisorState.CREATED:
            self._state = RunRecoverySupervisorState.CLOSED
            return
        if self._state is RunRecoverySupervisorState.RUNNING:
            self._state = RunRecoverySupervisorState.CLOSING
        elif self._state not in {
            RunRecoverySupervisorState.CLOSING,
            RunRecoverySupervisorState.FAILED,
        }:
            raise RunRecoverySupervisorLifecycleError()

        task = self._task
        if task is None:
            self._state = RunRecoverySupervisorState.FAILED
            raise RunRecoverySupervisorLifecycleError()

        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            current_task = asyncio.current_task()
            if current_task is not None and current_task.cancelling():
                self._state = (
                    RunRecoverySupervisorState.CLOSED
                    if task.done()
                    else RunRecoverySupervisorState.FAILED
                )
                raise
            if not task.cancelled():
                self._state = RunRecoverySupervisorState.FAILED
                raise
        except Exception:
            self._state = RunRecoverySupervisorState.FAILED
            raise
        else:
            self._state = RunRecoverySupervisorState.CLOSED
            return

        self._state = RunRecoverySupervisorState.CLOSED

    async def _run_loop(self) -> None:
        try:
            while True:
                await self._scan_once()
                await asyncio.sleep(self._scan_interval_seconds)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._state = RunRecoverySupervisorState.FAILED
            raise

    async def _scan_once(self) -> None:
        try:
            results = await self._service.scan_once(
                limit=self._scan_limit,
                recovery_ttl=self._recovery_ttl,
            )
        except StoreError as error:
            self._last_error_code = error.code
            LOGGER.warning("Run recovery scan failed", extra={"error_code": error.code})
            return

        failed = next(
            (
                result
                for result in results
                if result.status is RunRecoveryStatus.FAILED
            ),
            None,
        )
        if failed is None:
            self._last_error_code = None
            return

        self._last_error_code = failed.error_code or "store_error"
        LOGGER.warning(
            "Run recovery scan incomplete",
            extra={"error_code": self._last_error_code},
        )


__all__ = [
    "RunRecoverySupervisor",
    "RunRecoverySupervisorLifecycleError",
    "RunRecoverySupervisorState",
]
