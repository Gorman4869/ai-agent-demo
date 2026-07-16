from __future__ import annotations

import unittest

from backend.app.advanced.browser_agent import (
    BrowserAction,
    BrowserActionKind,
    BrowserAgent,
    BrowserPlan,
    browser_approval_arguments,
)
from backend.app.advanced.harness import PolicyViolation
from backend.app.tools import InMemoryApprovalStore, ToolExecutionContext


class BrowserAgentTest(unittest.TestCase):
    def test_rejects_non_integer_plan_limits(self) -> None:
        for value in (True, 1.5):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    _agent(max_actions=value)  # type: ignore[arg-type]

    def test_validates_and_simulates_an_allowlisted_read_only_plan(self) -> None:
        agent = _agent()
        plan = agent.validate_plan(
            [
                {
                    "id": "nav-1",
                    "kind": "navigate",
                    "url": "https://docs.example.test/guide?q=agent",
                },
                {
                    "id": "read-1",
                    "kind": "read_text",
                    "element_id": "article-body",
                },
            ]
        )

        result = agent.run(plan)

        self.assertTrue(result.offline)
        self.assertEqual("https://docs.example.test", result.final_origin)
        self.assertEqual(["navigate", "read_text"], [item.kind for item in result.actions])
        self.assertTrue(all(item.simulated for item in result.actions))
        self.assertNotIn("q=agent", repr(result.actions))

    def test_rejects_unsafe_urls_and_exact_origin_confusion(self) -> None:
        agent = _agent()
        cases = (
            ("http://docs.example.test", "browser_scheme_not_allowed"),
            ("file:///tmp/demo", "browser_scheme_not_allowed"),
            ("javascript:alert(1)", "browser_scheme_not_allowed"),
            (
                "https://user:pass@docs.example.test/",
                "browser_credentials_not_allowed",
            ),
            ("https://localhost/", "browser_localhost_not_allowed"),
            ("https://127.0.0.1/", "browser_localhost_not_allowed"),
            ("https://[::1]/", "browser_localhost_not_allowed"),
            ("https://docs.example.test.evil.test/", "origin_not_allowed"),
            ("https://sub.docs.example.test/", "origin_not_allowed"),
        )

        for url, expected_code in cases:
            with self.subTest(url=url):
                with self.assertRaises(PolicyViolation) as raised:
                    agent.validate_plan(
                        [{"id": "nav", "kind": "navigate", "url": url}]
                    )
                self.assertEqual(expected_code, raised.exception.code)

    def test_enforces_action_budget_before_simulation(self) -> None:
        agent = _agent(max_actions=1)

        with self.assertRaises(PolicyViolation) as raised:
            agent.validate_plan(
                [
                    {
                        "id": "nav",
                        "kind": "navigate",
                        "url": "https://docs.example.test/",
                    },
                    {
                        "id": "read",
                        "kind": "read_text",
                        "element_id": "article-body",
                    },
                ]
            )

        self.assertEqual("action_budget_exceeded", raised.exception.code)

    def test_run_revalidates_and_rejects_forged_compiled_plans(self) -> None:
        agent = _agent()
        valid_plan = agent.validate_plan(
            [
                {
                    "id": "nav",
                    "kind": "navigate",
                    "url": "https://docs.example.test/",
                }
            ]
        )
        forged_plans = (
            BrowserPlan(
                actions=(
                    BrowserAction(
                        id="nav",
                        kind=BrowserActionKind.NAVIGATE,
                        origin="https://evil.test",
                        url="https://docs.example.test/",
                    ),
                ),
                policy_digest=valid_plan.policy_digest,
            ),
            BrowserPlan(
                actions=(
                    valid_plan.actions[0],
                    BrowserAction(
                        id="read-forged",
                        kind=BrowserActionKind.READ_TEXT,
                        origin="https://docs.example.test",
                        element_id="model-invented-id",
                    ),
                ),
                policy_digest=valid_plan.policy_digest,
            ),
        )

        for forged_plan in forged_plans:
            with self.subTest(forged_plan=forged_plan):
                with self.assertRaises(PolicyViolation) as raised:
                    agent.run(forged_plan)
                self.assertEqual("invalid_browser_plan", raised.exception.code)

    def test_type_and_submit_require_exact_single_use_server_approval(self) -> None:
        agent = _agent()
        plan = agent.validate_plan(
            [
                {
                    "id": "nav",
                    "kind": "navigate",
                    "url": "https://docs.example.test/form",
                },
                {
                    "id": "type-1",
                    "kind": "type",
                    "element_id": "search-box",
                    "value": "agent security",
                },
                {
                    "id": "submit-1",
                    "kind": "submit",
                    "element_id": "search-form",
                },
            ]
        )
        approvals = InMemoryApprovalStore()
        for action in plan.actions[1:]:
            approvals.grant(
                principal_id="user-1",
                tool_call_id=action.id,
                tool_name=f"browser.{action.kind.value}",
                arguments=browser_approval_arguments(action),
            )
        context = ToolExecutionContext(
            principal_id="user-1",
            approval_store=approvals,
        )

        result = agent.run(plan, context=context)

        self.assertEqual(3, len(result.actions))
        self.assertNotIn("agent security", repr(result.actions))
        with self.assertRaises(PolicyViolation) as replay_error:
            agent.run(plan, context=context)
        self.assertEqual("approval_required", replay_error.exception.code)
        self.assertEqual("approval_already_consumed", replay_error.exception.detail)

    def test_changed_type_value_does_not_match_exact_approval(self) -> None:
        agent = _agent()
        approved_plan = agent.validate_plan(_type_plan("approved"))
        changed_plan = agent.validate_plan(_type_plan("changed"))
        approvals = InMemoryApprovalStore()
        approved_action = approved_plan.actions[-1]
        approvals.grant(
            principal_id="user-1",
            tool_call_id=approved_action.id,
            tool_name="browser.type",
            arguments=browser_approval_arguments(approved_action),
        )

        with self.assertRaises(PolicyViolation) as raised:
            agent.run(
                changed_plan,
                context=ToolExecutionContext(
                    principal_id="user-1",
                    approval_store=approvals,
                ),
            )

        self.assertEqual("approval_required", raised.exception.code)
        self.assertEqual("exact_call_approval_missing", raised.exception.detail)

    def test_rejects_scripts_downloads_selectors_and_sensitive_elements(self) -> None:
        agent = _agent()
        cases = (
            (
                [{"id": "script", "kind": "evaluate_script", "script": "1+1"}],
                "forbidden_browser_action",
            ),
            ([{"id": "download", "kind": "download"}], "forbidden_browser_action"),
            (
                [
                    {
                        "id": "nav",
                        "kind": "navigate",
                        "url": "https://docs.example.test/",
                    },
                    {
                        "id": "read",
                        "kind": "read_text",
                        "selector": "input[type=password]",
                    },
                ],
                "sensitive_browser_field",
            ),
            (
                [
                    {
                        "id": "nav",
                        "kind": "navigate",
                        "url": "https://docs.example.test/",
                    },
                    {
                        "id": "type",
                        "kind": "type",
                        "element_id": "password-field",
                        "value": "secret",
                    },
                ],
                "sensitive_browser_field",
            ),
        )

        for actions, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with self.assertRaises(PolicyViolation) as raised:
                    agent.validate_plan(actions)
                self.assertEqual(expected_code, raised.exception.code)

    def test_requires_navigation_and_server_allowlisted_element_ids(self) -> None:
        agent = _agent()
        with self.assertRaises(PolicyViolation) as navigation_error:
            agent.validate_plan(
                [
                    {
                        "id": "read",
                        "kind": "read_text",
                        "element_id": "article-body",
                    }
                ]
            )
        with self.assertRaises(PolicyViolation) as element_error:
            agent.validate_plan(
                [
                    {
                        "id": "nav",
                        "kind": "navigate",
                        "url": "https://docs.example.test/",
                    },
                    {
                        "id": "read",
                        "kind": "read_text",
                        "element_id": "model-invented-id",
                    },
                ]
            )

        self.assertEqual("navigation_required", navigation_error.exception.code)
        self.assertEqual("element_not_allowed", element_error.exception.code)


def _agent(*, max_actions: int = 12) -> BrowserAgent:
    return BrowserAgent(
        allowed_origins=["https://docs.example.test"],
        allowed_element_ids=["article-body", "search-box", "search-form"],
        max_actions=max_actions,
    )


def _type_plan(value: str) -> list[dict[str, str]]:
    return [
        {
            "id": "nav",
            "kind": "navigate",
            "url": "https://docs.example.test/",
        },
        {
            "id": "type-1",
            "kind": "type",
            "element_id": "search-box",
            "value": value,
        },
    ]


if __name__ == "__main__":
    unittest.main()
