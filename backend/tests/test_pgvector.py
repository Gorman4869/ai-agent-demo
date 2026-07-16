from __future__ import annotations

import unittest
from typing import Sequence
from unittest.mock import patch

from backend.app.knowledge import (
    Document,
    PgVectorKnowledgeBase,
    create_psycopg_connection_factory,
)


class _EmbeddingModel:
    def __init__(self, vector: Sequence[float] = (1.0, 2.0, 3.0)) -> None:
        self.vector = vector
        self.texts: list[str] = []

    def embed(self, text: str) -> Sequence[float]:
        self.texts.append(text)
        return self.vector


class _FakeCursor:
    def __init__(
        self,
        rows: Sequence[Sequence[object]] = (),
        *,
        fail_on_executemany: bool = False,
    ) -> None:
        self.rows = rows
        self.fail_on_executemany = fail_on_executemany
        self.executions: list[tuple[str, Sequence[object] | None]] = []
        self.batches: list[tuple[str, Sequence[Sequence[object]]]] = []
        self.closed = False

    def execute(
        self,
        query: str,
        parameters: Sequence[object] | None = None,
    ) -> object:
        self.executions.append((query, parameters))
        return self

    def executemany(
        self,
        query: str,
        parameters: Sequence[Sequence[object]],
    ) -> object:
        if self.fail_on_executemany:
            raise RuntimeError("database write failed")
        self.batches.append((query, parameters))
        return self

    def fetchall(self) -> Sequence[Sequence[object]]:
        return self.rows

    def close(self) -> None:
        self.closed = True


class _FakeConnection:
    def __init__(self, cursor: _FakeCursor) -> None:
        self._cursor = cursor
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def cursor(self) -> _FakeCursor:
        return self._cursor

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.closed = True


class _ConnectionFactory:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection
        self.calls = 0

    def __call__(self) -> _FakeConnection:
        self.calls += 1
        return self.connection


class PgVectorKnowledgeBaseTest(unittest.TestCase):
    def test_initialize_schema_is_explicit_and_transactional(self) -> None:
        cursor = _FakeCursor()
        connection = _FakeConnection(cursor)
        knowledge = PgVectorKnowledgeBase(
            _ConnectionFactory(connection),
            _EmbeddingModel(),
            dimensions=3,
        )

        knowledge.initialize_schema()

        self.assertEqual(2, len(cursor.executions))
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", cursor.executions[0][0])
        self.assertIn("embedding vector(3) NOT NULL", cursor.executions[1][0])
        self.assertEqual(1, connection.commits)
        self.assertEqual(0, connection.rollbacks)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_add_replaces_document_chunks_and_commits(self) -> None:
        cursor = _FakeCursor()
        connection = _FakeConnection(cursor)
        embedding = _EmbeddingModel()
        knowledge = PgVectorKnowledgeBase(
            _ConnectionFactory(connection),
            embedding,
            dimensions=3,
            chunk_size=20,
            overlap=0,
        )

        chunk_count = knowledge.add(
            Document(
                id="rag",
                title="RAG 基础",
                source="course/rag.md",
                content="12345678901234567890abcdefghij",
            )
        )

        self.assertEqual(2, chunk_count)
        self.assertIn("DELETE FROM", cursor.executions[0][0])
        self.assertEqual(("rag",), cursor.executions[0][1])
        self.assertEqual(1, len(cursor.batches))
        records = cursor.batches[0][1]
        self.assertEqual(2, len(records))
        self.assertEqual(("rag", 0, "RAG 基础", "course/rag.md"), records[0][:4])
        self.assertEqual("[1,2,3]", records[0][5])
        self.assertEqual(1, connection.commits)
        self.assertEqual(0, connection.rollbacks)

    def test_search_maps_positive_results_to_shared_contract(self) -> None:
        cursor = _FakeCursor(
            rows=(
                ("rag", "RAG 基础", "course/rag.md", 1, "可核验引用", 0.875),
                ("noise", "无关内容", "course/noise.md", 0, "无关", 0.0),
            )
        )
        connection = _FakeConnection(cursor)
        embedding = _EmbeddingModel()
        knowledge = PgVectorKnowledgeBase(
            _ConnectionFactory(connection),
            embedding,
            dimensions=3,
        )

        results = knowledge.search("如何返回引用？", limit=2)

        self.assertEqual(1, len(results))
        self.assertEqual(0.875, results[0].score)
        self.assertEqual("rag", results[0].citation.document_id)
        self.assertEqual("course/rag.md", results[0].citation.source)
        self.assertIn("<=>", cursor.executions[0][0])
        self.assertEqual(("[1,2,3]", 2), cursor.executions[0][1])
        self.assertEqual(["如何返回引用？"], embedding.texts)

    def test_invalid_embedding_fails_before_opening_connection(self) -> None:
        cursor = _FakeCursor()
        connection = _FakeConnection(cursor)
        factory = _ConnectionFactory(connection)
        knowledge = PgVectorKnowledgeBase(
            factory,
            _EmbeddingModel((1.0, 2.0)),
            dimensions=3,
        )

        with self.assertRaisesRegex(ValueError, "embedding dimension"):
            knowledge.search("query")

        self.assertEqual(0, factory.calls)

    def test_database_failure_rolls_back_and_propagates(self) -> None:
        cursor = _FakeCursor(fail_on_executemany=True)
        connection = _FakeConnection(cursor)
        knowledge = PgVectorKnowledgeBase(
            _ConnectionFactory(connection),
            _EmbeddingModel(),
            dimensions=3,
        )

        with self.assertRaisesRegex(RuntimeError, "database write failed"):
            knowledge.add(
                Document(id="rag", title="RAG", source="rag.md", content="RAG 检索")
            )

        self.assertEqual(0, connection.commits)
        self.assertEqual(1, connection.rollbacks)
        self.assertTrue(cursor.closed)
        self.assertTrue(connection.closed)

    def test_psycopg_is_loaded_only_when_optional_factory_is_called(self) -> None:
        factory = create_psycopg_connection_factory("postgresql://localhost/demo")

        with patch(
            "backend.app.knowledge.pgvector.import_module",
            side_effect=ModuleNotFoundError("psycopg"),
        ):
            with self.assertRaisesRegex(RuntimeError, "psycopg is required only"):
                factory()


if __name__ == "__main__":
    unittest.main()
