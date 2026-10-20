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

    def test_workflow_refuses_when_low_relevance_evidence_is_found(self) -> None:
        result = create_research_workflow(self.knowledge).invoke(
            {
                "question": "Agent 调用工具的具体步骤是什么？",
                "evidence": [],
                "draft": "",
                "critique": "",
                "approved": False,
                "answer": "",
            }
        )
        # 检索结果必须非空，证明这是“低分误召回”，不是完全没召回
        self.assertTrue(result["evidence"])
        # 最高分必须低于暂定阈值 0.3
        max_score = max([e["score"] for e in result["evidence"]])
        self.assertLess(max_score, 0.3)
        self.assertFalse(result["approved"])
        self.assertEqual("缺少可核验依据", result["answer"])

    def test_writer_excludes_low_relevance_evidence_from_answer(self) -> None:
        knowledge = InMemoryKnowledgeBase()
        knowledge.add(
            Document(
                id="mcp",
                title="mcp",
                source="course/agent.md",
                content="MCP 通过协议连接 Agent 与工具资源。",
            )
        )
        knowledge.add(
            Document(
                id="tool-security",
                title="tool-security",
                source="course/agent.md",
                content="Agent 调用工具前必须校验权限。",
            )
        )
        result = create_research_workflow(knowledge).invoke(
            {
                "question": "Agent 如何连接工具？",
                "evidence": [],
                "draft": "",
                "critique": "",
                "approved": False,
                "answer": "",
            }
        )
        print(result)
        # 原始 result["evidence"] 仍有两条，证明误召回信息没有被覆盖或隐藏。
        self.assertEqual(2, len(result["evidence"]))
        # 最高分 >= 0.3，最低分 < 0.3，证明这是“一强一弱”的混合候选。
        max_score = max([e["score"] for e in result["evidence"]])
        self.assertGreaterEqual(max_score, 0.3)
        min_score = min([e["score"] for e in result["evidence"]])
        self.assertLess(min_score, 0.3)
        # approved=True，因为至少有一条充分相关的证据。
        self.assertTrue(result["approved"])
        # 最终 answer 包含 MCP 内容。
        self.assertIn("MCP 通过协议连接 Agent 与工具资源", result["answer"])
        # 最终 answer 不包含低分的“校验权限”内容。
        self.assertNotIn("校验权限", result["answer"])
