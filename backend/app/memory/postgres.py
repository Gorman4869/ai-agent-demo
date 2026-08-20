from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from psycopg import Connection, Error as PsycopgError
from psycopg.rows import DictRow
from psycopg_pool import ConnectionPool, PoolTimeout

from backend.app.domain import Message
from backend.app.memory.store import (
    CorrectMemoryFact,
    DeleteMemoryFact,
    DeleteMemoryFactResult,
    MemoryFact,
    MemoryFactAuditAction,
    MemoryFactAuditRecord,
    MemoryFactConflictError,
    MemoryFactNotFoundError,
    MemoryScope,
    MemoryTurnConflictError,
    PublishTurn,
    PublishTurnResult,
    _fact_value_digest,
    _require_identifier,
)
from backend.app.stores.base import StoreUnavailableError


Clock = Callable[[], datetime]
SyncPool = ConnectionPool[Connection[DictRow]]


class PostgresMemoryStore:
    """Persist bounded conversation history and approved long-term facts."""

    def __init__(
        self,
        pool: SyncPool,
        *,
        message_limit: int = 20,
        clock: Clock | None = None,
    ) -> None:
        if message_limit < 1:
            raise ValueError("message_limit must be at least 1")
        self._pool = pool
        self._message_limit = message_limit
        self._clock = clock or (lambda: datetime.now(UTC))

    def append_message(self, session_id: str, message: Message) -> None:
        try:
            with self._pool.connection() as connection:
                with connection.transaction():
                    row = connection.execute(
                        """
                        INSERT INTO memory_message_sequences (
                            session_id,
                            next_sequence
                        ) VALUES (%s, 2)
                        ON CONFLICT (session_id) DO UPDATE
                        SET next_sequence =
                            memory_message_sequences.next_sequence + 1
                        RETURNING next_sequence - 1 AS sequence
                        """,
                        (session_id,),
                    ).fetchone()
                    if row is None:
                        raise StoreUnavailableError()
                    sequence = row["sequence"]
                    connection.execute(
                        """
                        INSERT INTO conversation_messages (
                            session_id,
                            sequence,
                            role,
                            content,
                            name,
                            tool_call_id
                        ) VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            session_id,
                            sequence,
                            message.role,
                            message.content,
                            message.name,
                            message.tool_call_id,
                        ),
                    )
                    connection.execute(
                        """
                        DELETE FROM conversation_messages
                        WHERE session_id = %s
                          AND sequence <= %s
                        """,
                        (session_id, sequence - self._message_limit),
                    )
        except StoreUnavailableError:
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def publish_turn(self, command: PublishTurn) -> PublishTurnResult:
        if not isinstance(command, PublishTurn):
            raise ValueError("publish turn command is invalid")
        try:
            with self._pool.connection() as connection:
                with connection.transaction():
                    publication = connection.execute(
                        """
                        INSERT INTO conversation_turn_publications (
                            run_id,
                            session_id,
                            turn_digest,
                            created_at
                        ) VALUES (%s, %s, %s, %s)
                        ON CONFLICT (run_id) DO NOTHING
                        RETURNING run_id
                        """,
                        (
                            command.run_id,
                            command.session_id,
                            command.digest,
                            _aware_utc(self._clock()),
                        ),
                    ).fetchone()
                    if publication is None:
                        existing = connection.execute(
                            """
                            SELECT session_id, turn_digest
                            FROM conversation_turn_publications
                            WHERE run_id = %s
                            """,
                            (command.run_id,),
                        ).fetchone()
                        if existing is None:
                            raise StoreUnavailableError()
                        if (
                            existing["session_id"] != command.session_id
                            or existing["turn_digest"].strip() != command.digest
                        ):
                            raise MemoryTurnConflictError()
                        return PublishTurnResult(created=False)

                    row = connection.execute(
                        """
                        INSERT INTO memory_message_sequences (
                            session_id,
                            next_sequence
                        ) VALUES (%s, 3)
                        ON CONFLICT (session_id) DO UPDATE
                        SET next_sequence =
                            memory_message_sequences.next_sequence + 2
                        RETURNING next_sequence - 2 AS first_sequence
                        """,
                        (command.session_id,),
                    ).fetchone()
                    if row is None:
                        raise StoreUnavailableError()
                    first_sequence = row["first_sequence"]
                    connection.execute(
                        """
                        INSERT INTO conversation_messages (
                            session_id,
                            sequence,
                            role,
                            content,
                            name,
                            tool_call_id
                        ) VALUES
                            (%s, %s, %s, %s, %s, %s),
                            (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            command.session_id,
                            first_sequence,
                            command.user_message.role,
                            command.user_message.content,
                            command.user_message.name,
                            command.user_message.tool_call_id,
                            command.session_id,
                            first_sequence + 1,
                            command.assistant_message.role,
                            command.assistant_message.content,
                            command.assistant_message.name,
                            command.assistant_message.tool_call_id,
                        ),
                    )
                    connection.execute(
                        """
                        DELETE FROM conversation_messages
                        WHERE session_id = %s
                          AND sequence <= %s
                        """,
                        (
                            command.session_id,
                            first_sequence + 1 - self._message_limit,
                        ),
                    )
                    return PublishTurnResult(created=True)
        except (MemoryTurnConflictError, StoreUnavailableError):
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def messages(self, session_id: str) -> tuple[Message, ...]:
        try:
            with self._pool.connection() as connection:
                rows = connection.execute(
                    """
                    SELECT role, content, name, tool_call_id
                    FROM conversation_messages
                    WHERE session_id = %s
                    ORDER BY sequence
                    """,
                    (session_id,),
                ).fetchall()
                return tuple(_row_to_message(row) for row in rows)
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def remember(
        self,
        *,
        owner_id: str,
        key: str,
        value: str,
        scope: MemoryScope,
        approved: bool,
    ) -> MemoryFact:
        if not approved:
            raise PermissionError("long-term memory requires explicit approval")
        checked_key = key.strip()
        checked_value = value.strip()
        if not checked_key or not checked_value:
            raise ValueError("memory key and value must not be empty")
        checked_scope = MemoryScope(scope)
        fact = MemoryFact(
            id=str(uuid4()),
            owner_id=owner_id,
            key=checked_key,
            value=checked_value,
            scope=checked_scope,
        )
        try:
            with self._pool.connection() as connection:
                with connection.transaction():
                    created_at = _aware_utc(self._clock())
                    connection.execute(
                        """
                        INSERT INTO conversation_memory_facts (
                            id,
                            owner_id,
                            key,
                            value,
                            scope,
                            version,
                            created_at
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                        """,
                        (
                            fact.id,
                            fact.owner_id,
                            fact.key,
                            fact.value,
                            fact.scope.value,
                            fact.version,
                            created_at,
                        ),
                    )
                    _insert_fact_audit(
                        connection,
                        fact_id=fact.id,
                        owner_id=fact.owner_id,
                        version=fact.version,
                        action=MemoryFactAuditAction.CREATED,
                        value_digest=_fact_value_digest(fact.value),
                        created_at=created_at,
                    )
                    return fact
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        try:
            with self._pool.connection() as connection:
                rows = connection.execute(
                    """
                    SELECT id, owner_id, key, value, scope, version
                    FROM conversation_memory_facts
                    WHERE owner_id = %s AND deleted_at IS NULL
                    ORDER BY ordinal
                    """,
                    (owner_id,),
                ).fetchall()
                return tuple(_row_to_fact(row) for row in rows)
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def correct_fact(self, command: CorrectMemoryFact) -> MemoryFact:
        if not isinstance(command, CorrectMemoryFact):
            raise ValueError("correct memory fact command is invalid")
        if not command.approved:
            raise PermissionError("memory correction requires explicit approval")
        try:
            with self._pool.connection() as connection:
                with connection.transaction():
                    current = _select_owned_active_fact(
                        connection,
                        command.fact_id,
                        owner_id=command.owner_id,
                    )
                    if current.version != command.expected_version:
                        raise MemoryFactConflictError()
                    corrected = MemoryFact(
                        id=current.id,
                        owner_id=current.owner_id,
                        key=current.key,
                        value=command.value,
                        scope=current.scope,
                        version=current.version + 1,
                    )
                    row = connection.execute(
                        """
                        UPDATE conversation_memory_facts
                        SET value = %s, version = %s
                        WHERE id = %s
                          AND owner_id = %s
                          AND version = %s
                          AND deleted_at IS NULL
                        RETURNING id
                        """,
                        (
                            corrected.value,
                            corrected.version,
                            corrected.id,
                            corrected.owner_id,
                            current.version,
                        ),
                    ).fetchone()
                    if row is None:
                        raise StoreUnavailableError()
                    _insert_fact_audit(
                        connection,
                        fact_id=corrected.id,
                        owner_id=corrected.owner_id,
                        version=corrected.version,
                        action=MemoryFactAuditAction.CORRECTED,
                        value_digest=command.value_digest,
                        created_at=_aware_utc(self._clock()),
                    )
                    return corrected
        except (
            MemoryFactConflictError,
            MemoryFactNotFoundError,
            StoreUnavailableError,
        ):
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def delete_fact(
        self,
        command: DeleteMemoryFact,
    ) -> DeleteMemoryFactResult:
        if not isinstance(command, DeleteMemoryFact):
            raise ValueError("delete memory fact command is invalid")
        try:
            with self._pool.connection() as connection:
                with connection.transaction():
                    current = _select_owned_active_fact(
                        connection,
                        command.fact_id,
                        owner_id=command.owner_id,
                    )
                    if current.version != command.expected_version:
                        raise MemoryFactConflictError()
                    return self._delete_fact(
                        connection,
                        current,
                        deleted_at=_aware_utc(self._clock()),
                    )
        except (
            MemoryFactConflictError,
            MemoryFactNotFoundError,
            StoreUnavailableError,
        ):
            raise
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def fact_audit(
        self,
        fact_id: str,
        *,
        owner_id: str,
    ) -> tuple[MemoryFactAuditRecord, ...]:
        _require_identifier(fact_id, "fact_id")
        _require_identifier(owner_id, "owner_id")
        try:
            with self._pool.connection() as connection:
                rows = connection.execute(
                    """
                    SELECT fact_id, owner_id, version, action, value_digest
                    FROM conversation_memory_fact_audit
                    WHERE fact_id = %s AND owner_id = %s
                    ORDER BY version
                    """,
                    (fact_id, owner_id),
                ).fetchall()
                return tuple(_row_to_fact_audit(row) for row in rows)
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def forget(self, fact_id: str, *, owner_id: str) -> bool:
        try:
            with self._pool.connection() as connection:
                with connection.transaction():
                    row = connection.execute(
                        """
                        SELECT id, owner_id, key, value, scope, version
                        FROM conversation_memory_facts
                        WHERE id = %s
                          AND owner_id = %s
                          AND deleted_at IS NULL
                        FOR UPDATE
                        """,
                        (fact_id, owner_id),
                    ).fetchone()
                    if row is None:
                        return False
                    self._delete_fact(
                        connection,
                        _row_to_fact(row),
                        deleted_at=_aware_utc(self._clock()),
                    )
                    return True
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def _delete_fact(
        self,
        connection: Connection[DictRow],
        current: MemoryFact,
        *,
        deleted_at: datetime,
    ) -> DeleteMemoryFactResult:
        deleted_version = current.version + 1
        row = connection.execute(
            """
            UPDATE conversation_memory_facts
            SET key = '',
                value = '',
                version = %s,
                deleted_at = %s
            WHERE id = %s
              AND owner_id = %s
              AND version = %s
              AND deleted_at IS NULL
            RETURNING id
            """,
            (
                deleted_version,
                deleted_at,
                current.id,
                current.owner_id,
                current.version,
            ),
        ).fetchone()
        if row is None:
            raise StoreUnavailableError()
        _insert_fact_audit(
            connection,
            fact_id=current.id,
            owner_id=current.owner_id,
            version=deleted_version,
            action=MemoryFactAuditAction.DELETED,
            value_digest=_fact_value_digest(current.value),
            created_at=deleted_at,
        )
        return DeleteMemoryFactResult(
            fact_id=current.id,
            version=deleted_version,
        )


