from __future__ import annotations

import os
import unittest
from typing import Sequence

import psycopg

from backend.app.knowledge import (
    Document,
    EmbeddingMetadata,
    PGVECTOR_DIMENSIONS,
    PgVectorKnowledgeBase,
    create_psycopg_connection_factory,
)


PGVECTOR_DSN = os.environ.get("AI_AGENT_TEST_PGVECTOR_DSN", "")


def setUpModule() -> None:
    if not PGVECTOR_DSN:
        raise unittest.SkipTest("AI_AGENT_TEST_PGVECTOR_DSN is not configured")


class _KeywordEmbedding:
    metadata = EmbeddingMetadata(
        provider="test",
        model="keyword",
        revision="v1",
        dimensions=3,
    )

    def embed(self, text: str) -> Sequence[float]:
        lowered = text.lower()
        if "mcp" in lowered or "协议" in text:
            return (0.0, 1.0, 0.0)
        if "记忆" in text or "memory" in lowered:
            return (0.0, 0.0, 1.0)
        return (1.0, 0.0, 0.0)

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[Sequence[float], ...]:
        return tuple(self.embed(text) for text in texts)


class _TwoDimensionalEmbedding:
    metadata = EmbeddingMetadata(
        provider="test",
        model="two-dimensional",
        revision="v1",
        dimensions=2,
    )

    def embed(self, text: str) -> Sequence[float]:
        del text
        return (1.0, 0.0)

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[Sequence[float], ...]:
        return tuple(self.embed(text) for text in texts)


class PgVectorIntegrationTest(unittest.TestCase):
    def setUp(self) -> None:
        self._reset_schema()
        self.knowledge = PgVectorKnowledgeBase(
            create_psycopg_connection_factory(PGVECTOR_DSN),
            _KeywordEmbedding(),
            dimensions=PGVECTOR_DIMENSIONS,
            chunk_size=80,
            overlap=10,
        )

    def tearDown(self) -> None:
        self._reset_schema()

    def test_versioned_migration_creates_extension_tables_and_cosine_index(
        self,
    ) -> None:
        first = self.knowledge.initialize_schema()
        second = self.knowledge.initialize_schema()

        self.assertEqual((1,), first)
        self.assertEqual((), second)
        with psycopg.connect(PGVECTOR_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
                )
                self.assertIsNotNone(cursor.fetchone())
                cursor.execute(
                    """
                    SELECT format_type(attribute.atttypid, attribute.atttypmod)
                    FROM pg_attribute AS attribute
                    WHERE attribute.attrelid = 'knowledge_chunks'::regclass
                      AND attribute.attname = 'embedding'
                    """
                )
                self.assertEqual(("vector(3)",), cursor.fetchone())
                cursor.execute(
                    """
                    SELECT indexdef
                    FROM pg_indexes
                    WHERE indexname = 'knowledge_chunks_embedding_hnsw_idx'
                    """
                )
                index_definition = str(cursor.fetchone()[0]).lower()
                self.assertIn("using hnsw", index_definition)
                self.assertIn("vector_cosine_ops", index_definition)

    def test_add_replace_search_and_delete_use_real_vector_column(self) -> None:
        self.knowledge.initialize_schema()
        self.knowledge.add(
            Document(
                id="agent",
                title="Agent 基础",
                source="course/agent.md",
                content="Agent 负责协调模型、工具与循环控制。",
            )
        )
        self.knowledge.add(
            Document(
                id="mcp",
                title="MCP 基础",
                source="course/mcp.md",
                content="MCP 使用统一协议连接 Agent 与工具。",
            )
        )

        mcp_results = self.knowledge.search("MCP 如何连接工具？", limit=2)

        self.assertEqual(1, len(mcp_results))
        self.assertEqual("mcp", mcp_results[0].citation.document_id)
        self.assertEqual("course/mcp.md", mcp_results[0].citation.source)
        self.assertAlmostEqual(1.0, mcp_results[0].score)

        self.knowledge.add(
            Document(
                id="mcp",
                title="持久记忆",
                source="course/memory.md",
                content="长期记忆必须可以纠正和删除。",
            )
        )
        self.assertEqual((), self.knowledge.search("MCP 协议", limit=2))
        memory_results = self.knowledge.search("如何删除记忆？", limit=2)
        self.assertEqual("course/memory.md", memory_results[0].citation.source)

        self.assertTrue(self.knowledge.delete("mcp"))
        self.assertFalse(self.knowledge.delete("mcp"))
        self.assertEqual((), self.knowledge.search("如何删除记忆？", limit=2))

    def test_same_seed_does_not_rewrite_chunks(self) -> None:
        self.knowledge.initialize_schema()
        document = Document(
            id="seed",
            title="Course Seed",
            source="course/seed.md",
            content="Agent 负责协调模型、工具与循环控制。",
        )

        first_count = self.knowledge.seed(document)
        before = self._document_snapshot("seed")
        second_count = self.knowledge.seed(document)
        after = self._document_snapshot("seed")

        self.assertEqual(1, first_count)
        self.assertEqual(first_count, second_count)
        self.assertEqual(before, after)

    def test_dimension_error_rolls_back_document_replacement(self) -> None:
        self.knowledge.initialize_schema()
        original = Document(
            id="rollback",
            title="Original",
            source="course/original.md",
            content="Agent 负责协调模型、工具与循环控制。",
        )
        self.knowledge.add(original)
        mismatched = PgVectorKnowledgeBase(
            create_psycopg_connection_factory(PGVECTOR_DSN),
            _TwoDimensionalEmbedding(),
            dimensions=2,
            chunk_size=80,
            overlap=10,
        )

        with self.assertRaises(psycopg.Error):
            mismatched.add(
                Document(
                    id="rollback",
                    title="Broken",
                    source="course/broken.md",
                    content="MCP 使用统一协议连接 Agent 与工具。",
                )
            )

        results = self.knowledge.search("Agent 如何协调工具？", limit=1)
        self.assertEqual(1, len(results))
        self.assertEqual("Original", results[0].citation.title)
        self.assertEqual("course/original.md", results[0].citation.source)

    def _document_snapshot(self, document_id: str) -> tuple[object, ...]:
        with psycopg.connect(PGVECTOR_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    SELECT
                        document.xmin::text,
                        document.updated_at,
                        document.chunk_count,
                        (
                            SELECT COUNT(*)
                            FROM knowledge_chunks AS chunk
                            WHERE chunk.document_id = document.id
                        )
                    FROM knowledge_documents AS document
                    WHERE document.id = %s
                    """,
                    (document_id,),
                )
                row = cursor.fetchone()
        if row is None:
            raise AssertionError("knowledge document was not persisted")
        return tuple(row)

    @staticmethod
    def _reset_schema() -> None:
        with psycopg.connect(PGVECTOR_DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    """
                    DROP TABLE IF EXISTS knowledge_chunks CASCADE;
                    DROP TABLE IF EXISTS knowledge_documents CASCADE;
                    DROP TABLE IF EXISTS knowledge_schema_migrations CASCADE;
                    DROP EXTENSION IF EXISTS vector CASCADE;
                    """,
                    prepare=False,
                )


if __name__ == "__main__":
    unittest.main()
