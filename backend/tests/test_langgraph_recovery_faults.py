from __future__ import annotations

import asyncio
import unittest
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from backend.app.agent import (
    CancellationToken,
    RuntimeApprovalDecision,
    RuntimeApprovalPause,
    RuntimeApprovalResume,
    RuntimeCheckpointContext,
    RuntimeControl,
    RuntimeEvent,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.agent.approval_runtime import (
    ApprovalLangGraphRuntime,
    PlannedToolCall,
)
from backend.app.agent.checkpoint_runtime import CheckpointedLangGraphRuntime
from backend.app.agent.replanning_runtime import (
    REPLANNING_STATE_VERSION,
    REPLANNING_WORKFLOW_KIND,
    PlanContext,
    PlanStep,
    PlanStepResult,
    ReplanningLangGraphRuntime,
    TaskPlan,
)
from backend.app.domain.run import RunFailure, RunRecord, RunStatus
from backend.app.services.run_coordinator import RunCoordinator
from backend.app.stores import InMemoryEventStore, InMemoryRunStore
from backend.app.tools import (
    InMemoryApprovalStore,
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolRisk,
)


NOW = datetime(2026, 7, 22, 6, 0, tzinfo=UTC)


class LangGraphRecoveryFaultTest(unittest.IsolatedAsyncioTestCase):
    async def test_checkpoint_read_failure_stops_before_delegate(self) -> None:
        delegate = _CountingRuntime()
        result = await CheckpointedLangGraphRuntime(
            delegate=delegate,
            checkpointer=_UnavailableSaver(),
        ).run(
            _request("checkpoint-read-failure"),
            emit=_ignore_event,
            control=_control(),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("checkpoint_unavailable", result.failure.code)
        self.assertEqual(0, delegate.calls)

    async def test_corrupt_checkpoint_commits_failed_diagnostic(self) -> None:
        saver = InMemorySaver()
        run_id = "corrupt-replanning-checkpoint"
        request = _request(run_id)
        await _seed_corrupt_replanning_checkpoint(saver, request)
        planner = _ScriptedPlanner()
        executor = _ScriptedExecutor()
        runtime = ReplanningLangGraphRuntime(
            planner=planner,
            executor=executor,
            checkpointer=saver,
        )

        result, events = await _execute_with_coordinator(runtime, run_id)

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("checkpoint_state_invalid", result.failure.code)
        self.assertEqual(["run.started", "run.failed"], _event_types(events))
        self.assertEqual(
            "checkpoint_state_invalid",
            events[-1].data["failure_code"],
        )
        self.assertEqual([], planner.contexts)
        self.assertEqual([], executor.calls)

    async def test_interrupted_read_only_step_resumes_in_new_runtime(self) -> None:
        saver = InMemorySaver()
        request = _request("interrupted-read-only")
        blocking_executor = _BlockingExecutor()
        first_task = asyncio.create_task(
            ReplanningLangGraphRuntime(
                planner=_ScriptedPlanner(
                    TaskPlan((PlanStep("fetch", "fetch_primary"),))
                ),
                executor=blocking_executor,
                checkpointer=saver,
            ).run(request, emit=_ignore_event, control=_control())
        )
        await asyncio.wait_for(blocking_executor.started.wait(), timeout=1)
        first_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first_task

        resumed_planner = _ScriptedPlanner()
        resumed_executor = _ScriptedExecutor(
            fetch_primary=PlanStepResult.completed("recovered answer")
        )
        result = await ReplanningLangGraphRuntime(
            planner=resumed_planner,
            executor=resumed_executor,
            checkpointer=saver,
        ).run(request, emit=_ignore_event, control=_control())

        self.assertEqual("recovered answer", result.answer)
        self.assertEqual(1, blocking_executor.calls)
        self.assertEqual(["fetch_primary"], resumed_executor.calls)
        self.assertEqual([], resumed_planner.contexts)

    async def test_read_only_tool_timeout_replans_with_diagnostics(self) -> None:
        planner = _ScriptedPlanner(
            TaskPlan((PlanStep("primary", "fetch_primary"),)),
            TaskPlan((PlanStep("backup", "fetch_backup"),)),
        )
        executor = _ScriptedExecutor(
            fetch_primary=PlanStepResult.failed(
                _failure("tool_timeout", retryable=True)
            ),
            fetch_backup=PlanStepResult.completed("backup answer"),
        )
        runtime = ReplanningLangGraphRuntime(
            planner=planner,
            executor=executor,
        )

        result, events = await _execute_with_coordinator(
            runtime,
            "read-only-tool-timeout",
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual("backup answer", result.answer)
        self.assertEqual(["fetch_primary", "fetch_backup"], executor.calls)
        self.assertEqual(2, len(planner.contexts))
        self.assertIn("plan.step.failed", _event_types(events))
        self.assertIn("plan.replanned", _event_types(events))

    async def test_waiting_approval_resumes_in_new_runtime_once(self) -> None:
        fixture = _approval_fixture("approval-shared-saver")
        paused = await _approval_runtime(fixture).run(
            fixture.request,
            emit=_ignore_event,
            control=_control(),
        )
        self.assertIsInstance(paused, RuntimeApprovalPause)
        self.assertEqual([], fixture.side_effects)
        approval = _approve(fixture, paused)

        completed = await _approval_runtime(
            fixture,
            planner=_unexpected_approval_planner,
        ).resume(
            fixture.request,
            approval=approval,
            emit=_ignore_event,
            control=_control(),
        )

        self.assertEqual(RunStatus.COMPLETED, completed.status)
        self.assertEqual(["quarterly-report"], fixture.side_effects)

    async def test_lost_approval_checkpoint_fails_without_side_effect(self) -> None:
        fixture = _approval_fixture("approval-lost-checkpoint")
        paused = await _approval_runtime(fixture).run(
            fixture.request,
            emit=_ignore_event,
            control=_control(),
        )
        self.assertIsInstance(paused, RuntimeApprovalPause)
        approval = _approve(fixture, paused)

        failed = await ApprovalLangGraphRuntime(
            registry=fixture.registry,
            approval_store=fixture.approval_store,
            planner=_unexpected_approval_planner,
            checkpointer=InMemorySaver(),
        ).resume(
            fixture.request,
            approval=approval,
            emit=_ignore_event,
            control=_control(),
        )

        self.assertEqual(RunStatus.FAILED, failed.status)
        self.assertEqual("approval_checkpoint_missing", failed.failure.code)
        self.assertEqual([], fixture.side_effects)

    async def test_approval_result_unknown_is_not_replayed(self) -> None:
        saver = _FailAfterEffectSaver()
        fixture = _approval_fixture(
            "approval-result-unknown",
            saver=saver,
            arm_after_effect=True,
        )
        paused = await _approval_runtime(fixture).run(
            fixture.request,
            emit=_ignore_event,
            control=_control(),
        )
        self.assertIsInstance(paused, RuntimeApprovalPause)
        approval = _approve(fixture, paused)

        first = await _approval_runtime(fixture).resume(
            fixture.request,
            approval=approval,
            emit=_ignore_event,
            control=_control(),
        )
        saver.disarm()
        events: list[RuntimeEvent] = []
        recovered = await _approval_runtime(
            fixture,
            planner=_unexpected_approval_planner,
        ).resume(
            fixture.request,
            approval=approval,
            emit=_collecting_sink(events),
            control=_control(),
        )

        self.assertEqual("approval_graph_failed", first.failure.code)
        self.assertEqual("side_effect_resume_unsafe", recovered.failure.code)
        self.assertEqual(["quarterly-report"], fixture.side_effects)
        self.assertEqual(["approval.stopped"], _runtime_event_types(events))
        self.assertEqual(
            "side_effect_outcome_unknown",
            events[0].data["reason"],
        )

    async def test_unknown_replanning_side_effect_emits_stop_without_replay(
        self,
    ) -> None:
        saver = InMemorySaver()
        request = _request("replanning-result-unknown")
        blocking_executor = _BlockingExecutor()
        first_task = asyncio.create_task(
            ReplanningLangGraphRuntime(
                planner=_ScriptedPlanner(
                    TaskPlan(
                        (
                            PlanStep(
                                "publish",
                                "publish_report",
                                side_effecting=True,
                            ),
                        )
                    )
                ),
                executor=blocking_executor,
                checkpointer=saver,
            ).run(request, emit=_ignore_event, control=_control())
        )
        await asyncio.wait_for(blocking_executor.started.wait(), timeout=1)
        first_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first_task

        replay_executor = _ScriptedExecutor(
            publish_report=PlanStepResult.completed("must not execute")
        )
        events: list[RuntimeEvent] = []
        result = await ReplanningLangGraphRuntime(
            planner=_ScriptedPlanner(),
            executor=replay_executor,
            checkpointer=saver,
        ).run(
            request,
            emit=_collecting_sink(events),
            control=_control(),
        )

        self.assertEqual("side_effect_resume_unsafe", result.failure.code)
        self.assertEqual(1, blocking_executor.calls)
        self.assertEqual([], replay_executor.calls)
        self.assertEqual(["plan.stopped"], _runtime_event_types(events))
        self.assertEqual(
            "side_effect_outcome_unknown",
            events[0].data["reason"],
        )

    async def test_side_effect_timeout_stops_without_replanning(self) -> None:
        planner = _ScriptedPlanner(
            TaskPlan(
                (
                    PlanStep(
                        "publish",
                        "publish_report",
                        side_effecting=True,
                    ),
                )
            ),
            TaskPlan((PlanStep("retry", "publish_report"),)),
        )
        executor = _ScriptedExecutor(
            publish_report=PlanStepResult.failed(
                _failure("tool_timeout", retryable=True)
            )
        )
        events: list[RuntimeEvent] = []

        result = await ReplanningLangGraphRuntime(
            planner=planner,
            executor=executor,
        ).run(
            _request("side-effect-timeout"),
            emit=_collecting_sink(events),
            control=_control(),
        )

        self.assertEqual("side_effect_replan_forbidden", result.failure.code)
        self.assertEqual(["publish_report"], executor.calls)
        self.assertEqual(1, len(planner.contexts))
        self.assertEqual("plan.stopped", events[-1].type)
        self.assertEqual("side_effecting_step", events[-1].data["reason"])

    async def test_waiting_approval_cancel_has_no_side_effect(self) -> None:
        run_id = "approval-wait-cancel"
        fixture = _approval_fixture(run_id)
        run_store = InMemoryRunStore(clock=lambda: NOW)
        event_store = InMemoryEventStore(run_store, clock=lambda: NOW)
        run = _run(run_id)
        await run_store.create(run)
        coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={"langgraph": _approval_runtime(fixture)},
            run_timeout_ms=1_000,
        )

        paused = await coordinator.execute(
            run_id,
            owner_id=run.owner_id,
            execution_context=fixture.base_context,
        )
        accepted = await coordinator.cancel(run_id, owner_id=run.owner_id)
        stored = await run_store.get(run_id, owner_id=run.owner_id)
        events = await event_store.list_for_run(run_id, owner_id=run.owner_id)

        self.assertEqual(RunStatus.WAITING_APPROVAL, paused.status)
        self.assertTrue(accepted)
        self.assertEqual(RunStatus.CANCELLED, stored.status)
        self.assertEqual([], fixture.side_effects)
        self.assertEqual(
            ["run.started", "run.waiting_approval", "run.cancelled"],
            _event_types(events),
        )


class _SeedState(TypedDict, total=False):
    workflow_kind: str
    state_version: int
    owner_scope: str
    plan_revision: int
    plan_steps: list[object]
    completed_steps: list[object]
    plan_signatures: list[str]
    execution_count: object
    replan_count: int


class _CountingRuntime:
    def __init__(self) -> None:
        self.calls = 0

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit, control
        self.calls += 1
        return RuntimeResult(status=RunStatus.COMPLETED, answer="unexpected")


class _UnavailableSaver(InMemorySaver):
    async def aget_tuple(self, config):
        del config
        raise OSError("injected checkpoint read failure")


class _FailAfterEffectSaver(InMemorySaver):
    def __init__(self) -> None:
        super().__init__()
        self._armed = False

    def arm(self) -> None:
        self._armed = True

    def disarm(self) -> None:
        self._armed = False

    async def aput_writes(self, config, writes, task_id, task_path="") -> None:
        if self._armed:
            raise OSError("injected checkpoint write failure")
        await super().aput_writes(config, writes, task_id, task_path)

    async def aput(self, config, checkpoint, metadata, new_versions):
        if self._armed:
            raise OSError("injected checkpoint write failure")
        return await super().aput(config, checkpoint, metadata, new_versions)


class _ScriptedPlanner:
    def __init__(self, *plans: TaskPlan) -> None:
        self._plans = list(plans)
        self.contexts: list[PlanContext] = []

    async def plan(self, request, *, context: PlanContext) -> TaskPlan:
        del request
        self.contexts.append(context)
        if not self._plans:
            raise AssertionError("planner was called more than expected")
        return self._plans.pop(0)


class _ScriptedExecutor:
    def __init__(self, **outcomes: PlanStepResult) -> None:
        self._outcomes = dict(outcomes)
        self.calls: list[str] = []

    async def execute(self, step, *, request, control) -> PlanStepResult:
        del request, control
        self.calls.append(step.operation)
        outcome = self._outcomes.get(step.operation)
        if outcome is None:
            raise AssertionError(f"unexpected operation: {step.operation}")
        return outcome


class _BlockingExecutor:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.calls = 0

    async def execute(self, step, *, request, control) -> PlanStepResult:
        del step, request, control
        self.calls += 1
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("blocking executor unexpectedly resumed")


@dataclass
class _ApprovalFixture:
    run_id: str
    approval_store: InMemoryApprovalStore
    registry: ToolRegistry
    saver: InMemorySaver
    base_context: ToolExecutionContext
    request: RuntimeRequest
    side_effects: list[str]


def _approval_fixture(
    run_id: str,
    *,
    saver: InMemorySaver | None = None,
    arm_after_effect: bool = False,
) -> _ApprovalFixture:
    checkpointer = saver if saver is not None else InMemorySaver()
    approval_store = InMemoryApprovalStore(clock=lambda: NOW)
    side_effects: list[str] = []

    def publish(arguments: dict[str, Any]) -> None:
        side_effects.append(arguments["title"])
        if arm_after_effect:
            if not isinstance(checkpointer, _FailAfterEffectSaver):
                raise AssertionError("fault saver is required")
            checkpointer.arm()

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="publish_report",
            description="Publish one report",
            input_schema={
                "type": "object",
                "properties": {"title": {"type": "string", "minLength": 1}},
                "required": ["title"],
                "additionalProperties": False,
            },
            handler=publish,
            allowed_roles=frozenset({"editor"}),
            risk_level=ToolRisk.HIGH,
            has_side_effects=True,
        )
    )
    base_context = ToolExecutionContext(
        principal_id="owner-a",
        roles=frozenset({"editor"}),
        approval_store=approval_store,
    )
    request = RuntimeRequest(
        run_id=run_id,
        input_text="publish the quarterly report",
        execution_context=base_context.for_run(run_id),
        checkpoint_context=RuntimeCheckpointContext.for_run(
            run_id=run_id,
            owner_id="owner-a",
        ),
    )
    return _ApprovalFixture(
        run_id=run_id,
        approval_store=approval_store,
        registry=registry,
        saver=checkpointer,
        base_context=base_context,
        request=request,
        side_effects=side_effects,
    )


