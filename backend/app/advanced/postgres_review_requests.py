from __future__ import annotations

import asyncio
from dataclasses import asdict

from psycopg import Error as PsycopgError
from psycopg_pool import PoolTimeout

from backend.app.advanced.review_requests import create_review_run_record
from backend.app.advanced.review_runtime import ReviewRunSpec
from backend.app.domain.run import RunRecord
from backend.app.stores.base import CreateRunResult, StoreError, StoreUnavailableError
from backend.app.stores.postgres import PostgresRunStore


class PostgresReviewRequestStore:
    """Create the durable Run, counter and private spec in one transaction."""

    def __init__(self, run_store: PostgresRunStore) -> None:
        self.run_store = run_store
        self._pool = run_store._pool

    async def create(
        self, spec: ReviewRunSpec, *, owner_id: str, idempotency_key: str,
    ) -> CreateRunResult:
        record = create_review_run_record(spec, owner_id=owner_id, idempotency_key=idempotency_key)
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    created = await self.run_store._create_on_connection(connection, record)
                    if created.created:
                        await connection.execute(
                            """
                            INSERT INTO review_run_requests (
                                run_id, request_digest, scenario_version, review_id,
                                expected_revision, image_asset_id, policy_topic,
                                page_fixture_id, requested_decision
                            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                            """,
                            (created.record.id, created.record.request_digest,
                             spec.scenario_version, spec.review_id, spec.expected_revision,
                             spec.image_asset_id, spec.policy_topic, spec.page_fixture_id,
                             spec.requested_decision),
                        )
                    else:
                        result = await connection.execute(
                            "SELECT request_digest FROM review_run_requests WHERE run_id = %s",
                            (created.record.id,),
                        )
                        row = await result.fetchone()
                        if row is None or row["request_digest"].strip() != record.request_digest:
                            raise StoreUnavailableError()
                    return created
        except StoreError:
            raise
        except asyncio.CancelledError:
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    async def resolve(self, run_id: str, *, owner_id: str) -> ReviewRunSpec | None:
        try:
            async with self._pool.connection() as connection:
                result = await connection.execute(
                    """
                    SELECT request.scenario_version, request.review_id,
                           request.expected_revision, request.image_asset_id,
                           request.policy_topic, request.page_fixture_id,
                           request.requested_decision, request.request_digest,
                           run.session_id, run.created_at,
                           run.request_digest AS run_request_digest
                    FROM review_run_requests AS request
                    JOIN agent_runs AS run ON run.id = request.run_id
                    WHERE run.id = %s AND run.owner_id = %s
                    """,
                    (run_id, owner_id),
                )
                row = await result.fetchone()
            if row is None:
                return None
            spec = ReviewRunSpec(**{
                key: row[key] for key in (
                    "scenario_version", "review_id", "expected_revision", "image_asset_id",
                    "policy_topic", "page_fixture_id", "requested_decision",
                )
            })
            expected = RunRecord.create(
                run_id=run_id, session_id=row["session_id"], owner_id=owner_id,
                runtime="manual", input_text="Review server-owned resources",
                idempotency_key="review-request-integrity", created_at=row["created_at"],
                request_options=asdict(spec),
            ).request_digest
            if row["request_digest"].strip() != expected or row["run_request_digest"].strip() != expected:
                raise StoreUnavailableError()
            return spec
        except StoreError:
            raise
        except asyncio.CancelledError:
            raise
        except (PsycopgError, PoolTimeout, TypeError, ValueError):
            raise StoreUnavailableError() from None


__all__ = ["PostgresReviewRequestStore"]
