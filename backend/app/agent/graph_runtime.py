from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import TypedDict

from langgraph.graph import END, START, StateGraph

from backend.app.agent.runtime import (
    RuntimeControl,
    RuntimeEvent,
    RuntimeEventSink,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.domain import Message, ModelDecision
from backend.app.domain.run import RunFailure, RunStatus
from backend.app.models import ChatModel, RetryableModelError
from backend.app.tools import ToolExecutionContext, ToolRegistry


class ResearchState(TypedDict):
    question: str
    plan: list[str]
    approved: bool
    answer: str


def create_research_graph():
    graph = StateGraph(ResearchState)
    graph.add_node("plan", _plan)
    graph.add_node("review", _review)
    graph.add_node("answer", _answer)
    graph.add_edge(START, "plan")
    graph.add_edge("plan", "review")
    graph.add_conditional_edges(
        "review",
        lambda state: "answer" if state["approved"] else END,
        {"answer": "answer", END: END},
    )
    graph.add_edge("answer", END)
    return graph.compile()


def _plan(state: ResearchState) -> dict[str, list[str]]:
    return {"plan": ["明确问题", "收集证据", "组织答案"]}


def _review(state: ResearchState) -> dict[str, bool]:
    return {"approved": bool(state["question"].strip())}


def _answer(state: ResearchState) -> dict[str, str]:
    return {"answer": f"已为“{state['question']}”生成 {len(state['plan'])} 步研究计划"}


class _RuntimeState(TypedDict):
    messages: list[Message]
    decision: ModelDecision | None
    result: RuntimeResult | None
    step: int


GraphModelFactory = Callable[[RuntimeRequest], ChatModel]
GraphToolRegistryFactory = Callable[[RuntimeRequest], ToolRegistry]


class LangGraphRuntime:
    """Offline AgentRuntime comparison implemented through a LangGraph graph."""

    def __init__(
        self,
        *,
        model_factory: GraphModelFactory,
        tool_registry_factory: GraphToolRegistryFactory,
        max_steps: int = 8,
        max_model_retries: int = 2,
    ) -> None:
        if (
            not isinstance(max_steps, int)
            or isinstance(max_steps, bool)
            or max_steps < 1
        ):
            raise ValueError("max_steps must be a positive integer")
        if (
            not isinstance(max_model_retries, int)
            or isinstance(max_model_retries, bool)
            or max_model_retries < 0
        ):
            raise ValueError("max_model_retries must not be negative")
        self._model_factory = model_factory
        self._tool_registry_factory = tool_registry_factory
        self._max_steps = max_steps
        self._max_model_retries = max_model_retries

    async def run(
        self,
        request: RuntimeRequest,
        *,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ) -> RuntimeResult:
        if control.cancellation_token.is_cancelled:
            return _cancelled_result(control, step=0)
        try:
            model = self._model_factory(request)
            tools = self._tool_registry_factory(request)
        except Exception:
            return _failure_result(
                code="langgraph_configuration_error",
                category="runtime",
                public_message="LangGraph runtime configuration failed",
            )
        if control.cancellation_token.is_cancelled:
            return _cancelled_result(control, step=0)

        graph = self._create_graph(
            model=model,
            tools=tools,
            execution_context=request.execution_context or ToolExecutionContext(),
            emit=emit,
            control=control,
        )
        messages: list[Message] = []
        if request.prompt_context is not None:
            messages.append(
                Message(role="system", content=request.prompt_context)
            )
        messages.append(Message(role="user", content=request.input_text))
        final_state = await graph.ainvoke(
            _RuntimeState(
                messages=messages,
                decision=None,
                result=None,
                step=0,
            )
        )
        result = final_state.get("result")
        if not isinstance(result, RuntimeResult):
            return _failure_result(
                code="langgraph_contract_error",
                category="runtime",
                public_message="LangGraph returned an invalid result",
                step=final_state.get("step", 0),
            )
        return result

    def _create_graph(
        self,
        *,
        model: ChatModel,
        tools: ToolRegistry,
        execution_context: ToolExecutionContext,
        emit: RuntimeEventSink,
        control: RuntimeControl,
    ):
        async def decide(state: _RuntimeState) -> dict[str, object]:
            if control.cancellation_token.is_cancelled:
                return {"result": _cancelled_result(control, step=state["step"])}
            if state["step"] >= self._max_steps:
                return {
                    "result": _failure_result(
                        code="max_steps_exceeded",
                        category="budget",
                        public_message="Agent exceeded the maximum step budget",
                        step=state["step"],
                    )
                }

            step = state["step"] + 1
            definitions = tools.definitions(context=execution_context)
            for retry_attempt in range(self._max_model_retries + 1):
                try:
                    decision = await asyncio.to_thread(
                        model.decide,
                        tuple(state["messages"]),
                        definitions,
                    )
                    break
                except RetryableModelError:
                    if retry_attempt >= self._max_model_retries:
                        return {
                            "step": step,
                            "result": _failure_result(
                                code="model_retry_exhausted",
                                category="model",
                                public_message="Model retry limit exhausted",
                                step=step,
                            ),
                        }
                    await emit(
                        RuntimeEvent(
                            type="model.retrying",
                            step=step,
                            data={"attempt": retry_attempt + 1},
                        )
                    )
                    if control.cancellation_token.is_cancelled:
                        return {
                            "step": step,
                            "result": _cancelled_result(control, step=step),
                        }
                except Exception:
                    return {
                        "step": step,
                        "result": _failure_result(
                            code="model_execution_failed",
                            category="model",
                            public_message="Model execution failed",
                            step=step,
                        ),
                    }

            if decision.final_answer is not None:
                answer = decision.final_answer
                return {
                    "decision": decision,
                    "messages": [
                        *state["messages"],
                        Message(role="assistant", content=answer),
                    ],
                    "result": RuntimeResult(
                        status=RunStatus.COMPLETED,
                        answer=answer,
                        step=step,
                    ),
                    "step": step,
                }
            return {"decision": decision, "step": step}

        async def execute_tool(state: _RuntimeState) -> dict[str, object]:
            decision = state["decision"]
            if decision is None or decision.tool_call is None:
                return {
                    "result": _failure_result(
                        code="langgraph_contract_error",
                        category="runtime",
                        public_message="LangGraph returned an invalid result",
                        step=state["step"],
                    )
                }
            if control.cancellation_token.is_cancelled:
                return {"result": _cancelled_result(control, step=state["step"])}

            tool_call = decision.tool_call
            await emit(
                RuntimeEvent(
                    type="tool.started",
                    step=state["step"],
                    data={"id": tool_call.id, "name": tool_call.name},
                )
            )
            tool_result = await asyncio.to_thread(
                tools.execute,
                tool_call.name,
                tool_call.arguments,
                context=execution_context,
                call_id=tool_call.id,
            )
            event_data: dict[str, object] = {
                "id": tool_call.id,
                "name": tool_call.name,
                "ok": tool_result.ok,
            }
            event_type = "tool.completed"
            if not tool_result.ok:
                event_type = "tool.failed"
                event_data["error_code"] = tool_result.error_code or "tool_failed"
            await emit(
                RuntimeEvent(
                    type=event_type,
                    step=state["step"],
                    data=event_data,
                )
            )
            result_payload = {
                "ok": tool_result.ok,
                "value": tool_result.value,
                "error_code": tool_result.error_code,
                "error_message": tool_result.error_message,
            }
            return {
                "decision": None,
                "messages": [
                    *state["messages"],
                    Message(
                        role="assistant",
                        content=json.dumps(
                            {
                                "name": tool_call.name,
                                "arguments": tool_call.arguments,
                            },
                            ensure_ascii=False,
                        ),
                        tool_call_id=tool_call.id,
                    ),
                    Message(
                        role="tool",
                        name=tool_call.name,
                        tool_call_id=tool_call.id,
                        content=json.dumps(result_payload, ensure_ascii=False),
                    ),
                ],
            }

        def route_after_model(state: _RuntimeState) -> str:
            return END if state["result"] is not None else "tool"

        graph = StateGraph(_RuntimeState)
        graph.add_node("model", decide)
        graph.add_node("tool", execute_tool)
        graph.add_edge(START, "model")
        graph.add_conditional_edges(
            "model",
            route_after_model,
            {"tool": "tool", END: END},
        )
        graph.add_edge("tool", "model")
        return graph.compile()


def _failure_result(
    *,
    code: str,
    category: str,
    public_message: str,
    step: int = 0,
) -> RuntimeResult:
    return RuntimeResult(
        status=RunStatus.FAILED,
        failure=RunFailure(
            code=code,
            category=category,
            public_message=public_message,
            step=step,
        ),
        step=step,
    )


def _cancelled_result(control: RuntimeControl, *, step: int) -> RuntimeResult:
    reason = control.cancellation_token.reason
    if reason == "deadline_exceeded":
        return _failure_result(
            code="run_timeout",
            category="timeout",
            public_message="Run timed out",
            step=step,
        )
    return RuntimeResult(
        status=RunStatus.CANCELLED,
        failure=RunFailure(
            code=(
                reason
                if reason in {"cancelled_by_user", "client_disconnected"}
                else "run_cancelled"
            ),
            category="cancellation",
            public_message="Run cancelled",
            step=step,
        ),
        step=step,
    )


__all__ = [
    "GraphModelFactory",
    "GraphToolRegistryFactory",
    "LangGraphRuntime",
    "ResearchState",
    "create_research_graph",
]
