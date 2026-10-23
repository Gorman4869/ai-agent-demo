from __future__ import annotations

import argparse
import asyncio
import json
import os
import selectors
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from backend.app.advanced.postgres_review_publication import (
    PostgresReviewPublicationStore,
)
from backend.app.advanced.review_runtime import (
    MultisourceReviewRuntime,
    ReviewRunBinding,
    ReviewRunCatalog,
    ReviewRunSpec,
    _execution_id,
)
from backend.app.advanced.review_tools import (
    ReviewScenarioLimits,
    create_review_publication_command,
)
from backend.app.agent import (
    CancellationToken,
    RuntimeApprovalDecision,
    RuntimeApprovalResume,
    RuntimeContextIdentity,
    RuntimeControl,
    RuntimeEvent,
    RuntimeRequest,
)
from backend.app.domain import RunRecord, RunStatus, ToolExecution
from backend.app.domain.run import RunFailure, ToolExecutionStatus
from backend.app.stores.base import StartCommit, TerminalCommit
from backend.app.stores.postgres import PostgresPersistence
from backend.app.tools import ToolExecutionContext


_OWNER_ID = "review-probe-owner"
_KNOWN_RUN_ID = "review-publication-known-run"
_MISSING_RUN_ID = "review-publication-missing-run"
_KNOWN_REVIEW_ID = "review-publication-known"
_MISSING_REVIEW_ID = "review-publication-missing"
_EXPECTED_REVISION = 3
_EVIDENCE_DIGEST = "d" * 64


def _publication_store(
    persistence: PostgresPersistence,
) -> PostgresReviewPublicationStore:
    return PostgresReviewPublicationStore(
        persistence.pool,
        {
            (_OWNER_ID, _KNOWN_REVIEW_ID): _EXPECTED_REVISION,
            (_OWNER_ID, _MISSING_REVIEW_ID): _EXPECTED_REVISION,
        },
    )


