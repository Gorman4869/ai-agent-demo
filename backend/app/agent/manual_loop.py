from __future__ import annotations

import json
from collections.abc import Callable
from time import perf_counter

from backend.app.agent.cancellation import CancellationToken, RunCancelled
from backend.app.domain import AgentEvent, AgentRunResult, Message
from backend.app.models import ChatModel, RetryableModelError
from backend.app.tools import ToolExecutionContext, ToolRegistry


Clock = Callable[[], float]


class ManualAgentLoop:
    def __init__(
        self,
        model: ChatModel,
        tools: ToolRegistry,
        *,
        max_steps: int = 8,
        execution_context: ToolExecutionContext | None = None,
        clock: Clock = perf_counter,
        cancellation_token: CancellationToken | None = None,
        max_model_retries: int = 2,
    ) -> None:
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        if max_model_retries < 0:
            raise ValueError("max_model_retries must not be negative")
        self._model = model
        self._tools = tools
        self._max_steps = max_steps
        self._execution_context = execution_context
        self._clock = clock
        self._cancellation_token = cancellation_token or CancellationToken()
        self._max_model_retries = max_model_retries

    def run(self, user_input: str) -> AgentRunResult:
        messages = [Message(role="user", content=user_input)]
        events = [AgentEvent(type="run.started", step=0, data={})]

        for step in range(1, self._max_steps + 1):
            try:
                self._cancellation_token.raise_if_cancelled()
            except RunCancelled as error:
                return _cancelled_result(messages, events, step, error.reason)

            for retry_attempt in range(self._max_model_retries + 1):
                model_started_at = self._clock()
                try:
                    decision = self._model.decide(
                        messages,
                        self._tools.definitions(context=self._execution_context),
                    )
                except RetryableModelError:
                    model_duration_ms = _elapsed_ms(model_started_at, self._clock())
                    if retry_attempt >= self._max_model_retries:
                        return _failed_result(
                            messages,
                            events,
                            step,
                            error_code="model_retry_exhausted",
                            error_message="Model retry limit exhausted",
                            model_duration_ms=model_duration_ms,
                        )
                    events.append(
                        AgentEvent(
                            type="model.retrying",
                            step=step,
                            data={
                                "attempt": retry_attempt + 1,
                                "model_duration_ms": model_duration_ms,
                            },
                        )
                    )
                    try:
                        self._cancellation_token.raise_if_cancelled()
                    except RunCancelled as error:
                        return _cancelled_result(
                            messages,
                            events,
                            step,
                            error.reason,
                        )
                    continue
                except RuntimeError:
                    model_duration_ms = _elapsed_ms(model_started_at, self._clock())
                    return _failed_result(
                        messages,
                        events,
                        step,
                        error_code="model_execution_failed",
                        error_message="Model execution failed",
                        model_duration_ms=model_duration_ms,
                    )
                model_duration_ms = _elapsed_ms(model_started_at, self._clock())
                break

            try:
                self._cancellation_token.raise_if_cancelled()
            except RunCancelled as error:
                return _cancelled_result(
                    messages,
                    events,
                    step,
                    error.reason,
                    model_duration_ms=model_duration_ms,
                )

            if decision.final_answer is not None:
                messages.append(Message(role="assistant", content=decision.final_answer))
                events.append(
                    AgentEvent(
                        type="run.completed",
                        step=step,
                        data={
                            "answer": decision.final_answer,
                            "model_duration_ms": model_duration_ms,
                        },
                    )
                )
                return AgentRunResult(
                    status="completed",
                    final_answer=decision.final_answer,
                    messages=tuple(messages),
                    events=tuple(events),
                )

            tool_call = decision.tool_call
            if tool_call is None:
                raise AssertionError("Validated ModelDecision has no outcome")

            events.append(
                AgentEvent(
                    type="tool.started",
                    step=step,
                    data={
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "model_duration_ms": model_duration_ms,
                    },
                )
            )
            tool_started_at = self._clock()
            tool_result = self._tools.execute(
                tool_call.name,
                tool_call.arguments,
                context=self._execution_context,
                call_id=tool_call.id,
            )
            tool_duration_ms = _elapsed_ms(tool_started_at, self._clock())
            result_payload = {
                "ok": tool_result.ok,
                "value": tool_result.value,
                "error_code": tool_result.error_code,
                "error_message": tool_result.error_message,
            }
            messages.append(
                Message(
                    role="assistant",
                    content=json.dumps(
                        {"name": tool_call.name, "arguments": tool_call.arguments},
                        ensure_ascii=False,
                    ),
                    tool_call_id=tool_call.id,
                )
            )
            messages.append(
                Message(
                    role="tool",
                    name=tool_call.name,
                    tool_call_id=tool_call.id,
                    content=json.dumps(result_payload, ensure_ascii=False),
                )
            )
            events.append(
                AgentEvent(
                    type="tool.completed" if tool_result.ok else "tool.failed",
                    step=step,
                    data={
                        "id": tool_call.id,
                        "name": tool_call.name,
                        "duration_ms": tool_duration_ms,
                        **result_payload,
                    },
                )
            )

        error = f"Agent exceeded maximum steps: {self._max_steps}"
        events.append(
            AgentEvent(type="run.failed", step=self._max_steps, data={"error": error})
        )
        return AgentRunResult(
            status="failed",
            final_answer=None,
            messages=tuple(messages),
            events=tuple(events),
            error=error,
        )


def _elapsed_ms(started_at: float, finished_at: float) -> float:
    return round(max(0.0, finished_at - started_at) * 1000, 3)


def _cancelled_result(
    messages: list[Message],
    events: list[AgentEvent],
    step: int,
    reason: str,
    *,
    model_duration_ms: float | None = None,
) -> AgentRunResult:
    data: dict[str, object] = {
        "error_code": "run_cancelled",
        "error_message": reason,
    }
    if model_duration_ms is not None:
        data["model_duration_ms"] = model_duration_ms
    events.append(AgentEvent(type="run.failed", step=step, data=data))
    return AgentRunResult(
        status="failed",
        final_answer=None,
        messages=tuple(messages),
        events=tuple(events),
        error="Run cancelled",
    )


def _failed_result(
    messages: list[Message],
    events: list[AgentEvent],
    step: int,
    *,
    error_code: str,
    error_message: str,
    model_duration_ms: float,
) -> AgentRunResult:
    events.append(
        AgentEvent(
            type="run.failed",
            step=step,
            data={
                "error_code": error_code,
                "error_message": error_message,
                "model_duration_ms": model_duration_ms,
            },
        )
    )
    return AgentRunResult(
        status="failed",
        final_answer=None,
        messages=tuple(messages),
        events=tuple(events),
        error=error_message,
    )
