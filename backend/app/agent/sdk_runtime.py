from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import AbstractAsyncContextManager, asynccontextmanager, suppress
from dataclasses import dataclass, field
from typing import Any, Protocol

import openai
from agents import (
    Agent,
    FunctionTool,
    ModelRetryBackoffSettings,
    ModelRetrySettings,
    ModelSettings,
    OpenAIResponsesModel,
    RunConfig,
    Runner,
    function_tool,
    retry_policies,
)
from agents.exceptions import (
    AgentsException,
    InputGuardrailTripwireTriggered,
    MaxTurnsExceeded,
    ModelBehaviorError,
    ModelRefusalError,
    OutputGuardrailTripwireTriggered,
    ToolInputGuardrailTripwireTriggered,
    ToolOutputGuardrailTripwireTriggered,
    ToolTimeoutError,
    UserError,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.agent.runtime import (
    RuntimeControl,
    RuntimeEvent,
    RuntimeEventSink,
    RuntimeRequest,
    RuntimeResult,
    _validate_prompt_context,
)
from backend.app.agent.sdk_tools import (
    OpenAIAgentsRunContext,
    build_sdk_tools,
)
from backend.app.domain.run import RunFailure, RunStatus
from backend.app.reliability import stable_run_failure
from backend.app.settings import RunBudgetSettings
from backend.app.tools import ToolExecutionContext


LOGGER = logging.getLogger(__name__)
_MAX_FINAL_OUTPUT_BYTES = 200_000
_MAX_DELTA_BYTES = 60_000
_JSON_WHITESPACE = " \t\r\n"
_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")
_JSON_ESCAPES = {
    '"': '"',
    "\\": "\\",
    "/": "/",
    "b": "\b",
    "f": "\f",
    "n": "\n",
    "r": "\r",
    "t": "\t",
}


class OpenAIAgentOutput(BaseModel):
    """Minimal structured output used by the learning Agent."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    answer: str = Field(repr=False)

    @field_validator("answer")
    @classmethod
    def validate_answer(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("answer must not be blank")
        return value


@function_tool
def add_numbers(a: float, b: float) -> float:
    """Add two numbers and return the result."""
    return a + b


def create_openai_learning_agent(
    *,
    tools: tuple[FunctionTool, ...] | list[FunctionTool] | None = None,
    prompt_context: str | None = None,
) -> Agent[OpenAIAgentsRunContext]:
    """Construct an SDK Agent without starting a model request."""
    instructions = (
        "Explain Agent concepts concisely. Use tools for arithmetic or "
        "approved actions. Never claim a tool ran unless a tool result is "
        "present. Return the answer in the required structured output."
    )
    if prompt_context is not None:
        _validate_prompt_context(prompt_context)
        instructions = f"{instructions}\n\n{prompt_context}"
    return Agent(
        name="Learning Assistant",
        instructions=instructions,
        tools=list(tools) if tools is not None else [],
        output_type=OpenAIAgentOutput,
    )


class _StreamingRun(Protocol):
    final_output: object
    context_wrapper: object
    is_complete: bool
    run_loop_exception: BaseException | None

    def stream_events(self) -> AsyncIterator[object]:
        ...

    def cancel(self, mode: str = "immediate") -> None:
        ...


class _AgentsRunner(Protocol):
    def run_streamed(
        self,
        starting_agent: object,
        input: str,
        *,
        context: object,
        max_turns: int,
        run_config: RunConfig,
    ) -> _StreamingRun:
        ...


AgentFactory = Callable[
    [RuntimeRequest, OpenAIAgentsRunContext],
    object,
]
ModelFactory = Callable[[], AbstractAsyncContextManager[object]]


@dataclass
class _StructuredAnswerStream:
    phase: str = "leading"
    segment: int = 0
    key: str = ""
    escaped: bool = False
    unicode_digits: str | None = None
    high_surrogate: int | None = None
    active: bool = False
    answer_parts: list[str] = field(default_factory=list, repr=False)

    def feed(self, delta: str) -> tuple[tuple[int, str], ...]:
        self.active = True
        decoded: list[str] = []
        segments: list[tuple[int, str]] = []
        for character in delta:
            previous_segment = self.segment
            self._consume(character, decoded)
            if self.segment != previous_segment and decoded:
                segments.append((previous_segment, "".join(decoded)))
                decoded = []
        result = "".join(decoded)
        if result:
            self.answer_parts.append(result)
            segments.append((self.segment, result))
        return tuple(segments)

    def validate(self, answer: str) -> None:
        if not self.active:
            return
        if (
            self.phase != "trailing"
            or self.escaped
            or self.unicode_digits is not None
            or self.high_surrogate is not None
        ):
            raise ValueError("structured output stream is incomplete")
        if "".join(self.answer_parts) != answer:
            raise ValueError("structured output stream does not match final output")

    def _consume(self, character: str, decoded: list[str]) -> None:
        if self.phase == "leading":
            if character in _JSON_WHITESPACE:
                return
            if character == "{":
                self._start_object()
                return
            raise _ContractFailure()
        if self.phase == "before_key":
            if character in _JSON_WHITESPACE:
                return
            if character == '"':
                self.phase = "key"
                return
            raise _ContractFailure()
        if self.phase == "key":
            self._consume_key(character)
            return
        if self.phase == "after_key":
            if character in _JSON_WHITESPACE:
                return
            if character == ":":
                self.phase = "before_value"
                return
            raise _ContractFailure()
        if self.phase == "before_value":
            if character in _JSON_WHITESPACE:
                return
            if character == '"':
                self.phase = "value"
                return
            raise _ContractFailure()
        if self.phase == "value":
            self._consume_value(character, decoded)
            return
        if self.phase == "after_value":
            if character in _JSON_WHITESPACE:
                return
            if character == "}":
                self.phase = "trailing"
                return
            raise _ContractFailure()
        if self.phase == "trailing":
            if character in _JSON_WHITESPACE:
                return
            if character == "{":
                self._start_object()
                return
            raise _ContractFailure()
        raise _ContractFailure()

    def _start_object(self) -> None:
        self.segment += 1
        self.phase = "before_key"
        self.key = ""
        self.escaped = False
        self.unicode_digits = None
        self.high_surrogate = None
        self.answer_parts.clear()

    def _consume_key(self, character: str) -> None:
        key_characters: list[str] = []
        if self.unicode_digits is not None:
            if character not in _HEX_DIGITS:
                raise _ContractFailure()
            self.unicode_digits += character
            if len(self.unicode_digits) == 4:
                codepoint = int(self.unicode_digits, 16)
                self.unicode_digits = None
                self._append_codepoint(codepoint, key_characters)
            self._append_key_characters(key_characters)
            return
        if self.escaped:
            self.escaped = False
            if character == "u":
                self.unicode_digits = ""
                return
            decoded_character = _JSON_ESCAPES.get(character)
            if decoded_character is None or self.high_surrogate is not None:
                raise _ContractFailure()
            self._append_key_characters([decoded_character])
            return
        if character == "\\":
            self.escaped = True
            return
        if character == '"':
            if self.high_surrogate is not None or self.key != "answer":
                raise _ContractFailure()
            self.phase = "after_key"
            return
        if ord(character) < 0x20 or self.high_surrogate is not None:
            raise _ContractFailure()
        if 0xD800 <= ord(character) <= 0xDFFF:
            raise _ContractFailure()
        self._append_key_characters([character])

    def _append_key_characters(self, characters: list[str]) -> None:
        for character in characters:
            self.key += character
            if not "answer".startswith(self.key):
                raise _ContractFailure()

    def _consume_value(self, character: str, decoded: list[str]) -> None:
        if self.unicode_digits is not None:
            if character not in _HEX_DIGITS:
                raise _ContractFailure()
            self.unicode_digits += character
            if len(self.unicode_digits) == 4:
                codepoint = int(self.unicode_digits, 16)
                self.unicode_digits = None
                self._append_codepoint(codepoint, decoded)
            return
        if self.escaped:
            self.escaped = False
            if character == "u":
                self.unicode_digits = ""
                return
            decoded_character = _JSON_ESCAPES.get(character)
            if decoded_character is None or self.high_surrogate is not None:
                raise _ContractFailure()
            decoded.append(decoded_character)
            return
        if character == "\\":
            self.escaped = True
            return
        if character == '"':
            if self.high_surrogate is not None:
                raise _ContractFailure()
            self.phase = "after_value"
            return
        if ord(character) < 0x20 or self.high_surrogate is not None:
            raise _ContractFailure()
        if 0xD800 <= ord(character) <= 0xDFFF:
            raise _ContractFailure()
        decoded.append(character)

    def _append_codepoint(self, codepoint: int, decoded: list[str]) -> None:
        if 0xD800 <= codepoint <= 0xDBFF:
            if self.high_surrogate is not None:
                raise _ContractFailure()
            self.high_surrogate = codepoint
            return
        if 0xDC00 <= codepoint <= 0xDFFF:
            if self.high_surrogate is None:
                raise _ContractFailure()
            combined = 0x10000 + (
                (self.high_surrogate - 0xD800) * 0x400
                + codepoint
                - 0xDC00
            )
            self.high_surrogate = None
            decoded.append(chr(combined))
            return
        if self.high_surrogate is not None:
            raise _ContractFailure()
        decoded.append(chr(codepoint))


@dataclass
class _StreamState:
    step: int = 0
    output_bytes: int = 0
    wire_output_bytes: int = 0
    suppress_events: bool = False
    cancel_called: bool = False
    agent_updates: int = 0
    tool_names: dict[str, str] = field(default_factory=dict)
    abort_requested: asyncio.Event = field(
        default_factory=asyncio.Event,
        repr=False,
    )
    failure: Exception | None = field(default=None, repr=False)
    structured_answer: _StructuredAnswerStream | None = field(
        default=None,
        repr=False,
    )

    def next_step(self) -> int:
        self.step += 1
        return self.step


class _StreamFailure(RuntimeError):
    def __init__(self, error: Exception) -> None:
        super().__init__("SDK stream failed")
        self.error = error


class _ContractFailure(RuntimeError):
    def __init__(self, code: str = "agents_sdk_contract_error") -> None:
        super().__init__(code)
        self.code = code


class _BudgetFailure(RuntimeError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class OpenAIAgentsRuntime:
    """Safe streaming adapter for the pinned OpenAI Agents SDK surface."""

    def __init__(
        self,
        *,
        agent_factory: AgentFactory,
        model_factory: ModelFactory,
        provider: str,
        model: str,
        budget: RunBudgetSettings,
        runner: _AgentsRunner = Runner,
        cancellation_poll_ms: int = 10,
        cancellation_grace_ms: int = 250,
        structured_output: bool = True,
    ) -> None:
        self._provider = _required_label(provider, "provider", max_length=100)
        self._model = _required_label(model, "model", max_length=200)
        if not isinstance(budget, RunBudgetSettings):
            raise ValueError("budget has an invalid type")
        for value, label in (
            (cancellation_poll_ms, "cancellation_poll_ms"),
            (cancellation_grace_ms, "cancellation_grace_ms"),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or value < 1
            ):
                raise ValueError(f"{label} must be a positive integer")
        self._agent_factory = agent_factory
        self._model_factory = model_factory
        self._runner = runner
        self._budget = budget
        self._max_turns = min(budget.max_steps, budget.max_model_calls)
        self._max_turn_failure_code = (
            "model_call_budget_exceeded"
            if budget.max_model_calls <= budget.max_steps
            else "max_steps_exceeded"
        )
        self._cancellation_poll_ms = cancellation_poll_ms
        self._cancellation_grace_ms = cancellation_grace_ms
        if not isinstance(structured_output, bool):
            raise ValueError("structured_output must be a boolean")
        self._structured_output = structured_output
        self._max_output_bytes = min(
            _MAX_FINAL_OUTPUT_BYTES,
            max(1_024, budget.max_output_tokens * 16),
        )

    def __repr__(self) -> str:
        return (
            "OpenAIAgentsRuntime("
            f"provider={self._provider!r}, model={self._model!r})"
        )

    async def run(
        self,
        request: RuntimeRequest,
        *,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeResult:
        token = control.cancellation_token
        if token.is_cancelled:
            return _cancelled_result(token.reason, step=0)
        run_context = OpenAIAgentsRunContext(
            run_id=request.run_id,
            execution_context=(
                request.execution_context
                if request.execution_context is not None
                else ToolExecutionContext()
            ),
            cancellation_token=token,
        )
        try:
            agent = self._agent_factory(request, run_context)
        except Exception:
            return _failure_result(
                code="agents_sdk_configuration_error",
                category="runtime",
                public_message="Agents SDK runtime configuration failed",
            )
        if token.is_cancelled:
            return _cancelled_result(token.reason, step=0)

        try:
            model_manager = self._model_factory()
            model = await model_manager.__aenter__()
        except asyncio.CancelledError:
            raise
        except Exception:
            return _failure_result(
                code="agents_sdk_configuration_error",
                category="runtime",
                public_message="Agents SDK model configuration failed",
            )

        try:
            run_config = self._create_run_config(model)
            try:
                stream = self._runner.run_streamed(
                    agent,
                    request.input_text,
                    context=run_context,
                    max_turns=self._max_turns,
                    run_config=run_config,
                )
            except asyncio.CancelledError:
                raise
            except Exception as error:
                return _failure_from_exception(
                    error,
                    step=0,
                    max_turn_failure_code=self._max_turn_failure_code,
                )
            return await self._consume_stream(
                stream,
                emit=emit,
                control=control,
            )
        finally:
            try:
                await model_manager.__aexit__(None, None, None)
            except asyncio.CancelledError:
                raise
            except Exception:
                LOGGER.warning("Agents SDK model cleanup failed")

    def _create_run_config(self, model: object) -> RunConfig:
        return RunConfig(
            model=model,
            model_settings=ModelSettings(
                max_tokens=self._budget.max_output_tokens,
                include_usage=True,
                retry=ModelRetrySettings(
                    max_retries=self._budget.max_model_retries,
                    backoff=ModelRetryBackoffSettings(
                        initial_delay=(
                            self._budget.model_retry_initial_delay_ms / 1_000
                        ),
                        max_delay=(
                            self._budget.model_retry_max_delay_ms / 1_000
                        ),
                        multiplier=2,
                        jitter=False,
                    ),
                    policy=retry_policies.provider_suggested(),
                ),
            ),
            tracing_disabled=True,
            trace_include_sensitive_data=False,
            workflow_name="AI Agent learning runtime",
        )

    async def _consume_stream(
        self,
        stream: _StreamingRun,
        *,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeResult:
        state = _StreamState(
            structured_answer=(
                _StructuredAnswerStream()
                if self._structured_output
                else None
            )
        )
        consumer = asyncio.create_task(
            self._consume_events(stream, emit=emit, state=state)
        )
        cancellation = asyncio.create_task(
            self._wait_for_cancellation(control)
        )
        aborted = asyncio.create_task(state.abort_requested.wait())
        try:
            await asyncio.wait(
                {consumer, cancellation, aborted},
                return_when=asyncio.FIRST_COMPLETED,
            )
        except asyncio.CancelledError:
            state.suppress_events = True
            self._cancel_stream(stream, state)
            await self._bounded_cleanup(consumer)
            await _cancel_task(cancellation)
            await _cancel_task(aborted)
            if _is_sink_failure(state.failure):
                assert state.failure is not None
                raise state.failure
            raise

        if control.cancellation_token.is_cancelled:
            state.suppress_events = True
            self._cancel_stream(stream, state)
            await self._bounded_cleanup(consumer)
            await _cancel_task(cancellation)
            await _cancel_task(aborted)
            if _is_sink_failure(state.failure):
                assert state.failure is not None
                raise state.failure
            return _cancelled_result(
                control.cancellation_token.reason,
                step=state.step,
            )

        await _cancel_task(cancellation)
        await _cancel_task(aborted)
        if state.abort_requested.is_set():
            await self._bounded_cleanup(consumer)
            return _consumer_failure_result(
                state.failure,
                step=state.step,
                max_turn_failure_code=self._max_turn_failure_code,
            )
        try:
            await consumer
        except _StreamFailure as failure:
            return _failure_from_exception(
                failure.error,
                step=state.step,
                max_turn_failure_code=self._max_turn_failure_code,
            )
        except _BudgetFailure as failure:
            return _failure_result(
                code=failure.code,
                category="budget",
                public_message="Model output exceeded the configured budget",
                step=state.step,
            )
        except _ContractFailure as failure:
            return _failure_result(
                code=failure.code,
                category="runtime",
                public_message="Agents SDK returned an invalid result",
                step=state.step,
            )

        run_loop_exception = getattr(stream, "run_loop_exception", None)
        if run_loop_exception is not None:
            if not isinstance(run_loop_exception, Exception):
                return _failure_result(
                    code="agents_sdk_contract_error",
                    category="runtime",
                    public_message="Agents SDK returned an invalid result",
                    step=state.step,
                )
            return _failure_from_exception(
                run_loop_exception,
                step=state.step,
                max_turn_failure_code=self._max_turn_failure_code,
            )
        interruptions = getattr(stream, "interruptions", ())
        if interruptions:
            return _failure_result(
                code="agents_sdk_interruption_not_supported",
                category="workflow",
                public_message="This runtime cannot resume an interrupted run yet",
                step=state.step,
            )
        if not getattr(stream, "is_complete", False):
            return _failure_result(
                code="agents_sdk_contract_error",
                category="runtime",
                public_message="Agents SDK returned an incomplete result",
                step=state.step,
            )
        if state.tool_names:
            return _failure_result(
                code="agents_sdk_contract_error",
                category="runtime",
                public_message="Agents SDK returned an invalid result",
                step=state.step,
            )

        try:
            usage_event, usage = self._usage_event(stream, state)
        except _ContractFailure as failure:
            return _failure_result(
                code=failure.code,
                category="provider",
                public_message="Agents SDK usage was unavailable or invalid",
                step=state.step,
            )
        await emit(usage_event)
        budget_failure = self._usage_budget_failure(usage)
        if budget_failure is not None:
            return _failure_result(
                code=budget_failure,
                category="budget",
                public_message="Model usage exceeded the configured budget",
                step=state.step,
            )
        try:
            answer = _normalize_final_output(
                getattr(stream, "final_output", None),
                max_bytes=self._max_output_bytes,
            )
            if state.structured_answer is not None:
                state.structured_answer.validate(answer)
        except (TypeError, ValueError):
            return _failure_result(
                code="agents_sdk_contract_error",
                category="runtime",
                public_message="Agents SDK returned an invalid result",
                step=state.step,
            )
        return RuntimeResult(
            status=RunStatus.COMPLETED,
            answer=answer,
            step=state.step,
        )

    async def _consume_events(
        self,
        stream: _StreamingRun,
        *,
        emit: RuntimeEventSink,
        state: _StreamState,
    ) -> None:
        try:
            iterator = stream.stream_events().__aiter__()
        except Exception:
            failure = _ContractFailure()
            self._start_abort(stream, state, failure)
            raise failure from None
        while True:
            try:
                event = await anext(iterator)
            except StopAsyncIteration:
                break
            except asyncio.CancelledError:
                raise
            except Exception as error:
                failure = _StreamFailure(error)
                self._start_abort(stream, state, failure)
                raise failure from None
            if state.suppress_events:
                continue
            try:
                for runtime_event in self._map_event(event, state):
                    if state.suppress_events:
                        break
                    await emit(runtime_event)
            except asyncio.CancelledError:
                raise
            except Exception as failure:
                self._start_abort(stream, state, failure)
        if state.failure is not None:
            raise state.failure

    def _start_abort(
        self,
        stream: _StreamingRun,
        state: _StreamState,
        failure: Exception,
    ) -> None:
        if state.failure is None:
            state.failure = failure
        state.suppress_events = True
        self._cancel_stream(stream, state)
        state.abort_requested.set()

    def _map_event(
        self,
        event: object,
        state: _StreamState,
    ) -> tuple[RuntimeEvent, ...]:
        event_type = getattr(event, "type", None)
        if event_type == "raw_response_event":
            data = getattr(event, "data", None)
            if getattr(data, "type", None) != "response.output_text.delta":
                return ()
            delta = getattr(data, "delta", None)
            if not isinstance(delta, str):
                raise _ContractFailure()
            if not delta:
                return ()
            try:
                raw_delta_bytes = len(delta.encode("utf-8"))
            except UnicodeError:
                raise _ContractFailure() from None
            if raw_delta_bytes > _MAX_DELTA_BYTES:
                raise _BudgetFailure("output_token_budget_exceeded")
            state.wire_output_bytes += raw_delta_bytes
            if state.wire_output_bytes > self._max_output_bytes + 1_024:
                raise _BudgetFailure("output_token_budget_exceeded")
            if state.structured_answer is not None:
                decoded_deltas = state.structured_answer.feed(delta)
                if not decoded_deltas:
                    return ()
            else:
                decoded_deltas = ((None, delta),)
            runtime_events: list[RuntimeEvent] = []
            for segment, decoded_delta in decoded_deltas:
                try:
                    delta_bytes = len(decoded_delta.encode("utf-8"))
                except UnicodeError:
                    raise _ContractFailure() from None
                state.output_bytes += delta_bytes
                if state.output_bytes > self._max_output_bytes:
                    raise _BudgetFailure("output_token_budget_exceeded")
                event_data: dict[str, object] = {"delta": decoded_delta}
                if segment is not None:
                    event_data["segment"] = segment
                runtime_events.append(
                    RuntimeEvent(
                        type="model.output.delta",
                        step=state.next_step(),
                        data=event_data,
                    )
                )
            return tuple(runtime_events)
        if event_type == "agent_updated_stream_event":
            state.agent_updates += 1
            if state.agent_updates > 1:
                raise _ContractFailure(
                    "agents_sdk_handoff_not_supported"
                )
            return ()
        if event_type != "run_item_stream_event":
            raise _ContractFailure()

        name = getattr(event, "name", None)
        item = getattr(event, "item", None)
        if name == "tool_called":
            call_id = _item_identifier(item, "call_id")
            tool_name = _item_identifier(item, "tool_name")
            if call_id in state.tool_names:
                raise _ContractFailure()
            state.tool_names[call_id] = tool_name
            return (
                RuntimeEvent(
                    type="tool.started",
                    step=state.next_step(),
                    data={"id": call_id, "name": tool_name},
                ),
            )
        if name == "tool_output":
            call_id = _item_identifier(item, "call_id")
            tool_name = state.tool_names.pop(call_id, None)
            if tool_name is None:
                raise _ContractFailure()
            custom_data = getattr(item, "custom_data", None)
            if not isinstance(custom_data, Mapping):
                raise _ContractFailure()
            ok = custom_data.get("ok")
            if not isinstance(ok, bool):
                raise _ContractFailure()
            event_data: dict[str, object] = {
                "id": call_id,
                "name": tool_name,
                "ok": ok,
            }
            runtime_type = "tool.completed"
            if not ok:
                runtime_type = "tool.failed"
                event_data["error_code"] = _safe_error_code(
                    custom_data.get("error_code")
                )
            return (
                RuntimeEvent(
                    type=runtime_type,
                    step=state.next_step(),
                    data=event_data,
                ),
            )
        if name in {"message_output_created", "reasoning_item_created"}:
            return ()
        raise _ContractFailure("agents_sdk_workflow_event_not_supported")

    def _usage_event(
        self,
        stream: _StreamingRun,
        state: _StreamState,
    ) -> tuple[RuntimeEvent, dict[str, int]]:
        context_wrapper = getattr(stream, "context_wrapper", None)
        usage_object = getattr(context_wrapper, "usage", None)
        if usage_object is None:
            raise _ContractFailure("agents_sdk_usage_missing")
        usage = {
            name: _nonnegative_int(getattr(usage_object, name, None))
            for name in (
                "requests",
                "input_tokens",
                "output_tokens",
                "total_tokens",
            )
        }
        if usage["total_tokens"] != (
            usage["input_tokens"] + usage["output_tokens"]
        ):
            raise _ContractFailure("agents_sdk_usage_invalid")
        if usage["requests"] == 0 or usage["total_tokens"] == 0:
            raise _ContractFailure("agents_sdk_usage_invalid")
        event = RuntimeEvent(
            type="model.usage",
            step=state.next_step(),
            data={
                "scope": "run",
                "provider": self._provider,
                "model": self._model,
                **usage,
                "estimated_cost_usd": None,
                "cost_source": "unknown",
            },
        )
        return event, usage

    def _usage_budget_failure(self, usage: Mapping[str, int]) -> str | None:
        if usage["requests"] > self._budget.max_model_calls:
            return "model_call_budget_exceeded"
        if usage["input_tokens"] > self._budget.max_input_tokens:
            return "input_token_budget_exceeded"
        if usage["output_tokens"] > self._budget.max_output_tokens:
            return "output_token_budget_exceeded"
        return None

    async def _wait_for_cancellation(self, control: RuntimeControl) -> None:
        while not control.cancellation_token.is_cancelled:
            await asyncio.sleep(self._cancellation_poll_ms / 1_000)

    def _cancel_stream(
        self,
        stream: _StreamingRun,
        state: _StreamState,
    ) -> None:
        if state.cancel_called:
            return
        state.cancel_called = True
        try:
            stream.cancel("immediate")
        except Exception:
            LOGGER.warning("Agents SDK stream cancellation failed")

    async def _bounded_cleanup(self, consumer: asyncio.Task[None]) -> None:
        try:
            async with asyncio.timeout(self._cancellation_grace_ms / 1_000):
                await asyncio.shield(consumer)
        except TimeoutError:
            consumer.cancel()
            try:
                async with asyncio.timeout(
                    self._cancellation_grace_ms / 1_000
                ):
                    await asyncio.shield(consumer)
            except BaseException:
                if not consumer.done():
                    consumer.add_done_callback(_consume_task_result)
        except BaseException:
            pass


def create_openai_model_factory(
    *,
    api_key: str,
    model: str,
    timeout_ms: int,
) -> ModelFactory:
    """Create per-Run explicit clients without mutating SDK global state."""

    _required_label(api_key, "api_key", max_length=512)
    resolved_model = _required_label(model, "model", max_length=200)
    if (
        not isinstance(timeout_ms, int)
        or isinstance(timeout_ms, bool)
        or timeout_ms < 1
    ):
        raise ValueError("timeout_ms must be a positive integer")

    @asynccontextmanager
    async def create_model():
        client = openai.AsyncOpenAI(
            api_key=api_key,
            timeout=timeout_ms / 1_000,
            max_retries=0,
        )
        try:
            yield OpenAIResponsesModel(
                model=resolved_model,
                openai_client=client,
            )
        finally:
            try:
                async with asyncio.timeout(min(timeout_ms, 1_000) / 1_000):
                    await client.close()
            except TimeoutError:
                LOGGER.warning("OpenAI client cleanup timed out")

    return create_model


def _failure_from_exception(
    error: Exception,
    *,
    step: int,
    max_turn_failure_code: str,
) -> RuntimeResult:
    if isinstance(error, MaxTurnsExceeded):
        return _registered_failure_result(max_turn_failure_code, step=step)
    if isinstance(error, ModelBehaviorError):
        return _registered_failure_result("provider_invalid_response", step=step)
    if isinstance(error, ModelRefusalError):
        return _failure_result(
            code="model_refused",
            category="provider",
            public_message="The model declined the request",
            step=step,
        )
    if isinstance(error, ToolTimeoutError):
        return _registered_failure_result("tool_timeout", step=step)
    if isinstance(error, TimeoutError):
        return _registered_failure_result("provider_timeout", step=step)
    if isinstance(
        error,
        (
            InputGuardrailTripwireTriggered,
            OutputGuardrailTripwireTriggered,
            ToolInputGuardrailTripwireTriggered,
            ToolOutputGuardrailTripwireTriggered,
        ),
    ):
        return _failure_result(
            code="guardrail_blocked",
            category="security",
            public_message="A safety guardrail blocked the run",
            step=step,
        )
    if isinstance(error, UserError):
        return _failure_result(
            code="agents_sdk_configuration_error",
            category="runtime",
            public_message="Agents SDK runtime configuration failed",
            step=step,
        )
    if isinstance(error, openai.APITimeoutError):
        return _registered_failure_result("provider_timeout", step=step)
    if isinstance(error, openai.RateLimitError):
        return _registered_failure_result("provider_rate_limited", step=step)
    if isinstance(
        error,
        (openai.AuthenticationError, openai.PermissionDeniedError),
    ):
        return _registered_failure_result("provider_auth_failed", step=step)
    if isinstance(
        error,
        (
            openai.BadRequestError,
            openai.NotFoundError,
            openai.UnprocessableEntityError,
        ),
    ):
        return _registered_failure_result("provider_request_rejected", step=step)
    if isinstance(error, (openai.InternalServerError, openai.APIConnectionError)):
        return _registered_failure_result("provider_unavailable", step=step)
    if isinstance(error, openai.APIStatusError):
        return _registered_failure_result(
            (
                "provider_unavailable"
                if error.status_code >= 500
                else "provider_request_rejected"
            ),
            step=step,
        )
    if isinstance(error, AgentsException):
        return _failure_result(
            code="agents_sdk_execution_failed",
            category="runtime",
            public_message="Agents SDK execution failed",
            step=step,
        )
    return _failure_result(
        code="agents_sdk_execution_failed",
        category="runtime",
        public_message="Agents SDK execution failed",
        step=step,
    )


def _consumer_failure_result(
    failure: Exception | None,
    *,
    step: int,
    max_turn_failure_code: str,
) -> RuntimeResult:
    if isinstance(failure, _StreamFailure):
        return _failure_from_exception(
            failure.error,
            step=step,
            max_turn_failure_code=max_turn_failure_code,
        )
    if isinstance(failure, _BudgetFailure):
        return _failure_result(
            code=failure.code,
            category="budget",
            public_message="Model output exceeded the configured budget",
            step=step,
        )
    if isinstance(failure, _ContractFailure):
        return _failure_result(
            code=failure.code,
            category="runtime",
            public_message="Agents SDK returned an invalid result",
            step=step,
        )
    if failure is not None:
        raise failure
    return _failure_result(
        code="agents_sdk_contract_error",
        category="runtime",
        public_message="Agents SDK returned an invalid result",
        step=step,
    )


def _registered_failure_result(code: str, *, step: int) -> RuntimeResult:
    return RuntimeResult(
        status=RunStatus.FAILED,
        failure=stable_run_failure(code, step=step),
        step=step,
    )


def _is_sink_failure(failure: Exception | None) -> bool:
    return failure is not None and not isinstance(
        failure,
        (_StreamFailure, _BudgetFailure, _ContractFailure),
    )


def _failure_result(
    *,
    code: str,
    category: str,
    public_message: str,
    retryable: bool = False,
    step: int = 0,
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


def _cancelled_result(reason: str | None, *, step: int) -> RuntimeResult:
    if reason == "deadline_exceeded":
        return _failure_result(
            code="run_timeout",
            category="timeout",
            public_message="Run timed out",
            step=step,
        )
    code = (
        reason
        if reason in {"cancelled_by_user", "client_disconnected"}
        else "run_cancelled"
    )
    return RuntimeResult(
        status=RunStatus.CANCELLED,
        failure=RunFailure(
            code=code,
            category="cancellation",
            public_message="Run cancelled",
            step=step,
        ),
        step=step,
    )


def _normalize_final_output(value: object, *, max_bytes: int) -> str:
    if isinstance(value, OpenAIAgentOutput):
        answer = value.answer
    elif isinstance(value, str):
        answer = value
    else:
        if isinstance(value, BaseModel):
            payload: object = value.model_dump(mode="json")
        elif isinstance(value, Mapping):
            payload = dict(value)
        elif isinstance(value, (list, tuple)):
            payload = list(value)
        else:
            raise TypeError("unsupported final output")
        if (
            isinstance(payload, Mapping)
            and isinstance(payload.get("answer"), str)
            and len(payload) == 1
        ):
            answer = payload["answer"]
        else:
            answer = json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
    if not answer.strip():
        raise ValueError("final output must not be empty")
    if len(answer.encode("utf-8")) > min(max_bytes, _MAX_FINAL_OUTPUT_BYTES):
        raise ValueError("final output exceeds its byte budget")
    return answer


def _item_identifier(item: object, name: str) -> str:
    try:
        return _required_label(
            getattr(item, name, None),
            name,
            max_length=200,
        )
    except ValueError:
        raise _ContractFailure() from None


def _required_label(value: object, label: str, *, max_length: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_length
        or any(character.isspace() or not character.isprintable() for character in value)
    ):
        raise ValueError(f"{label} has an invalid format")
    return value


def _safe_error_code(value: object) -> str:
    if (
        isinstance(value, str)
        and value
        and value == value.strip()
        and len(value) <= 100
        and all(character.isalnum() or character == "_" for character in value)
    ):
        return value
    return "tool_execution_failed"


def _nonnegative_int(value: object) -> int:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 0
    ):
        raise _ContractFailure("agents_sdk_usage_invalid")
    return value


async def _cancel_task(task: asyncio.Task[None]) -> None:
    if not task.done():
        task.cancel()
    with suppress(asyncio.CancelledError):
        await task


def _consume_task_result(task: asyncio.Task[None]) -> None:
    try:
        task.result()
    except BaseException:
        pass


__all__ = [
    "OpenAIAgentOutput",
    "OpenAIAgentsRunContext",
    "OpenAIAgentsRuntime",
    "add_numbers",
    "build_sdk_tools",
    "create_openai_learning_agent",
    "create_openai_model_factory",
]
