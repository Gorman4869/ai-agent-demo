from __future__ import annotations

import json
import os
import socket
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

from fastapi.testclient import TestClient

from backend.app.agent.graph_runtime import LangGraphRuntime
from backend.app.agent.sdk_runtime import OpenAIAgentsRuntime
from backend.app.application_lifecycle import (
    ApplicationAdmissionState,
    ApplicationLifecycleState,
)
from backend.app.container import ApplicationContainer
from backend.app.domain.run import RunRecord, RunStatus
from backend.app.integrations.mcp import McpClientState
from backend.app.knowledge import InMemoryKnowledgeBase
from backend.app.main import create_app
from backend.app.memory import ConversationMemory
from backend.app.security import StaticTokenAuthenticator
from backend.app.services import InMemoryRunService, RunCoordinator
from backend.app.settings import Settings
from backend.app.settings import SettingsError
from backend.app.skills import SkillAwareRuntime
from backend.app.stores import (
    AsyncLocalApprovalStore,
    AsyncLocalMemoryStore,
    InMemoryEventStore,
    InMemoryRunStore,
)
from backend.app.tools import InMemoryApprovalStore


class ApplicationContainerTest(unittest.TestCase):
    def test_default_container_is_offline_and_constructs_local_adapters(self) -> None:
        with (
            patch.dict(
                os.environ,
                {
                    "OPENAI_API_KEY": "inactive-host-secret",
                    "OPENAI_MODEL": "configured-model",
                },
                clear=True,
            ),
            patch.object(
                socket,
                "create_connection",
                side_effect=AssertionError("default container attempted network access"),
            ),
            patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("default container attempted network access"),
            ),
        ):
            container = ApplicationContainer.create()

        self.assertEqual("manual", container.settings.runtime)
        self.assertFalse(container.settings.online_provider_enabled)
        self.assertIsInstance(container.run_service, InMemoryRunService)
        self.assertIsInstance(container.run_store, InMemoryRunStore)
        self.assertIsInstance(container.event_store, InMemoryEventStore)
        self.assertIsInstance(container.runtimes["manual"], SkillAwareRuntime)
        self.assertNotIn("agents_sdk", container.runtimes)
        self.assertIsInstance(container.run_coordinator, RunCoordinator)
        self.assertEqual(McpClientState.CREATED, container.mcp_clients.state)
        self.assertEqual((), container.mcp_clients.connected_server_ids)
        self.assertIsInstance(container.knowledge_base, InMemoryKnowledgeBase)
        self.assertIsInstance(container.memory, ConversationMemory)
        self.assertIsInstance(container.authenticator, StaticTokenAuthenticator)

    def test_explicit_dependencies_are_preserved(self) -> None:
        settings = Settings.from_environment({})
        run_service = InMemoryRunService()
        run_store = InMemoryRunStore()
        event_store = InMemoryEventStore(run_store)
        knowledge_base = InMemoryKnowledgeBase()
        memory = ConversationMemory()
        authenticator = StaticTokenAuthenticator()
        runtime = Mock()

        container = ApplicationContainer.create(
            settings=settings,
            run_service=run_service,
            run_store=run_store,
            event_store=event_store,
            runtimes={"manual": runtime},
            knowledge_base=knowledge_base,
            memory=memory,
            authenticator=authenticator,
        )

        self.assertIs(settings, container.settings)
        self.assertIs(run_service, container.run_service)
        self.assertIs(run_store, container.run_store)
        self.assertIs(event_store, container.event_store)
        self.assertIs(runtime, container.runtimes["manual"])
        self.assertIs(knowledge_base, container.knowledge_base)
        self.assertIs(memory, container.memory)
        self.assertIs(authenticator, container.authenticator)

    def test_explicit_stores_must_be_provided_as_a_pair(self) -> None:
        run_store = InMemoryRunStore()

        with self.assertRaisesRegex(ValueError, "provided together"):
            ApplicationContainer.create(
                settings=Settings.from_environment({}),
                event_store=InMemoryEventStore(run_store),
            )
        with self.assertRaisesRegex(ValueError, "provided together"):
            ApplicationContainer.create(
                settings=Settings.from_environment({}),
                run_store=run_store,
            )

    def test_create_app_accepts_container_and_exposes_it_on_app_state(self) -> None:
        container = ApplicationContainer.create(
            settings=Settings.from_environment({})
        )

        app = create_app(container=container)

        self.assertIs(container, app.state.container)
        with TestClient(app) as client:
            self.assertEqual({"status": "ok"}, client.get("/health").json())

    def test_create_app_accepts_explicit_settings(self) -> None:
        settings = Settings.from_environment(
            {"AI_AGENT_RUNTIME": "langgraph"}
        )

        app = create_app(settings=settings)

        self.assertIs(settings, app.state.container.settings)
        self.assertIsInstance(
            app.state.container.runtimes["langgraph"].delegate,
            LangGraphRuntime,
        )

    def test_create_app_keeps_existing_dependency_injection_compatible(self) -> None:
        authenticator = StaticTokenAuthenticator()

        app = create_app(authenticator=authenticator)

        self.assertIs(authenticator, app.state.container.authenticator)

    def test_create_app_keeps_legacy_positional_injection_compatible(self) -> None:
        run_service = InMemoryRunService()
        knowledge_base = InMemoryKnowledgeBase()
        memory = ConversationMemory()
        authenticator = StaticTokenAuthenticator()

        app = create_app(run_service, knowledge_base, memory, authenticator)

        self.assertIs(run_service, app.state.container.run_service)
        self.assertIs(knowledge_base, app.state.container.knowledge_base)
        self.assertIs(memory, app.state.container.memory)
        self.assertIs(authenticator, app.state.container.authenticator)

    def test_container_repr_does_not_expose_provider_secret(self) -> None:
        secret = "container-secret-must-not-leak"
        settings = Settings.from_environment(
            {
                "AI_AGENT_RUNTIME": "agents_sdk",
                "AI_AGENT_MODEL_PROVIDER": "openai",
                "AI_AGENT_ONLINE_ENABLED": "true",
                "OPENAI_API_KEY": secret,
                "OPENAI_MODEL": "configured-model",
            }
        )

        with (
            patch(
                "backend.app.agent.sdk_runtime.openai.AsyncOpenAI"
            ) as openai_client,
            patch.object(
                socket,
                "create_connection",
                side_effect=AssertionError("container attempted network access"),
            ),
            patch.object(
                socket.socket,
                "connect",
                side_effect=AssertionError("container attempted network access"),
            ),
        ):
            container = ApplicationContainer.create(settings=settings)

        openai_client.assert_not_called()
        self.assertNotIn(secret, repr(container))
        self.assertIsInstance(
            container.runtimes["agents_sdk"].delegate,
            OpenAIAgentsRuntime,
        )
        self.assertIsInstance(container.runtimes["manual"], SkillAwareRuntime)

    def test_container_cannot_be_mixed_with_legacy_overrides(self) -> None:
        container = ApplicationContainer.create(
            settings=Settings.from_environment({})
        )

        with self.assertRaisesRegex(ValueError, "container cannot be combined"):
            create_app(container=container, run_service=InMemoryRunService())

        with self.assertRaisesRegex(ValueError, "container cannot be combined"):
            create_app(
                container=container,
                settings=Settings.from_environment({}),
            )

    def test_postgres_container_requires_async_open(self) -> None:
        settings = Settings.from_environment(
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": (
                    "postgresql://course@127.0.0.1:55432/agent_test"
                ),
            }
        )

        with self.assertRaisesRegex(ValueError, "requires await"):
            ApplicationContainer.create(settings=settings)

    def test_default_authenticator_still_reads_legacy_auth_environment(self) -> None:
        token = "configured-test-token"
        auth_config = json.dumps(
            {
                token: {
                    "principal_id": "configured-user",
                    "roles": ["observer"],
                }
            }
        )
        with patch.dict(
            os.environ,
            {"AI_AGENT_DEMO_AUTH_JSON": auth_config},
            clear=True,
        ):
            container = ApplicationContainer.create()

        principal = container.authenticator.authenticate(f"Bearer {token}")
        self.assertEqual("configured-user", principal.principal_id)
        self.assertEqual(frozenset({"observer"}), principal.roles)

    def test_invalid_environment_fails_before_knowledge_seed_side_effect(self) -> None:
        knowledge_base = Mock()
        with patch.dict(
            "os.environ",
            {
                "AI_AGENT_MODEL_PROVIDER": "openai",
                "AI_AGENT_ONLINE_ENABLED": "true",
            },
            clear=True,
        ):
            with self.assertRaises(SettingsError):
                create_app(knowledge_base=knowledge_base)

        knowledge_base.seed.assert_not_called()


