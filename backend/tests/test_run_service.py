from __future__ import annotations

import unittest
from unittest.mock import patch

from backend.app.services import InMemoryRunService


class RunServiceTest(unittest.TestCase):
    def test_failed_runner_observation_remains_visible_only_to_its_principal(self) -> None:
        service = InMemoryRunService()
        session = service.create_session(principal_id="user-1").session

        with patch(
            "backend.app.services.run_service.execute_agent",
            side_effect=RuntimeError("private provider failure"),
        ):
            with self.assertLogs("ai_agent.runs", level="INFO") as logs:
                with self.assertRaisesRegex(RuntimeError, "private provider failure"):
                    service.create_run(session.id, "private prompt")

        owner_observations = service.observations(principal_id="user-1")
        other_observations = service.observations(principal_id="user-2")
        self.assertEqual(1, len(owner_observations))
        self.assertEqual("failed", owner_observations[0].status)
        self.assertEqual(0, len(other_observations))
        self.assertNotIn("private", logs.output[0])

    def test_anonymous_session_stores_only_capability_digest(self) -> None:
        service = InMemoryRunService()
        created = service.create_session()

        self.assertIsNotNone(created.access_token)
        self.assertNotIn(created.access_token or "", repr(created.session))
        self.assertFalse(service.has_session(created.session.id))
        self.assertFalse(
            service.has_session(created.session.id, access_token="incorrect")
        )
        self.assertTrue(
            service.has_session(
                created.session.id,
                access_token=created.access_token,
            )
        )


if __name__ == "__main__":
    unittest.main()
