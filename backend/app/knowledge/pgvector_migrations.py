from __future__ import annotations

from pathlib import Path
from typing import Protocol, Sequence

from psycopg import Error as PsycopgError

from backend.app.stores.postgres_migrations import (
    MigrationApplyError,
    MigrationChecksumError,
    MigrationError,
    MigrationHistoryError,
    SqlMigration,
    load_sql_migrations,
)


_MIGRATION_LOCK = "ai-agent-demo-knowledge-migrations-v1"
DEFAULT_KNOWLEDGE_MIGRATIONS_ROOT = (
    Path(__file__).resolve().parents[2] / "knowledge_migrations"
)


class PgVectorMigrationCursor(Protocol):
    def execute(
        self,
        query: str,
        parameters: Sequence[object] | None = None,
        *,
        prepare: bool | None = None,
    ) -> object: ...

    def fetchall(self) -> Sequence[Sequence[object]]: ...


def load_pgvector_migrations(
    root: Path = DEFAULT_KNOWLEDGE_MIGRATIONS_ROOT,
) -> tuple[SqlMigration, ...]:
    return load_sql_migrations(root)


def apply_pgvector_migrations(
    cursor: PgVectorMigrationCursor,
    *,
    migrations: tuple[SqlMigration, ...] | None = None,
) -> tuple[int, ...]:
    planned = migrations if migrations is not None else load_pgvector_migrations()
    try:
        cursor.execute(
            "SELECT pg_advisory_xact_lock(hashtext(%s))",
            (_MIGRATION_LOCK,),
        )
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS knowledge_schema_migrations (
                version integer PRIMARY KEY CHECK (version > 0),
                name text NOT NULL,
                checksum char(64) NOT NULL,
                applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        cursor.execute(
            """
            SELECT version, name, checksum
            FROM knowledge_schema_migrations
            ORDER BY version
            """
        )
        applied_rows = cursor.fetchall()
        applied = {
            int(row[0]): (str(row[1]), str(row[2]).strip())
            for row in applied_rows
        }
        planned_by_version = {
            migration.version: migration for migration in planned
        }
        applied_versions = sorted(applied)
        if applied_versions != list(range(1, len(applied_versions) + 1)):
            raise MigrationHistoryError()
        if any(version not in planned_by_version for version in applied):
            raise MigrationHistoryError()

        for version, (name, checksum) in applied.items():
            migration = planned_by_version[version]
            if name != migration.name or checksum != migration.checksum:
                raise MigrationChecksumError()

        newly_applied: list[int] = []
        for migration in planned:
            if migration.version in applied:
                continue
            cursor.execute(migration.sql, prepare=False)
            cursor.execute(
                """
                INSERT INTO knowledge_schema_migrations (
                    version,
                    name,
                    checksum
                ) VALUES (%s, %s, %s)
                """,
                (
                    migration.version,
                    migration.name,
                    migration.checksum,
                ),
            )
            newly_applied.append(migration.version)
        return tuple(newly_applied)
    except MigrationError:
        raise
    except PsycopgError:
        raise MigrationApplyError() from None


__all__ = [
    "DEFAULT_KNOWLEDGE_MIGRATIONS_ROOT",
    "apply_pgvector_migrations",
    "load_pgvector_migrations",
]
