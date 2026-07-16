from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import uuid4

from backend.app.domain import Message


class MemoryScope(StrEnum):
    SESSION = "session"
    USER = "user"


@dataclass(frozen=True)
class MemoryFact:
    id: str
    owner_id: str
    key: str
    value: str
    scope: MemoryScope


class ConversationMemory:
    """Separates message history from explicitly approved long-term facts."""

    def __init__(self, *, message_limit: int = 20) -> None:
        if message_limit < 1:
            raise ValueError("message_limit must be at least 1")
        self._message_limit = message_limit
        self._messages: dict[str, list[Message]] = {}
        self._facts: dict[str, MemoryFact] = {}

    def append_message(self, session_id: str, message: Message) -> None:
        messages = self._messages.setdefault(session_id, [])
        messages.append(message)
        del messages[:-self._message_limit]

    def messages(self, session_id: str) -> tuple[Message, ...]:
        return tuple(self._messages.get(session_id, []))

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
        if not key.strip() or not value.strip():
            raise ValueError("memory key and value must not be empty")
        fact = MemoryFact(
            id=str(uuid4()),
            owner_id=owner_id,
            key=key.strip(),
            value=value.strip(),
            scope=scope,
        )
        self._facts[fact.id] = fact
        return fact

    def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        return tuple(fact for fact in self._facts.values() if fact.owner_id == owner_id)

    def forget(self, fact_id: str, *, owner_id: str) -> bool:
        fact = self._facts.get(fact_id)
        if fact is None or fact.owner_id != owner_id:
            return False
        del self._facts[fact_id]
        return True
