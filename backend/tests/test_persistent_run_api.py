from __future__ import annotations

import asyncio
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient

from backend.app.container import ApplicationContainer
from backend.app.domain.run import RunRecord, RunStatus
from backend.app.main import create_app
from backend.app.security import Principal, StaticTokenAuthenticator
from backend.app.settings import Settings
from backend.app.stores import PauseCommit, StartCommit


class PersistentRunApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.authenticator = StaticTokenAuthenticator(
            {
                "user-one-token": Principal("user-one"),
                "user-two-token": Principal("user-two"),
            }
        )
        self.container = ApplicationContainer.create(
            settings=Settings.from_environment({}),
            authenticator=self.authenticator,
        )
        self.client = TestClient(create_app(container=self.container))

    def test_anonymous_create_replays_idempotently_and_lists_session_runs(self) -> None:
        key = "a" * 32
        first = self.client.post(
            "/api/durable/runs",
            headers={"Idempotency-Key": key},
            json={"message": "hello"},
        )
        second = self.client.post(
            "/api/durable/runs",
            headers={"Idempotency-Key": key},
            json={"message": "hello"},
        )

        self.assertEqual(202, first.status_code)
        self.assertEqual(202, second.status_code)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(first.json()["id"], first.json()["run_id"])
        self.assertEqual(key, first.json()["session_capability"])
        self.assertIsNone(second.json()["session_capability"])
        self.assertNotIn(key, repr(self.container.run_store))

        listed = self.client.get(
            f"/api/durable/sessions/{first.json()['session_id']}/runs",
            headers={"X-Session-Token": key},
        )
        self.assertEqual(200, listed.status_code)
        self.assertEqual([first.json()["id"]], [item["id"] for item in listed.json()])

    def test_anonymous_capability_and_authenticated_owner_are_isolated(self) -> None:
        key = "b" * 32
        anonymous = self.client.post(
            "/api/durable/runs",
            headers={"Idempotency-Key": key},
            json={"message": "anonymous"},
        ).json()
        user_one = self.client.post(
            "/api/durable/runs",
            headers={
                "Authorization": "Bearer user-one-token",
                "Idempotency-Key": "user-one-create-key",
            },
            json={"message": "private"},
        ).json()

        self.assertEqual(
            404,
            self.client.get(f"/api/durable/runs/{anonymous['id']}").status_code,
        )
        self.assertEqual(
            404,
            self.client.get(
                f"/api/durable/runs/{anonymous['id']}",
                headers={"Authorization": "Bearer user-one-token"},
            ).status_code,
        )
        self.assertEqual(
            404,
            self.client.get(
                f"/api/durable/runs/{user_one['id']}",
                headers={"Authorization": "Bearer user-two-token"},
            ).status_code,
        )
        self.assertEqual(
            200,
            self.client.get(
                f"/api/durable/runs/{anonymous['id']}",
                headers={"X-Session-Token": key},
            ).status_code,
        )

    def test_same_key_with_different_request_is_a_content_free_conflict(self) -> None:
        key = "c" * 32
        self.client.post(
            "/api/durable/runs",
            headers={"Idempotency-Key": key},
            json={"message": "private original"},
        )

        conflict = self.client.post(
            "/api/durable/runs",
            headers={"Idempotency-Key": key},
            json={"message": "different private input"},
        )

        self.assertEqual(409, conflict.status_code)
        self.assertNotIn("private original", conflict.text)
        self.assertNotIn("different private input", conflict.text)
        self.assertNotIn(key, conflict.text)

    def test_missing_idempotency_key_is_rejected_before_creating_a_run(self) -> None:
        response = self.client.post(
            "/api/durable/runs",
            json={"message": "hello"},
        )

        self.assertEqual(400, response.status_code)
        self.assertEqual(
            (),
            asyncio.run(
                self.container.run_store.list_for_session(
                    "missing",
                    owner_id="anonymous-capability-v1-" + "d" * 64,
                )
            ),
        )

    def test_cancelled_run_cannot_be_reopened(self) -> None:
        run = self._create_run("cancel-run", "cancel-owner", "cancel-session")
        owner_container = ApplicationContainer.create(
            settings=Settings.from_environment({}),
            authenticator=StaticTokenAuthenticator(
                {"owner-token": Principal("cancel-owner")}
            ),
        )
        asyncio.run(owner_container.run_store.create(run))
        owner_client = TestClient(create_app(container=owner_container))
        cancelled = owner_client.post(
            "/api/durable/runs/cancel-run/cancel",
            headers={"Authorization": "Bearer owner-token"},
        )
        repeated = owner_client.post(
            "/api/durable/runs/cancel-run/cancel",
            headers={"Authorization": "Bearer owner-token"},
        )

        self.assertEqual(200, cancelled.status_code)
        self.assertEqual("cancelled", cancelled.json()["status"])
        self.assertEqual(200, repeated.status_code)
        self.assertEqual("cancelled", repeated.json()["status"])

    def test_approval_uses_only_persisted_event_binding(self) -> None:
        run = self._create_run("approval-run", "user-one", "approval-session")

        async def seed() -> RunRecord:
            await self.container.run_store.create(run)
            started = await self.container.event_store.commit_start(
                StartCommit(
                    run_id=run.id,
                    owner_id=run.owner_id,
                    expected_version=0,
                    event_id="approval-started",
                    event_data={"status": "running", "runtime": "manual"},
                )
            )
            paused = await self.container.event_store.commit_pause(
                PauseCommit(
                    run_id=run.id,
                    owner_id=run.owner_id,
                    expected_version=started.record.version,
                    event_id="approval-paused",
                    event_data={
                        "status": "waiting_approval",
                        "approval_id": "approval-1",
                        "tool_call_id": "stored-call",
                        "tool_name": "stored-tool",
                        "arguments_digest": "e" * 64,
                        "expires_at": None,
                    },
                )
            )
            return paused.record

        paused = asyncio.run(seed())
        commands = AsyncMock()
        commands.resume_approval.return_value = paused
        client = TestClient(
            create_app(container=replace(self.container, run_commands=commands))
        )

        response = client.post(
            "/api/durable/runs/approval-run/approvals/approval-1",
            headers={"Authorization": "Bearer user-one-token"},
            json={"decision": "approve", "tool_name": "forged-tool"},
        )

        self.assertEqual(200, response.status_code)
        kwargs = commands.resume_approval.await_args.kwargs
        self.assertEqual("stored-call", kwargs["tool_call_id"])
        self.assertEqual("stored-tool", kwargs["tool_name"])
        self.assertEqual("e" * 64, kwargs["arguments_digest"])
        self.assertEqual("approve", kwargs["decision"])

    @staticmethod
    def _create_run(run_id: str, owner_id: str, session_id: str) -> RunRecord:
        return RunRecord.create(
            run_id=run_id,
            session_id=session_id,
            owner_id=owner_id,
            runtime="manual",
            input_text="hello",
            idempotency_key=f"key-{run_id}",
            created_at=datetime(2026, 8, 28, tzinfo=UTC),
        )
