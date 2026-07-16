from __future__ import annotations

import asyncio
import json
import unittest
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, Mock, patch

import httpx
import openai
from agents import AgentOutputSchema
from agents.exceptions import (
    InputGuardrailTripwireTriggered,
    MaxTurnsExceeded,
    ModelBehaviorError,
    ModelRefusalError,
    ToolTimeoutError,
    UserError,
)
from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent
from agents.tool import FunctionToolCustomDataContext
from agents.tool_context import ToolContext
from agents.usage import Usage
from openai.types.responses import ResponseTextDeltaEvent

from backend.app.agent import CancellationToken
from backend.app.agent.runtime import RuntimeControl, RuntimeEvent, RuntimeRequest
from backend.app.agent.sdk_runtime import (
    OpenAIAgentOutput,
    OpenAIAgentsRunContext,
    OpenAIAgentsRuntime,
    build_sdk_tools,
    create_openai_model_factory,
)
from backend.app.domain.run import RunRecord, RunStatus
from backend.app.services import RunCoordinator
from backend.app.settings import RunBudgetSettings
from backend.app.stores import (
    InMemoryEventStore,
    InMemoryRunStore,
    StoreUnavailableError,
)
from backend.app.tools import (
    InMemoryApprovalStore,
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolRisk,
)


class OpenAIAgentsRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_provider_schema_omits_length_keywords_but_runtime_bounds_output(
        self,
    ) -> None:
        schema = AgentOutputSchema(OpenAIAgentOutput).json_schema()
        answer_schema = schema["properties"]["answer"]
        self.assertNotIn("minLength", answer_schema)
        self.assertNotIn("maxLength", answer_schema)

        stream = FakeStreamingRun(
            events=(),
            final_output=OpenAIAgentOutput(answer="x" * 1_601),
            usage=_usage(),
        )
        runtime, _, _ = _runtime(
            stream,
            budget=RunBudgetSettings(max_output_tokens=100),
        )

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="hello"),
            emit=_collecting_sink([]),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("agents_sdk_contract_error", result.failure.code)

    async def test_model_factory_uses_an_explicit_per_run_client_and_closes_it(
        self,
    ) -> None:
        client = Mock()
        client.close = AsyncMock()
        with patch(
            "backend.app.agent.sdk_runtime.openai.AsyncOpenAI",
            return_value=client,
        ) as client_factory:
            model_factory = create_openai_model_factory(
                api_key="factory-secret",
                model="configured-model",
                timeout_ms=2_500,
            )
            client_factory.assert_not_called()

            async with model_factory() as model:
                self.assertEqual("configured-model", model.model)

        client_factory.assert_called_once_with(
            api_key="factory-secret",
            timeout=2.5,
            max_retries=0,
        )
        client.close.assert_awaited_once_with()

    async def test_streams_reviewed_text_and_maps_structured_output_and_usage(
        self,
    ) -> None:
        stream = FakeStreamingRun(
            events=(
                _text_delta('{"answer":"Hello ', 1),
                _text_delta('world"}', 2),
            ),
            final_output=OpenAIAgentOutput(answer="Hello world"),
            usage=Usage(
                requests=2,
                input_tokens=11,
                output_tokens=4,
                total_tokens=15,
            ),
        )
        runtime, runner, models = _runtime(stream)
        emitted: list[RuntimeEvent] = []

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="Say hello"),
            emit=_collecting_sink(emitted),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual("Hello world", result.answer)
        self.assertEqual(
            ["model.output.delta", "model.output.delta", "model.usage"],
            [event.type for event in emitted],
        )
        self.assertEqual(["Hello ", "world"], [event.data["delta"] for event in emitted[:2]])
        self.assertEqual([1, 1], [event.data["segment"] for event in emitted[:2]])
        self.assertEqual(
            {
                "scope": "run",
                "provider": "openai",
                "model": "test-model",
                "requests": 2,
                "input_tokens": 11,
                "output_tokens": 4,
                "total_tokens": 15,
                "estimated_cost_usd": None,
                "cost_source": "unknown",
            },
            emitted[-1].data,
        )
        self.assertEqual(1, runner.calls)
        call = runner.call_args[0]
        self.assertEqual("Say hello", call["input"])
        self.assertEqual(4, call["max_turns"])
        self.assertIs(models.model, call["run_config"].model)
        self.assertTrue(call["run_config"].tracing_disabled)
        self.assertFalse(call["run_config"].trace_include_sensitive_data)
        self.assertTrue(call["run_config"].model_settings.include_usage)
        self.assertEqual(100, call["run_config"].model_settings.max_tokens)
        self.assertEqual(
            2,
            call["run_config"].model_settings.retry.max_retries,
        )
        self.assertEqual(1, models.entered)
        self.assertEqual(1, models.exited)

    async def test_decodes_structured_answer_escapes_across_chunks(self) -> None:
        answer = 'line\nquote:" emoji:🚀'
        stream = FakeStreamingRun(
            events=(
                _text_delta(' { "answer" : "line\\', 1),
                _text_delta('nquote:\\" emoji:\\uD83D', 2),
                _text_delta('\\uDE80" } ', 3),
            ),
            final_output=OpenAIAgentOutput(answer=answer),
            usage=_usage(),
        )
        runtime, _, _ = _runtime(stream)
        emitted: list[RuntimeEvent] = []

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="hello"),
            emit=_collecting_sink(emitted),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        deltas = [
            event.data["delta"]
            for event in emitted
            if event.type == "model.output.delta"
        ]
        self.assertEqual(answer, "".join(deltas))
        self.assertEqual("🚀", deltas[-1])

    async def test_decodes_escaped_key_and_tracks_the_latest_structured_turn(
        self,
    ) -> None:
        stream = FakeStreamingRun(
            events=(
                _text_delta('{"answer":"draft"}', 1),
                _text_delta('{"\\u0061ns', 2),
                _text_delta('wer":"final"}', 3),
            ),
            final_output=OpenAIAgentOutput(answer="final"),
            usage=_usage(requests=2),
        )
        runtime, _, _ = _runtime(stream)
        emitted: list[RuntimeEvent] = []

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="hello"),
            emit=_collecting_sink(emitted),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual("final", result.answer)
        deltas = [
            event.data["delta"]
            for event in emitted
            if event.type == "model.output.delta"
        ]
        self.assertEqual(["draft", "final"], deltas)
        self.assertEqual(
            [1, 2],
            [
                event.data["segment"]
                for event in emitted
                if event.type == "model.output.delta"
            ],
        )
        self.assertNotIn("answer", "".join(deltas))

    async def test_structured_stream_must_match_the_typed_final_answer(self) -> None:
        stream = FakeStreamingRun(
            events=(_text_delta('{"answer":"visible"}', 1),),
            final_output=OpenAIAgentOutput(answer="different"),
            usage=_usage(),
        )
        runtime, _, _ = _runtime(stream)

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="hello"),
            emit=_collecting_sink([]),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("agents_sdk_contract_error", result.failure.code)

    async def test_latest_structured_turn_must_match_the_typed_final_answer(
        self,
    ) -> None:
        stream = FakeStreamingRun(
            events=(
                _text_delta('{"answer":"typed"}', 1),
                _text_delta('{"answer":"different"}', 2),
            ),
            final_output=OpenAIAgentOutput(answer="typed"),
            usage=_usage(requests=2),
        )
        runtime, _, _ = _runtime(stream)

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="hello"),
            emit=_collecting_sink([]),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("agents_sdk_contract_error", result.failure.code)

    async def test_awaits_each_sink_before_reading_the_next_event(self) -> None:
        stream = FakeStreamingRun(
            events=(
                _text_delta('{"answer":"a', 1),
                _text_delta('b"}', 2),
            ),
            final_output="ab",
            usage=_usage(),
        )
        runtime, _, _ = _runtime(stream)
        active = 0
        seen: list[str] = []

        async def slow_sink(event: RuntimeEvent) -> None:
            nonlocal active
            active += 1
            self.assertEqual(1, active)
            await asyncio.sleep(0)
            seen.append(event.type)
            active -= 1

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="hello"),
            emit=slow_sink,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual(
            ["model.output.delta", "model.output.delta", "model.usage"],
            seen,
        )

    async def test_processing_failures_cancel_and_drain_the_same_stream(self) -> None:
        cases = (
            (
                FakeStreamingRun(
                    events=(SimpleNamespace(type="unknown_wrapper"),),
                    final_output=None,
                    usage=None,
                ),
                None,
                "agents_sdk_contract_error",
            ),
            (
                FakeStreamingRun(
                    events=(_text_delta('{"answer":"' + "x" * 1_100, 1),),
                    final_output=None,
                    usage=None,
                ),
                RunBudgetSettings(max_output_tokens=1),
                "output_token_budget_exceeded",
            ),
        )
        for stream, budget, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                runtime, _, _ = _runtime(stream, budget=budget)

                result = await runtime.run(
                    RuntimeRequest(run_id="run-1", input_text="hello"),
                    emit=_collecting_sink([]),
                    control=RuntimeControl(CancellationToken()),
                )

                self.assertEqual(RunStatus.FAILED, result.status)
                self.assertEqual(expected_code, result.failure.code)
                self.assertEqual(["immediate"], stream.cancel_modes)
                self.assertTrue(stream.drained)

    async def test_maps_tool_items_without_arguments_outputs_or_errors(self) -> None:
        argument_secret = "argument-secret"
        result_secret = "result-secret"
        error_secret = "error-secret"
        stream = FakeStreamingRun(
            events=(
                RunItemStreamEvent(
                    name="tool_called",
                    item=FakeToolCallItem(
                        tool_name="lookup",
                        call_id="call-1",
                        raw_item={"arguments": argument_secret},
                    ),
                ),
                RunItemStreamEvent(
                    name="tool_output",
                    item=FakeToolOutputItem(
                        call_id="call-1",
                        output=result_secret,
                        custom_data={"ok": True},
                    ),
                ),
                RunItemStreamEvent(
                    name="tool_called",
                    item=FakeToolCallItem(
                        tool_name="publish",
                        call_id="call-2",
                        raw_item={"arguments": argument_secret},
                    ),
                ),
                RunItemStreamEvent(
                    name="tool_output",
                    item=FakeToolOutputItem(
                        call_id="call-2",
                        output=error_secret,
                        custom_data={"ok": False, "error_code": "permission_denied"},
                    ),
                ),
            ),
            final_output="safe answer",
            usage=_usage(requests=2),
        )
        runtime, _, _ = _runtime(stream)
        emitted: list[RuntimeEvent] = []

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="use tools"),
            emit=_collecting_sink(emitted),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual(
            [
                "tool.started",
                "tool.completed",
                "tool.started",
                "tool.failed",
                "model.usage",
            ],
            [event.type for event in emitted],
        )
        self.assertEqual(
            {"id": "call-1", "name": "lookup", "ok": True},
            emitted[1].data,
        )
        self.assertEqual("permission_denied", emitted[3].data["error_code"])
        serialized = json.dumps(
            [dict(event.data) for event in emitted],
            ensure_ascii=False,
        )
        self.assertNotIn(argument_secret, serialized)
        self.assertNotIn(result_secret, serialized)
        self.assertNotIn(error_secret, serialized)

    async def test_unknown_raw_events_are_ignored_but_unknown_wrappers_fail_closed(
        self,
    ) -> None:
        ignored_secret = "raw-secret"
        ignored = RawResponsesStreamEvent(
            data=SimpleNamespace(type="response.created", secret=ignored_secret)
        )
        runtime, _, _ = _runtime(
            FakeStreamingRun(
                events=(ignored,),
                final_output="done",
                usage=_usage(),
            )
        )
        emitted: list[RuntimeEvent] = []

        completed = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="hello"),
            emit=_collecting_sink(emitted),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.COMPLETED, completed.status)
        self.assertEqual(["model.usage"], [event.type for event in emitted])
        self.assertNotIn(ignored_secret, repr(emitted))

        invalid_runtime, _, _ = _runtime(
            FakeStreamingRun(
                events=(SimpleNamespace(type="future_wrapper", secret=ignored_secret),),
                final_output="must-not-complete",
                usage=_usage(),
            )
        )
        invalid_events: list[RuntimeEvent] = []
        failed = await invalid_runtime.run(
            RuntimeRequest(run_id="run-2", input_text="hello"),
            emit=_collecting_sink(invalid_events),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, failed.status)
        self.assertEqual("agents_sdk_contract_error", failed.failure.code)
        self.assertNotIn(ignored_secret, failed.failure.public_message)
        self.assertEqual([], invalid_events)

    async def test_invalid_tool_items_and_unfinished_tools_fail_as_contract_errors(
        self,
    ) -> None:
        cases = (
            (
                RunItemStreamEvent(
                    name="tool_called",
                    item=SimpleNamespace(call_id="call-1"),
                ),
            ),
            (
                RunItemStreamEvent(
                    name="tool_called",
                    item=FakeToolCallItem(
                        tool_name="lookup",
                        call_id="call-1",
                        raw_item={},
                    ),
                ),
            ),
        )
        for events in cases:
            with self.subTest(events=events):
                runtime, _, _ = _runtime(
                    FakeStreamingRun(
                        events=events,
                        final_output="must-not-complete",
                        usage=_usage(),
                    )
                )
                result = await runtime.run(
                    RuntimeRequest(run_id="run-1", input_text="hello"),
                    emit=_collecting_sink([]),
                    control=RuntimeControl(CancellationToken()),
                )

                self.assertEqual(RunStatus.FAILED, result.status)
                self.assertEqual("agents_sdk_contract_error", result.failure.code)

    async def test_sdk_interruptions_are_not_encoded_as_completed_or_failed_tools(
        self,
    ) -> None:
        runtime, _, _ = _runtime(
            FakeStreamingRun(
                final_output=None,
                usage=_usage(),
                interruptions=[SimpleNamespace(secret="approval-secret")],
            )
        )

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="approve something"),
            emit=_collecting_sink([]),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("agents_sdk_interruption_not_supported", result.failure.code)
        self.assertEqual("workflow", result.failure.category)
        self.assertNotIn("approval-secret", result.failure.public_message)

    async def test_missing_usage_and_incomplete_stream_fail_without_fake_zeroes(
        self,
    ) -> None:
        for stream, expected_code in (
            (
                FakeStreamingRun(final_output="done", usage=None),
                "agents_sdk_usage_missing",
            ),
            (
                FakeStreamingRun(
                    final_output="done",
                    usage=_usage(),
                    is_complete=False,
                ),
                "agents_sdk_contract_error",
            ),
        ):
            with self.subTest(expected_code=expected_code):
                runtime, _, _ = _runtime(stream)
                emitted: list[RuntimeEvent] = []
                result = await runtime.run(
                    RuntimeRequest(run_id="run-1", input_text="hello"),
                    emit=_collecting_sink(emitted),
                    control=RuntimeControl(CancellationToken()),
                )

                self.assertEqual(RunStatus.FAILED, result.status)
                self.assertEqual(expected_code, result.failure.code)
                self.assertNotIn("model.usage", [event.type for event in emitted])

    async def test_zero_request_or_zero_token_usage_is_invalid(self) -> None:
        invalid_usage = (
            Usage(requests=1, input_tokens=0, output_tokens=0, total_tokens=0),
            Usage(requests=0, input_tokens=1, output_tokens=1, total_tokens=2),
        )
        for usage in invalid_usage:
            with self.subTest(usage=usage):
                runtime, _, _ = _runtime(
                    FakeStreamingRun(final_output="done", usage=usage)
                )

                result = await runtime.run(
                    RuntimeRequest(run_id="run-1", input_text="hello"),
                    emit=_collecting_sink([]),
                    control=RuntimeControl(CancellationToken()),
                )

                self.assertEqual(RunStatus.FAILED, result.status)
                self.assertEqual("agents_sdk_usage_invalid", result.failure.code)

    async def test_handoff_and_extended_workflow_events_fail_closed(self) -> None:
        cases = (
            (
                (
                    RunItemStreamEvent(
                        name="handoff_requested",
                        item=SimpleNamespace(secret="handoff-secret"),
                    ),
                ),
                "agents_sdk_workflow_event_not_supported",
            ),
            (
                (
                    SimpleNamespace(type="agent_updated_stream_event"),
                    SimpleNamespace(type="agent_updated_stream_event"),
                ),
                "agents_sdk_handoff_not_supported",
            ),
        )
        for events, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                stream = FakeStreamingRun(
                    events=events,
                    final_output=None,
                    usage=None,
                )
                runtime, _, _ = _runtime(stream)

                result = await runtime.run(
                    RuntimeRequest(run_id="run-1", input_text="hello"),
                    emit=_collecting_sink([]),
                    control=RuntimeControl(CancellationToken()),
                )

                self.assertEqual(RunStatus.FAILED, result.status)
                self.assertEqual(expected_code, result.failure.code)
                self.assertTrue(stream.drained)

    async def test_invalid_stream_shape_is_a_safe_contract_failure(self) -> None:
        invalid_stream = SimpleNamespace(
            final_output=None,
            context_wrapper=SimpleNamespace(usage=None),
            is_complete=False,
            run_loop_exception=None,
            cancel=lambda mode="immediate": None,
        )
        runner = FakeRunner(invalid_stream)
        runtime, _, _ = _runtime(FakeStreamingRun(), runner=runner)

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="hello"),
            emit=_collecting_sink([]),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("agents_sdk_contract_error", result.failure.code)

    async def test_usage_budget_excess_is_reported_after_safe_usage_event(self) -> None:
        budget = RunBudgetSettings(
            max_steps=8,
            max_model_calls=1,
            max_input_tokens=5,
            max_output_tokens=3,
        )
        runtime, _, _ = _runtime(
            FakeStreamingRun(
                final_output="too expensive",
                usage=Usage(
                    requests=2,
                    input_tokens=6,
                    output_tokens=4,
                    total_tokens=10,
                ),
            ),
            budget=budget,
        )
        emitted: list[RuntimeEvent] = []

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="hello"),
            emit=_collecting_sink(emitted),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("model_call_budget_exceeded", result.failure.code)
        self.assertEqual("budget", result.failure.category)
        self.assertEqual(["model.usage"], [event.type for event in emitted])
        self.assertIsNone(emitted[0].data["estimated_cost_usd"])

    async def test_pre_cancelled_request_never_creates_model_or_runner(self) -> None:
        token = CancellationToken()
        token.cancel("cancelled_by_user")
        stream = FakeStreamingRun(final_output="late", usage=_usage())
        runtime, runner, models = _runtime(stream)

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="hello"),
            emit=_collecting_sink([]),
            control=RuntimeControl(token),
        )

        self.assertEqual(RunStatus.CANCELLED, result.status)
        self.assertEqual("cancelled_by_user", result.failure.code)
        self.assertEqual(0, runner.calls)
        self.assertEqual(0, models.entered)

    async def test_token_cancellation_cancels_once_drains_and_suppresses_late_events(
        self,
    ) -> None:
        stream = BlockingStreamingRun(late_event=_text_delta("late-secret", 1))
        runtime, _, models = _runtime(stream, cancellation_poll_ms=1)
        token = CancellationToken()
        emitted: list[RuntimeEvent] = []
        task = asyncio.create_task(
            runtime.run(
                RuntimeRequest(run_id="run-1", input_text="hello"),
                emit=_collecting_sink(emitted),
                control=RuntimeControl(token),
            )
        )
        await asyncio.wait_for(stream.started.wait(), timeout=1)

        token.cancel("cancelled_by_user")
        result = await asyncio.wait_for(task, timeout=1)

        self.assertEqual(RunStatus.CANCELLED, result.status)
        self.assertEqual(["immediate"], stream.cancel_modes)
        self.assertTrue(stream.drained)
        self.assertEqual([], emitted)
        self.assertEqual(1, models.exited)

    async def test_outer_task_cancellation_cancels_stream_and_is_re_raised(self) -> None:
        stream = BlockingStreamingRun()
        runtime, _, _ = _runtime(stream)
        task = asyncio.create_task(
            runtime.run(
                RuntimeRequest(run_id="run-1", input_text="hello"),
                emit=_collecting_sink([]),
                control=RuntimeControl(CancellationToken()),
            )
        )
        await asyncio.wait_for(stream.started.wait(), timeout=1)

        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)

        self.assertEqual(["immediate"], stream.cancel_modes)
        self.assertTrue(stream.drained)

    async def test_sink_failure_wins_an_outer_task_cancellation_race(self) -> None:
        stream = FakeStreamingRun(
            events=(_text_delta('{"answer":"hello"}', 1),),
            final_output="hello",
            usage=_usage(),
        )
        runtime, _, _ = _runtime(stream)
        sink_started = asyncio.Event()
        release_sink = asyncio.Event()

        async def failing_sink(event: RuntimeEvent) -> None:
            del event
            sink_started.set()
            await release_sink.wait()
            raise StoreUnavailableError()

        task = asyncio.create_task(
            runtime.run(
                RuntimeRequest(run_id="run-1", input_text="hello"),
                emit=failing_sink,
                control=RuntimeControl(CancellationToken()),
            )
        )
        await asyncio.wait_for(sink_started.wait(), timeout=1)

        task.cancel()
        while not stream.cancel_modes:
            await asyncio.sleep(0)
        release_sink.set()

        with self.assertRaises(StoreUnavailableError):
            await asyncio.wait_for(task, timeout=1)
        self.assertEqual(["immediate"], stream.cancel_modes)
        self.assertTrue(stream.drained)

    async def test_abort_grace_force_closes_a_stalled_consumer(self) -> None:
        stream = StalledDrainStreamingRun()
        runtime, _, _ = _runtime(
            stream,
            cancellation_grace_ms=5,
        )

        result = await asyncio.wait_for(
            runtime.run(
                RuntimeRequest(run_id="run-1", input_text="hello"),
                emit=_collecting_sink([]),
                control=RuntimeControl(CancellationToken()),
            ),
            timeout=1,
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("agents_sdk_contract_error", result.failure.code)
        self.assertEqual(["immediate"], stream.cancel_modes)
        self.assertTrue(stream.closed)

    async def test_sink_failure_is_not_misclassified_as_provider_failure(self) -> None:
        stream = FakeStreamingRun(
            events=(_text_delta('{"answer":"hello"}', 1),),
            final_output="done",
            usage=_usage(),
        )
        runtime, _, _ = _runtime(stream)

        async def unavailable_sink(event: RuntimeEvent) -> None:
            del event
            raise StoreUnavailableError()

        with self.assertRaises(StoreUnavailableError):
            await runtime.run(
                RuntimeRequest(run_id="run-1", input_text="hello"),
                emit=unavailable_sink,
                control=RuntimeControl(CancellationToken()),
            )
        self.assertEqual(["immediate"], stream.cancel_modes)
        self.assertTrue(stream.drained)

    async def test_sink_failure_wins_a_simultaneous_token_cancellation(self) -> None:
        stream = FakeStreamingRun(
            events=(_text_delta('{"answer":"hello"}', 1),),
            final_output="hello",
            usage=_usage(),
        )
        runtime, _, _ = _runtime(stream)
        token = CancellationToken()

        async def cancelling_sink(event: RuntimeEvent) -> None:
            del event
            token.cancel("cancelled_by_user")
            raise StoreUnavailableError()

        with self.assertRaises(StoreUnavailableError):
            await runtime.run(
                RuntimeRequest(run_id="run-1", input_text="hello"),
                emit=cancelling_sink,
                control=RuntimeControl(token),
            )
        self.assertEqual(["immediate"], stream.cancel_modes)
        self.assertTrue(stream.drained)

    async def test_max_turns_uses_and_reports_the_tighter_execution_budget(
        self,
    ) -> None:
        cases = (
            (
                RunBudgetSettings(max_steps=2, max_model_calls=5),
                "max_steps_exceeded",
            ),
            (
                RunBudgetSettings(max_steps=5, max_model_calls=2),
                "model_call_budget_exceeded",
            ),
        )
        for budget, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                runner = FakeRunner(start_error=MaxTurnsExceeded("secret"))
                runtime, _, _ = _runtime(
                    FakeStreamingRun(),
                    runner=runner,
                    budget=budget,
                )

                result = await runtime.run(
                    RuntimeRequest(run_id="run-1", input_text="hello"),
                    emit=_collecting_sink([]),
                    control=RuntimeControl(CancellationToken()),
                )

                self.assertEqual(RunStatus.FAILED, result.status)
                self.assertEqual(expected_code, result.failure.code)
                self.assertEqual(
                    min(budget.max_steps, budget.max_model_calls),
                    runner.call_args[0]["max_turns"],
                )

    async def test_stream_and_post_stream_errors_use_safe_stable_mapping(self) -> None:
        secret = "provider-secret"
        cases = (
            (
                MaxTurnsExceeded(secret),
                "model_call_budget_exceeded",
                "budget",
                False,
            ),
            (ModelBehaviorError(secret), "provider_invalid_response", "provider", False),
            (ModelRefusalError(secret), "model_refused", "provider", False),
            (ToolTimeoutError("secret-tool", 1), "tool_timeout", "tool", False),
            (UserError(secret), "agents_sdk_configuration_error", "runtime", False),
            (
                InputGuardrailTripwireTriggered(
                    SimpleNamespace(guardrail=SimpleNamespace())
                ),
                "guardrail_blocked",
                "security",
                False,
            ),
            (
                _openai_error(openai.RateLimitError, 429, secret),
                "provider_rate_limited",
                "provider",
                True,
            ),
            (
                openai.APIConnectionError(
                    message=secret,
                    request=_request(),
                ),
                "provider_unavailable",
                "provider",
                True,
            ),
            (openai.APITimeoutError(_request()), "provider_timeout", "timeout", True),
            (
                _openai_error(openai.AuthenticationError, 401, secret),
                "provider_auth_failed",
                "provider",
                False,
            ),
            (
                _openai_error(openai.BadRequestError, 400, secret),
                "provider_request_rejected",
                "provider",
                False,
            ),
            (
                _openai_error(openai.InternalServerError, 500, secret),
                "provider_unavailable",
                "provider",
                True,
            ),
            (RuntimeError(secret), "agents_sdk_execution_failed", "runtime", False),
        )
        for error, code, category, retryable in cases:
            with self.subTest(error=type(error).__name__):
                runtime, _, _ = _runtime(
                    FakeStreamingRun(stream_error=error, final_output=None, usage=None)
                )
                result = await runtime.run(
                    RuntimeRequest(run_id="run-1", input_text="hello"),
                    emit=_collecting_sink([]),
                    control=RuntimeControl(CancellationToken()),
                )

                self.assertEqual(RunStatus.FAILED, result.status)
                self.assertEqual(code, result.failure.code)
                self.assertEqual(category, result.failure.category)
                self.assertEqual(retryable, result.failure.retryable)
                self.assertNotIn(secret, result.failure.public_message)
                self.assertNotIn(secret, repr(result))

        post_stream = FakeStreamingRun(
            final_output="must-not-complete",
            usage=_usage(),
            run_loop_exception=ModelBehaviorError(secret),
        )
        runtime, _, _ = _runtime(post_stream)
        result = await runtime.run(
            RuntimeRequest(run_id="run-2", input_text="hello"),
            emit=_collecting_sink([]),
            control=RuntimeControl(CancellationToken()),
        )
        self.assertEqual("provider_invalid_response", result.failure.code)

    async def test_runner_start_error_is_safe_and_does_not_leak_input(self) -> None:
        secret = "runner-start-secret"
        runner = FakeRunner(start_error=RuntimeError(secret))
        runtime, _, _ = _runtime(
            FakeStreamingRun(),
            runner=runner,
        )

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="private prompt"),
            emit=_collecting_sink([]),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual("agents_sdk_execution_failed", result.failure.code)
        self.assertNotIn(secret, result.failure.public_message)
        self.assertNotIn("private prompt", repr(result))


