from __future__ import annotations

import asyncio
import json
import unittest

from backend.app.context import (
    AsyncMemoryContextSourceCollector,
    ContextCollectionError,
    ContextCollectionInput,
    ContextSource,
    ContextSystemConstraint,
)
from backend.app.domain import Message
from backend.app.knowledge import Document, InMemoryKnowledgeBase, SearchResult
from backend.app.memory import (
    ConversationMemory,
    MemoryFact,
    MemoryScope,
)
from backend.app.skills import SkillContextBuilder, SkillDefinition
from backend.app.stores import AsyncLocalMemoryStore
from backend.app.stores.base import StoreUnavailableError
from backend.app.stores.postgres_async import (
    AsyncPostgresMemoryStore,
    PostgresSyncStoreTimeoutError,
)


class AsyncMemoryContextSourceCollectorTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_async_local_memory_collects_and_assembles_context(
        self,
    ) -> None:
        memory = ConversationMemory()
        memory.append_message(
            "session-1",
            Message(role="user", content="Recent async context."),
        )
        memory.remember(
            owner_id="owner-1",
            key="preferred_language",
            value="Chinese",
            scope=MemoryScope.USER,
            approved=True,
        )
        knowledge = InMemoryKnowledgeBase()
        knowledge.add(
            Document(
                id="async-context-doc",
                title="Async Context",
                content="Async memory evidence belongs in bounded context.",
                source="course-fixture",
            )
        )
        collector = _collector(
            AsyncLocalMemoryStore(memory),
            knowledge=knowledge,
            skills=(_skill("research-summary"),),
        )

        collected = await collector.collect(
            ContextCollectionInput(
                owner_id="owner-1",
                session_id="session-1",
                query="Use research-summary for async memory evidence.",
                system_constraints=(
                    ContextSystemConstraint(
                        id="async-memory-policy-v1",
                        content="Keep application policy server-owned.",
                    ),
                ),
            )
        )
        payload = _payload(collected.assemble().prompt_context)

        self.assertEqual(
            ["system", "skill", "memory", "recent", "rag"],
            [fragment["source"] for fragment in payload["fragments"]],
        )
        self.assertEqual(
            [
                "trusted_policy",
                "application_guidance",
                "owner_scoped_data",
                "user_content",
                "untrusted_evidence",
            ],
            [fragment["trust"] for fragment in payload["fragments"]],
        )

    async def test_owner_and_session_reads_remain_isolated(self) -> None:
        memory = ConversationMemory()
        for suffix in ("a", "b"):
            memory.append_message(
                f"session-{suffix}",
                Message(role="user", content=f"recent-{suffix}-private"),
            )
            memory.remember(
                owner_id=f"owner-{suffix}",
                key=f"fact-{suffix}",
                value=f"value-{suffix}-private",
                scope=MemoryScope.USER,
                approved=True,
            )
        collector = _collector(AsyncLocalMemoryStore(memory))

        rendered = []
        for suffix in ("a", "b"):
            collected = await collector.collect(
                ContextCollectionInput(
                    owner_id=f"owner-{suffix}",
                    session_id=f"session-{suffix}",
                    query="isolated context",
                )
            )
            rendered.append(collected.assemble().prompt_context or "")

        self.assertIn("recent-a-private", rendered[0])
        self.assertIn("value-a-private", rendered[0])
        self.assertNotIn("recent-b-private", rendered[0])
        self.assertNotIn("value-b-private", rendered[0])
        self.assertIn("recent-b-private", rendered[1])
        self.assertIn("value-b-private", rendered[1])
        self.assertNotIn("recent-a-private", rendered[1])
        self.assertNotIn("value-a-private", rendered[1])

    async def test_cross_owner_fact_fails_before_downstream_sources(self) -> None:
        memory = _StaticAsyncMemoryStore(
            facts=(
                MemoryFact(
                    id="fact-private",
                    owner_id="other-owner",
                    key="private-key",
                    value="private-value",
                    scope=MemoryScope.USER,
                ),
            )
        )
        knowledge = _RecordingKnowledgeBase()
        resolver = _RecordingResolver()
        collector = _collector(
            memory,
            knowledge=knowledge,
            resolver=resolver,
        )

        with self.assertRaises(ContextCollectionError) as raised:
            await collector.collect(_request())

        self.assertEqual("context_owner_mismatch", raised.exception.code)
        self.assertEqual([], knowledge.queries)
        self.assertEqual([], resolver.queries)

    async def test_message_store_failure_stops_before_fact_read(self) -> None:
        memory = _FailingAsyncMemoryStore(fail_on="messages")
        knowledge = _RecordingKnowledgeBase()
        collector = _collector(memory, knowledge=knowledge)

        with self.assertRaises(ContextCollectionError) as raised:
            await collector.collect(_request())

        self.assertEqual("memory_context_unavailable", raised.exception.code)
        self.assertEqual(1, memory.message_calls)
        self.assertEqual(0, memory.fact_calls)
        self.assertEqual([], knowledge.queries)

    async def test_fact_store_failure_stops_before_downstream_sources(self) -> None:
        memory = _FailingAsyncMemoryStore(fail_on="facts")
        knowledge = _RecordingKnowledgeBase()
        collector = _collector(memory, knowledge=knowledge)

        with self.assertRaises(ContextCollectionError) as raised:
            await collector.collect(_request())

        self.assertEqual("memory_context_unavailable", raised.exception.code)
        self.assertEqual(1, memory.message_calls)
        self.assertEqual(1, memory.fact_calls)
        self.assertEqual([], knowledge.queries)

    async def test_memory_timeout_is_stable_and_cancels_pending_read(self) -> None:
        memory = _BlockingAsyncMemoryStore()
        knowledge = _RecordingKnowledgeBase()
        collector = _collector(
            memory,
            knowledge=knowledge,
            memory_timeout_ms=10,
        )

        with self.assertRaises(ContextCollectionError) as raised:
            await collector.collect(_request())

        self.assertEqual("memory_context_timeout", raised.exception.code)
        self.assertTrue(memory.cancelled.is_set())
        self.assertEqual(0, memory.fact_calls)
        self.assertEqual([], knowledge.queries)
        self.assertNotIn("owner-1", repr(raised.exception))
        self.assertNotIn("session-1", repr(raised.exception))

    async def test_store_timeout_is_normalized_without_result_details(self) -> None:
        memory = _StoreTimeoutAsyncMemoryStore()

        with self.assertRaises(ContextCollectionError) as raised:
            await _collector(memory).collect(_request())

        self.assertEqual("memory_context_timeout", raised.exception.code)
        self.assertNotIn("result_unknown", repr(raised.exception))

    async def test_caller_cancellation_propagates_without_downstream_work(
        self,
    ) -> None:
        memory = _BlockingAsyncMemoryStore()
        knowledge = _RecordingKnowledgeBase()
        collector = _collector(memory, knowledge=knowledge)
        operation = asyncio.create_task(collector.collect(_request()))
        await memory.started.wait()

        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation

        self.assertTrue(memory.cancelled.is_set())
        self.assertEqual(0, memory.fact_calls)
        self.assertEqual([], knowledge.queries)

    async def test_postgres_facade_is_used_without_direct_sync_store_call(
        self,
    ) -> None:
        sync_store = _ForbiddenSyncMemoryStore()
        bridge = _SnapshotBridge()
        collector = _collector(
            AsyncPostgresMemoryStore(sync_store, bridge),
        )

        collected = await collector.collect(_request())
        payload = _payload(collected.assemble().prompt_context)

        self.assertEqual(["messages", "facts"], bridge.operations)
        self.assertEqual(0, sync_store.calls)
        self.assertEqual(
            [ContextSource.MEMORY.value, ContextSource.RECENT.value],
            [fragment["source"] for fragment in payload["fragments"]],
        )

    async def test_invalid_memory_payload_fails_before_downstream_sources(
        self,
    ) -> None:
        memory = _StaticAsyncMemoryStore(messages=(object(),))
        knowledge = _RecordingKnowledgeBase()
        collector = _collector(memory, knowledge=knowledge)

        with self.assertRaises(ContextCollectionError) as raised:
            await collector.collect(_request())

        self.assertEqual("context_source_invalid", raised.exception.code)
        self.assertEqual([], knowledge.queries)

    async def test_configuration_rejects_invalid_timeout_and_rag_limit(
        self,
    ) -> None:
        for timeout in (0, -1, True):
            with self.subTest(timeout=timeout):
                with self.assertRaises(ValueError):
                    _collector(
                        _StaticAsyncMemoryStore(),
                        memory_timeout_ms=timeout,
                    )
        for rag_limit in (0, 17, True):
            with self.subTest(rag_limit=rag_limit):
                with self.assertRaises(ValueError):
                    _collector(
                        _StaticAsyncMemoryStore(),
                        rag_limit=rag_limit,
                    )


