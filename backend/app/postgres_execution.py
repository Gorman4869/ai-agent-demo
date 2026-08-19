from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
from datetime import timedelta
from enum import StrEnum
from types import MappingProxyType
from typing import Protocol

from backend.app.agent import AgentRuntime
from backend.app.domain.run import RuntimeName
from backend.app.services.run_coordinator import EventNotifier, RunCoordinator
from backend.app.services.run_recovery import RunRecoveryService
from backend.app.services.run_recovery_supervisor import RunRecoverySupervisor
from backend.app.stores.postgres import PostgresPersistence


LOGGER = logging.getLogger("postgres.execution.composition")


class PostgresExecutionCompositionState(StrEnum):
    STARTING = "starting"
    RUNNING = "running"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class PostgresExecutionCompositionLifecycleError(RuntimeError):
    code = "invalid_state"

    def __init__(self) -> None:
        super().__init__(self.code)


class PostgresRuntimeFactory(Protocol):
    def __call__(
        self,
        persistence: PostgresPersistence,
    ) -> Mapping[RuntimeName | str, AgentRuntime]: ...


class PostgresExecutionComposition:
    """Own one explicit PostgreSQL execution and recovery lifecycle.

    Close first quiesces Coordinator work, then stops recovery scanning, and
    only then closes the PostgreSQL resources.
    """

    def __init__(
        self,
        *,
        persistence: PostgresPersistence,
        runtimes: Mapping[RuntimeName | str, AgentRuntime],
        coordinator: RunCoordinator,
        recovery_supervisor: RunRecoverySupervisor,
        coordinator_quiesce_timeout_ms: int,
    ) -> None:
        self._persistence = persistence
        self._runtimes = runtimes
        self._coordinator = coordinator
        self._recovery_supervisor = recovery_supervisor
        self._coordinator_quiesce_timeout_ms = coordinator_quiesce_timeout_ms
        self._state = PostgresExecutionCompositionState.STARTING
        self._close_lock = asyncio.Lock()

    @classmethod
    async def open(
        cls,
        conninfo: str,
        *,
        runtimes: Mapping[RuntimeName | str, AgentRuntime] | None = None,
        runtime_factory: PostgresRuntimeFactory | None = None,
        notifier: EventNotifier | None = None,
        run_timeout_ms: int = 30_000,
        notify_timeout_ms: int | None = None,
        lease_ttl_ms: int = 30_000,
        lease_heartbeat_interval_ms: int = 10_000,
        coordinator_quiesce_timeout_ms: int = 5_000,
        recovery_scan_interval: timedelta = timedelta(seconds=5),
        recovery_scan_limit: int = 25,
        recovery_ttl: timedelta = timedelta(seconds=30),
    ) -> PostgresExecutionComposition:
        _validate_quiesce_timeout(coordinator_quiesce_timeout_ms)
        if (runtimes is None) == (runtime_factory is None):
            raise ValueError(
                "provide exactly one of runtimes or runtime_factory"
            )
        persistence = await PostgresPersistence.open(conninfo)
        supervisor: RunRecoverySupervisor | None = None
        try:
            await persistence.setup()
            resolved_runtimes = (
                runtimes
                if runtime_factory is None
                else runtime_factory(persistence)
            )
            if resolved_runtimes is None:
                raise ValueError("runtime_factory returned no runtimes")
            resolved_runtimes = MappingProxyType(dict(resolved_runtimes))
            coordinator = RunCoordinator(
                run_store=persistence.run_store,
                event_store=persistence.event_store,
                runtimes=resolved_runtimes,
                notifier=notifier,
                run_timeout_ms=run_timeout_ms,
                notify_timeout_ms=notify_timeout_ms,
                run_lease_store=persistence.run_lease_store,
                lease_ttl_ms=lease_ttl_ms,
                lease_heartbeat_interval_ms=lease_heartbeat_interval_ms,
            )
            recovery = RunRecoveryService(
                run_store=persistence.run_store,
                event_store=persistence.event_store,
                tool_execution_store=persistence.tool_execution_store,
                run_lease_store=persistence.run_lease_store,
            )
            supervisor = RunRecoverySupervisor(
                service=recovery,
                scan_interval=recovery_scan_interval,
                scan_limit=recovery_scan_limit,
                recovery_ttl=recovery_ttl,
            )
            composition = cls(
                persistence=persistence,
                runtimes=resolved_runtimes,
                coordinator=coordinator,
                recovery_supervisor=supervisor,
                coordinator_quiesce_timeout_ms=coordinator_quiesce_timeout_ms,
            )
            await supervisor.start()
        except asyncio.CancelledError:
            await _close_after_startup_failure(persistence, supervisor)
            raise
        except Exception:
            await _close_after_startup_failure(persistence, supervisor)
            raise

        composition._state = PostgresExecutionCompositionState.RUNNING
        return composition

    @property
    def state(self) -> PostgresExecutionCompositionState:
        return self._state

    @property
    def persistence(self) -> PostgresPersistence:
        return self._persistence

    @property
    def runtimes(self) -> Mapping[RuntimeName | str, AgentRuntime]:
        return self._runtimes

    @property
    def coordinator(self) -> RunCoordinator:
        return self._coordinator

    @property
    def recovery_supervisor(self) -> RunRecoverySupervisor:
        return self._recovery_supervisor

    async def close(self) -> None:
        async with self._close_lock:
            if self._state is PostgresExecutionCompositionState.CLOSED:
                return
            if self._state is not PostgresExecutionCompositionState.RUNNING:
                raise PostgresExecutionCompositionLifecycleError()

            self._state = PostgresExecutionCompositionState.CLOSING
            cancellation: asyncio.CancelledError | None = None
            try:
                await self._coordinator.quiesce(
                    timeout_ms=self._coordinator_quiesce_timeout_ms,
                )
            except asyncio.CancelledError as error:
                cancellation = error
            except Exception:
                self._state = PostgresExecutionCompositionState.FAILED
                try:
                    await self._recovery_supervisor.close()
                except (asyncio.CancelledError, Exception):
                    LOGGER.error(
                        "PostgreSQL recovery supervisor close failed after "
                        "Coordinator quiesce failure"
                    )
                raise

            supervisor_error: Exception | None = None
            try:
                await self._recovery_supervisor.close()
            except asyncio.CancelledError as error:
                if cancellation is None:
                    cancellation = error
            except Exception as error:
                supervisor_error = error

            try:
                await self._persistence.close()
            except asyncio.CancelledError:
                self._state = PostgresExecutionCompositionState.FAILED
                raise
            except Exception:
                self._state = PostgresExecutionCompositionState.FAILED
                raise
            if supervisor_error is not None:
                self._state = PostgresExecutionCompositionState.FAILED
                raise supervisor_error
            self._state = PostgresExecutionCompositionState.CLOSED
            if cancellation is not None:
                raise cancellation

    async def __aenter__(self) -> PostgresExecutionComposition:
        if self._state is not PostgresExecutionCompositionState.RUNNING:
            raise PostgresExecutionCompositionLifecycleError()
        return self

    async def __aexit__(self, *args: object) -> None:
        await self.close()


async def _close_after_startup_failure(
    persistence: PostgresPersistence,
    supervisor: RunRecoverySupervisor | None,
) -> None:
    if supervisor is not None:
        try:
            await supervisor.close()
        except asyncio.CancelledError:
            raise
        except Exception:
            LOGGER.error("PostgreSQL recovery supervisor startup cleanup failed")
    try:
        await persistence.close()
    except asyncio.CancelledError:
        raise
    except Exception:
        LOGGER.error("PostgreSQL execution startup cleanup failed")


def _validate_quiesce_timeout(timeout_ms: int) -> None:
    if (
        not isinstance(timeout_ms, int)
        or isinstance(timeout_ms, bool)
        or timeout_ms < 1
    ):
        raise ValueError("coordinator_quiesce_timeout_ms must be positive")


__all__ = [
    "PostgresExecutionComposition",
    "PostgresExecutionCompositionLifecycleError",
    "PostgresExecutionCompositionState",
    "PostgresRuntimeFactory",
]
