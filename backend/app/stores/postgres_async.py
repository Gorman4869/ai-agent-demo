from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from concurrent.futures import Future as ConcurrentFuture
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from enum import StrEnum
from functools import partial
from typing import Any, ParamSpec, TypeVar

from backend.app.domain import Message
from backend.app.memory import MemoryFact, MemoryScope, MemoryStore
from backend.app.stores.base import StoreError
from backend.app.tools import (
    ApprovalDecision,
    ApprovalResponse,
    ApprovalStore,
    ToolApproval,
    ToolApprovalRequest,
    ToolApprovalResolution,
    copy_tool_arguments,
)


_Parameters = ParamSpec("_Parameters")
_Result = TypeVar("_Result")


class PostgresSyncStoreBridgeState(StrEnum):
    ACCEPTING = "accepting"
    QUIESCING = "quiescing"
    QUIESCED = "quiesced"
    FAILED = "failed"


class PostgresSyncStoreLifecycleError(StoreError):
    code = "store_not_accepting"


class PostgresSyncStoreTimeoutError(StoreError):
    code = "store_operation_timeout"

    def __init__(self, *, result_unknown: bool) -> None:
        self.result_unknown = result_unknown
        super().__init__()


class PostgresSyncStoreBridge:
    """Run synchronous PostgreSQL Stores without blocking the event loop."""

    def __init__(
        self,
        *,
        max_workers: int,
        operation_timeout_ms: int,
    ) -> None:
        _validate_positive_integer(max_workers, "max_workers")
        _validate_positive_integer(
            operation_timeout_ms,
            "operation_timeout_ms",
        )
        self._operation_timeout = operation_timeout_ms / 1_000
        self._executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="postgres-sync-store",
        )
        self._state = PostgresSyncStoreBridgeState.ACCEPTING
        self._lock = asyncio.Lock()
        self._in_flight: set[asyncio.Future[object]] = set()
        self._drain_task: asyncio.Task[None] | None = None

    @property
    def state(self) -> PostgresSyncStoreBridgeState:
        return self._state

    async def run(
        self,
        operation: Callable[_Parameters, _Result],
        *args: _Parameters.args,
        **kwargs: _Parameters.kwargs,
    ) -> _Result:
        loop = asyncio.get_running_loop()
        async with self._lock:
            if self._state is not PostgresSyncStoreBridgeState.ACCEPTING:
                raise PostgresSyncStoreLifecycleError()
            submitted: ConcurrentFuture[_Result] = self._executor.submit(
                partial(operation, *args, **kwargs)
            )
            worker = asyncio.wrap_future(submitted, loop=loop)
            self._in_flight.add(worker)
            worker.add_done_callback(self._consume_worker)

        try:
            return await asyncio.wait_for(
                asyncio.shield(worker),
                timeout=self._operation_timeout,
            )
        except TimeoutError:
            queued_cancelled = submitted.cancel()
            raise PostgresSyncStoreTimeoutError(
                result_unknown=not queued_cancelled,
            ) from None
        except asyncio.CancelledError:
            submitted.cancel()
            raise

    async def close(self) -> None:
        operation = asyncio.create_task(
            self._begin_close(),
            name="postgres-sync-store-close-request",
        )
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            await operation
            raise

    async def _begin_close(self) -> None:
        async with self._lock:
            if self._state is PostgresSyncStoreBridgeState.QUIESCED:
                return
            if self._state is PostgresSyncStoreBridgeState.FAILED:
                raise PostgresSyncStoreLifecycleError()
            if self._state is PostgresSyncStoreBridgeState.ACCEPTING:
                self._state = PostgresSyncStoreBridgeState.QUIESCING
                self._drain_task = asyncio.create_task(
                    self._drain(),
                    name="postgres-sync-store-drain",
                )
            drain = self._drain_task
        if drain is None:
            raise RuntimeError("PostgreSQL sync Store drain task is missing")
        await drain

    async def _drain(self) -> None:
        try:
            async with self._lock:
                workers = tuple(self._in_flight)
            if workers:
                await asyncio.gather(*workers, return_exceptions=True)
            self._executor.shutdown(wait=True, cancel_futures=False)
        except Exception:
            async with self._lock:
                self._state = PostgresSyncStoreBridgeState.FAILED
            raise
        async with self._lock:
            self._state = PostgresSyncStoreBridgeState.QUIESCED

    def _consume_worker(self, worker: asyncio.Future[object]) -> None:
        self._in_flight.discard(worker)
        if worker.cancelled():
            return
        try:
            worker.exception()
        except asyncio.CancelledError:
            pass