class _StaticResolver:
    def __init__(self, skills: tuple[SkillDefinition, ...] = ()) -> None:
        self._skills = skills

    def resolve(self, query: str) -> tuple[SkillDefinition, ...]:
        del query
        return self._skills


class _RecordingResolver:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def resolve(self, query: str) -> tuple[SkillDefinition, ...]:
        self.queries.append(query)
        return ()


class _RecordingKnowledgeBase:
    def __init__(self) -> None:
        self.queries: list[str] = []

    def search(self, query: str, *, limit: int = 3) -> tuple[SearchResult, ...]:
        del limit
        self.queries.append(query)
        return ()


class _StaticAsyncMemoryStore:
    def __init__(
        self,
        *,
        messages: tuple[Message, ...] = (),
        facts: tuple[MemoryFact, ...] = (),
    ) -> None:
        self._messages = messages
        self._facts = facts

    async def messages(self, session_id: str) -> tuple[Message, ...]:
        del session_id
        return self._messages

    async def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        del owner_id
        return self._facts


class _FailingAsyncMemoryStore:
    def __init__(self, *, fail_on: str) -> None:
        self._fail_on = fail_on
        self.message_calls = 0
        self.fact_calls = 0

    async def messages(self, session_id: str) -> tuple[Message, ...]:
        del session_id
        self.message_calls += 1
        if self._fail_on == "messages":
            raise StoreUnavailableError()
        return ()

    async def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        del owner_id
        self.fact_calls += 1
        if self._fail_on == "facts":
            raise StoreUnavailableError()
        return ()


