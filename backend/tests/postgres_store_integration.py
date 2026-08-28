from __future__ import annotations

import asyncio
import hashlib
import json
import os
import selectors
import subprocess
import sys
import threading
import unittest
from datetime import UTC, datetime, timedelta
from unittest.mock import patch
from uuid import uuid4

from fastapi.testclient import TestClient
from psycopg import Error as PsycopgError

from backend.app.agent import RuntimeResult
from backend.app.application_lifecycle import ApplicationLifecycleState
from backend.app.container import ApplicationContainer
from backend.app.main import create_app
from backend.app.domain import Message
from backend.app.domain.run import (
    RunRecord,
    RunStatus,
    ToolExecution,
    ToolExecutionStatus,
)
from backend.app.memory import (
    CorrectMemoryFact,
    DeleteMemoryFact,
    MemoryFactAuditAction,
    MemoryScope,
    PublishTurn,
)
from backend.app.postgres_execution import PostgresExecutionComposition
from backend.app.services.run_recovery import (
    RunRecoveryService,
    RunRecoveryStatus,
)
from backend.app.services.run_recovery_supervisor import (
    RunRecoverySupervisor,
    RunRecoverySupervisorState,
)
from backend.app.services.run_coordinator import RunCoordinator
from backend.app.security import StaticTokenAuthenticator
from backend.app.settings import Settings
from backend.app.stores import (
    EventStore,
    RunLeaseLostError,
    RunLeaseStore,
    RunStore,
    StoreUnavailableError,
    ToolExecutionStore,
)
from backend.app.stores.base import StartCommit
from backend.app.stores.postgres import PostgresPersistence
from backend.app.stores.postgres_async import (
    AsyncPostgresMemoryStore,
    PostgresSyncStoreBridgeState,
)
from backend.app.stores.postgres_migrations import (
    MigrationApplyError,
    MigrationChecksumError,
    MigrationHistoryError,
    SqlMigration,
    apply_postgres_migrations,
    load_sql_migrations,
)
from backend.app.tools import ApprovalResponse
from backend.tests.test_approval_store_contract import ApprovalStoreContract
from backend.tests.test_memory_store_contract import MemoryStoreContract
from backend.tests.test_run_store_contract import RunStoreContract, STORE_NOW
from backend.tests.test_run_lease_store_contract import (
    LEASE_NOW,
    SHORT_LEASE_TTL,
    RunLeaseStoreContract,
)
from backend.tests.test_tool_execution_store_contract import (
    TOOL_STORE_NOW,
    ToolExecutionStoreContract,
)


POSTGRES_DSN = os.environ.get("AI_AGENT_TEST_POSTGRES_DSN", "")

if sys.platform == "win32" and POSTGRES_DSN:
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())


def setUpModule() -> None:
    if not POSTGRES_DSN:
        raise unittest.SkipTest("AI_AGENT_TEST_POSTGRES_DSN is not configured")


class PostgresRunStoreContractTest(
    RunStoreContract,
    unittest.IsolatedAsyncioTestCase,
):
    async def asyncSetUp(self) -> None:
        self.persistence = await PostgresPersistence.open(
            POSTGRES_DSN,
            clock=lambda: STORE_NOW,
        )
        await self.persistence.setup()
        await _reset_app_data(self.persistence)
        await super().asyncSetUp()

    async def asyncTearDown(self) -> None:
        await self.persistence.close()

    async def create_store_pair(self) -> tuple[RunStore, EventStore]:
        return self.persistence.run_store, self.persistence.event_store


class PostgresApprovalStoreContractTest(
    ApprovalStoreContract,
    unittest.IsolatedAsyncioTestCase,
):
    async def create_approval_store(self):
        self.persistence = await PostgresPersistence.open(
            POSTGRES_DSN,
            clock=lambda: self.now,
        )
        await self.persistence.setup()
        await _reset_approval_memory_data(self.persistence)
        return self.persistence.approval_store

    async def asyncTearDown(self) -> None:
        await self.persistence.close()


class PostgresMemoryStoreContractTest(
    MemoryStoreContract,
    unittest.IsolatedAsyncioTestCase,
):
    async def create_memory_store(self, *, message_limit: int):
        self.persistence = await PostgresPersistence.open(
            POSTGRES_DSN,
            message_limit=message_limit,
        )
        await self.persistence.setup()
        await _reset_approval_memory_data(self.persistence)
        return self.persistence.memory_store

    async def asyncTearDown(self) -> None:
        await self.persistence.close()


class PostgresFastApiApplicationTest(unittest.TestCase):
    def test_durable_run_api_replays_and_reads_after_application_restart(self) -> None:
        token = f"postgres-durable-token-{uuid4()}"
        owner_id = f"postgres-durable-owner-{uuid4()}"
        idempotency_key = f"postgres-durable-key-{uuid4()}"
        auth_config = json.dumps(
            {token: {"principal_id": owner_id, "roles": []}}
        )
        settings = Settings.from_environment(
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": POSTGRES_DSN,
            }
        )
        headers = {
            "Authorization": f"Bearer {token}",
            "Idempotency-Key": idempotency_key,
        }

        with patch.dict(
            os.environ,
            {"AI_AGENT_DEMO_AUTH_JSON": auth_config},
            clear=False,
        ):
            first_app = create_app(settings=settings)
            with TestClient(first_app) as client:
                created = client.post(
                    "/api/durable/runs",
                    headers=headers,
                    json={"message": "postgres durable run"},
                )
                replayed = client.post(
                    "/api/durable/runs",
                    headers=headers,
                    json={"message": "postgres durable run"},
                )

                self.assertEqual(202, created.status_code)
                self.assertEqual(202, replayed.status_code)
                self.assertEqual(created.json()["id"], replayed.json()["id"])
                self.assertIsNone(created.json()["session_capability"])
                run_id = created.json()["id"]
                session_id = created.json()["session_id"]
                self.assertEqual(
                    200,
                    client.get(
                        f"/api/durable/runs/{run_id}",
                        headers={"Authorization": f"Bearer {token}"},
                    ).status_code,
                )
                self.assertEqual(
                    "PostgresRunStore",
                    type(first_app.state.container.run_store).__name__,
                )

            second_app = create_app(settings=settings)
            with TestClient(second_app) as client:
                listed = client.get(
                    f"/api/durable/sessions/{session_id}/runs",
                    headers={"Authorization": f"Bearer {token}"},
                )

                self.assertEqual(200, listed.status_code)
                self.assertEqual([run_id], [item["id"] for item in listed.json()])

    def test_lifespan_persists_memory_across_application_restart(self) -> None:
        token = "postgres-application-token"
        auth_config = json.dumps(
            {
                token: {
                    "principal_id": "postgres-application-owner",
                    "roles": [],
                }
            }
        )
        settings = Settings.from_environment(
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": POSTGRES_DSN,
            }
        )
        headers = {"Authorization": f"Bearer {token}"}

        with patch.dict(
            os.environ,
            {"AI_AGENT_DEMO_AUTH_JSON": auth_config},
            clear=False,
        ):
            first_app = create_app(settings=settings)
            self.assertIsNone(first_app.state.container)
            with TestClient(first_app) as client:
                created = client.post(
                    "/api/memories",
                    headers=headers,
                    json={
                        "key": "restart-proof",
                        "value": "postgres",
                        "scope": "user",
                        "approved": True,
                    },
                )
                first_container = first_app.state.container
                self.assertEqual(201, created.status_code)
                self.assertEqual(
                    "PostgresRunStore",
                    type(first_container.run_store).__name__,
                )
                self.assertIsInstance(
                    first_container.async_memory_store,
                    AsyncPostgresMemoryStore,
                )
                fact_id = created.json()["id"]

            self.assertEqual(
                ApplicationLifecycleState.CLOSED,
                first_container.lifecycle_state,
            )

            second_app = create_app(settings=settings)
            with TestClient(second_app) as client:
                deleted = client.delete(
                    f"/api/memories/{fact_id}",
                    headers=headers,
                )
                second_container = second_app.state.container
                self.assertEqual(204, deleted.status_code)

            self.assertEqual(
                ApplicationLifecycleState.CLOSED,
                second_container.lifecycle_state,
            )

    def test_versioned_memory_api_changes_main_run_context_across_lifespans(
        self,
    ) -> None:
        token = "postgres-versioned-memory-token"
        owner_id = f"postgres-versioned-owner-{uuid4()}"
        auth_config = json.dumps(
            {
                token: {
                    "principal_id": owner_id,
                    "roles": [],
                }
            }
        )
        settings = Settings.from_environment(
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": POSTGRES_DSN,
            }
        )
        headers = {"Authorization": f"Bearer {token}"}
        original_value = f"incorrect-memory-{uuid4()}"
        corrected_value = f"corrected-memory-{uuid4()}"
        session_id = f"versioned-memory-session-{uuid4()}"
        runtime = _ContextCapturingRuntime()

        with (
            patch.dict(
                os.environ,
                {"AI_AGENT_DEMO_AUTH_JSON": auth_config},
                clear=False,
            ),
            patch(
                "backend.app.container._create_built_in_runtimes",
                return_value={"manual": runtime},
            ),
        ):
            first_app = create_app(settings=settings)
            with TestClient(first_app) as client:
                created = client.post(
                    "/api/memories",
                    headers=headers,
                    json={
                        "key": "restart-context-proof",
                        "value": original_value,
                        "scope": "user",
                        "approved": True,
                    },
                )
                first_container = first_app.state.container
                self.assertEqual(201, created.status_code)
                fact_id = created.json()["id"]

            self.assertEqual(
                ApplicationLifecycleState.CLOSED,
                first_container.lifecycle_state,
            )

            second_app = create_app(settings=settings)
            with TestClient(second_app) as client:
                second_container = second_app.state.container
                fetched = client.get(
                    f"/api/memories/{fact_id}",
                    headers=headers,
                )
                corrected = client.patch(
                    f"/api/memories/{fact_id}",
                    headers=headers,
                    json={
                        "expected_version": 0,
                        "value": corrected_value,
                        "approved": True,
                    },
                )
                self.assertEqual(200, fetched.status_code)
                self.assertEqual(original_value, fetched.json()["value"])
                self.assertEqual(0, fetched.json()["version"])
                self.assertEqual(200, corrected.status_code)
                self.assertEqual(1, corrected.json()["version"])

                before_delete = _new_context_run(
                    owner_id=owner_id,
                    session_id=session_id,
                    label="before-delete",
                )
                completed = client.portal.call(
                    _create_and_execute_run,
                    second_container,
                    before_delete,
                )
                self.assertEqual(RunStatus.COMPLETED, completed.status)
                self.assertIn(corrected_value, runtime.prompt_contexts[-1])
                self.assertNotIn(original_value, runtime.prompt_contexts[-1])

                deleted = client.delete(
                    f"/api/memories/{fact_id}?expected_version=1",
                    headers=headers,
                )
                self.assertEqual(204, deleted.status_code)

                after_delete = _new_context_run(
                    owner_id=owner_id,
                    session_id=session_id,
                    label="after-delete",
                )
                completed = client.portal.call(
                    _create_and_execute_run,
                    second_container,
                    after_delete,
                )
                self.assertEqual(RunStatus.COMPLETED, completed.status)
                self.assertNotIn(corrected_value, runtime.prompt_contexts[-1])
                self.assertNotIn(original_value, runtime.prompt_contexts[-1])

            self.assertEqual(
                ApplicationLifecycleState.CLOSED,
                second_container.lifecycle_state,
            )

            third_app = create_app(settings=settings)
            with TestClient(third_app) as client:
                third_container = third_app.state.container
                self.assertEqual(
                    [],
                    client.get("/api/memories", headers=headers).json(),
                )
                audit = client.get(
                    f"/api/memories/{fact_id}/audit",
                    headers=headers,
                )
                self.assertEqual(200, audit.status_code)
                self.assertEqual(
                    ["created", "corrected", "deleted"],
                    [record["action"] for record in audit.json()],
                )
                self.assertNotIn(original_value, audit.text)
                self.assertNotIn(corrected_value, audit.text)

            self.assertEqual(
                ApplicationLifecycleState.CLOSED,
                third_container.lifecycle_state,
            )


