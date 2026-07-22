from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from agents import Runner
from agents.exceptions import MaxTurnsExceeded

from backend.app.agent.multi_agent import (
    MANAGER_INSTRUCTIONS,
    RESEARCHER_INSTRUCTIONS,
    REVIEWER_INSTRUCTIONS,
    SINGLE_AGENT_INSTRUCTIONS,
    WRITER_INSTRUCTIONS,
    create_manager_as_tools_topology,
    create_safe_multi_agent_run_config,
    create_single_agent_topology,
)
from backend.app.agent.sdk_tools import build_sdk_tools
from backend.app.evals.multi_agent import (
    DEFAULT_COLLABORATION_CASES,
    _DeterministicCollaborationModel,
    _FixtureRunState,
    _install_offline_trace_provider,
    _registries,
    _run_context,
    run_offline_multi_agent_comparison,
)
from backend.app.tools import ToolDefinition, ToolRegistry, ToolRisk


def _topologies():
    case = DEFAULT_COLLABORATION_CASES[0]
    state = _FixtureRunState(case)
    model = _DeterministicCollaborationModel(state, delay_ms=0)
    context = _run_context(case, "manager_as_tools")
    research_registry, review_registry, combined_registry = _registries(state)
    manager = create_manager_as_tools_topology(
        model=model,
        researcher_tools=build_sdk_tools(
            research_registry,
            run_context=context,
        ),
        reviewer_tools=build_sdk_tools(
            review_registry,
            run_context=context,
        ),
    )
    single = create_single_agent_topology(
        model=model,
        tools=build_sdk_tools(combined_registry, run_context=context),
    )
    return case, state, context, manager, single


class MultiAgentTopologyTest(unittest.TestCase):
    def test_roles_have_distinct_instructions_and_tool_sets(self) -> None:
        _, _, _, manager, single = _topologies()

        self.assertEqual(MANAGER_INSTRUCTIONS, manager.manager.instructions)
        self.assertEqual(
            RESEARCHER_INSTRUCTIONS,
            manager.researcher.instructions,
        )
        self.assertEqual(WRITER_INSTRUCTIONS, manager.writer.instructions)
        self.assertEqual(REVIEWER_INSTRUCTIONS, manager.reviewer.instructions)
        self.assertEqual(SINGLE_AGENT_INSTRUCTIONS, single.agent.instructions)
        self.assertEqual(
            {"research_course_fact", "draft_course_answer", "review_course_answer"},
            {tool.name for tool in manager.manager.tools},
        )
        self.assertEqual(
            {"lookup_course_fact"},
            {tool.name for tool in manager.researcher.tools},
        )
        self.assertEqual([], manager.writer.tools)
        self.assertEqual(
            {"check_required_terms"},
            {tool.name for tool in manager.reviewer.tools},
        )
        self.assertEqual(
            {"lookup_course_fact", "check_required_terms"},
            {tool.name for tool in single.agent.tools},
        )

    def test_manager_has_only_specialist_tools_and_higher_complexity(self) -> None:
        _, _, _, manager, single = _topologies()

        manager_tool_names = {tool.name for tool in manager.manager.tools}
        self.assertNotIn("lookup_course_fact", manager_tool_names)
        self.assertNotIn("check_required_terms", manager_tool_names)
        self.assertEqual(4, manager.complexity.agent_count)
        self.assertEqual(3, manager.complexity.routing_edge_count)
        self.assertEqual(12, manager.complexity.complexity_units)
        self.assertEqual(3, single.complexity.complexity_units)

    def test_role_snapshot_omits_denied_and_side_effecting_tools(self) -> None:
        case = DEFAULT_COLLABORATION_CASES[0]
        context = _run_context(case, "manager_as_tools")
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="admin_read",
                description="Read an administrator-only value.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                handler=lambda _: "hidden",
                allowed_roles=frozenset({"admin"}),
            )
        )
        registry.register(
            ToolDefinition(
                name="publish_report",
                description="Publish a report with side effects.",
                input_schema={
                    "type": "object",
                    "properties": {},
                    "required": [],
                    "additionalProperties": False,
                },
                handler=lambda _: "published",
                risk_level=ToolRisk.HIGH,
                has_side_effects=True,
            )
        )

        self.assertEqual((), build_sdk_tools(registry, run_context=context))

    def test_run_config_disables_tracing_and_sensitive_trace_data(self) -> None:
        run_config = create_safe_multi_agent_run_config()

        self.assertTrue(run_config.tracing_disabled)
        self.assertFalse(run_config.trace_include_sensitive_data)

    def test_duplicate_role_tools_are_rejected(self) -> None:
        _, _, _, manager, _ = _topologies()
        duplicate = manager.researcher.tools[0]

        with self.assertRaisesRegex(ValueError, "duplicate"):
            create_manager_as_tools_topology(
                model=manager.manager.model,
                researcher_tools=(duplicate, duplicate),
                reviewer_tools=manager.reviewer.tools,
            )


class MultiAgentRunnerTest(unittest.IsolatedAsyncioTestCase):
    async def test_public_runner_executes_all_specialists_and_domain_tools(self) -> None:
        report = await run_offline_multi_agent_comparison(
            DEFAULT_COLLABORATION_CASES[:1],
            model_delay_ms=0,
        )
        result = report.manager_as_tools.results[0]

        self.assertTrue(result.passed)
        self.assertEqual(
            {"manager": 4, "researcher": 2, "reviewer": 2, "writer": 1},
            dict(result.role_model_calls),
        )
        self.assertEqual(
            {"check_required_terms": 1, "lookup_course_fact": 1},
            dict(result.tool_calls),
        )
        self.assertEqual(9, result.model_requests)
        self.assertEqual(108, result.total_tokens)

    async def test_manager_turn_budget_fails_closed(self) -> None:
        case, _, context, manager, _ = _topologies()
        _install_offline_trace_provider()

        with self.assertRaises(MaxTurnsExceeded):
            await Runner.run(
                starting_agent=manager.manager,
                input=case.input_text,
                context=context,
                max_turns=1,
                run_config=create_safe_multi_agent_run_config(),
            )

    async def test_offline_runner_does_not_open_a_socket(self) -> None:
        with (
            patch.object(
                socket,
                "create_connection",
                side_effect=AssertionError("network access is forbidden"),
            ),
            patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("network access is forbidden"),
            ),
        ):
            report = await run_offline_multi_agent_comparison(
                DEFAULT_COLLABORATION_CASES[:1],
                model_delay_ms=0,
            )
        self.assertEqual(0.0, report.manager_as_tools.failure_rate)


if __name__ == "__main__":
    unittest.main()
