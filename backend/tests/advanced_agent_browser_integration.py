from __future__ import annotations

import unittest

from backend.app.evals.advanced_agent import (
    run_playwright_advanced_agent_eval,
)


class AdvancedAgentBrowserIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_fixed_evaluation_runs_browser_success_in_real_chromium(
        self,
    ) -> None:
        report = await run_playwright_advanced_agent_eval()
        browser_result = next(
            result
            for result in report.results
            if result.case_id == "browser-read-allowed"
        )
        record = report.to_record()

        self.assertTrue(report.passed)
        self.assertEqual("completed", browser_result.outcome)
        self.assertEqual(2, browser_result.step_count)
        self.assertEqual(
            "playwright_fixture",
            record["execution_profile"]["browser"],
        )
        self.assertEqual(
            "real_chromium_server_owned_fixture_without_public_network",
            record["execution_scope"]["browser"],
        )
        self.assertFalse(record["cost"]["provider_usage_available"])


if __name__ == "__main__":
    unittest.main()