def _row_to_message(row: Mapping[str, Any]) -> Message:
    return Message(
        role=row["role"],
        content=row["content"],
        name=row["name"],
        tool_call_id=row["tool_call_id"],
    )


def _row_to_fact(row: Mapping[str, Any]) -> MemoryFact:
    return MemoryFact(
        id=row["id"],
        owner_id=row["owner_id"],
        key=row["key"],
        value=row["value"],
        scope=MemoryScope(row["scope"]),
        version=row["version"],
    )


def _row_to_fact_audit(row: Mapping[str, Any]) -> MemoryFactAuditRecord:
    return MemoryFactAuditRecord(
        fact_id=row["fact_id"],
        owner_id=row["owner_id"],
        version=row["version"],
        action=MemoryFactAuditAction(row["action"]),
        value_digest=row["value_digest"].strip(),
    )


def _select_owned_active_fact(
    connection: Connection[DictRow],
    fact_id: str,
    *,
    owner_id: str,
) -> MemoryFact:
    row = connection.execute(
        """
        SELECT id, owner_id, key, value, scope, version
        FROM conversation_memory_facts
        WHERE id = %s
          AND owner_id = %s
          AND deleted_at IS NULL
        FOR UPDATE
        """,
        (fact_id, owner_id),
    ).fetchone()
    if row is None:
        raise MemoryFactNotFoundError()
    return _row_to_fact(row)


def _insert_fact_audit(
    connection: Connection[DictRow],
    *,
    fact_id: str,
    owner_id: str,
    version: int,
    action: MemoryFactAuditAction,
    value_digest: str,
    created_at: datetime,
) -> None:
    connection.execute(
        """
        INSERT INTO conversation_memory_fact_audit (
            fact_id,
            owner_id,
            version,
            action,
            value_digest,
            created_at
        ) VALUES (%s, %s, %s, %s, %s, %s)
        """,
        (
            fact_id,
            owner_id,
            version,
            action.value,
            value_digest,
            created_at,
        ),
    )


def _aware_utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError("memory clock must return a timezone-aware datetime")
    return value.astimezone(UTC)


__all__ = ["PostgresMemoryStore"]
