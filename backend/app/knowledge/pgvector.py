from __future__ import annotations

import math
import re
from contextlib import contextmanager
from importlib import import_module
from typing import Callable, Iterator, Protocol, Sequence, cast

from .embeddings import EmbeddingModel
from .pgvector_migrations import apply_pgvector_migrations
from .rag import (
    Citation,
    Document,
    SearchResult,
    _document_digest,
    _split_text,
)


PGVECTOR_DIMENSIONS = 3
PGVECTOR_DOCUMENT_TABLE = "knowledge_documents"
PGVECTOR_CHUNK_TABLE = "knowledge_chunks"


class DatabaseCursor(Protocol):
    def execute(
        self,
        query: str,
        parameters: Sequence[object] | None = None,
        *,
        prepare: bool | None = None,
    ) -> object: ...

    def executemany(
        self,
        query: str,
        parameters: Sequence[Sequence[object]],
    ) -> object: ...

    def fetchall(self) -> Sequence[Sequence[object]]: ...

    def fetchone(self) -> Sequence[object] | None: ...

    def close(self) -> None: ...


class DatabaseConnection(Protocol):
    def cursor(self) -> DatabaseCursor: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


DatabaseConnectionFactory = Callable[[], DatabaseConnection]


class PgVectorKnowledgeBase:
    """PostgreSQL/pgvector adapter with explicit schema and connection setup."""

    def __init__(
        self,
        connection_factory: DatabaseConnectionFactory,
        embedding_model: EmbeddingModel,
        *,
        dimensions: int,
        table_name: str = PGVECTOR_CHUNK_TABLE,
        document_table_name: str = PGVECTOR_DOCUMENT_TABLE,
        chunk_size: int = 160,
        overlap: int = 30,
    ) -> None:
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        if embedding_model.metadata.dimensions != dimensions:
            raise ValueError(
                "embedding metadata dimensions must match knowledge schema"
            )
        if chunk_size < 20:
            raise ValueError("chunk_size must be at least 20")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be between 0 and chunk_size")
        for name, value in (
            ("table_name", table_name),
            ("document_table_name", document_table_name),
        ):
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value) is None:
                raise ValueError(f"{name} must be a simple SQL identifier")
        self._connection_factory = connection_factory
        self._embedding_model = embedding_model
        self._dimensions = dimensions
        self._table_identifier = table_name
        self._document_table_identifier = document_table_name
        self._table_name = f'"{table_name}"'
        self._document_table_name = f'"{document_table_name}"'
        self._chunk_size = chunk_size
        self._overlap = overlap

    def initialize_schema(self) -> tuple[int, ...]:
        """Apply the fixed, versioned pgvector knowledge migration."""
        if (
            self._dimensions != PGVECTOR_DIMENSIONS
            or self._table_identifier != PGVECTOR_CHUNK_TABLE
            or self._document_table_identifier != PGVECTOR_DOCUMENT_TABLE
        ):
            raise ValueError(
                "default pgvector migration requires the fixed knowledge schema"
            )
        with self._transaction() as cursor:
            return apply_pgvector_migrations(cursor)

    def add(self, document: Document) -> int:
        chunks, digest, records = self._prepare_document(document)

        with self._transaction() as cursor:
            self._replace_document(
                cursor,
                document=document,
                digest=digest,
                records=records,
            )
        return len(chunks)

    def seed(self, document: Document) -> int:
        chunks, digest, records = self._prepare_document(document)
        with self._transaction() as cursor:
            cursor.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s), hashtext(%s))",
                ("knowledge-seed", document.id),
            )
            cursor.execute(
                f"""
                SELECT content_digest, chunk_count
                FROM {self._document_table_name}
                WHERE id = %s
                FOR UPDATE
                """,
                (document.id,),
            )
            current = cursor.fetchone()
            if current is not None and str(current[0]).strip() == digest:
                return int(current[1])
            self._replace_document(
                cursor,
                document=document,
                digest=digest,
                records=records,
            )
        return len(chunks)

    def delete(self, document_id: str) -> bool:
        if not isinstance(document_id, str) or not document_id:
            return False
        with self._transaction() as cursor:
            cursor.execute(
                f"""
                DELETE FROM {self._document_table_name}
                WHERE id = %s
                RETURNING id
                """,
                (document_id,),
            )
            return cursor.fetchone() is not None

    def search(self, query: str, *, limit: int = 3) -> tuple[SearchResult, ...]:
        if not query.strip() or limit < 1:
            return ()
        query_vector = self._embed_batch((query,))[0]
        with self._transaction() as cursor:
            cursor.execute(
                f"""
                WITH query_vector AS (
                    SELECT %s::vector AS embedding
                )
                SELECT
                    chunk.document_id,
                    document.title,
                    document.source,
                    chunk.chunk_index,
                    chunk.excerpt,
                    1 - (chunk.embedding <=> query_vector.embedding) AS score
                FROM {self._table_name} AS chunk
                JOIN {self._document_table_name} AS document
                    ON document.id = chunk.document_id
                CROSS JOIN query_vector
                ORDER BY
                    chunk.embedding <=> query_vector.embedding,
                    chunk.document_id,
                    chunk.chunk_index
                LIMIT %s
                """,
                (query_vector, limit),
            )
            rows = cursor.fetchall()

        results: list[SearchResult] = []
        for row in rows:
            if len(row) != 6:
                raise ValueError("pgvector search row must contain six values")
            score = float(row[5])
            if score <= 0:
                continue
            results.append(
                SearchResult(
                    score=score,
                    citation=Citation(
                        document_id=str(row[0]),
                        title=str(row[1]),
                        source=str(row[2]),
                        chunk_index=int(row[3]),
                        excerpt=str(row[4]),
                    ),
                )
            )
        return tuple(results)

    def _prepare_document(
        self,
        document: Document,
    ) -> tuple[list[str], str, list[Sequence[object]]]:
        if not document.content.strip():
            raise ValueError("document content must not be empty")
        chunks = _split_text(document.content, self._chunk_size, self._overlap)
        vectors = self._embed_batch(chunks)
        records: list[Sequence[object]] = []
        for chunk_index, (excerpt, vector) in enumerate(zip(chunks, vectors)):
            records.append(
                (
                    document.id,
                    chunk_index,
                    excerpt,
                    vector,
                )
            )
        return chunks, _document_digest(document, chunks), records

    def _replace_document(
        self,
        cursor: DatabaseCursor,
        *,
        document: Document,
        digest: str,
        records: list[Sequence[object]],
    ) -> None:
        cursor.execute(
            f"""
            INSERT INTO {self._document_table_name} (
                id,
                title,
                source,
                content_digest,
                chunk_count
            ) VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                source = EXCLUDED.source,
                content_digest = EXCLUDED.content_digest,
                chunk_count = EXCLUDED.chunk_count,
                updated_at = clock_timestamp()
            """,
            (
                document.id,
                document.title,
                document.source,
                digest,
                len(records),
            ),
        )
        cursor.execute(
            f"DELETE FROM {self._table_name} WHERE document_id = %s",
            (document.id,),
        )
        cursor.executemany(
            f"""
            INSERT INTO {self._table_name} (
                document_id,
                chunk_index,
                excerpt,
                embedding
            )
            VALUES (%s, %s, %s, %s::vector)
            """,
            records,
        )

    def _embed_batch(self, texts: Sequence[str]) -> tuple[str, ...]:
        if self._embedding_model.metadata.dimensions != self._dimensions:
            raise ValueError("embedding metadata dimensions changed")
        vectors = tuple(self._embedding_model.embed_batch(texts))
        if len(vectors) != len(texts):
            raise ValueError("embedding batch size must match input size")

        serialized: list[str] = []
        for vector in vectors:
            try:
                values = tuple(float(value) for value in vector)
            except (TypeError, ValueError):
                raise ValueError("embedding values must be numeric") from None
            if len(values) != self._dimensions:
                raise ValueError(
                    f"embedding dimension must be {self._dimensions}, "
                    f"got {len(values)}"
                )
            if not all(math.isfinite(value) for value in values):
                raise ValueError("embedding values must be finite")
            serialized.append(
                f"[{','.join(format(value, '.17g') for value in values)}]"
            )
        return tuple(serialized)

    @contextmanager
    def _transaction(self) -> Iterator[DatabaseCursor]:
        connection = self._connection_factory()
        cursor: DatabaseCursor | None = None
        try:
            cursor = connection.cursor()
            yield cursor
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()


def create_psycopg_connection_factory(dsn: str) -> DatabaseConnectionFactory:
    """Build a lazy psycopg factory without making psycopg a core dependency."""
    if not dsn.strip():
        raise ValueError("dsn must not be empty")

    def connect() -> DatabaseConnection:
        try:
            psycopg = import_module("psycopg")
        except ImportError as exc:
            raise RuntimeError(
                "psycopg is required only when using the pgvector adapter"
            ) from exc
        return cast(DatabaseConnection, psycopg.connect(dsn))

    return connect
