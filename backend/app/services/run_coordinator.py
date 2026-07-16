from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from backend.app.agent import (
    AgentRuntime,
    CancellationToken,
    RuntimeControl,
    RuntimeEvent,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.domain.run import (
    RunFailure,
    RunRecord,
    RunStatus,
    RuntimeName,
    StoredRunEvent,
)
from backend.app.stores import (
    AppendEventResult,
    ConcurrentWriteError,
    EventStore,
    InvalidRunTransitionError,
    RunNotFoundError,
    RunStore,
    StartCommit,
    StoreError,
    TerminalCommit,
)
from backend.app.tools import ToolExecutionContext


LOGGER = logging.getLogger(__name__)
EventIdFactory = Callable[[RuntimeEvent, int], str]


class EventNotifier(Protocol):
    """Live delivery hook; EventStore remains the replayable source of truth."""

    async def notify(self, event: StoredRunEvent) -> None:
        ...


class NullEventNotifier(EventNotifier):
    async def notify(self, event: StoredRunEvent) -> None:
        del event


class PersistentEventEmitter:
    """Persist one event before making it visible to live subscribers."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        run_id: str,
        owner_id: str,
        notifier: EventNotifier | None = None,
        event_id_factory: EventIdFactory | None = None,
        notify_timeout_ms: int = 1_000,
    ) -> None:
        if (
            not isinstance(notify_timeout_ms, int)
            or isinstance(notify_timeout_ms, bool)
            or notify_timeout_ms < 1
        ):
            raise ValueError("notify_timeout_ms must be a positive integer")
        self._event_store = event_store
        self._run_id = run_id
        self._owner_id = owner_id
        self._notifier = notifier or NullEventNotifier()
        self._event_id_factory = event_id_factory or self._default_event_id
        self._notify_timeout_ms = notify_timeout_ms
        self._ordinal = 0

    async def emit(self, event: RuntimeEvent) -> AppendEventResult:
        self._ordinal += 1
        result = await self._event_store.append(
            event_id=self._event_id_factory(event, self._ordinal),
            run_id=self._run_id,
            owner_id=self._owner_id,
            event_type=event.type,
            data=event.data,
            step=event.step,
        )
        if result.created:
            await self._safe_notify(result.event)
        return result

    async def notify_committed(
        self,
        event: StoredRunEvent,
        *,
        created: bool,
    ) -> None:
        if created:
            await self._safe_notify(event)

    async def _safe_notify(self, event: StoredRunEvent) -> None:
        try:
            async with asyncio.timeout(self._notify_timeout_ms / 1_000):
                await self._notifier.notify(event)
        except Exception:
            LOGGER.warning(
                "run event notification failed",
                extra={"run_id": event.run_id, "sequence": event.sequence},
            )

    def _default_event_id(self, event: RuntimeEvent, ordinal: int) -> str:
        digest = hashlib.sha256(
            f"{self._run_id}|progress|{ordinal}|{event.type}".encode("utf-8")
        ).hexdigest()
        return f"event-{digest}"


@dataclass(frozen=True)
class _ActiveRun:
    control: RuntimeControl
    task: asyncio.Task[RunRecord]


class _RuntimeStopped(RuntimeError):
    pass


class _DurableWinner(RuntimeError):
    def __init__(self, record: RunRecord) -> None:
        super().__init__("durable run already settled")
        self.record = record


class RunCoordinator:
    """Application service that arbitrates Runtime execution and durable state."""

    def __init__(
        self,
        *,
        run_store: RunStore,
        event_store: EventStore,
        runtimes: Mapping[RuntimeName | str, AgentRuntime],
        notifier: EventNotifier | None = None,
        run_timeout_ms: int = 30_000,
        notify_timeout_ms: int | None = None,
    ) -> None:
        if (
            not isinstance(run_timeout_ms, int)
            or isinstance(run_timeout_ms, bool)
            or run_timeout_ms < 1
        ):
            raise ValueError("run_timeout_ms must be a positive integer")
        self._run_store = run_store
        self._event_store = event_store
        self._runtimes = dict(runtimes)
        self._notifier = notifier or NullEventNotifier()
        self._run_timeout_ms = run_timeout_ms
        self._notify_timeout_ms = (
            min(1_000, run_timeout_ms)
            if notify_timeout_ms is None
            else notify_timeout_ms
        )
        if (
            not isinstance(self._notify_timeout_ms, int)
            or isinstance(self._notify_timeout_ms, bool)
            or self._notify_timeout_ms < 1
        ):
            raise ValueError("notify_timeout_ms must be a positive integer")
        self._active: dict[tuple[str, str], _ActiveRun] = {}
        self._active_lock = asyncio.Lock()

    async def execute(
        self,
        run_id: str,
        *,
        owner_id: str,
        execution_context: ToolExecutionContext | None = None,
    ) -> RunRecord:
        if (
            execution_context is not None
            and execution_context.principal_id != owner_id
        ):
            raise ValueError(
                "execution context principal must match the run owner"
            )
        key = (owner_id, run_id)
        async with self._active_lock:
            active = self._active.get(key)
            if active is None:
                deadline = (
                    asyncio.get_running_loop().time()
                    + self._run_timeout_ms / 1_000
                )
                control = RuntimeControl(
                    CancellationToken(timeout_ms=self._run_timeout_ms)
                )
                task = asyncio.create_task(
                    self._execute_once(
                        run_id,
                        owner_id=owner_id,
                        execution_context=execution_context,
                        control=control,
                        deadline=deadline,
                    )
                )
                active = _ActiveRun(control=control, task=task)
                self._active[key] = active
                task.add_done_callback(
                    lambda completed, run_key=key: asyncio.create_task(
                        self._remove_active(run_key, completed)
                    )
                )
        return await asyncio.shield(active.task)

    async def cancel(self, run_id: str, *, owner_id: str) -> bool:
        current = await self._run_store.get(run_id, owner_id=owner_id)
        if current is None:
            raise RunNotFoundError()
        if current.status.is_terminal:
            return False

        key = (owner_id, run_id)
        async with self._active_lock:
            active = self._active.get(key)
        active_execution = active is not None and not active.task.done()
        if active_execution:
            active.control.cancellation_token.cancel("cancelled_by_user")
        elif current.status is not RunStatus.QUEUED:
            return False

        failure = _cancelled_failure("cancelled_by_user")
        emitter = self._emitter(run_id, owner_id=owner_id)
        for _ in range(2):
            if current.status.is_terminal:
                return current.status is RunStatus.CANCELLED
            if current.status not in {RunStatus.QUEUED, RunStatus.RUNNING}:
                return False
            try:
                committed = await self._event_store.commit_terminal(
                    TerminalCommit(
                        run_id=run_id,
                        owner_id=owner_id,
                        expected_version=current.version,
                        target_status=RunStatus.CANCELLED,
                        event_id=_terminal_event_id(
                            run_id,
                            RunStatus.CANCELLED,
                        ),
                        event_data=_terminal_event_data(
                            RunStatus.CANCELLED,
                            failure=failure,
                        ),
                        failure=failure,
                    )
                )
            except ConcurrentWriteError:
                refreshed = await self._run_store.get(run_id, owner_id=owner_id)
                if refreshed is None:
                    raise RunNotFoundError()
                current = refreshed
                continue
            await emitter.notify_committed(
                committed.event,
                created=committed.created,
            )
            return True
        return current.status is RunStatus.CANCELLED

    async def _execute_once(
        self,
        run_id: str,
        *,
        owner_id: str,
        execution_context: ToolExecutionContext | None,
        control: RuntimeControl,
        deadline: float,
    ) -> RunRecord:
        current = await self._run_store.get(run_id, owner_id=owner_id)
        if current is None:
            raise RunNotFoundError()
        if current.status.is_terminal:
            return current
        if current.status is not RunStatus.QUEUED:
            raise InvalidRunTransitionError()

        emitter = self._emitter(run_id, owner_id=owner_id)
        try:
            started = await self._event_store.commit_start(
                StartCommit(
                    run_id=run_id,
                    owner_id=owner_id,
                    expected_version=current.version,
                    event_id=_lifecycle_event_id(run_id, "started"),
                    event_data={
                        "status": "running",
                        "runtime": current.runtime,
                    },
                )
            )
        except ConcurrentWriteError:
            winner = await self._run_store.get(run_id, owner_id=owner_id)
            if winner is not None and winner.status.is_terminal:
                return winner
            raise
        await emitter.notify_committed(
            started.event,
            created=started.created,
        )
        running = started.record
        if not started.created:
            if running.status.is_terminal:
                return running
            return await self._wait_for_existing_execution(
                run_id,
                owner_id=owner_id,
                deadline=deadline,
            )

        runtime = self._runtimes.get(running.runtime)
        if control.cancellation_token.is_cancelled:
            result = _cancellation_result(control.cancellation_token.reason)
        elif runtime is None:
            result = _failed_result(
                code="runtime_not_configured",
                category="configuration",
                public_message="Requested runtime is not configured",
            )
        else:
            try:
                result = await self._run_runtime(
                    runtime,
                    running,
                    execution_context=execution_context,
                    control=control,
                    emitter=emitter,
                    deadline=deadline,
                )
            except _DurableWinner as winner:
                return winner.record
        return await self._settle(running, result=result, emitter=emitter)

    async def _run_runtime(
        self,
        runtime: AgentRuntime,
        running: RunRecord,
        *,
        execution_context: ToolExecutionContext | None,
        control: RuntimeControl,
        emitter: PersistentEventEmitter,
        deadline: float,
    ) -> RuntimeResult:
        async def emit(event: RuntimeEvent) -> None:
            if control.cancellation_token.is_cancelled:
                raise _RuntimeStopped()
            await emitter.emit(event)

        try:
            remaining_seconds = deadline - asyncio.get_running_loop().time()
            if remaining_seconds <= 0:
                control.cancellation_token.cancel("deadline_exceeded")
                return _timeout_result()
            async with asyncio.timeout(remaining_seconds):
                result = await runtime.run(
                    RuntimeRequest(
                        run_id=running.id,
                        input_text=running.input_text,
                        execution_context=execution_context,
                    ),
                    emit=emit,
                    control=control,
                )
        except TimeoutError:
            control.cancellation_token.cancel("deadline_exceeded")
            return _timeout_result()
        except _RuntimeStopped:
            return _cancellation_result(control.cancellation_token.reason)
        except InvalidRunTransitionError:
            winner = await self._run_store.get(
                running.id,
                owner_id=running.owner_id,
            )
            if winner is not None and winner.status.is_terminal:
                raise _DurableWinner(winner) from None
            raise
        except StoreError:
            raise
        except asyncio.CancelledError:
            control.cancellation_token.cancel("coordinator_cancelled")
            return _cancellation_result(control.cancellation_token.reason)
        except Exception:
            return _failed_result(
                code="runtime_execution_failed",
                category="runtime",
                public_message="Runtime execution failed",
            )

        if not isinstance(result, RuntimeResult):
            return _failed_result(
                code="runtime_contract_error",
                category="runtime",
                public_message="Runtime returned an invalid result",
            )
        if control.cancellation_token.is_cancelled:
            return _cancellation_result(control.cancellation_token.reason)
        return result

    async def _wait_for_existing_execution(
        self,
        run_id: str,
        *,
        owner_id: str,
        deadline: float,
    ) -> RunRecord:
        while asyncio.get_running_loop().time() < deadline:
            current = await self._run_store.get(run_id, owner_id=owner_id)
            if current is None:
                raise RunNotFoundError()
            if current.status.is_terminal:
                return current
            await asyncio.sleep(0.01)
        raise ConcurrentWriteError()

    async def _settle(
        self,
        running: RunRecord,
        *,
        result: RuntimeResult,
        emitter: PersistentEventEmitter,
    ) -> RunRecord:
        event_data = _terminal_event_data(
            result.status,
            failure=result.failure,
        )
        command = TerminalCommit(
            run_id=running.id,
            owner_id=running.owner_id,
            expected_version=running.version,
            target_status=result.status,
            event_id=_terminal_event_id(running.id, result.status),
            event_data=event_data,
            step=0 if result.status is RunStatus.CANCELLED else result.step,
            answer=result.answer,
            failure=result.failure,
        )
        try:
            committed = await self._event_store.commit_terminal(command)
        except ConcurrentWriteError:
            winner = await self._run_store.get(
                running.id,
                owner_id=running.owner_id,
            )
            if winner is not None and winner.status.is_terminal:
                return winner
            raise
        await emitter.notify_committed(
            committed.event,
            created=committed.created,
        )
        return committed.record

    def _emitter(self, run_id: str, *, owner_id: str) -> PersistentEventEmitter:
        return PersistentEventEmitter(
            event_store=self._event_store,
            run_id=run_id,
            owner_id=owner_id,
            notifier=self._notifier,
            notify_timeout_ms=self._notify_timeout_ms,
        )

    async def _remove_active(
        self,
        key: tuple[str, str],
        completed: asyncio.Task[RunRecord],
    ) -> None:
        async with self._active_lock:
            active = self._active.get(key)
            if active is not None and active.task is completed:
                self._active.pop(key, None)


def _lifecycle_event_id(run_id: str, phase: str) -> str:
    digest = hashlib.sha256(f"{run_id}|lifecycle|{phase}".encode("utf-8")).hexdigest()
    return f"lifecycle-{digest}"


def _terminal_event_id(run_id: str, status: RunStatus) -> str:
    return _lifecycle_event_id(run_id, f"terminal:{status.value}")


def _terminal_event_data(
    status: RunStatus,
    *,
    failure: RunFailure | None,
) -> dict[str, object]:
    data: dict[str, object] = {"status": status.value}
    if failure is not None:
        data.update(
            {
                "failure_code": failure.code,
                "failure_category": failure.category,
                "retryable": failure.retryable,
            }
        )
    return data


def _failed_result(
    *,
    code: str,
    category: str,
    public_message: str,
) -> RuntimeResult:
    return RuntimeResult(
        status=RunStatus.FAILED,
        failure=RunFailure(
            code=code,
            category=category,
            public_message=public_message,
        ),
    )


def _timeout_result() -> RuntimeResult:
    return _failed_result(
        code="run_timeout",
        category="timeout",
        public_message="Run timed out",
    )


def _cancelled_failure(reason: str | None) -> RunFailure:
    return RunFailure(
        code=(
            reason
            if reason in {"cancelled_by_user", "client_disconnected"}
            else "run_cancelled"
        ),
        category="cancellation",
        public_message="Run cancelled",
    )


def _cancellation_result(reason: str | None) -> RuntimeResult:
    if reason == "deadline_exceeded":
        return _timeout_result()
    return RuntimeResult(
        status=RunStatus.CANCELLED,
        failure=_cancelled_failure(reason),
    )


__all__ = [
    "EventNotifier",
    "NullEventNotifier",
    "PersistentEventEmitter",
    "RunCoordinator",
]