class OpenAIAgentsRuntimeCoordinatorTest(unittest.IsolatedAsyncioTestCase):
    async def test_coordinator_persists_sdk_progress_and_owns_lifecycle(
        self,
    ) -> None:
        stream = FakeStreamingRun(
            events=(
                _text_delta('{"answer":"Hello from SDK"}', 1),
                RunItemStreamEvent(
                    name="tool_called",
                    item=FakeToolCallItem(
                        tool_name="lookup",
                        call_id="call-1",
                        raw_item={},
                    ),
                ),
                RunItemStreamEvent(
                    name="tool_output",
                    item=FakeToolOutputItem(
                        call_id="call-1",
                        output="private-tool-output",
                        custom_data={"ok": True},
                    ),
                ),
            ),
            final_output=OpenAIAgentOutput(answer="Hello from SDK"),
            usage=_usage(requests=2),
        )
        runtime, _, _ = _runtime(stream)
        run_store = InMemoryRunStore()
        event_store = InMemoryEventStore(run_store)
        run = _durable_sdk_run("sdk-success")
        await run_store.create(run)
        coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={"agents_sdk": runtime},
            run_timeout_ms=1_000,
        )

        completed = await coordinator.execute(run.id, owner_id=run.owner_id)
        events = await event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual(RunStatus.COMPLETED, completed.status)
        self.assertEqual("Hello from SDK", completed.answer)
        self.assertEqual(
            [
                "run.started",
                "model.output.delta",
                "tool.started",
                "tool.completed",
                "model.usage",
                "run.completed",
            ],
            [event.type for event in events],
        )
        self.assertEqual(
            list(range(1, len(events) + 1)),
            [event.sequence for event in events],
        )
        self.assertEqual(
            ["run.started", "run.completed"],
            [event.type for event in events if event.type.startswith("run.")],
        )
        self.assertNotIn("private-tool-output", repr(events))

    async def test_coordinator_stores_only_safe_sdk_failure(self) -> None:
        secret = "provider-error-secret"
        runtime, _, _ = _runtime(
            FakeStreamingRun(
                stream_error=RuntimeError(secret),
                final_output=None,
                usage=None,
            )
        )
        run_store = InMemoryRunStore()
        event_store = InMemoryEventStore(run_store)
        run = _durable_sdk_run("sdk-failure")
        await run_store.create(run)
        coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={"agents_sdk": runtime},
            run_timeout_ms=1_000,
        )

        failed = await coordinator.execute(run.id, owner_id=run.owner_id)
        events = await event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual(RunStatus.FAILED, failed.status)
        self.assertEqual("agents_sdk_execution_failed", failed.failure.code)
        self.assertEqual(
            ["run.started", "run.failed"],
            [event.type for event in events],
        )
        persisted = json.dumps(
            {
                "run": failed.safe_summary(),
                "events": [
                    {"type": event.type, "data": dict(event.data)}
                    for event in events
                ],
            },
            ensure_ascii=False,
        )
        self.assertNotIn(secret, persisted)


