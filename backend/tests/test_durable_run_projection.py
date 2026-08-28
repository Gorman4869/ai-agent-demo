from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from backend.app.agent import (
    CancellationToken,
    RuntimeContextIdentity,
    RuntimeControl,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.container import ApplicationContainer
from backend.app.context import (
    AsyncContextAwareRuntime,
    AsyncMemoryContextSourceCollector,
    ContextAwareRuntime,
    ContextSourceCollector,
    RuntimeIdentityBindingFactory,
)
from backend.app.domain.run import RunRecord, RunStatus
from backend.app.knowledge import Document, InMemoryKnowledgeBase
from backend.app.main import create_app
from backend.app.memory import ConversationMemory
from backend.app.security import Principal, StaticTokenAuthenticator
from backend.app.services import RunCoordinator
from backend.app.settings import Settings
from backend.app.skills import default_skill_context_builder
from backend.app.stores import InMemoryEventStore, InMemoryRunStore, StartCommit, TerminalCommit


class ContextCitationEventTest(unittest.IsolatedAsyncioTestCase):
    async def test_selected_rag_citations_and_answer_share_one_run(self) -> None:
        run_store = InMemoryRunStore()
        event_store = InMemoryEventStore(run_store)
        run = _run("citation-run")
        await run_store.create(run)
        runtime = ContextAwareRuntime(
            _ResultRuntime(RuntimeResult(status=RunStatus.COMPLETED, answer="done")),
            binding_factory=RuntimeIdentityBindingFactory(),
            collector=_collector(),
        )
        coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={"manual": runtime},
            run_timeout_ms=1_000,
        )

        completed = await coordinator.execute(run.id, owner_id=run.owner_id)
        events = await event_store.list_for_run(run.id, owner_id=run.owner_id)

        self.assertEqual(RunStatus.COMPLETED, completed.status)
        self.assertEqual(
            ["run.started", "rag.citations", "run.completed"],
            [event.type for event in events],
        )
        citation = events[1].data["citations"][0]
        self.assertEqual("Agent Guide", citation["title"])
        self.assertNotIn("document_id", citation)
        self.assertNotIn(run.owner_id, repr(events[1]))

    async def test_context_rag_failure_emits_safe_event_then_terminal_failure(self) -> None:
        run_store = InMemoryRunStore()
        event_store = InMemoryEventStore(run_store)
        run = _run("citation-failure-run")
        await run_store.create(run)
        runtime = ContextAwareRuntime(
            _ResultRuntime(RuntimeResult(status=RunStatus.COMPLETED, answer="unused")),
            binding_factory=RuntimeIdentityBindingFactory(),
            collector=ContextSourceCollector(
                memory_store=ConversationMemory(),
                knowledge_base=_InvalidKnowledgeBase(),
                skill_context_builder=default_skill_context_builder(),
            ),
        )
        coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={"manual": runtime},
            run_timeout_ms=1_000,
        )

        failed = await coordinator.execute(run.id, owner_id=run.owner_id)
        events = await event_store.list_for_run(run.id, owner_id=run.owner_id)

        self.assertEqual(RunStatus.FAILED, failed.status)
        self.assertEqual("context_unavailable", failed.failure.code)
        self.assertEqual(
            ["run.started", "context.failed", "run.failed"],
            [event.type for event in events],
        )
        self.assertEqual({"code": "context_unavailable"}, events[1].data)

    async def test_async_context_runtime_emits_the_same_citation_contract(self) -> None:
        runtime = AsyncContextAwareRuntime(
            _ResultRuntime(RuntimeResult(status=RunStatus.COMPLETED, answer="done")),
            binding_factory=RuntimeIdentityBindingFactory(),
            collector=AsyncMemoryContextSourceCollector(
                memory_store=_EmptyAsyncMemoryStore(),
                knowledge_base=_knowledge_base(),
                skill_context_builder=default_skill_context_builder(),
            ),
        )
        emitted = []

        async def collect(event) -> None:
            emitted.append(event)

        result = await runtime.run(
            RuntimeRequest(
                run_id="async-citation-run",
                input_text="How does an Agent use tools?",
                context_identity=RuntimeContextIdentity(
                    owner_id="projection-owner",
                    session_id="projection-session",
                ),
            ),
            emit=collect,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual(["rag.citations"], [event.type for event in emitted])
        self.assertEqual("Agent Guide", emitted[0].data["citations"][0]["title"])


class DurableRunProjectionApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.owner = Principal("projection-owner")
        self.container = ApplicationContainer.create(
            settings=Settings.from_environment({}),
            authenticator=StaticTokenAuthenticator(
                {"projection-token": self.owner}
            ),
        )
        self.client = TestClient(create_app(container=self.container))

    def test_snapshot_projects_citations_and_usage_from_the_same_run(self) -> None:
        run = asyncio.run(self._seed_completed_run("projection-api-run"))

        response = self.client.get(
            f"/api/durable/runs/{run.id}",
            headers={"Authorization": "Bearer projection-token"},
        )

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual("done", payload["answer"])
        self.assertEqual(
            [
                {
                    "title": "Agent Guide",
                    "source": "docs/agent.md",
                    "excerpt": "Agents use trusted tools.",
                    "score": 0.8,
                }
            ],
            payload["citations"],
        )
        self.assertEqual(
            {
                "input_tokens": 3,
                "output_tokens": 4,
                "total_tokens": 7,
                "estimated_cost_usd": None,
            },
            payload["usage"],
        )

    def test_snapshot_keeps_last_valid_projection_when_later_event_is_invalid(self) -> None:
        run = asyncio.run(self._seed_completed_run("projection-invalid-run"))

        response = self.client.get(
            f"/api/durable/runs/{run.id}",
            headers={"Authorization": "Bearer projection-token"},
        )

        self.assertEqual(200, response.status_code)
        self.assertEqual(7, response.json()["usage"]["total_tokens"])

    async def _seed_completed_run(self, run_id: str) -> RunRecord:
        run = _run(run_id, owner_id=self.owner.principal_id)
        await self.container.run_store.create(run)
        started = await self.container.event_store.commit_start(
            StartCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=0,
                event_id=f"{run_id}-started",
                event_data={"status": "running", "runtime": "manual"},
            )
        )
        await self.container.event_store.append(
            event_id=f"{run_id}-citations",
            run_id=run.id,
            owner_id=run.owner_id,
            event_type="rag.citations",
            data={
                "citations": [
                    {
                        "title": "Agent Guide",
                        "source": "docs/agent.md",
                        "excerpt": "Agents use trusted tools.",
                        "score": 0.8,
                    }
                ]
            },
        )
        await self.container.event_store.append(
            event_id=f"{run_id}-usage",
            run_id=run.id,
            owner_id=run.owner_id,
            event_type="model.usage",
            data={
                "scope": "run",
                "input_tokens": 3,
                "output_tokens": 4,
                "total_tokens": 7,
                "estimated_cost_usd": None,
            },
        )
        await self.container.event_store.append(
            event_id=f"{run_id}-invalid-usage",
            run_id=run.id,
            owner_id=run.owner_id,
            event_type="model.usage",
            data={
                "scope": "run",
                "input_tokens": 3,
                "output_tokens": 4,
                "total_tokens": 8,
                "estimated_cost_usd": 1.0,
            },
        )
        await self.container.event_store.commit_terminal(
            TerminalCommit(
                run_id=run.id,
                owner_id=run.owner_id,
                expected_version=started.record.version,
                target_status=RunStatus.COMPLETED,
                event_id=f"{run_id}-completed",
                event_data={"status": "completed", "answer": "done"},
                answer="done",
            )
        )
        return run