class PostgresApplicationContainerTest(unittest.IsolatedAsyncioTestCase):
    async def test_approval_is_granted_and_consumed_through_async_facade(
        self,
    ) -> None:
        tool_call_id = f"application-approval-{uuid4()}"
        arguments = {"report_id": "application-report"}
        settings = Settings.from_environment(
            {
                "AI_AGENT_PERSISTENCE": "postgres",
                "AI_AGENT_POSTGRES_DSN": POSTGRES_DSN,
            }
        )

        container = await ApplicationContainer.open(
            settings=settings,
            authenticator=StaticTokenAuthenticator(),
        )
        await container.start()
        try:
            await container.async_approval_store.grant(
                principal_id="postgres-approval-owner",
                tool_call_id=tool_call_id,
                tool_name="publish_report",
                arguments=arguments,
            )
            first = await container.async_approval_store.consume(
                principal_id="postgres-approval-owner",
                tool_call_id=tool_call_id,
                tool_name="publish_report",
                arguments=arguments,
            )
            replay = await container.async_approval_store.consume(
                principal_id="postgres-approval-owner",
                tool_call_id=tool_call_id,
                tool_name="publish_report",
                arguments=arguments,
            )
        finally:
            await container.close()

        self.assertTrue(first.approved)
        self.assertFalse(replay.approved)
        self.assertEqual(ApplicationLifecycleState.CLOSED, container.lifecycle_state)


class PostgresAsyncApprovalMemoryTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.persistence = await PostgresPersistence.open(
            POSTGRES_DSN,
            min_size=1,
            max_size=1,
            timeout=0.05,
            sync_operation_timeout_ms=1_000,
        )
        await self.persistence.setup()
        await _reset_approval_memory_data(self.persistence)

    async def asyncTearDown(self) -> None:
        await self.persistence.close()

    async def test_async_facades_execute_real_approval_and_memory_transactions(
        self,
    ) -> None:
        approval = self.persistence.async_approval_store
        memory = self.persistence.async_memory_store
        arguments = {"document_id": "async-fixture-document"}
        request = await approval.request(
            run_id="async-facade-run",
            principal_id="async-facade-owner",
            tool_call_id="async-facade-call",
            tool_name="publish_report",
            arguments=arguments,
        )
        resolution = await approval.resolve(
            approval_id=request.id,
            run_id=request.run_id,
            principal_id=request.principal_id,
            tool_call_id=request.tool_call_id,
            tool_name=request.tool_name,
            arguments_digest=request.arguments_digest,
            decision=ApprovalResponse.APPROVE,
        )
        approved_arguments = await approval.approved_arguments(resolution)
        first = await approval.consume(
            principal_id=request.principal_id,
            run_id=request.run_id,
            tool_call_id=request.tool_call_id,
            tool_name=request.tool_name,
            arguments=arguments,
        )
        second = await approval.consume(
            principal_id=request.principal_id,
            run_id=request.run_id,
            tool_call_id=request.tool_call_id,
            tool_name=request.tool_name,
            arguments=arguments,
        )
        turn = PublishTurn(
            run_id="async-facade-run",
            session_id="async-facade-session",
            user_message=Message(role="user", content="async fixture message"),
            assistant_message=Message(
                role="assistant",
                content="async fixture answer",
            ),
        )
        publication = await memory.publish_turn(turn)
        fact = await memory.remember(
            owner_id=request.principal_id,
            key="language",
            value="Chinese",
            scope=MemoryScope.USER,
            approved=True,
        )
        corrected = await memory.correct_fact(
            CorrectMemoryFact(
                fact_id=fact.id,
                owner_id=fact.owner_id,
                expected_version=fact.version,
                value="French",
                approved=True,
            )
        )
        deleted = await memory.delete_fact(
            DeleteMemoryFact(
                fact_id=corrected.id,
                owner_id=corrected.owner_id,
                expected_version=corrected.version,
            )
        )
        audit = await memory.fact_audit(
            fact.id,
            owner_id=request.principal_id,
        )

        self.assertEqual(arguments, approved_arguments)
        self.assertTrue(first.approved)
        self.assertFalse(second.approved)
        self.assertTrue(publication.created)
        self.assertEqual(
            (turn.user_message, turn.assistant_message),
            await memory.messages("async-facade-session"),
        )
        self.assertEqual(2, deleted.version)
        self.assertEqual((), await memory.facts(request.principal_id))
        self.assertEqual(
            (
                MemoryFactAuditAction.CREATED,
                MemoryFactAuditAction.CORRECTED,
                MemoryFactAuditAction.DELETED,
            ),
            tuple(record.action for record in audit),
        )

    async def test_exhausted_shared_sync_pool_returns_stable_store_error(
        self,
    ) -> None:
        entered = threading.Event()
        release = threading.Event()

        def occupy_only_connection() -> None:
            with self.persistence.sync_pool.connection():
                entered.set()
                release.wait()

        holder = asyncio.create_task(asyncio.to_thread(occupy_only_connection))
        try:
            self.assertTrue(
                await asyncio.wait_for(
                    asyncio.to_thread(entered.wait, 1),
                    timeout=1.1,
                )
            )
            with self.assertRaises(StoreUnavailableError) as raised:
                await self.persistence.async_memory_store.messages(
                    "pool-exhaustion-session"
                )
            self.assertEqual("store_unavailable", raised.exception.code)
        finally:
            release.set()
            await holder


class PostgresToolExecutionStoreContractTest(
    ToolExecutionStoreContract,
    unittest.IsolatedAsyncioTestCase,
):
    async def create_store_bundle(
        self,
    ) -> tuple[RunStore, ToolExecutionStore]:
        self.persistence = await PostgresPersistence.open(
            POSTGRES_DSN,
            clock=lambda: TOOL_STORE_NOW,
        )
        await self.persistence.setup()
        await _reset_app_data(self.persistence)
        return (
            self.persistence.run_store,
            self.persistence.tool_execution_store,
        )

    async def asyncTearDown(self) -> None:
        await self.persistence.close()


class PostgresRunLeaseStoreContractTest(
    RunLeaseStoreContract,
    unittest.IsolatedAsyncioTestCase,
):
    async def create_store_bundle(
        self,
    ) -> tuple[RunStore, RunLeaseStore]:
        self.persistence = await PostgresPersistence.open(
            POSTGRES_DSN,
            clock=lambda: LEASE_NOW + timedelta(seconds=1),
        )
        await self.persistence.setup()
        await _reset_app_data(self.persistence)
        return self.persistence.run_store, self.persistence.run_lease_store

    async def expire_short_lease(self) -> None:
        await asyncio.sleep(SHORT_LEASE_TTL.total_seconds() + 0.2)

    async def asyncTearDown(self) -> None:
        await self.persistence.close()

    async def test_raw_lease_token_is_not_persisted(self) -> None:
        run = await self._create_running_run()
        lease = await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=timedelta(seconds=10),
        )
        async with self.persistence.pool.connection() as connection:
            result = await connection.execute(
                """
                SELECT lease_token_digest
                FROM agent_run_leases
                WHERE run_id = %s
                """,
                (run.id,),
            )
            row = await result.fetchone()

        raw_token = lease.token.reveal()
        self.assertIsNotNone(row)
        self.assertNotEqual(raw_token, row["lease_token_digest"])
        self.assertEqual(
            hashlib.sha256(raw_token.encode("ascii")).hexdigest(),
            row["lease_token_digest"].strip(),
        )


class PostgresRunCoordinatorLeaseTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.persistence = await PostgresPersistence.open(
            POSTGRES_DSN,
            clock=lambda: LEASE_NOW + timedelta(seconds=1),
        )
        await self.persistence.setup()
        await _reset_app_data(self.persistence)

    async def asyncTearDown(self) -> None:
        await self.persistence.close()

    async def test_coordinator_heartbeats_and_releases_real_postgres_lease(
        self,
    ) -> None:
        run = await self._create_run(run_id="coordinator-heartbeat")
        runtime = PostgresGatedRuntime()
        coordinator = self._coordinator(runtime)
        execution = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)

        version = await self._wait_for_lease_version(run.id, minimum=1)
        runtime.release.set()
        completed = await asyncio.wait_for(execution, timeout=1)

        self.assertGreaterEqual(version, 1)
        self.assertEqual(RunStatus.COMPLETED, completed.status)
        self.assertEqual(0, await self._lease_count(run.id))

    async def test_lost_postgres_lease_fails_closed_then_scanner_recovers(
        self,
    ) -> None:
        run = await self._create_run(run_id="coordinator-lease-lost")
        runtime = PostgresSleepingRuntime()
        coordinator = self._coordinator(runtime)
        execution = asyncio.create_task(
            coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)
        await self._expire_lease(run.id)

        with self.assertRaises(RunLeaseLostError):
            await asyncio.wait_for(execution, timeout=1)
        running = await self.persistence.run_store.get(
            run.id,
            owner_id=run.owner_id,
        )

        recovered = await RunRecoveryService(
            run_store=self.persistence.run_store,
            event_store=self.persistence.event_store,
            tool_execution_store=self.persistence.tool_execution_store,
            run_lease_store=self.persistence.run_lease_store,
        ).scan_once(limit=1, recovery_ttl=timedelta(seconds=1))
        stored = await self.persistence.run_store.get(
            run.id,
            owner_id=run.owner_id,
        )

        self.assertTrue(runtime.cancelled.is_set())
        self.assertEqual(RunStatus.RUNNING, running.status)
        self.assertEqual(RunRecoveryStatus.RECOVERED, recovered[0].status)
        self.assertEqual(RunStatus.FAILED, stored.status)
        self.assertEqual("run_orphaned", stored.failure.code)
        self.assertEqual(0, await self._lease_count(run.id))

    async def test_supervisor_recovers_expired_lease_without_manual_scan(
        self,
    ) -> None:
        run = await self._create_run(run_id="supervisor-recovery")
        running = (
            await self.persistence.event_store.commit_start(
                StartCommit(
                    run_id=run.id,
                    owner_id=run.owner_id,
                    expected_version=run.version,
                    event_id="supervisor-recovery-started",
                    event_data={"status": "running", "runtime": "manual"},
                )
            )
        ).record
        await self.persistence.run_lease_store.acquire(
            running.id,
            owner_id=running.owner_id,
            ttl=timedelta(seconds=1),
        )
        await self._expire_lease(running.id)
        supervisor = RunRecoverySupervisor(
            service=RunRecoveryService(
                run_store=self.persistence.run_store,
                event_store=self.persistence.event_store,
                tool_execution_store=self.persistence.tool_execution_store,
                run_lease_store=self.persistence.run_lease_store,
            ),
            scan_interval=timedelta(milliseconds=20),
            scan_limit=1,
            recovery_ttl=timedelta(seconds=1),
        )

        await supervisor.start()
        try:
            stored = await self._wait_for_run_status(
                running.id,
                status=RunStatus.FAILED,
            )
            await self._wait_for_lease_count(running.id, expected=0)
        finally:
            await supervisor.close()

        self.assertEqual(RunRecoverySupervisorState.CLOSED, supervisor.state)
        self.assertEqual("run_orphaned", stored.failure.code)
        self.assertEqual(0, await self._lease_count(running.id))

    async def _create_run(self, *, run_id: str) -> RunRecord:
        run = RunRecord.create(
            run_id=run_id,
            session_id="coordinator-session",
            owner_id="coordinator-owner",
            runtime="manual",
            input_text="private coordinator input",
            idempotency_key=f"{run_id}-key",
            created_at=LEASE_NOW,
        )
        return (await self.persistence.run_store.create(run)).record

    def _coordinator(self, runtime) -> RunCoordinator:
        return RunCoordinator(
            run_store=self.persistence.run_store,
            event_store=self.persistence.event_store,
            runtimes={"manual": runtime},
            run_lease_store=self.persistence.run_lease_store,
            run_timeout_ms=2_000,
            lease_ttl_ms=500,
            lease_heartbeat_interval_ms=50,
        )

    async def _wait_for_lease_version(self, run_id: str, *, minimum: int) -> int:
        deadline = asyncio.get_running_loop().time() + 1
        while asyncio.get_running_loop().time() < deadline:
            async with self.persistence.pool.connection() as connection:
                result = await connection.execute(
                    "SELECT version FROM agent_run_leases WHERE run_id = %s",
                    (run_id,),
                )
                row = await result.fetchone()
            if row is not None and row["version"] >= minimum:
                return row["version"]
            await asyncio.sleep(0.01)
        self.fail("lease heartbeat version did not advance")

    async def _wait_for_run_status(
        self,
        run_id: str,
        *,
        status: RunStatus,
    ) -> RunRecord:
        deadline = asyncio.get_running_loop().time() + 1
        while asyncio.get_running_loop().time() < deadline:
            run = await self.persistence.run_store.get(
                run_id,
                owner_id="coordinator-owner",
            )
            if run is not None and run.status is status:
                return run
            await asyncio.sleep(0.01)
        self.fail(f"Run did not reach {status.value}")

    async def _wait_for_lease_count(
        self,
        run_id: str,
        *,
        expected: int,
    ) -> None:
        deadline = asyncio.get_running_loop().time() + 1
        while asyncio.get_running_loop().time() < deadline:
            if await self._lease_count(run_id) == expected:
                return
            await asyncio.sleep(0.01)
        self.fail(f"Run lease count did not reach {expected}")

    async def _expire_lease(self, run_id: str) -> None:
        async with self.persistence.pool.connection() as connection:
            await connection.execute(
                """
                UPDATE agent_run_leases
                SET acquired_at = clock_timestamp() - INTERVAL '3 seconds',
                    heartbeat_at = clock_timestamp() - INTERVAL '2 seconds',
                    expires_at = clock_timestamp() - INTERVAL '1 second'
                WHERE run_id = %s
                """,
                (run_id,),
            )

    async def _lease_count(self, run_id: str) -> int:
        async with self.persistence.pool.connection() as connection:
            result = await connection.execute(
                "SELECT COUNT(*) AS count FROM agent_run_leases WHERE run_id = %s",
                (run_id,),
            )
            row = await result.fetchone()
        return row["count"]


class PostgresMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.persistence = await PostgresPersistence.open(POSTGRES_DSN)
        await _drop_app_schema(self.persistence)

    async def asyncTearDown(self) -> None:
        await self.persistence.close()

    async def test_first_apply_and_repeat_are_versioned_and_idempotent(self) -> None:
        first = await apply_postgres_migrations(self.persistence.pool)
        second = await apply_postgres_migrations(self.persistence.pool)

        self.assertEqual((1, 2, 3, 4, 5, 6), first)
        self.assertEqual((), second)
        self.assertEqual(
            [1, 2, 3, 4, 5, 6],
            await _applied_versions(self.persistence),
        )

    async def test_sixth_migration_backfills_existing_fact_audit(self) -> None:
        migrations = load_sql_migrations()
        await apply_postgres_migrations(
            self.persistence.pool,
            migrations=migrations[:5],
        )
        async with self.persistence.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO conversation_memory_facts (
                    id,
                    owner_id,
                    key,
                    value,
                    scope,
                    created_at
                ) VALUES (%s, %s, %s, %s, %s, %s)
                """,
                (
                    "legacy-memory-fact",
                    "legacy-memory-owner",
                    "language",
                    "Chinese",
                    MemoryScope.USER.value,
                    STORE_NOW,
                ),
            )

        applied = await apply_postgres_migrations(self.persistence.pool)
        audit = self.persistence.memory_store.fact_audit(
            "legacy-memory-fact",
            owner_id="legacy-memory-owner",
        )
        digest = CorrectMemoryFact(
            fact_id="legacy-memory-fact",
            owner_id="legacy-memory-owner",
            expected_version=0,
            value="Chinese",
            approved=True,
        ).value_digest

        self.assertEqual((6,), applied)
        self.assertEqual(1, len(audit))
        self.assertEqual(0, audit[0].version)
        self.assertEqual(MemoryFactAuditAction.CREATED, audit[0].action)
        self.assertEqual(digest, audit[0].value_digest)

    async def test_changed_applied_migration_is_rejected(self) -> None:
        await apply_postgres_migrations(self.persistence.pool)
        original = load_sql_migrations()[0]
        changed = SqlMigration.from_sql(
            version=original.version,
            name=original.name,
            sql=original.sql + "\nSELECT 1;\n",
        )

        with self.assertRaises(MigrationChecksumError) as raised:
            await apply_postgres_migrations(
                self.persistence.pool,
                migrations=(changed, *load_sql_migrations()[1:]),
            )

        self.assertEqual("migration_checksum_mismatch", raised.exception.code)

    async def test_applied_history_must_be_a_contiguous_prefix(self) -> None:
        await apply_postgres_migrations(self.persistence.pool, migrations=())
        first = load_sql_migrations()[0]
        second = SqlMigration.from_sql(
            version=2,
            name="history_gap",
            sql="SELECT 1;",
        )
        async with self.persistence.pool.connection() as connection:
            await connection.execute(
                """
                INSERT INTO app_schema_migrations (
                    version,
                    name,
                    checksum
                ) VALUES (%s, %s, %s)
                """,
                (second.version, second.name, second.checksum),
            )

        with self.assertRaises(MigrationHistoryError) as raised:
            await apply_postgres_migrations(
                self.persistence.pool,
                migrations=(first, second),
            )

        self.assertEqual("migration_history_invalid", raised.exception.code)

    async def test_failed_pending_migration_rolls_back_ddl_and_version(self) -> None:
        await apply_postgres_migrations(self.persistence.pool)
        migrations = load_sql_migrations()
        broken = SqlMigration.from_sql(
            version=len(migrations) + 1,
            name="broken_transaction",
            sql="""
            CREATE TABLE migration_should_rollback (id integer PRIMARY KEY);
            SELECT missing_column FROM missing_migration_source;
            """,
        )

        with self.assertRaises(MigrationApplyError) as raised:
            await apply_postgres_migrations(
                self.persistence.pool,
                migrations=(*migrations, broken),
            )

        self.assertEqual("migration_apply_failed", raised.exception.code)
        self.assertEqual(
            [1, 2, 3, 4, 5, 6],
            await _applied_versions(self.persistence),
        )
        self.assertIsNone(
            await _relation_name(self.persistence, "migration_should_rollback")
        )


class PostgresCheckpointProcessTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        persistence = await PostgresPersistence.open(POSTGRES_DSN)
        try:
            await persistence.setup()
            async with persistence.pool.connection() as connection:
                await connection.execute(
                    "TRUNCATE checkpoints, checkpoint_blobs, checkpoint_writes"
                )
        finally:
            await persistence.close()

    async def test_checkpoint_survives_two_distinct_python_processes(self) -> None:
        first = await _run_checkpoint_probe("write")
        second = await _run_checkpoint_probe("resume")

        self.assertNotEqual(first.pop("process_id"), second.pop("process_id"))
        self.assertEqual(
            {
                "phase": "write",
                "before_count": 0,
                "after_count": 1,
                "answer": "write",
            },
            first,
        )
        self.assertEqual(
            {
                "phase": "resume",
                "before_count": 1,
                "after_count": 2,
                "answer": "resume",
            },
            second,
        )


class PostgresApprovalMemoryProcessTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        persistence = await PostgresPersistence.open(POSTGRES_DSN)
        try:
            await persistence.setup()
            await _reset_approval_memory_data(persistence)
        finally:
            await persistence.close()

    async def test_private_approval_and_memory_survive_process_restart(
        self,
    ) -> None:
        first = await _run_state_probe("write")
        second = await _run_state_probe(
            "resume",
            approval_id=first["approval_id"],
            fact_id=first["fact_id"],
        )

        self.assertNotEqual(first["process_id"], second["process_id"])
        self.assertEqual(
            {
                "phase",
                "process_id",
                "approval_id",
                "fact_id",
                "turn_created",
            },
            set(first),
        )
        self.assertEqual("write", first["phase"])
        self.assertTrue(first["turn_created"])
        self.assertEqual(
            {
                "phase": "resume",
                "process_id": second["process_id"],
                "arguments_recovered": True,
                "approval_consumed": True,
                "replay_reason": "approval_already_consumed",
                "messages_recovered": 2,
                "turn_created": False,
                "facts_recovered": 1,
                "fact_deleted": True,
            },
            second,
        )


class PostgresMemoryTurnReplayProcessTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        persistence = await PostgresPersistence.open(POSTGRES_DSN)
        try:
            await persistence.setup()
            await _reset_app_data(persistence)
            await _reset_approval_memory_data(persistence)
        finally:
            await persistence.close()

    async def test_terminal_run_replay_repairs_missing_turn_after_restart(
        self,
    ) -> None:
        prepared = await _run_turn_replay_probe("prepare")
        replayed = await _run_turn_replay_probe("replay")

        self.assertNotEqual(prepared["process_id"], replayed["process_id"])
        self.assertEqual(
            {
                "phase": "prepare",
                "process_id": prepared["process_id"],
                "run_status": "completed",
                "messages": 0,
            },
            prepared,
        )
        self.assertEqual(
            {
                "phase": "replay",
                "process_id": replayed["process_id"],
                "run_status": "completed",
                "messages": 2,
                "runtime_calls": 0,
            },
            replayed,
        )


class PostgresMemoryFactAuditProcessTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        persistence = await PostgresPersistence.open(POSTGRES_DSN)
        try:
            await persistence.setup()
            await _reset_approval_memory_data(persistence)
        finally:
            await persistence.close()

    async def test_correction_delete_and_audit_survive_process_restarts(
        self,
    ) -> None:
        prepared = await _run_fact_audit_probe("prepare")
        corrected = await _run_fact_audit_probe(
            "correct",
            fact_id=prepared["fact_id"],
        )
        deleted = await _run_fact_audit_probe(
            "delete",
            fact_id=prepared["fact_id"],
        )
        audited = await _run_fact_audit_probe(
            "audit",
            fact_id=prepared["fact_id"],
        )

        self.assertEqual(
            4,
            len(
                {
                    prepared["process_id"],
                    corrected["process_id"],
                    deleted["process_id"],
                    audited["process_id"],
                }
            ),
        )
        self.assertEqual(0, prepared["version"])
        self.assertEqual(1, corrected["version"])
        self.assertEqual(2, deleted["version"])
        self.assertEqual(
            {
                "phase": "audit",
                "process_id": audited["process_id"],
                "active_facts": 0,
                "audit_actions": ["created", "corrected", "deleted"],
                "audit_versions": [0, 1, 2],
                "digests_valid": True,
            },
            audited,
        )


class PostgresApprovalTransactionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.persistence = await PostgresPersistence.open(
            POSTGRES_DSN,
            clock=lambda: STORE_NOW,
        )
        await self.persistence.setup()
        await _reset_approval_memory_data(self.persistence)

    async def asyncTearDown(self) -> None:
        await self.persistence.close()

    async def test_grant_insert_failure_rolls_back_resolution(self) -> None:
        request = self.persistence.approval_store.request(
            run_id="approval-transaction-run",
            principal_id="approval-transaction-owner",
            tool_call_id="approval-transaction-fault-call",
            tool_name="publish_report",
            arguments={"document_id": "fixture-document"},
            expires_in=timedelta(minutes=5),
        )
        await _install_approval_grant_failure_trigger(self.persistence)
        try:
            with self.assertRaises(StoreUnavailableError):
                self.persistence.approval_store.resolve(
                    approval_id=request.id,
                    run_id=request.run_id,
                    principal_id=request.principal_id,
                    tool_call_id=request.tool_call_id,
                    tool_name=request.tool_name,
                    arguments_digest=request.arguments_digest,
                    decision=ApprovalResponse.APPROVE,
                )
        finally:
            await _remove_approval_grant_failure_trigger(self.persistence)

        self.assertIsNone(
            self.persistence.approval_store.get_resolution(
                approval_id=request.id,
                run_id=request.run_id,
                principal_id=request.principal_id,
            )
        )
        decision = self.persistence.approval_store.consume(
            principal_id=request.principal_id,
            run_id=request.run_id,
            tool_call_id=request.tool_call_id,
            tool_name=request.tool_name,
            arguments={"document_id": "fixture-document"},
        )
        self.assertFalse(decision.approved)
        self.assertEqual("exact_call_approval_missing", decision.reason)


class PostgresMemoryTurnTransactionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.persistence = await PostgresPersistence.open(
            POSTGRES_DSN,
            clock=lambda: STORE_NOW,
        )
        await self.persistence.setup()
        await _reset_approval_memory_data(self.persistence)

    async def asyncTearDown(self) -> None:
        await self.persistence.close()

    async def test_concurrent_same_turn_has_one_create_and_one_pair(self) -> None:
        command = _published_turn("memory-turn-concurrent")

        first, second = await asyncio.gather(
            asyncio.to_thread(self.persistence.memory_store.publish_turn, command),
            asyncio.to_thread(self.persistence.memory_store.publish_turn, command),
        )

        self.assertEqual([False, True], sorted((first.created, second.created)))
        self.assertEqual(
            (command.user_message, command.assistant_message),
            self.persistence.memory_store.messages(command.session_id),
        )
        self.assertEqual(
            1,
            await _conversation_turn_publication_count(
                self.persistence,
                command.run_id,
            ),
        )

    async def test_second_message_failure_rolls_back_pair_and_ledger(self) -> None:
        command = _published_turn(
            "memory-turn-rollback",
            session_id="memory-turn-fault-session",
        )
        await _install_memory_turn_failure_trigger(self.persistence)
        try:
            with self.assertRaises(StoreUnavailableError):
                self.persistence.memory_store.publish_turn(command)
        finally:
            await _remove_memory_turn_failure_trigger(self.persistence)

        self.assertEqual(
            (),
            self.persistence.memory_store.messages(command.session_id),
        )
        self.assertEqual(
            0,
            await _conversation_turn_publication_count(
                self.persistence,
                command.run_id,
            ),
        )

        retried = self.persistence.memory_store.publish_turn(command)
        self.assertTrue(retried.created)
        self.assertEqual(
            (command.user_message, command.assistant_message),
            self.persistence.memory_store.messages(command.session_id),
        )


class PostgresMemoryFactTransactionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.persistence = await PostgresPersistence.open(
            POSTGRES_DSN,
            clock=lambda: STORE_NOW,
        )
        await self.persistence.setup()
        await _reset_approval_memory_data(self.persistence)

    async def asyncTearDown(self) -> None:
        await self.persistence.close()

    async def test_audit_insert_failure_rolls_back_correction(self) -> None:
        fact = self.persistence.memory_store.remember(
            owner_id="memory-fact-transaction-owner",
            key="language",
            value="English",
            scope=MemoryScope.USER,
            approved=True,
        )
        command = CorrectMemoryFact(
            fact_id=fact.id,
            owner_id=fact.owner_id,
            expected_version=fact.version,
            value="Chinese",
            approved=True,
        )
        await _install_memory_fact_audit_failure_trigger(self.persistence)
        try:
            with self.assertRaises(StoreUnavailableError):
                self.persistence.memory_store.correct_fact(command)
        finally:
            await _remove_memory_fact_audit_failure_trigger(self.persistence)

        self.assertEqual(
            (fact,),
            self.persistence.memory_store.facts(fact.owner_id),
        )
        self.assertEqual(
            1,
            len(self.persistence.memory_store.fact_audit(
                fact.id,
                owner_id=fact.owner_id,
            )),
        )

        corrected = self.persistence.memory_store.correct_fact(command)
        self.assertEqual(1, corrected.version)
        self.assertEqual("Chinese", corrected.value)

    async def test_audit_rows_reject_update_and_delete(self) -> None:
        fact = self.persistence.memory_store.remember(
            owner_id="memory-fact-audit-owner",
            key="language",
            value="Chinese",
            scope=MemoryScope.USER,
            approved=True,
        )

        for statement in (
            """
            UPDATE conversation_memory_fact_audit
            SET action = 'deleted'
            WHERE fact_id = %s
            """,
            """
            DELETE FROM conversation_memory_fact_audit
            WHERE fact_id = %s
            """,
        ):
            with self.subTest(statement=statement.strip().split()[0]):
                async with self.persistence.pool.connection() as connection:
                    with self.assertRaises(PsycopgError):
                        await connection.execute(statement, (fact.id,))

        audit = self.persistence.memory_store.fact_audit(
            fact.id,
            owner_id=fact.owner_id,
        )
        self.assertEqual(1, len(audit))
        self.assertEqual(MemoryFactAuditAction.CREATED, audit[0].action)

    async def test_delete_clears_active_content_but_keeps_digest_audit(self) -> None:
        fact = self.persistence.memory_store.remember(
            owner_id="memory-fact-delete-owner",
            key="private-key",
            value="private value",
            scope=MemoryScope.USER,
            approved=True,
        )

        deleted = self.persistence.memory_store.delete_fact(
            DeleteMemoryFact(
                fact_id=fact.id,
                owner_id=fact.owner_id,
                expected_version=fact.version,
            )
        )
        row = await _memory_fact_row(self.persistence, fact.id)

        self.assertEqual(1, deleted.version)
        self.assertEqual("", row["key"])
        self.assertEqual("", row["value"])
        self.assertEqual(1, row["version"])
        self.assertIsNotNone(row["deleted_at"])
        audit = self.persistence.memory_store.fact_audit(
            fact.id,
            owner_id=fact.owner_id,
        )
        self.assertEqual(2, len(audit))
        self.assertTrue(all(len(item.value_digest) == 64 for item in audit))


class PostgresToolExecutionProcessTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        persistence = await PostgresPersistence.open(POSTGRES_DSN)
        try:
            await persistence.setup()
            await _reset_app_data(persistence)
        finally:
            await persistence.close()

    async def test_committed_result_and_running_unknown_survive_process_exit(
        self,
    ) -> None:
        prepared = await _run_tool_execution_probe("prepare")
        crashed = await _run_tool_execution_probe(
            "settle-crash",
            known_execution_id=prepared["known_execution_id"],
            expected_returncode=17,
        )
        recovered = await _run_tool_execution_probe(
            "recover",
            known_execution_id=prepared["known_execution_id"],
            unknown_execution_id=prepared["unknown_execution_id"],
        )

        self.assertEqual(
            3,
            len(
                {
                    prepared["process_id"],
                    crashed["process_id"],
                    recovered["process_id"],
                }
            ),
        )
        self.assertEqual("prepare", prepared["phase"])
        self.assertEqual("settle-started", crashed["phase"])
        self.assertEqual(
            {
                "phase": "recover",
                "process_id": recovered["process_id"],
                "known_completed": True,
                "known_replayed": True,
                "unknown_reconciled": True,
                "terminal_immutable": True,
            },
            recovered,
        )


class PostgresRunRecoveryProcessTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        persistence = await PostgresPersistence.open(POSTGRES_DSN)
        try:
            await persistence.setup()
            await _reset_app_data(persistence)
        finally:
            await persistence.close()

    async def test_two_process_scanners_claim_one_expired_orphan(self) -> None:
        prepared = await _run_recovery_probe(
            "prepare-crash",
            expected_returncode=17,
        )
        await asyncio.sleep(0.6)
        scans = await _run_recovery_scanners()
        audited = await _run_recovery_probe("audit")

        self.assertEqual("prepare-crash", prepared["phase"])
        self.assertTrue(prepared["lease_created"])
        self.assertEqual(1, sum(item["recovered_count"] for item in scans))
        self.assertEqual({"scan"}, {item["phase"] for item in scans})
        self.assertEqual(
            4,
            len(
                {
                    prepared["process_id"],
                    scans[0]["process_id"],
                    scans[1]["process_id"],
                    audited["process_id"],
                }
            ),
        )
        self.assertEqual(
            {
                "phase": "audit",
                "process_id": audited["process_id"],
                "run_failed": True,
                "running_tool_unknown": True,
                "pending_tool_cancelled": True,
                "single_recovery_event": True,
                "lease_released": True,
            },
            audited,
        )


class PostgresExecutionCompositionProcessTest(
    unittest.IsolatedAsyncioTestCase
):
    async def asyncSetUp(self) -> None:
        persistence = await PostgresPersistence.open(POSTGRES_DSN)
        try:
            await persistence.setup()
            await _reset_app_data(persistence)
        finally:
            await persistence.close()

    async def test_new_composition_process_recovers_crashed_holder(self) -> None:
        holder = await _run_execution_composition_probe(
            "holder-crash",
            expected_returncode=17,
        )
        await asyncio.sleep(0.6)
        recovered = await _run_execution_composition_probe("recover")

        self.assertNotEqual(holder["process_id"], recovered["process_id"])
        self.assertEqual(
            {
                "phase": "holder-crash",
                "process_id": holder["process_id"],
                "runtime_started": True,
            },
            holder,
        )
        self.assertEqual(
            {
                "phase": "recover",
                "process_id": recovered["process_id"],
                "run_failed": True,
                "lease_released": True,
                "single_recovery_event": True,
            },
            recovered,
        )

    async def test_close_waits_for_active_run_before_closing_persistence(
        self,
    ) -> None:
        runtime = PostgresGatedRuntime()
        composition = await PostgresExecutionComposition.open(
            POSTGRES_DSN,
            runtimes={"manual": runtime},
            coordinator_quiesce_timeout_ms=1_000,
            lease_ttl_ms=100,
            lease_heartbeat_interval_ms=20,
            recovery_scan_interval=timedelta(seconds=30),
        )
        run = await _create_composition_run(
            composition,
            run_id="composition-graceful-close-run",
        )
        execution = asyncio.create_task(
            composition.coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)

        closing = asyncio.create_task(composition.close())
        await asyncio.sleep(0.05)
        self.assertFalse(closing.done())
        self.assertIsNotNone(
            await composition.persistence.run_store.get(
                run.id,
                owner_id=run.owner_id,
            )
        )

        runtime.release.set()
        completed = await asyncio.wait_for(execution, timeout=1)
        await asyncio.wait_for(closing, timeout=1)

        audit = await PostgresPersistence.open(POSTGRES_DSN)
        try:
            await audit.setup()
            stored = await audit.run_store.get(run.id, owner_id=run.owner_id)
            lease_count = await _composition_lease_count(audit, run.id)
        finally:
            await audit.close()
        self.assertEqual(RunStatus.COMPLETED, completed.status)
        self.assertEqual(RunStatus.COMPLETED, stored.status)
        self.assertEqual(0, lease_count)

    async def test_close_timeout_leaves_recoverable_run_for_new_composition(
        self,
    ) -> None:
        runtime = PostgresSleepingRuntime()
        composition = await PostgresExecutionComposition.open(
            POSTGRES_DSN,
            runtimes={"manual": runtime},
            coordinator_quiesce_timeout_ms=20,
            lease_ttl_ms=100,
            lease_heartbeat_interval_ms=20,
            recovery_scan_interval=timedelta(seconds=30),
        )
        run = await _create_composition_run(
            composition,
            run_id="composition-timeout-close-run",
        )
        execution = asyncio.create_task(
            composition.coordinator.execute(run.id, owner_id=run.owner_id)
        )
        await asyncio.wait_for(runtime.started.wait(), timeout=1)

        await composition.close()
        with self.assertRaises(asyncio.CancelledError):
            await execution

        audit = await PostgresPersistence.open(POSTGRES_DSN)
        try:
            await audit.setup()
            abandoned = await audit.run_store.get(run.id, owner_id=run.owner_id)
            events = await audit.event_store.list_for_run(
                run.id,
                owner_id=run.owner_id,
            )
            lease_count = await _composition_lease_count(audit, run.id)
        finally:
            await audit.close()
        self.assertTrue(runtime.cancelled.is_set())
        self.assertEqual(RunStatus.RUNNING, abandoned.status)
        self.assertEqual(["run.started"], [event.type for event in events])
        self.assertEqual(1, lease_count)

        await asyncio.sleep(0.12)
        recovering = await PostgresExecutionComposition.open(
            POSTGRES_DSN,
            runtimes={"manual": PostgresGatedRuntime()},
            lease_ttl_ms=100,
            lease_heartbeat_interval_ms=20,
            recovery_scan_interval=timedelta(milliseconds=20),
            recovery_scan_limit=1,
            recovery_ttl=timedelta(milliseconds=100),
        )
        try:
            recovered = await _wait_for_composition_recovery(
                recovering,
                run_id=run.id,
                owner_id=run.owner_id,
            )
        finally:
            await recovering.close()
        self.assertEqual(RunStatus.FAILED, recovered.status)
        self.assertEqual("run_orphaned", recovered.failure.code)

    async def test_close_waits_for_inflight_sync_store_worker(self) -> None:
        composition = await PostgresExecutionComposition.open(
            POSTGRES_DSN,
            runtimes={"manual": PostgresGatedRuntime()},
            recovery_scan_interval=timedelta(seconds=30),
        )
        entered = threading.Event()
        release = threading.Event()
        original_messages = composition.persistence.memory_store.messages

        def blocking_messages(session_id: str) -> tuple[Message, ...]:
            entered.set()
            release.wait()
            return original_messages(session_id)

        composition.persistence.memory_store.messages = blocking_messages
        operation = asyncio.create_task(
            composition.persistence.async_memory_store.messages(
                "composition-sync-worker-session"
            )
        )
        closing: asyncio.Task[None] | None = None
        try:
            self.assertTrue(
                await asyncio.wait_for(
                    asyncio.to_thread(entered.wait, 1),
                    timeout=1.1,
                )
            )
            closing = asyncio.create_task(composition.close())
            await _wait_for_sync_bridge_state(
                composition.persistence,
                PostgresSyncStoreBridgeState.QUIESCING,
            )
            self.assertFalse(closing.done())

            release.set()
            self.assertEqual((), await asyncio.wait_for(operation, timeout=1))
            await asyncio.wait_for(closing, timeout=1)
        finally:
            release.set()
            if not operation.done():
                await asyncio.gather(operation, return_exceptions=True)
            if closing is None:
                await composition.close()
            elif not closing.done():
                await asyncio.gather(closing, return_exceptions=True)


class PostgresRunRecoveryTransactionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.persistence = await PostgresPersistence.open(POSTGRES_DSN)
        await self.persistence.setup()
        await _reset_app_data(self.persistence)

    async def asyncTearDown(self) -> None:
        await self.persistence.close()

    async def test_terminal_event_failure_retries_after_tool_unknown(self) -> None:
        now = datetime.now(UTC)
        run = RunRecord.create(
            run_id="recovery-transaction-run",
            session_id="recovery-transaction-session",
            owner_id="recovery-transaction-owner",
            runtime="manual",
            input_text="private recovery transaction input",
            idempotency_key="private-recovery-transaction-key",
            created_at=now,
        )
        await self.persistence.run_store.create(run)
        running_run = (
            await self.persistence.event_store.commit_start(
                StartCommit(
                    run_id=run.id,
                    owner_id=run.owner_id,
                    expected_version=run.version,
                    event_id="recovery-transaction-started",
                    event_data={"status": "running", "runtime": "manual"},
                )
            )
        ).record
        execution = ToolExecution.create(
            execution_id="recovery-transaction-tool",
            run_id=run.id,
            tool_call_id="recovery-transaction-call",
            tool_name="publish_report",
            arguments={"document_id": "private-transaction-document"},
            side_effecting=True,
            idempotency_key="private-recovery-tool-key",
            created_at=now,
        )
        await self.persistence.tool_execution_store.create(
            execution,
            owner_id=run.owner_id,
        )
        await self.persistence.tool_execution_store.transition(
            execution.id,
            owner_id=run.owner_id,
            expected_version=execution.version,
            target_status=ToolExecutionStatus.RUNNING,
        )
        await self.persistence.run_lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=SHORT_LEASE_TTL,
        )
        await asyncio.sleep(SHORT_LEASE_TTL.total_seconds() + 0.2)
        service = RunRecoveryService(
            run_store=self.persistence.run_store,
            event_store=self.persistence.event_store,
            tool_execution_store=self.persistence.tool_execution_store,
            run_lease_store=self.persistence.run_lease_store,
        )

        await _install_recovery_event_failure_trigger(self.persistence)
        try:
            first = await service.scan_once(
                recovery_ttl=SHORT_LEASE_TTL
            )
        finally:
            await _remove_recovery_event_failure_trigger(self.persistence)

        self.assertEqual(RunRecoveryStatus.FAILED, first[0].status)
        self.assertEqual("store_unavailable", first[0].error_code)
        stored_run = await self.persistence.run_store.get(
            run.id,
            owner_id=run.owner_id,
        )
        stored_tool = await self.persistence.tool_execution_store.get(
            execution.id,
            owner_id=run.owner_id,
        )
        self.assertEqual(RunStatus.RUNNING, stored_run.status)
        self.assertEqual(running_run.version, stored_run.version)
        self.assertEqual(ToolExecutionStatus.UNKNOWN, stored_tool.status)

        await asyncio.sleep(SHORT_LEASE_TTL.total_seconds() + 0.2)
        second = await service.scan_once()

        self.assertEqual(RunRecoveryStatus.RECOVERED, second[0].status)
        recovered = await self.persistence.run_store.get(
            run.id,
            owner_id=run.owner_id,
        )
        events = await self.persistence.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )
        self.assertEqual(RunStatus.FAILED, recovered.status)
        self.assertEqual("run_orphaned", recovered.failure.code)
        self.assertEqual(1, sum(event.type == "run.failed" for event in events))


class PostgresToolExecutionTransactionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.persistence = await PostgresPersistence.open(
            POSTGRES_DSN,
            clock=lambda: STORE_NOW,
        )
        await self.persistence.setup()
        await _reset_app_data(self.persistence)

    async def asyncTearDown(self) -> None:
        await self.persistence.close()

    async def test_settlement_failure_leaves_running_for_unknown_recovery(
        self,
    ) -> None:
        run = RunRecord.create(
            run_id="tool-transaction-run",
            session_id="tool-transaction-session",
            owner_id="tool-transaction-owner",
            runtime="manual",
            input_text="private transaction input",
            idempotency_key="tool-transaction-run-key",
            created_at=STORE_NOW,
        )
        await self.persistence.run_store.create(run)
        running_run = await self.persistence.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=run.version,
            target_status=RunStatus.RUNNING,
        )
        execution = ToolExecution.create(
            execution_id="tool-transaction-execution",
            run_id=running_run.id,
            tool_call_id="tool-transaction-fault-call",
            tool_name="publish_report",
            arguments={"document_id": "private-document"},
            side_effecting=True,
            idempotency_key="private-tool-transaction-key",
            created_at=STORE_NOW,
        )
        await self.persistence.tool_execution_store.create(
            execution,
            owner_id=run.owner_id,
        )
        running = await self.persistence.tool_execution_store.transition(
            execution.id,
            owner_id=run.owner_id,
            expected_version=execution.version,
            target_status=ToolExecutionStatus.RUNNING,
        )

        await _install_tool_settlement_failure_trigger(self.persistence)
        try:
            with self.assertRaises(StoreUnavailableError):
                await self.persistence.tool_execution_store.transition(
                    execution.id,
                    owner_id=run.owner_id,
                    expected_version=running.version,
                    target_status=ToolExecutionStatus.COMPLETED,
                    result={"private": "private-result"},
                    result_summary="document published",
                )
        finally:
            await _remove_tool_settlement_failure_trigger(self.persistence)

        stored = await self.persistence.tool_execution_store.get(
            execution.id,
            owner_id=run.owner_id,
        )
        self.assertEqual(running, stored)
        reconciled = await self.persistence.tool_execution_store.transition(
            execution.id,
            owner_id=run.owner_id,
            expected_version=running.version,
            target_status=ToolExecutionStatus.UNKNOWN,
            error_code="tool_result_unknown",
            public_message="Tool result could not be confirmed",
        )
        self.assertEqual(ToolExecutionStatus.UNKNOWN, reconciled.status)
        self.assertIsNone(reconciled.result_digest)


class PostgresLifecycleTransactionTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.persistence = await PostgresPersistence.open(
            POSTGRES_DSN,
            clock=lambda: STORE_NOW,
        )
        await self.persistence.setup()
        await _reset_app_data(self.persistence)

    async def asyncTearDown(self) -> None:
        await self.persistence.close()

    async def test_event_insert_failure_rolls_back_run_transition(self) -> None:
        run = RunRecord.create(
            run_id="transaction-fault-run",
            session_id="transaction-session",
            owner_id="transaction-owner",
            runtime="manual",
            input_text="private transaction input",
            idempotency_key="transaction-key",
            created_at=STORE_NOW,
        )
        await self.persistence.run_store.create(run)
        await _install_event_failure_trigger(self.persistence)
        try:
            with self.assertRaises(StoreUnavailableError):
                await self.persistence.event_store.commit_start(
                    StartCommit(
                        run_id=run.id,
                        owner_id=run.owner_id,
                        expected_version=run.version,
                        event_id="transaction-fault-event",
                        event_data={"status": "running"},
                    )
                )
        finally:
            await _remove_event_failure_trigger(self.persistence)

        stored = await self.persistence.run_store.get(
            run.id,
            owner_id=run.owner_id,
        )
        events = await self.persistence.event_store.list_for_run(
            run.id,
            owner_id=run.owner_id,
        )
        self.assertEqual(RunStatus.QUEUED, stored.status)
        self.assertEqual(0, stored.version)
        self.assertEqual((), events)


class PostgresUnavailableTest(unittest.IsolatedAsyncioTestCase):
    async def test_unavailable_database_fails_closed_without_memory_fallback(
        self,
    ) -> None:
        unavailable = (
            "postgresql://ai_agent@127.0.0.1:1/ai_agent_test"
            "?sslmode=disable&connect_timeout=1"
        )

        with self.assertRaises(StoreUnavailableError) as raised:
            await PostgresPersistence.open(unavailable, timeout=0.2)

        self.assertEqual("store_unavailable", raised.exception.code)


class _ContextCapturingRuntime:
    def __init__(self) -> None:
        self.prompt_contexts: list[str] = []

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del emit, control
        if not isinstance(request.prompt_context, str):
            raise AssertionError("versioned memory context was not assembled")
        self.prompt_contexts.append(request.prompt_context)
        return RuntimeResult(
            status=RunStatus.COMPLETED,
            answer="context captured",
        )


def _new_context_run(
    *,
    owner_id: str,
    session_id: str,
    label: str,
) -> RunRecord:
    return RunRecord.create(
        run_id=f"versioned-memory-run-{label}-{uuid4()}",
        session_id=session_id,
        owner_id=owner_id,
        runtime="manual",
        input_text=f"inspect memory context {label}",
        idempotency_key=f"versioned-memory-key-{label}-{uuid4()}",
        created_at=datetime.now(UTC),
    )


async def _create_and_execute_run(
    container: ApplicationContainer,
    run: RunRecord,
) -> RunRecord:
    await container.run_store.create(run)
    return await container.run_coordinator.execute(
        run.id,
        owner_id=run.owner_id,
    )


class PostgresGatedRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit, control
        self.started.set()
        await self.release.wait()
        return RuntimeResult(status=RunStatus.COMPLETED, answer="done")


class PostgresSleepingRuntime:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit, control
        self.started.set()
        try:
            await asyncio.Future()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise


async def _create_composition_run(
    composition: PostgresExecutionComposition,
    *,
    run_id: str,
) -> RunRecord:
    run = RunRecord.create(
        run_id=run_id,
        session_id="composition-close-session",
        owner_id="composition-close-owner",
        runtime="manual",
        input_text="private composition close input",
        idempotency_key=f"{run_id}-private-key",
        created_at=datetime.now(UTC),
    )
    await composition.persistence.run_store.create(run)
    return run


async def _wait_for_composition_recovery(
    composition: PostgresExecutionComposition,
    *,
    run_id: str,
    owner_id: str,
) -> RunRecord:
    deadline = asyncio.get_running_loop().time() + 3
    while asyncio.get_running_loop().time() < deadline:
        run = await composition.persistence.run_store.get(
            run_id,
            owner_id=owner_id,
        )
        if (
            run is not None
            and run.status is RunStatus.FAILED
            and run.failure is not None
            and run.failure.code == "run_orphaned"
            and await _composition_lease_count(composition.persistence, run_id) == 0
        ):
            return run
        await asyncio.sleep(0.02)
    raise AssertionError("composition did not recover abandoned run")


async def _composition_lease_count(
    persistence: PostgresPersistence,
    run_id: str,
) -> int:
    async with persistence.pool.connection() as connection:
        result = await connection.execute(
            "SELECT COUNT(*) AS count FROM agent_run_leases WHERE run_id = %s",
            (run_id,),
        )
        row = await result.fetchone()
    if row is None:
        raise AssertionError("lease count query returned no row")
    return row["count"]


async def _wait_for_sync_bridge_state(
    persistence: PostgresPersistence,
    expected: PostgresSyncStoreBridgeState,
) -> None:
    deadline = asyncio.get_running_loop().time() + 1
    while asyncio.get_running_loop().time() < deadline:
        if persistence.sync_store_bridge.state is expected:
            return
        await asyncio.sleep(0)
    raise AssertionError(f"sync Store bridge did not enter {expected.value}")


async def _reset_app_data(persistence: PostgresPersistence) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            TRUNCATE agent_run_events, agent_run_event_sequences, agent_runs
            CASCADE
            """
        )


