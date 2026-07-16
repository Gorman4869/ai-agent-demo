from __future__ import annotations

import json
import os
import socket
import unittest
from unittest.mock import Mock, patch

from fastapi.testclient import TestClient

from backend.app.container import ApplicationContainer
from backend.app.knowledge import InMemoryKnowledgeBase
from backend.app.main import create_app
from backend.app.memory import ConversationMemory
from backend.app.security import StaticTokenAuthenticator
from backend.app.services import InMemoryRunService
from backend.app.settings import Settings
from backend.app.settings import SettingsError


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
        self.assertIsInstance(container.knowledge_base, InMemoryKnowledgeBase)
        self.assertIsInstance(container.memory, ConversationMemory)
        self.assertIsInstance(container.authenticator, StaticTokenAuthenticator)

    def test_explicit_dependencies_are_preserved(self) -> None:
        settings = Settings.from_environment({})
        run_service = InMemoryRunService()
        knowledge_base = InMemoryKnowledgeBase()
        memory = ConversationMemory()
        authenticator = StaticTokenAuthenticator()

        container = ApplicationContainer.create(
            settings=settings,
            run_service=run_service,
            knowledge_base=knowledge_base,
            memory=memory,
            authenticator=authenticator,
        )

        self.assertIs(settings, container.settings)
        self.assertIs(run_service, container.run_service)
        self.assertIs(knowledge_base, container.knowledge_base)
        self.assertIs(memory, container.memory)
        self.assertIs(authenticator, container.authenticator)

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

        container = ApplicationContainer.create(settings=settings)

        self.assertNotIn(secret, repr(container))

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

        knowledge_base.add.assert_not_called()


if __name__ == "__main__":
    unittest.main()