def _approval_runtime(
    fixture: _ApprovalFixture,
    *,
    planner=None,
) -> ApprovalLangGraphRuntime:
    return ApprovalLangGraphRuntime(
        registry=fixture.registry,
        approval_store=fixture.approval_store,
        planner=planner or _approval_planner,
        approval_ttl=timedelta(minutes=1),
        checkpointer=fixture.saver,
    )


def _approval_planner(request) -> PlannedToolCall:
    del request
    return PlannedToolCall(
        call_id="call-publish-1",
        tool_name="publish_report",
        arguments={"title": "quarterly-report"},
    )


def _unexpected_approval_planner(request) -> PlannedToolCall:
    del request
    raise AssertionError("resume must not call the planner")


def _approve(
    fixture: _ApprovalFixture,
    pause: RuntimeApprovalPause,
) -> RuntimeApprovalResume:
    fixture.approval_store.resolve(
        approval_id=pause.approval_id,
        run_id=fixture.run_id,
        principal_id="owner-a",
        tool_call_id=pause.tool_call_id,
        tool_name=pause.tool_name,
        arguments_digest=pause.arguments_digest,
        decision="approve",
    )
    return RuntimeApprovalResume(
        approval_id=pause.approval_id,
        tool_call_id=pause.tool_call_id,
        tool_name=pause.tool_name,
        arguments_digest=pause.arguments_digest,
        decision=RuntimeApprovalDecision.APPROVED,
    )