class OpenAIAgentsToolAdapterTest(unittest.IsolatedAsyncioTestCase):
    async def test_builds_strict_sdk_tool_and_keeps_only_safe_custom_data(
        self,
    ) -> None:
        argument_secret = "argument-secret"
        result_secret = "result-secret"
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="secret_lookup",
                description="Look up one value.",
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
                handler=lambda arguments: f"{result_secret}:{arguments['value']}",
            )
        )
        run_context = OpenAIAgentsRunContext(
            run_id="run-a",
            execution_context=ToolExecutionContext(principal_id="owner"),
            cancellation_token=CancellationToken(),
        )

        tools = build_sdk_tools(registry, run_context=run_context)

        self.assertEqual(1, len(tools))
        tool = tools[0]
        self.assertTrue(tool.strict_json_schema)
        self.assertFalse(tool.params_json_schema["additionalProperties"])
        tool_context = ToolContext(
            context=run_context,
            tool_name=tool.name,
            tool_call_id="call-1",
            tool_arguments=json.dumps({"value": argument_secret}),
        )
        output = await tool.on_invoke_tool(
            tool_context,
            json.dumps({"value": argument_secret}),
        )
        custom_data = await _maybe_await(
            tool.custom_data_extractor(
                FunctionToolCustomDataContext(
                    tool_context=tool_context,
                    tool=tool,
                    output=output,
                    raw_item={"output": result_secret},
                )
            )
        )

        self.assertIn(result_secret, output)
        self.assertEqual({"ok": True}, custom_data)
        self.assertNotIn(argument_secret, repr(run_context))
        self.assertNotIn(result_secret, repr(run_context))
        self.assertNotIn(result_secret, repr(custom_data))

        other_context = OpenAIAgentsRunContext(
            run_id="run-b",
            execution_context=ToolExecutionContext(principal_id="owner"),
            cancellation_token=CancellationToken(),
        )
        mismatch_output = await tool.on_invoke_tool(
            ToolContext(
                context=other_context,
                tool_name=tool.name,
                tool_call_id="call-2",
                tool_arguments=json.dumps({"value": "safe"}),
            ),
            json.dumps({"value": "safe"}),
        )
        self.assertEqual(
            "tool_context_mismatch",
            json.loads(mismatch_output)["error_code"],
        )

    async def test_run_contexts_filter_roles_and_omit_approval_tools(self) -> None:
        read_calls = 0
        publish_calls = 0

        def read(arguments: dict[str, Any]) -> dict[str, str]:
            nonlocal read_calls
            read_calls += 1
            return {"report_id": arguments["report_id"]}

        def publish(arguments: dict[str, Any]) -> dict[str, str]:
            nonlocal publish_calls
            publish_calls += 1
            return {"report_id": arguments["report_id"]}

        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="read_report",
                description="Read a report.",
                input_schema={
                    "type": "object",
                    "properties": {"report_id": {"type": "string"}},
                    "required": ["report_id"],
                },
                handler=read,
                allowed_roles=frozenset({"editor"}),
            )
        )
        registry.register(
            ToolDefinition(
                name="publish_report",
                description="Publish a report.",
                input_schema={
                    "type": "object",
                    "properties": {"report_id": {"type": "string"}},
                    "required": ["report_id"],
                },
                handler=publish,
                allowed_roles=frozenset({"editor"}),
                risk_level=ToolRisk.HIGH,
                has_side_effects=True,
            )
        )
        arguments = {"report_id": "report-1"}
        approval_store = InMemoryApprovalStore()
        approval_store.grant(
            principal_id="editor-user",
            tool_call_id="call-1",
            tool_name="publish_report",
            arguments=arguments,
        )
        viewer_context = OpenAIAgentsRunContext(
            run_id="run-viewer",
            execution_context=ToolExecutionContext(
                principal_id="viewer-user",
                roles=frozenset({"viewer"}),
                approval_store=approval_store,
            ),
            cancellation_token=CancellationToken(),
        )
        editor_context = OpenAIAgentsRunContext(
            run_id="run-editor",
            execution_context=ToolExecutionContext(
                principal_id="editor-user",
                roles=frozenset({"editor"}),
                approval_store=approval_store,
            ),
            cancellation_token=CancellationToken(),
        )

        viewer_tools, editor_tools = await asyncio.gather(
            asyncio.to_thread(build_sdk_tools, registry, run_context=viewer_context),
            asyncio.to_thread(build_sdk_tools, registry, run_context=editor_context),
        )

        self.assertEqual((), viewer_tools)
        self.assertEqual(1, len(editor_tools))
        editor_tool = editor_tools[0]
        self.assertEqual("read_report", editor_tool.name)
        output = await editor_tool.on_invoke_tool(
            ToolContext(
                context=editor_context,
                tool_name=editor_tool.name,
                tool_call_id="call-1",
                tool_arguments=json.dumps(arguments),
            ),
            json.dumps(arguments),
        )
        self.assertTrue(json.loads(output)["ok"])
        self.assertEqual(1, read_calls)
        self.assertEqual(0, publish_calls)

    async def test_bridge_revalidates_schema_and_bounds_calls_and_outputs(
        self,
    ) -> None:
        calls = 0
        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic

        def handler(arguments: dict[str, Any]) -> object:
            nonlocal calls
            del arguments
            calls += 1
            return cyclic

        definition = ToolDefinition(
            name="bounded_tool",
            description="Return one bounded value.",
            input_schema={
                "type": "object",
                "properties": {},
                "required": [],
            },
            handler=handler,
        )
        registry = ToolRegistry()
        registry.register(definition)
        definition.input_schema["mutated_keyword"] = "not-reviewed"
        run_context = OpenAIAgentsRunContext(
            run_id="run-schema-secret",
            execution_context=ToolExecutionContext(principal_id="owner"),
            cancellation_token=CancellationToken(),
        )

        with self.assertRaisesRegex(ValueError, "Unsupported tool schema"):
            build_sdk_tools(registry, run_context=run_context)

        definition.input_schema.pop("mutated_keyword")
        tool = build_sdk_tools(registry, run_context=run_context)[0]
        invalid_call_output = await tool.on_invoke_tool(
            ToolContext(
                context=run_context,
                tool_name=tool.name,
                tool_call_id=" invalid ",
                tool_arguments="{}",
            ),
            "{}",
        )
        self.assertEqual(
            "tool_call_id_missing",
            json.loads(invalid_call_output)["error_code"],
        )
        self.assertEqual(0, calls)

        cyclic_output = await tool.on_invoke_tool(
            ToolContext(
                context=run_context,
                tool_name=tool.name,
                tool_call_id="call-1",
                tool_arguments="{}",
            ),
            "{}",
        )
        self.assertEqual(
            "tool_output_invalid",
            json.loads(cyclic_output)["error_code"],
        )
        self.assertEqual(1, calls)
        self.assertNotIn("run-schema-secret", repr(run_context))

        oversized_registry = ToolRegistry()
        oversized_registry.register(
            ToolDefinition(
                name="oversized_tool",
                description="Return too many individually valid strings.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                },
                handler=lambda arguments: ["x" * 1_000] * 70,
            )
        )
        oversized_tool = build_sdk_tools(
            oversized_registry,
            run_context=run_context,
        )[0]
        oversized_output = await oversized_tool.on_invoke_tool(
            ToolContext(
                context=run_context,
                tool_name=oversized_tool.name,
                tool_call_id="call-2",
                tool_arguments="{}",
            ),
            "{}",
        )
        self.assertEqual(
            "tool_output_invalid",
            json.loads(oversized_output)["error_code"],
        )


