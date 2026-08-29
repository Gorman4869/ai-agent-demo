from __future__ import annotations

import unittest
from decimal import Decimal
from pathlib import Path

from pydantic import ValidationError

from backend.app.settings import (
    EmbeddingSettings,
    McpClientSettings,
    Settings,
    SettingsError,
)


class SettingsTest(unittest.TestCase):
    def test_defaults_are_offline_manual_mock_with_bounded_budgets(self) -> None:
        settings = Settings.from_environment({})

        self.assertEqual("manual", settings.runtime)
        self.assertEqual("mock", settings.model_provider)
        self.assertFalse(settings.online_enabled)
        self.assertFalse(settings.trace_include_sensitive)
        self.assertFalse(settings.online_provider_enabled)
        self.assertIsNone(settings.openai_api_key)
        self.assertIsNone(settings.openai_model)
        self.assertEqual(8, settings.budget.max_steps)
        self.assertEqual(8, settings.budget.max_model_calls)
        self.assertEqual(30_000, settings.budget.run_timeout_ms)
        self.assertEqual(20_000, settings.budget.model_timeout_ms)
        self.assertEqual(16_000, settings.budget.max_input_tokens)
        self.assertEqual(2_000, settings.budget.max_output_tokens)
        self.assertEqual(Decimal("0.25"), settings.budget.max_cost_usd)
        self.assertEqual(2, settings.budget.max_model_retries)
        self.assertEqual(100, settings.budget.model_retry_initial_delay_ms)
        self.assertEqual(2_000, settings.budget.model_retry_max_delay_ms)
        self.assertEqual(1, settings.budget.max_tool_retries)
        self.assertEqual(100, settings.budget.tool_retry_initial_delay_ms)
        self.assertEqual(1_000, settings.budget.tool_retry_max_delay_ms)
        self.assertEqual("offline", settings.embedding.provider)
        self.assertIsNone(settings.embedding.model)
        self.assertIsNone(settings.embedding.revision)
        self.assertEqual(3, settings.embedding.dimensions)
        self.assertEqual(32, settings.embedding.batch_size)
        self.assertEqual(256, settings.embedding.cache_max_entries)
        self.assertEqual(20_000, settings.embedding.request_timeout_ms)
        self.assertEqual(2, settings.embedding.max_retries)
        self.assertFalse(settings.online_embedding_enabled)
        self.assertEqual((), settings.mcp.server_ids)
        self.assertEqual(5_000, settings.mcp.startup_timeout_ms)
        self.assertEqual(5_000, settings.mcp.request_timeout_ms)
        self.assertEqual("memory", settings.persistence.backend)
        self.assertIsNone(settings.persistence.postgres_dsn)

    def test_postgres_requires_explicit_backend_and_valid_dsn(self) -> None:
        dsn = "postgresql://course@127.0.0.1:55432/agent_test"
        inactive = Settings.from_environment({"AI_AGENT_POSTGRES_DSN": dsn})
        enabled = Settings.from_environment(
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": dsn,
            }
        )

        self.assertEqual("memory", inactive.persistence.backend)
        self.assertEqual("postgres", enabled.persistence.backend)
        self.assertEqual(
            dsn,
            enabled.persistence.postgres_dsn.get_secret_value(),
        )

    def test_invalid_postgres_configuration_fails_closed(self) -> None:
        environments = (
            {"AI_AGENT_PERSISTENCE": "postgres"},
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": "not a postgres conninfo",
            },
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": "postgresql://bad\nvalue",
            },
            {"AI_AGENT_PERSISTENCE": "sqlite"},
        )

        for environment in environments:
            with self.subTest(environment=environment):
                with self.assertRaises(SettingsError):
                    Settings.from_environment(environment)

    def test_postgres_dsn_is_excluded_from_safe_outputs(self) -> None:
        dsn = "postgresql://private-user:private-pass@localhost/private-db"
        settings = Settings.from_environment(
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": dsn,
            }
        )

        self.assertNotIn(dsn, repr(settings))
        self.assertNotIn(dsn, settings.model_dump_json())
        self.assertNotIn(dsn, str(settings.safe_summary()))
        self.assertEqual(
            {
                "backend": "postgres",
                "postgres_dsn_configured": True,
            },
            settings.safe_summary()["persistence"],
        )

    def test_mcp_server_selectors_and_timeout_are_parsed(self) -> None:
        settings = Settings.from_environment(
            {
                "AI_AGENT_MCP_SERVERS": "python-knowledge, team-readonly",
                "AI_AGENT_MCP_STARTUP_TIMEOUT_MS": "7500",
                "AI_AGENT_MCP_REQUEST_TIMEOUT_MS": "9000",
            }
        )

        self.assertEqual(
            ("python-knowledge", "team-readonly"),
            settings.mcp.server_ids,
        )
        self.assertEqual(7_500, settings.mcp.startup_timeout_ms)
        self.assertEqual(9_000, settings.mcp.request_timeout_ms)

    def test_invalid_mcp_settings_fail_closed(self) -> None:
        environments = (
            {"AI_AGENT_MCP_SERVERS": "python-knowledge,"},
            {"AI_AGENT_MCP_SERVERS": "python-knowledge,python-knowledge"},
            {"AI_AGENT_MCP_SERVERS": "bad server"},
            {"AI_AGENT_MCP_SERVERS": "a,b,c,d,e,f,g,h,i"},
            {"AI_AGENT_MCP_STARTUP_TIMEOUT_MS": "99"},
            {"AI_AGENT_MCP_STARTUP_TIMEOUT_MS": "30001"},
            {"AI_AGENT_MCP_REQUEST_TIMEOUT_MS": "99"},
            {"AI_AGENT_MCP_REQUEST_TIMEOUT_MS": "30001"},
        )

        for environment in environments:
            with self.subTest(environment=environment):
                with self.assertRaises(SettingsError):
                    Settings.from_environment(environment)

        with self.assertRaises(ValidationError):
            McpClientSettings(server_ids=("bad\nserver",))

    def test_complete_openai_gate_is_accepted_without_running_provider(self) -> None:
        settings = Settings.from_environment(
            {
                "AI_AGENT_RUNTIME": "agents_sdk",
                "AI_AGENT_MODEL_PROVIDER": "openai",
                "AI_AGENT_ONLINE_ENABLED": "true",
                "OPENAI_API_KEY": "test-secret-value",
                "OPENAI_MODEL": "configured-model",
            }
        )

        self.assertTrue(settings.online_provider_enabled)
        self.assertEqual("agents_sdk", settings.runtime)
        self.assertEqual("configured-model", settings.openai_model)

    def test_openai_embedding_gate_is_independent_from_chat_runtime(self) -> None:
        settings = Settings.from_environment(
            {
                "AI_AGENT_ONLINE_ENABLED": "true",
                "OPENAI_API_KEY": "test-secret-value",
                "AI_AGENT_EMBEDDING_PROVIDER": "openai",
                "AI_AGENT_EMBEDDING_MODEL": "configured-embedding",
                "AI_AGENT_EMBEDDING_REVISION": "course-v1",
                "AI_AGENT_EMBEDDING_DIMENSIONS": "3",
                "AI_AGENT_EMBEDDING_BATCH_SIZE": "2",
                "AI_AGENT_EMBEDDING_CACHE_MAX_ENTRIES": "4",
                "AI_AGENT_EMBEDDING_REQUEST_TIMEOUT_MS": "1500",
                "AI_AGENT_EMBEDDING_MAX_RETRIES": "1",
            }
        )

        self.assertEqual("manual", settings.runtime)
        self.assertEqual("mock", settings.model_provider)
        self.assertFalse(settings.online_provider_enabled)
        self.assertTrue(settings.online_embedding_enabled)
        self.assertEqual("configured-embedding", settings.embedding.model)
        self.assertEqual("course-v1", settings.embedding.revision)
        self.assertEqual(2, settings.embedding.batch_size)
        self.assertEqual(4, settings.embedding.cache_max_entries)
        self.assertEqual(1_500, settings.embedding.request_timeout_ms)
        self.assertEqual(1, settings.embedding.max_retries)
        self.assertNotIn(
            "configured-embedding",
            str(settings.safe_summary()["embedding"]),
        )

    def test_embedding_labels_and_key_do_not_enable_inactive_provider(self) -> None:
        settings = Settings.from_environment(
            {
                "OPENAI_API_KEY": "inactive-host-secret",
                "AI_AGENT_EMBEDDING_MODEL": "configured-embedding",
                "AI_AGENT_EMBEDDING_REVISION": "course-v1",
            }
        )

        self.assertEqual("offline", settings.embedding.provider)
        self.assertFalse(settings.online_embedding_enabled)

    def test_langgraph_can_use_mock_without_online_access(self) -> None:
        settings = Settings.from_environment(
            {
                "AI_AGENT_RUNTIME": "langgraph",
                "AI_AGENT_MODEL_PROVIDER": "mock",
                "AI_AGENT_ONLINE_ENABLED": "false",
            }
        )

        self.assertFalse(settings.online_provider_enabled)

    def test_credentials_alone_do_not_enable_online_provider(self) -> None:
        settings = Settings.from_environment(
            {
                "OPENAI_API_KEY": "host-secret-that-must-remain-inactive",
                "OPENAI_MODEL": "configured-model",
            }
        )

        self.assertEqual("manual", settings.runtime)
        self.assertEqual("mock", settings.model_provider)
        self.assertFalse(settings.online_provider_enabled)

    def test_langgraph_can_use_explicit_openai_provider(self) -> None:
        settings = Settings.from_environment(
            {
                "AI_AGENT_RUNTIME": "langgraph",
                "AI_AGENT_MODEL_PROVIDER": "openai",
                "AI_AGENT_ONLINE_ENABLED": "true",
                "OPENAI_API_KEY": "test-secret-value",
                "OPENAI_MODEL": "configured-model",
            }
        )

        self.assertTrue(settings.online_provider_enabled)

    def test_settings_are_an_immutable_snapshot(self) -> None:
        environment = {"AI_AGENT_MAX_STEPS": "12"}
        settings = Settings.from_environment(environment)
        environment["AI_AGENT_MAX_STEPS"] = "20"

        self.assertEqual(12, settings.budget.max_steps)
        with self.assertRaises(ValidationError):
            settings.runtime = "langgraph"  # type: ignore[misc]

    def test_incomplete_or_inconsistent_online_gate_fails_closed(self) -> None:
        cases = {
            "switch disabled": {
                "AI_AGENT_RUNTIME": "agents_sdk",
                "AI_AGENT_MODEL_PROVIDER": "openai",
                "AI_AGENT_ONLINE_ENABLED": "false",
                "OPENAI_API_KEY": "test-secret-value",
                "OPENAI_MODEL": "configured-model",
            },
            "missing key": {
                "AI_AGENT_RUNTIME": "agents_sdk",
                "AI_AGENT_MODEL_PROVIDER": "openai",
                "AI_AGENT_ONLINE_ENABLED": "true",
                "OPENAI_MODEL": "configured-model",
            },
            "empty key": {
                "AI_AGENT_RUNTIME": "agents_sdk",
                "AI_AGENT_MODEL_PROVIDER": "openai",
                "AI_AGENT_ONLINE_ENABLED": "true",
                "OPENAI_API_KEY": "   ",
                "OPENAI_MODEL": "configured-model",
            },
            "missing model": {
                "AI_AGENT_RUNTIME": "agents_sdk",
                "AI_AGENT_MODEL_PROVIDER": "openai",
                "AI_AGENT_ONLINE_ENABLED": "true",
                "OPENAI_API_KEY": "test-secret-value",
            },
            "empty model": {
                "AI_AGENT_RUNTIME": "agents_sdk",
                "AI_AGENT_MODEL_PROVIDER": "openai",
                "AI_AGENT_ONLINE_ENABLED": "true",
                "OPENAI_API_KEY": "test-secret-value",
                "OPENAI_MODEL": "   ",
            },
            "manual runtime": {
                "AI_AGENT_RUNTIME": "manual",
                "AI_AGENT_MODEL_PROVIDER": "openai",
                "AI_AGENT_ONLINE_ENABLED": "true",
                "OPENAI_API_KEY": "test-secret-value",
                "OPENAI_MODEL": "configured-model",
            },
            "sdk with mock": {
                "AI_AGENT_RUNTIME": "agents_sdk",
                "AI_AGENT_MODEL_PROVIDER": "mock",
                "AI_AGENT_ONLINE_ENABLED": "false",
            },
            "online mock": {
                "AI_AGENT_RUNTIME": "manual",
                "AI_AGENT_MODEL_PROVIDER": "mock",
                "AI_AGENT_ONLINE_ENABLED": "true",
            },
        }

        for label, environment in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(SettingsError):
                    Settings.from_environment(environment)

    def test_incomplete_openai_embedding_gate_fails_closed(self) -> None:
        complete = {
            "AI_AGENT_ONLINE_ENABLED": "true",
            "OPENAI_API_KEY": "test-secret-value",
            "AI_AGENT_EMBEDDING_PROVIDER": "openai",
            "AI_AGENT_EMBEDDING_MODEL": "configured-embedding",
            "AI_AGENT_EMBEDDING_REVISION": "course-v1",
        }
        cases = {
            "switch disabled": {
                **complete,
                "AI_AGENT_ONLINE_ENABLED": "false",
            },
            "missing key": {
                key: value
                for key, value in complete.items()
                if key != "OPENAI_API_KEY"
            },
            "missing model": {
                key: value
                for key, value in complete.items()
                if key != "AI_AGENT_EMBEDDING_MODEL"
            },
            "missing revision": {
                key: value
                for key, value in complete.items()
                if key != "AI_AGENT_EMBEDDING_REVISION"
            },
        }

        for label, environment in cases.items():
            with self.subTest(label=label):
                with self.assertRaises(SettingsError):
                    Settings.from_environment(environment)

    def test_invalid_embedding_settings_fail_closed(self) -> None:
        cases = {
            "AI_AGENT_EMBEDDING_PROVIDER": ("other",),
            "AI_AGENT_EMBEDDING_MODEL": ("bad model", "x" * 201),
            "AI_AGENT_EMBEDDING_REVISION": ("bad\nrevision", "x" * 201),
            "AI_AGENT_EMBEDDING_DIMENSIONS": ("0", "32769", "many"),
            "AI_AGENT_EMBEDDING_BATCH_SIZE": ("0", "2049", "many"),
            "AI_AGENT_EMBEDDING_CACHE_MAX_ENTRIES": (
                "0",
                "100001",
                "many",
            ),
            "AI_AGENT_EMBEDDING_REQUEST_TIMEOUT_MS": (
                "99",
                "120001",
                "many",
            ),
            "AI_AGENT_EMBEDDING_MAX_RETRIES": ("-1", "6", "many"),
        }

        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(SettingsError):
                        Settings.from_environment({name: value})

        with self.assertRaises(ValidationError):
            EmbeddingSettings(model="bad model")

    def test_unknown_names_and_invalid_boolean_fail_closed(self) -> None:
        for environment in (
            {"AI_AGENT_RUNTIME": "other"},
            {"AI_AGENT_MODEL_PROVIDER": "other"},
            {"AI_AGENT_ONLINE_ENABLED": "sometimes"},
            {"AI_AGENT_TRACE_INCLUDE_SENSITIVE": "sometimes"},
            {"AI_AGENT_TRACE_INCLUDE_SENSITIVE": "true"},
        ):
            with self.subTest(environment=environment):
                with self.assertRaises(SettingsError):
                    Settings.from_environment(environment)

    def test_invalid_or_unbounded_budgets_fail_closed(self) -> None:
        cases = {
            "AI_AGENT_MAX_STEPS": ("0", "65", "many"),
            "AI_AGENT_MAX_MODEL_CALLS": ("0", "65", "many"),
            "AI_AGENT_RUN_TIMEOUT_MS": ("99", "120001", "none"),
            "AI_AGENT_MODEL_TIMEOUT_MS": ("99", "120001", "none"),
            "AI_AGENT_MAX_INPUT_TOKENS": ("0", "200001", "many"),
            "AI_AGENT_MAX_OUTPUT_TOKENS": ("0", "32001", "many"),
            "AI_AGENT_MAX_COST_USD": ("0", "10.01", "nan", "inf", "many"),
            "AI_AGENT_MAX_MODEL_RETRIES": ("-1", "6", "many"),
            "AI_AGENT_MODEL_RETRY_INITIAL_DELAY_MS": ("-1", "10001", "many"),
            "AI_AGENT_MODEL_RETRY_MAX_DELAY_MS": ("-1", "30001", "many"),
            "AI_AGENT_MAX_TOOL_RETRIES": ("-1", "4", "many"),
            "AI_AGENT_TOOL_RETRY_INITIAL_DELAY_MS": ("-1", "10001", "many"),
            "AI_AGENT_TOOL_RETRY_MAX_DELAY_MS": ("-1", "30001", "many"),
        }

        for name, values in cases.items():
            for value in values:
                with self.subTest(name=name, value=value):
                    with self.assertRaises(SettingsError):
                        Settings.from_environment({name: value})

        with self.assertRaises(SettingsError):
            Settings.from_environment(
                {
                    "AI_AGENT_RUN_TIMEOUT_MS": "1000",
                    "AI_AGENT_MODEL_TIMEOUT_MS": "1001",
                }
            )
        for environment in (
            {
                "AI_AGENT_MODEL_RETRY_INITIAL_DELAY_MS": "201",
                "AI_AGENT_MODEL_RETRY_MAX_DELAY_MS": "200",
            },
            {
                "AI_AGENT_TOOL_RETRY_INITIAL_DELAY_MS": "201",
                "AI_AGENT_TOOL_RETRY_MAX_DELAY_MS": "200",
            },
            {
                "AI_AGENT_RUN_TIMEOUT_MS": "1000",
                "AI_AGENT_MODEL_TIMEOUT_MS": "1000",
                "AI_AGENT_MODEL_RETRY_MAX_DELAY_MS": "1000",
                "AI_AGENT_TOOL_RETRY_MAX_DELAY_MS": "999",
            },
        ):
            with self.subTest(environment=environment):
                with self.assertRaises(SettingsError):
                    Settings.from_environment(environment)

    def test_custom_budget_boundaries_are_parsed(self) -> None:
        settings = Settings.from_environment(
            {
                "AI_AGENT_MAX_STEPS": "64",
                "AI_AGENT_MAX_MODEL_CALLS": "1",
                "AI_AGENT_RUN_TIMEOUT_MS": "120000",
                "AI_AGENT_MODEL_TIMEOUT_MS": "100",
                "AI_AGENT_MAX_INPUT_TOKENS": "200000",
                "AI_AGENT_MAX_OUTPUT_TOKENS": "32000",
                "AI_AGENT_MAX_COST_USD": "10",
                "AI_AGENT_MAX_MODEL_RETRIES": "0",
                "AI_AGENT_MODEL_RETRY_INITIAL_DELAY_MS": "0",
                "AI_AGENT_MODEL_RETRY_MAX_DELAY_MS": "0",
                "AI_AGENT_MAX_TOOL_RETRIES": "3",
                "AI_AGENT_TOOL_RETRY_INITIAL_DELAY_MS": "0",
                "AI_AGENT_TOOL_RETRY_MAX_DELAY_MS": "0",
            }
        )

        self.assertEqual(64, settings.budget.max_steps)
        self.assertEqual(1, settings.budget.max_model_calls)
        self.assertEqual(120_000, settings.budget.run_timeout_ms)
        self.assertEqual(100, settings.budget.model_timeout_ms)
        self.assertEqual(200_000, settings.budget.max_input_tokens)
        self.assertEqual(32_000, settings.budget.max_output_tokens)
        self.assertEqual(Decimal("10"), settings.budget.max_cost_usd)
        self.assertEqual(0, settings.budget.max_model_retries)
        self.assertEqual(0, settings.budget.model_retry_initial_delay_ms)
        self.assertEqual(0, settings.budget.model_retry_max_delay_ms)
        self.assertEqual(3, settings.budget.max_tool_retries)
        self.assertEqual(0, settings.budget.tool_retry_initial_delay_ms)
        self.assertEqual(0, settings.budget.tool_retry_max_delay_ms)

    def test_provider_identifiers_reject_control_characters_and_long_values(
        self,
    ) -> None:
        for name, value in (
            ("OPENAI_API_KEY", "bad\nkey"),
            ("OPENAI_API_KEY", "x" * 513),
            ("OPENAI_MODEL", "bad model"),
            ("OPENAI_MODEL", "bad\x00model"),
            ("OPENAI_MODEL", "x" * 201),
        ):
            with self.subTest(name=name):
                with self.assertRaises(SettingsError):
                    Settings.from_environment({name: value})

    def test_secret_is_excluded_from_repr_and_validation_errors(self) -> None:
        secret = "do-not-print-this-secret"
        settings = Settings.from_environment(
            {
                "AI_AGENT_RUNTIME": "agents_sdk",
                "AI_AGENT_MODEL_PROVIDER": "openai",
                "AI_AGENT_ONLINE_ENABLED": "true",
                "OPENAI_API_KEY": secret,
                "OPENAI_MODEL": "configured-model",
            }
        )

        self.assertNotIn(secret, repr(settings))
        self.assertNotIn(secret, settings.model_dump_json())
        self.assertNotIn(secret, str(settings.safe_summary()))

        with self.assertRaises(SettingsError) as raised:
            Settings.from_environment(
                {
                    "AI_AGENT_RUNTIME": "manual",
                    "AI_AGENT_MODEL_PROVIDER": "openai",
                    "AI_AGENT_ONLINE_ENABLED": "true",
                    "OPENAI_API_KEY": secret,
                    "OPENAI_MODEL": "configured-model",
                }
            )
        self.assertNotIn(secret, str(raised.exception))

    def test_environment_example_is_offline_and_keeps_secret_empty(self) -> None:
        example_path = Path(__file__).resolve().parents[1] / ".env.example"
        content = example_path.read_text(encoding="utf-8")

        self.assertIn("AI_AGENT_RUNTIME=manual", content)
        self.assertIn("AI_AGENT_MODEL_PROVIDER=mock", content)
        self.assertIn("AI_AGENT_ONLINE_ENABLED=false", content)
        self.assertIn("AI_AGENT_TRACE_INCLUDE_SENSITIVE=false", content)
        self.assertIn("\nAI_AGENT_MCP_SERVERS=\n", content)
        self.assertIn("\nAI_AGENT_MCP_STARTUP_TIMEOUT_MS=5000\n", content)
        self.assertIn("\nAI_AGENT_MCP_REQUEST_TIMEOUT_MS=5000\n", content)
        self.assertIn("\nAI_AGENT_PERSISTENCE=memory\n", content)
        self.assertIn("\nAI_AGENT_POSTGRES_DSN=\n", content)
        self.assertIn("\nOPENAI_API_KEY=\n", content)
        self.assertIn("\nOPENAI_MODEL=\n", content)
        self.assertIn("\nAI_AGENT_EMBEDDING_PROVIDER=offline\n", content)
        self.assertIn("\nAI_AGENT_EMBEDDING_MODEL=\n", content)
        self.assertIn("\nAI_AGENT_EMBEDDING_REVISION=\n", content)
        self.assertIn("\nAI_AGENT_EMBEDDING_DIMENSIONS=3\n", content)
        self.assertIn("\nAI_AGENT_EMBEDDING_BATCH_SIZE=32\n", content)
        self.assertIn("\nAI_AGENT_EMBEDDING_CACHE_MAX_ENTRIES=256\n", content)
        self.assertIn(
            "\nAI_AGENT_EMBEDDING_REQUEST_TIMEOUT_MS=20000\n",
            content,
        )
        self.assertIn("\nAI_AGENT_EMBEDDING_MAX_RETRIES=2\n", content)
        self.assertIn("\nAI_AGENT_MODEL_RETRY_INITIAL_DELAY_MS=100\n", content)
        self.assertIn("\nAI_AGENT_MODEL_RETRY_MAX_DELAY_MS=2000\n", content)
        self.assertIn("\nAI_AGENT_MAX_TOOL_RETRIES=1\n", content)
        self.assertIn("\nAI_AGENT_TOOL_RETRY_INITIAL_DELAY_MS=100\n", content)
        self.assertIn("\nAI_AGENT_TOOL_RETRY_MAX_DELAY_MS=1000\n", content)


if __name__ == "__main__":
    unittest.main()
