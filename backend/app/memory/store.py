from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import StrEnum
from threading import Lock
from typing import Protocol
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


class MemoryTurnConflictError(RuntimeError):
    code = "memory_turn_conflict"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True)
class PublishTurn:
    run_id: str
    session_id: str = field(repr=False)
    user_message: Message = field(repr=False)
    assistant_message: Message = field(repr=False)

    def __post_init__(self) -> None:
        _require_identifier(self.run_id, "run_id")
        _require_identifier(self.session_id, "session_id")
        _require_turn_message(self.user_message, role="user")
        _require_turn_message(self.assistant_message, role="assistant")

    @property
    def digest(self) -> str:
        payload = {
            "assistant": _message_payload(self.assistant_message),
            "schema": "conversation-turn-v1",
            "session_id": self.session_id,
            "user": _message_payload(self.user_message),
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True)
class PublishTurnResult:
    created: bool


class MemoryStore(Protocol):
    def append_message(self, session_id: str, message: Message) -> None: ...

    def publish_turn(self, command: PublishTurn) -> PublishTurnResult: ...

    def messages(self, session_id: str) -> tuple[Message, ...]: ...

    def remember(
        self,
        *,
        owner_id: str,
        key: str,
        value: str,
        scope: MemoryScope,
        approved: bool,
    ) -> MemoryFact: ...

    def facts(self, owner_id: str) -> tuple[MemoryFact, ...]: ...

    def forget(self, fact_id: str, *, owner_id: str) -> bool: ...


class ConversationMemory:
    """Separates message history from explicitly approved long-term facts."""

    def __init__(self, *, message_limit: int = 20) -> None:
        if message_limit < 1:
            raise ValueError("message_limit must be at least 1")
        self._message_limit = message_limit
        self._message_lock = Lock()
        self._messages: dict[str, list[Message]] = {}
        self._published_turns: dict[str, tuple[str, str]] = {}
        self._facts: dict[str, MemoryFact] = {}

    def append_message(self, session_id: str, message: Message) -> None:
        with self._message_lock:
            messages = self._messages.setdefault(session_id, [])
            messages.append(message)
            del messages[:-self._message_limit]

    def publish_turn(self, command: PublishTurn) -> PublishTurnResult:
        if not isinstance(command, PublishTurn):
            raise ValueError("publish turn command is invalid")
        binding = (command.session_id, command.digest)
        with self._message_lock:
            existing = self._published_turns.get(command.run_id)
            if existing is not None:
                if existing != binding:
                    raise MemoryTurnConflictError()
                return PublishTurnResult(created=False)

            messages = [
                *self._messages.get(command.session_id, ()),
                command.user_message,
                command.assistant_message,
            ][-self._message_limit :]
            self._messages[command.session_id] = messages
            self._published_turns[command.run_id] = binding
            return PublishTurnResult(created=True)

    def messages(self, session_id: str) -> tuple[Message, ...]:
        with self._message_lock:
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
        checked_scope = MemoryScope(scope)
        fact = MemoryFact(
            id=str(uuid4()),
            owner_id=owner_id,
            key=key.strip(),
            value=value.strip(),
            scope=checked_scope,
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


def _require_identifier(value: object, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
    ):
        raise ValueError(f"{label} has an invalid format")


def _require_turn_message(message: object, *, role: str) -> None:
    if (
        not isinstance(message, Message)
        or message.role != role
        or not isinstance(message.content, str)
        or message.name is not None
        or message.tool_call_id is not None
    ):
        raise ValueError(f"publish turn requires a plain {role} message")


def _message_payload(message: Message) -> dict[str, str | None]:
    return {
        "content": message.content,
        "name": message.name,
        "role": message.role,
        "tool_call_id": message.tool_call_id,
    }
