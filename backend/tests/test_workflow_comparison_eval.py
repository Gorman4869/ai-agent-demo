from __future__ import annotations

import json
import unittest
from unittest.mock import AsyncMock, patch

from backend.app.evals.multi_agent import (
    DEFAULT_COLLABORATION_CASES,
    CollaborationEvalCase,
    run_offline_multi_agent_comparison,
)


class WorkflowComparisonEvalTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.report = await run_offline_multi_agent_comparison(
            model_delay_ms=1,
        )

    async def test_equal_quality_and_failure_rate_keep_single_agent(self) -> None:
        self.assertEqual(1.0, self.report.manager_as_tools.quality_score)
        self.assertEqual(1.0, self.report.single_agent.quality_score)
        self.assertEqual(0.0, self.report.manager_as_tools.failure_rate)
        self.assertEqual(0.0, self.report.single_agent.failure_rate)
        self.assertEqual("single_agent", self.report.preferred_strategy)
        self.assertEqual(
            "no_multi_agent_quality_gain",
            self.report.decision_code,
        )

    async def test_multi_agent_has_more_requests_tokens_latency_and_complexity(self) -> None:
        manager = self.report.manager_as_tools
        single = self.report.single_agent

        self.assertEqual(27, manager.total_model_requests)
        self.assertEqual(9, single.total_model_requests)
        self.assertEqual(324, manager.total_tokens)
        self.assertEqual(108, single.total_tokens)
        self.assertGreater(manager.total_latency_ms, single.total_latency_ms)
        self.assertGreater(
            manager.complexity.complexity_units,
            single.complexity.complexity_units,
        )

    async def test_each_case_records_role_and_tool_execution_counts(self) -> None:
        for result in self.report.manager_as_tools.results:
            self.assertEqual(
                {"manager": 4, "researcher": 2, "reviewer": 2, "writer": 1},
                dict(result.role_model_calls),
            )
            self.assertEqual(
                {"check_required_terms": 1, "lookup_course_fact": 1},
                dict(result.tool_calls),
            )
        for result in self.report.single_agent.results:
            self.assertEqual({"single": 3}, dict(result.role_model_calls))

    async def test_record_labels_fixture_evidence_without_answers_or_facts(self) -> None:
        record = self.report.to_record()
        serialized = json.dumps(record, ensure_ascii=False, allow_nan=False)

        self.assertEqual("E2_offline_fixture", record["evidence_level"])
        self.assertEqual(
            "deterministic_fixture_usage_not_provider_billing",
            record["token_scope"],
        )
        self.assertNotIn(DEFAULT_COLLABORATION_CASES[0].fact, serialized)
        self.assertNotIn("final_output", serialized)

    async def test_invalid_case_sets_and_delay_are_rejected(self) -> None:
        duplicate = DEFAULT_COLLABORATION_CASES[0]
        with self.assertRaisesRegex(ValueError, "at least one"):
            await run_offline_multi_agent_comparison(())
        with self.assertRaisesRegex(ValueError, "unique"):
            await run_offline_multi_agent_comparison((duplicate, duplicate))
        with self.assertRaisesRegex(ValueError, "between 0 and 100"):
            await run_offline_multi_agent_comparison(model_delay_ms=-1)

    async def test_execution_errors_use_stable_code_without_raw_text(self) -> None:
        secret = "provider-secret-must-not-leak"
        with patch(
            "backend.app.evals.multi_agent.Runner.run",
            new=AsyncMock(side_effect=RuntimeError(secret)),
        ):
            report = await run_offline_multi_agent_comparison(
                (
                    CollaborationEvalCase(
                        id="safe-error",
                        input_text="Trigger one safe failure.",
                        fact="A safe fact.",
                        expected_terms=("safe",),
                    ),
                ),
                model_delay_ms=0,
            )

        serialized = json.dumps(report.to_record(), ensure_ascii=False)
        self.assertEqual(1.0, report.manager_as_tools.failure_rate)
        self.assertEqual(
            "collaboration_execution_failed",
            report.manager_as_tools.results[0].error_code,
        )
        self.assertNotIn(secret, serialized)


if __name__ == "__main__":
    unittest.main()
