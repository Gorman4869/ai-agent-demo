from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import timedelta
from enum import StrEnum

from backend.app.domain.run import (
    RunFailure,
    RunRecord,
    RunStatus,
    ToolExecutionStatus,
)
from backend.app.stores import (
    ConcurrentWriteError,
    EventStore,
    RunLease,
    RunLeaseStore,
    RunNotFoundError,
    RunStore,
    StoreError,
    TerminalCommit,
    ToolExecutionNotFoundError,
    ToolExecutionStore,
)


class RunRecoveryStatus(StrEnum):
    RECOVERED = "recovered"
    ALREADY_TERMINAL = "already_terminal"
    NOT_RUNNING = "not_running"
    FAILED = "failed"


@dataclass(frozen=True)
class RunRecoveryResult:
    run_id: str
    status: RunRecoveryStatus
    unknown_tool_count: int = 0
    cancelled_tool_count: int = 0
    error_code: str | None = None


class RunRecoveryService:
    """Claim expired leases and converge orphaned Runs to safe terminal state."""

    def __init__(
        self,
        *,
        run_store: RunStore,
        event_store: EventStore,
        tool_execution_store: ToolExecutionStore,
        run_lease_store: RunLeaseStore,
    ) -> None:
        self._run_store = run_store
        self._event_store = event_store
        self._tool_execution_store = tool_execution_store
        self._run_lease_store = run_lease_store

    async def scan_once(
        self,
        *,
        limit: int = 25,
        recovery_ttl: timedelta = timedelta(seconds=30),
    ) -> tuple[RunRecoveryResult, ...]:
        leases = await self._run_lease_store.claim_expired(
            limit=limit,
            ttl=recovery_ttl,
        )
        results: list[RunRecoveryResult] = []
        for lease in leases:
            try:
                results.append(await self._recover(lease))
            except StoreError as exc:
                results.append(
                    RunRecoveryResult(
                        run_id=lease.run_id,
                        status=RunRecoveryStatus.FAILED,
                        error_code=exc.code,
                    )
                )
        return tuple(results)

    async def _recover(self, lease: RunLease) -> RunRecoveryResult:
        run = await self._run_store.get(
            lease.run_id,
            owner_id=lease.owner_id,
        )
        if run is None:
            raise RunNotFoundError()
        if run.status.is_terminal:
            await self._run_lease_store.release(lease)
            return RunRecoveryResult(
                run_id=run.id,
                status=RunRecoveryStatus.ALREADY_TERMINAL,
            )
        if run.status is not RunStatus.RUNNING:
            await self._run_lease_store.release(lease)
            return RunRecoveryResult(
                run_id=run.id,
                status=RunRecoveryStatus.NOT_RUNNING,
            )

        unknown_count, cancelled_count = await self._settle_tools(run)
        current = await self._run_store.get(run.id, owner_id=run.owner_id)
        if current is None:
            raise RunNotFoundError()
        if current.status.is_terminal:
            await self._run_lease_store.release(lease)
            return RunRecoveryResult(
                run_id=current.id,
                status=RunRecoveryStatus.ALREADY_TERMINAL,
                unknown_tool_count=unknown_count,
                cancelled_tool_count=cancelled_count,
            )
        if current.status is not RunStatus.RUNNING:
            await self._run_lease_store.release(lease)
            return RunRecoveryResult(
                run_id=current.id,
                status=RunRecoveryStatus.NOT_RUNNING,
                unknown_tool_count=unknown_count,
                cancelled_tool_count=cancelled_count,
            )

        failure = RunFailure(
            code="run_orphaned",
            category="recovery",
            public_message="Run stopped because its execution lease expired",
            retryable=False,
        )
        try:
            committed = await self._event_store.commit_terminal(
                TerminalCommit(
                    run_id=current.id,
                    owner_id=current.owner_id,
                    expected_version=current.version,
                    target_status=RunStatus.FAILED,
                    event_id=_recovery_event_id(current.id),
                    event_data={
                        "status": RunStatus.FAILED.value,
                        "failure_code": failure.code,
                        "failure_category": failure.category,
                        "retryable": failure.retryable,
                    },
                    failure=failure,
                )
            )
        except ConcurrentWriteError:
            winner = await self._run_store.get(
                current.id,
                owner_id=current.owner_id,
            )
            if winner is None:
                raise RunNotFoundError()
            if not winner.status.is_terminal:
                raise
            await self._run_lease_store.release(lease)
            return RunRecoveryResult(
                run_id=winner.id,
                status=RunRecoveryStatus.ALREADY_TERMINAL,
                unknown_tool_count=unknown_count,
                cancelled_tool_count=cancelled_count,
            )

        await self._run_lease_store.release(lease)
        return RunRecoveryResult(
            run_id=committed.record.id,
            status=RunRecoveryStatus.RECOVERED,
            unknown_tool_count=unknown_count,
            cancelled_tool_count=cancelled_count,
        )

    async def _settle_tools(self, run: RunRecord) -> tuple[int, int]:
        unknown_count = 0
        cancelled_count = 0
        executions = await self._tool_execution_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )
        for execution in executions:
            if execution.status is ToolExecutionStatus.RUNNING:
                target = ToolExecutionStatus.UNKNOWN
                error_code = "tool_result_unknown"
                public_message = "Tool result could not be confirmed"
            elif execution.status in {
                ToolExecutionStatus.PENDING,
                ToolExecutionStatus.WAITING_APPROVAL,
            }:
                target = ToolExecutionStatus.CANCELLED
                error_code = "run_orphaned"
                public_message = "Tool execution stopped with its Run"
            else:
                continue
            try:
                settled = await self._tool_execution_store.transition(
                    execution.id,
                    owner_id=run.owner_id,
                    expected_version=execution.version,
                    target_status=target,
                    error_code=error_code,
                    public_message=public_message,
                )
            except ConcurrentWriteError:
                settled = await self._tool_execution_store.get(
                    execution.id,
                    owner_id=run.owner_id,
                )
                if settled is None:
                    raise ToolExecutionNotFoundError()
                if not settled.status.is_terminal:
                    raise
            if settled.status is ToolExecutionStatus.UNKNOWN:
                unknown_count += 1
            elif settled.status is ToolExecutionStatus.CANCELLED:
                cancelled_count += 1
        return unknown_count, cancelled_count


def _recovery_event_id(run_id: str) -> str:
    digest = hashlib.sha256(
        f"{run_id}|recovery|orphaned".encode("utf-8")
    ).hexdigest()
    return f"recovery-{digest}"


__all__ = [
    "RunRecoveryResult",
    "RunRecoveryService",
    "RunRecoveryStatus",
]
