from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from backend.app.domain import RunRecord, RunStatus
from backend.app.stores import (
    InMemoryRunLeaseStore,
    InMemoryRunStore,
    InvalidRunTransitionError,
    RunLease,
    RunLeaseLostError,
    RunLeaseMode,
    RunLeaseStore,
    RunLeaseUnavailableError,
    RunNotFoundError,
    RunStore,
)


LEASE_NOW = datetime(2026, 8, 3, 6, 0, tzinfo=UTC)
LEASE_TTL = timedelta(seconds=10)
SHORT_LEASE_TTL = timedelta(milliseconds=150)


class RunLeaseStoreContract:
    """Adapter-independent token, expiry, heartbeat, and scan contract."""

    async def asyncSetUp(self) -> None:
        self.run_store, self.lease_store = await self.create_store_bundle()

    async def create_store_bundle(
        self,
    ) -> tuple[RunStore, RunLeaseStore]:
        raise NotImplementedError

    async def expire_short_lease(self) -> None:
        raise NotImplementedError

    async def test_execution_reservation_precedes_start_and_then_heartbeats(
        self,
    ) -> None:
        queued = await self._create_queued_run()
        reservation = await self.lease_store.reserve_execution(
            queued.id,
            owner_id=queued.owner_id,
            expected_status=RunStatus.QUEUED,
            ttl=LEASE_TTL,
        )

        running = await self._start_run(queued)
        heartbeat = await self.lease_store.heartbeat(
            reservation,
            ttl=LEASE_TTL,
        )

        self.assertEqual(RunStatus.RUNNING, running.status)
        self.assertEqual(reservation.version + 1, heartbeat.version)
        await self.lease_store.release(heartbeat)

    async def test_execution_reservation_requires_exact_owned_predecessor(
        self,
    ) -> None:
        queued = await self._create_queued_run()

        with self.assertRaises(RunNotFoundError):
            await self.lease_store.reserve_execution(
                queued.id,
                owner_id="owner-2",
                expected_status=RunStatus.QUEUED,
                ttl=LEASE_TTL,
            )
        with self.assertRaises(InvalidRunTransitionError):
            await self.lease_store.reserve_execution(
                queued.id,
                owner_id=queued.owner_id,
                expected_status=RunStatus.WAITING_APPROVAL,
                ttl=LEASE_TTL,
            )
        with self.assertRaises(ValueError):
            await self.lease_store.reserve_execution(
                queued.id,
                owner_id=queued.owner_id,
                expected_status=RunStatus.RUNNING,
                ttl=LEASE_TTL,
            )

        reservation = await self.lease_store.reserve_execution(
            queued.id,
            owner_id=queued.owner_id,
            expected_status=RunStatus.QUEUED,
            ttl=LEASE_TTL,
        )
        await self.lease_store.release(reservation)

    async def test_waiting_approval_can_reserve_resume_execution(self) -> None:
        running = await self._create_running_run()
        waiting = await self.run_store.transition(
            running.id,
            owner_id=running.owner_id,
            expected_version=running.version,
            target_status=RunStatus.WAITING_APPROVAL,
        )

        reservation = await self.lease_store.reserve_execution(
            waiting.id,
            owner_id=waiting.owner_id,
            expected_status=RunStatus.WAITING_APPROVAL,
            ttl=LEASE_TTL,
        )

        self.assertEqual(RunLeaseMode.EXECUTION, reservation.mode)
        await self.lease_store.release(reservation)

    async def test_expired_pre_start_reservation_requires_recovery_claim(
        self,
    ) -> None:
        queued = await self._create_queued_run()
        reservation = await self.lease_store.reserve_execution(
            queued.id,
            owner_id=queued.owner_id,
            expected_status=RunStatus.QUEUED,
            ttl=SHORT_LEASE_TTL,
        )
        await self.expire_short_lease()

        with self.assertRaises(RunLeaseUnavailableError):
            await self.lease_store.reserve_execution(
                queued.id,
                owner_id=queued.owner_id,
                expected_status=RunStatus.QUEUED,
                ttl=LEASE_TTL,
            )
        claimed = await self.lease_store.claim_expired(
            limit=1,
            ttl=LEASE_TTL,
        )

        self.assertEqual(1, len(claimed))
        self.assertEqual(reservation.version + 1, claimed[0].version)
        self.assertEqual(RunLeaseMode.RECOVERY, claimed[0].mode)
        await self.lease_store.release(claimed[0])

    async def test_acquire_requires_an_owned_running_run(self) -> None:
        queued = await self._create_queued_run()

        with self.assertRaises(RunNotFoundError):
            await self.lease_store.acquire(
                queued.id,
                owner_id="owner-2",
                ttl=LEASE_TTL,
            )
        with self.assertRaises(InvalidRunTransitionError):
            await self.lease_store.acquire(
                queued.id,
                owner_id=queued.owner_id,
                ttl=LEASE_TTL,
            )

        running = await self._start_run(queued)
        lease = await self.lease_store.acquire(
            running.id,
            owner_id=running.owner_id,
            ttl=LEASE_TTL,
        )

        self.assertEqual(RunLeaseMode.EXECUTION, lease.mode)
        self.assertEqual(0, lease.version)
        raw_token = lease.token.reveal()
        self.assertNotIn(raw_token, repr(lease))
        self.assertNotIn(raw_token, str(lease.token))
        self.assertNotIn("token", lease.safe_summary())

    async def test_active_or_expired_lease_cannot_be_acquired_again(self) -> None:
        run = await self._create_running_run()
        await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=SHORT_LEASE_TTL,
        )

        with self.assertRaises(RunLeaseUnavailableError):
            await self.lease_store.acquire(
                run.id,
                owner_id=run.owner_id,
                ttl=LEASE_TTL,
            )
        await self.expire_short_lease()
        with self.assertRaises(RunLeaseUnavailableError):
            await self.lease_store.acquire(
                run.id,
                owner_id=run.owner_id,
                ttl=LEASE_TTL,
            )

    async def test_heartbeat_and_release_require_exact_token_version(self) -> None:
        run = await self._create_running_run()
        first = await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=LEASE_TTL,
        )
        heartbeat = await self.lease_store.heartbeat(
            first,
            ttl=LEASE_TTL,
        )

        self.assertEqual(first.version + 1, heartbeat.version)
        self.assertGreaterEqual(heartbeat.heartbeat_at, first.heartbeat_at)
        with self.assertRaises(RunLeaseLostError):
            await self.lease_store.heartbeat(first, ttl=LEASE_TTL)
        with self.assertRaises(RunLeaseLostError):
            await self.lease_store.release(first)

        await self.lease_store.release(heartbeat)
        replacement = await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=LEASE_TTL,
        )
        self.assertEqual(0, replacement.version)
        self.assertNotEqual(
            heartbeat.token.reveal(),
            replacement.token.reveal(),
        )

    async def test_expired_lease_is_claimed_with_new_recovery_credential(
        self,
    ) -> None:
        run = await self._create_running_run()
        execution = await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=SHORT_LEASE_TTL,
        )
        await self.expire_short_lease()

        claimed = await self.lease_store.claim_expired(
            limit=10,
            ttl=LEASE_TTL,
        )

        self.assertEqual(1, len(claimed))
        recovery = claimed[0]
        self.assertEqual(RunLeaseMode.RECOVERY, recovery.mode)
        self.assertEqual(execution.version + 1, recovery.version)
        self.assertNotEqual(
            execution.token.reveal(),
            recovery.token.reveal(),
        )
        with self.assertRaises(RunLeaseLostError):
            await self.lease_store.heartbeat(execution, ttl=LEASE_TTL)
        with self.assertRaises(RunLeaseLostError):
            await self.lease_store.release(execution)
        await self.lease_store.release(recovery)

    async def test_terminal_run_invalidates_heartbeat_but_allows_release(
        self,
    ) -> None:
        run = await self._create_running_run()
        lease = await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=LEASE_TTL,
        )
        await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=run.version,
            target_status=RunStatus.CANCELLED,
            error_code="run_cancelled",
            public_message="Run cancelled",
        )

        with self.assertRaises(RunLeaseLostError):
            await self.lease_store.heartbeat(lease, ttl=LEASE_TTL)
        await self.lease_store.release(lease)

    async def test_scan_skips_active_leases_and_respects_limit(self) -> None:
        first = await self._create_running_run(
            run_id="run-1",
            idempotency_key="run-key-1",
        )
        second = await self._create_running_run(
            run_id="run-2",
            idempotency_key="run-key-2",
        )
        active = await self._create_running_run(
            run_id="run-active",
            idempotency_key="run-key-active",
        )
        for run in (first, second):
            await self.lease_store.acquire(
                run.id,
                owner_id=run.owner_id,
                ttl=SHORT_LEASE_TTL,
            )
        await self.lease_store.acquire(
            active.id,
            owner_id=active.owner_id,
            ttl=LEASE_TTL,
        )
        await self.expire_short_lease()

        first_scan = await self.lease_store.claim_expired(
            limit=1,
            ttl=LEASE_TTL,
        )
        second_scan = await self.lease_store.claim_expired(
            limit=10,
            ttl=LEASE_TTL,
        )

        self.assertEqual(1, len(first_scan))
        self.assertEqual(1, len(second_scan))
        self.assertEqual(
            {first.id, second.id},
            {first_scan[0].run_id, second_scan[0].run_id},
        )
        self.assertNotIn(
            active.id,
            {first_scan[0].run_id, second_scan[0].run_id},
        )

    async def test_concurrent_scanners_have_one_winner(self) -> None:
        run = await self._create_running_run()
        await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=SHORT_LEASE_TTL,
        )
        await self.expire_short_lease()

        scans = await asyncio.gather(
            *(
                self.lease_store.claim_expired(
                    limit=1,
                    ttl=LEASE_TTL,
                )
                for _ in range(2)
            )
        )

        self.assertEqual(1, sum(len(scan) for scan in scans))
        self.assertEqual(
            [run.id],
            [lease.run_id for scan in scans for lease in scan],
        )

    async def test_invalid_ttl_and_scan_limit_fail_before_storage(self) -> None:
        run = await self._create_running_run()

        for ttl in (timedelta(0), timedelta(days=2), "30 seconds"):
            with self.subTest(ttl=ttl):
                with self.assertRaises(ValueError):
                    await self.lease_store.acquire(
                        run.id,
                        owner_id=run.owner_id,
                        ttl=ttl,
                    )
        for limit in (0, 101, True):
            with self.subTest(limit=limit):
                with self.assertRaises(ValueError):
                    await self.lease_store.claim_expired(
                        limit=limit,
                        ttl=LEASE_TTL,
                    )

    async def _create_queued_run(
        self,
        *,
        run_id: str = "run-1",
        idempotency_key: str = "run-key-1",
    ) -> RunRecord:
        run = RunRecord.create(
            run_id=run_id,
            session_id="session-1",
            owner_id="owner-1",
            runtime="manual",
            input_text="private run input",
            idempotency_key=idempotency_key,
            created_at=LEASE_NOW,
        )
        return (await self.run_store.create(run)).record

    async def _start_run(self, run: RunRecord) -> RunRecord:
        return await self.run_store.transition(
            run.id,
            owner_id=run.owner_id,
            expected_version=run.version,
            target_status=RunStatus.RUNNING,
        )

    async def _create_running_run(
        self,
        *,
        run_id: str = "run-1",
        idempotency_key: str = "run-key-1",
    ) -> RunRecord:
        return await self._start_run(
            await self._create_queued_run(
                run_id=run_id,
                idempotency_key=idempotency_key,
            )
        )


