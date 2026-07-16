from __future__ import annotations

import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from backend.app.domain.run import (
    InvalidRunTransition,
    RunRecord,
    RunStatus,
    StoredRunEvent,
    ToolExecution,
    ToolExecutionStatus,
    UsageRecord,
)


NOW = datetime(2026, 7, 16, 4, 0, tzinfo=UTC)


class RunDomainTest(unittest.TestCase):
    def test_new_run_is_queued_and_hides_input_and_idempotency_key(self) -> None:
        raw_input = "private user request"
        raw_key = "private-idempotency-key"

        run = _new_run(input_text=raw_input, idempotency_key=raw_key)

        self.assertEqual(RunStatus.QUEUED, run.status)
        self.assertEqual(0, run.version)
        self.assertEqual(NOW, run.created_at)
        self.assertEqual(NOW, run.updated_at)
        self.assertIsNone(run.started_at)
        self.assertIsNone(run.finished_at)
        self.assertEqual(64, len(run.idempotency_key_digest))
        self.assertEqual(64, len(run.request_digest))
        self.assertNotIn(raw_input, repr(run))
        self.assertNotIn(raw_key, repr(run))
        self.assertNotIn(raw_input, repr(run.safe_summary()))
        self.assertNotIn(raw_key, repr(run.safe_summary()))

    def test_transition_returns_new_immutable_snapshots(self) -> None:
        queued = _new_run()
        running = queued.transition_to(
            RunStatus.RUNNING,
            at=NOW + timedelta(seconds=1),
        )
        waiting = running.transition_to(
            RunStatus.WAITING_APPROVAL,
            at=NOW + timedelta(seconds=2),
        )
        resumed = waiting.transition_to(
            RunStatus.RUNNING,
            at=NOW + timedelta(seconds=3),
        )
        completed = resumed.transition_to(
            RunStatus.COMPLETED,
            at=NOW + timedelta(seconds=4),
            answer="done",
        )

        self.assertEqual(RunStatus.QUEUED, queued.status)
        self.assertEqual(RunStatus.COMPLETED, completed.status)
        self.assertEqual(4, completed.version)
        self.assertEqual(NOW + timedelta(seconds=1), completed.started_at)
        self.assertEqual(NOW + timedelta(seconds=4), completed.finished_at)
        self.assertEqual("done", completed.answer)

    def test_all_supported_terminal_paths_are_available(self) -> None:
        cancelled = _new_run(run_id="run-cancelled").transition_to(
            RunStatus.CANCELLED,
            at=NOW + timedelta(seconds=1),
            error_code="cancelled_by_user",
            public_message="Run cancelled",
        )
        failed = _new_run(run_id="run-failed").transition_to(
            RunStatus.RUNNING,
            at=NOW + timedelta(seconds=1),
        ).transition_to(
            RunStatus.FAILED,
            at=NOW + timedelta(seconds=2),
            error_code="model_timeout",
            public_message="Model timed out",
        )
        waiting_failed = _new_run(run_id="run-waiting-failed").transition_to(
            RunStatus.RUNNING,
            at=NOW + timedelta(seconds=1),
        ).transition_to(
            RunStatus.WAITING_APPROVAL,
            at=NOW + timedelta(seconds=2),
        ).transition_to(
            RunStatus.FAILED,
            at=NOW + timedelta(seconds=3),
            error_code="approval_rejected",
            public_message="Approval rejected",
        )

        self.assertEqual(RunStatus.CANCELLED, cancelled.status)
        self.assertEqual(RunStatus.FAILED, failed.status)
        self.assertEqual(RunStatus.FAILED, waiting_failed.status)

    def test_invalid_and_terminal_transitions_are_rejected(self) -> None:
        queued = _new_run()
        with self.assertRaises(InvalidRunTransition):
            queued.transition_to(
                RunStatus.COMPLETED,
                at=NOW + timedelta(seconds=1),
                answer="not allowed",
            )

        running = queued.transition_to(
            RunStatus.RUNNING,
            at=NOW + timedelta(seconds=1),
        )
        with self.assertRaises(InvalidRunTransition):
            running.transition_to(RunStatus.QUEUED, at=NOW + timedelta(seconds=2))

        waiting = running.transition_to(
            RunStatus.WAITING_APPROVAL,
            at=NOW + timedelta(seconds=2),
        )
        with self.assertRaises(InvalidRunTransition):
            waiting.transition_to(
                RunStatus.COMPLETED,
                at=NOW + timedelta(seconds=3),
                answer="not allowed",
            )

        completed = running.transition_to(
            RunStatus.COMPLETED,
            at=NOW + timedelta(seconds=2),
            answer="done",
        )
        for target in RunStatus:
            with self.subTest(target=target):
                with self.assertRaises(InvalidRunTransition):
                    completed.transition_to(
                        target,
                        at=NOW + timedelta(seconds=3),
                    )

    def test_transition_payload_and_time_are_validated(self) -> None:
        queued = _new_run()
        with self.assertRaises(ValueError):
            queued.transition_to(
                RunStatus.RUNNING,
                at=NOW - timedelta(seconds=1),
            )

        running = queued.transition_to(
            RunStatus.RUNNING,
            at=NOW + timedelta(seconds=1),
        )
        with self.assertRaises(ValueError):
            running.transition_to(
                RunStatus.COMPLETED,
                at=NOW + timedelta(seconds=2),
            )
        with self.assertRaises(ValueError):
            running.transition_to(
                RunStatus.FAILED,
                at=NOW + timedelta(seconds=2),
            )
        with self.assertRaises(ValueError):
            running.transition_to(
                RunStatus.WAITING_APPROVAL,
                at=NOW + timedelta(seconds=2),
                answer="must not be discarded",
            )

    def test_usage_preserves_unknown_cost_and_validates_totals(self) -> None:
        usage = _usage(cost=None)

        self.assertIsNone(usage.estimated_cost_usd)
        self.assertEqual(15, usage.total_tokens)

        invalid_values = (
            {"input_tokens": -1},
            {"input_tokens": True},
            {"total_tokens": 16},
            {"sequence": 0},
            {"duration_ms": float("inf")},
            {"estimated_cost_usd": Decimal("NaN")},
            {"estimated_cost_usd": Decimal("-0.01")},
            {"cost_source": "unknown"},
        )
        for override in invalid_values:
            with self.subTest(override=override):
                values = {
                    "id": "usage-1",
                    "run_id": "run-1",
                    "sequence": 1,
                    "provider": "openai",
                    "model": "configured-model",
                    "input_tokens": 10,
                    "output_tokens": 5,
                    "total_tokens": 15,
                    "duration_ms": 12.5,
                    "estimated_cost_usd": Decimal("0.01"),
                    "cost_source": "provider",
                    "created_at": NOW,
                    **override,
                }
                with self.assertRaises(ValueError):
                    UsageRecord(**values)

        with self.assertRaises(ValueError):
            _usage(cost=None, cost_source="provider")
        with self.assertRaises(ValueError):
            _usage(cost=0.01)  # type: ignore[arg-type]

    def test_tool_execution_keeps_only_digests_and_bounded_summaries(self) -> None:
        raw_key = "tool-idempotency-key"
        raw_arguments = {"report_id": "private-report"}
        requested = ToolExecution.create(
            execution_id="execution-1",
            run_id="run-1",
            tool_call_id="call-1",
            tool_name="publish_report",
            arguments=raw_arguments,
            idempotency_key=raw_key,
            side_effecting=True,
            created_at=NOW,
        )
        running = requested.transition_to(
            ToolExecutionStatus.RUNNING,
            at=NOW + timedelta(seconds=1),
        )
        completed = running.transition_to(
            ToolExecutionStatus.COMPLETED,
            at=NOW + timedelta(seconds=2),
            result_summary="report published",
        )

        self.assertEqual(64, len(requested.arguments_digest))
        self.assertEqual(64, len(requested.idempotency_key_digest or ""))
        self.assertNotIn("private-report", repr(requested))
        self.assertNotIn(raw_key, repr(requested))
        self.assertNotIn("private-report", repr(requested.safe_summary()))
        self.assertNotIn(raw_key, repr(requested.safe_summary()))
        self.assertEqual("report published", completed.result_summary)
        with self.assertRaises(InvalidRunTransition):
            completed.transition_to(
                ToolExecutionStatus.RUNNING,
                at=NOW + timedelta(seconds=3),
            )

        with self.assertRaises(ValueError):
            ToolExecution.create(
                execution_id="execution-2",
                run_id="run-1",
                tool_call_id="call-2",
                tool_name="publish_report",
                arguments=raw_arguments,
                side_effecting=True,
                created_at=NOW,
            )

        safe_without_key = ToolExecution.create(
            execution_id="execution-restored",
            run_id="run-1",
            tool_call_id="call-restored",
            tool_name="read_report",
            arguments={"report_id": "report-1"},
            created_at=NOW,
        )
        with self.assertRaises(ValueError):
            replace(
                safe_without_key,
                side_effecting=True,
                status=ToolExecutionStatus.RUNNING,
                version=1,
                updated_at=NOW + timedelta(seconds=1),
                started_at=NOW + timedelta(seconds=1),
            )

    def test_tool_can_fail_while_waiting_without_claiming_it_started(self) -> None:
        requested = ToolExecution.create(
            execution_id="execution-waiting",
            run_id="run-1",
            tool_call_id="call-waiting",
            tool_name="publish_report",
            arguments={"report_id": "report-1"},
            side_effecting=True,
            idempotency_key="waiting-tool-key",
            created_at=NOW,
        )
        waiting = requested.transition_to(
            ToolExecutionStatus.WAITING_APPROVAL,
            at=NOW + timedelta(seconds=1),
        )
        failed = waiting.transition_to(
            ToolExecutionStatus.FAILED,
            at=NOW + timedelta(seconds=2),
            error_code="approval_rejected",
            public_message="Approval rejected",
        )

        self.assertIsNone(failed.started_at)
        self.assertEqual(NOW + timedelta(seconds=2), failed.finished_at)
        self.assertEqual("approval_rejected", failed.error_code)

        with self.assertRaises(ValueError):
            waiting.transition_to(
                ToolExecutionStatus.RUNNING,
                at=NOW + timedelta(milliseconds=500),
            )

    def test_tool_result_is_digested_without_retaining_raw_output(self) -> None:
        raw_result = {"private": "result-secret"}
        completed = ToolExecution.create(
            execution_id="execution-result",
            run_id="run-1",
            tool_call_id="call-result",
            tool_name="lookup_report",
            arguments={"report_id": "report-1"},
            created_at=NOW,
        ).transition_to(
            ToolExecutionStatus.RUNNING,
            at=NOW + timedelta(seconds=1),
        ).transition_to(
            ToolExecutionStatus.COMPLETED,
            at=NOW + timedelta(seconds=2),
            result=raw_result,
            result_summary="report found",
        )

        self.assertEqual(64, len(completed.result_digest or ""))
        self.assertFalse(hasattr(completed, "result"))
        self.assertNotIn("result-secret", repr(completed))

        with self.assertRaises(ValueError):
            ToolExecution.create(
                execution_id="execution-large-result",
                run_id="run-1",
                tool_call_id="call-large-result",
                tool_name="lookup_report",
                arguments={"report_id": "report-1"},
                created_at=NOW,
            ).transition_to(
                ToolExecutionStatus.RUNNING,
                at=NOW + timedelta(seconds=1),
            ).transition_to(
                ToolExecutionStatus.COMPLETED,
                at=NOW + timedelta(seconds=2),
                result={"content": "x" * 65_000},
                result_summary="bounded summary",
            )

        with self.assertRaises(ValueError):
            ToolExecution.create(
                execution_id="execution-invalid-unicode",
                run_id="run-1",
                tool_call_id="call-invalid-unicode",
                tool_name="lookup_report",
                arguments={"value": "invalid-\ud800-argument"},
                created_at=NOW,
            )
        with self.assertRaises(ValueError):
            ToolExecution.create(
                execution_id="execution-invalid-result",
                run_id="run-1",
                tool_call_id="call-invalid-result",
                tool_name="lookup_report",
                arguments={},
                created_at=NOW,
            ).transition_to(
                ToolExecutionStatus.RUNNING,
                at=NOW + timedelta(seconds=1),
            ).transition_to(
                ToolExecutionStatus.COMPLETED,
                at=NOW + timedelta(seconds=2),
                result={"value": "invalid-\ud800-result"},
                result_summary="safe summary",
            )

    def test_explicit_json_null_result_differs_from_omitted_result(self) -> None:
        omitted = ToolExecution.create(
            execution_id="execution-omitted",
            run_id="run-1",
            tool_call_id="call-omitted",
            tool_name="lookup_report",
            arguments={"report_id": "report-1"},
            created_at=NOW,
        ).transition_to(
            ToolExecutionStatus.RUNNING,
            at=NOW + timedelta(seconds=1),
        ).transition_to(
            ToolExecutionStatus.COMPLETED,
            at=NOW + timedelta(seconds=2),
            result_summary="no raw result supplied",
        )
        explicit_null = ToolExecution.create(
            execution_id="execution-null",
            run_id="run-1",
            tool_call_id="call-null",
            tool_name="lookup_report",
            arguments={"report_id": "report-1"},
            created_at=NOW,
        ).transition_to(
            ToolExecutionStatus.RUNNING,
            at=NOW + timedelta(seconds=1),
        ).transition_to(
            ToolExecutionStatus.COMPLETED,
            at=NOW + timedelta(seconds=2),
            result=None,
            result_summary="no raw result supplied",
        )

        self.assertNotEqual(omitted.result_digest, explicit_null.result_digest)

    def test_stored_event_normalizes_json_and_validates_sequence_and_time(self) -> None:
        payload = {"nested": {"value": 1}, "items": ("a", "b")}
        event = StoredRunEvent(
            id="event-1",
            run_id="run-1",
            sequence=1,
            type="run.started",
            step=0,
            data=payload,
            created_at=NOW,
        )
        payload["nested"]["value"] = 2

        self.assertEqual(1, event.data["nested"]["value"])
        self.assertEqual(["a", "b"], event.data["items"])
        self.assertNotIn("nested", repr(event))

        with self.assertRaises(ValueError):
            StoredRunEvent(
                id="event-2",
                run_id="run-1",
                sequence=0,
                type="run.started",
                data={},
                created_at=NOW,
            )

        with self.assertRaises(ValueError):
            StoredRunEvent(
                id="event-3",
                run_id="run-1",
                sequence=1,
                type="run.started",
                data={},
                created_at=NOW.replace(tzinfo=None),
            )
        for invalid_type in (".bad.", "run..started", "Run.started"):
            with self.subTest(invalid_type=invalid_type):
                with self.assertRaises(ValueError):
                    StoredRunEvent(
                        id="event-invalid-type",
                        run_id="run-1",
                        sequence=1,
                        type=invalid_type,
                        data={},
                        created_at=NOW,
                    )

    def test_run_request_rejects_non_object_options_and_invalid_unicode(self) -> None:
        with self.assertRaises(ValueError):
            RunRecord.create(
                run_id="run-options",
                session_id="session-1",
                owner_id="owner-1",
                runtime="manual",
                input_text="hello",
                idempotency_key="key-options",
                request_options=[],  # type: ignore[arg-type]
                created_at=NOW,
            )
        with self.assertRaises(ValueError):
            _new_run(input_text="invalid-\ud800-input")

        with self.assertRaises(ValueError):
            StoredRunEvent(
                id="event-invalid-unicode",
                run_id="run-1",
                sequence=1,
                type="run.started",
                data={"value": "invalid-\ud800-data"},
                created_at=NOW,
            )


def _new_run(
    *,
    run_id: str = "run-1",
    session_id: str = "session-1",
    owner_id: str = "owner-1",
    runtime: str = "manual",
    input_text: str = "hello",
    idempotency_key: str = "key-1",
) -> RunRecord:
    return RunRecord.create(
        run_id=run_id,
        session_id=session_id,
        owner_id=owner_id,
        runtime=runtime,
        input_text=input_text,
        idempotency_key=idempotency_key,
        created_at=NOW,
    )


def _usage(
    *,
    run_id: str = "run-1",
    cost: Decimal | None = Decimal("0.01"),
    cost_source: str | None = None,
) -> UsageRecord:
    return UsageRecord(
        id="usage-1",
        run_id=run_id,
        sequence=1,
        provider="openai",
        model="configured-model",
        input_tokens=10,
        output_tokens=5,
        total_tokens=15,
        duration_ms=12.5,
        estimated_cost_usd=cost,
        cost_source=cost_source or ("unknown" if cost is None else "provider"),
        created_at=NOW,
    )


if __name__ == "__main__":
    unittest.main()