async def _reset_approval_memory_data(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            TRUNCATE
                tool_approval_grants,
                tool_approval_requests,
                conversation_turn_publications,
                conversation_messages,
                memory_message_sequences,
                conversation_memory_fact_audit,
                conversation_memory_facts
            RESTART IDENTITY
            """
        )


async def _drop_app_schema(persistence: PostgresPersistence) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            DROP TABLE IF EXISTS agent_run_leases CASCADE;
            DROP TABLE IF EXISTS tool_executions CASCADE;
            DROP TABLE IF EXISTS conversation_memory_fact_audit CASCADE;
            DROP TABLE IF EXISTS conversation_memory_facts CASCADE;
            DROP TABLE IF EXISTS conversation_turn_publications CASCADE;
            DROP TABLE IF EXISTS conversation_messages CASCADE;
            DROP TABLE IF EXISTS memory_message_sequences CASCADE;
            DROP TABLE IF EXISTS tool_approval_grants CASCADE;
            DROP TABLE IF EXISTS tool_approval_requests CASCADE;
            DROP TABLE IF EXISTS agent_run_events CASCADE;
            DROP TABLE IF EXISTS agent_run_event_sequences CASCADE;
            DROP TABLE IF EXISTS agent_runs CASCADE;
            DROP TABLE IF EXISTS app_schema_migrations CASCADE;
            DROP FUNCTION IF EXISTS reject_memory_fact_audit_mutation();
            """,
            prepare=False,
        )


