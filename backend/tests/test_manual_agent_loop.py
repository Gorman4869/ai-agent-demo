from __future__ import annotations

import unittest
from collections.abc import Iterable

from backend.app.agent import CancellationToken, ManualAgentLoop
from backend.app.domain import AgentRunResult, ModelDecision, ToolCall
from backend.app.models import MockModel, RetryableModelError
from backend.app.tools import ToolDefinition, ToolRegistry
from backend.app.tools.builtin import create_default_registry


class ManualAgentLoopTest(unittest.TestCase):
    def test_returns_direct_answer(self) -> None:
        model = MockModel([ModelDecision(final_answer="直接回答")])

        result = ManualAgentLoop(model, create_default_registry()).run("你好")

        self.assertEqual("completed", result.status)
        self.assertEqual("直接回答", result.final_answer)
        self.assertEqual(["run.started", "run.completed"], _event_types(result))

    def test_executes_tool_then_returns_answer(self) -> None:
        model = MockModel(
            [
                ModelDecision(
                    tool_call=ToolCall(
                        id="call-1",
                        name="add_numbers",
                        arguments={"a": 2, "b": 3},
                    )
                ),
                ModelDecision(final_answer="结果是 5"),
            ]
        )

        result = ManualAgentLoop(model, create_default_registry()).run("2 + 3")

        self.assertEqual("completed", result.status)
        self.assertEqual(
            ["run.started", "tool.started", "tool.completed", "run.completed"],
            _event_types(result),
        )
        self.assertIn('"value": 5', result.messages[-2].content)

    def test_unknown_tool_is_returned_to_model(self) -> None:
        model = MockModel(
            [
                ModelDecision(
                    tool_call=ToolCall(id="call-1", name="missing", arguments={})
                ),
                ModelDecision(final_answer="工具不存在，无法执行"),
            ]
        )

        result = ManualAgentLoop(model, create_default_registry()).run("执行未知工具")

        self.assertEqual("completed", result.status)
        self.assertIn("tool.failed", _event_types(result))
        self.assertIn("unknown_tool", result.messages[-2].content)

    def test_invalid_arguments_are_returned_to_model(self) -> None:
        model = MockModel(
            [
                ModelDecision(
                    tool_call=ToolCall(
                        id="call-1",
                        name="add_numbers",
                        arguments={"a": "2", "b": 3},
                    )
                ),
                ModelDecision(final_answer="参数类型错误"),
            ]
        )

        result = ManualAgentLoop(model, create_default_registry()).run("错误参数")

        self.assertIn("invalid_arguments", result.messages[-2].content)

    def test_stops_at_maximum_steps(self) -> None:
        decisions = [
            ModelDecision(
                tool_call=ToolCall(id=f"call-{index}", name="missing", arguments={})
            )
            for index in range(2)
        ]

        result = ManualAgentLoop(
            MockModel(decisions),
            create_default_registry(),
            max_steps=2,
        ).run("不断调用")

        self.assertEqual("failed", result.status)
        self.assertEqual("Agent exceeded maximum steps: 2", result.error)
        self.assertEqual("run.failed", result.events[-1].type)

    def test_retries_only_explicit_transient_model_errors_with_a_limit(self) -> None:
        class FlakyModel:
            def __init__(self) -> None:
                self.attempts = 0

            def decide(self, messages, tools):
                del messages, tools
                self.attempts += 1
                if self.attempts < 3:
                    raise RetryableModelError("temporary provider failure")
                return ModelDecision(final_answer="recovered")

        model = FlakyModel()
        result = ManualAgentLoop(
            model,
            create_default_registry(),
            max_model_retries=2,
            clock=ScriptedClock([0.0, 0.001, 1.0, 1.002, 2.0, 2.003]),
        ).run("retry")

        self.assertEqual("completed", result.status)
        self.assertEqual(3, model.attempts)
        self.assertEqual(2, _event_types(result).count("model.retrying"))

    def test_cancellation_after_model_decision_prevents_tool_execution(self) -> None:
        token = CancellationToken()
        calls: list[dict[str, object]] = []
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="side_effect",
                description="Record one simulated side effect.",
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
                handler=lambda arguments: calls.append(arguments),
            )
        )

        class CancellingModel:
            def decide(self, messages, tools):
                del messages, tools
                token.cancel("client_disconnected")
                return ModelDecision(
                    tool_call=ToolCall(
                        id="call-side-effect",
                        name="side_effect",
                        arguments={"value": "must-not-run"},
                    )
                )

        result = ManualAgentLoop(
            CancellingModel(),
            registry,
            cancellation_token=token,
        ).run("cancel while the model is deciding")

        self.assertEqual("failed", result.status)
        self.assertEqual("run_cancelled", result.events[-1].data["error_code"])
        self.assertEqual([], calls)
        self.assertNotIn("tool.started", _event_types(result))


class ScriptedClock:
    def __init__(self, values: Iterable[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def _event_types(result: AgentRunResult) -> list[str]:
    return [event.type for event in result.events]


if __name__ == "__main__":
    unittest.main()
