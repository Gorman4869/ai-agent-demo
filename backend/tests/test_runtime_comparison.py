from __future__ import annotations

import unittest

from backend.app.agent import CancellationToken
from backend.app.agent.graph_runtime import LangGraphRuntime
from backend.app.agent.runtime import RuntimeControl, RuntimeEvent, RuntimeRequest
from backend.app.domain import ModelDecision, ToolCall
from backend.app.domain.run import RunStatus
from backend.app.models import MockModel, RetryableModelError
from backend.app.tools import ToolDefinition, ToolRegistry
from backend.app.tools.builtin import create_default_registry
from backend.tests.runtime_comparison_fixtures import (
    INVALID_TYPE_CASE,
    INVALID_ARGUMENTS_CASE,
    SUCCESS_CASE,
    RuntimeContractCase,
    create_runtime_harnesses,
)


class RuntimeComparisonContractTest(unittest.IsolatedAsyncioTestCase):
    async def test_success_case_is_semantically_equal_across_three_runtimes(
        self,
    ) -> None:
        await self._assert_case(SUCCESS_CASE)

    async def test_invalid_arguments_are_semantically_equal_across_three_runtimes(
        self,
    ) -> None:
        await self._assert_case(INVALID_ARGUMENTS_CASE)

    async def test_shared_events_do_not_expose_arguments_results_or_errors(
        self,
    ) -> None:
        for case in (SUCCESS_CASE, INVALID_ARGUMENTS_CASE):
            for harness in create_runtime_harnesses(case):
                with self.subTest(case=case.name, runtime=harness.name):
                    events: list[RuntimeEvent] = []
                    await harness.runtime.run(
                        RuntimeRequest(
                            run_id=f"run-{case.name}-{harness.name}",
                            input_text=case.input_text,
                        ),
                        emit=_collecting_sink(events),
                        control=RuntimeControl(CancellationToken()),
                    )

                    for event in events:
                        self.assertFalse(event.type.startswith("run."))
                        self.assertTrue(
                            {"arguments", "value", "error_message"}.isdisjoint(
                                event.data
                            )
                        )

    async def test_langgraph_cancellation_stops_before_model_or_tool(self) -> None:
        factories_called = 0

        def create_model(request):
            nonlocal factories_called
            factories_called += 1
            return MockModel([])

        token = CancellationToken()
        token.cancel("cancelled_by_user")
        runtime = LangGraphRuntime(
            model_factory=create_model,
            tool_registry_factory=lambda _request: create_default_registry(),
        )

        result = await runtime.run(
            RuntimeRequest(run_id="run-cancelled", input_text="cancel"),
            emit=_collecting_sink([]),
            control=RuntimeControl(token),
        )

        self.assertEqual(RunStatus.CANCELLED, result.status)
        self.assertEqual("cancelled_by_user", result.failure.code)
        self.assertEqual(0, factories_called)

    async def test_langgraph_model_error_is_normalized_without_raw_text(self) -> None:
        secret = "model-secret-error"

        class BrokenModel:
            def decide(self, messages, tools):
                del messages, tools
                raise RuntimeError(secret)

        result = await LangGraphRuntime(
            model_factory=lambda _request: BrokenModel(),
            tool_registry_factory=lambda _request: create_default_registry(),
            max_model_retries=0,
        ).run(
            RuntimeRequest(run_id="run-error", input_text="fail"),
            emit=_collecting_sink([]),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("model_execution_failed", result.failure.code)
        self.assertNotIn(secret, result.failure.public_message)
        self.assertNotIn(secret, repr(result))

    async def test_langgraph_retries_model_and_read_only_tool_with_events(self) -> None:
        model_calls = 0
        tool_calls = 0

        class FlakyModel:
            def decide(self, messages, tools):
                nonlocal model_calls
                del messages, tools
                model_calls += 1
                if model_calls == 1:
                    raise RetryableModelError("transient model fixture")
                if model_calls == 2:
                    return ModelDecision(
                        tool_call=ToolCall(
                            id="call-retry",
                            name="lookup",
                            arguments={},
                        )
                    )
                return ModelDecision(final_answer="recovered")

        def create_tools(_request):
            def flaky_lookup(_arguments: dict[str, object]) -> str:
                nonlocal tool_calls
                tool_calls += 1
                if tool_calls == 1:
                    raise OSError("transient tool fixture")
                return "recovered"

            registry = ToolRegistry()
            registry.register(
                ToolDefinition(
                    name="lookup",
                    description="Read one deterministic value.",
                    input_schema={"type": "object", "properties": {}},
                    handler=flaky_lookup,
                )
            )
            return registry

        events: list[RuntimeEvent] = []
        result = await LangGraphRuntime(
            model_factory=lambda _request: FlakyModel(),
            tool_registry_factory=create_tools,
            max_model_retries=1,
            model_retry_initial_delay_ms=0,
            model_retry_max_delay_ms=0,
            max_tool_retries=1,
            tool_retry_initial_delay_ms=0,
            tool_retry_max_delay_ms=0,
        ).run(
            RuntimeRequest(run_id="run-retry", input_text="retry"),
            emit=_collecting_sink(events),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual(3, model_calls)
        self.assertEqual(2, tool_calls)
        self.assertEqual(
            [
                "model.retrying",
                "tool.started",
                "tool.retrying",
                "tool.completed",
            ],
            [event.type for event in events],
        )
        self.assertEqual(
            [0, 0],
            [
                event.data["delay_ms"]
                for event in events
                if event.type.endswith("retrying")
            ],
        )
        tool_retry = next(
            event for event in events if event.type == "tool.retrying"
        )
        self.assertEqual("tool_io_error", tool_retry.data["error_code"])

    async def test_langgraph_event_sink_failure_propagates(self) -> None:
        marker = RuntimeError("event-store-unavailable")
        runtime = create_runtime_harnesses(SUCCESS_CASE)[-1].runtime

        async def broken_sink(event: RuntimeEvent) -> None:
            del event
            raise marker

        with self.assertRaises(RuntimeError) as raised:
            await runtime.run(
                RuntimeRequest(
                    run_id="run-store-failure",
                    input_text=SUCCESS_CASE.input_text,
                ),
                emit=broken_sink,
                control=RuntimeControl(CancellationToken()),
            )

        self.assertIs(marker, raised.exception)

    async def _assert_case(self, case: RuntimeContractCase) -> None:
        for harness in create_runtime_harnesses(case):
            with self.subTest(runtime=harness.name):
                events: list[RuntimeEvent] = []
                result = await harness.runtime.run(
                    RuntimeRequest(
                        run_id=f"run-{case.name}-{harness.name}",
                        input_text=case.input_text,
                    ),
                    emit=_collecting_sink(events),
                    control=RuntimeControl(CancellationToken()),
                )

                self.assertEqual(RunStatus.COMPLETED, result.status)
                self.assertEqual(case.answer, result.answer)
                self.assertEqual(
                    ["tool.started", case.terminal_tool_event],
                    [event.type for event in events if event.type.startswith("tool.")],
                )
                terminal_event = next(
                    event for event in events if event.type == case.terminal_tool_event
                )
                self.assertEqual("add_numbers", terminal_event.data["name"])
                self.assertEqual(case.error_code, terminal_event.data.get("error_code"))
                if case.error_code is None:
                    self.assertEqual([case.arguments], harness.executed_arguments)
                else:
                    self.assertEqual([], harness.executed_arguments)

    async def test_invalid_type_case_is_semantically_equal_across_three_runtimes(
        self,
    ) -> None:
        await self._assert_case(INVALID_TYPE_CASE)

def _collecting_sink(events: list[RuntimeEvent]):
    async def collect(event: RuntimeEvent) -> None:
        events.append(event)

    return collect


if __name__ == "__main__":
    unittest.main()
