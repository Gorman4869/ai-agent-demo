from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import sys
from datetime import UTC, datetime, timedelta

from backend.app.domain import RunRecord, RunStatus, ToolExecution
from backend.app.domain.run import ToolExecutionStatus
from backend.app.services.run_recovery import (
    RunRecoveryService,
    RunRecoveryStatus,
)
from backend.app.stores import StartCommit
from backend.app.stores.postgres import PostgresPersistence


_RUN_ID = "m11-recovery-process-run"
_OWNER_ID = "m11-recovery-process-owner"
_RUNNING_EXECUTION_ID = "m11-recovery-running-tool"
_PENDING_EXECUTION_ID = "m11-recovery-pending-tool"


async def _run_probe(phase: str) -> None:
    conninfo = os.environ.get("AI_AGENT_POSTGRES_DSN", "")
    persistence = await PostgresPersistence.open(conninfo)
    try:
        await persistence.setup()
        if phase == "prepare-crash":
            await _prepare(persistence)
            print(
                json.dumps(
                    {
                        "phase": phase,
                        "process_id": os.getpid(),
                        "lease_created": True,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            os._exit(17)
        if phase == "scan":
            output = await _scan(persistence)
        else:
            output = await _audit(persistence)
        print(json.dumps(output, sort_keys=True))
    finally:
        await persistence.close()


async def _prepare(persistence: PostgresPersistence) -> None:
    now = datetime.now(UTC)
    run = RunRecord.create(
        run_id=_RUN_ID,
        session_id="m11-recovery-process-session",
        owner_id=_OWNER_ID,
        runtime="manual",
        input_text="private orphan recovery process probe",
        idempotency_key="private-recovery-run-key",
        created_at=now,
    )
    await persistence.run_store.create(run)
    running_run = (
        await persistence.event_store.commit_start(
            StartCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=run.version,
                event_id="m11-recovery-process-started",
                event_data={"status": "running", "runtime": "manual"},
            )
        )
    ).record
    running = ToolExecution.create(
        execution_id=_RUNNING_EXECUTION_ID,
        run_id=running_run.id,
        tool_call_id="m11-recovery-running-call",
        tool_name="publish_report",
        arguments={"document_id": "private-running-document"},
        side_effecting=True,
        idempotency_key="private-running-tool-key",
        created_at=now,
    )
    pending = ToolExecution.create(
        execution_id=_PENDING_EXECUTION_ID,
        run_id=running_run.id,
        tool_call_id="m11-recovery-pending-call",
        tool_name="publish_report",
        arguments={"document_id": "private-pending-document"},
        side_effecting=True,
        idempotency_key="private-pending-tool-key",
        created_at=now,
    )
    await persistence.tool_execution_store.create(
        running,
        owner_id=_OWNER_ID,
    )
    await persistence.tool_execution_store.create(
        pending,
        owner_id=_OWNER_ID,
    )
    await persistence.tool_execution_store.transition(
        running.id,
        owner_id=_OWNER_ID,
        expected_version=running.version,
        target_status=ToolExecutionStatus.RUNNING,
    )
    await persistence.run_lease_store.acquire(
        running_run.id,
        owner_id=_OWNER_ID,
        ttl=timedelta(milliseconds=300),
    )


async def _scan(persistence: PostgresPersistence) -> dict[str, object]:
    service = RunRecoveryService(
        run_store=persistence.run_store,
        event_store=persistence.event_store,
        tool_execution_store=persistence.tool_execution_store,
        run_lease_store=persistence.run_lease_store,
    )
    results = await service.scan_once(
        limit=1,
        recovery_ttl=timedelta(seconds=10),
    )
    if results and results[0].status is not RunRecoveryStatus.RECOVERED:
        raise RuntimeError("recovery_probe_scan_failed")
    return {
        "phase": "scan",
        "process_id": os.getpid(),
        "recovered_count": len(results),
    }


async def _audit(persistence: PostgresPersistence) -> dict[str, object]:
    run = await persistence.run_store.get(_RUN_ID, owner_id=_OWNER_ID)
    executions = await persistence.tool_execution_store.list_for_run(
        _RUN_ID,
        owner_id=_OWNER_ID,
    )
    events = await persistence.event_store.list_for_run(
        _RUN_ID,
        owner_id=_OWNER_ID,
    )
    async with persistence.pool.connection() as connection:
        result = await connection.execute(
            "SELECT COUNT(*) AS count FROM agent_run_leases WHERE run_id = %s",
            (_RUN_ID,),
        )
        row = await result.fetchone()
    statuses = {item.id: item.status for item in executions}
    return {
        "phase": "audit",
        "process_id": os.getpid(),
        "run_failed": (
            run is not None
            and run.status is RunStatus.FAILED
            and run.failure is not None
            and run.failure.code == "run_orphaned"
        ),
        "running_tool_unknown": (
            statuses.get(_RUNNING_EXECUTION_ID) is ToolExecutionStatus.UNKNOWN
        ),
        "pending_tool_cancelled": (
            statuses.get(_PENDING_EXECUTION_ID)
            is ToolExecutionStatus.CANCELLED
        ),
        "single_recovery_event": (
            sum(event.type == "run.failed" for event in events) == 1
        ),
        "lease_released": row is not None and row["count"] == 0,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("prepare-crash", "scan", "audit"),
        required=True,
    )
    return parser.parse_args()


def main() -> None:
    coroutine = _run_probe(_arguments().phase)
    if sys.platform == "win32":
        asyncio.run(
            coroutine,
            loop_factory=lambda: asyncio.SelectorEventLoop(
                selectors.SelectSelector()
            ),
        )
    else:
        asyncio.run(coroutine)


if __name__ == "__main__":
    main()
