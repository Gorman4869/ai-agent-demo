from __future__ import annotations

import unittest

from backend.app.advanced.browser_agent import (
    BrowserAgent,
    BrowserPlan,
    browser_approval_arguments,
)
from backend.app.advanced.browser_driver import (
    BrowserDriverRun,
    BrowserFixtureSite,
    PlaywrightBrowserDriver,
)
from backend.app.advanced.harness import PolicyViolation
from backend.app.advanced.browser_network import (
    BrowserNetworkPolicy,
    StaticBrowserAddressResolver,
)
from backend.app.tools import InMemoryApprovalStore, ToolExecutionContext


_ORIGIN = "https://browser.fixture.test"
_HOME = """<!doctype html>
<html>
  <head>
    <meta charset="utf-8">
    <title>Controlled Browser Fixture</title>
    <style>body { font-family: sans-serif; padding: 24px; } form { display: grid; gap: 8px; width: 360px; }</style>
  </head>
  <body>
    <main>
      <article data-agent-id="article">Verified fixture article</article>
      <form data-agent-id="search-form">
        <label>Query <input data-agent-id="search-box" type="text"></label>
        <button data-agent-id="submit-button" type="submit">Submit</button>
      </form>
      <output data-agent-id="result">idle</output>
      <a data-agent-id="cross-link" href="https://outside.example.test/">Cross origin</a>
      <button data-agent-id="popup-button" type="button" onclick="window.open('/popup', '_blank')">Popup</button>
      <a data-agent-id="download-link" download="fixture.txt" href="data:text/plain,fixture">Download</a>
      <input data-agent-id="file-input" type="file">
    </main>
    <script>
      document.querySelector('[data-agent-id="search-form"]').addEventListener('submit', (event) => {
        event.preventDefault();
        const value = document.querySelector('[data-agent-id="search-box"]').value;
        document.querySelector('[data-agent-id="result"]').textContent = `submitted:${value}`;
      });
    </script>
  </body>
</html>"""
_POPUP = "<!doctype html><title>Popup</title><p>Popup fixture</p>"
_ELEMENT_IDS = (
    "article",
    "search-form",
    "search-box",
    "submit-button",
    "result",
    "cross-link",
    "popup-button",
    "download-link",
    "file-input",
    "missing-element",
)


class PlaywrightBrowserDriverIntegrationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.site = BrowserFixtureSite(
            _ORIGIN,
            {
                "/": _HOME,
                "/popup": _POPUP,
                "/redirect-final": _POPUP,
            },
            redirects={"/redirect-start": _ORIGIN + "/redirect-final"},
        )

    def test_real_chromium_reads_types_submits_and_returns_observation(self) -> None:
        agent = _agent()
        driver = _driver(self.site)
        page_digest = _initial_digest(agent, driver)
        plan = agent.validate_plan(
            [
                {"id": "nav", "kind": "navigate", "url": _ORIGIN + "/"},
                {
                    "id": "read",
                    "kind": "read_text",
                    "element_id": "result",
                    "expected_page_digest": page_digest,
                },
                {
                    "id": "type",
                    "kind": "type",
                    "element_id": "search-box",
                    "value": "agent safety",
                    "expected_page_digest": page_digest,
                },
                {
                    "id": "submit",
                    "kind": "submit",
                    "element_id": "search-form",
                    "expected_page_digest": page_digest,
                },
            ]
        )

        result = agent.run_with_driver(
            plan,
            driver=driver,
            context=_approval_context(plan),
        )

        self.assertIsInstance(result, BrowserDriverRun)
        self.assertEqual("playwright", result.driver)
        self.assertFalse(result.network_access)
        self.assertEqual("idle", result.actions[1].text)
        self.assertIn("submitted:agent safety", result.observation.text)
        self.assertTrue(result.observation.screenshot_png.startswith(b"\x89PNG"))
        self.assertGreater(result.observation.screenshot_bytes, 8)
        self.assertIn("result", result.observation.visible_element_ids)
        self.assertNotIn("agent safety", repr(result))

    def test_rejects_changed_page_and_missing_element(self) -> None:
        agent = _agent()
        driver = _driver(self.site)
        page_digest = _initial_digest(agent, driver)
        cases = (
            (
                {
                    "id": "read-changed",
                    "kind": "read_text",
                    "element_id": "article",
                    "expected_page_digest": "f" * 64,
                },
                "browser_page_changed",
            ),
            (
                {
                    "id": "read-missing",
                    "kind": "read_text",
                    "element_id": "missing-element",
                    "expected_page_digest": page_digest,
                },
                "browser_element_missing",
            ),
        )

        for action, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                plan = agent.validate_plan(
                    [
                        {
                            "id": "nav-" + action["id"],
                            "kind": "navigate",
                            "url": _ORIGIN + "/",
                        },
                        action,
                    ]
                )
                with self.assertRaises(PolicyViolation) as raised:
                    agent.run_with_driver(plan, driver=driver)
                self.assertEqual(expected_code, raised.exception.code)

    def test_real_chromium_follows_only_prevalidated_safe_redirect(self) -> None:
        agent = _agent()
        driver = _driver(self.site)
        plan = agent.validate_plan(
            [
                {
                    "id": "redirect",
                    "kind": "navigate",
                    "url": _ORIGIN + "/redirect-start",
                }
            ]
        )

        result = agent.run_with_driver(plan, driver=driver)

        self.assertEqual(_ORIGIN + "/redirect-final", result.observation.url)
        self.assertFalse(result.network_access)

    def test_cross_origin_popup_and_transfers_fail_closed(self) -> None:
        agent = _agent()
        driver = _driver(self.site)
        page_digest = _initial_digest(agent, driver)
        cases = (
            ("cross-link", "browser_cross_origin"),
            ("popup-button", "browser_popup_blocked"),
            ("download-link", "browser_download_blocked"),
            ("file-input", "browser_upload_blocked"),
        )

        for index, (element_id, expected_code) in enumerate(cases, start=1):
            with self.subTest(element_id=element_id):
                plan = agent.validate_plan(
                    [
                        {
                            "id": f"nav-{index}",
                            "kind": "navigate",
                            "url": _ORIGIN + "/",
                        },
                        {
                            "id": f"click-{index}",
                            "kind": "click",
                            "element_id": element_id,
                            "expected_page_digest": page_digest,
                        },
                    ]
                )
                with self.assertRaises(PolicyViolation) as raised:
                    agent.run_with_driver(
                        plan,
                        driver=driver,
                        context=_approval_context(plan),
                    )
                self.assertEqual(expected_code, raised.exception.code)


def _agent() -> BrowserAgent:
    return BrowserAgent(
        allowed_origins=[_ORIGIN],
        allowed_element_ids=_ELEMENT_IDS,
    )


def _initial_digest(
    agent: BrowserAgent,
    driver: PlaywrightBrowserDriver,
) -> str:
    plan = agent.validate_plan(
        [{"id": "observe", "kind": "navigate", "url": _ORIGIN + "/"}]
    )
    return agent.run_with_driver(plan, driver=driver).observation.page_digest


def _approval_context(plan: BrowserPlan) -> ToolExecutionContext:
    approvals = InMemoryApprovalStore()
    for action in plan.actions:
        if not action.requires_approval:
            continue
        approvals.grant(
            principal_id="integration-user",
            tool_call_id=action.id,
            tool_name=f"browser.{action.kind.value}",
            arguments=browser_approval_arguments(
                action,
                plan_digest=plan.plan_digest,
            ),
        )
    return ToolExecutionContext(
        principal_id="integration-user",
        approval_store=approvals,
    )


def _driver(site: BrowserFixtureSite) -> PlaywrightBrowserDriver:
    return PlaywrightBrowserDriver(
        site,
        network_policy=BrowserNetworkPolicy(
            StaticBrowserAddressResolver(
                {"browser.fixture.test": ("93.184.216.34",)}
            )
        ),
    )


if __name__ == "__main__":
    unittest.main()