async def _install_event_failure_trigger(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            CREATE OR REPLACE FUNCTION m11_reject_fault_event()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.id = 'transaction-fault-event' THEN
                    RAISE EXCEPTION 'injected event insert failure';
                END IF;
                RETURN NEW;
            END;
            $$;

            CREATE TRIGGER m11_reject_fault_event_trigger
            BEFORE INSERT ON agent_run_events
            FOR EACH ROW
            EXECUTE FUNCTION m11_reject_fault_event();
            """,
            prepare=False,
        )


async def _remove_event_failure_trigger(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            DROP TRIGGER IF EXISTS m11_reject_fault_event_trigger
                ON agent_run_events;
            DROP FUNCTION IF EXISTS m11_reject_fault_event();
            """,
            prepare=False,
        )


async def _install_recovery_event_failure_trigger(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            CREATE OR REPLACE FUNCTION m11_reject_recovery_event()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.type = 'run.failed'
                   AND NEW.data ->> 'failure_code' = 'run_orphaned' THEN
                    RAISE EXCEPTION 'injected recovery event failure';
                END IF;
                RETURN NEW;
            END;
            $$;

            CREATE TRIGGER m11_reject_recovery_event_trigger
            BEFORE INSERT ON agent_run_events
            FOR EACH ROW
            EXECUTE FUNCTION m11_reject_recovery_event();
            """,
            prepare=False,
        )


async def _remove_recovery_event_failure_trigger(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            DROP TRIGGER IF EXISTS m11_reject_recovery_event_trigger
                ON agent_run_events;
            DROP FUNCTION IF EXISTS m11_reject_recovery_event();
            """,
            prepare=False,
        )


