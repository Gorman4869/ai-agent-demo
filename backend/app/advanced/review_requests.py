from __future__ import annotations

import hashlib
from dataclasses import asdict
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from backend.app.advanced.review_runtime import ReviewRunSpec
from backend.app.domain.run import RunRecord
from backend.app.stores.base import CreateRunResult


class ReviewRequestStore(Protocol):
    async def create(
        self, spec: ReviewRunSpec, *, owner_id: str, idempotency_key: str,
    ) -> CreateRunResult: ...

    async def resolve(self, run_id: str, *, owner_id: str) -> ReviewRunSpec | None: ...


def create_review_run_record(
    spec: ReviewRunSpec, *, owner_id: str, idempotency_key: str,
) -> RunRecord:
    session_digest = hashlib.sha256(
        f"review-session-v1:{len(owner_id)}:{owner_id}:{idempotency_key}".encode("utf-8")
    ).hexdigest()
    return RunRecord.create(
        run_id=str(uuid4()), session_id=f"review-{session_digest}",
        owner_id=owner_id, runtime="manual", input_text="Review server-owned resources",
        idempotency_key=idempotency_key, created_at=datetime.now(UTC),
        request_options=asdict(spec),
    )