@dataclass
class FakeToolCallItem:
    tool_name: str
    call_id: str
    raw_item: object = field(repr=False)


@dataclass
class FakeToolOutputItem:
    call_id: str
    output: object = field(repr=False)
    custom_data: dict[str, object] | None = field(default=None, repr=False)


class FakeStreamingRun:
    def __init__(
        self,
        *,
        events: tuple[object, ...] = (),
        final_output: object = "done",
        usage: Usage | None = None,
        is_complete: bool = True,
        stream_error: BaseException | None = None,
        run_loop_exception: BaseException | None = None,
        interruptions: list[object] | None = None,
    ) -> None:
        self._events = events
        self.final_output = final_output
        self.context_wrapper = SimpleNamespace(usage=usage)
        self.is_complete = is_complete
        self._stream_error = stream_error
        self.run_loop_exception = run_loop_exception
        self.interruptions = interruptions or []
        self.cancel_modes: list[str] = []
        self.drained = False

    async def stream_events(self):
        try:
            for event in self._events:
                yield event
            if self._stream_error is not None:
                raise self._stream_error
        finally:
            self.drained = True

    def cancel(self, mode: str = "immediate") -> None:
        self.cancel_modes.append(mode)


class BlockingStreamingRun(FakeStreamingRun):
    def __init__(self, *, late_event: object | None = None) -> None:
        super().__init__(final_output=None, usage=None, is_complete=False)
        self.started = asyncio.Event()
        self._release = asyncio.Event()
        self._late_event = late_event
        self.drained = False

    async def stream_events(self):
        self.started.set()
        await self._release.wait()
        if self._late_event is not None:
            yield self._late_event
        self.drained = True

    def cancel(self, mode: str = "immediate") -> None:
        super().cancel(mode)
        self.is_complete = True
        self._release.set()


