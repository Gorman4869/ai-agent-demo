"""`ManualAgentLoop` 的离线单元测试。

本套测试通过确定性的 `MockModel` 与内存中的 `ToolRegistry` 锁住
循环的公开合约：不依赖任何模型提供方、不访问网络、不读写持久层。
每个用例对应 `ManualAgentLoop.run` 的一个可观察契约面：

* 直接回答的短路路径；
* ReAct 工具调用循环及其事件序列；
* 工具执行失败以结构化 `tool` 消息回传给模型，而非让整次运行崩溃；
* `max_steps` 与 `max_model_retries` 上限；
* 模型与工具边界之间的协作式取消。

测试期望对齐 `docs/stages/01-manual-agent-loop.md` 与
`BACKEND_CODING_STANDARDS.md` 中的运行时／错误处理规则
（§6 步数上限、§10 协作式取消、§10 瞬态错误重试、§10 副作用边界）。
"""

from __future__ import annotations

import unittest
from collections.abc import Iterable

from backend.app.agent import CancellationToken, ManualAgentLoop
from backend.app.domain import AgentRunResult, ModelDecision, ToolCall
from backend.app.models import MockModel, RetryableModelError
from backend.app.tools import ToolDefinition, ToolRegistry
from backend.app.tools.builtin import create_default_registry


