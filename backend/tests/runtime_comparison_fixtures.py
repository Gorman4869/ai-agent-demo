from __future__ import annotations

import inspect
import json
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from types import SimpleNamespace

from agents.stream_events import RawResponsesStreamEvent, RunItemStreamEvent
from agents.tool import FunctionToolCustomDataContext
from agents.tool_context import ToolContext
from agents.usage import Usage
from openai.types.responses import ResponseTextDeltaEvent

from backend.app.agent import ManualAgentLoop, ManualRuntime
from backend.app.agent.graph_runtime import LangGraphRuntime
from backend.app.agent.runtime import AgentRuntime, RuntimeRequest
from backend.app.agent.sdk_runtime import (
    OpenAIAgentOutput,
    OpenAIAgentsRuntime,
    build_sdk_tools,
)
from backend.app.domain import ModelDecision, ToolCall
from backend.app.models import MockModel
from backend.app.settings import RunBudgetSettings
from backend.app.tools import ToolDefinition, ToolRegistry


@dataclass(frozen=True)
class RuntimeContractCase:
    name: str
    input_text: str
    arguments: dict[str, object]
    answer: str
    terminal_tool_event: str
    error_code: str | None = None

    def decisions(self) -> tuple[ModelDecision, ...]:
        return (
            ModelDecision(
                tool_call=ToolCall(
                    id=f"{self.name}-call",
                    name="add_numbers",
                    arguments=dict(self.arguments),
                )
            ),
            ModelDecision(final_answer=self.answer),
        )


SUCCESS_CASE = RuntimeContractCase(
    name="success",
    input_text="请计算 2 + 3",
    arguments={"a": 2, "b": 3},
    answer="计算结果是 5",
    terminal_tool_event="tool.completed",
)

INVALID_ARGUMENTS_CASE = RuntimeContractCase(
    name="invalid-arguments",
    input_text="请计算只有一个参数的输入",
    arguments={"a": 2},
    answer="工具参数无效，未执行计算",
    terminal_tool_event="tool.failed",
    error_code="invalid_arguments",
)


@dataclass
class RuntimeHarness:
    name: str
    runtime: AgentRuntime
    executed_arguments: list[dict[str, object]] = field(default_factory=list)


def create_runtime_harnesses(
    case: RuntimeContractCase,
) -> tuple[RuntimeHarness, ...]:
    return (
        _manual_harness(case),
        _agents_sdk_harness(case),
        _langgraph_harness(case),
    )


def _manual_harness(case: RuntimeContractCase) -> RuntimeHarness:
    executed_arguments: list[dict[str, object]] = []
    runtime = ManualRuntime(
        lambda request, token: ManualAgentLoop(
            MockModel(case.decisions()),
            _registry(executed_arguments),
            cancellation_token=token,
        )
    )
    return RuntimeHarness("manual", runtime, executed_arguments)


def _agents_sdk_harness(case: RuntimeContractCase) -> RuntimeHarness:
    executed_arguments: list[dict[str, object]] = []

    def create_agent(request, run_context):
        del request
        return SimpleNamespace(
            name="Contract Agent",
            tools=build_sdk_tools(
                _registry(executed_arguments),
                run_context=run_context,
            ),
        )

    runtime = OpenAIAgentsRuntime(
        agent_factory=create_agent,
        model_factory=_fake_model_factory,
        runner=_ContractRunner(case),
        provider="offline-fake",
        model="contract-model",
        budget=RunBudgetSettings(
            max_steps=4,
            max_model_calls=4,
            max_input_tokens=100,
            max_output_tokens=100,
            max_model_retries=0,
        ),
    )
    return RuntimeHarness("agents_sdk", runtime, executed_arguments)


def _langgraph_harness(case: RuntimeContractCase) -> RuntimeHarness:
    executed_arguments: list[dict[str, object]] = []
    runtime = LangGraphRuntime(
        model_factory=lambda _request: MockModel(case.decisions()),
        tool_registry_factory=lambda _request: _registry(executed_arguments),
        max_steps=4,
        max_model_retries=0,
    )
    return RuntimeHarness("langgraph", runtime, executed_arguments)


