from __future__ import annotations

import unittest
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


class LoadFaultScriptContractTest(unittest.TestCase):
    def setUp(self) -> None:
        self.wrapper = (
            REPOSITORY_ROOT / "scripts/verify-load-fault.ps1"
        ).read_text(encoding="utf-8")
        self.verifier = (
            REPOSITORY_ROOT / "scripts/verify-deployment.ps1"
        ).read_text(encoding="utf-8")
        self.content = self.wrapper + "\n" + self.verifier

    def test_owns_a_unique_project_and_exact_cleanup(self) -> None:
        self.assertIn("^ai-agent-demo-m13-[a-z0-9-]+$", self.content)
        self.assertIn("verify-deployment.ps1", self.content)
        self.assertIn("down --volumes --remove-orphans", self.content)
        self.assertIn("Remove-Item -LiteralPath $path -Force", self.content)
        self.assertNotIn("ai-agent-demo-integration", self.content)
        self.assertNotIn("--rmi", self.content)

    def test_bounds_load_outage_and_process_execution(self) -> None:
        self.assertIn("[ValidateRange(1, 100)]", self.content)
        self.assertIn("[ValidateRange(1, 16)]", self.content)
        self.assertIn("-TimeoutSec 8", self.content)
        self.assertIn("$outageStatus = [int]$_.Exception.Response.StatusCode", self.content)
        self.assertIn("$probeExitCode = $LASTEXITCODE", self.content)
        self.assertNotIn("Start-Process", self.content)
        self.assertIn("[int]$LoadFaultRuns = 16", self.verifier)
        self.assertIn("[int]$LoadFaultConcurrency = 4", self.verifier)
        self.assertIn(
            "database_integration=skipped_reused_m13_t4",
            self.verifier,
        )
        self.assertLess(
            self.verifier.index("$probeLine = $probeOutput"),
            self.verifier.index("$probeExitCode -ne 0"),
        )

    def test_exercises_required_faults_without_provider_secrets(self) -> None:
        self.assertIn("Stop owned PostgreSQL service", self.content)
        self.assertIn("Start owned PostgreSQL service", self.content)
        self.assertIn("Restart owned backend service", self.content)
        self.assertIn("Get-ProjectResourceSnapshot", self.content)
        self.assertIn("backend.app.load_fault_probe", self.content)
        self.assertNotIn("OPENAI_API_KEY", self.content)
        self.assertNotIn("DASHSCOPE_API_KEY", self.content)

    def test_wrapper_reuses_the_deployment_secret_lifecycle(self) -> None:
        self.assertIn("-LoadFault", self.wrapper)
        self.assertIn("-SkipDatabaseRegression", self.wrapper)
        self.assertNotIn("docker @composeArguments", self.wrapper)
        self.assertIn("$secretFiles", self.verifier)
        self.assertIn("$temporaryFiles", self.verifier)
        self.assertIn(
            "$probeError = (Get-Content $probeStderr | Out-String).Trim()",
            self.verifier,
        )
        self.assertIn(
            "SkipDatabaseRegression is allowed only for the M13-T6 load/fault path",
            self.verifier,
        )

    def test_recovery_accepts_idempotent_replay_without_reissuing_capability(
        self,
    ) -> None:
        self.assertIn("$createdRun.session_capability -and", self.verifier)
        self.assertIn(
            "$createdRun.session_capability -ne $runCapability",
            self.verifier,
        )
        self.assertIn("'X-Session-Token' = $runCapability", self.verifier)
        self.assertIn("$terminalFailures -ge 8", self.verifier)
        self.assertIn("terminal_failures = $terminalFailures", self.verifier)
        self.assertLess(
            self.verifier.index("$storedRun.status -in @('failed', 'cancelled')"),
            self.verifier.index(
                "$runCapability = [Guid]::NewGuid().ToString('N')",
                self.verifier.index("$storedRun.status -in @('failed', 'cancelled')"),
            ),
        )


if __name__ == "__main__":
    unittest.main()
