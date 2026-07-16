from __future__ import annotations

import unittest

from backend.app.advanced.harness import (
    PolicyViolation,
    SafetyBudget,
    SafetyLimits,
    content_digest,
)


class AdvancedHarnessTest(unittest.TestCase):
    def test_tracks_actions_and_bytes_without_storing_content(self) -> None:
        budget = SafetyBudget(
            SafetyLimits(max_actions=2, max_input_bytes=5, max_output_bytes=3)
        )

        budget.consume(input_bytes=2, output_bytes=1)
        budget.consume(input_bytes=3, output_bytes=2)

        self.assertEqual(2, budget.actions)
        self.assertEqual(5, budget.input_bytes)
        self.assertEqual(3, budget.output_bytes)
        self.assertEqual(64, len(content_digest("private content")))

    def test_budget_violation_has_a_stable_category(self) -> None:
        budget = SafetyBudget(SafetyLimits(max_actions=1))
        budget.consume()

        with self.assertRaises(PolicyViolation) as raised:
            budget.consume()

        self.assertEqual("action_budget_exceeded", raised.exception.code)

    def test_rejects_invalid_limits_and_negative_usage(self) -> None:
        for value in (0, True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    SafetyLimits(max_actions=value)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            SafetyBudget().consume(input_bytes=-1)
        with self.assertRaises(TypeError):
            SafetyBudget().consume(actions=1.5)  # type: ignore[arg-type]


if __name__ == "__main__":
    unittest.main()
