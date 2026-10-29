from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import sys

from backend.app.advanced.postgres_review_requests import PostgresReviewRequestStore
from backend.app.advanced.review_runtime import ReviewRunSpec
from backend.app.stores.postgres import PostgresPersistence


async def _run(phase: str, run_id: str | None) -> None:
    persistence = await PostgresPersistence.open(os.environ.get("AI_AGENT_POSTGRES_DSN", ""))
    try:
        await persistence.setup()
        store = PostgresReviewRequestStore(persistence.run_store)
        spec = ReviewRunSpec(
            review_id="review-request-probe", expected_revision=3,
            image_asset_id="image-1", policy_topic="private review request topic",
            page_fixture_id="page-1", requested_decision="approve",
        )
        if phase == "create":
            created = await store.create(spec, owner_id="request-probe-owner", idempotency_key="private-review-request-probe-key")
            output = {"phase": phase, "process_id": os.getpid(), "run_id": created.record.id}
        else:
            if run_id is None:
                raise RuntimeError("review_request_probe_run_required")
            resolved = await store.resolve(run_id, owner_id="request-probe-owner")
            replay = await store.create(spec, owner_id="request-probe-owner", idempotency_key="private-review-request-probe-key")
            output = {
                "phase": phase, "process_id": os.getpid(),
                "spec_restored": resolved == spec,
                "same_run_replayed": not replay.created and replay.record.id == run_id,
                "cross_owner_hidden": await store.resolve(run_id, owner_id="other-owner") is None,
            }
        print(json.dumps(output, sort_keys=True))
    finally:
        await persistence.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase", choices=("create", "resolve"), required=True)
    parser.add_argument("--run-id")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.run(_run(args.phase, args.run_id), loop_factory=lambda: asyncio.SelectorEventLoop(selectors.SelectSelector()))
    else:
        asyncio.run(_run(args.phase, args.run_id))


if __name__ == "__main__":
    main()
