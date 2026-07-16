from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Protocol

from backend.app.agent.cancellation import CancellationToken
from backend.app.agent.runtime import (
    RuntimeControl,
    RuntimeEvent,
    RuntimeEventSink,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.domain import AgentEvent, AgentRunResult
from backend.app.domain.run import RunFailure, RunStatus


class LegacyManualLoop(Protocol):
    def run(self, user_input: str) -> AgentRunResult:
        ...


ManualLoopFactory = Callable[
    [RuntimeRequest, CancellationToken],
    LegacyManualLoop,
]


class ManualRuntime:
    """Async compatibility adapter around the existing synchronous loop.

    The legacy loop is executed once in a worker thread. Its lifecycle events
    are consumed for outcome validation, while only reviewed and redacted
    progress events cross the new Runtime boundary.
    """

    def __init__(
        self,
        loop_factory: ManualLoopFactory,
        *,
        cancellation_grace_ms: int = 100,
    ) -> None:
        if (
            not isinstance(cancellation_grace_ms, int)
            or isinstance(cancellation_grace_ms, bool)
            or cancellation_grace_ms < 1
        ):
            raise ValueError("cancellation_grace_ms must be a positive integer")
        self._loop_factory = loop_factory
        self._cancellation_grace_ms = cancellation_grace_ms

    async def run(
        self,
        request: RuntimeRequest,
        *,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeResult:
        try:
            loop = self._loop_factory(request, control.cancellation_token)
            worker = asyncio.create_task(
                asyncio.to_thread(loop.run, request.input_text)
            )
            try:
                legacy_result = await asyncio.shield(worker)
            except asyncio.CancelledError:
                control.cancellation_token.cancel("runtime_task_cancelled")
                try:
                    await asyncio.wait_for(
                        asyncio.shield(worker),
                        timeout=self._cancellation_grace_ms / 1_000,
                    )
                except TimeoutError:
                    worker.add_done_callback(_consume_worker_result)
                except Exception:
                    pass
                raise
        except asyncio.CancelledError:
            raise
        except Exception:
            return _failure_result(
                code="manual_runtime_failed",
                category="runtime",
                public_message="Manual runtime failed",
            )

        try:
            result, events = _adapt_legacy_result(legacy_result)
        except (TypeError, ValueError):
            return _failure_result(
                code="manual_runtime_contract_error",
                category="runtime",
                public_message="Manual runtime returned an invalid result",
            )

        for event in events:
            await emit(event)
        return result


def _adapt_legacy_result(
    result: AgentRunResult,
) -> tuple[RuntimeResult, tuple[RuntimeEvent, ...]]:
    if not isinstance(result, AgentRunResult) or len(result.events) < 2:
        raise ValueError("legacy result has no lifecycle envelope")
    if result.events[0].type != "run.started":
        raise ValueError("legacy result does not start with run.started")

    terminal = result.events[-1]
    progress = tuple(_adapt_progress_event(event) for event in result.events[1:-1])
    if result.status == "completed":
        if terminal.type != "run.completed" or result.final_answer is None:
            raise ValueError("completed legacy result is inconsistent")
        return (
            RuntimeResult(
                status=RunStatus.COMPLETED,
                answer=result.final_answer,
                step=terminal.step,
            ),
            progress,
        )
    if result.status != "failed" or terminal.type != "run.failed":
        raise ValueError("failed legacy result is inconsistent")
    return _adapt_legacy_failure(result, terminal), progress


def _adapt_legacy_failure(
    result: AgentRunResult,
    terminal: AgentEvent,
) -> RuntimeResult:
    error_code = terminal.data.get("error_code")
    if error_code == "run_cancelled":
        reason = terminal.data.get("error_message")
        if reason == "deadline_exceeded":
            return _failure_result(
                code="run_timeout",
                category="timeout",
                public_message="Run timed out",
                step=terminal.step,
            )
        return _failure_result(
            code=(
                reason
                if reason in {"cancelled_by_user", "client_disconnected"}
                else "run_cancelled"
            ),
            category="cancellation",
            public_message="Run cancelled",
            status=RunStatus.CANCELLED,
            step=terminal.step,
        )
    if error_code == "model_retry_exhausted":
        return _failure_result(
            code="model_retry_exhausted",
            category="model",
            public_message="Model retry limit exhausted",
            step=terminal.step,
        )
    if error_code == "model_execution_failed":
        return _failure_result(
            code="model_execution_failed",
            category="model",
            public_message="Model execution failed",
            step=terminal.step,
        )
    if result.error is not None and result.error.startswith(
        "Agent exceeded maximum steps:"
    ):
        return _failure_result(
            code="max_steps_exceeded",
            category="budget",
            public_message="Agent exceeded the maximum step budget",
            step=terminal.step,
        )
    return _failure_result(
        code="manual_runtime_failed",
        category="runtime",
        public_message="Manual runtime failed",
        step=terminal.step,
    )


def _adapt_progress_event(event: AgentEvent) -> RuntimeEvent:
    if event.type == "model.retrying":
        keys = ("attempt", "model_duration_ms")
    elif event.type == "tool.started":
        keys = ("id", "name", "model_duration_ms")
    elif event.type == "tool.completed":
        keys = ("id", "name", "duration_ms", "ok")
    elif event.type == "tool.failed":
        keys = ("id", "name", "duration_ms", "ok", "error_code")
    else:
        raise ValueError("legacy progress event is not reviewed")
    return RuntimeEvent(
        type=event.type,
        step=event.step,
        data={key: event.data[key] for key in keys if key in event.data},
    )


def _failure_result(
    *,
    code: str,
    category: str,
    public_message: str,
    status: RunStatus = RunStatus.FAILED,
    step: int | None = None,
) -> RuntimeResult:
    return RuntimeResult(
        status=status,
        failure=RunFailure(
            code=code,
            category=category,
            public_message=public_message,
            step=step,
        ),
        step=step or 0,
    )


def _consume_worker_result(worker: asyncio.Task[AgentRunResult]) -> None:
    try:
        worker.result()
    except BaseException:
        pass


__all__ = ["ManualLoopFactory", "ManualRuntime"]
