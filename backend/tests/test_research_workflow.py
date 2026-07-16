from __future__ import annotations

import unittest

from backend.app.agent.research_workflow import create_research_workflow
from backend.app.knowledge import Document, InMemoryKnowledgeBase


class ResearchWorkflowTest(unittest.TestCase):
    def setUp(self) -> None:
        self.knowledge = InMemoryKnowledgeBase()
        self.knowledge.add(
            Document(
                id="agent",
                title="Agent 基础",
                source="course/agent.md",
                content="Agent 由模型、工具与循环控制组成，程序负责校验并执行工具。",
            )
        )

    def test_research_writer_reviewer_workflow_approves_grounded_answer(self) -> None:
        result = create_research_workflow(self.knowledge).invoke(
            {
                "question": "Agent 的工具由谁执行？",
                "evidence": [],
                "draft": "",
                "critique": "",
                "approved": False,
                "answer": "",
            }
        )
        self.assertTrue(result["approved"])
        self.assertEqual("证据和引用完整", result["critique"])
        self.assertIn("程序负责", result["answer"])

    def test_workflow_refuses_when_no_evidence_is_found(self) -> None:
        result = create_research_workflow(self.knowledge).invoke(
            {
                "question": "天气预报",
                "evidence": [],
                "draft": "",
                "critique": "",
                "approved": False,
                "answer": "",
            }
        )
        self.assertFalse(result["approved"])
        self.assertEqual("缺少可核验依据", result["answer"])
