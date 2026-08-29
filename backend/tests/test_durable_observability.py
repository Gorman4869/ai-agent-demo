from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from backend.app.agent import RuntimeEvent, RuntimeResult
from backend.app.container import ApplicationContainer
from backend.app.domain.run import RunFailure, RunRecord, RunStatus
from backend.app.main import create_app
from backend.app.observability import (
    EventRunObservability,
    InMemoryMetricsSink,
    InMemoryTraceSink,
    RunTelemetryExporter,
    TraceStatus,
)
from backend.app.security import Principal, StaticTokenAuthenticator
from backend.app.services import RunCoordinator
from backend.app.settings import Settings
from backend.app.stores import InMemoryEventStore, InMemoryRunStore


class DurableObservabilityScenarioTest(unittest.IsolatedAsyncioTestCase):
    async def test_success_exports_correlated_spans_metrics_and_cost(self) -> None:
        scenario = await _execute_scenario(
            "success",
            events=(
                RuntimeEvent(
                    type="plan.step.started",
                    step=1,
                    data={"revision": 1, "attempt": 1},
                ),
                RuntimeEvent(
                    type="plan.step.completed",
                    step=1,
                    data={"revision": 1, "attempt": 1},
                ),
                RuntimeEvent(
                    type="model.output.delta",
                    step=2,
                    data={"delta": "private answer content"},
                ),
                _usage_event(step=3, cost=0.00125, cost_source="provider"),
            ),
            result=RuntimeResult(
                status=RunStatus.COMPLETED,
                answer="private answer content",
                step=3,
            ),
        )

        self.assertEqual(RunStatus.COMPLETED, scenario.record.status)
        self.assertEqual(
            {"run", "node", "model"},
            {span.layer.value for span in scenario.snapshot.spans},
        )
        runtime_span = next(
            span
            for span in scenario.snapshot.spans
            if span.name == "runtime.manual"
        )
        self.assertEqual("success", runtime_span.run_id)
        self.assertIsNotNone(runtime_span.duration_ms)
        self.assertGreaterEqual(runtime_span.duration_ms, 0)
        self.assertEqual(
            Decimal("0.00125"),
            scenario.snapshot.cost_summary.estimated_cost_usd,
        )
        self.assertEqual("provider", scenario.snapshot.cost_summary.cost_source)
        self.assertEqual(7, scenario.snapshot.cost_summary.total_tokens)
        self.assertEqual(
            {span.id for span in scenario.snapshot.spans},
            {span.id for span in scenario.trace_sink.spans(run_id="success")},
        )
        self.assertTrue(scenario.metrics_sink.metrics(run_id="success"))
        self.assertNotIn("private answer content", repr(scenario.snapshot.to_record()))

        rebuilt = await EventRunObservability(scenario.event_store).snapshot(
            "success",
            owner_id="observability-owner",
        )
        self.assertEqual(scenario.snapshot, rebuilt)

    async def test_retry_reports_attempt_duration_and_metric(self) -> None:
        scenario = await _execute_scenario(
            "retry",
            events=(
                RuntimeEvent(
                    type="model.retrying",
                    step=1,
                    data={"attempt": 1, "model_duration_ms": 4.5},
                ),
                _usage_event(step=2),
            ),
            result=RuntimeResult(
                status=RunStatus.COMPLETED,
                answer="ok",
                step=2,
            ),
        )

        retry_span = next(
            span
            for span in scenario.snapshot.spans
            if span.status is TraceStatus.RETRYING
        )
        self.assertEqual("model", retry_span.layer.value)
        self.assertEqual(1, retry_span.step)
        self.assertEqual(1, retry_span.attempt)
        self.assertEqual(4.5, retry_span.duration_ms)
        self.assertIn(
            "agent.model.retry",
            {metric.name for metric in scenario.snapshot.metrics},
        )

    async def test_tool_retry_reports_backoff_without_argument_content(self) -> None:
        scenario = await _execute_scenario(
            "tool-retry",
            events=(
                RuntimeEvent(
                    type="tool.retrying",
                    step=1,
                    data={
                        "id": "call-1",
                        "name": "safe_lookup",
                        "attempt": 1,
                        "delay_ms": 125,
                        "error_code": "tool_io_error",
                    },
                ),
            ),
            result=RuntimeResult(
                status=RunStatus.COMPLETED,
                answer="ok",
                step=1,
            ),
        )

        retry_span = next(
            span
            for span in scenario.snapshot.spans
            if span.status is TraceStatus.RETRYING
        )
        self.assertEqual("tool", retry_span.layer.value)
        self.assertEqual("tool.safe_lookup", retry_span.name)
        self.assertEqual(125, retry_span.duration_ms)
        self.assertIn(
            "agent.tool.retry",
            {metric.name for metric in scenario.snapshot.metrics},
        )

    async def test_cumulative_usage_snapshots_are_not_summed_twice(self) -> None:
        scenario = await _execute_scenario(
            "usage-snapshots",
            events=(
                RuntimeEvent(
                    type="model.usage",
                    step=1,
                    data={
                        "scope": "run",
                        "requests": 1,
                        "input_tokens": 2,
                        "output_tokens": 3,
                        "total_tokens": 5,
                        "estimated_cost_usd": 0.001,
                        "cost_source": "provider",
                    },
                ),
                RuntimeEvent(
                    type="model.usage",
                    step=2,
                    data={
                        "scope": "run",
                        "requests": 2,
                        "input_tokens": 3,
                        "output_tokens": 4,
                        "total_tokens": 7,
                        "estimated_cost_usd": 0.002,
                        "cost_source": "provider",
                    },
                ),
            ),
            result=RuntimeResult(
                status=RunStatus.COMPLETED,
                answer="ok",
                step=2,
            ),
        )

        self.assertEqual(2, len(scenario.snapshot.usage_ledger))
        self.assertEqual(2, scenario.snapshot.cost_summary.entry_count)
        self.assertEqual(7, scenario.snapshot.cost_summary.total_tokens)
        self.assertEqual(
            Decimal("0.002"),
            scenario.snapshot.cost_summary.estimated_cost_usd,
        )

    async def test_tool_denial_reports_tool_layer_and_step(self) -> None:
        scenario = await _execute_scenario(
            "tool-denial",
            events=(
                RuntimeEvent(
                    type="tool.started",
                    step=2,
                    data={"id": "call-1", "name": "write_file"},
                ),
                RuntimeEvent(
                    type="tool.failed",
                    step=2,
                    data={
                        "id": "call-1",
                        "name": "write_file",
                        "ok": False,
                        "error_code": "tool_not_allowed",
                    },
                ),
            ),
            result=_failed_result(
                code="tool_not_allowed",
                category="authorization",
                step=2,
            ),
        )

        tool_span = next(
            span
            for span in scenario.snapshot.spans
            if span.layer.value == "tool"
        )
        self.assertEqual("failed", tool_span.status.value)
        self.assertEqual(2, tool_span.step)
        self.assertEqual("tool_not_allowed", tool_span.error_code)
        self.assertIsNone(scenario.snapshot.cost_summary)

    async def test_model_failure_reports_model_layer_without_zero_cost(self) -> None:
        scenario = await _execute_scenario(
            "model-failure",
            events=(),
            result=_failed_result(
                code="model_execution_failed",
                category="model",
                step=1,
            ),
        )

        model_span = next(
            span
            for span in scenario.snapshot.spans
            if span.layer.value == "model"
        )
        self.assertEqual("failed", model_span.status.value)
        self.assertEqual(1, model_span.step)
        self.assertEqual("model_execution_failed", model_span.error_code)
        self.assertIsNone(scenario.snapshot.cost_summary)

    async def test_rag_failure_reports_context_layer_and_safe_code(self) -> None:
        scenario = await _execute_scenario(
            "rag-failure",
            events=(
                RuntimeEvent(
                    type="context.failed",
                    step=0,
                    data={"code": "context_unavailable"},
                ),
            ),
            result=_failed_result(
                code="context_unavailable",
                category="context",
                step=0,
            ),
        )

        context_span = next(
            span
            for span in scenario.snapshot.spans
            if span.name == "context.prepare"
        )
        self.assertEqual("node", context_span.layer.value)
        self.assertEqual(0, context_span.step)
        self.assertEqual("context_unavailable", context_span.error_code)
        self.assertNotIn("private", repr(context_span.to_record()))

    async def test_exporter_failure_does_not_rewrite_durable_success(self) -> None:
        with self.assertLogs(
            "backend.app.services.run_coordinator",
            level="WARNING",
        ) as logs:
            scenario = await _execute_scenario(
                "sink-failure",
                events=(_usage_event(step=1),),
                result=RuntimeResult(
                    status=RunStatus.COMPLETED,
                    answer="ok",
                    step=1,
                ),
                trace_sink=_FailingTraceSink(),
            )

        self.assertEqual(RunStatus.COMPLETED, scenario.record.status)
        self.assertIn("run telemetry export failed", logs.output[0])
        self.assertNotIn("private exporter detail", logs.output[0])


class DurableObservabilityApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.owner = Principal("observability-owner")
        self.container = ApplicationContainer.create(
            settings=Settings.from_environment({}),
            runtimes={
                "manual": _ScenarioRuntime(
                    events=(_usage_event(step=1),),
                    result=RuntimeResult(
                        status=RunStatus.COMPLETED,
                        answer="safe answer",
                        step=1,
                    ),
                )
            },
            authenticator=StaticTokenAuthenticator(
                {
                    "owner-token": self.owner,
                    "other-token": Principal("other-owner"),
                }
            ),
        )
        self.client = TestClient(create_app(container=self.container))

    def test_owner_can_query_and_cross_owner_is_hidden(self) -> None:
        run = _run("api-observability")
        asyncio.run(self.container.run_store.create(run))
        completed = asyncio.run(
            self.container.run_coordinator.execute(
                run.id,
                owner_id=run.owner_id,
            )
        )
        self.assertEqual(RunStatus.COMPLETED, completed.status)

        response = self.client.get(
            f"/api/durable/runs/{run.id}/observability",
            headers={"Authorization": "Bearer owner-token"},
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(run.id, payload["run_id"])
        self.assertEqual("7", str(payload["cost_summary"]["total_tokens"]))
        self.assertIsNone(payload["cost_summary"]["estimated_cost_usd"])
        self.assertEqual("unknown", payload["cost_summary"]["cost_source"])
        self.assertIn("run", {span["layer"] for span in payload["spans"]})

        denied = self.client.get(
            f"/api/durable/runs/{run.id}/observability",
            headers={"Authorization": "Bearer other-token"},
        )
        self.assertEqual(404, denied.status_code)


class _ScenarioRuntime:
    def __init__(
        self,
        *,
        events: tuple[RuntimeEvent, ...],
        result: RuntimeResult,
    ) -> None:
        self._events = events
        self._result = result

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, control
        for event in self._events:
            await emit(event)
        return self._result


class _FailingTraceSink:
    async def record(self, span) -> None:
        del span
        raise RuntimeError("private exporter detail")


class _Scenario:
    def __init__(
        self,
        *,
        record: RunRecord,
        snapshot,
        event_store: InMemoryEventStore,
        trace_sink: InMemoryTraceSink | _FailingTraceSink,
        metrics_sink: InMemoryMetricsSink,
    ) -> None:
        self.record = record
        self.snapshot = snapshot
        self.event_store = event_store
        self.trace_sink = trace_sink
        self.metrics_sink = metrics_sink


async def _execute_scenario(
    run_id: str,
    *,
    events: tuple[RuntimeEvent, ...],
    result: RuntimeResult,
    trace_sink: InMemoryTraceSink | _FailingTraceSink | None = None,
) -> _Scenario:
    run_store = InMemoryRunStore()
    event_store = InMemoryEventStore(run_store)
    run = _run(run_id)
    await run_store.create(run)
    observability = EventRunObservability(event_store)
    resolved_trace_sink = trace_sink or InMemoryTraceSink()
    metrics_sink = InMemoryMetricsSink()
    coordinator = RunCoordinator(
        run_store=run_store,
        event_store=event_store,
        runtimes={
            "manual": _ScenarioRuntime(events=events, result=result)
        },
        event_observer=RunTelemetryExporter(
            observability,
            trace_sink=resolved_trace_sink,
            metrics_sink=metrics_sink,
        ),
        run_timeout_ms=1_000,
    )
    record = await coordinator.execute(run.id, owner_id=run.owner_id)
    snapshot = await observability.snapshot(run.id, owner_id=run.owner_id)
    return _Scenario(
        record=record,
        snapshot=snapshot,
        event_store=event_store,
        trace_sink=resolved_trace_sink,
        metrics_sink=metrics_sink,
    )


def _run(run_id: str) -> RunRecord:
    return RunRecord.create(
        run_id=run_id,
        session_id=f"{run_id}-session",
        owner_id="observability-owner",
        runtime="manual",
        input_text="private input that must not enter telemetry",
        idempotency_key=f"{run_id}-key",
        created_at=datetime.now(UTC),
    )


def _usage_event(
    *,
    step: int,
    cost: float | None = None,
    cost_source: str = "unknown",
) -> RuntimeEvent:
    return RuntimeEvent(
        type="model.usage",
        step=step,
        data={
            "scope": "run",
            "provider": "fake-provider",
            "model": "fake-model-v1",
            "requests": 1,
            "input_tokens": 3,
            "output_tokens": 4,
            "total_tokens": 7,
            "estimated_cost_usd": cost,
            "cost_source": cost_source,
        },
    )


def _failed_result(*, code: str, category: str, step: int) -> RuntimeResult:
    return RuntimeResult(
        status=RunStatus.FAILED,
        failure=RunFailure(
            code=code,
            category=category,
            public_message="Safe failure",
            step=step,
        ),
        step=step,
    )


if __name__ == "__main__":
    unittest.main()
