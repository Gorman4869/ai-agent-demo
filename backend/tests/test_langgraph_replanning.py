from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime

from langgraph.checkpoint.memory import InMemorySaver

from backend.app.agent import (
    CancellationToken,
    RuntimeCheckpointContext,
    RuntimeControl,
    RuntimeEvent,
    RuntimeRequest,
)
from backend.app.agent.replanning_runtime import (
    PlanContext,
    PlanStep,
    PlanStepResult,
    ReplanningLangGraphRuntime,
    TaskPlan,
)
from backend.app.domain.run import RunFailure, RunRecord, RunStatus
from backend.app.services.run_coordinator import RunCoordinator
from backend.app.stores import InMemoryEventStore, InMemoryRunStore


NOW = datetime(2026, 7, 22, 2, 0, tzinfo=UTC)


class ReplanningLangGraphRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_coordinator_persists_plan_events_and_terminal_result(
        self,
    ) -> None:
        run_store = InMemoryRunStore()
        event_store = InMemoryEventStore(run_store)
        run = RunRecord.create(
            run_id="coordinator-replan",
            session_id="session-1",
            owner_id="owner-a",
            runtime="langgraph",
            input_text="research question",
            idempotency_key="coordinator-replan-key",
            created_at=NOW,
        )
        await run_store.create(run)
        planner = _ScriptedPlanner(
            TaskPlan((PlanStep("primary", "fetch_primary"),)),
            TaskPlan((PlanStep("backup", "fetch_backup"),)),
        )
        executor = _ScriptedExecutor(
            fetch_primary=PlanStepResult.failed(
                _failure("tool_timeout", retryable=True)
            ),
            fetch_backup=PlanStepResult.completed("durable answer"),
        )
        coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={
                "langgraph": ReplanningLangGraphRuntime(
                    planner=planner,
                    executor=executor,
                )
            },
            run_timeout_ms=1_000,
        )

        result = await coordinator.execute(run.id, owner_id=run.owner_id)
        events = await event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual("durable answer", result.answer)
        self.assertEqual(
            [
                "run.started",
                "plan.created",
                "plan.step.started",
                "plan.step.failed",
                "plan.replanned",
                "plan.step.started",
                "plan.step.completed",
                "run.completed",
            ],
            [event.type for event in events],
        )
        self.assertEqual(list(range(1, 9)), [event.sequence for event in events])

    async def test_dynamic_plan_executes_and_persists_explainable_state(
        self,
    ) -> None:
        secret = "private-customer-question"
        planner = _ScriptedPlanner(
            TaskPlan(
                (
                    PlanStep("analyze", "analyze_request"),
                    PlanStep("collect", "collect_evidence"),
                    PlanStep("compose", "compose_answer"),
                )
            )
        )
        executor = _ScriptedExecutor(
            analyze_request=PlanStepResult.completed("analyzed"),
            collect_evidence=PlanStepResult.completed("evidence ready"),
            compose_answer=PlanStepResult.completed("final answer"),
        )
        events: list[RuntimeEvent] = []
        request = _request("dynamic-plan", input_text=secret)
        runtime = ReplanningLangGraphRuntime(
            planner=planner,
            executor=executor,
        )

        result = await runtime.run(
            request,
            emit=_collecting_sink(events),
            control=_control(),
        )
        values = await _checkpoint_values(runtime.checkpointer, request)

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual("final answer", result.answer)
        self.assertEqual(
            ["analyze_request", "collect_evidence", "compose_answer"],
            executor.calls,
        )
        self.assertEqual(1, values["plan_revision"])
        self.assertEqual(3, values["execution_count"])
        self.assertEqual(3, len(values["completed_steps"]))
        self.assertNotIn(secret, repr(await _checkpoint_tuple(runtime.checkpointer, request)))
        self.assertEqual(
            [
                "plan.created",
                "plan.step.started",
                "plan.step.completed",
                "plan.step.started",
                "plan.step.completed",
                "plan.step.started",
                "plan.step.completed",
            ],
            [event.type for event in events],
        )

    async def test_retryable_whitelisted_failure_uses_an_alternate_plan(
        self,
    ) -> None:
        planner = _ScriptedPlanner(
            TaskPlan(
                (
                    PlanStep("primary", "fetch_primary"),
                    PlanStep("draft", "compose_answer"),
                )
            ),
            TaskPlan(
                (
                    PlanStep("backup", "fetch_backup"),
                    PlanStep("final", "compose_answer"),
                )
            ),
        )
        executor = _ScriptedExecutor(
            fetch_primary=PlanStepResult.failed(
                _failure("tool_timeout", retryable=True)
            ),
            fetch_backup=PlanStepResult.completed("backup evidence"),
            compose_answer=PlanStepResult.completed("recovered answer"),
        )
        events: list[RuntimeEvent] = []

        result = await ReplanningLangGraphRuntime(
            planner=planner,
            executor=executor,
            max_steps=4,
        ).run(
            _request("retryable-route"),
            emit=_collecting_sink(events),
            control=_control(),
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual("recovered answer", result.answer)
        self.assertEqual(
            ["fetch_primary", "fetch_backup", "compose_answer"],
            executor.calls,
        )
        self.assertEqual(2, len(planner.contexts))
        self.assertEqual("tool_timeout", planner.contexts[1].failure.code)
        self.assertIn("plan.replanned", [event.type for event in events])

    async def test_failure_flag_cannot_bypass_retryability_or_category_rules(
        self,
    ) -> None:
        cases = (
            _failure("tool_timeout", retryable=False),
            RunFailure(
                code="tool_timeout",
                category="authorization",
                public_message="Denied",
                retryable=True,
            ),
        )

        for index, failure in enumerate(cases):
            with self.subTest(index=index):
                planner = _ScriptedPlanner(
                    TaskPlan((PlanStep("fetch", "fetch_primary"),)),
                    TaskPlan((PlanStep("backup", "fetch_backup"),)),
                )
                executor = _ScriptedExecutor(
                    fetch_primary=PlanStepResult.failed(failure),
                )

                result = await ReplanningLangGraphRuntime(
                    planner=planner,
                    executor=executor,
                ).run(
                    _request(f"non-retryable-{index}"),
                    emit=_ignore_event,
                    control=_control(),
                )

                self.assertEqual(RunStatus.FAILED, result.status)
                self.assertEqual("tool_timeout", result.failure.code)
                self.assertEqual(["fetch_primary"], executor.calls)
                self.assertEqual(1, len(planner.contexts))

    async def test_replan_budget_exhaustion_stops_without_retrying_step(
        self,
    ) -> None:
        planner = _ScriptedPlanner(
            TaskPlan((PlanStep("fetch", "fetch_primary"),)),
        )
        executor = _ScriptedExecutor(
            fetch_primary=PlanStepResult.failed(
                _failure("tool_timeout", retryable=True)
            ),
        )

        result = await ReplanningLangGraphRuntime(
            planner=planner,
            executor=executor,
            max_replans=0,
        ).run(
            _request("replan-budget"),
            emit=_ignore_event,
            control=_control(),
        )

        self.assertEqual("replan_budget_exhausted", result.failure.code)
        self.assertEqual(["fetch_primary"], executor.calls)
        self.assertEqual(1, len(planner.contexts))

    async def test_replan_cannot_exceed_remaining_step_budget(self) -> None:
        planner = _ScriptedPlanner(
            TaskPlan((PlanStep("fetch", "fetch_primary"),)),
            TaskPlan(
                (
                    PlanStep("backup", "fetch_backup"),
                    PlanStep("compose", "compose_answer"),
                )
            ),
        )
        executor = _ScriptedExecutor(
            fetch_primary=PlanStepResult.failed(
                _failure("tool_timeout", retryable=True)
            ),
        )

        result = await ReplanningLangGraphRuntime(
            planner=planner,
            executor=executor,
            max_steps=2,
        ).run(
            _request("step-budget"),
            emit=_ignore_event,
            control=_control(),
        )

        self.assertEqual("plan_step_budget_exceeded", result.failure.code)
        self.assertEqual(["fetch_primary"], executor.calls)
        self.assertEqual(2, len(planner.contexts))
        self.assertEqual(1, planner.contexts[1].remaining_step_budget)

    async def test_plan_loop_detection_ignores_cosmetic_step_ids(self) -> None:
        planner = _ScriptedPlanner(
            TaskPlan((PlanStep("primary", "fetch_primary"),)),
            TaskPlan((PlanStep("renamed", "fetch_primary"),)),
        )
        executor = _ScriptedExecutor(
            fetch_primary=PlanStepResult.failed(
                _failure("tool_timeout", retryable=True)
            ),
        )

        result = await ReplanningLangGraphRuntime(
            planner=planner,
            executor=executor,
        ).run(
            _request("loop-detection"),
            emit=_ignore_event,
            control=_control(),
        )

        self.assertEqual("replan_loop_detected", result.failure.code)
        self.assertEqual(["fetch_primary"], executor.calls)

    async def test_side_effecting_failure_is_never_replanned(self) -> None:
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
            ),
        )

        result = await ReplanningLangGraphRuntime(
            planner=planner,
            executor=executor,
        ).run(
            _request("side-effect-failure"),
            emit=_ignore_event,
            control=_control(),
        )

        self.assertEqual("side_effect_replan_forbidden", result.failure.code)
        self.assertEqual(["publish_report"], executor.calls)
        self.assertEqual(1, len(planner.contexts))

    async def test_replan_cannot_repeat_a_completed_side_effect(self) -> None:
        planner = _ScriptedPlanner(
            TaskPlan(
                (
                    PlanStep(
                        "publish",
                        "publish_report",
                        side_effecting=True,
                    ),
                    PlanStep("fetch", "fetch_primary"),
                )
            ),
            TaskPlan(
                (
                    PlanStep(
                        "publish-again",
                        "publish_report",
                        side_effecting=True,
                    ),
                )
            ),
        )
        executor = _ScriptedExecutor(
            publish_report=PlanStepResult.completed("published"),
            fetch_primary=PlanStepResult.failed(
                _failure("tool_timeout", retryable=True)
            ),
        )

        result = await ReplanningLangGraphRuntime(
            planner=planner,
            executor=executor,
        ).run(
            _request("completed-side-effect"),
            emit=_ignore_event,
            control=_control(),
        )

        self.assertEqual(
            "replan_side_effect_replay_forbidden",
            result.failure.code,
        )
        self.assertEqual(["publish_report", "fetch_primary"], executor.calls)

    async def test_approval_step_is_not_executed_or_replanned(self) -> None:
        planner = _ScriptedPlanner(
            TaskPlan(
                (
                    PlanStep(
                        "publish",
                        "publish_report",
                        side_effecting=True,
                        requires_approval=True,
                    ),
                )
            ),
        )
        executor = _ScriptedExecutor()

        result = await ReplanningLangGraphRuntime(
            planner=planner,
            executor=executor,
        ).run(
            _request("approval-boundary"),
            emit=_ignore_event,
            control=_control(),
        )

        self.assertEqual("approval_step_requires_interrupt", result.failure.code)
        self.assertEqual([], executor.calls)
        self.assertEqual(1, len(planner.contexts))

    async def test_pre_cancelled_run_does_not_plan_or_execute(self) -> None:
        planner = _ScriptedPlanner(
            TaskPlan((PlanStep("fetch", "fetch_primary"),)),
        )
        executor = _ScriptedExecutor(
            fetch_primary=PlanStepResult.completed("done"),
        )
        control = _control()
        control.cancellation_token.cancel("cancelled_by_user")

        result = await ReplanningLangGraphRuntime(
            planner=planner,
            executor=executor,
        ).run(
            _request("pre-cancelled"),
            emit=_ignore_event,
            control=control,
        )

        self.assertEqual(RunStatus.CANCELLED, result.status)
        self.assertEqual("cancelled_by_user", result.failure.code)
        self.assertEqual([], planner.contexts)
        self.assertEqual([], executor.calls)

    async def test_terminal_checkpoint_replays_without_planner_or_executor(
        self,
    ) -> None:
        saver = InMemorySaver()
        request = _request("terminal-replay", input_text="sensitive-input")
        first_planner = _ScriptedPlanner(
            TaskPlan((PlanStep("compose", "compose_answer"),)),
        )
        first_executor = _ScriptedExecutor(
            compose_answer=PlanStepResult.completed("persisted answer"),
        )
        first = await ReplanningLangGraphRuntime(
            planner=first_planner,
            executor=first_executor,
            checkpointer=saver,
        ).run(request, emit=_ignore_event, control=_control())
        replay_planner = _ScriptedPlanner(
            TaskPlan((PlanStep("unexpected", "must_not_plan"),)),
        )
        replay_executor = _ScriptedExecutor(
            must_not_plan=PlanStepResult.completed("unexpected"),
        )
        replay_events: list[RuntimeEvent] = []

        replay = await ReplanningLangGraphRuntime(
            planner=replay_planner,
            executor=replay_executor,
            checkpointer=saver,
        ).run(
            request,
            emit=_collecting_sink(replay_events),
            control=_control(),
        )

        self.assertEqual("persisted answer", first.answer)
        self.assertEqual(first, replay)
        self.assertEqual([], replay_planner.contexts)
        self.assertEqual([], replay_executor.calls)
        self.assertEqual([], replay_events)

    async def test_cancelled_read_only_node_resumes_from_shared_checkpoint(
        self,
    ) -> None:
        saver = InMemorySaver()
        request = _request("read-only-resume")
        planner = _ScriptedPlanner(
            TaskPlan((PlanStep("fetch", "fetch_primary"),)),
        )
        blocking_executor = _BlockingExecutor()
        first_runtime = ReplanningLangGraphRuntime(
            planner=planner,
            executor=blocking_executor,
            checkpointer=saver,
        )
        first_task = asyncio.create_task(
            first_runtime.run(
                request,
                emit=_ignore_event,
                control=_control(),
            )
        )
        await asyncio.wait_for(blocking_executor.started.wait(), timeout=1)
        first_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first_task

        resume_planner = _ScriptedPlanner(
            TaskPlan((PlanStep("unexpected", "must_not_plan"),)),
        )
        resume_executor = _ScriptedExecutor(
            fetch_primary=PlanStepResult.completed("resumed answer"),
        )
        resumed = await ReplanningLangGraphRuntime(
            planner=resume_planner,
            executor=resume_executor,
            checkpointer=saver,
        ).run(request, emit=_ignore_event, control=_control())

        self.assertEqual("resumed answer", resumed.answer)
        self.assertEqual(1, blocking_executor.calls)
        self.assertEqual(["fetch_primary"], resume_executor.calls)
        self.assertEqual([], resume_planner.contexts)

    async def test_unknown_side_effect_outcome_fails_closed_without_replay(
        self,
    ) -> None:
        saver = InMemorySaver()
        request = _request("side-effect-resume")
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
        )
        blocking_executor = _BlockingExecutor()
        first_task = asyncio.create_task(
            ReplanningLangGraphRuntime(
                planner=planner,
                executor=blocking_executor,
                checkpointer=saver,
            ).run(request, emit=_ignore_event, control=_control())
        )
        await asyncio.wait_for(blocking_executor.started.wait(), timeout=1)
        first_task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await first_task

        replay_executor = _ScriptedExecutor(
            publish_report=PlanStepResult.completed("must not execute"),
        )
        result = await ReplanningLangGraphRuntime(
            planner=_ScriptedPlanner(
                TaskPlan((PlanStep("unexpected", "must_not_plan"),)),
            ),
            executor=replay_executor,
            checkpointer=saver,
        ).run(request, emit=_ignore_event, control=_control())

        self.assertEqual("side_effect_resume_unsafe", result.failure.code)
        self.assertEqual(1, blocking_executor.calls)
        self.assertEqual([], replay_executor.calls)


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


