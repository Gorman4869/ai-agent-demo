from __future__ import annotations

import asyncio
import unittest
from datetime import UTC, datetime, timedelta

from langgraph.checkpoint.memory import InMemorySaver

from backend.app.agent import RuntimeCheckpointContext
from backend.app.agent.approval_runtime import (
    ApprovalLangGraphRuntime,
    PlannedToolCall,
)
from backend.app.domain.run import RunRecord, RunStatus
from backend.app.services.run_coordinator import RunCoordinator
from backend.app.stores import (
    InMemoryEventStore,
    InMemoryRunStore,
    StoreUnavailableError,
)
from backend.app.tools import (
    ApprovalResolutionError,
    InMemoryApprovalStore,
    ToolDefinition,
    ToolExecutionContext,
    ToolRegistry,
    ToolRisk,
)


class LangGraphApprovalResumeTest(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.now = datetime(2026, 7, 20, 8, 0, tzinfo=UTC)
        self.side_effects: list[str] = []
        self.approval_store = InMemoryApprovalStore(clock=lambda: self.now)
        self.registry = _registry(self.side_effects)
        self.checkpointer = InMemorySaver()
        self.runtime = self._runtime()
        self.run_store = InMemoryRunStore(clock=lambda: self.now)
        self.event_store = InMemoryEventStore(
            self.run_store,
            clock=lambda: self.now,
        )
        self.coordinator = self._coordinator(self.runtime)
        self.run = _run(self.now)
        await self.run_store.create(self.run)
        self.context = ToolExecutionContext(
            principal_id=self.run.owner_id,
            roles=frozenset({"editor"}),
            approval_store=self.approval_store,
        )

    async def test_approve_resumes_and_consumes_exact_grant_once(self) -> None:
        paused = await self._pause()

        completed = await self._resume(decision="approve")
        repeated = self.registry.execute(
            "publish_report",
            {"title": "quarterly-secret"},
            context=self.context.for_run(self.run.id),
            call_id="call-publish-1",
        )
        events = await self._events()

        self.assertEqual(RunStatus.WAITING_APPROVAL, paused.status)
        self.assertEqual(RunStatus.COMPLETED, completed.status)
        self.assertEqual(["quarterly-secret"], self.side_effects)
        self.assertFalse(repeated.ok)
        self.assertEqual(
            "approval_already_consumed",
            repeated.error_details["reason"],
        )
        self.assertEqual(
            [
                "run.started",
                "run.waiting_approval",
                "run.resumed",
                "run.completed",
            ],
            [event.type for event in events],
        )

    async def test_reject_resumes_to_failure_without_tool_execution(self) -> None:
        await self._pause()

        failed = await self._resume(decision="reject")

        self.assertEqual(RunStatus.FAILED, failed.status)
        self.assertEqual("approval_rejected", failed.failure.code)
        self.assertEqual([], self.side_effects)

    async def test_expired_approval_fails_without_tool_execution(self) -> None:
        await self._pause()
        self.now += timedelta(minutes=2)

        failed = await self._resume(decision="approve")
        events = await self._events()

        self.assertEqual(RunStatus.FAILED, failed.status)
        self.assertEqual("approval_expired", failed.failure.code)
        self.assertEqual("expired", events[-2].data["decision"])
        self.assertEqual([], self.side_effects)

    async def test_approval_store_failure_propagates_without_false_terminal(
        self,
    ) -> None:
        self.approval_store = _UnavailableApprovalStore()
        self.runtime = self._runtime()
        self.coordinator = self._coordinator(self.runtime)
        self.context = ToolExecutionContext(
            principal_id=self.run.owner_id,
            roles=frozenset({"editor"}),
            approval_store=self.approval_store,
        )

        with self.assertRaises(StoreUnavailableError):
            await self._pause()

        stored = await self.run_store.get(
            self.run.id,
            owner_id=self.run.owner_id,
        )
        self.assertEqual(RunStatus.RUNNING, stored.status)
        self.assertEqual(
            ["run.started"],
            [event.type for event in await self._events()],
        )

    async def test_duplicate_resume_across_coordinators_executes_once(self) -> None:
        await self._pause()
        fields = await self._approval_fields()
        first = self._coordinator(self.runtime)
        second = self._coordinator(self.runtime)

        first_result, second_result = await asyncio.gather(
            first.resume_approval(
                self.run.id,
                owner_id=self.run.owner_id,
                decision="approve",
                execution_context=self.context,
                **fields,
            ),
            second.resume_approval(
                self.run.id,
                owner_id=self.run.owner_id,
                decision="approve",
                execution_context=self.context,
                **fields,
            ),
        )

        self.assertEqual(RunStatus.COMPLETED, first_result.status)
        self.assertEqual(first_result, second_result)
        self.assertEqual(["quarterly-secret"], self.side_effects)

    async def test_tampered_binding_cannot_leave_waiting_state(self) -> None:
        await self._pause()
        fields = await self._approval_fields()

        for changed in (
            {**fields, "tool_call_id": "call-tampered"},
            {**fields, "tool_name": "other_tool"},
            {**fields, "arguments_digest": "0" * 64},
        ):
            with self.subTest(changed=changed):
                with self.assertRaises(ApprovalResolutionError) as raised:
                    await self.coordinator.resume_approval(
                        self.run.id,
                        owner_id=self.run.owner_id,
                        decision="approve",
                        execution_context=self.context,
                        **changed,
                    )
                self.assertEqual("approval_binding_mismatch", raised.exception.code)

        stored = await self.run_store.get(
            self.run.id,
            owner_id=self.run.owner_id,
        )
        self.assertEqual(RunStatus.WAITING_APPROVAL, stored.status)
        self.assertEqual([], self.side_effects)

    async def test_raw_boolean_approval_cannot_resume_tool_execution(self) -> None:
        await self._pause()

        with self.assertRaisesRegex(ValueError, "approve or reject"):
            await self._resume(decision=True)

        stored = await self.run_store.get(
            self.run.id,
            owner_id=self.run.owner_id,
        )
        self.assertEqual(RunStatus.WAITING_APPROVAL, stored.status)
        self.assertEqual([], self.side_effects)

    async def test_new_runtime_instance_resumes_shared_checkpoint(self) -> None:
        await self._pause()
        restarted_runtime = self._runtime(planner=_unexpected_planner)
        restarted_coordinator = self._coordinator(restarted_runtime)
        fields = await self._approval_fields()

        completed = await restarted_coordinator.resume_approval(
            self.run.id,
            owner_id=self.run.owner_id,
            decision="approve",
            execution_context=self.context,
            **fields,
        )

        self.assertEqual(RunStatus.COMPLETED, completed.status)
        self.assertEqual(["quarterly-secret"], self.side_effects)

    async def test_resume_from_waiting_notification_survives_execute_cleanup(
        self,
    ) -> None:
        notifier = ImmediateResumeNotifier(self.context)
        coordinator = self._coordinator(self.runtime, notifier=notifier)
        notifier.coordinator = coordinator

        paused = await coordinator.execute(
            self.run.id,
            owner_id=self.run.owner_id,
            execution_context=self.context,
        )
        completed = await asyncio.wait_for(notifier.task, timeout=1)

        self.assertEqual(RunStatus.WAITING_APPROVAL, paused.status)
        self.assertEqual(RunStatus.COMPLETED, completed.status)
        self.assertEqual(["quarterly-secret"], self.side_effects)

    async def test_checkpoint_and_events_exclude_raw_tool_arguments(self) -> None:
        await self._pause()
        checkpoint_context = RuntimeCheckpointContext.for_run(
            run_id=self.run.id,
            owner_id=self.run.owner_id,
        )
        checkpoint = await self.checkpointer.aget_tuple(
            {"configurable": {"thread_id": checkpoint_context.thread_id}}
        )
        events = await self._events()

        self.assertIsNotNone(checkpoint)
        self.assertNotIn("quarterly-secret", repr(checkpoint.checkpoint))
        self.assertNotIn("quarterly-secret", repr(events))

    async def test_waiting_run_can_be_cancelled_without_tool_execution(self) -> None:
        await self._pause()

        accepted = await self.coordinator.cancel(
            self.run.id,
            owner_id=self.run.owner_id,
        )
        stored = await self.run_store.get(
            self.run.id,
            owner_id=self.run.owner_id,
        )

        self.assertTrue(accepted)
        self.assertEqual(RunStatus.CANCELLED, stored.status)
        self.assertEqual([], self.side_effects)

    async def _pause(self) -> RunRecord:
        return await self.coordinator.execute(
            self.run.id,
            owner_id=self.run.owner_id,
            execution_context=self.context,
        )

    async def _resume(self, *, decision) -> RunRecord:
        return await self.coordinator.resume_approval(
            self.run.id,
            owner_id=self.run.owner_id,
            decision=decision,
            execution_context=self.context,
            **(await self._approval_fields()),
        )

    async def _approval_fields(self) -> dict[str, str]:
        waiting = next(
            event
            for event in reversed(await self._events())
            if event.type == "run.waiting_approval"
        )
        return {
            "approval_id": waiting.data["approval_id"],
            "tool_call_id": waiting.data["tool_call_id"],
            "tool_name": waiting.data["tool_name"],
            "arguments_digest": waiting.data["arguments_digest"],
        }

    async def _events(self):
        return await self.event_store.list_for_run(
            self.run.id,
            owner_id=self.run.owner_id,
        )

    def _runtime(self, *, planner=None) -> ApprovalLangGraphRuntime:
        return ApprovalLangGraphRuntime(
            registry=self.registry,
            approval_store=self.approval_store,
            planner=planner or _planner,
            approval_ttl=timedelta(minutes=1),
            checkpointer=self.checkpointer,
        )

    def _coordinator(self, runtime, *, notifier=None) -> RunCoordinator:
        return RunCoordinator(
            run_store=self.run_store,
            event_store=self.event_store,
            runtimes={"langgraph": runtime},
            notifier=notifier,
            run_timeout_ms=1_000,
        )


class ImmediateResumeNotifier:
    def __init__(self, context: ToolExecutionContext) -> None:
        self.context = context
        self.coordinator: RunCoordinator | None = None
        self.task = None

    async def notify(self, event) -> None:
        if event.type != "run.waiting_approval":
            return
        if self.coordinator is None:
            raise AssertionError("coordinator is not configured")
        self.task = asyncio.create_task(
            self.coordinator.resume_approval(
                event.run_id,
                owner_id=self.context.principal_id,
                approval_id=event.data["approval_id"],
                tool_call_id=event.data["tool_call_id"],
                tool_name=event.data["tool_name"],
                arguments_digest=event.data["arguments_digest"],
                decision="approve",
                execution_context=self.context,
            )
        )
        await asyncio.sleep(0)


class _UnavailableApprovalStore(InMemoryApprovalStore):
    def request(self, **kwargs):
        del kwargs
        raise StoreUnavailableError()


def _registry(side_effects: list[str]) -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolDefinition(
            name="publish_report",
            description="Publish one report",
            input_schema={
                "type": "object",
                "properties": {
                    "title": {"type": "string", "minLength": 1},
                },
                "required": ["title"],
                "additionalProperties": False,
            },
            handler=lambda arguments: side_effects.append(arguments["title"]),
            allowed_roles=frozenset({"editor"}),
            risk_level=ToolRisk.HIGH,
            has_side_effects=True,
        )
    )
    return registry


def _planner(request) -> PlannedToolCall:
    del request
    return PlannedToolCall(
        call_id="call-publish-1",
        tool_name="publish_report",
        arguments={"title": "quarterly-secret"},
    )


def _unexpected_planner(request) -> PlannedToolCall:
    del request
    raise AssertionError("resume must not rebuild the planned tool call")


def _run(now: datetime) -> RunRecord:
    return RunRecord.create(
        run_id="run-approval-1",
        session_id="session-approval-1",
        owner_id="owner-approval-1",
        runtime="langgraph",
        input_text="publish the quarterly report",
        idempotency_key="approval-idempotency-key",
        created_at=now,
    )


if __name__ == "__main__":
    unittest.main()
