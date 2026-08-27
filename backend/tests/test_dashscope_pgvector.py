from __future__ import annotations

import unittest
from collections.abc import Sequence

from backend.app.knowledge import (
    DASHSCOPE_EMBEDDING_DIMENSIONS,
    DashScopePgVectorKnowledgeBase,
    Document,
    EmbeddingMetadata,
)


class _Embedding:
    metadata = EmbeddingMetadata(
        provider="dashscope",
        model="text-embedding-v4",
        revision="m11-t7-dashscope-v1",
        dimensions=DASHSCOPE_EMBEDDING_DIMENSIONS,
    )

    def embed(self, text: str) -> Sequence[float]:
        del text
        return (1.0,) + (0.0,) * 63

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[Sequence[float], ...]:
        return tuple(self.embed(text) for text in texts)


class _Cursor:
    def __init__(self) -> None:
        self.executions: list[str] = []
        self.batches: list[Sequence[Sequence[object]]] = []
        self.closed = False

    def execute(
        self,
        query: str,
        parameters: Sequence[object] | None = None,
        *,
        prepare: bool | None = None,
    ) -> _Cursor:
        del parameters, prepare
        self.executions.append(query)
        return self

    def executemany(
        self,
        query: str,
        parameters: Sequence[Sequence[object]],
    ) -> _Cursor:
        self.executions.append(query)
        self.batches.append(parameters)
        return self

    def fetchall(self) -> Sequence[Sequence[object]]:
        return ()

    def fetchone(self) -> Sequence[object] | None:
        return None

    def close(self) -> None:
        self.closed = True


class _Connection:
    def __init__(self, cursor: _Cursor) -> None:
        self.cursor_value = cursor
        self.commits = 0
        self.rollbacks = 0

    def cursor(self) -> _Cursor:
        return self.cursor_value

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        pass


class DashScopePgVectorKnowledgeBaseTest(unittest.TestCase):
    def test_schema_is_explicit_isolated_and_fixed_to_sixty_four_dimensions(self) -> None:
        cursor = _Cursor()
        connection = _Connection(cursor)
        knowledge = DashScopePgVectorKnowledgeBase(lambda: connection, _Embedding())

        self.assertEqual((1,), knowledge.initialize_schema())

        statements = "\n".join(cursor.executions)
        self.assertIn("dashscope_knowledge_schema_migrations", statements)
        self.assertIn("dashscope_knowledge_chunks", statements)
        self.assertIn("embedding vector(64) NOT NULL", statements)
        self.assertEqual(1, connection.commits)

    def test_write_uses_the_isolated_dashscope_tables(self) -> None:
        cursor = _Cursor()
        knowledge = DashScopePgVectorKnowledgeBase(
            lambda: _Connection(cursor),
            _Embedding(),
            chunk_size=20,
            overlap=0,
        )

        knowledge.add(
            Document(
                id="dashscope-smoke",
                title="DashScope Smoke",
                source="course/dashscope.md",
                content="12345678901234567890abcdefghij",
            )
        )

        statements = "\n".join(cursor.executions)
        self.assertIn('INSERT INTO "dashscope_knowledge_documents"', statements)
        self.assertIn('DELETE FROM "dashscope_knowledge_chunks"', statements)
        self.assertIn('INSERT INTO "dashscope_knowledge_chunks"', statements)
        self.assertEqual(64, len(tuple(cursor.batches[0][0][3].split(","))))


if __name__ == "__main__":
    unittest.main()
