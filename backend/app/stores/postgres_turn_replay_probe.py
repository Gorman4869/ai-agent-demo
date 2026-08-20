from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import sys
from datetime import UTC, datetime

from backend.app.domain import Message
from backend.app.domain.run import RunRecord, RunStatus
from backend.app.postgres_execution import PostgresExecutionComposition
from backend.app.stores.base import TerminalCommit
from backend.app.stores.postgres import PostgresPersistence


_RUN_ID = "m11-memory-turn-replay-run"
_SESSION_ID = "m11-memory-turn-replay-session"
_OWNER_ID = "m11-memory-turn-replay-owner"
_INPUT = "private replay fixture input"
_ANSWER = "private replay fixture answer"


class _ForbiddenRuntime:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, request, emit, control):
        del request, emit, control
        self.calls += 1
        raise AssertionError("terminal Run replay called Runtime")


async def _run_probe(phase: str) -> None:
    conninfo = os.environ.get("AI_AGENT_POSTGRES_DSN", "")
    output = (
        await _prepare(conninfo)
        if phase == "prepare"
        else await _replay(conninfo)
    )
    print(json.dumps(output, sort_keys=True))


async def _prepare(conninfo: str) -> dict[str, object]:
    persistence = await PostgresPersistence.open(conninfo)
    try:
        await persistence.setup()
        run = RunRecord.create(
            run_id=_RUN_ID,
            session_id=_SESSION_ID,
            owner_id=_OWNER_ID,
            runtime="manual",
            input_text=_INPUT,
            idempotency_key="m11-memory-turn-replay-key",
            created_at=datetime(2026, 8, 20, tzinfo=UTC),
        )
        await persistence.run_store.create(run)
        running = await persistence.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=run.version,
            target_status=RunStatus.RUNNING,
        )
        terminal = await persistence.event_store.commit_terminal(
            TerminalCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=running.version,
                target_status=RunStatus.COMPLETED,
                event_id="m11-memory-turn-replay-completed",
                event_data={"status": RunStatus.COMPLETED.value},
                answer=_ANSWER,
            )
        )
        messages = persistence.memory_store.messages(_SESSION_ID)
        if messages:
            raise RuntimeError("turn_replay_prepare_published_messages")
        return {
            "phase": "prepare",
            "process_id": os.getpid(),
            "run_status": terminal.record.status.value,
            "messages": len(messages),
        }
    finally:
        await persistence.close()


async def _replay(conninfo: str) -> dict[str, object]:
    runtime = _ForbiddenRuntime()
    composition = await PostgresExecutionComposition.open(
        conninfo,
        runtimes={"manual": runtime},
    )
    try:
        first = await composition.coordinator.execute(
            _RUN_ID,
            owner_id=_OWNER_ID,
        )
        second = await composition.coordinator.execute(
            _RUN_ID,
            owner_id=_OWNER_ID,
        )
        messages = await composition.persistence.async_memory_store.messages(
            _SESSION_ID
        )
        expected = (
            Message(role="user", content=_INPUT),
            Message(role="assistant", content=_ANSWER),
        )
        if first != second or messages != expected:
            raise RuntimeError("turn_replay_result_invalid")
        return {
            "phase": "replay",
            "process_id": os.getpid(),
            "run_status": first.status.value,
            "messages": len(messages),
            "runtime_calls": runtime.calls,
        }
    finally:
        await composition.close()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("prepare", "replay"), required=True)
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    coroutine = _run_probe(arguments.phase)
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
