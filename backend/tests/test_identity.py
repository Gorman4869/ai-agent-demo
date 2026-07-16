from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

from backend.app.security import (
    AUTH_CONFIG_ENV,
    AuthenticationError,
    Principal,
    StaticTokenAuthenticator,
)
from backend.app.tools.builtin import create_default_registry


class IdentityTest(unittest.TestCase):
    def test_missing_credential_is_explicit_anonymous_principal(self) -> None:
        principal = StaticTokenAuthenticator().authenticate(None)

        self.assertFalse(principal.authenticated)
        self.assertEqual("anonymous", principal.principal_id)

    def test_known_bearer_token_resolves_server_owned_principal(self) -> None:
        authenticator = StaticTokenAuthenticator(
            {
                "test-token": Principal(
                    "user-1",
                    roles=frozenset({"editor"}),
                )
            }
        )

        principal = authenticator.authenticate("Bearer test-token")

        self.assertEqual("user-1", principal.principal_id)
        self.assertEqual(frozenset({"editor"}), principal.roles)

    def test_unknown_or_malformed_credentials_are_rejected(self) -> None:
        authenticator = StaticTokenAuthenticator()

        for credential in ("Basic abc", "Bearer", "Bearer unknown"):
            with self.subTest(credential=credential):
                with self.assertRaises(AuthenticationError):
                    authenticator.authenticate(credential)

    def test_environment_approval_is_exact_and_single_use(self) -> None:
        config = {
            "test-token": {
                "principal_id": "editor-1",
                "roles": ["editor"],
                "approvals": [
                    {
                        "tool_call_id": "call-1",
                        "tool_name": "publish_report",
                        "arguments": {"report_id": "report-7"},
                    }
                ],
            }
        }
        with patch.dict(
            os.environ,
            {AUTH_CONFIG_ENV: json.dumps(config)},
            clear=False,
        ):
            principal = StaticTokenAuthenticator.from_environment().authenticate(
                "Bearer test-token"
            )

        registry = create_default_registry()
        first = registry.execute(
            "publish_report",
            {"report_id": "report-7"},
            context=principal.to_tool_context(),
            call_id="call-1",
        )
        replay = registry.execute(
            "publish_report",
            {"report_id": "report-7"},
            context=principal.to_tool_context(),
            call_id="call-1",
        )

        self.assertTrue(first.ok)
        self.assertEqual("approval_required", replay.error_code)
        self.assertEqual("approval_already_consumed", replay.error_details["reason"])

    def test_legacy_tool_wide_approval_configuration_fails_closed(self) -> None:
        config = {
            "test-token": {
                "principal_id": "editor-1",
                "roles": ["editor"],
                "approved_tools": ["publish_report"],
            }
        }
        with patch.dict(
            os.environ,
            {AUTH_CONFIG_ENV: json.dumps(config)},
            clear=False,
        ):
            with self.assertRaisesRegex(ValueError, "unsupported authentication"):
                StaticTokenAuthenticator.from_environment()


if __name__ == "__main__":
    unittest.main()
