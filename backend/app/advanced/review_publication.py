from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from backend.app.advanced.harness import content_digest
from backend.app.advanced.review_tools import (
    ReviewPublicationCommand,
    ReviewPublicationResult,
    ReviewPublisher,
)
from backend.app.tools import ToolHandlerError


_MAX_REVISION_SCOPES = 32


class ReviewPublicationStore(ReviewPublisher, Protocol):
    """Authoritative owner-scoped publication and reconciliation boundary."""

    async def reconcile(
        self,
        command: ReviewPublicationCommand,
    ) -> ReviewPublicationResult | None: ...


@dataclass(frozen=True)
class _StoredPublication:
    binding_digest: str = field(repr=False)
    result: ReviewPublicationResult


class InMemoryReviewPublicationStore:
    """Single-event-loop review publication CAS with business-key replay."""

    def __init__(
        self,
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
        self._revisions = copied
        self._publications: dict[tuple[str, str], _StoredPublication] = {}
        self._lock = asyncio.Lock()

    async def publish(
        self,
        command: ReviewPublicationCommand,
    ) -> ReviewPublicationResult:
        if not isinstance(command, ReviewPublicationCommand):
            raise ToolHandlerError("review_evidence_invalid")
        owner_scope = content_digest(command.owner_id)
        idempotency_digest = content_digest(command.idempotency_key)
        publication_key = (owner_scope, idempotency_digest)
        binding_digest = _publication_binding_digest(command)
        async with self._lock:
            existing = self._publications.get(publication_key)
            if existing is not None:
                if existing.binding_digest != binding_digest:
                    raise ToolHandlerError("review_revision_conflict")
                return existing.result
            revision_scope = (owner_scope, command.review_id)
            current_revision = self._revisions.get(revision_scope)
            if current_revision != command.expected_revision:
                raise ToolHandlerError("review_revision_conflict")
            result = ReviewPublicationResult(
                publication_id=f"publication-{idempotency_digest[:32]}",
                revision=current_revision + 1,
            )
            self._revisions[revision_scope] = result.revision
            self._publications[publication_key] = _StoredPublication(
                binding_digest=binding_digest,
                result=result,
            )
            return result

    async def reconcile(
        self,
        command: ReviewPublicationCommand,
    ) -> ReviewPublicationResult | None:
        if not isinstance(command, ReviewPublicationCommand):
            raise ToolHandlerError("review_evidence_invalid")
        publication_key = (
            content_digest(command.owner_id),
            content_digest(command.idempotency_key),
        )
        binding_digest = _publication_binding_digest(command)
        async with self._lock:
            existing = self._publications.get(publication_key)
            if existing is None:
                return None
            if existing.binding_digest != binding_digest:
                raise ToolHandlerError("review_revision_conflict")
            return existing.result


def _publication_binding_digest(command: ReviewPublicationCommand) -> str:
    encoded = json.dumps(
        {
            "scenario_version": command.scenario_version,
            "owner_scope_digest": content_digest(command.owner_id),
            "review_id": command.review_id,
            "expected_revision": command.expected_revision,
            "requested_decision": command.requested_decision,
            "evidence_bundle_digest": command.evidence_bundle_digest,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


__all__ = [
    "InMemoryReviewPublicationStore",
    "ReviewPublicationStore",
]
