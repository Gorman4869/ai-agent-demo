from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from enum import StrEnum
from typing import Protocol

from backend.app.domain.run import RunRecord
from backend.app.integrations.mcp import McpClientManager, McpClientState
from backend.app.services import RunCoordinator
from backend.app.tools import ApprovalResponse, ToolExecutionContext


LOGGER = logging.getLogger("application.lifecycle")


class ApplicationAdmissionState(StrEnum):
    CREATED = "created"
    ACCEPTING = "accepting"
    QUIESCING = "quiescing"
    CLOSED = "closed"


class ApplicationNotAcceptingError(RuntimeError):
    code = "application_not_accepting"

    def __init__(self) -> None:
        super().__init__(self.code)


class ApplicationAdmission:
    """Track HTTP and command work before owned resources are closed."""

    def __init__(self, *, accepting: bool = False) -> None:
        self._state = (
            ApplicationAdmissionState.ACCEPTING
            if accepting
            else ApplicationAdmissionState.CREATED
        )
        self._active = 0
        self._drained = asyncio.Event()
        self._drained.set()
        self._lock = asyncio.Lock()
        self._drain_task: asyncio.Task[None] | None = None

    @property
    def state(self) -> ApplicationAdmissionState:
        return self._state

    async def start(self) -> None:
        async with self._lock:
            if self._state is ApplicationAdmissionState.ACCEPTING:
                return
            if self._state is not ApplicationAdmissionState.CREATED:
                raise ApplicationNotAcceptingError()
            self._state = ApplicationAdmissionState.ACCEPTING

    @asynccontextmanager
    async def admit(self) -> AsyncIterator[None]:
        await self.acquire()
        try:
            yield
        finally:
            await self.release()

    async def acquire(self) -> None:
        async with self._lock:
            if self._state is not ApplicationAdmissionState.ACCEPTING:
                raise ApplicationNotAcceptingError()
            self._active += 1
            if self._active == 1:
                self._drained.clear()

    async def release(self) -> None:
        operation = asyncio.create_task(
            self._release_once(),
            name="application-admission-release",
        )
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            await operation
            raise

    async def _release_once(self) -> None:
        async with self._lock:
            if self._active < 1:
                raise RuntimeError("application admission has no active work")
            self._active -= 1
            if self._active == 0:
                self._drained.set()

    async def close(self) -> None:
        operation = asyncio.create_task(
            self._begin_close(),
            name="application-admission-close-request",
        )
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            await operation
            raise

    async def _begin_close(self) -> None:
        async with self._lock:
            if self._state is ApplicationAdmissionState.CLOSED:
                return
            if self._state is ApplicationAdmissionState.CREATED:
                self._state = ApplicationAdmissionState.CLOSED
                return
            if self._state is ApplicationAdmissionState.ACCEPTING:
                self._state = ApplicationAdmissionState.QUIESCING
                self._drain_task = asyncio.create_task(
                    self._drain(),
                    name="application-admission-drain",
                )
            drain = self._drain_task
        if drain is None:
            raise RuntimeError("application admission drain task is missing")
        await drain

    async def _drain(self) -> None:
        await self._drained.wait()
        async with self._lock:
            self._state = ApplicationAdmissionState.CLOSED


class ApplicationRunCommands:
    """Admission-controlled programmatic access to durable Run commands."""

    def __init__(
        self,
        coordinator: RunCoordinator,
        admission: ApplicationAdmission,
    ) -> None:
        self._coordinator = coordinator
        self._admission = admission

    async def execute(
        self,
        run_id: str,
        *,
        owner_id: str,
        execution_context: ToolExecutionContext | None = None,
    ) -> RunRecord:
        async with self._admission.admit():
            return await self._coordinator.execute(
                run_id,
                owner_id=owner_id,
                execution_context=execution_context,
            )

    async def resume_approval(
        self,
        run_id: str,
        *,
        owner_id: str,
        approval_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments_digest: str,
        decision: ApprovalResponse | str,
        execution_context: ToolExecutionContext,
    ) -> RunRecord:
        async with self._admission.admit():
            return await self._coordinator.resume_approval(
                run_id,
                owner_id=owner_id,
                approval_id=approval_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments_digest=arguments_digest,
                decision=decision,
                execution_context=execution_context,
            )

    async def cancel(self, run_id: str, *, owner_id: str) -> bool:
        async with self._admission.admit():
            return await self._coordinator.cancel(run_id, owner_id=owner_id)


