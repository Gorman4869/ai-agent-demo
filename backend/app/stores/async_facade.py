from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import Any, Protocol

from backend.app.domain import Message
from backend.app.memory import (
    MemoryFact,
    MemoryScope,
    MemoryStore,
    PublishTurn,
    PublishTurnResult,
)
from backend.app.tools import (
    ApprovalDecision,
    ApprovalResponse,
    ApprovalStore,
    ToolApproval,
    ToolApprovalRequest,
    ToolApprovalResolution,
    copy_tool_arguments,
)


class AsyncApprovalStore(Protocol):
    async def grant(
        self,
        *,
        principal_id: str,
        run_id: str | None = None,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        expires_at: datetime | None = None,
    ) -> ToolApproval: ...

    async def request(
        self,
        *,
        run_id: str,
        principal_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        expires_in: timedelta | None = None,
    ) -> ToolApprovalRequest: ...

    async def resolve(
        self,
        *,
        approval_id: str,
        run_id: str,
        principal_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments_digest: str,
        decision: ApprovalResponse | str,
    ) -> ToolApprovalResolution: ...

    async def get_resolution(
        self,
        *,
        approval_id: str,
        run_id: str,
        principal_id: str,
    ) -> ToolApprovalResolution | None: ...

    async def approved_arguments(
        self,
        resolution: ToolApprovalResolution,
    ) -> dict[str, Any]: ...

    async def consume(
        self,
        *,
        principal_id: str,
        run_id: str | None = None,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> ApprovalDecision: ...


class AsyncMemoryStore(Protocol):
    async def append_message(self, session_id: str, message: Message) -> None: ...

    async def publish_turn(self, command: PublishTurn) -> PublishTurnResult: ...

    async def messages(self, session_id: str) -> tuple[Message, ...]: ...

    async def remember(
        self,
        *,
        owner_id: str,
        key: str,
        value: str,
        scope: MemoryScope,
        approved: bool,
    ) -> MemoryFact: ...

    async def facts(self, owner_id: str) -> tuple[MemoryFact, ...]: ...

    async def forget(self, fact_id: str, *, owner_id: str) -> bool: ...


class AsyncLocalApprovalStore:
    """Async view over a non-blocking process-local ApprovalStore."""

    def __init__(self, store: ApprovalStore) -> None:
        self._store = store

    async def grant(
        self,
        *,
        principal_id: str,
        run_id: str | None = None,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        expires_at: datetime | None = None,
    ) -> ToolApproval:
        return self._store.grant(
            principal_id=principal_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=copy_tool_arguments(arguments),
            expires_at=expires_at,
        )

    async def request(
        self,
        *,
        run_id: str,
        principal_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
        expires_in: timedelta | None = None,
    ) -> ToolApprovalRequest:
        return self._store.request(
            run_id=run_id,
            principal_id=principal_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=copy_tool_arguments(arguments),
            expires_in=expires_in,
        )

    async def resolve(
        self,
        *,
        approval_id: str,
        run_id: str,
        principal_id: str,
        tool_call_id: str,
        tool_name: str,
        arguments_digest: str,
        decision: ApprovalResponse | str,
    ) -> ToolApprovalResolution:
        return self._store.resolve(
            approval_id=approval_id,
            run_id=run_id,
            principal_id=principal_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments_digest=arguments_digest,
            decision=decision,
        )

    async def get_resolution(
        self,
        *,
        approval_id: str,
        run_id: str,
        principal_id: str,
    ) -> ToolApprovalResolution | None:
        return self._store.get_resolution(
            approval_id=approval_id,
            run_id=run_id,
            principal_id=principal_id,
        )

    async def approved_arguments(
        self,
        resolution: ToolApprovalResolution,
    ) -> dict[str, Any]:
        return self._store.approved_arguments(resolution)

    async def consume(
        self,
        *,
        principal_id: str,
        run_id: str | None = None,
        tool_call_id: str,
        tool_name: str,
        arguments: Mapping[str, Any],
    ) -> ApprovalDecision:
        return self._store.consume(
            principal_id=principal_id,
            run_id=run_id,
            tool_call_id=tool_call_id,
            tool_name=tool_name,
            arguments=copy_tool_arguments(arguments),
        )


class AsyncLocalMemoryStore:
    """Async view over a non-blocking process-local MemoryStore."""

    def __init__(self, store: MemoryStore) -> None:
        self._store = store

    async def append_message(self, session_id: str, message: Message) -> None:
        self._store.append_message(session_id, message)

    async def publish_turn(self, command: PublishTurn) -> PublishTurnResult:
        return self._store.publish_turn(command)

    async def messages(self, session_id: str) -> tuple[Message, ...]:
        return self._store.messages(session_id)

    async def remember(
        self,
        *,
        owner_id: str,
        key: str,
        value: str,
        scope: MemoryScope,
        approved: bool,
    ) -> MemoryFact:
        return self._store.remember(
            owner_id=owner_id,
            key=key,
            value=value,
            scope=scope,
            approved=approved,
        )

    async def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        return self._store.facts(owner_id)

    async def forget(self, fact_id: str, *, owner_id: str) -> bool:
        return self._store.forget(fact_id, owner_id=owner_id)


__all__ = [
    "AsyncApprovalStore",
    "AsyncLocalApprovalStore",
    "AsyncLocalMemoryStore",
    "AsyncMemoryStore",
]
