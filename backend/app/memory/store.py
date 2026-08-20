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
    owner_id: str = field(repr=False)
    key: str = field(repr=False)
    value: str = field(repr=False)
    scope: MemoryScope
    version: int = 0


class MemoryFactAuditAction(StrEnum):
    CREATED = "created"
    CORRECTED = "corrected"
    DELETED = "deleted"


@dataclass(frozen=True)
class MemoryFactAuditRecord:
    fact_id: str
    owner_id: str = field(repr=False)
    version: int
    action: MemoryFactAuditAction
    value_digest: str


class MemoryFactConflictError(RuntimeError):
    code = "memory_fact_conflict"

    def __init__(self) -> None:
        super().__init__(self.code)


class MemoryFactNotFoundError(RuntimeError):
    code = "memory_fact_not_found"

    def __init__(self) -> None:
        super().__init__(self.code)


@dataclass(frozen=True)
class CorrectMemoryFact:
    fact_id: str
    owner_id: str = field(repr=False)
    expected_version: int
    value: str = field(repr=False)
    approved: bool = field(repr=False)

    def __post_init__(self) -> None:
        _require_identifier(self.fact_id, "fact_id")
        _require_identifier(self.owner_id, "owner_id")
        _require_fact_version(self.expected_version)
        if not isinstance(self.approved, bool):
            raise ValueError("approved must be a boolean")
        object.__setattr__(self, "value", _normalize_fact_value(self.value))

    @property
    def value_digest(self) -> str:
        return _fact_value_digest(self.value)


@dataclass(frozen=True)
class DeleteMemoryFact:
    fact_id: str
    owner_id: str = field(repr=False)
    expected_version: int

    def __post_init__(self) -> None:
        _require_identifier(self.fact_id, "fact_id")
        _require_identifier(self.owner_id, "owner_id")
        _require_fact_version(self.expected_version)


@dataclass(frozen=True)
class DeleteMemoryFactResult:
    fact_id: str
    version: int


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

    def correct_fact(self, command: CorrectMemoryFact) -> MemoryFact: ...

    def delete_fact(
        self,
        command: DeleteMemoryFact,
    ) -> DeleteMemoryFactResult: ...

    def fact_audit(
        self,
        fact_id: str,
        *,
        owner_id: str,
    ) -> tuple[MemoryFactAuditRecord, ...]: ...

    def forget(self, fact_id: str, *, owner_id: str) -> bool: ...


@dataclass(frozen=True)
class _MemoryFactState:
    owner_id: str
    version: int
    fact: MemoryFact | None


