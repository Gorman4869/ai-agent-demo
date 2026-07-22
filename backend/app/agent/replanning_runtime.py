from __future__ import annotations

import asyncio
import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime as GraphRuntime

from backend.app.agent.runtime import (
    RuntimeControl,
    RuntimeEvent,
    RuntimeEventSink,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.domain.run import RunFailure, RunStatus
from backend.app.stores import StoreError


REPLANNING_STATE_VERSION = 1
REPLANNING_WORKFLOW_KIND = "bounded-replanning-v1"
DEFAULT_REPLANNABLE_FAILURE_CODES = frozenset(
    {
        "mcp_timeout",
        "provider_rate_limited",
        "provider_timeout",
        "provider_unavailable",
        "tool_io_error",
        "tool_timeout",
    }
)

_PLAN_IDENTIFIER_PATTERN = re.compile(r"[a-z][a-z0-9_-]{0,99}")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
_NON_REPLANNABLE_CATEGORIES = frozenset(
    {
        "approval",
        "auth",
        "authorization",
        "cancellation",
        "security",
        "storage",
        "validation",
    }
)
_MAX_STEP_OUTPUT_BYTES = 200_000
_MAX_PLAN_STEPS = 100
_MAX_REPLANS = 20


@dataclass(frozen=True)
class PlanStep:
    """One server-reviewed operation in a structured task plan."""

    id: str
    operation: str
    side_effecting: bool = False
    requires_approval: bool = False

    def __post_init__(self) -> None:
        _require_plan_identifier(self.id, "plan step id")
        _require_plan_identifier(self.operation, "plan step operation")
        if not isinstance(self.side_effecting, bool):
            raise ValueError("plan step side_effecting must be a boolean")
        if not isinstance(self.requires_approval, bool):
            raise ValueError("plan step requires_approval must be a boolean")


@dataclass(frozen=True)
class TaskPlan:
    """A bounded ordered set of remaining workflow operations."""

    steps: tuple[PlanStep, ...]

    def __post_init__(self) -> None:
        try:
            steps = tuple(self.steps)
        except TypeError:
            raise ValueError("task plan steps must be iterable") from None
        if not steps or any(not isinstance(step, PlanStep) for step in steps):
            raise ValueError("task plan requires PlanStep values")
        step_ids = [step.id for step in steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("task plan step ids must be unique")
        object.__setattr__(self, "steps", steps)


@dataclass(frozen=True)
class PlanContext:
    """Safe state supplied to a planner for an initial plan or replan."""

    revision: int
    completed_steps: tuple[PlanStep, ...]
    failure: RunFailure | None
    remaining_step_budget: int
    remaining_replan_budget: int

    def __post_init__(self) -> None:
        _require_positive_int(self.revision, "plan revision")
        try:
            completed_steps = tuple(self.completed_steps)
        except TypeError:
            raise ValueError("completed_steps must be iterable") from None
        if any(not isinstance(step, PlanStep) for step in completed_steps):
            raise ValueError("completed_steps must contain PlanStep values")
        if self.failure is not None and not isinstance(self.failure, RunFailure):
            raise ValueError("plan failure must be RunFailure")
        _require_nonnegative_int(
            self.remaining_step_budget,
            "remaining step budget",
        )
        _require_nonnegative_int(
            self.remaining_replan_budget,
            "remaining replan budget",
        )
        object.__setattr__(self, "completed_steps", completed_steps)


@dataclass(frozen=True)
class PlanStepResult:
    """Exactly one safe output or classified failure from a plan step."""

    output: str | None = field(default=None, repr=False)
    failure: RunFailure | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (self.output is None) == (self.failure is None):
            raise ValueError("plan step result requires exactly one outcome")
        if self.output is not None:
            if not isinstance(self.output, str) or not self.output.strip():
                raise ValueError("plan step output must not be empty")
            try:
                output_size = len(self.output.encode("utf-8"))
            except UnicodeError:
                raise ValueError("plan step output contains invalid Unicode") from None
            if output_size > _MAX_STEP_OUTPUT_BYTES:
                raise ValueError("plan step output exceeds the size limit")
        if self.failure is not None and not isinstance(self.failure, RunFailure):
            raise ValueError("plan step failure must be RunFailure")

    @classmethod
    def completed(cls, output: str) -> PlanStepResult:
        return cls(output=output)

    @classmethod
    def failed(cls, failure: RunFailure) -> PlanStepResult:
        return cls(failure=failure)


class TaskPlanner(Protocol):
    async def plan(
        self,
        request: RuntimeRequest,
        *,
        context: PlanContext,
    ) -> TaskPlan:
        ...


class PlanStepExecutor(Protocol):
    async def execute(
        self,
        step: PlanStep,
        *,
        request: RuntimeRequest,
        control: RuntimeControl,
    ) -> PlanStepResult:
        ...


class _PlanStepState(TypedDict):
    id: str
    operation: str
    side_effecting: bool
    requires_approval: bool


class _ReplanningState(TypedDict, total=False):
    workflow_kind: str
    state_version: int
    owner_scope: str
    plan_revision: int
    plan_steps: list[_PlanStepState]
    completed_steps: list[_PlanStepState]
    plan_signatures: list[str]
    execution_count: int
    replan_count: int
    failed_step: _PlanStepState | None
    last_failure_code: str | None
    last_failure_category: str | None
    last_failure_message: str | None
    last_failure_retryable: bool | None
    last_failure_internal_ref: str | None
    last_failure_step: int | None
    result_status: str | None
    result_answer: str | None
    result_step: int | None
    result_failure_code: str | None
    result_failure_category: str | None
    result_failure_message: str | None
    result_failure_retryable: bool | None
    result_failure_internal_ref: str | None
    result_failure_step: int | None


@dataclass(frozen=True)
class _ReplanningContext:
    planner: TaskPlanner = field(repr=False)
    executor: PlanStepExecutor = field(repr=False)
    request: RuntimeRequest = field(repr=False)
    emit: RuntimeEventSink = field(repr=False)
    control: RuntimeControl = field(repr=False)
    max_steps: int
    max_replans: int
    replannable_failure_codes: frozenset[str]


class _ReplanningContractError(RuntimeError):
    pass


class _PlanValidationError(ValueError):
    def __init__(self, code: str, public_message: str) -> None:
        self.code = code
        self.public_message = public_message
        super().__init__(code)


class ReplanningLangGraphRuntime:
    """A checkpointed LangGraph runtime with bounded, safe replanning."""

    def __init__(
        self,
        *,
        planner: TaskPlanner,
        executor: PlanStepExecutor,
        max_steps: int = 8,
        max_replans: int = 2,
        replannable_failure_codes: frozenset[str] = (
            DEFAULT_REPLANNABLE_FAILURE_CODES
        ),
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        checked_max_steps = _require_positive_int(max_steps, "max_steps")
        checked_max_replans = _require_nonnegative_int(
            max_replans,
            "max_replans",
        )
        if checked_max_steps > _MAX_PLAN_STEPS:
            raise ValueError("max_steps exceeds the supported limit")
        if checked_max_replans > _MAX_REPLANS:
            raise ValueError("max_replans exceeds the supported limit")
        try:
            checked_codes = frozenset(replannable_failure_codes)
        except TypeError:
            raise ValueError("replannable failure codes must be iterable") from None
        if not checked_codes:
            raise ValueError("replannable failure codes must not be empty")
        for code in checked_codes:
            _require_plan_identifier(code, "replannable failure code")

        self._planner = planner
        self._executor = executor
        self._max_steps = checked_max_steps
        self._max_replans = checked_max_replans
        self._replannable_failure_codes = checked_codes
        self._checkpointer = (
            checkpointer if checkpointer is not None else InMemorySaver()
        )
        self._graph = self._create_graph()

    @property
    def checkpointer(self) -> BaseCheckpointSaver:
        return self._checkpointer

    async def run(
        self,
        request: RuntimeRequest,
        *,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeResult:
        checkpoint_context = request.checkpoint_context
        if checkpoint_context is None:
            return _failure_result(
                code="checkpoint_thread_required",
                category="workflow",
                public_message="Checkpoint thread context is required",
            )
        if control.cancellation_token.is_cancelled:
            return _cancelled_result(control, step=0)

        config: dict[str, object] = {
            "configurable": {"thread_id": checkpoint_context.thread_id},
            "recursion_limit": 6 + (self._max_steps * 2) + (self._max_replans * 2),
        }
        try:
            snapshot = await self._graph.aget_state(config)
        except Exception:
            return _failure_result(
                code="checkpoint_unavailable",
                category="storage",
                public_message="Checkpoint storage is unavailable",
                retryable=True,
            )

        graph_input: _ReplanningState | None
        values = snapshot.values
        if values:
            checkpoint_failure = _validate_existing_state(
                values,
                owner_scope=checkpoint_context.owner_scope,
            )
            if checkpoint_failure is not None:
                return checkpoint_failure
            existing_result = _state_result_or_none(values)
            if existing_result is not None:
                return existing_result
            if not snapshot.next:
                return _invalid_checkpoint_result()
            if any(
                node not in {"plan", "execute", "diagnose", "replan"}
                for node in snapshot.next
            ):
                return _invalid_checkpoint_result()
            if "execute" in snapshot.next:
                steps = _state_steps(values.get("plan_steps"), "plan_steps")
                if not steps:
                    return _invalid_checkpoint_result()
                if steps[0].side_effecting:
                    failure = _failure_result(
                        code="side_effect_resume_unsafe",
                        category="workflow",
                        public_message=(
                            "Side-effecting step outcome is unknown and was not replayed"
                        ),
                        step=_state_nonnegative_int(values, "execution_count"),
                    )
                    await emit(
                        RuntimeEvent(
                            type="plan.stopped",
                            step=failure.step,
                            data={
                                "reason": "side_effect_outcome_unknown",
                                "error_code": "side_effect_resume_unsafe",
                                "revision": _state_positive_int(
                                    values,
                                    "plan_revision",
                                ),
                            },
                        )
                    )
                    return failure
            graph_input = None
        else:
            graph_input = _ReplanningState(
                workflow_kind=REPLANNING_WORKFLOW_KIND,
                state_version=REPLANNING_STATE_VERSION,
                owner_scope=checkpoint_context.owner_scope,
                plan_revision=0,
                plan_steps=[],
                completed_steps=[],
                plan_signatures=[],
                execution_count=0,
                replan_count=0,
            )

        try:
            final_state = await self._graph.ainvoke(
                graph_input,
                config=config,
                context=_ReplanningContext(
                    planner=self._planner,
                    executor=self._executor,
                    request=request,
                    emit=emit,
                    control=control,
                    max_steps=self._max_steps,
                    max_replans=self._max_replans,
                    replannable_failure_codes=self._replannable_failure_codes,
                ),
            )
            result = _state_result_or_none(final_state)
            if result is None:
                return _invalid_checkpoint_result()
            return result
        except asyncio.CancelledError:
            raise
        except StoreError:
            raise
        except _ReplanningContractError:
            return _invalid_checkpoint_result()
        except Exception:
            return _failure_result(
                code="replanning_graph_failed",
                category="workflow",
                public_message="Replanning workflow failed",
            )

    def _create_graph(self):
        graph = StateGraph(
            _ReplanningState,
            context_schema=_ReplanningContext,
        )
        graph.add_node("plan", _create_plan)
        graph.add_node("execute", _execute_step)
        graph.add_node("diagnose", _diagnose_failure)
        graph.add_node("replan", _replan)
        graph.add_edge(START, "plan")
        graph.add_conditional_edges(
            "plan",
            _route_after_plan,
            {"execute": "execute", END: END},
        )
        graph.add_conditional_edges(
            "execute",
            _route_after_execute,
            {"execute": "execute", "diagnose": "diagnose", END: END},
        )
        graph.add_conditional_edges(
            "diagnose",
            _route_after_diagnose,
            {"replan": "replan", END: END},
        )
        graph.add_conditional_edges(
            "replan",
            _route_after_plan,
            {"execute": "execute", END: END},
        )
        return graph.compile(checkpointer=self._checkpointer)


async def _create_plan(
    state: _ReplanningState,
    runtime: GraphRuntime[_ReplanningContext],
) -> _ReplanningState:
    context = runtime.context
    if context.control.cancellation_token.is_cancelled:
        return _result_state(_cancelled_result(context.control, step=0))
    if _state_nonnegative_int(state, "plan_revision") != 0:
        raise _ReplanningContractError("initial plan already exists")

    plan_context = PlanContext(
        revision=1,
        completed_steps=(),
        failure=None,
        remaining_step_budget=context.max_steps,
        remaining_replan_budget=context.max_replans,
    )
    plan_or_failure = await _build_plan(
        context,
        plan_context=plan_context,
        phase="initial",
    )
    if isinstance(plan_or_failure, RuntimeResult):
        return _result_state(plan_or_failure)
    plan = plan_or_failure
    signature = _plan_signature(plan.steps)
    await context.emit(
        RuntimeEvent(
            type="plan.created",
            step=0,
            data={
                "revision": 1,
                "steps": [_safe_step_data(step) for step in plan.steps],
            },
        )
    )
    return _ReplanningState(
        plan_revision=1,
        plan_steps=[_step_state(step) for step in plan.steps],
        plan_signatures=[signature],
        **_clear_last_failure_state(),
    )


async def _execute_step(
    state: _ReplanningState,
    runtime: GraphRuntime[_ReplanningContext],
) -> _ReplanningState:
    context = runtime.context
    execution_count = _state_nonnegative_int(state, "execution_count")
    if context.control.cancellation_token.is_cancelled:
        return _result_state(
            _cancelled_result(context.control, step=execution_count)
        )
    if execution_count >= context.max_steps:
        return _result_state(
            _failure_result(
                code="plan_step_budget_exhausted",
                category="budget",
                public_message="Plan step budget was exhausted",
                step=execution_count,
            )
        )

    steps = _state_steps(state.get("plan_steps"), "plan_steps")
    if not steps:
        raise _ReplanningContractError("plan has no remaining step")
    step = steps[0]
    attempt = execution_count + 1
    if step.requires_approval:
        failure = _failure_result(
            code="approval_step_requires_interrupt",
            category="approval",
            public_message="Approval steps require the approval runtime",
            step=attempt,
        )
        await _emit_step_failure(
            context.emit,
            step=step,
            revision=_state_positive_int(state, "plan_revision"),
            attempt=attempt,
            failure=failure.failure,
        )
        return _ReplanningState(
            execution_count=attempt,
            **_result_state(failure),
        )

    await context.emit(
        RuntimeEvent(
            type="plan.step.started",
            step=attempt,
            data={
                "revision": _state_positive_int(state, "plan_revision"),
                "attempt": attempt,
                **_safe_step_data(step),
            },
        )
    )
    try:
        result = await context.executor.execute(
            step,
            request=context.request,
            control=context.control,
        )
    except asyncio.CancelledError:
        raise
    except StoreError:
        raise
    except Exception:
        result = PlanStepResult.failed(
            RunFailure(
                code="plan_step_execution_failed",
                category="workflow",
                public_message="Plan step execution failed",
                step=attempt,
            )
        )
    if not isinstance(result, PlanStepResult):
        result = PlanStepResult.failed(
            RunFailure(
                code="plan_step_contract_error",
                category="workflow",
                public_message="Plan step returned an invalid result",
                step=attempt,
            )
        )

    if result.failure is not None:
        failure = _failure_at_step(result.failure, attempt)
        await _emit_step_failure(
            context.emit,
            step=step,
            revision=_state_positive_int(state, "plan_revision"),
            attempt=attempt,
            failure=failure,
        )
        return _ReplanningState(
            execution_count=attempt,
            failed_step=_step_state(step),
            **_failure_state(failure),
        )

    await context.emit(
        RuntimeEvent(
            type="plan.step.completed",
            step=attempt,
            data={
                "revision": _state_positive_int(state, "plan_revision"),
                "attempt": attempt,
                **_safe_step_data(step),
            },
        )
    )
    completed = _state_steps(
        state.get("completed_steps", []),
        "completed_steps",
    )
    remaining = steps[1:]
    updates = _ReplanningState(
        execution_count=attempt,
        completed_steps=[
            *[_step_state(item) for item in completed],
            _step_state(step),
        ],
        plan_steps=[_step_state(item) for item in remaining],
        **_clear_last_failure_state(),
    )
    if not remaining:
        output = result.output
        if output is None:
            raise _ReplanningContractError("completed step has no output")
        updates.update(
            _result_state(
                RuntimeResult(
                    status=RunStatus.COMPLETED,
                    answer=output,
                    step=attempt,
                )
            )
        )
    return updates


async def _diagnose_failure(
    state: _ReplanningState,
    runtime: GraphRuntime[_ReplanningContext],
) -> _ReplanningState:
    context = runtime.context
    execution_count = _state_nonnegative_int(state, "execution_count")
    if context.control.cancellation_token.is_cancelled:
        return _result_state(
            _cancelled_result(context.control, step=execution_count)
        )
    failure = _last_failure(state)
    failed_step_state = state.get("failed_step")
    if failed_step_state is None:
        raise _ReplanningContractError("failed step is missing")
    failed_step = _step_from_state(failed_step_state)

    stop_result: RuntimeResult | None = None
    stop_reason: str | None = None
    if failed_step.side_effecting:
        stop_reason = "side_effecting_step"
        stop_result = _failure_result(
            code="side_effect_replan_forbidden",
            category="workflow",
            public_message="Side-effecting step was not replanned",
            step=execution_count,
        )
    elif (
        not failure.retryable
        or failure.code not in context.replannable_failure_codes
        or failure.category in _NON_REPLANNABLE_CATEGORIES
    ):
        stop_reason = "failure_not_replannable"
        stop_result = RuntimeResult(
            status=RunStatus.FAILED,
            failure=failure,
            step=execution_count,
        )
    elif _state_nonnegative_int(state, "replan_count") >= context.max_replans:
        stop_reason = "replan_budget_exhausted"
        stop_result = _failure_result(
            code="replan_budget_exhausted",
            category="budget",
            public_message="Replan budget was exhausted",
            step=execution_count,
        )
    elif execution_count >= context.max_steps:
        stop_reason = "step_budget_exhausted"
        stop_result = _failure_result(
            code="plan_step_budget_exhausted",
            category="budget",
            public_message="Plan step budget was exhausted",
            step=execution_count,
        )

    if stop_result is None:
        return _ReplanningState()
    await context.emit(
        RuntimeEvent(
            type="plan.stopped",
            step=execution_count,
            data={
                "reason": stop_reason,
                "error_code": failure.code,
                "revision": _state_positive_int(state, "plan_revision"),
            },
        )
    )
    return _result_state(stop_result)


async def _replan(
    state: _ReplanningState,
    runtime: GraphRuntime[_ReplanningContext],
) -> _ReplanningState:
    context = runtime.context
    execution_count = _state_nonnegative_int(state, "execution_count")
    replan_count = _state_nonnegative_int(state, "replan_count")
    if context.control.cancellation_token.is_cancelled:
        return _result_state(
            _cancelled_result(context.control, step=execution_count)
        )
    failure = _last_failure(state)
    completed = _state_steps(
        state.get("completed_steps", []),
        "completed_steps",
    )
    revision = _state_positive_int(state, "plan_revision") + 1
    plan_or_failure = await _build_plan(
        context,
        plan_context=PlanContext(
            revision=revision,
            completed_steps=tuple(completed),
            failure=failure,
            remaining_step_budget=context.max_steps - execution_count,
            remaining_replan_budget=context.max_replans - replan_count,
        ),
        phase="replan",
    )
    if isinstance(plan_or_failure, RuntimeResult):
        return _result_state(plan_or_failure)
    plan = plan_or_failure

    completed_ids = {step.id for step in completed}
    if any(step.id in completed_ids for step in plan.steps):
        return _result_state(
            _failure_result(
                code="replan_completed_step_repeated",
                category="workflow",
                public_message="Replan repeated a completed step",
                step=execution_count,
            )
        )
    completed_side_effects = {
        step.operation for step in completed if step.side_effecting
    }
    if any(step.operation in completed_side_effects for step in plan.steps):
        return _result_state(
            _failure_result(
                code="replan_side_effect_replay_forbidden",
                category="workflow",
                public_message="Replan attempted to replay a side effect",
                step=execution_count,
            )
        )

    signature = _plan_signature(plan.steps)
    signatures = _state_signatures(state.get("plan_signatures", []))
    if signature in signatures:
        await context.emit(
            RuntimeEvent(
                type="plan.stopped",
                step=execution_count,
                data={
                    "reason": "plan_loop_detected",
                    "error_code": failure.code,
                    "revision": revision,
                },
            )
        )
        return _result_state(
            _failure_result(
                code="replan_loop_detected",
                category="workflow",
                public_message="Replan repeated a previous operation path",
                step=execution_count,
            )
        )

    await context.emit(
        RuntimeEvent(
            type="plan.replanned",
            step=execution_count,
            data={
                "revision": revision,
                "cause": failure.code,
                "steps": [_safe_step_data(step) for step in plan.steps],
            },
        )
    )
    return _ReplanningState(
        plan_revision=revision,
        plan_steps=[_step_state(step) for step in plan.steps],
        plan_signatures=[*signatures, signature],
        replan_count=replan_count + 1,
        **_clear_last_failure_state(),
    )


async def _build_plan(
    context: _ReplanningContext,
    *,
    plan_context: PlanContext,
    phase: str,
) -> TaskPlan | RuntimeResult:
    try:
        plan = await context.planner.plan(
            context.request,
            context=plan_context,
        )
    except asyncio.CancelledError:
        raise
    except StoreError:
        raise
    except Exception:
        return _failure_result(
            code=(
                "plan_generation_failed"
                if phase == "initial"
                else "replan_generation_failed"
            ),
            category="workflow",
            public_message=(
                "Task plan could not be created"
                if phase == "initial"
                else "Task could not be replanned"
            ),
            step=context.max_steps - plan_context.remaining_step_budget,
        )
    try:
        return _validate_plan(
            plan,
            remaining_step_budget=plan_context.remaining_step_budget,
            phase=phase,
        )
    except _PlanValidationError as error:
        return _failure_result(
            code=error.code,
            category=("budget" if "budget" in error.code else "workflow"),
            public_message=error.public_message,
            step=context.max_steps - plan_context.remaining_step_budget,
        )


def _validate_plan(
    plan: object,
    *,
    remaining_step_budget: int,
    phase: str,
) -> TaskPlan:
    if not isinstance(plan, TaskPlan):
        raise _PlanValidationError(
            "plan_contract_error" if phase == "initial" else "replan_contract_error",
            "Planner returned an invalid task plan",
        )
    if len(plan.steps) > remaining_step_budget:
        raise _PlanValidationError(
            "plan_step_budget_exceeded",
            "Task plan exceeds the remaining step budget",
        )
    return plan


def _route_after_plan(state: _ReplanningState) -> str:
    return END if state.get("result_status") is not None else "execute"


def _route_after_execute(state: _ReplanningState) -> str:
    if state.get("result_status") is not None:
        return END
    if state.get("last_failure_code") is not None:
        return "diagnose"
    return "execute"


def _route_after_diagnose(state: _ReplanningState) -> str:
    return END if state.get("result_status") is not None else "replan"


async def _emit_step_failure(
    emit: RuntimeEventSink,
    *,
    step: PlanStep,
    revision: int,
    attempt: int,
    failure: RunFailure | None,
) -> None:
    if failure is None:
        raise _ReplanningContractError("step failure is missing")
    await emit(
        RuntimeEvent(
            type="plan.step.failed",
            step=attempt,
            data={
                "revision": revision,
                "attempt": attempt,
                "error_code": failure.code,
                "category": failure.category,
                "retryable": failure.retryable,
                **_safe_step_data(step),
            },
        )
    )


def _validate_existing_state(
    state: Mapping[str, object],
    *,
    owner_scope: str,
) -> RuntimeResult | None:
    try:
        if state.get("workflow_kind") != REPLANNING_WORKFLOW_KIND:
            return _failure_result(
                code="checkpoint_workflow_mismatch",
                category="workflow",
                public_message="Checkpoint workflow kind does not match",
            )
        if state.get("state_version") != REPLANNING_STATE_VERSION:
            return _failure_result(
                code="checkpoint_version_unsupported",
                category="workflow",
                public_message="Checkpoint state version is unsupported",
            )
        if state.get("owner_scope") != owner_scope:
            return _failure_result(
                code="checkpoint_scope_mismatch",
                category="authorization",
                public_message="Checkpoint owner scope does not match",
            )
        plan_revision = _state_nonnegative_int(state, "plan_revision")
        _state_nonnegative_int(state, "execution_count")
        replan_count = _state_nonnegative_int(state, "replan_count")
        plan_steps = _state_steps(state.get("plan_steps", []), "plan_steps")
        completed_steps = _state_steps(
            state.get("completed_steps", []),
            "completed_steps",
        )
        signatures = _state_signatures(state.get("plan_signatures", []))
        if plan_revision != len(signatures) or replan_count != max(
            0,
            plan_revision - 1,
        ):
            raise _ReplanningContractError("plan revision metadata is invalid")
        completed_ids = {step.id for step in completed_steps}
        if any(step.id in completed_ids for step in plan_steps):
            raise _ReplanningContractError("completed plan step was scheduled again")
        completed_side_effects = {
            step.operation for step in completed_steps if step.side_effecting
        }
        if any(step.operation in completed_side_effects for step in plan_steps):
            raise _ReplanningContractError("completed side effect was scheduled again")
        failed_step = state.get("failed_step")
        if failed_step is not None:
            _step_from_state(state["failed_step"])
            _last_failure(state)
        elif any(
            state.get(field_name) is not None
            for field_name in (
                "last_failure_code",
                "last_failure_category",
                "last_failure_message",
                "last_failure_retryable",
                "last_failure_internal_ref",
                "last_failure_step",
            )
        ):
            raise _ReplanningContractError("last failure has no failed step")
        _state_result_or_none(state)
    except (TypeError, ValueError, _ReplanningContractError):
        return _invalid_checkpoint_result()
    return None


def _step_state(step: PlanStep) -> _PlanStepState:
    return _PlanStepState(
        id=step.id,
        operation=step.operation,
        side_effecting=step.side_effecting,
        requires_approval=step.requires_approval,
    )


def _step_from_state(value: object) -> PlanStep:
    if not isinstance(value, Mapping) or set(value) != {
        "id",
        "operation",
        "side_effecting",
        "requires_approval",
    }:
        raise _ReplanningContractError("plan step state is invalid")
    return PlanStep(
        id=value["id"],
        operation=value["operation"],
        side_effecting=value["side_effecting"],
        requires_approval=value["requires_approval"],
    )


def _state_steps(value: object, field_name: str) -> list[PlanStep]:
    if not isinstance(value, list):
        raise _ReplanningContractError(f"{field_name} is invalid")
    steps = [_step_from_state(item) for item in value]
    step_ids = [step.id for step in steps]
    if len(step_ids) != len(set(step_ids)):
        raise _ReplanningContractError(f"{field_name} contains duplicate ids")
    return steps


def _state_signatures(value: object) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or _SHA256_PATTERN.fullmatch(item) is None
        for item in value
    ):
        raise _ReplanningContractError("plan signatures are invalid")
    if len(value) != len(set(value)):
        raise _ReplanningContractError("plan signatures contain duplicates")
    return list(value)


def _plan_signature(steps: tuple[PlanStep, ...]) -> str:
    payload = json.dumps(
        [
            {
                "operation": step.operation,
                "requires_approval": step.requires_approval,
                "side_effecting": step.side_effecting,
            }
            for step in steps
        ],
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_step_data(step: PlanStep) -> dict[str, object]:
    return {
        "id": step.id,
        "operation": step.operation,
        "side_effecting": step.side_effecting,
        "requires_approval": step.requires_approval,
    }


def _failure_at_step(failure: RunFailure, step: int) -> RunFailure:
    return RunFailure(
        code=failure.code,
        category=failure.category,
        public_message=failure.public_message,
        retryable=failure.retryable,
        internal_ref=failure.internal_ref,
        step=step,
    )


def _failure_state(failure: RunFailure) -> _ReplanningState:
    return _ReplanningState(
        last_failure_code=failure.code,
        last_failure_category=failure.category,
        last_failure_message=failure.public_message,
        last_failure_retryable=failure.retryable,
        last_failure_internal_ref=failure.internal_ref,
        last_failure_step=failure.step,
    )


def _clear_last_failure_state() -> _ReplanningState:
    return _ReplanningState(
        failed_step=None,
        last_failure_code=None,
        last_failure_category=None,
        last_failure_message=None,
        last_failure_retryable=None,
        last_failure_internal_ref=None,
        last_failure_step=None,
    )


def _last_failure(state: Mapping[str, object]) -> RunFailure:
    code = state.get("last_failure_code")
    category = state.get("last_failure_category")
    message = state.get("last_failure_message")
    retryable = state.get("last_failure_retryable")
    step = state.get("last_failure_step")
    if not isinstance(retryable, bool):
        raise _ReplanningContractError("last failure retryable is invalid")
    return RunFailure(
        code=code,
        category=category,
        public_message=message,
        retryable=retryable,
        internal_ref=state.get("last_failure_internal_ref"),
        step=step,
    )


def _result_state(result: RuntimeResult) -> _ReplanningState:
    failure = result.failure
    return _ReplanningState(
        result_status=result.status.value,
        result_answer=result.answer,
        result_step=result.step,
        result_failure_code=failure.code if failure is not None else None,
        result_failure_category=(
            failure.category if failure is not None else None
        ),
        result_failure_message=(
            failure.public_message if failure is not None else None
        ),
        result_failure_retryable=(
            failure.retryable if failure is not None else None
        ),
        result_failure_internal_ref=(
            failure.internal_ref if failure is not None else None
        ),
        result_failure_step=failure.step if failure is not None else None,
    )


def _state_result_or_none(state: Mapping[str, object]) -> RuntimeResult | None:
    status_value = state.get("result_status")
    if status_value is None:
        return None
    status = RunStatus(status_value)
    step = state.get("result_step")
    if not isinstance(step, int) or isinstance(step, bool) or step < 0:
        raise _ReplanningContractError("result step is invalid")
    if status is RunStatus.COMPLETED:
        return RuntimeResult(
            status=status,
            answer=state.get("result_answer"),
            step=step,
        )
    retryable = state.get("result_failure_retryable")
    if not isinstance(retryable, bool):
        raise _ReplanningContractError("result failure retryable is invalid")
    return RuntimeResult(
        status=status,
        failure=RunFailure(
            code=state.get("result_failure_code"),
            category=state.get("result_failure_category"),
            public_message=state.get("result_failure_message"),
            retryable=retryable,
            internal_ref=state.get("result_failure_internal_ref"),
            step=state.get("result_failure_step"),
        ),
        step=step,
    )


def _invalid_checkpoint_result() -> RuntimeResult:
    return _failure_result(
        code="checkpoint_state_invalid",
        category="workflow",
        public_message="Checkpoint state is invalid",
    )


def _failure_result(
    *,
    code: str,
    category: str,
    public_message: str,
    step: int = 0,
    retryable: bool = False,
) -> RuntimeResult:
    return RuntimeResult(
        status=RunStatus.FAILED,
        failure=RunFailure(
            code=code,
            category=category,
            public_message=public_message,
            retryable=retryable,
            step=step,
        ),
        step=step,
    )


def _cancelled_result(control: RuntimeControl, *, step: int) -> RuntimeResult:
    reason = control.cancellation_token.reason
    if reason == "deadline_exceeded":
        return _failure_result(
            code="run_timeout",
            category="timeout",
            public_message="Run timed out",
            step=step,
        )
    return RuntimeResult(
        status=RunStatus.CANCELLED,
        failure=RunFailure(
            code=(
                reason
                if reason in {"cancelled_by_user", "client_disconnected"}
                else "run_cancelled"
            ),
            category="cancellation",
            public_message="Run cancelled",
            step=step,
        ),
        step=step,
    )


def _state_nonnegative_int(state: Mapping[str, object], field_name: str) -> int:
    value = state.get(field_name)
    return _require_nonnegative_int(value, field_name)


def _state_positive_int(state: Mapping[str, object], field_name: str) -> int:
    value = state.get(field_name)
    return _require_positive_int(value, field_name)


def _require_nonnegative_int(value: object, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
    return value


def _require_positive_int(value: object, label: str) -> int:
    result = _require_nonnegative_int(value, label)
    if result == 0:
        raise ValueError(f"{label} must be positive")
    return result


def _require_plan_identifier(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or _PLAN_IDENTIFIER_PATTERN.fullmatch(value) is None
    ):
        raise ValueError(f"{label} has an invalid format")
    return value


__all__ = [
    "DEFAULT_REPLANNABLE_FAILURE_CODES",
    "PlanContext",
    "PlanStep",
    "PlanStepExecutor",
    "PlanStepResult",
    "REPLANNING_STATE_VERSION",
    "REPLANNING_WORKFLOW_KIND",
    "ReplanningLangGraphRuntime",
    "TaskPlan",
    "TaskPlanner",
]
