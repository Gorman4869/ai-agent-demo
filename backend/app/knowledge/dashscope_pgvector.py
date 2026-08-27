from __future__ import annotations

from pathlib import Path

from .embeddings import EmbeddingModel
from .pgvector import DatabaseConnectionFactory, PgVectorKnowledgeBase
from .pgvector_migrations import apply_pgvector_migrations, load_pgvector_migrations


DASHSCOPE_EMBEDDING_DIMENSIONS = 64
DASHSCOPE_DOCUMENT_TABLE = "dashscope_knowledge_documents"
DASHSCOPE_CHUNK_TABLE = "dashscope_knowledge_chunks"
_DASHSCOPE_MIGRATION_LOCK = "ai-agent-demo-dashscope-knowledge-migrations-v1"
_DASHSCOPE_MIGRATION_TABLE = "dashscope_knowledge_schema_migrations"
_DASHSCOPE_MIGRATIONS_ROOT = (
    Path(__file__).resolve().parents[2] / "dashscope_knowledge_migrations"
)


class DashScopePgVectorKnowledgeBase(PgVectorKnowledgeBase):
    """Fixed 64-dimensional pgvector store reserved for DashScope smoke checks."""

    def __init__(
        self,
        connection_factory: DatabaseConnectionFactory,
        embedding_model: EmbeddingModel,
        *,
        chunk_size: int = 160,
        overlap: int = 30,
    ) -> None:
        super().__init__(
            connection_factory,
            embedding_model,
            dimensions=DASHSCOPE_EMBEDDING_DIMENSIONS,
            table_name=DASHSCOPE_CHUNK_TABLE,
            document_table_name=DASHSCOPE_DOCUMENT_TABLE,
            chunk_size=chunk_size,
            overlap=overlap,
        )

    def initialize_schema(self) -> tuple[int, ...]:
        """Apply the isolated, fixed-dimensional DashScope smoke schema."""
        with self._transaction() as cursor:
            return apply_pgvector_migrations(
                cursor,
                migrations=load_pgvector_migrations(_DASHSCOPE_MIGRATIONS_ROOT),
                migration_lock=_DASHSCOPE_MIGRATION_LOCK,
                migration_table=_DASHSCOPE_MIGRATION_TABLE,
            )


__all__ = [
    "DASHSCOPE_CHUNK_TABLE",
    "DASHSCOPE_DOCUMENT_TABLE",
    "DASHSCOPE_EMBEDDING_DIMENSIONS",
    "DashScopePgVectorKnowledgeBase",
]