def _failure(code: str, *, retryable: bool) -> RunFailure:
    return RunFailure(
        code=code,
        category="tool",
        public_message="A safe tool step failed",
        retryable=retryable,
    )


def _request(run_id: str) -> RuntimeRequest:
    return RuntimeRequest(
        run_id=run_id,
        input_text="recovery fault exercise",
        checkpoint_context=RuntimeCheckpointContext.for_run(
            run_id=run_id,
            owner_id="owner-a",
        ),
    )


def _run(run_id: str) -> RunRecord:
    return RunRecord.create(
        run_id=run_id,
        session_id=f"session-{run_id}",
        owner_id="owner-a",
        runtime="langgraph",
        input_text="recovery fault exercise",
        idempotency_key=f"key-{run_id}",
        created_at=NOW,
    )


async def _execute_with_coordinator(runtime, run_id: str):
    run_store = InMemoryRunStore(clock=lambda: NOW)
    event_store = InMemoryEventStore(run_store, clock=lambda: NOW)
    run = _run(run_id)
    await run_store.create(run)
    coordinator = RunCoordinator(
        run_store=run_store,
        event_store=event_store,
        runtimes={"langgraph": runtime},
        run_timeout_ms=1_000,
    )
    result = await coordinator.execute(run_id, owner_id=run.owner_id)
    events = await event_store.list_for_run(run_id, owner_id=run.owner_id)
    return result, events


