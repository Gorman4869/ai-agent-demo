from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime as GraphRuntime
from langgraph.types import Command, interrupt

from backend.app.agent.runtime import (
    RuntimeApprovalDecision,
    RuntimeApprovalPause,
    RuntimeApprovalResume,
    RuntimeControl,
    RuntimeEvent,
    RuntimeEventSink,
    RuntimeOutcome,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.domain.run import RunFailure, RunStatus
from backend.app.tools import (
    ApprovalResolutionError,
    ApprovalResolutionStatus,
    InMemoryApprovalStore,
    ToolApprovalRequest,
    ToolRegistry,
    ToolApprovalResolution,
)


APPROVAL_CHECKPOINT_STATE_VERSION = 1


@dataclass(frozen=True)
class PlannedToolCall:
    call_id: str
    tool_name: str
    arguments: Mapping[str, Any] = field(repr=False)

    def __post_init__(self) -> None:
        for value, label in (
            (self.call_id, "call_id"),
            (self.tool_name, "tool_name"),
        ):
            if not isinstance(value, str) or not value or value != value.strip():
                raise ValueError(f"{label} has an invalid format")
        if not isinstance(self.arguments, Mapping):
            raise ValueError("tool arguments must be a mapping")
        object.__setattr__(self, "arguments", dict(self.arguments))


ToolCallPlanner = Callable[[RuntimeRequest], PlannedToolCall]


class _ApprovalState(TypedDict, total=False):
    state_version: int
    owner_scope: str
    approval_id: str
    tool_call_id: str
    tool_name: str
    arguments_digest: str
    expires_at: str | None
    result_status: str | None
    result_answer: str | None
    result_step: int | None
    failure_code: str | None
    failure_category: str | None
    failure_message: str | None


@dataclass(frozen=True)
class _ApprovalContext:
    approval_store: InMemoryApprovalStore = field(repr=False)
    registry: ToolRegistry = field(repr=False)
    request: RuntimeRequest = field(repr=False)
    control: RuntimeControl = field(repr=False)
    emit: RuntimeEventSink = field(repr=False)
    planned_call: PlannedToolCall | None = field(default=None, repr=False)
    approval_ttl: timedelta = field(
        default=timedelta(minutes=15),
        repr=False,
    )


class _ApprovalContractError(RuntimeError):
    pass


class ApprovalLangGraphRuntime:
    """A real LangGraph interrupt/resume path for one approved tool call."""

    def __init__(
        self,
        *,
        registry: ToolRegistry,
        approval_store: InMemoryApprovalStore,
        planner: ToolCallPlanner,
        approval_ttl: timedelta = timedelta(minutes=15),
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        if not isinstance(approval_ttl, timedelta) or approval_ttl <= timedelta(0):
            raise ValueError("approval_ttl must be positive")
        self._registry = registry
        self._approval_store = approval_store
        self._planner = planner
        self._approval_ttl = approval_ttl
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
    ) -> RuntimeOutcome:
        context_failure = self._validate_execution_context(request)
        if context_failure is not None:
            return context_failure
        checkpoint_context = request.checkpoint_context
        if checkpoint_context is None:
            return _failure_result(
                code="checkpoint_thread_required",
                category="runtime",
                public_message="Checkpoint thread context is required",
            )
        if control.cancellation_token.is_cancelled:
            return _cancelled_result()

        try:
            planned_call = self._planner(request)
        except Exception:
            return _failure_result(
                code="approval_plan_failed",
                category="runtime",
                public_message="Approval plan could not be created",
            )
        plan_failure = self._validate_plan(request, planned_call)
        if plan_failure is not None:
            return plan_failure

        config = {"configurable": {"thread_id": checkpoint_context.thread_id}}
        checkpoint_failure = await self._validate_checkpoint(
            config=config,
            owner_scope=checkpoint_context.owner_scope,
            required=False,
        )
        if checkpoint_failure is not None:
            return checkpoint_failure
        return await self._invoke(
            _ApprovalState(
                state_version=APPROVAL_CHECKPOINT_STATE_VERSION,
                owner_scope=checkpoint_context.owner_scope,
            ),
            config=config,
            context=_ApprovalContext(
                approval_store=self._approval_store,
                registry=self._registry,
                request=request,
                control=control,
                emit=emit,
                planned_call=planned_call,
                approval_ttl=self._approval_ttl,
            ),
        )

    async def resume(
        self,
        request: RuntimeRequest,
        *,
        approval: RuntimeApprovalResume,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeOutcome:
        context_failure = self._validate_execution_context(request)
        if context_failure is not None:
            return context_failure
        checkpoint_context = request.checkpoint_context
        if checkpoint_context is None:
            return _failure_result(
                code="checkpoint_thread_required",
                category="runtime",
                public_message="Checkpoint thread context is required",
            )
        if control.cancellation_token.is_cancelled:
            return _cancelled_result()

        config = {"configurable": {"thread_id": checkpoint_context.thread_id}}
        checkpoint_failure = await self._validate_checkpoint(
            config=config,
            owner_scope=checkpoint_context.owner_scope,
            required=True,
            approval=approval,
        )
        if checkpoint_failure is not None:
            return checkpoint_failure
        resolution = self._approval_store.get_resolution(
            approval_id=approval.approval_id,
            run_id=request.run_id,
            principal_id=request.execution_context.principal_id,
        )
        if resolution is None or not _resolution_matches(approval, resolution):
            return _failure_result(
                code="approval_resolution_invalid",
                category="authorization",
                public_message="Approval resolution is invalid",
            )

        return await self._invoke(
            Command(resume={"approval_id": approval.approval_id}),
            config=config,
            context=_ApprovalContext(
                approval_store=self._approval_store,
                registry=self._registry,
                request=request,
                control=control,
                emit=emit,
            ),
        )

    def _validate_execution_context(
        self,
        request: RuntimeRequest,
    ) -> RuntimeResult | None:
        context = request.execution_context
        if (
            context is None
            or context.run_id != request.run_id
            or context.approval_store is not self._approval_store
        ):
            return _failure_result(
                code="approval_context_required",
                category="authorization",
                public_message="Trusted approval context is required",
            )
        return None

    def _validate_plan(
        self,
        request: RuntimeRequest,
        planned_call: object,
    ) -> RuntimeResult | None:
        if not isinstance(planned_call, PlannedToolCall):
            return _failure_result(
                code="approval_plan_invalid",
                category="runtime",
                public_message="Approval plan is invalid",
            )
        definitions = {
            definition.name: definition
            for definition in self._registry.definitions(
                context=request.execution_context,
            )
        }
        definition = definitions.get(planned_call.tool_name)
        if definition is None:
            return _failure_result(
                code="approval_tool_unavailable",
                category="authorization",
                public_message="Requested approval tool is unavailable",
            )
        if not definition.approval_required:
            return _failure_result(
                code="approval_not_required",
                category="configuration",
                public_message="Requested tool does not require approval",
            )
        return None

    async def _validate_checkpoint(
        self,
        *,
        config: Mapping[str, object],
        owner_scope: str,
        required: bool,
        approval: RuntimeApprovalResume | None = None,
    ) -> RuntimeResult | None:
        try:
            checkpoint_tuple = await self._checkpointer.aget_tuple(config)
        except Exception:
            return _failure_result(
                code="checkpoint_unavailable",
                category="runtime",
                public_message="Checkpoint storage is unavailable",
            )
        if checkpoint_tuple is None:
            if required:
                return _failure_result(
                    code="approval_checkpoint_missing",
                    category="runtime",
                    public_message="Approval checkpoint is missing",
                )
            return None
        channel_values = checkpoint_tuple.checkpoint.get("channel_values")
        if not isinstance(channel_values, Mapping):
            return _invalid_checkpoint_result()
        if channel_values.get("state_version") != APPROVAL_CHECKPOINT_STATE_VERSION:
            return _failure_result(
                code="checkpoint_version_unsupported",
                category="runtime",
                public_message="Checkpoint state version is unsupported",
            )
        if channel_values.get("owner_scope") != owner_scope:
            return _failure_result(
                code="checkpoint_scope_mismatch",
                category="authorization",
                public_message="Checkpoint owner scope does not match",
            )
        if approval is not None and not _checkpoint_matches_approval(
            channel_values,
            approval,
        ):
            return _failure_result(
                code="approval_checkpoint_mismatch",
                category="authorization",
                public_message="Approval does not match checkpoint state",
            )
        return None

    async def _invoke(
        self,
        graph_input: _ApprovalState | Command,
        *,
        config: Mapping[str, object],
        context: _ApprovalContext,
    ) -> RuntimeOutcome:
        try:
            final_state = await self._graph.ainvoke(
                graph_input,
                config=config,
                context=context,
            )
            return _state_outcome(final_state)
        except asyncio.CancelledError:
            raise
        except ApprovalResolutionError:
            return _failure_result(
                code="approval_resolution_invalid",
                category="authorization",
                public_message="Approval resolution is invalid",
            )
        except _ApprovalContractError:
            return _invalid_checkpoint_result()
        except Exception:
            return _failure_result(
                code="approval_graph_failed",
                category="runtime",
                public_message="Approval workflow failed",
            )

    def _create_graph(self):
        graph = StateGraph(_ApprovalState, context_schema=_ApprovalContext)
        graph.add_node("prepare", _prepare_approval)
        graph.add_node("execute", _execute_approved_call)
        graph.add_edge(START, "prepare")
        graph.add_edge("prepare", "execute")
        graph.add_edge("execute", END)
        return graph.compile(checkpointer=self._checkpointer)


def _prepare_approval(
    state: _ApprovalState,
    runtime: GraphRuntime[_ApprovalContext],
) -> _ApprovalState:
    del state
    context = runtime.context
    planned_call = context.planned_call
    execution_context = context.request.execution_context
    if planned_call is None or execution_context is None:
        raise _ApprovalContractError("approval plan is missing")
    request = context.approval_store.request(
        run_id=context.request.run_id,
        principal_id=execution_context.principal_id,
        tool_call_id=planned_call.call_id,
        tool_name=planned_call.tool_name,
        arguments=planned_call.arguments,
        expires_in=context.approval_ttl,
    )
    return _ApprovalState(
        approval_id=request.id,
        tool_call_id=request.tool_call_id,
        tool_name=request.tool_name,
        arguments_digest=request.arguments_digest,
        expires_at=(
            request.expires_at.isoformat()
            if request.expires_at is not None
            else None
        ),
        result_status=None,
        result_answer=None,
        result_step=None,
        failure_code=None,
        failure_category=None,
        failure_message=None,
    )


async def _execute_approved_call(
    state: _ApprovalState,
    runtime: GraphRuntime[_ApprovalContext],
) -> _ApprovalState:
    approval_id = _state_text(state, "approval_id")
    resumed = interrupt(
        {
            "approval_id": approval_id,
            "tool_call_id": _state_text(state, "tool_call_id"),
            "tool_name": _state_text(state, "tool_name"),
            "arguments_digest": _state_text(state, "arguments_digest"),
            "expires_at": state.get("expires_at"),
        }
    )
    if not isinstance(resumed, Mapping) or resumed.get("approval_id") != approval_id:
        raise _ApprovalContractError("resume payload is invalid")

    context = runtime.context
    execution_context = context.request.execution_context
    if execution_context is None:
        raise _ApprovalContractError("execution context is missing")
    resolution = context.approval_store.get_resolution(
        approval_id=approval_id,
        run_id=context.request.run_id,
        principal_id=execution_context.principal_id,
    )
    if resolution is None:
        raise ApprovalResolutionError("approval_resolution_missing")
    if not _request_matches_state(resolution.request, state):
        raise ApprovalResolutionError("approval_binding_mismatch")
    if resolution.status is ApprovalResolutionStatus.REJECTED:
        return _failure_state(
            code="approval_rejected",
            category="authorization",
            public_message="Tool execution was rejected",
        )
    if resolution.status is ApprovalResolutionStatus.EXPIRED:
        return _failure_state(
            code="approval_expired",
            category="authorization",
            public_message="Tool approval expired",
        )
    if context.control.cancellation_token.is_cancelled:
        return _cancelled_state()

    arguments = context.approval_store.approved_arguments(resolution)
    result = context.registry.execute(
        resolution.request.tool_name,
        arguments,
        context=execution_context,
        call_id=resolution.request.tool_call_id,
    )
    if not result.ok:
        if (
            result.error_code == "approval_required"
            and result.error_details is not None
            and result.error_details.get("reason")
            == "approval_already_consumed"
        ):
            await context.emit(
                RuntimeEvent(
                    type="approval.stopped",
                    step=1,
                    data={
                        "reason": "side_effect_outcome_unknown",
                        "error_code": "side_effect_resume_unsafe",
                        "tool_name": resolution.request.tool_name,
                    },
                )
            )
            return _failure_state(
                code="side_effect_resume_unsafe",
                category="workflow",
                public_message=(
                    "Approved tool outcome is unknown and was not replayed"
                ),
            )
        return _failure_state(
            code=result.error_code or "tool_execution_failed",
            category="tool",
            public_message="Approved tool execution failed",
        )
    return _ApprovalState(
        result_status=RunStatus.COMPLETED.value,
        result_answer=f"Approved tool completed: {resolution.request.tool_name}",
        result_step=1,
    )


def _state_outcome(state: Mapping[str, object]) -> RuntimeOutcome:
    if state.get("__interrupt__"):
        expires_at = state.get("expires_at")
        if expires_at is not None and not isinstance(expires_at, str):
            raise _ApprovalContractError("approval expiry is invalid")
        return RuntimeApprovalPause(
            approval_id=_state_text(state, "approval_id"),
            tool_call_id=_state_text(state, "tool_call_id"),
            tool_name=_state_text(state, "tool_name"),
            arguments_digest=_state_text(state, "arguments_digest"),
            expires_at=(datetime.fromisoformat(expires_at) if expires_at else None),
            step=1,
        )

    status = RunStatus(state.get("result_status"))
    step = state.get("result_step")
    if not isinstance(step, int) or isinstance(step, bool):
        raise _ApprovalContractError("result step is invalid")
    if status is RunStatus.COMPLETED:
        return RuntimeResult(
            status=status,
            answer=state.get("result_answer"),
            step=step,
        )
    return RuntimeResult(
        status=status,
        failure=RunFailure(
            code=state.get("failure_code"),
            category=state.get("failure_category"),
            public_message=state.get("failure_message"),
            step=step,
        ),
        step=step,
    )


def _checkpoint_matches_approval(
    state: Mapping[str, object],
    approval: RuntimeApprovalResume,
) -> bool:
    return (
        state.get("approval_id") == approval.approval_id
        and state.get("tool_call_id") == approval.tool_call_id
        and state.get("tool_name") == approval.tool_name
        and state.get("arguments_digest") == approval.arguments_digest
    )


def _request_matches_state(
    request: ToolApprovalRequest,
    state: Mapping[str, object],
) -> bool:
    return (
        state.get("approval_id") == request.id
        and state.get("tool_call_id") == request.tool_call_id
        and state.get("tool_name") == request.tool_name
        and state.get("arguments_digest") == request.arguments_digest
    )


def _resolution_matches(
    approval: RuntimeApprovalResume,
    resolution: ToolApprovalResolution,
) -> bool:
    expected_status = ApprovalResolutionStatus(approval.decision.value)
    request = resolution.request
    return (
        resolution.status is expected_status
        and request.id == approval.approval_id
        and request.tool_call_id == approval.tool_call_id
        and request.tool_name == approval.tool_name
        and request.arguments_digest == approval.arguments_digest
    )


def _state_text(state: Mapping[str, object], name: str) -> str:
    value = state.get(name)
    if not isinstance(value, str) or not value:
        raise _ApprovalContractError(f"{name} is invalid")
    return value


def _failure_state(
    *,
    code: str,
    category: str,
    public_message: str,
) -> _ApprovalState:
    return _ApprovalState(
        result_status=RunStatus.FAILED.value,
        result_step=1,
        failure_code=code,
        failure_category=category,
        failure_message=public_message,
    )


def _cancelled_state() -> _ApprovalState:
    return _ApprovalState(
        result_status=RunStatus.CANCELLED.value,
        result_step=1,
        failure_code="run_cancelled",
        failure_category="cancellation",
        failure_message="Run cancelled",
    )


def _failure_result(
    *,
    code: str,
    category: str,
    public_message: str,
) -> RuntimeResult:
    return RuntimeResult(
        status=RunStatus.FAILED,
        failure=RunFailure(
            code=code,
            category=category,
            public_message=public_message,
        ),
    )


def _invalid_checkpoint_result() -> RuntimeResult:
    return _failure_result(
        code="checkpoint_state_invalid",
        category="runtime",
        public_message="Checkpoint state is invalid",
    )


def _cancelled_result() -> RuntimeResult:
    return RuntimeResult(
        status=RunStatus.CANCELLED,
        failure=RunFailure(
            code="run_cancelled",
            category="cancellation",
            public_message="Run cancelled",
        ),
    )


__all__ = [
    "APPROVAL_CHECKPOINT_STATE_VERSION",
    "ApprovalLangGraphRuntime",
    "PlannedToolCall",
    "ToolCallPlanner",
]