async def _install_approval_grant_failure_trigger(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            CREATE OR REPLACE FUNCTION m11_reject_fault_approval_grant()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.tool_call_id = 'approval-transaction-fault-call' THEN
                    RAISE EXCEPTION 'injected approval grant failure';
                END IF;
                RETURN NEW;
            END;
            $$;

            CREATE TRIGGER m11_reject_fault_approval_grant_trigger
            BEFORE INSERT OR UPDATE ON tool_approval_grants
            FOR EACH ROW
            EXECUTE FUNCTION m11_reject_fault_approval_grant();
            """,
            prepare=False,
        )


async def _remove_approval_grant_failure_trigger(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            DROP TRIGGER IF EXISTS m11_reject_fault_approval_grant_trigger
                ON tool_approval_grants;
            DROP FUNCTION IF EXISTS m11_reject_fault_approval_grant();
            """,
            prepare=False,
        )


async def _install_memory_turn_failure_trigger(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            CREATE OR REPLACE FUNCTION m11_reject_fault_memory_turn()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.session_id = 'memory-turn-fault-session'
                   AND NEW.role = 'assistant' THEN
                    RAISE EXCEPTION 'injected assistant message failure';
                END IF;
                RETURN NEW;
            END;
            $$;

            CREATE TRIGGER m11_reject_fault_memory_turn_trigger
            BEFORE INSERT ON conversation_messages
            FOR EACH ROW
            EXECUTE FUNCTION m11_reject_fault_memory_turn();
            """,
            prepare=False,
        )


async def _remove_memory_turn_failure_trigger(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            DROP TRIGGER IF EXISTS m11_reject_fault_memory_turn_trigger
                ON conversation_messages;
            DROP FUNCTION IF EXISTS m11_reject_fault_memory_turn();
            """,
            prepare=False,
        )


async def _install_memory_fact_audit_failure_trigger(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            CREATE OR REPLACE FUNCTION m11_reject_fault_memory_fact_audit()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.owner_id = 'memory-fact-transaction-owner'
                   AND NEW.action = 'corrected' THEN
                    RAISE EXCEPTION 'injected memory fact audit failure';
                END IF;
                RETURN NEW;
            END;
            $$;

            CREATE TRIGGER m11_reject_fault_memory_fact_audit_trigger
            BEFORE INSERT ON conversation_memory_fact_audit
            FOR EACH ROW
            EXECUTE FUNCTION m11_reject_fault_memory_fact_audit();
            """,
            prepare=False,
        )


async def _remove_memory_fact_audit_failure_trigger(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            DROP TRIGGER IF EXISTS m11_reject_fault_memory_fact_audit_trigger
                ON conversation_memory_fact_audit;
            DROP FUNCTION IF EXISTS m11_reject_fault_memory_fact_audit();
            """,
            prepare=False,
        )


async def _install_tool_settlement_failure_trigger(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            CREATE OR REPLACE FUNCTION m11_reject_tool_settlement()
            RETURNS trigger
            LANGUAGE plpgsql
            AS $$
            BEGIN
                IF NEW.tool_call_id = 'tool-transaction-fault-call'
                   AND NEW.status = 'completed' THEN
                    RAISE EXCEPTION 'injected tool settlement failure';
                END IF;
                RETURN NEW;
            END;
            $$;

            CREATE TRIGGER m11_reject_tool_settlement_trigger
            BEFORE UPDATE ON tool_executions
            FOR EACH ROW
            EXECUTE FUNCTION m11_reject_tool_settlement();
            """,
            prepare=False,
        )


async def _remove_tool_settlement_failure_trigger(
    persistence: PostgresPersistence,
) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            DROP TRIGGER IF EXISTS m11_reject_tool_settlement_trigger
                ON tool_executions;
            DROP FUNCTION IF EXISTS m11_reject_tool_settlement();
            """,
            prepare=False,
        )


async def _applied_versions(
    persistence: PostgresPersistence,
) -> list[int]:
    async with persistence.pool.connection() as connection:
        result = await connection.execute(
            "SELECT version FROM app_schema_migrations ORDER BY version"
        )
        return [row["version"] for row in await result.fetchall()]


async def _relation_name(
    persistence: PostgresPersistence,
    name: str,
) -> str | None:
    async with persistence.pool.connection() as connection:
        result = await connection.execute(
            "SELECT to_regclass(%s) AS name",
            (name,),
        )
        row = await result.fetchone()
        return row["name"] if row is not None else None


