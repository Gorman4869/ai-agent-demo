from __future__ import annotations

import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from backend.app.deployment_seed import (
    DeploymentSeedReport,
    initialize_deployment_knowledge,
    main,
)
from backend.app.settings import Settings, SettingsError


class _KnowledgeBase:
    def __init__(self) -> None:
        self.initialized = 0
        self.seeded_documents: list[object] = []

    def initialize_schema(self) -> tuple[int, ...]:
        self.initialized += 1
        return (1,)

    def seed(self, document: object) -> int:
        self.seeded_documents.append(document)
        return 2


class DeploymentSeedTest(unittest.TestCase):
    def test_initializes_and_seeds_the_fixed_offline_knowledge_document(self) -> None:
        dsn = "postgresql://private-user:private-pass@postgres/private-db"
        settings = Settings.from_environment(
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": dsn,
            }
        )
        knowledge_base = _KnowledgeBase()

        report = initialize_deployment_knowledge(
            settings,
            knowledge_base=knowledge_base,
        )

        self.assertEqual((1,), report.migration_versions)
        self.assertEqual("agent-course", report.document_id)
        self.assertEqual(2, report.chunk_count)
        self.assertEqual(1, knowledge_base.initialized)
        self.assertEqual(1, len(knowledge_base.seeded_documents))
        self.assertNotIn(dsn, repr(report))
        self.assertNotIn(dsn, json.dumps(report.to_record()))

    def test_rejects_online_or_wrong_dimension_deployment_seed(self) -> None:
        environments = (
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": "postgresql://course@postgres/course",
                "AI_AGENT_EMBEDDING_PROVIDER": "openai",
                "AI_AGENT_EMBEDDING_MODEL": "configured-model",
                "AI_AGENT_EMBEDDING_REVISION": "configured-revision",
                "OPENAI_API_KEY": "configured-key",
                "AI_AGENT_ONLINE_ENABLED": "true",
            },
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": "postgresql://course@postgres/course",
                "AI_AGENT_EMBEDDING_DIMENSIONS": "4",
            },
        )

        for environment in environments:
            with self.subTest(environment=environment):
                settings = Settings.from_environment(environment)
                with self.assertRaises(SettingsError):
                    initialize_deployment_knowledge(
                        settings,
                        knowledge_base=_KnowledgeBase(),
                    )

    def test_main_returns_content_free_configuration_failure(self) -> None:
        secret = "postgresql://private-user:private-pass@postgres/private-db"
        output = io.StringIO()

        with (
            patch(
                "backend.app.deployment_seed.Settings.from_environment",
                side_effect=SettingsError(secret),
            ),
            redirect_stdout(output),
        ):
            exit_code = main()

        self.assertEqual(1, exit_code)
        self.assertEqual(
            {"status": "failed", "error_code": "configuration_invalid"},
            json.loads(output.getvalue()),
        )
        self.assertNotIn(secret, output.getvalue())

    def test_main_prints_only_the_reviewed_success_record(self) -> None:
        report = DeploymentSeedReport(
            migration_versions=(1,),
            document_id="agent-course",
            chunk_count=2,
        )
        output = io.StringIO()

        with (
            patch(
                "backend.app.deployment_seed.Settings.from_environment",
                return_value=Settings.from_environment({}),
            ),
            patch(
                "backend.app.deployment_seed.initialize_deployment_knowledge",
                return_value=report,
            ),
            redirect_stdout(output),
        ):
            exit_code = main()

        self.assertEqual(0, exit_code)
        self.assertEqual(report.to_record(), json.loads(output.getvalue()))


if __name__ == "__main__":
    unittest.main()
