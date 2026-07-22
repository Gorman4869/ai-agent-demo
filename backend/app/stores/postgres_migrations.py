from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path

from psycopg import Error as PsycopgError
from psycopg_pool import AsyncConnectionPool


_MIGRATION_NAME = re.compile(r"(?P<version>[0-9]{4})_(?P<name>[a-z0-9_]+)\.sql")
_MIGRATION_LOCK = "ai-agent-demo-app-migrations-v1"
DEFAULT_MIGRATIONS_ROOT = Path(__file__).resolve().parents[2] / "migrations"


class MigrationError(RuntimeError):
    code = "migration_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class MigrationHistoryError(MigrationError):
    code = "migration_history_invalid"


class MigrationChecksumError(MigrationError):
    code = "migration_checksum_mismatch"


class MigrationApplyError(MigrationError):
    code = "migration_apply_failed"


@dataclass(frozen=True)
class SqlMigration:
    version: int
    name: str
    checksum: str
    sql: str

    @classmethod
    def from_sql(cls, *, version: int, name: str, sql: str) -> SqlMigration:
        if version < 1 or not name or not sql.strip():
            raise ValueError("migration metadata is invalid")
        return cls(
            version=version,
            name=name,
            checksum=hashlib.sha256(sql.encode("utf-8")).hexdigest(),
            sql=sql,
        )


def load_sql_migrations(
    root: Path = DEFAULT_MIGRATIONS_ROOT,
) -> tuple[SqlMigration, ...]:
    migrations: list[SqlMigration] = []
    for path in sorted(root.glob("*.sql")):
        matched = _MIGRATION_NAME.fullmatch(path.name)
        if matched is None:
            raise MigrationHistoryError()
        migrations.append(
            SqlMigration.from_sql(
                version=int(matched.group("version")),
                name=matched.group("name"),
                sql=path.read_text(encoding="utf-8"),
            )
        )
    expected_versions = list(range(1, len(migrations) + 1))
    if [migration.version for migration in migrations] != expected_versions:
        raise MigrationHistoryError()
    return tuple(migrations)


async def apply_postgres_migrations(
    pool: AsyncConnectionPool,
    *,
    migrations: tuple[SqlMigration, ...] | None = None,
) -> tuple[int, ...]:
    planned = migrations if migrations is not None else load_sql_migrations()
    try:
        async with pool.connection() as connection:
            async with connection.transaction():
                await connection.execute(
                    "SELECT pg_advisory_xact_lock(hashtext(%s))",
                    (_MIGRATION_LOCK,),
                )
                await connection.execute(
                    """
                    CREATE TABLE IF NOT EXISTS app_schema_migrations (
                        version integer PRIMARY KEY CHECK (version > 0),
                        name text NOT NULL,
                        checksum char(64) NOT NULL,
                        applied_at timestamptz NOT NULL DEFAULT CURRENT_TIMESTAMP
                    )
                    """
                )
                result = await connection.execute(
                    """
                    SELECT version, name, checksum
                    FROM app_schema_migrations
                    ORDER BY version
                    """
                )
                applied_rows = await result.fetchall()
                applied = {row["version"]: row for row in applied_rows}
                planned_by_version = {
                    migration.version: migration for migration in planned
                }
                applied_versions = sorted(applied)
                if applied_versions != list(
                    range(1, len(applied_versions) + 1)
                ):
                    raise MigrationHistoryError()
                if any(version not in planned_by_version for version in applied):
                    raise MigrationHistoryError()

                for version, row in applied.items():
                    migration = planned_by_version[version]
                    if (
                        row["name"] != migration.name
                        or row["checksum"].strip() != migration.checksum
                    ):
                        raise MigrationChecksumError()

                newly_applied: list[int] = []
                for migration in planned:
                    if migration.version in applied:
                        continue
                    await connection.execute(migration.sql, prepare=False)
                    await connection.execute(
                        """
                        INSERT INTO app_schema_migrations (
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
    "DEFAULT_MIGRATIONS_ROOT",
    "MigrationApplyError",
    "MigrationChecksumError",
    "MigrationError",
    "MigrationHistoryError",
    "SqlMigration",
    "apply_postgres_migrations",
    "load_sql_migrations",
]
