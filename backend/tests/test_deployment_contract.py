from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class DeploymentContractTest(unittest.TestCase):
    def test_deployment_compose_owns_persistent_pgvector_and_runtime_secrets(
        self,
    ) -> None:
        content = self._read("deploy/compose.deployment.yaml")

        self.assertIn("pgvector/pgvector:0.8.1-pg17", content)
        self.assertIn("postgres_data:/var/lib/postgresql/data", content)
        self.assertNotIn("POSTGRES_HOST_AUTH_METHOD", content)
        self.assertIn("POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password", content)
        self.assertIn("AI_AGENT_POSTGRES_DSN_FILE: /run/secrets/postgres_dsn", content)
        self.assertIn("AI_AGENT_DEPLOY_POSTGRES_PASSWORD_FILE", content)
        self.assertIn("AI_AGENT_DEPLOY_POSTGRES_DSN_FILE", content)
        self.assertNotIn("environment: AI_AGENT_DEPLOY_POSTGRES", content)
        self.assertNotIn("OPENAI_API_KEY", content)
        self.assertNotIn("DASHSCOPE_API_KEY", content)

    def test_deployment_orders_migration_seed_backend_and_frontend_health(self) -> None:
        content = self._read("deploy/compose.deployment.yaml")

        self.assertIn('command: ["python", "-m", "backend.app.deployment_seed"]', content)
        self.assertGreater(
            content.index("condition: service_healthy"),
            content.index("knowledge-seed:"),
        )
        self.assertIn("condition: service_completed_successfully", content)
        self.assertGreater(
            content.rindex("condition: service_healthy"),
            content.index("frontend:"),
        )
        self.assertIn('AI_AGENT_ONLINE_ENABLED: "false"', content)
        self.assertIn("AI_AGENT_EMBEDDING_PROVIDER: offline", content)

    def test_application_containers_keep_the_existing_restricted_runtime(self) -> None:
        content = self._read("deploy/compose.deployment.yaml")

        self.assertGreaterEqual(content.count("read_only: true"), 3)
        self.assertGreaterEqual(content.count("no-new-privileges:true"), 4)
        self.assertGreaterEqual(content.count("- ALL"), 4)
        self.assertIn("stop_grace_period: 15s", content)
        self.assertIn('127.0.0.1:${DEPLOY_BACKEND_PORT:-18000}:8000', content)
        self.assertIn('127.0.0.1:${DEPLOY_FRONTEND_PORT:-15173}:8080', content)

    def test_nginx_and_backend_images_keep_health_and_sse_streaming_contract(self) -> None:
        nginx = self._read("deploy/nginx.conf")
        backend = self._read("deploy/backend.Dockerfile")
        frontend = self._read("deploy/frontend.Dockerfile")

        self.assertIn("proxy_buffering off;", nginx)
        self.assertIn("proxy_cache off;", nginx)
        self.assertIn("proxy_read_timeout 300s;", nginx)
        self.assertIn("HEALTHCHECK", backend)
        self.assertIn("http://127.0.0.1:8000/health", backend)
        self.assertIn("COPY --chown=app:app skills /app/skills", backend)
        self.assertIn("USER app", backend)
        self.assertIn("HEALTHCHECK", frontend)
        self.assertIn("http://127.0.0.1:8080/ui-health", frontend)
        self.assertIn("USER nginx", frontend)

    def test_deployment_verifier_is_isolated_and_checks_restart_recovery(self) -> None:
        content = self._read("scripts/verify-deployment.ps1")

        self.assertIn("^ai-agent-demo-m13-[a-z0-9-]+$", content)
        self.assertIn("config', '--quiet", content)
        self.assertIn("'up',", content)
        self.assertIn("'--build',", content)
        self.assertIn("SELECT count(*) FROM app_schema_migrations", content)
        self.assertIn("SELECT count(*) FROM knowledge_schema_migrations", content)
        self.assertIn("ai_agent_store_test", content)
        self.assertIn("ai_agent_pgvector_test", content)
        self.assertIn("AI_AGENT_TEST_POSTGRES_DSN", content)
        self.assertIn("AI_AGENT_TEST_PGVECTOR_DSN", content)
        self.assertIn("backend.tests.postgres_store_integration", content)
        self.assertIn("backend.tests.pgvector_integration", content)
        self.assertIn("[System.IO.Path]::GetTempFileName()", content)
        self.assertIn("$uiHealthText = ($uiHealth | Out-String).Trim()", content)
        self.assertIn("Remove-Item -LiteralPath $path -Force", content)
        self.assertIn("collecting bounded project diagnostics", content)
        self.assertIn("--tail 80", content)
        self.assertIn("event: run.started", content)
        self.assertIn("event: run.completed", content)
        self.assertIn("$completedIndex -le $startedIndex", content)
        self.assertIn("'restart', 'backend'", content)
        self.assertIn("Wait-HttpHealth -Uri \"$backendBaseUrl/health\"", content)
        self.assertNotIn("'Wait for restarted deployment'", content)
        self.assertIn("down --volumes --remove-orphans", content)
        self.assertNotIn("--rmi", content)

    @staticmethod
    def _read(path: str) -> str:
        return (REPOSITORY_ROOT / path).read_text(encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