class ApplicationContainerStorePairTest(unittest.IsolatedAsyncioTestCase):
    async def test_postgres_open_failure_preserves_error_and_closes_composition(
        self,
    ) -> None:
        settings = Settings.from_environment(
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": (
                    "postgresql://course@127.0.0.1:55432/agent_test"
                ),
            }
        )
        composition = SimpleNamespace(
            persistence=SimpleNamespace(
                approval_store=InMemoryApprovalStore(),
            ),
            close=AsyncMock(side_effect=RuntimeError("cleanup failed")),
        )

        with (
            patch(
                "backend.app.postgres_execution."
                "PostgresExecutionComposition.open",
                new=AsyncMock(return_value=composition),
            ),
            patch(
                "backend.app.container."
                "StaticTokenAuthenticator.from_environment",
                side_effect=ValueError("invalid auth config"),
            ),
            self.assertLogs("application.container", level="ERROR") as logs,
        ):
            with self.assertRaisesRegex(ValueError, "invalid auth config"):
                await ApplicationContainer.open(settings=settings)

        composition.close.assert_awaited_once()
        self.assertEqual(
            ["ERROR:application.container:PostgreSQL container startup cleanup failed"],
            logs.output,
        )

    async def test_postgres_open_binds_composition_and_async_facades(self) -> None:
        dsn = "postgresql://course@127.0.0.1:55432/agent_test"
        settings = Settings.from_environment(
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": dsn,
            }
        )
        run_store = InMemoryRunStore()
        event_store = InMemoryEventStore(run_store)
        memory = ConversationMemory()
        approvals = InMemoryApprovalStore()

        persistence = SimpleNamespace(
            run_store=run_store,
            event_store=event_store,
            memory_store=memory,
            approval_store=approvals,
            async_memory_store=AsyncLocalMemoryStore(memory),
            async_approval_store=AsyncLocalApprovalStore(approvals),
        )
        coordinator = Mock(spec=RunCoordinator)
        composition = SimpleNamespace(
            persistence=persistence,
            coordinator=coordinator,
            close=AsyncMock(),
        )
        open_composition = AsyncMock(return_value=composition)

        with (
            patch.dict(os.environ, {}, clear=True),
            patch(
                "backend.app.postgres_execution."
                "PostgresExecutionComposition.open",
                new=open_composition,
            ),
        ):
            container = await ApplicationContainer.open(settings=settings)

        self.assertIs(run_store, container.run_store)
        self.assertIs(event_store, container.event_store)
        self.assertIs(memory, container.memory)
        self.assertIs(approvals, container.approval_store)
        self.assertIs(
            persistence.async_memory_store,
            container.async_memory_store,
        )
        self.assertIs(
            persistence.async_approval_store,
            container.async_approval_store,
        )
        self.assertIs(coordinator, container.run_coordinator)
        self.assertEqual(ApplicationLifecycleState.CREATED, container.lifecycle_state)
        self.assertEqual(ApplicationAdmissionState.CREATED, container.admission.state)
        self.assertNotIn(dsn, repr(container))
        open_composition.assert_awaited_once()
        self.assertEqual(dsn, open_composition.await_args.args[0])

        await container.start()
        self.assertEqual(ApplicationLifecycleState.RUNNING, container.lifecycle_state)
        self.assertEqual(
            ApplicationAdmissionState.ACCEPTING,
            container.admission.state,
        )
        await container.close()

        composition.close.assert_awaited_once()
        self.assertEqual(ApplicationLifecycleState.CLOSED, container.lifecycle_state)
        self.assertEqual(McpClientState.CLOSED, container.mcp_clients.state)

    async def test_default_event_store_is_bound_to_default_run_store(self) -> None:
        now = datetime(2026, 7, 16, 4, 0, tzinfo=UTC)
        container = ApplicationContainer.create(
            settings=Settings.from_environment({})
        )
        run = RunRecord.create(
            run_id="container-run",
            session_id="container-session",
            owner_id="container-owner",
            runtime="manual",
            input_text="hello",
            idempotency_key="container-key",
            created_at=now,
        )

        await container.run_store.create(run)
        appended = await container.event_store.append(
            event_id="container-event",
            run_id=run.id,
            owner_id=run.owner_id,
            event_type="model.started",
            data={},
        )

        self.assertTrue(appended.created)
        self.assertEqual(1, appended.event.sequence)

    async def test_default_coordinator_uses_the_container_store_pair_offline(
        self,
    ) -> None:
        now = datetime(2026, 7, 16, 4, 0, tzinfo=UTC)
        container = ApplicationContainer.create(
            settings=Settings.from_environment({})
        )
        run = RunRecord.create(
            run_id="coordinator-run",
            session_id="coordinator-session",
            owner_id="coordinator-owner",
            runtime="manual",
            input_text="hello",
            idempotency_key="coordinator-key",
            created_at=now,
        )
        await container.run_store.create(run)

        completed = await container.run_coordinator.execute(
            run.id,
            owner_id=run.owner_id,
        )
        events = await container.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertEqual(RunStatus.COMPLETED, completed.status)
        self.assertEqual("Mock Agent 收到：hello", completed.answer)
        self.assertEqual(
            ["run.started", "run.completed"],
            [event.type for event in events],
        )


if __name__ == "__main__":
    unittest.main()
