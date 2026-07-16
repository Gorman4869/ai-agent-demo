from __future__ import annotations

import unittest
from collections.abc import Iterable

from backend.app.agent import ManualAgentLoop
from backend.app.domain import AgentRunResult, ModelDecision
from backend.app.evals import EvalCase, OfflineEvaluator
from backend.app.models import MockModel
from backend.app.observability import RunObserver
from backend.app.tools.builtin import create_default_registry


class ScriptedClock:
    def __init__(self, values: Iterable[float]) -> None:
        self._values = iter(values)

    def __call__(self) -> float:
        return next(self._values)


def run_scripted(user_input: str) -> AgentRunResult:
    answers = {
        "grounded": "Answer with source course/agent.md",
        "wrong": "Unsupported answer",
    }
    return ManualAgentLoop(
        MockModel([ModelDecision(final_answer=answers[user_input])]),
        create_default_registry(),
    ).run(user_input)


class OfflineEvaluatorTest(unittest.TestCase):
    def test_reports_pass_rate_and_failure_details(self) -> None:
        observer = RunObserver(
            clock=ScriptedClock([1.0, 1.004, 2.0, 2.006])
        )
        cases = [
            EvalCase(
                id="grounded-answer",
                input="grounded",
                answer_contains=("course/agent.md",),
                required_event_types=("run.completed",),
                max_duration_ms=5,
            ),
            EvalCase(
                id="missing-evidence",
                input="wrong",
                answer_contains=("course/agent.md",),
                required_tool_names=("search_knowledge",),
                max_duration_ms=5,
            ),
        ]

        report = OfflineEvaluator(
            run_scripted,
            observer=observer,
            batch_id_factory=lambda: "batch-fixed",
        ).evaluate(cases)

        self.assertEqual(2, report.total_cases)
        self.assertEqual(1, report.passed_cases)
        self.assertEqual(1, report.failed_cases)
        self.assertEqual(0.5, report.pass_rate)
        self.assertEqual(
            "eval-batch-fixed-missing-evidence",
            report.failures[0].observation.run_id,
        )
        self.assertEqual(
            ["answer_contains", "required_tool_name", "max_duration_ms"],
            [failure.check for failure in report.failures[0].failures],
        )
        self.assertEqual(0.5, report.to_record()["pass_rate"])
        self.assertEqual("batch-fixed", report.to_record()["batch_id"])

    def test_runner_exception_becomes_a_deterministic_failure(self) -> None:
        def broken_runner(_: str) -> AgentRunResult:
            raise RuntimeError("model unavailable")

        evaluator = OfflineEvaluator(
            broken_runner,
            observer=RunObserver(clock=ScriptedClock([3.0, 3.002])),
        )

        report = evaluator.evaluate([EvalCase(id="broken", input="question")])

        self.assertEqual(0, report.passed_cases)
        self.assertEqual("runner_exception", report.failures[0].failures[0].check)
        self.assertEqual(
            "exception.RuntimeError",
            report.failures[0].observation.errors[0].category,
        )
        self.assertEqual(2.0, report.failures[0].observation.duration_ms)

    def test_rejects_empty_or_duplicate_case_sets(self) -> None:
        evaluator = OfflineEvaluator(run_scripted)
        with self.assertRaisesRegex(ValueError, "at least one"):
            evaluator.evaluate([])
        with self.assertRaisesRegex(ValueError, "unique"):
            evaluator.evaluate(
                [
                    EvalCase(id="same", input="grounded"),
                    EvalCase(id="same", input="wrong"),
                ]
            )

    def test_cost_threshold_fails_when_provider_usage_is_unavailable(self) -> None:
        report = OfflineEvaluator(
            run_scripted,
            batch_id_factory=lambda: "cost-batch",
        ).evaluate(
            [
                EvalCase(
                    id="cost",
                    input="grounded",
                    expected_usage_available=False,
                    max_estimated_cost_usd=0.01,
                )
            ]
        )

        self.assertEqual(0, report.passed_cases)
        self.assertEqual(
            "max_estimated_cost_usd",
            report.failures[0].failures[0].check,
        )
        self.assertEqual("unavailable", report.failures[0].failures[0].actual)

    def test_each_evaluation_batch_has_a_distinct_run_id(self) -> None:
        batch_ids = iter(["batch-a", "batch-b"])
        evaluator = OfflineEvaluator(
            run_scripted,
            batch_id_factory=lambda: next(batch_ids),
        )
        case = [EvalCase(id="same-case", input="grounded")]

        first = evaluator.evaluate(case)
        second = evaluator.evaluate(case)

        self.assertNotEqual(
            first.results[0].observation.run_id,
            second.results[0].observation.run_id,
        )


if __name__ == "__main__":
    unittest.main()