class StalledDrainStreamingRun(FakeStreamingRun):
    def __init__(self) -> None:
        super().__init__(final_output=None, usage=None, is_complete=False)
        self.closed = False

    async def stream_events(self):
        try:
            yield SimpleNamespace(type="unknown_wrapper")
            await asyncio.Event().wait()
        finally:
            self.closed = True


class FakeRunner:
    def __init__(
        self,
        stream: FakeStreamingRun | None = None,
        *,
        start_error: BaseException | None = None,
    ) -> None:
        self._stream = stream or FakeStreamingRun(usage=_usage())
        self._start_error = start_error
        self.calls = 0
        self.call_args: list[dict[str, object]] = []

    def run_streamed(
        self,
        starting_agent: object,
        input: str,
        *,
        context: object,
        max_turns: int,
        run_config: object,
    ) -> FakeStreamingRun:
        self.calls += 1
        self.call_args.append(
            {
                "starting_agent": starting_agent,
                "input": input,
                "context": context,
                "max_turns": max_turns,
                "run_config": run_config,
            }
        )
        if self._start_error is not None:
            raise self._start_error
        return self._stream


class FakeModelFactory:
    def __init__(self) -> None:
        self.model = object()
        self.entered = 0
        self.exited = 0

    def __call__(self):
        @asynccontextmanager
        async def context():
            self.entered += 1
            try:
                yield self.model
            finally:
                self.exited += 1

        return context()


