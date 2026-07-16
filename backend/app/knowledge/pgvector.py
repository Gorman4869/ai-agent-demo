from __future__ import annotations

import math
import re
from contextlib import contextmanager
from importlib import import_module
from typing import Callable, Iterator, Protocol, Sequence, cast

from .rag import Citation, Document, SearchResult, _split_text


class EmbeddingModel(Protocol):
    def embed(self, text: str) -> Sequence[float]:
        """Return one fixed-size vector for the supplied text."""


class DatabaseCursor(Protocol):
    def execute(
        self,
        query: str,
        parameters: Sequence[object] | None = None,
    ) -> object: ...

    def executemany(
        self,
        query: str,
        parameters: Sequence[Sequence[object]],
    ) -> object: ...

    def fetchall(self) -> Sequence[Sequence[object]]: ...

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
        table_name: str = "knowledge_chunks",
        chunk_size: int = 160,
        overlap: int = 30,
    ) -> None:
        if dimensions < 1:
            raise ValueError("dimensions must be positive")
        if chunk_size < 20:
            raise ValueError("chunk_size must be at least 20")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be between 0 and chunk_size")
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name) is None:
            raise ValueError("table_name must be a simple SQL identifier")
        self._connection_factory = connection_factory
        self._embedding_model = embedding_model
        self._dimensions = dimensions
        self._table_name = f'"{table_name}"'
        self._chunk_size = chunk_size
        self._overlap = overlap

    def initialize_schema(self) -> None:
        """Create the pgvector extension and chunk table when explicitly requested."""
        with self._transaction() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {self._table_name} (
                    document_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    source TEXT NOT NULL,
                    excerpt TEXT NOT NULL,
                    embedding vector({self._dimensions}) NOT NULL,
                    PRIMARY KEY (document_id, chunk_index)
                )
                """
            )

    def add(self, document: Document) -> int:
        if not document.content.strip():
            raise ValueError("document content must not be empty")
        chunks = _split_text(document.content, self._chunk_size, self._overlap)
        records: list[Sequence[object]] = []
        for chunk_index, excerpt in enumerate(chunks):
            records.append(
                (
                    document.id,
                    chunk_index,
                    document.title,
                    document.source,
                    excerpt,
                    self._embed(excerpt),
                )
            )

        with self._transaction() as cursor:
            cursor.execute(
                f"DELETE FROM {self._table_name} WHERE document_id = %s",
                (document.id,),
            )
            cursor.executemany(
                f"""
                INSERT INTO {self._table_name} (
                    document_id,
                    chunk_index,
                    title,
                    source,
                    excerpt,
                    embedding
                )
                VALUES (%s, %s, %s, %s, %s, %s::vector)
                """,
                records,
            )
        return len(chunks)

    def search(self, query: str, *, limit: int = 3) -> tuple[SearchResult, ...]:
        if not query.strip() or limit < 1:
            return ()
        query_vector = self._embed(query)
        with self._transaction() as cursor:
            cursor.execute(
                f"""
                WITH query_vector AS (
                    SELECT %s::vector AS embedding
                )
                SELECT
                    chunk.document_id,
                    chunk.title,
                    chunk.source,
                    chunk.chunk_index,
                    chunk.excerpt,
                    1 - (chunk.embedding <=> query_vector.embedding) AS score
                FROM {self._table_name} AS chunk
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

    def _embed(self, text: str) -> str:
        values = tuple(float(value) for value in self._embedding_model.embed(text))
        if len(values) != self._dimensions:
            raise ValueError(
                f"embedding dimension must be {self._dimensions}, got {len(values)}"
            )
        if not all(math.isfinite(value) for value in values):
            raise ValueError("embedding values must be finite")
        return f"[{','.join(format(value, '.17g') for value in values)}]"

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