async def _run_probe(
    *,
    phase: str,
    known_approval_id: str | None,
    missing_approval_id: str | None,
) -> None:
    conninfo = os.environ.get("AI_AGENT_POSTGRES_DSN", "")
    persistence = await PostgresPersistence.open(conninfo)
    try:
        await persistence.setup()
        publication_store = _publication_store(persistence)
        if phase == "commit-crash":
            known = await _prepare_running_execution(
                persistence,
                publication_store,
                run_id=_KNOWN_RUN_ID,
                review_id=_KNOWN_REVIEW_ID,
                commit_publication=True,
            )
            missing = await _prepare_running_execution(
                persistence,
                publication_store,
                run_id=_MISSING_RUN_ID,
                review_id=_MISSING_REVIEW_ID,
                commit_publication=False,
            )
            print(
                json.dumps(
                    {
                        "phase": phase,
                        "process_id": os.getpid(),
                        "known_approval_id": known,
                        "missing_approval_id": missing,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
            await persistence.close()
            os._exit(17)
        if known_approval_id is None or missing_approval_id is None:
            raise RuntimeError("review_publication_probe_approval_ids_required")
        output = await _recover(
            persistence,
            publication_store,
            known_approval_id=known_approval_id,
            missing_approval_id=missing_approval_id,
        )
        print(json.dumps(output, sort_keys=True))
    finally:
        await persistence.close()


async def _prepare_running_execution(
    persistence: PostgresPersistence,
    publication_store: PostgresReviewPublicationStore,
    *,
    run_id: str,
    review_id: str,
    commit_publication: bool,
) -> str:
    now = datetime.now(UTC)
    run = RunRecord.create(
        run_id=run_id,
        session_id=f"{run_id}-session",
        owner_id=_OWNER_ID,
        runtime="manual",
        input_text="private review publication restart input",
        idempotency_key=f"private-{run_id}-idempotency-key",
        created_at=now,
    )
    await persistence.run_store.create(run)
    started = await persistence.event_store.commit_start(
        StartCommit(
            run_id=run.id,
            owner_id=run.owner_id,
            expected_version=run.version,
            event_id=f"{run_id}-started",
            event_data={"runtime": "manual"},
        )
    )
    arguments = _publication_arguments(review_id)
    call_id = f"{run_id}-publish"
    approval = await asyncio.to_thread(
        persistence.approval_store.request,
        run_id=run_id,
        principal_id=_OWNER_ID,
        tool_call_id=call_id,
        tool_name="publish_review",
        arguments=arguments,
    )
    resolution = await asyncio.to_thread(
        persistence.approval_store.resolve,
        approval_id=approval.id,
        run_id=run_id,
        principal_id=_OWNER_ID,
        tool_call_id=call_id,
        tool_name="publish_review",
        arguments_digest=approval.arguments_digest,
        decision="approve",
    )
    context = ToolExecutionContext(
        principal_id=_OWNER_ID,
        roles=frozenset({"reviewer"}),
        approval_store=persistence.approval_store,
        run_id=run_id,
    )
    command = create_review_publication_command(arguments, context)
    execution = ToolExecution.create(
        execution_id=_execution_id(call_id),
        run_id=run_id,
        tool_call_id=call_id,
        tool_name="publish_review",
        arguments=arguments,
        side_effecting=True,
        idempotency_key=command.idempotency_key,
        created_at=now,
    )
    created = await persistence.tool_execution_store.create(
        execution,
        owner_id=_OWNER_ID,
    )
    waiting = await persistence.tool_execution_store.transition(
        execution.id,
        owner_id=_OWNER_ID,
        expected_version=created.record.version,
        target_status=ToolExecutionStatus.WAITING_APPROVAL,
    )
    running = await persistence.tool_execution_store.transition(
        execution.id,
        owner_id=_OWNER_ID,
        expected_version=waiting.version,
        target_status=ToolExecutionStatus.RUNNING,
    )
    decision = await asyncio.to_thread(
        persistence.approval_store.consume,
        principal_id=_OWNER_ID,
        run_id=run_id,
        tool_call_id=call_id,
        tool_name="publish_review",
        arguments=arguments,
    )
    if not decision.approved or started.record.status is not RunStatus.RUNNING:
        raise RuntimeError("review_publication_probe_prepare_invalid")
    if running.status is not ToolExecutionStatus.RUNNING:
        raise RuntimeError("review_publication_probe_execution_invalid")
    if resolution.request.id != approval.id:
        raise RuntimeError("review_publication_probe_resolution_invalid")
    if commit_publication:
        await publication_store.publish(command)
    return approval.id


async def _recover(
    persistence: PostgresPersistence,
    publication_store: PostgresReviewPublicationStore,
    *,
    known_approval_id: str,
    missing_approval_id: str,
) -> dict[str, object]:
    known = await _resume_one(
        persistence,
        publication_store,
        run_id=_KNOWN_RUN_ID,
        review_id=_KNOWN_REVIEW_ID,
        approval_id=known_approval_id,
    )
    missing = await _resume_one(
        persistence,
        publication_store,
        run_id=_MISSING_RUN_ID,
        review_id=_MISSING_REVIEW_ID,
        approval_id=missing_approval_id,
    )
    return {
        "phase": "recover",
        "process_id": os.getpid(),
        "known_completed": known[0],
        "known_result_event": known[1],
        "missing_unknown": not missing[0],
        "publisher_replayed": known[2] + missing[2] > 0,
    }


async def _resume_one(
    persistence: PostgresPersistence,
    publication_store: PostgresReviewPublicationStore,
    *,
    run_id: str,
    review_id: str,
    approval_id: str,
) -> tuple[bool, bool, int]:
    resolution = await asyncio.to_thread(
        persistence.approval_store.get_resolution,
        approval_id=approval_id,
        run_id=run_id,
        principal_id=_OWNER_ID,
    )
    if resolution is None:
        raise RuntimeError("review_publication_probe_resolution_missing")
    arguments = await asyncio.to_thread(
        persistence.approval_store.approved_arguments,
        resolution,
    )
    approval_store = _RecoveredApprovalStore(resolution, arguments)
    registry = _NoReplayRegistry(publication_store)
    spec = _review_spec(review_id)
    runtime = MultisourceReviewRuntime(
        registry=registry,
        run_catalog=ReviewRunCatalog(
            {
                run_id: ReviewRunBinding(
                    run_id=run_id,
                    owner_id=_OWNER_ID,
                    spec=spec,
                )
            }
        ),
        tool_execution_store=persistence.tool_execution_store,
    )

    async def emit(event: RuntimeEvent) -> None:
        await persistence.event_store.append(
            event_id=f"{run_id}-{event.type}",
            run_id=run_id,
            owner_id=_OWNER_ID,
            event_type=event.type,
            data=event.data,
            step=event.step,
        )

    request = RuntimeRequest(
        run_id=run_id,
        input_text="private review publication restart input",
        execution_context=ToolExecutionContext(
            principal_id=_OWNER_ID,
            roles=frozenset({"reviewer"}),
            approval_store=approval_store,
        ),
        context_identity=RuntimeContextIdentity(
            owner_id=_OWNER_ID,
            session_id=f"{run_id}-session",
        ),
    )
    approval = RuntimeApprovalResume(
        approval_id=resolution.request.id,
        tool_call_id=resolution.request.tool_call_id,
        tool_name=resolution.request.tool_name,
        arguments_digest=resolution.request.arguments_digest,
        decision=RuntimeApprovalDecision(resolution.status.value),
    )
    outcome = await runtime.resume(
        request,
        approval=approval,
        emit=emit,
        control=RuntimeControl(CancellationToken()),
    )
    execution = await persistence.tool_execution_store.get(
        _execution_id(resolution.request.tool_call_id),
        owner_id=_OWNER_ID,
    )
    run = await persistence.run_store.get(run_id, owner_id=_OWNER_ID)
    if execution is None or run is None:
        raise RuntimeError("review_publication_probe_state_missing")
    completed = outcome.status is RunStatus.COMPLETED
    if completed and execution.status is not ToolExecutionStatus.COMPLETED:
        raise RuntimeError("review_publication_probe_completion_invalid")
    if not completed and (
        outcome.failure is None
        or outcome.failure.code != "tool_result_unknown"
        or execution.status is not ToolExecutionStatus.UNKNOWN
    ):
        raise RuntimeError("review_publication_probe_unknown_invalid")
    if completed:
        terminal = TerminalCommit(
            run_id=run_id,
            owner_id=_OWNER_ID,
            expected_version=run.version,
            target_status=RunStatus.COMPLETED,
            event_id=f"{run_id}-completed",
            event_data={"status": "completed"},
            answer=outcome.answer,
            step=4,
        )
    else:
        failure = outcome.failure or RunFailure(
            code="tool_result_unknown",
            category="tool",
            public_message="Review publication result could not be confirmed",
            step=4,
        )
        terminal = TerminalCommit(
            run_id=run_id,
            owner_id=_OWNER_ID,
            expected_version=run.version,
            target_status=RunStatus.FAILED,
            event_id=f"{run_id}-failed",
            event_data={"status": "failed", "code": failure.code},
            failure=failure,
            step=4,
        )
    await persistence.event_store.commit_terminal(terminal)
    events = await persistence.event_store.list_for_run(
        run_id,
        owner_id=_OWNER_ID,
    )
    return (
        completed,
        sum(event.type == "review.result" for event in events) == 1,
        registry.publish_calls,
    )


@dataclass
class _RecoveredApprovalStore:
    resolution: Any
    arguments: dict[str, Any]

    def get_resolution(self, **_kwargs: object) -> Any:
        return self.resolution

    def approved_arguments(self, resolution: object) -> dict[str, Any]:
        if resolution is not self.resolution:
            raise RuntimeError("review_publication_probe_resolution_mismatch")
        return dict(self.arguments)

    def consume(self, **_kwargs: object) -> None:
        raise RuntimeError("review_publication_probe_publish_replayed")


@dataclass
class _NoReplayRegistry:
    publisher: PostgresReviewPublicationStore
    limits: ReviewScenarioLimits = ReviewScenarioLimits()
    publish_calls: int = 0

    async def execute(self, *_args: object, **_kwargs: object) -> None:
        self.publish_calls += 1
        raise RuntimeError("review_publication_probe_publish_replayed")


def _publication_arguments(review_id: str) -> dict[str, object]:
    return {
        "review_id": review_id,
        "expected_revision": _EXPECTED_REVISION,
        "requested_decision": "approve",
        "evidence_bundle_digest": _EVIDENCE_DIGEST,
    }


def _review_spec(review_id: str) -> ReviewRunSpec:
    return ReviewRunSpec(
        review_id=review_id,
        expected_revision=_EXPECTED_REVISION,
        image_asset_id="image-1",
        policy_topic="review policy",
        page_fixture_id="page-1",
        requested_decision="approve",
    )


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--phase",
        choices=("commit-crash", "recover"),
        required=True,
    )
    parser.add_argument("--known-approval-id")
    parser.add_argument("--missing-approval-id")
    return parser.parse_args()


def main() -> None:
    arguments = _arguments()
    coroutine = _run_probe(
        phase=arguments.phase,
        known_approval_id=arguments.known_approval_id,
        missing_approval_id=arguments.missing_approval_id,
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