def _registry(
    executed_arguments: list[dict[str, object]],
) -> ToolRegistry:
    def add_numbers(arguments):
        executed_arguments.append(dict(arguments))
        return arguments["a"] + arguments["b"]

    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="add_numbers",
            description="Add two numbers and return the sum.",
            input_schema={
                "type": "object",
                "properties": {
                    "a": {"type": "number"},
                    "b": {"type": "number"},
                },
                "required": ["a", "b"],
            },
            handler=add_numbers,
        )
    )
    return registry


@dataclass
class _ToolCallItem:
    tool_name: str
    call_id: str
    raw_item: object = field(repr=False)


@dataclass
class _ToolOutputItem:
    call_id: str
    output: object = field(repr=False)
    custom_data: dict[str, object] = field(repr=False)


class _ContractStreamingRun:
    def __init__(
        self,
        *,
        case: RuntimeContractCase,
        starting_agent: object,
        context: object,
    ) -> None:
        self._case = case
        self._starting_agent = starting_agent
        self._context = context
        self.final_output = OpenAIAgentOutput(answer=case.answer)
        self.context_wrapper = SimpleNamespace(
            usage=Usage(
                requests=2,
                input_tokens=8,
                output_tokens=4,
                total_tokens=12,
            )
        )
        self.is_complete = True
        self.run_loop_exception = None
        self.interruptions: list[object] = []
        self.cancel_modes: list[str] = []

    async def stream_events(self):
        tool = self._starting_agent.tools[0]
        call_id = f"{self._case.name}-call"
        arguments_json = json.dumps(self._case.arguments)
        yield RunItemStreamEvent(
            name="tool_called",
            item=_ToolCallItem(
                tool_name=tool.name,
                call_id=call_id,
                raw_item={"arguments": "not-persisted"},
            ),
        )
        tool_context = ToolContext(
            context=self._context,
            tool_name=tool.name,
            tool_call_id=call_id,
            tool_arguments=arguments_json,
        )
        output = await tool.on_invoke_tool(tool_context, arguments_json)
        extractor = tool.custom_data_extractor
        if extractor is None:
            raise AssertionError("contract tool has no custom data extractor")
        custom_data = extractor(
            FunctionToolCustomDataContext(
                tool_context=tool_context,
                tool=tool,
                output=output,
                raw_item={"output": "not-persisted"},
            )
        )
        if inspect.isawaitable(custom_data):
            custom_data = await custom_data
        yield RunItemStreamEvent(
            name="tool_output",
            item=_ToolOutputItem(
                call_id=call_id,
                output=output,
                custom_data=dict(custom_data),
            ),
        )
        yield _text_delta(json.dumps({"answer": self._case.answer}, ensure_ascii=False))

    def cancel(self, mode: str = "immediate") -> None:
        self.cancel_modes.append(mode)


class _ContractRunner:
    def __init__(self, case: RuntimeContractCase) -> None:
        self._case = case

    def run_streamed(
        self,
        starting_agent: object,
        input: str,
        *,
        context: object,
        max_turns: int,
        run_config: object,
    ) -> _ContractStreamingRun:
        del max_turns, run_config
        if input != self._case.input_text:
            raise AssertionError("Runtime received a different contract input")
        return _ContractStreamingRun(
            case=self._case,
            starting_agent=starting_agent,
            context=context,
        )


def _fake_model_factory():
    @asynccontextmanager
    async def model_context():
        yield object()

    return model_context()


def _text_delta(text: str) -> RawResponsesStreamEvent:
    return RawResponsesStreamEvent(
        data=ResponseTextDeltaEvent(
            content_index=0,
            delta=text,
            item_id="message-1",
            logprobs=[],
            output_index=0,
            sequence_number=1,
            type="response.output_text.delta",
        )
    )


__all__ = [
    "INVALID_ARGUMENTS_CASE",
    "RuntimeContractCase",
    "RuntimeHarness",
    "SUCCESS_CASE",
    "create_runtime_harnesses",
]