class ConversationMemory:
    """Separates message history from explicitly approved long-term facts."""

    def __init__(self, *, message_limit: int = 20) -> None:
        if message_limit < 1:
            raise ValueError("message_limit must be at least 1")
        self._message_limit = message_limit
        self._message_lock = Lock()
        self._messages: dict[str, list[Message]] = {}
        self._published_turns: dict[str, tuple[str, str]] = {}
        self._fact_lock = Lock()
        self._facts: dict[str, _MemoryFactState] = {}
        self._fact_audits: dict[str, list[MemoryFactAuditRecord]] = {}

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
        with self._fact_lock:
            self._facts[fact.id] = _MemoryFactState(
                owner_id=fact.owner_id,
                version=fact.version,
                fact=fact,
            )
            self._fact_audits[fact.id] = [
                _fact_audit_record(fact, MemoryFactAuditAction.CREATED)
            ]
        return fact

    def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        with self._fact_lock:
            return tuple(
                state.fact
                for state in self._facts.values()
                if state.owner_id == owner_id and state.fact is not None
            )

    def correct_fact(self, command: CorrectMemoryFact) -> MemoryFact:
        if not isinstance(command, CorrectMemoryFact):
            raise ValueError("correct memory fact command is invalid")
        if not command.approved:
            raise PermissionError("memory correction requires explicit approval")
        with self._fact_lock:
            state = self._owned_active_fact(
                command.fact_id,
                owner_id=command.owner_id,
            )
            if state.version != command.expected_version:
                raise MemoryFactConflictError()
            current = state.fact
            if current is None:
                raise MemoryFactNotFoundError()
            corrected = MemoryFact(
                id=current.id,
                owner_id=current.owner_id,
                key=current.key,
                value=command.value,
                scope=current.scope,
                version=current.version + 1,
            )
            self._facts[current.id] = _MemoryFactState(
                owner_id=current.owner_id,
                version=corrected.version,
                fact=corrected,
            )
            self._fact_audits[current.id].append(
                _fact_audit_record(
                    corrected,
                    MemoryFactAuditAction.CORRECTED,
                )
            )
            return corrected

    def delete_fact(
        self,
        command: DeleteMemoryFact,
    ) -> DeleteMemoryFactResult:
        if not isinstance(command, DeleteMemoryFact):
            raise ValueError("delete memory fact command is invalid")
        with self._fact_lock:
            state = self._owned_active_fact(
                command.fact_id,
                owner_id=command.owner_id,
            )
            if state.version != command.expected_version:
                raise MemoryFactConflictError()
            return self._delete_fact_locked(state)

    def fact_audit(
        self,
        fact_id: str,
        *,
        owner_id: str,
    ) -> tuple[MemoryFactAuditRecord, ...]:
        _require_identifier(fact_id, "fact_id")
        _require_identifier(owner_id, "owner_id")
        with self._fact_lock:
            state = self._facts.get(fact_id)
            if state is None or state.owner_id != owner_id:
                return ()
            return tuple(self._fact_audits[fact_id])

    def forget(self, fact_id: str, *, owner_id: str) -> bool:
        with self._fact_lock:
            state = self._facts.get(fact_id)
            if (
                state is None
                or state.owner_id != owner_id
                or state.fact is None
            ):
                return False
            self._delete_fact_locked(state)
            return True

    def _owned_active_fact(
        self,
        fact_id: str,
        *,
        owner_id: str,
    ) -> _MemoryFactState:
        state = self._facts.get(fact_id)
        if (
            state is None
            or state.owner_id != owner_id
            or state.fact is None
        ):
            raise MemoryFactNotFoundError()
        return state

    def _delete_fact_locked(
        self,
        state: _MemoryFactState,
    ) -> DeleteMemoryFactResult:
        current = state.fact
        if current is None:
            raise MemoryFactNotFoundError()
        deleted_version = current.version + 1
        self._facts[current.id] = _MemoryFactState(
            owner_id=current.owner_id,
            version=deleted_version,
            fact=None,
        )
        self._fact_audits[current.id].append(
            MemoryFactAuditRecord(
                fact_id=current.id,
                owner_id=current.owner_id,
                version=deleted_version,
                action=MemoryFactAuditAction.DELETED,
                value_digest=_fact_value_digest(current.value),
            )
        )
        return DeleteMemoryFactResult(
            fact_id=current.id,
            version=deleted_version,
        )


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


def _require_fact_version(value: object) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("expected_version must be a non-negative integer")


def _normalize_fact_value(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("memory value must not be empty")
    return value.strip()


def _fact_value_digest(value: str) -> str:
    encoded = value.encode("utf-8")
    payload = f"memory-fact-value-v1:{len(encoded)}:".encode("ascii") + encoded
    return hashlib.sha256(payload).hexdigest()


def _fact_audit_record(
    fact: MemoryFact,
    action: MemoryFactAuditAction,
) -> MemoryFactAuditRecord:
    return MemoryFactAuditRecord(
        fact_id=fact.id,
        owner_id=fact.owner_id,
        version=fact.version,
        action=action,
        value_digest=_fact_value_digest(fact.value),
    )


def _message_payload(message: Message) -> dict[str, str | None]:
    return {
        "content": message.content,
        "name": message.name,
        "role": message.role,
        "tool_call_id": message.tool_call_id,
    }
