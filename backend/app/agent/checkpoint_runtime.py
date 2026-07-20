from __future__ import annotations

import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
from typing import TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime as GraphRuntime

from backend.app.agent.runtime import (
    AgentRuntime,
    RuntimeControl,
    RuntimeEventSink,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.domain.run import RunFailure, RunStatus
from backend.app.stores import StoreError


CHECKPOINT_STATE_VERSION = 1


class _CheckpointState(TypedDict, total=False):
    state_version: int
    owner_scope: str
    invocation_count: int
    result_status: str | None
    result_answer: str | None
    result_step: int | None
    failure_code: str | None
    failure_category: str | None
    failure_message: str | None
    failure_retryable: bool | None
    failure_internal_ref: str | None
    failure_step: int | None


@dataclass(frozen=True)
class _InvocationContext:
    delegate: AgentRuntime
    request: RuntimeRequest
    emit: RuntimeEventSink
    control: RuntimeControl


class _CheckpointContractError(RuntimeError):
    pass


class _DelegateNodeError(RuntimeError):
    pass


class CheckpointedLangGraphRuntime:
    """Adds versioned, owner-scoped LangGraph checkpoints to a Runtime."""

    def __init__(
        self,
        *,
        delegate: AgentRuntime,
        checkpointer: BaseCheckpointSaver | None = None,
    ) -> None:
        self._delegate = delegate
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
                category="runtime",
                public_message="Checkpoint thread context is required",
            )
        if control.cancellation_token.is_cancelled:
            return _cancelled_result(control, step=0)

        config = {
            "configurable": {"thread_id": checkpoint_context.thread_id}
        }
        invalid_state = await self._validate_existing_checkpoint(
            config=config,
            owner_scope=checkpoint_context.owner_scope,
        )
        if invalid_state is not None:
            return invalid_state

        try:
            final_state = await self._graph.ainvoke(
                _CheckpointState(
                    state_version=CHECKPOINT_STATE_VERSION,
                    owner_scope=checkpoint_context.owner_scope,
                ),
                config=config,
                context=_InvocationContext(
                    delegate=self._delegate,
                    request=request,
                    emit=emit,
                    control=control,
                ),
            )
        except asyncio.CancelledError:
            raise
        except StoreError:
            raise
        except _DelegateNodeError:
            if control.cancellation_token.is_cancelled:
                return _cancelled_result(control, step=0)
            return _failure_result(
                code="checkpoint_node_failed",
                category="runtime",
                public_message="Checkpointed runtime node failed",
            )
        except _CheckpointContractError:
            return _failure_result(
                code="checkpoint_contract_error",
                category="runtime",
                public_message="Checkpointed runtime returned invalid state",
            )
        except Exception:
            return _failure_result(
                code="checkpoint_unavailable",
                category="runtime",
                public_message="Checkpoint storage is unavailable",
                retryable=True,
            )

        try:
            return _state_result(final_state)
        except (TypeError, ValueError):
            return _failure_result(
                code="checkpoint_contract_error",
                category="runtime",
                public_message="Checkpointed runtime returned invalid state",
            )

    async def _validate_existing_checkpoint(
        self,
        *,
        config: Mapping[str, object],
        owner_scope: str,
    ) -> RuntimeResult | None:
        try:
            checkpoint_tuple = await self._checkpointer.aget_tuple(config)
        except Exception:
            return _failure_result(
                code="checkpoint_unavailable",
                category="runtime",
                public_message="Checkpoint storage is unavailable",
                retryable=True,
            )
        if checkpoint_tuple is None:
            return None

        checkpoint = checkpoint_tuple.checkpoint
        channel_values = checkpoint.get("channel_values")
        if not isinstance(channel_values, Mapping):
            return _invalid_checkpoint_state()
        if channel_values.get("state_version") != CHECKPOINT_STATE_VERSION:
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
        invocation_count = channel_values.get("invocation_count", 0)
        if (
            not isinstance(invocation_count, int)
            or isinstance(invocation_count, bool)
            or invocation_count < 0
        ):
            return _invalid_checkpoint_state()
        return None

    def _create_graph(self):
        graph = StateGraph(
            _CheckpointState,
            context_schema=_InvocationContext,
        )
        graph.add_node("advance", _advance_checkpoint)
        graph.add_node("execute", _execute_delegate)
        graph.add_edge(START, "advance")
        graph.add_edge("advance", "execute")
        graph.add_edge("execute", END)
        return graph.compile(checkpointer=self._checkpointer)


def _advance_checkpoint(state: _CheckpointState) -> _CheckpointState:
    invocation_count = state.get("invocation_count", 0)
    if (
        not isinstance(invocation_count, int)
        or isinstance(invocation_count, bool)
        or invocation_count < 0
    ):
        raise _CheckpointContractError("invalid invocation count")
    return _CheckpointState(
        invocation_count=invocation_count + 1,
        result_status=None,
        result_answer=None,
        result_step=None,
        failure_code=None,
        failure_category=None,
        failure_message=None,
        failure_retryable=None,
        failure_internal_ref=None,
        failure_step=None,
    )


async def _execute_delegate(
    state: _CheckpointState,
    runtime: GraphRuntime[_InvocationContext],
) -> _CheckpointState:
    del state
    context = runtime.context
    try:
        result = await context.delegate.run(
            context.request,
            emit=context.emit,
            control=context.control,
        )
    except asyncio.CancelledError:
        raise
    except StoreError:
        raise
    except Exception:
        raise _DelegateNodeError from None
    if not isinstance(result, RuntimeResult):
        raise _CheckpointContractError("delegate returned an invalid result")
    return _result_state(result)


def _result_state(result: RuntimeResult) -> _CheckpointState:
    failure = result.failure
    return _CheckpointState(
        result_status=result.status.value,
        result_answer=result.answer,
        result_step=result.step,
        failure_code=failure.code if failure is not None else None,
        failure_category=failure.category if failure is not None else None,
        failure_message=(
            failure.public_message if failure is not None else None
        ),
        failure_retryable=failure.retryable if failure is not None else None,
        failure_internal_ref=failure.internal_ref if failure is not None else None,
        failure_step=failure.step if failure is not None else None,
    )


def _state_result(state: Mapping[str, object]) -> RuntimeResult:
    status = RunStatus(state.get("result_status"))
    step = state.get("result_step")
    if not isinstance(step, int) or isinstance(step, bool):
        raise ValueError("result step is invalid")
    if status is RunStatus.COMPLETED:
        return RuntimeResult(
            status=status,
            answer=state.get("result_answer"),
            step=step,
        )

    retryable = state.get("failure_retryable")
    if not isinstance(retryable, bool):
        raise ValueError("failure retryable flag is invalid")
    return RuntimeResult(
        status=status,
        failure=RunFailure(
            code=state.get("failure_code"),
            category=state.get("failure_category"),
            public_message=state.get("failure_message"),
            retryable=retryable,
            internal_ref=state.get("failure_internal_ref"),
            step=state.get("failure_step"),
        ),
        step=step,
    )


def _invalid_checkpoint_state() -> RuntimeResult:
    return _failure_result(
        code="checkpoint_state_invalid",
        category="runtime",
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
                if reason in {"cancelled_by_caller", "run_cancelled"}
                else "run_cancelled"
            ),
            category="cancellation",
            public_message="Run cancelled",
            step=step,
        ),
        step=step,
    )


__all__ = [
    "CHECKPOINT_STATE_VERSION",
    "CheckpointedLangGraphRuntime",
]
