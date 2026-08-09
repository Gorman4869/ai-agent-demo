from __future__ import annotations

import unittest
from typing import Sequence
from unittest.mock import patch

from backend.app.knowledge import (
    Document,
    EmbeddingMetadata,
    PgVectorKnowledgeBase,
    create_psycopg_connection_factory,
)
from backend.app.knowledge.pgvector_migrations import load_pgvector_migrations
from backend.app.stores.postgres_migrations import (
    MigrationChecksumError,
    MigrationHistoryError,
)


class _EmbeddingModel:
    def __init__(
        self,
        vector: Sequence[float] = (1.0, 2.0, 3.0),
        *,
        metadata_dimensions: int = 3,
    ) -> None:
        self.vector = vector
        self.texts: list[str] = []
        self.batches: list[tuple[str, ...]] = []
        self.metadata = EmbeddingMetadata(
            provider="test",
            model="fixture",
            revision="v1",
            dimensions=metadata_dimensions,
        )

    def embed(self, text: str) -> Sequence[float]:
        self.texts.append(text)
        return self.vector

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[Sequence[float], ...]:
        batch = tuple(texts)
        self.batches.append(batch)
        self.texts.extend(batch)
        return tuple(self.vector for _ in batch)


class _IncompleteEmbeddingModel(_EmbeddingModel):
    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[Sequence[float], ...]:
        vectors = super().embed_batch(texts)
        return vectors[:-1]


