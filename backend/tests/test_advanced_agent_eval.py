from __future__ import annotations

import json
import tempfile
import unittest
from collections.abc import Sequence
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from backend.app.advanced.browser_agent import BrowserAction
from backend.app.advanced.browser_driver import (
    BrowserDriverActionResult,
    BrowserDriverRun,
    BrowserObservation,
)
from backend.app.advanced.harness import PolicyViolation
from backend.app.evals.advanced_agent import (
    DEFAULT_ADVANCED_AGENT_DATASET,
    AdvancedAgentDatasetError,
    AdvancedAgentEvaluator,
    load_advanced_agent_dataset,
    run_default_advanced_agent_eval,
)


class AdvancedAgentDatasetTest(unittest.TestCase):
    def test_default_dataset_is_versioned_bounded_and_covers_both_modalities(
        self,
    ) -> None:
        dataset = load_advanced_agent_dataset()

        self.assertEqual("m14-advanced-agent-v1", dataset.version)
        self.assertEqual(64, len(dataset.digest))
        self.assertEqual(7, len(dataset.cases))
        self.assertEqual(
            {"browser", "vision"},
            {case.modality for case in dataset.cases},
        )
        self.assertTrue(any(case.safety_case for case in dataset.cases))
        self.assertTrue(
            any(case.expected_outcome == "completed" for case in dataset.cases)
        )
        self.assertTrue(
            any(case.expected_outcome != "completed" for case in dataset.cases)
        )

    def test_dataset_digest_is_independent_of_json_formatting(self) -> None:
        payload = json.loads(DEFAULT_ADVANCED_AGENT_DATASET.read_text("utf-8"))

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary_directory:
            compact_path = Path(temporary_directory) / "compact.json"
            compact_path.write_text(
                json.dumps(payload, separators=(",", ":")),
                encoding="utf-8",
            )
            compact = load_advanced_agent_dataset(compact_path)

        self.assertEqual(load_advanced_agent_dataset().digest, compact.digest)

    def test_loader_rejects_unknown_scenario_without_echoing_content(self) -> None:
        payload = json.loads(DEFAULT_ADVANCED_AGENT_DATASET.read_text("utf-8"))
        payload["cases"][0]["scenario"] = "private-unknown-scenario"

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary_directory:
            path = Path(temporary_directory) / "dataset.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(AdvancedAgentDatasetError) as caught:
                load_advanced_agent_dataset(path)

        self.assertEqual("advanced_eval_scenario_unknown", caught.exception.code)
        self.assertNotIn("private-unknown-scenario", str(caught.exception))

    def test_loader_rejects_human_intervention_without_approval_case(self) -> None:
        payload = json.loads(DEFAULT_ADVANCED_AGENT_DATASET.read_text("utf-8"))
        payload["cases"][2]["human_intervention_expected"] = True

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as temporary_directory:
            path = Path(temporary_directory) / "dataset.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(AdvancedAgentDatasetError) as caught:
                load_advanced_agent_dataset(path)

        self.assertEqual(
            "advanced_eval_human_intervention_invalid",
            caught.exception.code,
        )


