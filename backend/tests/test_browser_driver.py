from __future__ import annotations

import base64
import json
import os
import sys
import unittest
from collections.abc import Mapping, Sequence
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from backend.app.advanced.browser_agent import BrowserAgent
from backend.app.advanced.browser_driver import (
    BrowserFixtureSite,
    PlaywrightBrowserDriver,
)
from backend.app.advanced.harness import PolicyViolation, content_digest
from backend.app.advanced.process_runner import (
    BoundedProcessResult,
    ProcessResourceLimits,
)


_ORIGIN = "https://browser.fixture.test"
_DOCUMENT = "<!doctype html><title>Fixture</title><p data-agent-id='article'>Safe text</p>"
_PNG = b"\x89PNG\r\n\x1a\n"


class BrowserFixtureSiteTest(unittest.TestCase):
    def test_canonicalizes_documents_and_hides_document_content(self) -> None:
        site = BrowserFixtureSite(_ORIGIN, {"/guide?q=agent": _DOCUMENT})

        self.assertEqual(
            {_ORIGIN + "/guide?q=agent": _DOCUMENT},
            dict(site.documents),
        )
        self.assertNotIn("Safe text", repr(site))

    def test_rejects_cross_origin_style_and_fragment_targets(self) -> None:
        for target in ("//evil.test/", "https://evil.test/", "/guide#fragment"):
            with self.subTest(target=target):
                with self.assertRaises(ValueError):
                    BrowserFixtureSite(_ORIGIN, {target: _DOCUMENT})


class PlaywrightBrowserDriverTest(unittest.TestCase):
    def test_requires_observation_digest_before_dom_action(self) -> None:
        runner = _FakeBrowserRunner()
        with TemporaryDirectory() as temporary:
            driver = _driver(runner, Path(temporary))
            plan = _agent().validate_plan(
                [
                    {"id": "nav", "kind": "navigate", "url": _ORIGIN + "/"},
                    {
                        "id": "read",
                        "kind": "read_text",
                        "element_id": "article",
                    },
                ]
            )

            with self.assertRaises(PolicyViolation) as raised:
                driver.execute(plan.actions)

        self.assertEqual("browser_observation_required", raised.exception.code)
        self.assertEqual(0, runner.call_count)

    def test_parses_bounded_observation_and_excludes_provider_secrets(self) -> None:
        runner = _FakeBrowserRunner()
        with TemporaryDirectory() as temporary, patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "must-not-leak",
                "DASHSCOPE_API_KEY": "must-not-leak",
            },
        ):
            driver = _driver(runner, Path(temporary))
            plan = _agent().validate_plan(
                [{"id": "nav", "kind": "navigate", "url": _ORIGIN + "/"}]
            )

            result = driver.execute(plan.actions)

        self.assertEqual("playwright", result.driver)
        self.assertFalse(result.network_access)
        self.assertEqual(content_digest(_PNG), result.observation.screenshot_sha256)
        self.assertEqual(_PNG, result.observation.screenshot_png)
        self.assertNotIn("Safe text", repr(result))
        self.assertEqual(1, runner.call_count)
        self.assertNotIn("OPENAI_API_KEY", runner.environment)
        self.assertNotIn("DASHSCOPE_API_KEY", runner.environment)
        self.assertEqual(1, runner.request["schema_version"])

    def test_maps_unknown_child_error_to_stable_invalid_response(self) -> None:
        runner = _FakeBrowserRunner(error_code="unknown_child_error")
        with TemporaryDirectory() as temporary:
            driver = _driver(runner, Path(temporary))
            plan = _agent().validate_plan(
                [{"id": "nav", "kind": "navigate", "url": _ORIGIN + "/"}]
            )

            with self.assertRaises(PolicyViolation) as raised:
                driver.execute(plan.actions)

        self.assertEqual("browser_driver_invalid_response", raised.exception.code)


class _FakeBrowserRunner:
    def __init__(self, *, error_code: str | None = None) -> None:
        self.error_code = error_code
        self.call_count = 0
        self.environment: Mapping[str, str] = {}
        self.request: Mapping[str, object] = {}

    def __call__(
        self,
        argv: Sequence[str],
        *,
        cwd: Path,
        environment: Mapping[str, str],
        timeout_seconds: float,
        max_output_bytes: int,
        resources: ProcessResourceLimits,
    ) -> BoundedProcessResult:
        del cwd, timeout_seconds, max_output_bytes, resources
        self.call_count += 1
        self.environment = dict(environment)
        request_path = Path(argv[-2])
        response_path = Path(argv[-1])
        self.request = json.loads(request_path.read_text(encoding="utf-8"))
        if self.error_code is not None:
            response = {"ok": False, "code": self.error_code}
            return_code = 1
        else:
            digest = "a" * 64
            actions = self.request["actions"]
            assert isinstance(actions, list)
            response = {
                "ok": True,
                "actions": [
                    {
                        "action_id": action["id"],
                        "kind": action["kind"],
                        "origin": action["origin"],
                        "page_digest": digest,
                        "text": None,
                    }
                    for action in actions
                ],
                "observation": {
                    "origin": _ORIGIN,
                    "page_digest": digest,
                    "visible_element_ids": ["article"],
                    "url": _ORIGIN + "/",
                    "title": "Fixture",
                    "text": "Safe text",
                    "screenshot_base64": base64.b64encode(_PNG).decode("ascii"),
                },
            }
            return_code = 0
        response_path.write_text(json.dumps(response), encoding="utf-8")
        return BoundedProcessResult(
            stdout=b"",
            stderr=b"",
            return_code=return_code,
            truncated=False,
            observed_output_bytes=0,
            termination_reason="completed",
            resource_limit=None,
            process_scope="fake",
            process_tree_cleaned=True,
            output_read_succeeded=True,
        )


def _driver(
    runner: _FakeBrowserRunner,
    temporary_root: Path,
) -> PlaywrightBrowserDriver:
    return PlaywrightBrowserDriver(
        BrowserFixtureSite(_ORIGIN, {"/": _DOCUMENT}),
        node_executable=sys.executable,
        temporary_root=temporary_root,
        process_runner=runner,
    )


def _agent() -> BrowserAgent:
    return BrowserAgent(
        allowed_origins=[_ORIGIN],
        allowed_element_ids=["article"],
    )


if __name__ == "__main__":
    unittest.main()
