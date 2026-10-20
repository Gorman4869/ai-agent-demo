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

    def test_seed_is_idempotent_and_changed_content_replaces(self) -> None:
        knowledge = InMemoryKnowledgeBase()
        first = Document(id="seed", title="Seed", source="one", content="Agent 工具")
        changed = Document(
            id="seed",
            title="Seed",
            source="two",
            content="Agent 记忆",
        )

        self.assertEqual(1, knowledge.seed(first))
        self.assertEqual(1, knowledge.seed(first))
        self.assertEqual(1, knowledge.seed(changed))

        self.assertEqual((), knowledge.search("工具"))
        self.assertEqual("two", knowledge.search("记忆")[0].citation.source)

    def test_delete_removes_all_document_chunks(self) -> None:
        knowledge = InMemoryKnowledgeBase(chunk_size=20, overlap=0)
        knowledge.add(
            Document(
                id="delete",
                title="Delete",
                source="delete.md",
                content="12345678901234567890abcdefghij",
            )
        )

        self.assertTrue(knowledge.delete("delete"))
        self.assertFalse(knowledge.delete("delete"))
        self.assertEqual((), knowledge.search("abcdefghij"))

    def test_similar_documents_expose_lower_score_false_retrieval(self) -> None:
        knowledge = InMemoryKnowledgeBase(chunk_size=80, overlap=10)
        knowledge.add(
            Document(
                id="mcp",
                title="MCP 基础",
                source="docs/mcp.md",
                content="MCP 通过协议连接 Agent 与工具资源",
            )
        )
        knowledge.add(
            Document(
                id="tool-security",
                title="工具安全",
                source="docs/rag.md",
                content="Agent 调用工具前必须校验权限",
            )
        )
        results = knowledge.search("Agent 如何连接工具", limit=3)
        self.assertEqual(2, len(results))
        self.assertEqual(["mcp","tool-security"], [results[0].citation.document_id, results[1].citation.document_id])
        self.assertGreater(results[0].score, results[1].score)
        self.assertGreater(results[1].score,0)

    def test_documents_replace_all_old_chunks(self) -> None:
        knowledge = InMemoryKnowledgeBase(chunk_size=20, overlap=0)
        old = Document(id="same", title="Old Title", source="old", content="A test method for replacing chunk, this is old chunk")
        new = Document(id="same", title="New Title", source="new", content="A test method for replacing chunk, this is new chunk")
        knowledge.add(old)
        knowledge.add(new)
        results = knowledge.search("new", limit=3)
        self.assertEqual(0, len(knowledge.search("old")))
        self.assertEqual(1, len(results))
        self.assertEqual("new", results[0].citation.source)

    def test_seed_is_idempotent_and_changed_source_replaces(self) -> None:
        knowledge = InMemoryKnowledgeBase()
        first = Document(id="seed", title="Seed", source="old", content="Agent 工具")
        changed = Document(
            id="seed",
            title="Seed",
            source="new",
            content="Agent 工具",
        )
        self.assertEqual(1, knowledge.seed(first))
        self.assertEqual(1, knowledge.seed(changed))
        self.assertEqual("new", knowledge.search("工具")[0].citation.source)

    def test_seed_rebuilds_after_deletion(self) -> None:
        knowledge = InMemoryKnowledgeBase()
        document = Document(id="seed", title="Seed", source="one", content="Agent 工具")
        self.assertEqual(1, knowledge.seed(document))
        self.assertTrue(knowledge.delete(document.id))
        self.assertEqual(1, knowledge.seed(document))
        self.assertEqual("one", knowledge.search("工具")[0].citation.source)

    def test_different_overlaps_produce_different_results(self) -> None:
        without_overlap_knowledge = InMemoryKnowledgeBase(chunk_size=20, overlap=0)
        with_overlap_knowledge = InMemoryKnowledgeBase(chunk_size=20, overlap=5)
        document = Document(id="test", title="Test", source="test", content="1234567890!@#$%^&权限校验")
        without_overlap_knowledge.add(document)
        with_overlap_knowledge.add(document)
        results_without_overlap = without_overlap_knowledge.search("权限校验")
        results_with_overlap = with_overlap_knowledge.search("权限校验")
        # 断言无 overlap 的结果中，没有任何 excerpt 包含完整 权限校验
        self.assertGreater(len(results_without_overlap), 0)
        self.assertTrue(all("权限校验" not in result.citation.excerpt for result in results_without_overlap))
        # 断言有 overlap 的结果中，至少一个 excerpt 包含完整 权限校验
        self.assertGreater(len(results_with_overlap), 0)
        self.assertTrue(any("权限校验" in result.citation.excerpt for result in results_with_overlap))
