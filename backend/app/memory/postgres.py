from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from psycopg import Connection, Error as PsycopgError
from psycopg.rows import DictRow
from psycopg_pool import ConnectionPool, PoolTimeout

from backend.app.domain import Message
from backend.app.memory.store import MemoryFact, MemoryScope
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
                connection.execute(
                    """
                    INSERT INTO conversation_memory_facts (
                        id,
                        owner_id,
                        key,
                        value,
                        scope,
                        created_at
                    ) VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    (
                        fact.id,
                        fact.owner_id,
                        fact.key,
                        fact.value,
                        fact.scope.value,
                        _aware_utc(self._clock()),
                    ),
                )
                return fact
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        try:
            with self._pool.connection() as connection:
                rows = connection.execute(
                    """
                    SELECT id, owner_id, key, value, scope
                    FROM conversation_memory_facts
                    WHERE owner_id = %s
                    ORDER BY ordinal
                    """,
                    (owner_id,),
                ).fetchall()
                return tuple(_row_to_fact(row) for row in rows)
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None

    def forget(self, fact_id: str, *, owner_id: str) -> bool:
        try:
            with self._pool.connection() as connection:
                row = connection.execute(
                    """
                    DELETE FROM conversation_memory_facts
                    WHERE id = %s AND owner_id = %s
                    RETURNING id
                    """,
                    (fact_id, owner_id),
                ).fetchone()
                return row is not None
        except (PsycopgError, PoolTimeout):
            raise StoreUnavailableError() from None


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
