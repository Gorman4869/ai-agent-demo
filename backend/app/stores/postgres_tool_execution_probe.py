from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import sys
from datetime import UTC, datetime

from backend.app.domain import RunRecord, RunStatus, ToolExecution
from backend.app.domain.run import ToolExecutionStatus
from backend.app.stores import InvalidToolExecutionTransitionError
from backend.app.stores.postgres import PostgresPersistence


_RUN_ID = "m11-tool-process-run"
_OWNER_ID = "m11-tool-process-owner"
_KNOWN_CALL_ID = "m11-tool-known-call"
_UNKNOWN_CALL_ID = "m11-tool-unknown-call"
_TOOL_NAME = "publish_report"
_KNOWN_ARGUMENTS = {"document_id": "private-known-document"}
_UNKNOWN_ARGUMENTS = {"document_id": "private-unknown-document"}
_KNOWN_KEY = "private-known-idempotency-key"
_UNKNOWN_KEY = "private-unknown-idempotency-key"


async def _run_probe(
    *,
    phase: str,
    known_execution_id: str | None,
    unknown_execution_id: str | None,
) -> None:
    conninfo = os.environ.get("AI_AGENT_POSTGRES_DSN", "")
    persistence = await PostgresPersistence.open(conninfo)
    try:
        await persistence.setup()
        if phase == "prepare":
            output = await _prepare(persistence)
        elif phase == "settle-crash":
            if known_execution_id is None:
                raise RuntimeError("tool_probe_known_execution_required")
            print(
                json.dumps(
                    {
                        "phase": "settle-started",
                        "process_id": os.getpid(),
                        "known_execution_id": known_execution_id,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            current = await persistence.tool_execution_store.get(
                known_execution_id,
                owner_id=_OWNER_ID,
            )
            if current is None or current.status is not ToolExecutionStatus.RUNNING:
                raise RuntimeError("tool_probe_known_execution_invalid")
            await persistence.tool_execution_store.transition(
                current.id,
                owner_id=_OWNER_ID,
                expected_version=current.version,
                target_status=ToolExecutionStatus.COMPLETED,
                result={"private": "private-published-result"},
                result_summary="document published",
            )
            await persistence.close()
            os._exit(17)
        else:
            if known_execution_id is None or unknown_execution_id is None:
                raise RuntimeError("tool_probe_execution_identifiers_required")
            output = await _recover(
                persistence,
                known_execution_id=known_execution_id,
                unknown_execution_id=unknown_execution_id,
            )
        print(json.dumps(output, sort_keys=True))
    finally:
        await persistence.close()


async def _prepare(persistence: PostgresPersistence) -> dict[str, object]:
    now = datetime.now(UTC)
    run = RunRecord.create(
        run_id=_RUN_ID,
        session_id="m11-tool-process-session",
        owner_id=_OWNER_ID,
        runtime="manual",
        input_text="private tool execution process probe",
        idempotency_key="private-tool-process-run-key",
        created_at=now,
    )
    await persistence.run_store.create(run)
    running_run = await persistence.run_store.transition(
        run.id,
        owner_id=run.owner_id,
        expected_version=run.version,
        target_status=RunStatus.RUNNING,
    )
    known = ToolExecution.create(
        execution_id="m11-known-execution",
        run_id=running_run.id,
        tool_call_id=_KNOWN_CALL_ID,
        tool_name=_TOOL_NAME,
        arguments=_KNOWN_ARGUMENTS,
        side_effecting=True,
        idempotency_key=_KNOWN_KEY,
        created_at=now,
    )
    unknown = ToolExecution.create(
        execution_id="m11-unknown-execution",
        run_id=running_run.id,
        tool_call_id=_UNKNOWN_CALL_ID,
        tool_name=_TOOL_NAME,
        arguments=_UNKNOWN_ARGUMENTS,
        side_effecting=True,
        idempotency_key=_UNKNOWN_KEY,
        created_at=now,
    )
    await persistence.tool_execution_store.create(
        known,
        owner_id=_OWNER_ID,
    )
    await persistence.tool_execution_store.create(
        unknown,
        owner_id=_OWNER_ID,
    )
    known_running = await persistence.tool_execution_store.transition(
        known.id,
        owner_id=_OWNER_ID,
        expected_version=known.version,
        target_status=ToolExecutionStatus.RUNNING,
    )
    unknown_running = await persistence.tool_execution_store.transition(
        unknown.id,
        owner_id=_OWNER_ID,
        expected_version=unknown.version,
        target_status=ToolExecutionStatus.RUNNING,
    )
    return {
        "phase": "prepare",
        "process_id": os.getpid(),
        "known_execution_id": known_running.id,
        "unknown_execution_id": unknown_running.id,
    }


async def _recover(
    persistence: PostgresPersistence,
    *,
    known_execution_id: str,
    unknown_execution_id: str,
) -> dict[str, object]:
    known = await persistence.tool_execution_store.get(
        known_execution_id,
        owner_id=_OWNER_ID,
    )
    unknown = await persistence.tool_execution_store.get(
        unknown_execution_id,
        owner_id=_OWNER_ID,
    )
    if (
        known is None
        or known.status is not ToolExecutionStatus.COMPLETED
        or known.result_summary != "document published"
        or known.result_digest is None
    ):
        raise RuntimeError("tool_probe_completed_result_invalid")
    if unknown is None or unknown.status is not ToolExecutionStatus.RUNNING:
        raise RuntimeError("tool_probe_unknown_result_invalid")

    replay = await persistence.tool_execution_store.create(
        ToolExecution.create(
            execution_id="m11-known-replay",
            run_id=_RUN_ID,
            tool_call_id="m11-known-replay-call",
            tool_name=_TOOL_NAME,
            arguments=_KNOWN_ARGUMENTS,
            side_effecting=True,
            idempotency_key=_KNOWN_KEY,
            attempt=2,
            created_at=datetime.now(UTC),
        ),
        owner_id=_OWNER_ID,
    )
    reconciled = await persistence.tool_execution_store.transition(
        unknown.id,
        owner_id=_OWNER_ID,
        expected_version=unknown.version,
        target_status=ToolExecutionStatus.UNKNOWN,
        error_code="tool_result_unknown",
        public_message="Tool result could not be confirmed",
    )
    terminal_immutable = False
    try:
        await persistence.tool_execution_store.transition(
            reconciled.id,
            owner_id=_OWNER_ID,
            expected_version=reconciled.version,
            target_status=ToolExecutionStatus.COMPLETED,
            result_summary="must not replay",
        )
    except InvalidToolExecutionTransitionError:
        terminal_immutable = True

    return {
        "phase": "recover",
        "process_id": os.getpid(),
        "known_completed": True,
        "known_replayed": not replay.created and replay.record.id == known.id,
        "unknown_reconciled": (
            reconciled.status is ToolExecutionStatus.UNKNOWN
        ),
        "terminal_immutable": terminal_immutable,
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("prepare", "settle-crash", "recover"),
        required=True,
    )
    parser.add_argument("--known-execution-id")
    parser.add_argument("--unknown-execution-id")
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    coroutine = _run_probe(
        phase=arguments.phase,
        known_execution_id=arguments.known_execution_id,
        unknown_execution_id=arguments.unknown_execution_id,
    )
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