class AsyncPostgresApprovalStore:
    """Async facade for the existing synchronous ApprovalStore contract."""

    def __init__(
        self,
        store: ApprovalStore,
        bridge: PostgresSyncStoreBridge,
    ) -> None:
        self._store = store
        self._bridge = bridge

    async def grant(
        self,
        *,
        principal_id: str,
        run_id: str | None = None,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        expires_at: datetime | None = None,
    ) -> ToolApproval:
        return await self._bridge.run(
            self._store.grant,
            principal_id=principal_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=copy_tool_arguments(arguments),
            expires_at=expires_at,
        )

    async def request(
        self,
        *,
        run_id: str,
        principal_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        expires_in: timedelta | None = None,
    ) -> ToolApprovalRequest:
        return await self._bridge.run(
            self._store.request,
            run_id=run_id,
            principal_id=principal_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=copy_tool_arguments(arguments),
            expires_in=expires_in,
        )

    async def resolve(
        self,
        *,
        approval_id: str,
        run_id: str,
        principal_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments_digest: str,
        decision: ApprovalResponse | str,
    ) -> ToolApprovalResolution:
        return await self._bridge.run(
            self._store.resolve,
            approval_id=approval_id,
            run_id=run_id,
            principal_id=principal_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments_digest=arguments_digest,
            decision=decision,
        )

    async def get_resolution(
        self,
        *,
        approval_id: str,
        run_id: str,
        principal_id: str,
    ) -> ToolApprovalResolution | None:
        return await self._bridge.run(
            self._store.get_resolution,
            approval_id=approval_id,
            run_id=run_id,
            principal_id=principal_id,
        )

    async def approved_arguments(
        self,
        resolution: ToolApprovalResolution,
    ) -> dict[str, Any]:
        return await self._bridge.run(
            self._store.approved_arguments,
            resolution,
        )

    async def consume(
        self,
        *,
        principal_id: str,
        run_id: str | None = None,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> ApprovalDecision:
        return await self._bridge.run(
            self._store.consume,
            principal_id=principal_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=copy_tool_arguments(arguments),
        )


class AsyncPostgresMemoryStore:
    """Async facade for the existing synchronous MemoryStore contract."""

    def __init__(
        self,
        store: MemoryStore,
        bridge: PostgresSyncStoreBridge,
    ) -> None:
        self._store = store
        self._bridge = bridge

    async def append_message(self, session_id: str, message: Message) -> None:
        await self._bridge.run(
            self._store.append_message,
            session_id,
            message,
        )

    async def messages(self, session_id: str) -> tuple[Message, ...]:
        return await self._bridge.run(self._store.messages, session_id)

    async def remember(
        self,
        *,
        owner_id: str,
        key: str,
        value: str,
        scope: MemoryScope,
        approved: bool,
    ) -> MemoryFact:
        return await self._bridge.run(
            self._store.remember,
            owner_id=owner_id,
            key=key,
            value=value,
            scope=scope,
            approved=approved,
        )

    async def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        return await self._bridge.run(self._store.facts, owner_id)

    async def forget(self, fact_id: str, *, owner_id: str) -> bool:
        return await self._bridge.run(
            self._store.forget,
            fact_id,
            owner_id=owner_id,
        )


def _validate_positive_integer(value: int, label: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be a positive integer")


__all__ = [
    "AsyncPostgresApprovalStore",
    "AsyncPostgresMemoryStore",
    "PostgresSyncStoreBridge",
    "PostgresSyncStoreBridgeState",
    "PostgresSyncStoreLifecycleError",
    "PostgresSyncStoreTimeoutError",
]