def _collector() -> ContextSourceCollector:
    return ContextSourceCollector(
        memory_store=ConversationMemory(),
        knowledge_base=_knowledge_base(),
        skill_context_builder=default_skill_context_builder(),
    )


def _knowledge_base() -> InMemoryKnowledgeBase:
    knowledge_base = InMemoryKnowledgeBase()
    knowledge_base.add(
        Document(
            id="agent-guide",
            title="Agent Guide",
            content="Agents use trusted tools.",
            source="docs/agent.md",
        )
    )
    return knowledge_base


def _run(run_id: str, *, owner_id: str = "projection-owner") -> RunRecord:
    return RunRecord.create(
        run_id=run_id,
        session_id=f"{run_id}-session",
        owner_id=owner_id,
        runtime="manual",
        input_text="How does an Agent use tools?",
        idempotency_key=f"{run_id}-key",
        created_at=datetime.now(UTC),
    )


class _ResultRuntime:
    def __init__(self, result: RuntimeResult) -> None:
        self._result = result

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit, control
        return self._result


class _InvalidKnowledgeBase:
    def search(self, query: str, *, limit: int = 3):
        del query, limit
        return ("invalid search result",)


class _EmptyAsyncMemoryStore:
    async def messages(self, session_id: str):
        del session_id
        return ()

    async def facts(self, owner_id: str):
        del owner_id
        return ()