async def _conversation_turn_publication_count(
    persistence: PostgresPersistence,
    run_id: str,
) -> int:
    async with persistence.pool.connection() as connection:
        result = await connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM conversation_turn_publications
            WHERE run_id = %s
            """,
            (run_id,),
        )
        row = await result.fetchone()
    if row is None:
        raise AssertionError("turn publication count query returned no row")
    return row["count"]


async def _memory_fact_row(
    persistence: PostgresPersistence,
    fact_id: str,
):
    async with persistence.pool.connection() as connection:
        result = await connection.execute(
            """
            SELECT key, value, version, deleted_at
            FROM conversation_memory_facts
            WHERE id = %s
            """,
            (fact_id,),
        )
        row = await result.fetchone()
    if row is None:
        raise AssertionError("memory fact row query returned no row")
    return row


def _published_turn(
    run_id: str,
    *,
    session_id: str = "memory-turn-session",
) -> PublishTurn:
    return PublishTurn(
        run_id=run_id,
        session_id=session_id,
        user_message=Message(role="user", content="private turn input"),
        assistant_message=Message(role="assistant", content="private turn answer"),
    )


async def _run_checkpoint_probe(phase: str) -> dict[str, object]:
    return await asyncio.to_thread(_run_checkpoint_probe_sync, phase)


def _run_checkpoint_probe_sync(phase: str) -> dict[str, object]:
    environment = os.environ.copy()
    environment["AI_AGENT_POSTGRES_DSN"] = POSTGRES_DSN
    process = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-B",
            "-m",
            "backend.app.stores.postgres_checkpoint_probe",
            "--phase",
            phase,
            "--run-id",
            "m11-process-restart-run",
            "--owner-id",
            "m11-process-owner",
        ],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise AssertionError(
            f"checkpoint probe failed with code {process.returncode}: "
            f"{process.stderr.decode('utf-8', errors='replace')}"
        )
    if process.stderr:
        raise AssertionError(
            "checkpoint probe wrote stderr: "
            + process.stderr.decode("utf-8", errors="replace")
        )
    return json.loads(process.stdout.decode("utf-8"))


async def _run_state_probe(
    phase: str,
    *,
    approval_id: object | None = None,
    fact_id: object | None = None,
) -> dict[str, object]:
    return await asyncio.to_thread(
        _run_state_probe_sync,
        phase,
        approval_id,
        fact_id,
    )


def _run_state_probe_sync(
    phase: str,
    approval_id: object | None,
    fact_id: object | None,
) -> dict[str, object]:
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-B",
        "-m",
        "backend.app.stores.postgres_state_probe",
        "--phase",
        phase,
    ]
    if approval_id is not None:
        command.extend(("--approval-id", str(approval_id)))
    if fact_id is not None:
        command.extend(("--fact-id", str(fact_id)))
    environment = os.environ.copy()
    environment["AI_AGENT_POSTGRES_DSN"] = POSTGRES_DSN
    process = subprocess.run(
        command,
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise AssertionError(
            f"state probe failed with code {process.returncode}: "
            f"{process.stderr.decode('utf-8', errors='replace')}"
        )
    if process.stderr:
        raise AssertionError(
            "state probe wrote stderr: "
            + process.stderr.decode("utf-8", errors="replace")
        )
    return json.loads(process.stdout.decode("utf-8"))


async def _run_fact_audit_probe(
    phase: str,
    *,
    fact_id: object | None = None,
) -> dict[str, object]:
    return await asyncio.to_thread(
        _run_fact_audit_probe_sync,
        phase,
        fact_id,
    )


def _run_fact_audit_probe_sync(
    phase: str,
    fact_id: object | None,
) -> dict[str, object]:
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-B",
        "-m",
        "backend.app.stores.postgres_fact_audit_probe",
        "--phase",
        phase,
    ]
    if fact_id is not None:
        command.extend(("--fact-id", str(fact_id)))
    environment = os.environ.copy()
    environment["AI_AGENT_POSTGRES_DSN"] = POSTGRES_DSN
    process = subprocess.run(
        command,
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise AssertionError(
            f"fact audit probe failed with code {process.returncode}: "
            f"{process.stderr.decode('utf-8', errors='replace')}"
        )
    if process.stderr:
        raise AssertionError(
            "fact audit probe wrote stderr: "
            + process.stderr.decode("utf-8", errors="replace")
        )
    stdout = process.stdout.decode("utf-8")
    for private_value in ("English", "Chinese", "preferred-language"):
        if private_value in stdout:
            raise AssertionError("fact audit probe exposed private data")
    lines = [line for line in stdout.splitlines() if line]
    if len(lines) != 1:
        raise AssertionError("fact audit probe output is not bounded JSON")
    return json.loads(lines[0])


async def _run_turn_replay_probe(phase: str) -> dict[str, object]:
    return await asyncio.to_thread(_run_turn_replay_probe_sync, phase)


def _run_turn_replay_probe_sync(phase: str) -> dict[str, object]:
    environment = os.environ.copy()
    environment["AI_AGENT_POSTGRES_DSN"] = POSTGRES_DSN
    process = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-B",
            "-m",
            "backend.app.stores.postgres_turn_replay_probe",
            "--phase",
            phase,
        ],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        check=False,
    )
    if process.returncode != 0:
        raise AssertionError(
            f"turn replay probe failed with code {process.returncode}: "
            f"{process.stderr.decode('utf-8', errors='replace')}"
        )
    if process.stderr:
        raise AssertionError(
            "turn replay probe wrote stderr: "
            + process.stderr.decode("utf-8", errors="replace")
        )
    stdout = process.stdout.decode("utf-8")
    for private_value in (
        "private replay fixture input",
        "private replay fixture answer",
    ):
        if private_value in stdout:
            raise AssertionError("turn replay probe exposed private data")
    lines = [line for line in stdout.splitlines() if line]
    if len(lines) != 1:
        raise AssertionError("turn replay probe output is not bounded JSON")
    return json.loads(lines[0])


async def _run_tool_execution_probe(
    phase: str,
    *,
    known_execution_id: object | None = None,
    unknown_execution_id: object | None = None,
    expected_returncode: int = 0,
) -> dict[str, object]:
    return await asyncio.to_thread(
        _run_tool_execution_probe_sync,
        phase,
        known_execution_id,
        unknown_execution_id,
        expected_returncode,
    )


def _run_tool_execution_probe_sync(
    phase: str,
    known_execution_id: object | None,
    unknown_execution_id: object | None,
    expected_returncode: int,
) -> dict[str, object]:
    command = [
        sys.executable,
        "-X",
        "utf8",
        "-B",
        "-m",
        "backend.app.stores.postgres_tool_execution_probe",
        "--phase",
        phase,
    ]
    if known_execution_id is not None:
        command.extend(("--known-execution-id", str(known_execution_id)))
    if unknown_execution_id is not None:
        command.extend(("--unknown-execution-id", str(unknown_execution_id)))
    environment = os.environ.copy()
    environment["AI_AGENT_POSTGRES_DSN"] = POSTGRES_DSN
    process = subprocess.run(
        command,
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        check=False,
    )
    if process.returncode != expected_returncode:
        raise AssertionError(
            f"tool execution probe failed with code {process.returncode}: "
            f"{process.stderr.decode('utf-8', errors='replace')}"
        )
    if process.stderr:
        raise AssertionError(
            "tool execution probe wrote stderr: "
            + process.stderr.decode("utf-8", errors="replace")
        )
    stdout = process.stdout.decode("utf-8")
    for private_value in (
        "private-known-document",
        "private-unknown-document",
        "private-known-idempotency-key",
        "private-unknown-idempotency-key",
        "private-published-result",
    ):
        if private_value in stdout:
            raise AssertionError("tool execution probe exposed private data")
    lines = [line for line in stdout.splitlines() if line]
    if len(lines) != 1:
        raise AssertionError("tool execution probe output is not bounded JSON")
    return json.loads(lines[0])


async def _run_recovery_probe(
    phase: str,
    *,
    expected_returncode: int = 0,
) -> dict[str, object]:
    return await asyncio.to_thread(
        _run_recovery_probe_sync,
        phase,
        expected_returncode,
    )


def _run_recovery_probe_sync(
    phase: str,
    expected_returncode: int,
) -> dict[str, object]:
    process = subprocess.run(
        _recovery_probe_command(phase),
        cwd=os.getcwd(),
        env=_recovery_probe_environment(),
        capture_output=True,
        check=False,
    )
    return _decode_recovery_probe(
        process,
        expected_returncode=expected_returncode,
    )


async def _run_recovery_scanners() -> tuple[dict[str, object], ...]:
    return await asyncio.to_thread(_run_recovery_scanners_sync)


def _run_recovery_scanners_sync() -> tuple[dict[str, object], ...]:
    processes = tuple(
        subprocess.Popen(
            _recovery_probe_command("scan"),
            cwd=os.getcwd(),
            env=_recovery_probe_environment(),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        for _ in range(2)
    )
    completed: list[subprocess.CompletedProcess[bytes]] = []
    for process in processes:
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
            raise AssertionError("recovery scanner probe timed out")
        completed.append(
            subprocess.CompletedProcess(
                process.args,
                process.returncode,
                stdout,
                stderr,
            )
        )
    return tuple(
        _decode_recovery_probe(process, expected_returncode=0)
        for process in completed
    )


def _recovery_probe_command(phase: str) -> list[str]:
    return [
        sys.executable,
        "-X",
        "utf8",
        "-B",
        "-m",
        "backend.app.stores.postgres_recovery_probe",
        "--phase",
        phase,
    ]


def _recovery_probe_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["AI_AGENT_POSTGRES_DSN"] = POSTGRES_DSN
    return environment


def _decode_recovery_probe(
    process: subprocess.CompletedProcess[bytes],
    *,
    expected_returncode: int,
) -> dict[str, object]:
    if process.returncode != expected_returncode:
        raise AssertionError(
            f"recovery probe failed with code {process.returncode}: "
            f"{process.stderr.decode('utf-8', errors='replace')}"
        )
    if process.stderr:
        raise AssertionError(
            "recovery probe wrote stderr: "
            + process.stderr.decode("utf-8", errors="replace")
        )
    stdout = process.stdout.decode("utf-8")
    for private_value in (
        "private orphan recovery process probe",
        "private-recovery-run-key",
        "private-running-document",
        "private-pending-document",
        "private-running-tool-key",
        "private-pending-tool-key",
    ):
        if private_value in stdout:
            raise AssertionError("recovery probe exposed private data")
    lines = [line for line in stdout.splitlines() if line]
    if len(lines) != 1:
        raise AssertionError("recovery probe output is not bounded JSON")
    return json.loads(lines[0])


async def _run_execution_composition_probe(
    phase: str,
    *,
    expected_returncode: int = 0,
) -> dict[str, object]:
    return await asyncio.to_thread(
        _run_execution_composition_probe_sync,
        phase,
        expected_returncode,
    )


def _run_execution_composition_probe_sync(
    phase: str,
    expected_returncode: int,
) -> dict[str, object]:
    environment = os.environ.copy()
    environment["AI_AGENT_POSTGRES_DSN"] = POSTGRES_DSN
    process = subprocess.run(
        [
            sys.executable,
            "-X",
            "utf8",
            "-B",
            "-m",
            "backend.app.postgres_execution_probe",
            "--phase",
            phase,
        ],
        cwd=os.getcwd(),
        env=environment,
        capture_output=True,
        check=False,
    )
    if process.returncode != expected_returncode:
        raise AssertionError(
            "execution composition probe failed with code "
            f"{process.returncode}: "
            f"{process.stderr.decode('utf-8', errors='replace')}"
        )
    if process.stderr:
        raise AssertionError(
            "execution composition probe wrote stderr: "
            + process.stderr.decode("utf-8", errors="replace")
        )
    stdout = process.stdout.decode("utf-8")
    for private_value in (
        "private composition recovery input",
        "private-composition-recovery-key",
    ):
        if private_value in stdout:
            raise AssertionError("execution composition probe exposed private data")
    lines = [line for line in stdout.splitlines() if line]
    if len(lines) != 1:
        raise AssertionError(
            "execution composition probe output is not bounded JSON"
        )
    return json.loads(lines[0])


if __name__ == "__main__":
    unittest.main()
