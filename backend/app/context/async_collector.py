from __future__ import annotations

import asyncio

from backend.app.domain import Message
from backend.app.knowledge.rag import KnowledgeBase
from backend.app.memory.store import MemoryFact
from backend.app.skills.context import SkillContextBuilder
from backend.app.stores.async_facade import AsyncMemoryStore
from backend.app.stores.base import StoreError

from .collector import (
    CollectedContext,
    ContextCollectionError,
    ContextCollectionInput,
    ContextSourceCollector,
    ContextSummarizer,
    _validate_rag_limit,
)


_DEFAULT_MEMORY_TIMEOUT_MS = 5_000


class AsyncMemoryContextSourceCollector:
    """Read Memory asynchronously before using process-local context sources."""

    def __init__(
        self,
        *,
        memory_store: AsyncMemoryStore,
        knowledge_base: KnowledgeBase,
        skill_context_builder: SkillContextBuilder,
        summarizer: ContextSummarizer | None = None,
        rag_limit: int = 3,
        memory_timeout_ms: int = _DEFAULT_MEMORY_TIMEOUT_MS,
    ) -> None:
        _validate_rag_limit(rag_limit)
        if (
            not isinstance(memory_timeout_ms, int)
            or isinstance(memory_timeout_ms, bool)
            or memory_timeout_ms < 1
        ):
            raise ValueError("memory_timeout_ms must be a positive integer")
        self._memory_store = memory_store
        self._knowledge_base = knowledge_base
        self._skill_context_builder = skill_context_builder
        self._summarizer = summarizer
        self._rag_limit = rag_limit
        self._memory_timeout = memory_timeout_ms / 1_000

    async def collect(
        self,
        request: ContextCollectionInput,
    ) -> CollectedContext:
        if not isinstance(request, ContextCollectionInput):
            raise ContextCollectionError("context_collection_input_invalid")

        snapshot = await self._load_memory(request)
        collector = ContextSourceCollector(
            memory_store=snapshot,
            knowledge_base=self._knowledge_base,
            skill_context_builder=self._skill_context_builder,
            summarizer=self._summarizer,
            rag_limit=self._rag_limit,
        )
        return collector.collect(request)

    async def _load_memory(
        self,
        request: ContextCollectionInput,
    ) -> _ContextMemorySnapshot:
        try:
            async with asyncio.timeout(self._memory_timeout):
                messages = await self._memory_store.messages(request.session_id)
                facts = await self._memory_store.facts(request.owner_id)
        except TimeoutError:
            raise ContextCollectionError("memory_context_timeout") from None
        except StoreError as error:
            code = (
                "memory_context_timeout"
                if error.code == "store_operation_timeout"
                else "memory_context_unavailable"
            )
            raise ContextCollectionError(code) from None

        return _ContextMemorySnapshot(
            owner_id=request.owner_id,
            session_id=request.session_id,
            messages=messages,
            facts=facts,
        )


class _ContextMemorySnapshot:
    """Request-scoped, non-blocking MemoryStore view over async read results."""

    def __init__(
        self,
        *,
        owner_id: str,
        session_id: str,
        messages: tuple[Message, ...],
        facts: tuple[MemoryFact, ...],
    ) -> None:
        self._owner_id = owner_id
        self._session_id = session_id
        self._messages = messages
        self._facts = facts

    def messages(self, session_id: str) -> tuple[Message, ...]:
        if session_id != self._session_id:
            raise ContextCollectionError("context_owner_mismatch")
        return self._messages

    def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        if owner_id != self._owner_id:
            raise ContextCollectionError("context_owner_mismatch")
        return self._facts


__all__ = ["AsyncMemoryContextSourceCollector"]
