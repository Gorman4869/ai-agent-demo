from __future__ import annotations

import unittest

from backend.app.knowledge import Document, InMemoryKnowledgeBase


class RagTest(unittest.TestCase):
    def test_retrieves_relevant_document_with_citation(self) -> None:
        knowledge = InMemoryKnowledgeBase(chunk_size=80, overlap=10)
        knowledge.add(
            Document(
                id="mcp",
                title="MCP 基础",
                source="docs/mcp.md",
                content="MCP 是模型上下文协议，用于连接 Agent 客户端与工具和资源。",
            )
        )
        knowledge.add(
            Document(
                id="rag",
                title="RAG 基础",
                source="docs/rag.md",
                content="RAG 通过检索相关证据增强模型回答，并返回可核验引用。",
            )
        )

        results = knowledge.search("MCP 如何连接工具？", limit=1)

        self.assertEqual(1, len(results))
        self.assertEqual("mcp", results[0].citation.document_id)
        self.assertEqual("docs/mcp.md", results[0].citation.source)

    def test_returns_empty_when_query_has_no_shared_tokens(self) -> None:
        knowledge = InMemoryKnowledgeBase()
        knowledge.add(Document(id="1", title="Agent", source="a", content="工具调用"))
        self.assertEqual((), knowledge.search("天气预报"))

    def test_rejects_invalid_chunk_configuration(self) -> None:
        with self.assertRaises(ValueError):
            InMemoryKnowledgeBase(chunk_size=20, overlap=20)

    def test_reindex_replaces_existing_document_chunks(self) -> None:
        knowledge = InMemoryKnowledgeBase()
        first = Document(id="same", title="旧标题", source="old", content="旧的工具说明")
        second = Document(id="same", title="新标题", source="new", content="新的记忆说明")
        knowledge.add(first)
        knowledge.add(second)

        self.assertEqual((), knowledge.search("旧的工具"))
        results = knowledge.search("新的记忆", limit=3)
        self.assertEqual(1, len(results))
        self.assertEqual("new", results[0].citation.source)
