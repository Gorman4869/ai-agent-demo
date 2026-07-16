from __future__ import annotations

from agents import Agent, function_tool


@function_tool
def add_numbers(a: float, b: float) -> float:
    """Add two numbers and return the result."""
    return a + b


def create_openai_learning_agent() -> Agent:
    """Construct an SDK Agent without making a network request."""
    return Agent(
        name="Learning Assistant",
        instructions=(
            "Explain Agent concepts concisely. Use add_numbers for arithmetic. "
            "Never claim a tool ran unless a tool result is present."
        ),
        tools=[add_numbers],
    )
