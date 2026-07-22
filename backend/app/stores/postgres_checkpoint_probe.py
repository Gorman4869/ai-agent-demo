from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import sys

from backend.app.agent import (
    CancellationToken,
    RuntimeCheckpointContext,
    RuntimeControl,
    RuntimeEvent,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.agent.checkpoint_runtime import CheckpointedLangGraphRuntime
from backend.app.domain.run import RunStatus
from backend.app.stores.postgres import PostgresPersistence


class _StaticRuntime:
    def __init__(self, answer: str) -> None:
        self._answer = answer

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit, control
        return RuntimeResult(status=RunStatus.COMPLETED, answer=self._answer)


async def _ignore_event(event: RuntimeEvent) -> None:
    del event


async def _run_probe(*, phase: str, run_id: str, owner_id: str) -> None:
    conninfo = os.environ.get("AI_AGENT_POSTGRES_DSN", "")
    persistence = await PostgresPersistence.open(conninfo)
    try:
        await persistence.setup()
        request = RuntimeRequest(
            run_id=run_id,
            input_text="checkpoint persistence probe",
            checkpoint_context=RuntimeCheckpointContext.for_run(
                run_id=run_id,
                owner_id=owner_id,
            ),
        )
        config = {
            "configurable": {
                "thread_id": request.checkpoint_context.thread_id,
            }
        }
        before = await persistence.checkpointer.aget_tuple(config)
        before_count = _invocation_count(before)
        result = await CheckpointedLangGraphRuntime(
            delegate=_StaticRuntime(phase),
            checkpointer=persistence.checkpointer,
        ).run(
            request,
            emit=_ignore_event,
            control=RuntimeControl(CancellationToken()),
        )
        after = await persistence.checkpointer.aget_tuple(config)
        print(
            json.dumps(
                {
                    "phase": phase,
                    "process_id": os.getpid(),
                    "before_count": before_count,
                    "after_count": _invocation_count(after),
                    "answer": result.answer,
                },
                sort_keys=True,
            )
        )
    finally:
        await persistence.close()


def _invocation_count(checkpoint_tuple: object | None) -> int:
    if checkpoint_tuple is None:
        return 0
    checkpoint = getattr(checkpoint_tuple, "checkpoint", None)
    if not isinstance(checkpoint, dict):
        raise RuntimeError("checkpoint_probe_invalid")
    channel_values = checkpoint.get("channel_values")
    if not isinstance(channel_values, dict):
        raise RuntimeError("checkpoint_probe_invalid")
    value = channel_values.get("invocation_count", 0)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise RuntimeError("checkpoint_probe_invalid")
    return value


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("write", "resume"), required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--owner-id", required=True)
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    coroutine = _run_probe(
        phase=arguments.phase,
        run_id=arguments.run_id,
        owner_id=arguments.owner_id,
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