async def _seed_corrupt_replanning_checkpoint(
    saver: InMemorySaver,
    request: RuntimeRequest,
) -> None:
    checkpoint_context = request.checkpoint_context
    if checkpoint_context is None:
        raise AssertionError("checkpoint context is required")
    graph = StateGraph(_SeedState)
    graph.add_node("seed", lambda _state: {})
    graph.add_edge(START, "seed")
    graph.add_edge("seed", END)
    await graph.compile(checkpointer=saver).ainvoke(
        _SeedState(
            workflow_kind=REPLANNING_WORKFLOW_KIND,
            state_version=REPLANNING_STATE_VERSION,
            owner_scope=checkpoint_context.owner_scope,
            plan_revision=0,
            plan_steps=[],
            completed_steps=[],
            plan_signatures=[],
            execution_count="corrupt",
            replan_count=0,
        ),
        {"configurable": {"thread_id": checkpoint_context.thread_id}},
    )


def _control() -> RuntimeControl:
    return RuntimeControl(CancellationToken())


async def _ignore_event(event: RuntimeEvent) -> None:
    del event


def _collecting_sink(events: list[RuntimeEvent]):
    async def collect(event: RuntimeEvent) -> None:
        events.append(event)

    return collect


def _runtime_event_types(events: list[RuntimeEvent]) -> list[str]:
    return [event.type for event in events]


def _event_types(events) -> list[str]:
    return [event.type for event in events]


if __name__ == "__main__":
    unittest.main()