class _FakeCursor:
    def __init__(
        self,
        rows: Sequence[Sequence[object]] = (),
        *,
        row: Sequence[object] | None = None,
        fail_on_executemany: bool = False,
    ) -> None:
        self.rows = rows
        self.row = row
        self.fail_on_executemany = fail_on_executemany
        self.executions: list[tuple[str, Sequence[object] | None]] = []
        self.batches: list[tuple[str, Sequence[Sequence[object]]]] = []
        self.closed = False

    def execute(
        self,
        query: str,
        parameters: Sequence[object] | None = None,
        *,
        prepare: bool | None = None,
    ) -> object:
        del prepare
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

    def fetchone(self) -> Sequence[object] | None:
        return self.row

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

        applied = knowledge.initialize_schema()

        statements = "\n".join(query for query, _ in cursor.executions)
        self.assertEqual((1,), applied)
        self.assertIn("knowledge_schema_migrations", statements)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", statements)
        self.assertIn("embedding vector(3) NOT NULL", statements)
        self.assertIn("USING hnsw (embedding vector_cosine_ops)", statements)
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
        self.assertIn("INSERT INTO", cursor.executions[0][0])
        self.assertEqual(
            ("rag", "RAG 基础", "course/rag.md"),
            cursor.executions[0][1][:3],
        )
        self.assertIn("DELETE FROM", cursor.executions[1][0])
        self.assertEqual(("rag",), cursor.executions[1][1])
        self.assertEqual(1, len(cursor.batches))
        records = cursor.batches[0][1]
        self.assertEqual(2, len(records))
        self.assertEqual(("rag", 0, "12345678901234567890"), records[0][:3])
        self.assertEqual("[1,2,3]", records[0][3])
        self.assertEqual(
            [("12345678901234567890", "abcdefghij")],
            embedding.batches,
        )
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
        self.assertIn("JOIN \"knowledge_documents\"", cursor.executions[0][0])
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

    def test_incomplete_embedding_batch_fails_before_opening_connection(
        self,
    ) -> None:
        factory = _ConnectionFactory(_FakeConnection(_FakeCursor()))
        knowledge = PgVectorKnowledgeBase(
            factory,
            _IncompleteEmbeddingModel(),
            dimensions=3,
            chunk_size=20,
            overlap=0,
        )

        with self.assertRaisesRegex(ValueError, "batch size"):
            knowledge.add(
                Document(
                    id="rag",
                    title="RAG",
                    source="rag.md",
                    content="12345678901234567890abcdefghij",
                )
            )

        self.assertEqual(0, factory.calls)

    def test_metadata_dimension_mismatch_fails_before_connection(self) -> None:
        factory = _ConnectionFactory(_FakeConnection(_FakeCursor()))

        with self.assertRaisesRegex(ValueError, "metadata dimensions"):
            PgVectorKnowledgeBase(
                factory,
                _EmbeddingModel(metadata_dimensions=2),
                dimensions=3,
            )

        self.assertEqual(0, factory.calls)

    def test_seed_skips_same_document_digest(self) -> None:
        document = Document(
            id="seed",
            title="Seed",
            source="course/seed.md",
            content="12345678901234567890abcdefghij",
        )
        first_cursor = _FakeCursor()
        first = PgVectorKnowledgeBase(
            _ConnectionFactory(_FakeConnection(first_cursor)),
            _EmbeddingModel(),
            dimensions=3,
            chunk_size=20,
            overlap=0,
        )

        self.assertEqual(2, first.seed(document))
        insert = next(
            execution
            for execution in first_cursor.executions
            if 'INSERT INTO "knowledge_documents"' in execution[0]
        )
        assert insert[1] is not None
        digest = insert[1][3]

        second_cursor = _FakeCursor(row=(digest, 2))
        second_connection = _FakeConnection(second_cursor)
        second = PgVectorKnowledgeBase(
            _ConnectionFactory(second_connection),
            _EmbeddingModel(),
            dimensions=3,
            chunk_size=20,
            overlap=0,
        )

        self.assertEqual(2, second.seed(document))
        self.assertEqual(2, len(second_cursor.executions))
        self.assertEqual([], second_cursor.batches)
        self.assertEqual(1, second_connection.commits)

    def test_delete_returns_database_result(self) -> None:
        existing_cursor = _FakeCursor(row=("rag",))
        existing = PgVectorKnowledgeBase(
            _ConnectionFactory(_FakeConnection(existing_cursor)),
            _EmbeddingModel(),
            dimensions=3,
        )
        missing = PgVectorKnowledgeBase(
            _ConnectionFactory(_FakeConnection(_FakeCursor())),
            _EmbeddingModel(),
            dimensions=3,
        )

        self.assertTrue(existing.delete("rag"))
        self.assertFalse(missing.delete("missing"))
        self.assertIn("RETURNING id", existing_cursor.executions[0][0])

    def test_default_migration_rejects_custom_dimensions_before_connection(self) -> None:
        factory = _ConnectionFactory(_FakeConnection(_FakeCursor()))
        knowledge = PgVectorKnowledgeBase(
            factory,
            _EmbeddingModel((1.0, 2.0), metadata_dimensions=2),
            dimensions=2,
        )

        with self.assertRaisesRegex(ValueError, "fixed knowledge schema"):
            knowledge.initialize_schema()

        self.assertEqual(0, factory.calls)

    def test_migration_checksum_drift_rolls_back(self) -> None:
        migration = load_pgvector_migrations()[0]
        cursor = _FakeCursor(
            rows=((migration.version, migration.name, "0" * 64),)
        )
        connection = _FakeConnection(cursor)
        knowledge = PgVectorKnowledgeBase(
            _ConnectionFactory(connection),
            _EmbeddingModel(),
            dimensions=3,
        )

        with self.assertRaises(MigrationChecksumError):
            knowledge.initialize_schema()

        self.assertEqual(0, connection.commits)
        self.assertEqual(1, connection.rollbacks)

    def test_migration_history_gap_rolls_back(self) -> None:
        cursor = _FakeCursor(rows=((2, "unexpected", "0" * 64),))
        connection = _FakeConnection(cursor)
        knowledge = PgVectorKnowledgeBase(
            _ConnectionFactory(connection),
            _EmbeddingModel(),
            dimensions=3,
        )

        with self.assertRaises(MigrationHistoryError):
            knowledge.initialize_schema()

        self.assertEqual(0, connection.commits)
        self.assertEqual(1, connection.rollbacks)

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
