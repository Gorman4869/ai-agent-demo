from __future__ import annotations

import unittest

from backend.app.agent import CancellationToken
from backend.app.agent.graph_runtime import LangGraphRuntime
from backend.app.agent.runtime import RuntimeControl, RuntimeEvent, RuntimeRequest
from backend.app.domain.run import RunStatus
from backend.app.models import MockModel
from backend.app.tools.builtin import create_default_registry
from backend.tests.runtime_comparison_fixtures import (
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


def _collecting_sink(events: list[RuntimeEvent]):
    async def collect(event: RuntimeEvent) -> None:
        events.append(event)

    return collect


if __name__ == "__main__":
    unittest.main()
