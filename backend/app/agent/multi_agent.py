from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agents import Agent, FunctionTool, RunConfig
from agents.models.interface import Model

from backend.app.agent.sdk_tools import OpenAIAgentsRunContext


MANAGER_MAX_TURNS = 6
SPECIALIST_MAX_TURNS = 3

MANAGER_INSTRUCTIONS = """ROLE=manager
Coordinate the declared specialist tools in this order: researcher, writer,
then reviewer. Keep control of the final answer. Never call business tools
directly and never invent a specialist result.
"""
RESEARCHER_INSTRUCTIONS = """ROLE=researcher
Use only the declared research tools. Return a concise factual note and do not
draft the final answer.
"""
WRITER_INSTRUCTIONS = """ROLE=writer
Turn the supplied research note into a concise answer. Do not perform research
or review your own answer.
"""
REVIEWER_INSTRUCTIONS = """ROLE=reviewer
Use only the declared review tools. Report whether the draft covers the
required facts; do not replace the draft with a new answer.
"""
SINGLE_AGENT_INSTRUCTIONS = """ROLE=single
Use the declared research and review tools, then return one concise answer.
Never claim a tool ran unless its result is present.
"""


@dataclass(frozen=True)
class OrchestrationComplexity:
    agent_count: int
    business_tool_count: int
    orchestration_tool_count: int
    routing_edge_count: int

    @property
    def complexity_units(self) -> int:
        return (
            self.agent_count
            + self.business_tool_count
            + self.orchestration_tool_count
            + self.routing_edge_count
        )


@dataclass(frozen=True)
class ManagerAsToolsTopology:
    manager: Agent[OpenAIAgentsRunContext]
    researcher: Agent[OpenAIAgentsRunContext]
    writer: Agent[OpenAIAgentsRunContext]
    reviewer: Agent[OpenAIAgentsRunContext]
    complexity: OrchestrationComplexity

    @property
    def specialists(self) -> tuple[Agent[OpenAIAgentsRunContext], ...]:
        return (self.researcher, self.writer, self.reviewer)


@dataclass(frozen=True)
class SingleAgentTopology:
    agent: Agent[OpenAIAgentsRunContext]
    complexity: OrchestrationComplexity


def create_safe_multi_agent_run_config() -> RunConfig:
    """Create the explicit no-trace configuration shared by all SDK runs."""

    return RunConfig(
        tracing_disabled=True,
        trace_include_sensitive_data=False,
    )


def create_manager_as_tools_topology(
    *,
    model: Model,
    researcher_tools: Sequence[FunctionTool],
    writer_tools: Sequence[FunctionTool] = (),
    reviewer_tools: Sequence[FunctionTool],
) -> ManagerAsToolsTopology:
    """Build an isolated manager-as-tools topology without executing a run."""

    checked_researcher_tools = _checked_tools(
        researcher_tools,
        label="researcher_tools",
    )
    checked_writer_tools = _checked_tools(writer_tools, label="writer_tools")
    checked_reviewer_tools = _checked_tools(
        reviewer_tools,
        label="reviewer_tools",
    )
    run_config = create_safe_multi_agent_run_config()

    researcher = Agent[OpenAIAgentsRunContext](
        name="Course Researcher",
        instructions=RESEARCHER_INSTRUCTIONS,
        model=model,
        tools=list(checked_researcher_tools),
    )
    writer = Agent[OpenAIAgentsRunContext](
        name="Course Writer",
        instructions=WRITER_INSTRUCTIONS,
        model=model,
        tools=list(checked_writer_tools),
    )
    reviewer = Agent[OpenAIAgentsRunContext](
        name="Course Reviewer",
        instructions=REVIEWER_INSTRUCTIONS,
        model=model,
        tools=list(checked_reviewer_tools),
    )
    specialist_tools = (
        researcher.as_tool(
            tool_name="research_course_fact",
            tool_description="Research one course fact for the manager.",
            run_config=run_config,
            max_turns=SPECIALIST_MAX_TURNS,
            failure_error_function=None,
        ),
        writer.as_tool(
            tool_name="draft_course_answer",
            tool_description="Draft an answer from the supplied research note.",
            run_config=run_config,
            max_turns=SPECIALIST_MAX_TURNS,
            failure_error_function=None,
        ),
        reviewer.as_tool(
            tool_name="review_course_answer",
            tool_description="Review a draft against the required facts.",
            run_config=run_config,
            max_turns=SPECIALIST_MAX_TURNS,
            failure_error_function=None,
        ),
    )
    manager = Agent[OpenAIAgentsRunContext](
        name="Course Manager",
        instructions=MANAGER_INSTRUCTIONS,
        model=model,
        tools=list(specialist_tools),
    )
    business_tool_count = (
        len(checked_researcher_tools)
        + len(checked_writer_tools)
        + len(checked_reviewer_tools)
    )
    return ManagerAsToolsTopology(
        manager=manager,
        researcher=researcher,
        writer=writer,
        reviewer=reviewer,
        complexity=OrchestrationComplexity(
            agent_count=4,
            business_tool_count=business_tool_count,
            orchestration_tool_count=len(specialist_tools),
            routing_edge_count=len(specialist_tools),
        ),
    )


def create_single_agent_topology(
    *,
    model: Model,
    tools: Sequence[FunctionTool],
) -> SingleAgentTopology:
    """Build the same-task single Agent control group."""

    checked_tools = _checked_tools(tools, label="tools")
    return SingleAgentTopology(
        agent=Agent[OpenAIAgentsRunContext](
            name="Single Course Agent",
            instructions=SINGLE_AGENT_INSTRUCTIONS,
            model=model,
            tools=list(checked_tools),
        ),
        complexity=OrchestrationComplexity(
            agent_count=1,
            business_tool_count=len(checked_tools),
            orchestration_tool_count=0,
            routing_edge_count=0,
        ),
    )


def _checked_tools(
    tools: Sequence[FunctionTool],
    *,
    label: str,
) -> tuple[FunctionTool, ...]:
    checked = tuple(tools)
    if any(not isinstance(tool, FunctionTool) for tool in checked):
        raise ValueError(f"{label} must contain FunctionTool values")
    names = tuple(tool.name for tool in checked)
    if len(names) != len(set(names)):
        raise ValueError(f"{label} contains duplicate tool names")
    return checked


__all__ = [
    "MANAGER_INSTRUCTIONS",
    "MANAGER_MAX_TURNS",
    "ManagerAsToolsTopology",
    "OrchestrationComplexity",
    "RESEARCHER_INSTRUCTIONS",
    "REVIEWER_INSTRUCTIONS",
    "SINGLE_AGENT_INSTRUCTIONS",
    "SPECIALIST_MAX_TURNS",
    "SingleAgentTopology",
    "WRITER_INSTRUCTIONS",
    "create_manager_as_tools_topology",
    "create_safe_multi_agent_run_config",
    "create_single_agent_topology",
]
