from __future__ import annotations

import runpy
import socket
import unittest
from pathlib import Path
from unittest.mock import patch


_DEMO_PATH = (
    Path(__file__).resolve().parents[2]
    / "labs"
    / "langchain-agent"
    / "demo.py"
)


class LangChainAgentLabTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.run_demo = staticmethod(runpy.run_path(str(_DEMO_PATH))["run_demo"])

    def test_create_agent_invoke_executes_the_declared_tool(self) -> None:
        result = self.run_demo(2, 3)

        self.assertEqual("计算结果是 5", result["answer"])
        self.assertEqual(1, result["tool_call_count"])
        self.assertEqual("add_numbers", result["tool_name"])
        self.assertEqual(5.0, float(result["tool_output"]))
        self.assertEqual(
            ["HumanMessage", "AIMessage", "ToolMessage", "AIMessage"],
            result["message_types"],
        )
        self.assertIn("create_agent", result["framework_path"])
        self.assertIn("agent.invoke", result["framework_path"])

    def test_demo_is_offline_under_socket_guards(self) -> None:
        with (
            patch.object(
                socket,
                "create_connection",
                side_effect=AssertionError("LangChain demo attempted network access"),
            ),
            patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("LangChain demo attempted network access"),
            ),
        ):
            result = self.run_demo(1.5, 2.5)

        self.assertEqual("计算结果是 4", result["answer"])
        self.assertEqual(1, result["tool_call_count"])

    def test_demo_rejects_non_numeric_operands_before_agent_execution(self) -> None:
        with self.assertRaisesRegex(ValueError, "finite numbers"):
            self.run_demo(True, 2)


if __name__ == "__main__":
    unittest.main()
