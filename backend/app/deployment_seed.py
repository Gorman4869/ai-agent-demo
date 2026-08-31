from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Protocol

from psycopg import Error as PsycopgError

from backend.app.knowledge import (
    DEMO_COURSE_DOCUMENT,
    Document,
    PGVECTOR_DIMENSIONS,
    PgVectorKnowledgeBase,
    create_deterministic_embedding_model,
    create_psycopg_connection_factory,
)
from backend.app.knowledge.embeddings import EmbeddingError
from backend.app.stores.postgres_migrations import MigrationError
from backend.app.settings import Settings, SettingsError


class DeploymentKnowledgeBase(Protocol):
    def initialize_schema(self) -> tuple[int, ...]: ...

    def seed(self, document: Document) -> int: ...


@dataclass(frozen=True)
class DeploymentSeedReport:
    migration_versions: tuple[int, ...]
    document_id: str
    chunk_count: int

    def to_record(self) -> dict[str, object]:
        return {
            "status": "ok",
            "migration_versions": list(self.migration_versions),
            "document_id": self.document_id,
            "chunk_count": self.chunk_count,
            "embedding_provider": "offline",
        }


def initialize_deployment_knowledge(
    settings: Settings,
    *,
    knowledge_base: DeploymentKnowledgeBase | None = None,
) -> DeploymentSeedReport:
    """Apply the fixed pgvector schema and explicit idempotent course seed."""

    if settings.persistence.backend != "postgres":
        raise SettingsError("deployment seed requires postgres persistence")
    postgres_dsn = settings.persistence.postgres_dsn
    if postgres_dsn is None:
        raise SettingsError("deployment seed requires a configured DSN")
    if settings.embedding.provider != "offline":
        raise SettingsError("deployment seed requires the offline embedding provider")
    if settings.embedding.dimensions != PGVECTOR_DIMENSIONS:
        raise SettingsError("deployment seed requires the fixed pgvector dimensions")

    resolved_knowledge_base = knowledge_base
    if resolved_knowledge_base is None:
        embedding_model = create_deterministic_embedding_model(
            dimensions=PGVECTOR_DIMENSIONS,
            batch_size=settings.embedding.batch_size,
        )
        resolved_knowledge_base = PgVectorKnowledgeBase(
            create_psycopg_connection_factory(
                postgres_dsn.get_secret_value()
            ),
            embedding_model,
            dimensions=PGVECTOR_DIMENSIONS,
        )

    migration_versions = resolved_knowledge_base.initialize_schema()
    chunk_count = resolved_knowledge_base.seed(DEMO_COURSE_DOCUMENT)
    return DeploymentSeedReport(
        migration_versions=migration_versions,
        document_id=DEMO_COURSE_DOCUMENT.id,
        chunk_count=chunk_count,
    )


def main() -> int:
    try:
        report = initialize_deployment_knowledge(Settings.from_environment())
    except SettingsError:
        print(json.dumps({"status": "failed", "error_code": "configuration_invalid"}))
        return 1
    except (MigrationError, PsycopgError, EmbeddingError):
        print(json.dumps({"status": "failed", "error_code": "deployment_seed_failed"}))
        return 1
    print(json.dumps(report.to_record(), ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "DeploymentSeedReport",
    "initialize_deployment_knowledge",
    "main",
]
