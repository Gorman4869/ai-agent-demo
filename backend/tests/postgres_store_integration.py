from __future__ import annotations

import asyncio
import json
import os
import selectors
import subprocess
import sys
import unittest
from datetime import timedelta

from backend.app.domain.run import RunRecord, RunStatus
from backend.app.stores import EventStore, RunStore, StoreUnavailableError
from backend.app.stores.base import StartCommit
from backend.app.stores.postgres import PostgresPersistence
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


class PostgresMigrationTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.persistence = await PostgresPersistence.open(POSTGRES_DSN)
        await _drop_app_schema(self.persistence)

    async def asyncTearDown(self) -> None:
        await self.persistence.close()

    async def test_first_apply_and_repeat_are_versioned_and_idempotent(self) -> None:
        first = await apply_postgres_migrations(self.persistence.pool)
        second = await apply_postgres_migrations(self.persistence.pool)

        self.assertEqual((1, 2), first)
        self.assertEqual((), second)
        self.assertEqual(
            [1, 2],
            await _applied_versions(self.persistence),
        )

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
            version=3,
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
        self.assertEqual([1, 2], await _applied_versions(self.persistence))
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
            {"phase", "process_id", "approval_id", "fact_id"},
            set(first),
        )
        self.assertEqual("write", first["phase"])
        self.assertEqual(
            {
                "phase": "resume",
                "process_id": second["process_id"],
                "arguments_recovered": True,
                "approval_consumed": True,
                "replay_reason": "approval_already_consumed",
                "messages_recovered": 1,
                "facts_recovered": 1,
                "fact_deleted": True,
            },
            second,
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
                conversation_messages,
                memory_message_sequences,
                conversation_memory_facts
            RESTART IDENTITY
            """
        )


async def _drop_app_schema(persistence: PostgresPersistence) -> None:
    async with persistence.pool.connection() as connection:
        await connection.execute(
            """
            DROP TABLE IF EXISTS conversation_memory_facts CASCADE;
            DROP TABLE IF EXISTS conversation_messages CASCADE;
            DROP TABLE IF EXISTS memory_message_sequences CASCADE;
            DROP TABLE IF EXISTS tool_approval_grants CASCADE;
            DROP TABLE IF EXISTS tool_approval_requests CASCADE;
            DROP TABLE IF EXISTS agent_run_events CASCADE;
            DROP TABLE IF EXISTS agent_run_event_sequences CASCADE;
            DROP TABLE IF EXISTS agent_runs CASCADE;
            DROP TABLE IF EXISTS app_schema_migrations CASCADE;
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


if __name__ == "__main__":
    unittest.main()