def _failure(code: str, *, retryable: bool) -> RunFailure:
    return RunFailure(
        code=code,
        category="tool",
        public_message="A safe tool step failed",
        retryable=retryable,
    )


def _request(run_id: str, *, input_text: str = "research question") -> RuntimeRequest:
    return RuntimeRequest(
        run_id=run_id,
        input_text=input_text,
        checkpoint_context=RuntimeCheckpointContext.for_run(
            run_id=run_id,
            owner_id="owner-a",
        ),
    )


def _control() -> RuntimeControl:
    return RuntimeControl(CancellationToken())


async def _ignore_event(event: RuntimeEvent) -> None:
    del event


def _collecting_sink(events: list[RuntimeEvent]):
    async def collect(event: RuntimeEvent) -> None:
        events.append(event)

    return collect


def _config(request: RuntimeRequest) -> dict[str, dict[str, str]]:
    context = request.checkpoint_context
    if context is None:
        raise AssertionError("test request has no checkpoint context")
    return {"configurable": {"thread_id": context.thread_id}}


async def _checkpoint_tuple(
    saver: InMemorySaver,
    request: RuntimeRequest,
):
    checkpoint_tuple = await saver.aget_tuple(_config(request))
    if checkpoint_tuple is None:
        raise AssertionError("checkpoint was not persisted")
    return checkpoint_tuple


async def _checkpoint_values(
    saver: InMemorySaver,
    request: RuntimeRequest,
) -> dict[str, object]:
    checkpoint_tuple = await _checkpoint_tuple(saver, request)
    return dict(checkpoint_tuple.checkpoint["channel_values"])


if __name__ == "__main__":
    unittest.main()
