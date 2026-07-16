from __future__ import annotations

import json
import math
from collections.abc import Callable, Sequence
from typing import Any

from langchain.agents import create_agent
from langchain_core.language_models.fake_chat_models import (
    FakeMessagesListChatModel,
)
from langchain_core.messages import AIMessage, ToolMessage
from langchain_core.tools import BaseTool, tool


class _ToolCallingFakeModel(FakeMessagesListChatModel):
    """Deterministic provider boundary that still supports tool binding."""

    def bind_tools(
        self,
        tools: Sequence[
            dict[str, Any] | type | Callable[..., Any] | BaseTool
        ],
        *,
        tool_choice: str | None = None,
        **kwargs: Any,
    ):
        del tools, tool_choice, kwargs
        return self


def run_demo(a: float = 2, b: float = 3) -> dict[str, object]:
    """Run one real LangChain create_agent tool loop with an offline model."""
    for value in (a, b):
        if (
            not isinstance(value, (int, float))
            or isinstance(value, bool)
            or not math.isfinite(value)
        ):
            raise ValueError("demo operands must be finite numbers")

    tool_call_count = 0

    @tool
    def add_numbers(first: float, second: float) -> float:
        """Add two finite numbers and return the sum."""
        nonlocal tool_call_count
        tool_call_count += 1
        return first + second

    total = a + b
    model = _ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "add_numbers",
                        "args": {"first": a, "second": b},
                        "id": "langchain-add-call",
                        "type": "tool_call",
                    }
                ],
            ),
            AIMessage(content=f"计算结果是 {total:g}"),
        ]
    )
    agent = create_agent(
        model=model,
        tools=[add_numbers],
        system_prompt="Use the declared calculation tool exactly once.",
        name="offline_langchain_comparison",
    )
    state = agent.invoke(
        {"messages": [{"role": "user", "content": f"计算 {a:g} + {b:g}"}]}
    )
    messages = state["messages"]
    tool_messages = [
        message for message in messages if isinstance(message, ToolMessage)
    ]
    if len(tool_messages) != 1 or not isinstance(messages[-1], AIMessage):
        raise RuntimeError("LangChain agent returned an invalid message sequence")

    return {
        "answer": messages[-1].content,
        "framework_path": "langchain.agents.create_agent -> agent.invoke",
        "message_types": [type(message).__name__ for message in messages],
        "tool_call_count": tool_call_count,
        "tool_name": tool_messages[0].name,
        "tool_output": tool_messages[0].content,
    }


if __name__ == "__main__":
    print(json.dumps(run_demo(), ensure_ascii=False, indent=2))
