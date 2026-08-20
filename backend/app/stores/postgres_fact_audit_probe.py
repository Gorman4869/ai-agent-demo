from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import sys

from backend.app.memory import (
    CorrectMemoryFact,
    DeleteMemoryFact,
    MemoryFactAuditAction,
    MemoryScope,
)
from backend.app.stores.postgres import PostgresPersistence


_OWNER_ID = "m11-memory-fact-audit-owner"


async def _run_probe(phase: str, fact_id: str | None) -> None:
    conninfo = os.environ.get("AI_AGENT_POSTGRES_DSN", "")
    persistence = await PostgresPersistence.open(conninfo)
    try:
        await persistence.setup()
        if phase == "prepare":
            fact = persistence.memory_store.remember(
                owner_id=_OWNER_ID,
                key="preferred-language",
                value="English",
                scope=MemoryScope.USER,
                approved=True,
            )
            output = {
                "phase": phase,
                "process_id": os.getpid(),
                "fact_id": fact.id,
                "version": fact.version,
            }
        else:
            if fact_id is None:
                raise RuntimeError("memory_fact_probe_id_missing")
            output = _mutate_or_audit(persistence, phase, fact_id)
        print(json.dumps(output, sort_keys=True))
    finally:
        await persistence.close()


def _mutate_or_audit(
    persistence: PostgresPersistence,
    phase: str,
    fact_id: str,
) -> dict[str, object]:
    if phase == "correct":
        fact = persistence.memory_store.correct_fact(
            CorrectMemoryFact(
                fact_id=fact_id,
                owner_id=_OWNER_ID,
                expected_version=0,
                value="Chinese",
                approved=True,
            )
        )
        return {
            "phase": phase,
            "process_id": os.getpid(),
            "version": fact.version,
        }
    if phase == "delete":
        result = persistence.memory_store.delete_fact(
            DeleteMemoryFact(
                fact_id=fact_id,
                owner_id=_OWNER_ID,
                expected_version=1,
            )
        )
        return {
            "phase": phase,
            "process_id": os.getpid(),
            "version": result.version,
        }

    audit = persistence.memory_store.fact_audit(
        fact_id,
        owner_id=_OWNER_ID,
    )
    actions = tuple(record.action for record in audit)
    versions = tuple(record.version for record in audit)
    if actions != (
        MemoryFactAuditAction.CREATED,
        MemoryFactAuditAction.CORRECTED,
        MemoryFactAuditAction.DELETED,
    ) or versions != (0, 1, 2):
        raise RuntimeError("memory_fact_probe_audit_invalid")
    return {
        "phase": phase,
        "process_id": os.getpid(),
        "active_facts": len(persistence.memory_store.facts(_OWNER_ID)),
        "audit_actions": [action.value for action in actions],
        "audit_versions": list(versions),
        "digests_valid": all(len(record.value_digest) == 64 for record in audit),
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("prepare", "correct", "delete", "audit"),
        required=True,
    )
    parser.add_argument("--fact-id")
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    coroutine = _run_probe(arguments.phase, arguments.fact_id)
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