def _runtime(
    stream: FakeStreamingRun,
    *,
    runner: FakeRunner | None = None,
    budget: RunBudgetSettings | None = None,
    cancellation_poll_ms: int = 5,
    cancellation_grace_ms: int = 100,
) -> tuple[OpenAIAgentsRuntime, FakeRunner, FakeModelFactory]:
    resolved_runner = runner or FakeRunner(stream)
    models = FakeModelFactory()
    runtime = OpenAIAgentsRuntime(
        agent_factory=lambda request, context: SimpleNamespace(
            name="Fake Agent",
            request_id=request.run_id,
            runtime_context=context,
        ),
        model_factory=models,
        runner=resolved_runner,
        provider="openai",
        model="test-model",
        budget=budget
        or RunBudgetSettings(
            max_steps=8,
            max_model_calls=4,
            max_input_tokens=100,
            max_output_tokens=100,
            max_model_retries=2,
        ),
        cancellation_poll_ms=cancellation_poll_ms,
        cancellation_grace_ms=cancellation_grace_ms,
    )
    return runtime, resolved_runner, models


def _text_delta(text: str, sequence: int) -> RawResponsesStreamEvent:
    return RawResponsesStreamEvent(
        data=ResponseTextDeltaEvent(
            content_index=0,
            delta=text,
            item_id="message-1",
            logprobs=[],
            output_index=0,
            sequence_number=sequence,
            type="response.output_text.delta",
        )
    )


def _usage(*, requests: int = 1) -> Usage:
    return Usage(
        requests=requests,
        input_tokens=4,
        output_tokens=2,
        total_tokens=6,
    )


def _durable_sdk_run(suffix: str) -> RunRecord:
    return RunRecord.create(
        run_id=f"run-{suffix}",
        session_id=f"session-{suffix}",
        owner_id="owner-1",
        runtime="agents_sdk",
        input_text="hello",
        idempotency_key=f"idempotency-{suffix}",
        created_at=datetime(2026, 7, 16, 8, 0, tzinfo=UTC),
    )


def _collecting_sink(events: list[RuntimeEvent]):
    async def collect(event: RuntimeEvent) -> None:
        events.append(event)

    return collect


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.openai.invalid/v1/responses")


def _openai_error(error_type, status_code: int, message: str):
    return error_type(
        message,
        response=httpx.Response(status_code, request=_request()),
        body=None,
    )


async def _maybe_await(value):
    if hasattr(value, "__await__"):
        return await value
    return value


if __name__ == "__main__":
    unittest.main()