class _BlockingAsyncMemoryStore:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.release = asyncio.Event()
        self.fact_calls = 0

    async def messages(self, session_id: str) -> tuple[Message, ...]:
        del session_id
        self.started.set()
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return ()

    async def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        del owner_id
        self.fact_calls += 1
        return ()


class _StoreTimeoutAsyncMemoryStore:
    async def messages(self, session_id: str) -> tuple[Message, ...]:
        del session_id
        raise PostgresSyncStoreTimeoutError(result_unknown=True)

    async def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        del owner_id
        raise AssertionError("facts must not run after message timeout")


class _ForbiddenSyncMemoryStore:
    def __init__(self) -> None:
        self.calls = 0

    def messages(self, session_id: str) -> tuple[Message, ...]:
        del session_id
        self.calls += 1
        raise AssertionError("sync messages called on event loop")

    def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        del owner_id
        self.calls += 1
        raise AssertionError("sync facts called on event loop")


class _SnapshotBridge:
    def __init__(self) -> None:
        self.operations: list[str] = []

    async def run(self, operation, *args, **kwargs):
        del args, kwargs
        self.operations.append(operation.__name__)
        if operation.__name__ == "messages":
            return (Message(role="user", content="bridge recent"),)
        if operation.__name__ == "facts":
            return (
                MemoryFact(
                    id="bridge-fact",
                    owner_id="owner-1",
                    key="bridge-key",
                    value="bridge-value",
                    scope=MemoryScope.USER,
                ),
            )
        raise AssertionError("unexpected bridge operation")


def _collector(
    memory_store,
    *,
    knowledge=None,
    resolver=None,
    skills: tuple[SkillDefinition, ...] = (),
    rag_limit: int = 3,
    memory_timeout_ms: int = 5_000,
) -> AsyncMemoryContextSourceCollector:
    return AsyncMemoryContextSourceCollector(
        memory_store=memory_store,
        knowledge_base=knowledge or InMemoryKnowledgeBase(),
        skill_context_builder=SkillContextBuilder(
            resolver or _StaticResolver(skills)
        ),
        rag_limit=rag_limit,
        memory_timeout_ms=memory_timeout_ms,
    )


def _request() -> ContextCollectionInput:
    return ContextCollectionInput(
        owner_id="owner-1",
        session_id="session-1",
        query="async context query",
    )


def _skill(name: str) -> SkillDefinition:
    return SkillDefinition(
        name=name,
        description="Controlled async context Skill.",
        instructions="Use bounded source evidence.",
    )


def _payload(prompt_context: str | None) -> dict[str, object]:
    assert prompt_context is not None
    return json.loads(prompt_context[prompt_context.index("{") :])
