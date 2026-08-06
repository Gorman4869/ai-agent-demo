from __future__ import annotations

import unittest

from backend.app.agent.graph_runtime import create_research_graph
from backend.app.agent.sdk_runtime import create_openai_learning_agent
from backend.app.mcp_server import lookup_concept, list_concepts


class FrameworkRuntimeTest(unittest.TestCase):
    def test_langgraph_runs_deterministic_workflow(self) -> None:
        result = create_research_graph().invoke(
            {"question": "MCP 有什么用？", "plan": [], "approved": False, "answer": ""}
        )
        self.assertTrue(result["approved"])
        self.assertEqual(3, len(result["plan"]))
        self.assertIn("3 步研究计划", result["answer"])

    def test_openai_agent_can_be_constructed_without_api_call(self) -> None:
        agent = create_openai_learning_agent()
        self.assertEqual("Learning Assistant", agent.name)
        self.assertEqual(0, len(agent.tools))

    def test_mcp_tool_function_uses_local_knowledge(self) -> None:
        self.assertIn("统一协议", lookup_concept("MCP"))
        self.assertEqual("未找到该概念", lookup_concept("missing"))
        self.assertEqual(["agent", "mcp", "rag"], list_concepts())
