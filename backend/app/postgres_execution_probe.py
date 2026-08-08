from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import sys
from datetime import UTC, datetime, timedelta

from backend.app.domain.run import RunRecord, RunStatus
from backend.app.postgres_execution import PostgresExecutionComposition


_RUN_ID = "m11-execution-composition-run"
_OWNER_ID = "m11-execution-composition-owner"


class _BlockingRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def run(self, request, *, emit, control):
        del request, emit, control
        self.started.set()
        await asyncio.Future()


async def _run_probe(phase: str) -> None:
    conninfo = os.environ.get("AI_AGENT_POSTGRES_DSN", "")
    runtime = _BlockingRuntime()
    composition = await PostgresExecutionComposition.open(
        conninfo,
        runtimes={"manual": runtime},
        run_timeout_ms=10_000,
        lease_ttl_ms=300,
        lease_heartbeat_interval_ms=100,
        recovery_scan_interval=(
            timedelta(seconds=30)
            if phase == "holder-crash"
            else timedelta(milliseconds=20)
        ),
        recovery_scan_limit=1,
        recovery_ttl=timedelta(milliseconds=300),
    )
    if phase == "holder-crash":
        execution = await _prepare_crashed_holder(composition, runtime)
        print(
            json.dumps(
                {
                    "phase": phase,
                    "process_id": os.getpid(),
                    "runtime_started": True,
                },
                sort_keys=True,
            ),
            flush=True,
        )
        if execution.done():
            raise RuntimeError("composition_holder_stopped_early")
        os._exit(17)

    try:
        output = await _wait_for_recovery(composition)
        print(json.dumps(output, sort_keys=True))
    finally:
        await composition.close()


async def _prepare_crashed_holder(
    composition: PostgresExecutionComposition,
    runtime: _BlockingRuntime,
) -> asyncio.Task[RunRecord]:
    now = datetime.now(UTC)
    run = RunRecord.create(
        run_id=_RUN_ID,
        session_id="m11-execution-composition-session",
        owner_id=_OWNER_ID,
        runtime="manual",
        input_text="private composition recovery input",
        idempotency_key="private-composition-recovery-key",
        created_at=now,
    )
    await composition.persistence.run_store.create(run)
    execution = asyncio.create_task(
        composition.coordinator.execute(run.id, owner_id=run.owner_id),
        name="composition-holder-execution",
    )
    await asyncio.wait_for(runtime.started.wait(), timeout=3)
    stored = await composition.persistence.run_store.get(
        run.id,
        owner_id=run.owner_id,
    )
    if stored is None or stored.status is not RunStatus.RUNNING:
        raise RuntimeError("composition_holder_not_running")
    return execution


async def _wait_for_recovery(
    composition: PostgresExecutionComposition,
) -> dict[str, object]:
    deadline = asyncio.get_running_loop().time() + 3
    while asyncio.get_running_loop().time() < deadline:
        run = await composition.persistence.run_store.get(
            _RUN_ID,
            owner_id=_OWNER_ID,
        )
        if (
            run is not None
            and run.status is RunStatus.FAILED
            and run.failure is not None
            and run.failure.code == "run_orphaned"
        ):
            events = await composition.persistence.event_store.list_for_run(
                _RUN_ID,
                owner_id=_OWNER_ID,
            )
            async with composition.persistence.pool.connection() as connection:
                result = await connection.execute(
                    "SELECT COUNT(*) AS count FROM agent_run_leases WHERE run_id = %s",
                    (_RUN_ID,),
                )
                row = await result.fetchone()
            if row is not None and row["count"] == 0:
                return {
                    "phase": "recover",
                    "process_id": os.getpid(),
                    "run_failed": True,
                    "lease_released": True,
                    "single_recovery_event": (
                        sum(event.type == "run.failed" for event in events) == 1
                    ),
                }
        await asyncio.sleep(0.02)
    raise RuntimeError("composition_recovery_timeout")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("holder-crash", "recover"),
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
