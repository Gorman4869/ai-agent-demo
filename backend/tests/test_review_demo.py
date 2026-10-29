import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.review_demo import create_demo_review_app, create_postgres_demo_review_app
from backend.app.settings import SettingsError


class ReviewDemoBoundaryTest(unittest.TestCase):
    def test_postgres_demo_requires_its_own_explicit_dsn_file(self) -> None:
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(SettingsError):
                create_postgres_demo_review_app()

    def test_postgres_demo_does_not_read_model_or_generic_database_environment(self) -> None:
        with patch.dict("os.environ", {
            "OPENAI_API_KEY": "unused-test-placeholder", "AI_AGENT_ONLINE_ENABLED": "true",
            "AI_AGENT_POSTGRES_DSN": "postgresql://unused-localhost/unused",
        }, clear=True):
            with self.assertRaises(SettingsError):
                create_postgres_demo_review_app()

    def test_postgres_demo_keeps_offline_settings_and_the_same_host_client_boundary(self) -> None:
        with TemporaryDirectory() as directory:
            path = Path(directory) / "synthetic-dsn.txt"
            path.write_text("postgresql://synthetic@127.0.0.1/demo", encoding="utf-8")
            with patch.dict("os.environ", {
                "AI_AGENT_REVIEW_DEMO_DSN_FILE": str(path), "AI_AGENT_ONLINE_ENABLED": "true",
                "OPENAI_API_KEY": "unused-test-placeholder", "AI_AGENT_RUNTIME": "agents_sdk",
            }, clear=True), patch("backend.app.review_demo.create_postgres_review_app", return_value=FastAPI()) as factory:
                app = create_postgres_demo_review_app()
            settings = factory.call_args.kwargs["settings"]
            self.assertEqual("postgres", settings.persistence.backend)
            self.assertEqual("manual", settings.runtime)
            self.assertFalse(settings.online_enabled)
            self.assertIsNone(settings.openai_api_key)
            with TestClient(app, client=("127.0.0.1", 12345), base_url="http://127.0.0.1") as client:
                self.assertEqual(404, client.get("/health").status_code)
                self.assertEqual(400, client.get("/health", headers={"Host": "outside.example"}).status_code)
            with TestClient(app, client=("192.0.2.1", 12345), base_url="http://127.0.0.1") as client:
                self.assertEqual(403, client.get("/health").status_code)

    def test_only_loopback_client_and_known_host_are_accepted(self) -> None:
        with TestClient(create_demo_review_app(), client=("127.0.0.1", 12345), base_url="http://127.0.0.1") as client:
            self.assertEqual(200, client.get("/health").status_code)
            self.assertEqual(400, client.get("/health", headers={"Host": "outside.example"}).status_code)
        with TestClient(create_demo_review_app(), client=("192.0.2.1", 12345), base_url="http://127.0.0.1") as client:
            self.assertEqual(403, client.get("/health").status_code)
