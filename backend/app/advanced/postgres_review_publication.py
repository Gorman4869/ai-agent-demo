from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

from psycopg import AsyncConnection, Error as PsycopgError
from psycopg.rows import DictRow
from psycopg_pool import AsyncConnectionPool, PoolTimeout

from backend.app.advanced.harness import content_digest
from backend.app.advanced.review_publication import _publication_binding_digest
from backend.app.advanced.review_tools import (
    ReviewPublicationCommand,
    ReviewPublicationResult,
)
from backend.app.tools import ToolHandlerError


Pool = AsyncConnectionPool[AsyncConnection[DictRow]]
_MAX_REVISION_SCOPES = 32


class PostgresReviewPublicationStore:
    """Persist owner-scoped review revision CAS and business-key replay."""

    def __init__(
        self,
        pool: Pool,
        revisions: Mapping[tuple[str, str], int],
    ) -> None:
        if not isinstance(revisions, Mapping):
            raise TypeError("review revisions must use a mapping")
        if len(revisions) < 1 or len(revisions) > _MAX_REVISION_SCOPES:
            raise ValueError("review revisions must be bounded and non-empty")
        copied: dict[tuple[str, str], int] = {}
        for scope, revision in revisions.items():
            if (
                not isinstance(scope, tuple)
                or len(scope) != 2
                or not all(
                    isinstance(value, str) and value and value == value.strip()
                    for value in scope
                )
                or isinstance(revision, bool)
                or not isinstance(revision, int)
                or revision < 1
            ):
                raise ValueError("review revision scope is invalid")
            owner_id, review_id = scope
            copied[(content_digest(owner_id), review_id)] = revision
        self._pool = pool
        self._revisions = copied

    async def publish(
        self,
        command: ReviewPublicationCommand,
    ) -> ReviewPublicationResult:
        if not isinstance(command, ReviewPublicationCommand):
            raise ToolHandlerError("review_evidence_invalid")
        owner_scope = content_digest(command.owner_id)
        revision_scope = (owner_scope, command.review_id)
        initial_revision = self._revisions.get(revision_scope)
        if initial_revision is None:
            raise ToolHandlerError("review_revision_conflict")
        idempotency_digest = content_digest(command.idempotency_key)
        binding_digest = _publication_binding_digest(command)
        try:
            async with self._pool.connection() as connection:
                async with connection.transaction():
                    await connection.execute(
                        """
                        INSERT INTO review_publication_heads (
                            owner_scope_digest,
                            review_id,
                            current_revision
                        ) VALUES (%s, %s, %s)
                        ON CONFLICT DO NOTHING
                        """,
                        (owner_scope, command.review_id, initial_revision),
                    )
                    current_revision = await _lock_current_revision(
                        connection,
                        owner_scope=owner_scope,
                        review_id=command.review_id,
                    )
                    existing = await _select_publication(
                        connection,
                        owner_scope=owner_scope,
                        idempotency_digest=idempotency_digest,
                    )
                    if existing is not None:
                        if existing["binding_digest"].strip() != binding_digest:
                            raise ToolHandlerError("review_revision_conflict")
                        return _row_to_result(existing)
                    if current_revision != command.expected_revision:
                        raise ToolHandlerError("review_revision_conflict")

                    revision = current_revision + 1
                    publication_id = f"publication-{idempotency_digest[:32]}"
                    inserted = await connection.execute(
                        """
                        INSERT INTO review_publications (
                            publication_id,
                            owner_scope_digest,
                            review_id,
                            expected_revision,
                            revision,
                            requested_decision,
                            evidence_bundle_digest,
                            idempotency_key_digest,
                            binding_digest,
                            status
                        ) VALUES (
                            %s, %s, %s, %s, %s, %s, %s, %s, %s, 'published'
                        )
                        RETURNING publication_id, revision, status, binding_digest
                        """,
                        (
                            publication_id,
                            owner_scope,
                            command.review_id,
                            command.expected_revision,
                            revision,
                            command.requested_decision,
                            command.evidence_bundle_digest,
                            idempotency_digest,
                            binding_digest,
                        ),
                    )
                    row = await inserted.fetchone()
                    if row is None:
                        raise ToolHandlerError(
                            "tool_result_unknown",
                            result_unknown=True,
                        )
                    await connection.execute(
                        """
                        UPDATE review_publication_heads
                        SET current_revision = %s,
                            updated_at = CURRENT_TIMESTAMP
                        WHERE owner_scope_digest = %s
                          AND review_id = %s
                          AND current_revision = %s
                        """,
                        (
                            revision,
                            owner_scope,
                            command.review_id,
                            current_revision,
                        ),
                    )
                    return _row_to_result(row)
        except ToolHandlerError:
            raise
        except asyncio.CancelledError:
            raise
        except (PsycopgError, PoolTimeout):
            raise ToolHandlerError(
                "tool_result_unknown",
                result_unknown=True,
            ) from None

    async def reconcile(
        self,
        command: ReviewPublicationCommand,
    ) -> ReviewPublicationResult | None:
        if not isinstance(command, ReviewPublicationCommand):
            raise ToolHandlerError("review_evidence_invalid")
        owner_scope = content_digest(command.owner_id)
        idempotency_digest = content_digest(command.idempotency_key)
        binding_digest = _publication_binding_digest(command)
        try:
            async with self._pool.connection() as connection:
                row = await _select_publication(
                    connection,
                    owner_scope=owner_scope,
                    idempotency_digest=idempotency_digest,
                )
            if row is None:
                return None
            if row["binding_digest"].strip() != binding_digest:
                raise ToolHandlerError("review_revision_conflict")
            return _row_to_result(row)
        except ToolHandlerError:
            raise
        except asyncio.CancelledError:
            raise
        except (PsycopgError, PoolTimeout):
            raise ToolHandlerError(
                "tool_result_unknown",
                result_unknown=True,
            ) from None


async def _lock_current_revision(
    connection: AsyncConnection[DictRow],
    *,
    owner_scope: str,
    review_id: str,
) -> int:
    result = await connection.execute(
        """
        SELECT current_revision
        FROM review_publication_heads
        WHERE owner_scope_digest = %s AND review_id = %s
        FOR UPDATE
        """,
        (owner_scope, review_id),
    )
    row = await result.fetchone()
    if row is None:
        raise ToolHandlerError("review_revision_conflict")
    return row["current_revision"]


async def _select_publication(
    connection: AsyncConnection[DictRow],
    *,
    owner_scope: str,
    idempotency_digest: str,
) -> Mapping[str, Any] | None:
    result = await connection.execute(
        """
        SELECT publication_id, revision, status, binding_digest
        FROM review_publications
        WHERE owner_scope_digest = %s
          AND idempotency_key_digest = %s
        """,
        (owner_scope, idempotency_digest),
    )
    return await result.fetchone()


def _row_to_result(row: Mapping[str, Any]) -> ReviewPublicationResult:
    return ReviewPublicationResult(
        publication_id=row["publication_id"],
        revision=row["revision"],
        status=row["status"],
    )


__all__ = ["PostgresReviewPublicationStore"]
