from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum
from typing import Protocol

from backend.app.agent import (
    AgentRuntime,
    ApprovalResumableRuntime,
    CancellationToken,
    RuntimeApprovalDecision,
    RuntimeApprovalPause,
    RuntimeApprovalResume,
    RuntimeCheckpointContext,
    RuntimeContextIdentity,
    RuntimeControl,
    RuntimeEvent,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.domain import Message
from backend.app.memory import MemoryTurnConflictError, PublishTurn
from backend.app.domain.run import (
    RunFailure,
    RunRecord,
    RunStatus,
    RuntimeName,
    StoredRunEvent,
)
from backend.app.stores import (
    AppendEventResult,
    AsyncMemoryStore,
    ConcurrentWriteError,
    EventStore,
    InvalidRunTransitionError,
    PauseCommit,
    ResumeCommit,
    RunLease,
    RunLeaseLostError,
    RunLeaseStore,
    RunLeaseUnavailableError,
    RunNotFoundError,
    RunStore,
    StartCommit,
    StoreError,
    TerminalCommit,
)
from backend.app.tools import (
    ApprovalResponse,
    ToolExecutionContext,
)


LOGGER = logging.getLogger(__name__)
EventIdFactory = Callable[[RuntimeEvent, int], str]
_COORDINATOR_SHUTDOWN_REASON = "coordinator_shutdown"


class RunCoordinatorState(StrEnum):
    ACCEPTING = "accepting"
    QUIESCING = "quiescing"
    QUIESCED = "quiesced"


class RunCoordinatorAdmissionError(RuntimeError):
    code = "coordinator_not_accepting"

    def __init__(self) -> None:
        super().__init__(self.code)


class EventNotifier(Protocol):
    """Live delivery hook; EventStore remains the replayable source of truth."""

    async def notify(self, event: StoredRunEvent) -> None:
        ...


class RunEventObserver(Protocol):
    """Best-effort observer of events that are already durable."""

    async def observe(
        self,
        event: StoredRunEvent,
        *,
        owner_id: str,
    ) -> None:
        ...


class NullEventNotifier(EventNotifier):
    async def notify(self, event: StoredRunEvent) -> None:
        del event


class NullRunEventObserver(RunEventObserver):
    async def observe(
        self,
        event: StoredRunEvent,
        *,
        owner_id: str,
    ) -> None:
        del event, owner_id


class PersistentEventEmitter:
    """Persist one event before making it visible to live subscribers."""

    def __init__(
        self,
        *,
        event_store: EventStore,
        run_id: str,
        owner_id: str,
        notifier: EventNotifier | None = None,
        observer: RunEventObserver | None = None,
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
        self._observer = observer or NullRunEventObserver()
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
            await self._safe_observe(result.event)
        return result

    async def notify_committed(
        self,
        event: StoredRunEvent,
        *,
        created: bool,
    ) -> None:
        if created:
            await self._safe_notify(event)
            await self._safe_observe(event)

    async def _safe_notify(self, event: StoredRunEvent) -> None:
        try:
            async with asyncio.timeout(self._notify_timeout_ms / 1_000):
                await self._notifier.notify(event)
        except Exception:
            LOGGER.warning(
                "run event notification failed",
                extra={"run_id": event.run_id, "sequence": event.sequence},
            )

    async def _safe_observe(self, event: StoredRunEvent) -> None:
        try:
            async with asyncio.timeout(self._notify_timeout_ms / 1_000):
                await self._observer.observe(
                    event,
                    owner_id=self._owner_id,
                )
        except Exception:
            LOGGER.warning(
                "run telemetry export failed",
                extra={"run_id": event.run_id, "sequence": event.sequence},
            )

    def _default_event_id(self, event: RuntimeEvent, ordinal: int) -> str:
        digest = hashlib.sha256(
            f"{self._run_id}|progress|{ordinal}|{event.type}".encode("utf-8")
        ).hexdigest()
        return f"event-{digest}"


class _RunLeaseSession:
    """Own one Coordinator reservation, heartbeat task, and release attempt."""

    def __init__(
        self,
        *,
        store: RunLeaseStore | None,
        ttl: timedelta,
        heartbeat_interval: float,
    ) -> None:
        self._store = store
        self._ttl = ttl
        self._heartbeat_interval = heartbeat_interval
        self._lease: RunLease | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._stop_event = asyncio.Event()
        self._failure_event = asyncio.Event()
        self._failure: Exception | None = None
        self._operation_lock = asyncio.Lock()
        self._released = False

    @property
    def enabled(self) -> bool:
        return self._store is not None

    async def reserve_execution(
        self,
        run_id: str,
        *,
        owner_id: str,
        expected_status: RunStatus,
    ) -> None:
        if self._store is None:
            return
        async with self._operation_lock:
            if self._released:
                raise RunLeaseLostError()
            self._lease = await self._store.reserve_execution(
                run_id,
                owner_id=owner_id,
                expected_status=expected_status,
                ttl=self._ttl,
            )

    def start_heartbeat(self) -> None:
        if self._store is None:
            return
        if self._lease is None or self._released:
            raise RunLeaseLostError()
        if self._heartbeat_task is not None:
            raise RuntimeError("run lease heartbeat already started")
        self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())

    async def wait_for_failure(self) -> Exception:
        await self._failure_event.wait()
        if self._failure is None:
            raise RuntimeError("run lease failure signal has no error")
        return self._failure

    async def stop_heartbeat(self, *, require_healthy: bool) -> None:
        self._stop_event.set()
        task = self._heartbeat_task
        if task is not None and task is not asyncio.current_task():
            await task
        if require_healthy and self._failure is not None:
            raise self._failure

    async def release_after_transition(self) -> None:
        await self.stop_heartbeat(require_healthy=False)
        async with self._operation_lock:
            if self._released:
                return
            lease = self._lease
            self._released = True
            if self._store is None or lease is None:
                return
            try:
                await self._store.release(lease)
            except StoreError as exc:
                LOGGER.warning(
                    "run lease release failed",
                    extra={"run_id": lease.run_id, "error_code": exc.code},
                )

    async def abandon(self) -> None:
        await self.stop_heartbeat(require_healthy=False)

    async def _heartbeat_loop(self) -> None:
        if self._store is None:
            return
        while True:
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),
                    timeout=self._heartbeat_interval,
                )
                return
            except TimeoutError:
                pass

            async with self._operation_lock:
                if self._released or self._lease is None:
                    return
                try:
                    self._lease = await self._store.heartbeat(
                        self._lease,
                        ttl=self._ttl,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as exc:
                    self._failure = exc
                    self._failure_event.set()
                    return


@dataclass(frozen=True)
class _ActiveRun:
    kind: str
    control: RuntimeControl
    lease_session: _RunLeaseSession
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
        memory_store: AsyncMemoryStore | None = None,
        notifier: EventNotifier | None = None,
        event_observer: RunEventObserver | None = None,
        run_timeout_ms: int = 30_000,
        notify_timeout_ms: int | None = None,
        run_lease_store: RunLeaseStore | None = None,
        lease_ttl_ms: int = 30_000,
        lease_heartbeat_interval_ms: int = 10_000,
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
        self._memory_store = memory_store
        self._notifier = notifier or NullEventNotifier()
        self._event_observer = event_observer or NullRunEventObserver()
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
        for value, label in (
            (lease_ttl_ms, "lease_ttl_ms"),
            (lease_heartbeat_interval_ms, "lease_heartbeat_interval_ms"),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
            ):
                raise ValueError(f"{label} must be a positive integer")
        if lease_ttl_ms > 86_400_000:
            raise ValueError("lease_ttl_ms must not exceed one day")
        if lease_heartbeat_interval_ms >= lease_ttl_ms:
            raise ValueError(
                "lease_heartbeat_interval_ms must be less than lease_ttl_ms"
            )
        self._run_lease_store = run_lease_store
        self._lease_ttl = timedelta(milliseconds=lease_ttl_ms)
        self._lease_heartbeat_interval = lease_heartbeat_interval_ms / 1_000
        self._active: dict[tuple[str, str], _ActiveRun] = {}
        self._active_lock = asyncio.Lock()
        self._state = RunCoordinatorState.ACCEPTING
        self._quiesce_task: asyncio.Task[None] | None = None

    @property
    def state(self) -> RunCoordinatorState:
        return self._state

    async def execute(
        self,
        run_id: str,
        *,
        owner_id: str,
        execution_context: ToolExecutionContext | None = None,
    ) -> RunRecord:
        execution_context = _bind_execution_context(
            run_id,
            owner_id=owner_id,
            execution_context=execution_context,
            bind_run=False,
        )
        key = (owner_id, run_id)
        async with self._active_lock:
            self._require_accepting()
            active = self._active.get(key)
            if active is None or active.task.done():
                deadline = (
                    asyncio.get_running_loop().time()
                    + self._run_timeout_ms / 1_000
                )
                control = RuntimeControl(
                    CancellationToken(timeout_ms=self._run_timeout_ms)
                )
                lease_session = self._new_lease_session()
                task = asyncio.create_task(
                    self._execute_once(
                        run_id,
                        owner_id=owner_id,
                        execution_context=execution_context,
                        control=control,
                        deadline=deadline,
                        lease_session=lease_session,
                    )
                )
                active = _ActiveRun(
                    kind="execute",
                    control=control,
                    lease_session=lease_session,
                    task=task,
                )
                self._active[key] = active
                task.add_done_callback(
                    lambda completed, run_key=key: asyncio.create_task(
                        self._remove_active(run_key, completed)
                    )
                )
        return await asyncio.shield(active.task)

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
        bound_context = _bind_execution_context(
            run_id,
            owner_id=owner_id,
            execution_context=execution_context,
        )
        if bound_context is None or bound_context.approval_store is None:
            raise ValueError("approval store is required to resume a run")

        key = (owner_id, run_id)
        while True:
            finishing_execute: asyncio.Task[RunRecord] | None = None
            async with self._active_lock:
                self._require_accepting()
                active = self._active.get(key)
                if (
                    active is not None
                    and not active.task.done()
                    and active.kind == "execute"
                ):
                    finishing_execute = active.task
                elif active is None or active.task.done():
                    deadline = (
                        asyncio.get_running_loop().time()
                        + self._run_timeout_ms / 1_000
                    )
                    control = RuntimeControl(
                        CancellationToken(timeout_ms=self._run_timeout_ms)
                    )
                    lease_session = self._new_lease_session()
                    task = asyncio.create_task(
                        self._resume_once(
                            run_id,
                            owner_id=owner_id,
                            approval_id=approval_id,
                            tool_call_id=tool_call_id,
                            tool_name=tool_name,
                            arguments_digest=arguments_digest,
                            decision=decision,
                            execution_context=bound_context,
                            control=control,
                            deadline=deadline,
                            lease_session=lease_session,
                        )
                    )
                    active = _ActiveRun(
                        kind="resume",
                        control=control,
                        lease_session=lease_session,
                        task=task,
                    )
                    self._active[key] = active
                    task.add_done_callback(
                        lambda completed, run_key=key: asyncio.create_task(
                            self._remove_active(run_key, completed)
                        )
                    )
            if finishing_execute is not None:
                await asyncio.shield(finishing_execute)
                continue
            return await asyncio.shield(active.task)

    async def quiesce(self, *, timeout_ms: int = 5_000) -> None:
        if (
            not isinstance(timeout_ms, int)
            or isinstance(timeout_ms, bool)
            or timeout_ms < 1
        ):
            raise ValueError("timeout_ms must be a positive integer")

        operation = asyncio.create_task(
            self._begin_quiesce(timeout_ms),
            name="run-coordinator-quiesce-request",
        )
        try:
            await asyncio.shield(operation)
        except asyncio.CancelledError:
            await operation
            raise

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
            await active.lease_session.stop_heartbeat(require_healthy=False)
        elif current.status not in {
            RunStatus.QUEUED,
            RunStatus.WAITING_APPROVAL,
        }:
            return False

        failure = _cancelled_failure("cancelled_by_user")
        emitter = self._emitter(run_id, owner_id=owner_id)
        for _ in range(2):
            if current.status.is_terminal:
                if active_execution:
                    await active.lease_session.release_after_transition()
                return current.status is RunStatus.CANCELLED
            if current.status not in {
                RunStatus.QUEUED,
                RunStatus.RUNNING,
                RunStatus.WAITING_APPROVAL,
            }:
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
            if active_execution:
                await active.lease_session.release_after_transition()
            await emitter.notify_committed(
                committed.event,
                created=committed.created,
            )
            return True
        if active_execution and current.status.is_terminal:
            await active.lease_session.release_after_transition()
        return current.status is RunStatus.CANCELLED

    async def _execute_once(
        self,
        run_id: str,
        *,
        owner_id: str,
        execution_context: ToolExecutionContext | None,
        control: RuntimeControl,
        deadline: float,
        lease_session: _RunLeaseSession,
    ) -> RunRecord:
        current = await self._run_store.get(run_id, owner_id=owner_id)
        if current is None:
            raise RunNotFoundError()
        if current.status.is_terminal:
            await self._publish_completed_turn(current)
            return current
        if lease_session.enabled and current.status in {
            RunStatus.RUNNING,
            RunStatus.WAITING_APPROVAL,
        }:
            return await self._wait_for_existing_execution(
                run_id,
                owner_id=owner_id,
                deadline=deadline,
            )
        if current.status is not RunStatus.QUEUED:
            raise InvalidRunTransitionError()

        try:
            await lease_session.reserve_execution(
                run_id,
                owner_id=owner_id,
                expected_status=RunStatus.QUEUED,
            )
        except (RunLeaseUnavailableError, RunLeaseLostError):
            return await self._wait_for_existing_execution(
                run_id,
                owner_id=owner_id,
                deadline=deadline,
            )
        except InvalidRunTransitionError:
            winner = await self._run_store.get(run_id, owner_id=owner_id)
            if winner is not None and (
                winner.status.is_terminal
                or winner.status in {RunStatus.RUNNING, RunStatus.WAITING_APPROVAL}
            ):
                return await self._wait_for_existing_execution(
                    run_id,
                    owner_id=owner_id,
                    deadline=deadline,
                )
            raise

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
            await lease_session.release_after_transition()
            winner = await self._run_store.get(run_id, owner_id=owner_id)
            if winner is not None and (
                winner.status.is_terminal
                or winner.status in {RunStatus.RUNNING, RunStatus.WAITING_APPROVAL}
            ):
                return await self._wait_for_existing_execution(
                    run_id,
                    owner_id=owner_id,
                    deadline=deadline,
                )
            raise
        except (StoreError, asyncio.CancelledError):
            await lease_session.abandon()
            raise
        except Exception:
            await lease_session.release_after_transition()
            raise

        running = started.record
        if not started.created:
            await lease_session.release_after_transition()
            if running.status.is_terminal:
                return running
            return await self._wait_for_existing_execution(
                run_id,
                owner_id=owner_id,
                deadline=deadline,
            )

        runtime = self._runtimes.get(running.runtime)
        return await self._drive_running(
            runtime,
            running,
            execution_context=execution_context,
            control=control,
            emitter=emitter,
            deadline=deadline,
            lease_session=lease_session,
            lifecycle_event=started.event,
            lifecycle_created=started.created,
        )

    async def _resume_once(
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
        control: RuntimeControl,
        deadline: float,
        lease_session: _RunLeaseSession,
    ) -> RunRecord:
        current = await self._run_store.get(run_id, owner_id=owner_id)
        if current is None:
            raise RunNotFoundError()
        if current.status.is_terminal:
            await self._publish_completed_turn(current)
            return current
        if current.status is RunStatus.RUNNING:
            return await self._wait_for_terminal(
                run_id,
                owner_id=owner_id,
                deadline=deadline,
            )
        if current.status is not RunStatus.WAITING_APPROVAL:
            raise InvalidRunTransitionError()

        runtime = self._runtimes.get(current.runtime)
        emitter = self._emitter(run_id, owner_id=owner_id)
        if runtime is None or not isinstance(runtime, ApprovalResumableRuntime):
            return await self._settle(
                current,
                result=_failed_result(
                    code="runtime_resume_not_supported",
                    category="configuration",
                    public_message="Requested runtime cannot resume approvals",
                ),
                emitter=emitter,
            )

        try:
            await lease_session.reserve_execution(
                run_id,
                owner_id=owner_id,
                expected_status=RunStatus.WAITING_APPROVAL,
            )
        except (RunLeaseUnavailableError, RunLeaseLostError):
            return await self._wait_for_resumed_execution(
                run_id,
                owner_id=owner_id,
                initial_version=current.version,
                deadline=deadline,
            )
        except InvalidRunTransitionError:
            winner = await self._run_store.get(run_id, owner_id=owner_id)
            if winner is None:
                raise RunNotFoundError()
            if winner.status.is_terminal:
                return winner
            if winner.status is RunStatus.RUNNING:
                return await self._wait_for_terminal(
                    run_id,
                    owner_id=owner_id,
                    deadline=deadline,
                )
            if (
                winner.status is RunStatus.WAITING_APPROVAL
                and winner.version != current.version
            ):
                return winner
            raise

        try:
            resolution = execution_context.approval_store.resolve(
                approval_id=approval_id,
                run_id=run_id,
                principal_id=owner_id,
                tool_call_id=tool_call_id,
                tool_name=tool_name,
                arguments_digest=arguments_digest,
                decision=decision,
            )
        except Exception:
            await lease_session.release_after_transition()
            raise
        approval = RuntimeApprovalResume(
            approval_id=resolution.request.id,
            tool_call_id=resolution.request.tool_call_id,
            tool_name=resolution.request.tool_name,
            arguments_digest=resolution.request.arguments_digest,
            decision=RuntimeApprovalDecision(resolution.status.value),
        )
        try:
            resumed = await self._event_store.commit_resume(
                ResumeCommit(
                    run_id=run_id,
                    owner_id=owner_id,
                    expected_version=current.version,
                    event_id=_lifecycle_event_id(
                        run_id,
                        f"resumed:{approval.approval_id}",
                    ),
                    event_data={
                        "status": RunStatus.RUNNING.value,
                        "approval_id": approval.approval_id,
                        "decision": approval.decision.value,
                    },
                    step=1,
                )
            )
        except ConcurrentWriteError:
            await lease_session.release_after_transition()
            winner = await self._run_store.get(run_id, owner_id=owner_id)
            if winner is None:
                raise RunNotFoundError()
            if winner.status.is_terminal:
                return winner
            if winner.status is RunStatus.RUNNING:
                return await self._wait_for_terminal(
                    run_id,
                    owner_id=owner_id,
                    deadline=deadline,
                )
            if (
                winner.status is RunStatus.WAITING_APPROVAL
                and winner.version != current.version
            ):
                return winner
            raise
        except (StoreError, asyncio.CancelledError):
            await lease_session.abandon()
            raise
        except Exception:
            await lease_session.release_after_transition()
            raise

        if not resumed.created:
            await lease_session.release_after_transition()
            if resumed.record.status.is_terminal:
                return resumed.record
            return await self._wait_for_resumed_execution(
                run_id,
                owner_id=owner_id,
                initial_version=current.version,
                deadline=deadline,
            )

        return await self._drive_running(
            runtime,
            resumed.record,
            execution_context=execution_context,
            control=control,
            emitter=emitter,
            deadline=deadline,
            lease_session=lease_session,
            lifecycle_event=resumed.event,
            lifecycle_created=resumed.created,
            approval=approval,
        )

    async def _drive_running(
        self,
        runtime: AgentRuntime | None,
        running: RunRecord,
        *,
        execution_context: ToolExecutionContext | None,
        control: RuntimeControl,
        emitter: PersistentEventEmitter,
        deadline: float,
        lease_session: _RunLeaseSession,
        lifecycle_event: StoredRunEvent,
        lifecycle_created: bool,
        approval: RuntimeApprovalResume | None = None,
    ) -> RunRecord:
        lease_session.start_heartbeat()
        try:
            await emitter.notify_committed(
                lifecycle_event,
                created=lifecycle_created,
            )
            if _is_coordinator_shutdown(control):
                raise asyncio.CancelledError()
            if control.cancellation_token.is_cancelled:
                result: RuntimeResult | RuntimeApprovalPause = _cancellation_result(
                    control.cancellation_token.reason
                )
            elif runtime is None:
                result = _failed_result(
                    code="runtime_not_configured",
                    category="configuration",
                    public_message="Requested runtime is not configured",
                )
            else:
                result = await self._run_runtime(
                    runtime,
                    running,
                    execution_context=execution_context,
                    control=control,
                    emitter=emitter,
                    deadline=deadline,
                    lease_session=lease_session,
                    approval=approval,
                )
            await lease_session.stop_heartbeat(require_healthy=True)
            if isinstance(result, RuntimeApprovalPause):
                record = await self._pause(
                    running,
                    pause=result,
                    emitter=emitter,
                )
            else:
                record = await self._settle(
                    running,
                    result=result,
                    emitter=emitter,
                )
        except _DurableWinner as winner:
            await lease_session.release_after_transition()
            return winner.record
        except BaseException:
            await lease_session.abandon()
            raise

        await lease_session.release_after_transition()
        return record

    async def _run_runtime(
        self,
        runtime: AgentRuntime,
        running: RunRecord,
        *,
        execution_context: ToolExecutionContext | None,
        control: RuntimeControl,
        emitter: PersistentEventEmitter,
        deadline: float,
        lease_session: _RunLeaseSession,
        approval: RuntimeApprovalResume | None = None,
    ) -> RuntimeResult | RuntimeApprovalPause:
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
                runtime_request = RuntimeRequest(
                    run_id=running.id,
                    input_text=running.input_text,
                    execution_context=(
                        execution_context.for_run(running.id)
                        if execution_context is not None
                        and isinstance(runtime, ApprovalResumableRuntime)
                        else execution_context
                    ),
                    checkpoint_context=RuntimeCheckpointContext.for_run(
                        run_id=running.id,
                        owner_id=running.owner_id,
                    ),
                    context_identity=RuntimeContextIdentity(
                        owner_id=running.owner_id,
                        session_id=running.session_id,
                    ),
                )
                if approval is None:
                    invocation = runtime.run(
                        runtime_request, emit=emit, control=control
                    )
                else:
                    if not isinstance(runtime, ApprovalResumableRuntime):
                        return _failed_result(
                            code="runtime_resume_not_supported",
                            category="configuration",
                            public_message="Requested runtime cannot resume approvals",
                        )
                    invocation = runtime.resume(
                        runtime_request,
                        approval=approval,
                        emit=emit,
                        control=control,
                    )
                result = await self._await_runtime_with_lease(
                    invocation,
                    running=running,
                    control=control,
                    lease_session=lease_session,
                )
        except TimeoutError:
            control.cancellation_token.cancel("deadline_exceeded")
            return _timeout_result()
        except _RuntimeStopped:
            if _is_coordinator_shutdown(control):
                raise asyncio.CancelledError() from None
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
            if _is_coordinator_shutdown(control):
                raise
            control.cancellation_token.cancel("coordinator_cancelled")
            return _cancellation_result(control.cancellation_token.reason)
        except Exception:
            return _failed_result(
                code="runtime_execution_failed",
                category="runtime",
                public_message="Runtime execution failed",
            )

        if not isinstance(result, (RuntimeResult, RuntimeApprovalPause)):
            return _failed_result(
                code="runtime_contract_error",
                category="runtime",
                public_message="Runtime returned an invalid result",
            )
        if _is_coordinator_shutdown(control):
            raise asyncio.CancelledError()
        if control.cancellation_token.is_cancelled:
            return _cancellation_result(control.cancellation_token.reason)
        return result

    async def _await_runtime_with_lease(
        self,
        invocation: Awaitable[RuntimeResult | RuntimeApprovalPause],
        *,
        running: RunRecord,
        control: RuntimeControl,
        lease_session: _RunLeaseSession,
    ) -> RuntimeResult | RuntimeApprovalPause:
        if not lease_session.enabled:
            return await invocation

        runtime_task = asyncio.create_task(invocation)
        failure_task = asyncio.create_task(lease_session.wait_for_failure())
        try:
            completed, _ = await asyncio.wait(
                {runtime_task, failure_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if failure_task in completed:
                failure = failure_task.result()
                control.cancellation_token.cancel("run_lease_lost")
                runtime_task.cancel()
                await asyncio.gather(runtime_task, return_exceptions=True)
                winner = await self._run_store.get(
                    running.id,
                    owner_id=running.owner_id,
                )
                if winner is not None and (
                    winner.status.is_terminal
                    or winner.status is RunStatus.WAITING_APPROVAL
                ):
                    raise _DurableWinner(winner)
                raise failure
            return await runtime_task
        except asyncio.CancelledError:
            runtime_task.cancel()
            await asyncio.gather(runtime_task, return_exceptions=True)
            raise
        finally:
            failure_task.cancel()
            await asyncio.gather(failure_task, return_exceptions=True)

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
            if current.status.is_terminal or current.status is RunStatus.WAITING_APPROVAL:
                return current
            await asyncio.sleep(0.01)
        raise ConcurrentWriteError()

    async def _wait_for_terminal(
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

    async def _wait_for_resumed_execution(
        self,
        run_id: str,
        *,
        owner_id: str,
        initial_version: int,
        deadline: float,
    ) -> RunRecord:
        while asyncio.get_running_loop().time() < deadline:
            current = await self._run_store.get(run_id, owner_id=owner_id)
            if current is None:
                raise RunNotFoundError()
            if current.status.is_terminal:
                return current
            if (
                current.status is RunStatus.WAITING_APPROVAL
                and current.version != initial_version
            ):
                return current
            await asyncio.sleep(0.01)
        raise ConcurrentWriteError()

    async def _pause(
        self,
        running: RunRecord,
        *,
        pause: RuntimeApprovalPause,
        emitter: PersistentEventEmitter,
    ) -> RunRecord:
        event_data: dict[str, object] = {
            "status": RunStatus.WAITING_APPROVAL.value,
            "approval_id": pause.approval_id,
            "tool_call_id": pause.tool_call_id,
            "tool_name": pause.tool_name,
            "arguments_digest": pause.arguments_digest,
            "expires_at": (
                pause.expires_at.isoformat()
                if pause.expires_at is not None
                else None
            ),
        }
        try:
            committed = await self._event_store.commit_pause(
                PauseCommit(
                    run_id=running.id,
                    owner_id=running.owner_id,
                    expected_version=running.version,
                    event_id=_lifecycle_event_id(
                        running.id,
                        f"waiting:{pause.approval_id}",
                    ),
                    event_data=event_data,
                    step=pause.step,
                )
            )
        except ConcurrentWriteError:
            winner = await self._run_store.get(
                running.id,
                owner_id=running.owner_id,
            )
            if winner is not None and (
                winner.status.is_terminal
                or winner.status is RunStatus.WAITING_APPROVAL
            ):
                return winner
            raise
        await emitter.notify_committed(
            committed.event,
            created=committed.created,
        )
        return committed.record

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
        if committed.created and result.status is RunStatus.COMPLETED:
            await self._publish_completed_turn(committed.record)
        await emitter.notify_committed(
            committed.event,
            created=committed.created,
        )
        return committed.record

    async def _publish_completed_turn(self, record: RunRecord) -> None:
        if self._memory_store is None:
            return
        publication = asyncio.create_task(
            self._append_completed_turn(record),
            name=f"run-memory-publication-{record.id}",
        )
        try:
            await asyncio.shield(publication)
        except asyncio.CancelledError:
            await publication

    async def _append_completed_turn(self, record: RunRecord) -> None:
        if self._memory_store is None:
            return
        try:
            answer = record.answer
            if answer is None:
                raise ValueError("completed run is missing its answer")
            await self._memory_store.publish_turn(
                PublishTurn(
                    run_id=record.id,
                    session_id=record.session_id,
                    user_message=Message(
                        role="user",
                        content=record.input_text,
                    ),
                    assistant_message=Message(
                        role="assistant",
                        content=answer,
                    ),
                )
            )
        except asyncio.CancelledError:
            LOGGER.warning(
                "run memory publication cancelled",
                extra={
                    "run_id": record.id,
                    "error_code": "memory_write_cancelled",
                },
            )
        except (MemoryTurnConflictError, StoreError) as exc:
            LOGGER.warning(
                "run memory publication failed",
                extra={
                    "run_id": record.id,
                    "error_code": exc.code,
                    "result_unknown": bool(
                        getattr(exc, "result_unknown", False)
                    ),
                },
            )
        except Exception:
            LOGGER.error(
                "run memory publication failed",
                extra={
                    "run_id": record.id,
                    "error_code": "memory_write_failed",
                },
            )

    def _emitter(self, run_id: str, *, owner_id: str) -> PersistentEventEmitter:
        return PersistentEventEmitter(
            event_store=self._event_store,
            run_id=run_id,
            owner_id=owner_id,
            notifier=self._notifier,
            observer=self._event_observer,
            notify_timeout_ms=self._notify_timeout_ms,
        )

    def _new_lease_session(self) -> _RunLeaseSession:
        return _RunLeaseSession(
            store=self._run_lease_store,
            ttl=self._lease_ttl,
            heartbeat_interval=self._lease_heartbeat_interval,
        )

    def _require_accepting(self) -> None:
        if self._state is not RunCoordinatorState.ACCEPTING:
            raise RunCoordinatorAdmissionError()

    async def _begin_quiesce(self, timeout_ms: int) -> None:
        async with self._active_lock:
            if self._state is RunCoordinatorState.QUIESCED:
                return
            if self._state is RunCoordinatorState.ACCEPTING:
                self._state = RunCoordinatorState.QUIESCING
                self._quiesce_task = asyncio.create_task(
                    self._drain_active(timeout_ms),
                    name="run-coordinator-quiesce",
                )
            task = self._quiesce_task
        if task is None:
            raise RuntimeError("coordinator quiesce task is missing")
        await task

    async def _drain_active(self, timeout_ms: int) -> None:
        async with self._active_lock:
            active_runs = tuple(
                active for active in self._active.values() if not active.task.done()
            )
        tasks = {active.task for active in active_runs}
        pending: set[asyncio.Task[RunRecord]] = set()
        if tasks:
            _, pending = await asyncio.wait(
                tasks,
                timeout=timeout_ms / 1_000,
            )
        if pending:
            async with self._active_lock:
                forced = tuple(
                    active
                    for active in self._active.values()
                    if active.task in pending and not active.task.done()
                )
                for active in forced:
                    active.control.cancellation_token.cancel(
                        _COORDINATOR_SHUTDOWN_REASON
                    )
                    active.task.cancel()
        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )
        async with self._active_lock:
            self._state = RunCoordinatorState.QUIESCED

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


def _bind_execution_context(
    run_id: str,
    *,
    owner_id: str,
    execution_context: ToolExecutionContext | None,
    bind_run: bool = True,
) -> ToolExecutionContext | None:
    if execution_context is None:
        return None
    if execution_context.principal_id != owner_id:
        raise ValueError("execution context principal must match the run owner")
    if execution_context.run_id not in {None, run_id}:
        raise ValueError("execution context run_id does not match")
    return execution_context.for_run(run_id) if bind_run else execution_context


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


def _is_coordinator_shutdown(control: RuntimeControl) -> bool:
    return (
        control.cancellation_token.reason
        == _COORDINATOR_SHUTDOWN_REASON
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
    "RunCoordinatorAdmissionError",
    "RunCoordinatorState",
]