class ApplicationLifecycleState(StrEnum):
    CREATED = "created"
    STARTING = "starting"
    RUNNING = "running"
    CLOSING = "closing"
    CLOSED = "closed"
    FAILED = "failed"


class _ExecutionComposition(Protocol):
    async def close(self) -> None: ...


class ApplicationLifecycle:
    """Own admission, PostgreSQL execution, and MCP for one application."""

    def __init__(
        self,
        *,
        admission: ApplicationAdmission,
        mcp_clients: McpClientManager,
        execution_composition: _ExecutionComposition | None = None,
    ) -> None:
        self._admission = admission
        self._mcp_clients = mcp_clients
        self._execution_composition = execution_composition
        self._state = ApplicationLifecycleState.CREATED
        self._operation_lock = asyncio.Lock()

    @property
    def state(self) -> ApplicationLifecycleState:
        return self._state

    async def start(self) -> None:
        async with self._operation_lock:
            if self._state is ApplicationLifecycleState.RUNNING:
                return
            if self._state is not ApplicationLifecycleState.CREATED:
                raise ApplicationNotAcceptingError()
            self._state = ApplicationLifecycleState.STARTING
            try:
                await self._mcp_clients.start()
                await self._admission.start()
            except asyncio.CancelledError:
                await self._cleanup_startup()
                self._state = ApplicationLifecycleState.FAILED
                raise
            except Exception:
                await self._cleanup_startup()
                self._state = ApplicationLifecycleState.FAILED
                raise
            self._state = ApplicationLifecycleState.RUNNING

    async def close(self) -> None:
        operation = asyncio.create_task(
            self._close_once(),
            name="application-lifecycle-close-request",
        )
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            await operation
            raise

    async def _close_once(self) -> None:
        async with self._operation_lock:
            if self._state in {
                ApplicationLifecycleState.CLOSED,
                ApplicationLifecycleState.FAILED,
            }:
                return
            self._state = ApplicationLifecycleState.CLOSING
            cancellation: asyncio.CancelledError | None = None
            first_error: Exception | None = None

            try:
                await self._admission.close()
            except asyncio.CancelledError as error:
                cancellation = error
            except Exception as error:
                first_error = error

            if self._execution_composition is not None:
                try:
                    await self._execution_composition.close()
                except asyncio.CancelledError as error:
                    if cancellation is None:
                        cancellation = error
                except Exception as error:
                    if first_error is None:
                        first_error = error

            try:
                await self._mcp_clients.close()
            except asyncio.CancelledError as error:
                if cancellation is None:
                    cancellation = error
            except Exception as error:
                if first_error is None:
                    first_error = error

            if first_error is not None:
                self._state = ApplicationLifecycleState.FAILED
                raise first_error
            self._state = ApplicationLifecycleState.CLOSED
            if cancellation is not None:
                raise cancellation

    async def _cleanup_startup(self) -> None:
        try:
            await self._admission.close()
        except (asyncio.CancelledError, Exception):
            LOGGER.error("Application admission startup cleanup failed")
        if self._execution_composition is not None:
            try:
                await self._execution_composition.close()
            except (asyncio.CancelledError, Exception):
                LOGGER.error("Application execution startup cleanup failed")
        if self._mcp_clients.state in {
            McpClientState.CREATED,
            McpClientState.RUNNING,
        }:
            try:
                await self._mcp_clients.close()
            except (asyncio.CancelledError, Exception):
                LOGGER.error("MCP startup cleanup failed")


__all__ = [
    "ApplicationAdmission",
    "ApplicationAdmissionState",
    "ApplicationLifecycle",
    "ApplicationLifecycleState",
    "ApplicationNotAcceptingError",
    "ApplicationRunCommands",
]