class _MutableClock:
    def __init__(self) -> None:
        self.now = LEASE_NOW + timedelta(seconds=1)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


class InMemoryRunLeaseStoreContractTest(
    RunLeaseStoreContract,
    unittest.IsolatedAsyncioTestCase,
):
    async def create_store_bundle(
        self,
    ) -> tuple[RunStore, RunLeaseStore]:
        self.clock = _MutableClock()
        self.token_sequence = 0
        run_store = InMemoryRunStore(clock=self.clock)
        return (
            run_store,
            InMemoryRunLeaseStore(
                run_store,
                clock=self.clock,
                token_factory=self._token_factory,
            ),
        )

    async def expire_short_lease(self) -> None:
        self.clock.advance(SHORT_LEASE_TTL + timedelta(milliseconds=1))

    async def test_invalid_or_backwards_clock_does_not_mutate_lease(self) -> None:
        run = await self._create_running_run()
        lease = await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=LEASE_TTL,
        )
        valid_now = self.clock.now
        self.clock.now = valid_now - timedelta(seconds=1)
        with self.assertRaises(ValueError):
            await self.lease_store.heartbeat(lease, ttl=LEASE_TTL)

        self.clock.now = valid_now
        heartbeat = await self.lease_store.heartbeat(
            lease,
            ttl=LEASE_TTL,
        )
        await self.lease_store.release(heartbeat)
        self.clock.now = valid_now.replace(tzinfo=None)
        with self.assertRaises(ValueError):
            await self.lease_store.acquire(
                run.id,
                owner_id=run.owner_id,
                ttl=LEASE_TTL,
            )

        self.clock.now = valid_now
        replacement = await self.lease_store.acquire(
            run.id,
            owner_id=run.owner_id,
            ttl=LEASE_TTL,
        )
        self.assertEqual(0, replacement.version)

    def _token_factory(self) -> str:
        self.token_sequence += 1
        return f"lease-token-{self.token_sequence:052d}"


if __name__ == "__main__":
    unittest.main()