class ManualAgentLoopTest(unittest.TestCase):
    """`ManualAgentLoop.run` 的合约覆盖。

    断言只针对外部可见产物：`AgentRunResult.status`、
    按声明顺序排列的事件序列、合成的 `messages` 历史，
    以及到达模型的工具结果负载。
    `ScriptedClock` 用于让耗时字段保持可复现，
    而不是断言真实的 wall-clock 时长。
    """

    def test_returns_direct_answer(self) -> None:
        """模型在第一轮决策就给出 `final_answer`。

        锁住最短路径：一次模型决策，无任何 `tool.*` 事件，
        且 assistant 消息是 `messages` 中的最后一条。
        """
        model = MockModel([ModelDecision(final_answer="直接回答")])

        result = ManualAgentLoop(model, create_default_registry()).run("你好")

        self.assertEqual("completed", result.status)
        self.assertEqual("直接回答", result.final_answer)
        self.assertEqual(["run.started", "run.completed"], _event_types(result))

    def test_executes_tool_then_returns_answer(self) -> None:
        """一次工具调用，然后给出 `final_answer`。

        验证 ReAct 循环事件序列
        `[run.started, tool.started, tool.completed, run.completed]`，
        并确认工具的 `value` 落在 `messages` 倒数第二条（即 tool 消息）。
        """
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
        """未知工具名应该软失败，而非硬崩溃。

        循环发出携带 `unknown_tool` 的 `tool.failed` 事件，
        并把结构化失败回传给模型，让下一轮有机会自行应对。
        """
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
        """Schema 级别的参数校验失败同样回传给模型。

        与运行时失败不同：本用例覆盖注册表在执行前的 JSON Schema
        拒绝路径，以及对应的 `invalid_arguments` 错误码。
        """
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
        """`max_steps` 是硬性上限（§6）。

        在 `max_steps=2` 下，两次决策都触发工具失败时，
        运行必须以 `status="failed"` 结束，错误信息与配置一致，
        并以 `run.failed` 事件收尾，防止循环无界扩张。
        """
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
        """仅 `RetryableModelError` 会重试，且上限由 `max_model_retries` 控制（§10）。

        一个不稳定的模型在前两次抛错、第三次成功，
        同时证明三件事：`RetryableModelError` 是唯一可重试异常类；
        `max_model_retries=2` 恰好允许两次重试（即总共三次尝试）；
        每次重试都会发出一个 `model.retrying` 事件。
        `ScriptedClock` 让耗时保持确定性，
        避免断言依赖真实的 wall-clock 漂移。
        """
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

    def test_retries_read_only_tool_and_emits_bounded_backoff_event(self) -> None:
        calls = 0

        def flaky_lookup(_arguments: dict[str, object]) -> str:
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("transient local fixture")
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
        model = MockModel(
            [
                ModelDecision(
                    tool_call=ToolCall(
                        id="call-retry",
                        name="lookup",
                        arguments={},
                    )
                ),
                ModelDecision(final_answer="recovered"),
            ]
        )

        result = ManualAgentLoop(
            model,
            registry,
            max_tool_retries=1,
            tool_retry_initial_delay_ms=0,
            tool_retry_max_delay_ms=0,
        ).run("retry one read-only tool")

        self.assertEqual("completed", result.status)
        self.assertEqual(2, calls)
        retry = next(
            event for event in result.events if event.type == "tool.retrying"
        )
        self.assertEqual(1, retry.data["attempt"])
        self.assertEqual(0, retry.data["delay_ms"])
        self.assertEqual("tool_io_error", retry.data["error_code"])
        self.assertEqual(
            ["tool.started", "tool.retrying", "tool.completed"],
            [event.type for event in result.events if event.type.startswith("tool.")],
        )

    def test_cancellation_after_model_decision_prevents_tool_execution(self) -> None:
        """取消是协作式的，且在工具边界之前进行检查（§10）。

        模型在 `decide()` 运行期间触发 `token.cancel()`。
        循环必须在分发工具前结束本次运行，绝不能调用副作用处理器，
        并以 `error_code="run_cancelled"` 的 `run.failed` 事件收尾，
        不出现任何 `tool.started` 事件。
        副作用工具永远不能被盲目重试，因此 `calls` 为空列表
        也属于本合约的一部分。
        """
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

    def test_transform_temperature_success(self) -> None:
        """课程示例工具 `convert_temperature` 的正常路径。

        锁住端到端的事件形态以及结果负载（`"value": 212.0`），
        作为课程材料中的标准范例。
        """
        model = MockModel(
            [
                ModelDecision(
                    tool_call=ToolCall(
                        id="call-1",
                        name="convert_temperature",
                        arguments={"value": 100, "from_unit": "C", "to_unit": "F"},
                    )
                ),
                ModelDecision(final_answer="100°C = 212°F"),
            ]
        )
        result = ManualAgentLoop(model, create_default_registry()).run("转换温度")
        self.assertEqual("completed", result.status)
        self.assertIn('"value": 212.0', result.messages[-2].content)
        self.assertEqual(
            ["run.started", "tool.started", "tool.completed", "run.completed"],
            _event_types(result),
        )

    def test_transform_temperature_invalid_arguments(self) -> None:
        """缺少 `to_unit` 是 schema 失败，不是运行时失败。

        tool 消息中携带 `invalid_arguments`，事件以 `tool.failed` 收尾，
        但本次运行仍然正常结束，模型可以在下一轮作出应对。
        """
        model = MockModel(
            [
                ModelDecision(
                    tool_call=ToolCall(
                        id="call-2",
                        name="convert_temperature",
                        arguments={"value": 1, "from_unit": "C"},
                    )
                ),
                ModelDecision(final_answer="缺少 to_unit 参数"),
            ]
        )
        result = ManualAgentLoop(model, create_default_registry()).run("转换温度")
        self.assertEqual("completed", result.status)
        self.assertIn("invalid_arguments", result.messages[-2].content)
        self.assertEqual(
            ["run.started", "tool.started", "tool.failed", "run.completed"],
            _event_types(result),
        )

    def test_transform_temperature_unsupported_unit(self) -> None:
        """`X` 是合法的 JSON 值，但不是支持的单位。

        schema 校验通过，工具本身返回 `tool_execution_failed`，
        事件以 `tool.failed` 收尾。
        与上一条用例一起，证明注册表能区分参数 schema 失败与
        运行时失败这两类不同的错误来源。
        """
        model = MockModel(
            [
                ModelDecision(
                    tool_call=ToolCall(
                        id="call-3",
                        name="convert_temperature",
                        arguments={"value": 1, "from_unit": "C", "to_unit": "X"},
                    )
                ),
                ModelDecision(final_answer="无法转换到未知单位"),
            ]
        )
        result = ManualAgentLoop(model, create_default_registry()).run("转换温度")
        self.assertEqual("completed", result.status)
        self.assertIn("tool_execution_failed", result.messages[-2].content)
        self.assertEqual(
            ["run.started", "tool.started", "tool.failed", "run.completed"],
            _event_types(result),
        )

class ScriptedClock:
    """用于耗时断言的确定性时钟 fixture。

    每次调用按顺序返回预先排队的下一个值。
    让 `model_duration_ms` 与 `tool_duration_ms` 可复现，
    从而避免事件断言依赖真实的 wall-clock 时长。
    """

    def __init__(self, values: Iterable[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def _event_types(result: AgentRunResult) -> list[str]:
    """按声明顺序提取每个事件的 `type` 字段。

    让事件序列断言更紧凑、可读。
    """
    return [event.type for event in result.events]


if __name__ == "__main__":
    unittest.main()
