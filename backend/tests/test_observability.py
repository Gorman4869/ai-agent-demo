from __future__ import annotations

import json
import logging
import unittest
from collections.abc import Iterable

from backend.app.agent import ManualAgentLoop
from backend.app.domain import (
    AgentEvent,
    AgentRunResult,
    ModelDecision,
    ModelUsage,
    ToolCall,
)
from backend.app.models import MockModel
from backend.app.observability import JsonLogSink, RunObservation, RunObserver
from backend.app.tools.builtin import create_default_registry


class ScriptedClock:
    def __init__(self, values: Iterable[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


class RunObserverTest(unittest.TestCase):
    def test_summarizes_run_id_events_and_duration(self) -> None:
        model = MockModel(
            [
                ModelDecision(
                    tool_call=ToolCall(
                        id="call-1",
                        name="add_numbers",
                        arguments={"a": 2, "b": 3},
                    )
                ),
                ModelDecision(final_answer="result: 5"),
            ]
        )
        observer = RunObserver(clock=ScriptedClock([10.0, 10.025]))
        loop_clock = ScriptedClock([1.0, 1.004, 2.0, 2.006, 3.0, 3.002])

        observed = observer.observe(
            lambda: ManualAgentLoop(
                model,
                create_default_registry(),
                clock=loop_clock,
            ).run("2 + 3"),
            run_id="run-fixed",
        )

        summary = observed.observation
        self.assertEqual("run-fixed", summary.run_id)
        self.assertEqual(25.0, summary.duration_ms)
        self.assertEqual(4, summary.event_count)
        self.assertEqual(1, summary.event_counts["tool.completed"])
        self.assertEqual(6.0, summary.model_duration_ms)
        self.assertEqual(6.0, summary.tool_duration_ms)
        self.assertEqual({"add_numbers": 6.0}, summary.tool_durations_ms)
        self.assertIsNone(summary.usage)
        self.assertEqual(0, summary.error_count)
        self.assertNotIn("2 + 3", repr(summary.to_record()))

    def test_collects_tool_and_terminal_errors(self) -> None:
        result = ManualAgentLoop(
            MockModel(
                [
                    ModelDecision(
                        tool_call=ToolCall(
                            id="call-1", name="missing", arguments={}
                        )
                    )
                ]
            ),
            create_default_registry(),
            max_steps=1,
        ).run("fail")
        observer = RunObserver(clock=ScriptedClock([2.0, 2.01]))

        summary = observer.observe(lambda: result, run_id="run-failed").observation

        self.assertEqual("failed", summary.status)
        self.assertEqual(2, summary.error_count)
        self.assertEqual("unknown_tool", summary.errors[0].category)
        self.assertEqual("run.failed", summary.errors[1].category)
        self.assertEqual(1, summary.event_counts["tool.failed"])

    def test_publishes_exception_observation_and_reraises(self) -> None:
        published: list[RunObservation] = []
        observer = RunObserver(
            clock=ScriptedClock([4.0, 4.005]),
            sink=published.append,
        )

        def fail():
            raise ValueError("broken runner")

        with self.assertRaisesRegex(ValueError, "broken runner"):
            observer.observe(fail, run_id="run-exception")

        self.assertEqual(1, len(published))
        self.assertEqual(5.0, published[0].duration_ms)
        self.assertEqual("exception.ValueError", published[0].errors[0].category)

    def test_json_log_sink_excludes_messages_and_prompts(self) -> None:
        captured: list[str] = []

        class CapturingLogger(logging.Logger):
            def info(self, msg, *args, **kwargs):
                captured.append(str(msg))

        observation = RunObserver(
            clock=ScriptedClock([1.0, 1.001]),
            sink=JsonLogSink(CapturingLogger("test")),
        ).observe(
            lambda: ManualAgentLoop(
                MockModel([ModelDecision(final_answer="private answer")]),
                create_default_registry(),
            ).run("private prompt"),
            run_id="safe-log",
        ).observation

        record = json.loads(captured[0])
        self.assertEqual(observation.run_id, record["run_id"])
        self.assertEqual("agent.run.observed", record["event"])
        self.assertNotIn("private", captured[0])

        def fail_with_sensitive_text():
            raise ValueError("private prompt copied into an exception")

        with self.assertRaisesRegex(ValueError, "private prompt"):
            RunObserver(
                clock=ScriptedClock([2.0, 2.001]),
                sink=JsonLogSink(CapturingLogger("test-error")),
            ).observe(fail_with_sensitive_text, run_id="safe-error-log")

        error_record = json.loads(captured[1])
        self.assertEqual(["exception.ValueError"], error_record["error_categories"])
        self.assertNotIn("private", captured[1])

    def test_preserves_provider_usage_without_inventing_missing_cost(self) -> None:
        result = AgentRunResult(
            status="completed",
            final_answer="ok",
            messages=(),
            events=(AgentEvent("run.completed", 1, {}),),
            usage=ModelUsage(
                input_tokens=12,
                output_tokens=3,
                total_tokens=15,
            ),
        )

        observation = RunObserver(
            clock=ScriptedClock([1.0, 1.001])
        ).observe(lambda: result, run_id="usage-run").observation

        self.assertEqual(15, observation.usage.total_tokens)
        self.assertIsNone(observation.usage.estimated_cost_usd)
        self.assertEqual(15, observation.to_record()["usage"]["total_tokens"])

    def test_sink_failure_does_not_change_a_successful_agent_result(self) -> None:
        def broken_sink(_: RunObservation) -> None:
            raise RuntimeError("private sink details")

        with self.assertLogs("ai_agent.observability", level="WARNING") as logs:
            observed = RunObserver(
                clock=ScriptedClock([1.0, 1.001]),
                sink=broken_sink,
            ).observe(
                lambda: AgentRunResult(
                    status="completed",
                    final_answer="ok",
                    messages=(),
                    events=(AgentEvent("run.completed", 1, {}),),
                ),
                run_id="sink-failure",
            )

        self.assertEqual("completed", observed.result.status)
        self.assertEqual("sink-failure", observed.observation.run_id)
        self.assertNotIn("private sink details", logs.output[0])


if __name__ == "__main__":
    unittest.main()
