from __future__ import annotations

from pydantic import ValidationError

from backend.app.advanced.review_runtime import (
    REVIEW_SOURCE_ORDER,
    ReviewEvidenceBundle,
    ReviewEvidenceRecord,
)
from backend.app.api.schemas import (
    ReviewEvidenceResponse,
    ReviewPublicationResponse,
    ReviewSnapshotResponse,
    ReviewUsageResponse,
)
from backend.app.domain.run import RunRecord, RunStatus, StoredRunEvent


_ATTENTION_CODES = {
    "approval_rejected", "approval_expired", "tool_result_unknown",
    "review_policy_no_evidence", "review_page_changed", "review_revision_conflict",
}


def project_review_snapshot(
    run: RunRecord,
    events: tuple[StoredRunEvent, ...],
) -> ReviewSnapshotResponse | None:
    """Project reviewed fields from the owned Run history without resource reads."""
    records: list[ReviewEvidenceRecord] = []
    publications: list[dict[str, object]] = []
    for event in events:
        if event.run_id != run.id:
            continue
        if event.type == "review.result":
            publications.append(event.data)
        if event.type != "review.evidence.recorded" or len(records) == 3:
            continue
        data = event.data
        try:
            record = ReviewEvidenceRecord(
                review_id=data.get("review_id"),
                source_kind=data.get("source_kind"),
                source_ref=data.get("source_ref"),
                content_sha256=data.get("content_sha256"),
                content_bytes=data.get("content_bytes"),
                trust=data.get("trust"),
                status=data.get("status"),
                citation_refs=tuple(data.get("citation_refs", ())),
                schema=data.get("schema"),
            )
        except (TypeError, ValueError):
            continue
        if record.source_kind != REVIEW_SOURCE_ORDER[len(records)]:
            continue
        if records and record.review_id != records[0].review_id:
            continue
        records.append(record)
    if not records:
        return None

    digest = (
        ReviewEvidenceBundle(records[0].review_id, tuple(records)).digest
        if len(records) == 3 else None
    )
    outcome = "in_progress"
    if run.status is RunStatus.WAITING_APPROVAL:
        outcome = "waiting_approval"
    elif run.status.is_terminal:
        outcome = (
            "needs_attention"
            if run.status in {RunStatus.COMPLETED, RunStatus.CANCELLED}
            or run.failure is not None and run.failure.code in _ATTENTION_CODES
            else "failed"
        )
    publication = None
    if digest is not None and run.status is RunStatus.COMPLETED:
        for data in publications:
            if (
                data.get("schema") != "review-result-v1"
                or data.get("scenario_version") != "multisource-review-v1"
                or data.get("review_id") != records[0].review_id
                or data.get("outcome") != "published"
                or data.get("evidence_bundle_digest") != digest
                or data.get("evidence_refs") != [r.source_ref for r in records]
            ):
                continue
            try:
                candidate = ReviewPublicationResponse.model_validate(
                    data.get("publication")
                )
                ReviewUsageResponse.model_validate(data.get("usage"))
            except ValidationError:
                continue
            publication = candidate
            outcome = "published"
    return ReviewSnapshotResponse(
        review_id=records[0].review_id,
        outcome=outcome,
        evidence=[
            ReviewEvidenceResponse(
                source_kind=r.source_kind,
                source_ref=r.source_ref,
                content_sha256=r.content_sha256,
                content_bytes=r.content_bytes,
                trust=r.trust,
                status=r.status,
                citation_refs=list(r.citation_refs),
            )
            for r in records
        ],
        evidence_bundle_digest=digest,
        publication=publication,
    )
