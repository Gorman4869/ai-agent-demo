from __future__ import annotations

import os
import shutil
import subprocess
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERIFY_SCRIPT = PROJECT_ROOT / "scripts" / "verify.ps1"
ONLINE_SCRIPT = PROJECT_ROOT / "scripts" / "verify-online.ps1"
WORKFLOW = PROJECT_ROOT / ".github" / "workflows" / "verification.yml"


class VerificationEntrypointTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.powershell = shutil.which("powershell") or shutil.which("pwsh")
        if cls.powershell is None:
            raise unittest.SkipTest("PowerShell is not available")

    def test_missing_postgres_configuration_fails_without_success_claim(self) -> None:
        completed = self._run_script(VERIFY_SCRIPT, "-Profile", "postgresql")

        self.assertEqual(1, completed.returncode)
        self.assertIn("postgresql   FAILED", completed.stdout)
        self.assertIn("AI_AGENT_TEST_POSTGRES_DSN", completed.stdout)
        self.assertNotIn(
            "All selected required verification layers passed.",
            completed.stdout,
        )

    def test_online_without_authorization_is_an_explicit_skip(self) -> None:
        completed = self._run_script(VERIFY_SCRIPT, "-Profile", "online")

        self.assertEqual(0, completed.returncode)
        self.assertIn("online       SKIPPED", completed.stdout)
        self.assertIn("explicit one-time authorization is missing", completed.stdout)
        self.assertIn("7 skipped", completed.stdout)
        self.assertNotIn(
            "All selected required verification layers passed.",
            completed.stdout,
        )

    def test_online_entrypoint_still_refuses_without_authorization(self) -> None:
        completed = self._run_script(ONLINE_SCRIPT)

        self.assertEqual(64, completed.returncode)
        self.assertIn("explicit one-time authorization is missing", completed.stdout)

    def test_ci_has_all_layers_and_no_repository_secret_reference(self) -> None:
        content = WORKFLOW.read_text(encoding="utf-8")

        for profile in (
            "offline",
            "mcp",
            "postgresql",
            "frontend",
            "e2e",
            "docker",
            "online",
        ):
            self.assertIn(f"-Profile {profile}", content)
        self.assertIn("contents: read", content)
        self.assertIn("Install offline MCP dependencies", content)
        self.assertNotIn("secrets.", content)
        self.assertNotIn("pull_request_target", content)
        self.assertNotIn("-AuthorizedOnline", content)

    def _run_script(self, script: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
        environment = os.environ.copy()
        for name in (
            "AI_AGENT_TEST_POSTGRES_DSN",
            "AI_AGENT_TEST_PGVECTOR_DSN",
            "OPENAI_API_KEY",
            "DASHSCOPE_API_KEY",
        ):
            environment.pop(name, None)

        command = [self.powershell, "-NoProfile"]
        if os.name == "nt":
            command.extend(("-ExecutionPolicy", "Bypass"))
        command.extend(("-File", str(script), *arguments))
        return subprocess.run(
            command,
            cwd=PROJECT_ROOT,
            env=environment,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            timeout=30,
        )


if __name__ == "__main__":
    unittest.main()