class AdvancedAgentEvaluatorTest(unittest.IsolatedAsyncioTestCase):
    async def test_default_evaluation_records_success_failure_and_safety(self) -> None:
        report = await run_default_advanced_agent_eval()

        self.assertTrue(report.passed)
        self.assertEqual(1.0, report.expectation_pass_rate)
        self.assertEqual(3 / 7, report.task_success_rate)
        self.assertEqual(1.0, report.safety_rejection_rate)
        self.assertEqual(1 / 7, report.human_intervention_rate)
        self.assertEqual(
            {
                "approval_required": 1,
                "invalid_png_signature": 1,
                "origin_not_allowed": 1,
                "provider_timeout": 1,
            },
            report.failure_analysis,
        )
        self.assertEqual(4, len(report.mitigation_codes))

    async def test_report_separates_modalities_steps_latency_and_cost_scope(
        self,
    ) -> None:
        record = (await run_default_advanced_agent_eval()).to_record()

        self.assertEqual("offline", record["execution_profile"]["browser"])
        self.assertEqual(9, record["metrics"]["total_steps"])
        self.assertEqual(3, record["modalities"]["browser"]["total_cases"])
        self.assertEqual(4, record["modalities"]["vision"]["total_cases"])
        self.assertEqual(
            "local_process_wall_clock_not_production_latency",
            record["metrics"]["latency_scope"],
        )
        self.assertFalse(record["cost"]["provider_usage_available"])
        self.assertIsNone(record["cost"]["total_tokens"])
        self.assertIsNone(record["cost"]["estimated_cost"])
        self.assertIn(
            "no human was observed",
            record["metric_scopes"]["human_intervention_rate"],
        )

    async def test_report_omits_urls_visual_text_and_fixture_content(self) -> None:
        serialized = json.dumps(
            (await run_default_advanced_agent_eval()).to_record(),
            ensure_ascii=False,
        )

        self.assertNotIn("docs.example.test", serialized)
        self.assertNotIn("evil.example.test", serialized)
        self.assertNotIn("IGNORE RULES", serialized)
        self.assertNotIn("APPROVE TOOL", serialized)
        self.assertIn("vision-prompt-injection-boundary", serialized)

    async def test_expectation_drift_fails_the_report(self) -> None:
        dataset = load_advanced_agent_dataset()
        changed_case = replace(
            dataset.cases[0],
            expected_step_count=3,
        )
        changed_dataset = replace(
            dataset,
            cases=(changed_case, *dataset.cases[1:]),
        )

        report = await AdvancedAgentEvaluator(changed_dataset).evaluate()

        self.assertFalse(report.passed)
        self.assertIn(
            "expectation_pass_rate_below_threshold",
            report.threshold_failure_codes,
        )
        self.assertEqual(
            ("step_count_mismatch",),
            report.results[0].expectation_failure_codes,
        )

    async def test_default_evaluation_does_not_construct_provider_client(
        self,
    ) -> None:
        with patch(
            "backend.app.advanced.multimodal.openai.AsyncOpenAI",
            side_effect=AssertionError("provider client is forbidden"),
        ):
            report = await run_default_advanced_agent_eval()

        self.assertTrue(report.passed)

    async def test_playwright_profile_reuses_dataset_and_records_driver_scope(
        self,
    ) -> None:
        driver = _RecordingBrowserDriver()

        report = await AdvancedAgentEvaluator(
            load_advanced_agent_dataset(),
            browser_execution_profile="playwright_fixture",
            browser_driver_factory=lambda: driver,
        ).evaluate()
        record = report.to_record()

        self.assertTrue(report.passed)
        self.assertEqual(
            "playwright_fixture",
            record["execution_profile"]["browser"],
        )
        self.assertEqual(
            "real_chromium_server_owned_fixture_without_public_network",
            record["execution_scope"]["browser"],
        )
        self.assertEqual([1, 2, 1], driver.executed_action_counts)
        self.assertFalse(record["cost"]["provider_usage_available"])

    async def test_playwright_driver_drift_failures_are_reported_stably(
        self,
    ) -> None:
        for failure_code in (
            "browser_page_changed",
            "browser_element_missing",
        ):
            with self.subTest(failure_code=failure_code):
                driver = _RecordingBrowserDriver(failure_code=failure_code)
                report = await AdvancedAgentEvaluator(
                    load_advanced_agent_dataset(),
                    browser_execution_profile="playwright_fixture",
                    browser_driver_factory=lambda: driver,
                ).evaluate()
                first = report.results[0]

                self.assertFalse(report.passed)
                self.assertEqual("rejected", first.outcome)
                self.assertEqual(failure_code, first.failure_code)
                self.assertEqual(
                    "refresh_observation_and_replan",
                    first.mitigation_code,
                )
                self.assertEqual(1, report.failure_analysis[failure_code])


class _RecordingBrowserDriver:
    def __init__(self, *, failure_code: str | None = None) -> None:
        self._failure_code = failure_code
        self.executed_action_counts: list[int] = []

    def validate(self, actions: Sequence[BrowserAction]) -> None:
        compiled = tuple(actions)
        if (
            self._failure_code is not None
            and len(compiled) > 1
            and compiled[1].kind.value == "read_text"
        ):
            raise PolicyViolation(self._failure_code, "stable fixture failure")

    def execute(self, actions: Sequence[BrowserAction]) -> BrowserDriverRun:
        compiled = tuple(actions)
        self.executed_action_counts.append(len(compiled))
        page_digest = "a" * 64
        results = tuple(
            BrowserDriverActionResult(
                action_id=action.id,
                kind=action.kind.value,
                origin=action.origin,
                page_digest=page_digest,
                text="Reviewed fixture article"
                if action.kind.value == "read_text"
                else None,
            )
            for action in compiled
        )
        return BrowserDriverRun(
            actions=results,
            observation=BrowserObservation(
                origin="https://docs.example.test",
                page_digest=page_digest,
                visible_element_ids=("article-body",),
                screenshot_sha256="b" * 64,
                screenshot_bytes=8,
                url="https://docs.example.test/guide",
                title="Advanced Agent Fixture",
                text="Reviewed fixture article",
                screenshot_png=b"\x89PNG\r\n\x1a\n",
            ),
        )


if __name__ == "__main__":
    unittest.main()
