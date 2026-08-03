from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import sys
from datetime import timedelta

from backend.app.domain import Message
from backend.app.memory import MemoryScope
from backend.app.stores.postgres import PostgresPersistence
from backend.app.tools import ApprovalResponse, tool_arguments_digest


_RUN_ID = "m11-state-process-run"
_OWNER_ID = "m11-state-process-owner"
_CALL_ID = "m11-state-process-call"
_TOOL_NAME = "publish_report"
_SESSION_ID = "m11-state-process-session"
_ARGUMENTS = {"document_id": "fixture-document", "publish": True}


async def _run_probe(
    *,
    phase: str,
    approval_id: str | None,
    fact_id: str | None,
) -> None:
    conninfo = os.environ.get("AI_AGENT_POSTGRES_DSN", "")
    persistence = await PostgresPersistence.open(conninfo)
    try:
        await persistence.setup()
        if phase == "write":
            request = persistence.approval_store.request(
                run_id=_RUN_ID,
                principal_id=_OWNER_ID,
                tool_call_id=_CALL_ID,
                tool_name=_TOOL_NAME,
                arguments=_ARGUMENTS,
                expires_in=timedelta(hours=1),
            )
            persistence.memory_store.append_message(
                _SESSION_ID,
                Message(role="user", content="private fixture message"),
            )
            fact = persistence.memory_store.remember(
                owner_id=_OWNER_ID,
                key="preferred_language",
                value="Chinese",
                scope=MemoryScope.USER,
                approved=True,
            )
            output = {
                "phase": phase,
                "process_id": os.getpid(),
                "approval_id": request.id,
                "fact_id": fact.id,
            }
        else:
            if approval_id is None or fact_id is None:
                raise RuntimeError("state_probe_identifiers_required")
            resolution = persistence.approval_store.resolve(
                approval_id=approval_id,
                run_id=_RUN_ID,
                principal_id=_OWNER_ID,
                tool_call_id=_CALL_ID,
                tool_name=_TOOL_NAME,
                arguments_digest=tool_arguments_digest(_ARGUMENTS),
                decision=ApprovalResponse.APPROVE,
            )
            recovered_arguments = (
                persistence.approval_store.approved_arguments(resolution)
            )
            first = persistence.approval_store.consume(
                principal_id=_OWNER_ID,
                run_id=_RUN_ID,
                tool_call_id=_CALL_ID,
                tool_name=_TOOL_NAME,
                arguments=_ARGUMENTS,
            )
            replay = persistence.approval_store.consume(
                principal_id=_OWNER_ID,
                run_id=_RUN_ID,
                tool_call_id=_CALL_ID,
                tool_name=_TOOL_NAME,
                arguments=_ARGUMENTS,
            )
            messages = persistence.memory_store.messages(_SESSION_ID)
            facts = persistence.memory_store.facts(_OWNER_ID)
            if messages != (
                Message(role="user", content="private fixture message"),
            ):
                raise RuntimeError("state_probe_messages_invalid")
            if (
                len(facts) != 1
                or facts[0].id != fact_id
                or facts[0].key != "preferred_language"
                or facts[0].value != "Chinese"
                or facts[0].scope is not MemoryScope.USER
            ):
                raise RuntimeError("state_probe_facts_invalid")
            output = {
                "phase": phase,
                "process_id": os.getpid(),
                "arguments_recovered": recovered_arguments == _ARGUMENTS,
                "approval_consumed": first.approved,
                "replay_reason": replay.reason,
                "messages_recovered": len(messages),
                "facts_recovered": len(facts),
                "fact_deleted": persistence.memory_store.forget(
                    fact_id,
                    owner_id=_OWNER_ID,
                ),
            }
        print(json.dumps(output, sort_keys=True))
    finally:
        await persistence.close()


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("write", "resume"), required=True)
    parser.add_argument("--approval-id")
    parser.add_argument("--fact-id")
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    coroutine = _run_probe(
        phase=arguments.phase,
        approval_id=arguments.approval_id,
        fact_id=arguments.fact_id,
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
