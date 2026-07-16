from __future__ import annotations

import asyncio
import threading
import unittest

from backend.app.agent import CancellationToken, ManualAgentLoop
from backend.app.agent.manual_runtime import ManualRuntime
from backend.app.agent.runtime import (
    RuntimeControl,
    RuntimeEvent,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.domain import AgentEvent, AgentRunResult, ModelDecision, ToolCall
from backend.app.domain.run import RunFailure, RunStatus
from backend.app.models import MockModel
from backend.app.tools import ToolDefinition, ToolRegistry
from backend.app.tools.builtin import create_default_registry


class RuntimeContractTest(unittest.TestCase):
    def test_runtime_result_accepts_only_consistent_terminal_outcomes(self) -> None:
        completed = RuntimeResult(
            status=RunStatus.COMPLETED,
            answer="done",
        )
        cancelled = RuntimeResult(
            status=RunStatus.CANCELLED,
            failure=RunFailure(
                code="cancelled_by_user",
                category="cancellation",
                public_message="Run cancelled",
            ),
        )

        self.assertEqual("done", completed.answer)
        self.assertEqual("cancelled_by_user", cancelled.failure.code)
        with self.assertRaises(ValueError):
            RuntimeResult(status=RunStatus.RUNNING)
        with self.assertRaises(ValueError):
            RuntimeResult(status=RunStatus.COMPLETED, answer=None)
        with self.assertRaises(ValueError):
            RuntimeResult(
                status=RunStatus.FAILED,
                answer="must-not-exist",
                failure=cancelled.failure,
            )

    def test_runtime_event_rejects_coordinator_owned_lifecycle_types(self) -> None:
        with self.assertRaisesRegex(ValueError, "lifecycle"):
            RuntimeEvent(type="run.completed", step=1, data={})

    def test_runtime_request_repr_hides_input(self) -> None:
        secret = "prompt-secret-value"
        request = RuntimeRequest(run_id="run-1", input_text=secret)

        self.assertNotIn(secret, repr(request))


class ManualRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_direct_answer_matches_legacy_loop_and_filters_lifecycle(self) -> None:
        direct = ModelDecision(final_answer="直接回答")
        legacy = ManualAgentLoop(
            MockModel([direct]),
            create_default_registry(),
        ).run("你好")
        runtime = ManualRuntime(
            lambda request, token: ManualAgentLoop(
                MockModel([direct]),
                create_default_registry(),
                cancellation_token=token,
            )
        )
        emitted: list[RuntimeEvent] = []

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="你好"),
            emit=_collecting_sink(emitted),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual(legacy.final_answer, result.answer)
        self.assertEqual([], emitted)

    async def test_tool_events_are_ordered_awaited_and_redacted(self) -> None:
        secret_argument = "argument-secret"
        secret_result = "result-secret"
        registry = ToolRegistry()
        registry.register(
            ToolDefinition(
                name="secret_tool",
                description="Return a test secret.",
                input_schema={
                    "type": "object",
                    "properties": {"value": {"type": "string"}},
                    "required": ["value"],
                },
                handler=lambda arguments: f"{secret_result}:{arguments['value']}",
            )
        )
        decisions = [
            ModelDecision(
                tool_call=ToolCall(
                    id="call-1",
                    name="secret_tool",
                    arguments={"value": secret_argument},
                )
            ),
            ModelDecision(final_answer="safe answer"),
        ]
        runtime = ManualRuntime(
            lambda request, token: ManualAgentLoop(
                MockModel(decisions),
                registry,
                cancellation_token=token,
            )
        )
        emitted: list[RuntimeEvent] = []
        active_sinks = 0

        async def slow_sink(event: RuntimeEvent) -> None:
            nonlocal active_sinks
            active_sinks += 1
            self.assertEqual(1, active_sinks)
            await asyncio.sleep(0)
            emitted.append(event)
            active_sinks -= 1

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="use a tool"),
            emit=slow_sink,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual(
            ["tool.started", "tool.completed"],
            [event.type for event in emitted],
        )
        serialized = repr(emitted)
        self.assertNotIn(secret_argument, serialized)
        self.assertNotIn(secret_result, serialized)
        self.assertEqual(
            {"id", "name", "duration_ms", "ok"},
            set(emitted[-1].data),
        )

    async def test_tool_failure_keeps_only_stable_error_code(self) -> None:
        runtime = ManualRuntime(
            lambda request, token: ManualAgentLoop(
                MockModel(
                    [
                        ModelDecision(
                            tool_call=ToolCall(
                                id="call-1",
                                name="missing",
                                arguments={},
                            )
                        ),
                        ModelDecision(final_answer="fallback"),
                    ]
                ),
                create_default_registry(),
                cancellation_token=token,
            )
        )
        emitted: list[RuntimeEvent] = []

        await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="missing tool"),
            emit=_collecting_sink(emitted),
            control=RuntimeControl(CancellationToken()),
        )

        failed = emitted[-1]
        self.assertEqual("tool.failed", failed.type)
        self.assertEqual("unknown_tool", failed.data["error_code"])
        self.assertNotIn("error_message", failed.data)
        self.assertNotIn("value", failed.data)

    async def test_legacy_user_cancellation_maps_to_durable_cancelled(self) -> None:
        token = CancellationToken()
        token.cancel("cancelled_by_user")
        runtime = ManualRuntime(
            lambda request, cancellation_token: ManualAgentLoop(
                MockModel([ModelDecision(final_answer="too late")]),
                create_default_registry(),
                cancellation_token=cancellation_token,
            )
        )

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="cancel"),
            emit=_collecting_sink([]),
            control=RuntimeControl(token),
        )

        self.assertEqual(RunStatus.CANCELLED, result.status)
        self.assertEqual("cancelled_by_user", result.failure.code)

    async def test_deadline_cancellation_maps_to_safe_timeout_failure(self) -> None:
        token = CancellationToken()
        token.cancel("deadline_exceeded")
        runtime = ManualRuntime(
            lambda request, cancellation_token: ManualAgentLoop(
                MockModel([ModelDecision(final_answer="too late")]),
                create_default_registry(),
                cancellation_token=cancellation_token,
            )
        )

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="timeout"),
            emit=_collecting_sink([]),
            control=RuntimeControl(token),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("run_timeout", result.failure.code)
        self.assertEqual("timeout", result.failure.category)

    async def test_unexpected_loop_error_is_normalized_without_leaking_text(
        self,
    ) -> None:
        secret = "provider-secret-exception"

        class BrokenLoop:
            def run(self, user_input: str) -> AgentRunResult:
                del user_input
                raise KeyError(secret)

        runtime = ManualRuntime(lambda request, token: BrokenLoop())

        result = await runtime.run(
            RuntimeRequest(run_id="run-1", input_text="hello"),
            emit=_collecting_sink([]),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("manual_runtime_failed", result.failure.code)
        self.assertNotIn(secret, repr(result))
        self.assertNotIn(secret, result.failure.public_message)

    async def test_invalid_legacy_event_fails_closed_before_any_emit(self) -> None:
        invalid = AgentRunResult(
            status="completed",
            final_answer="done",
            messages=(),
            events=(
                AgentEvent(type="run.started", step=0),
                AgentEvent(type="model.unreviewed", step=1, data={"secret": "x"}),
                AgentEvent(type="run.completed", step=1, data={"answer": "done"}),
            ),
        )

        class InvalidLoop:
            def run(self, user_input: str) -> AgentRunResult:
                del user_input
                return invalid

        emitted: list[RuntimeEvent] = []
        result = await ManualRuntime(
            lambda request, token: InvalidLoop()
        ).run(
            RuntimeRequest(run_id="run-1", input_text="hello"),
            emit=_collecting_sink(emitted),
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("manual_runtime_contract_error", result.failure.code)
        self.assertEqual([], emitted)

    async def test_cancelling_async_wrapper_reaps_the_worker_thread(self) -> None:
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        class BlockingLoop:
            def run(self, user_input: str) -> AgentRunResult:
                del user_input
                entered.set()
                release.wait(timeout=2)
                finished.set()
                return AgentRunResult(
                    status="completed",
                    final_answer="done",
                    messages=(),
                    events=(
                        AgentEvent(type="run.started", step=0),
                        AgentEvent(
                            type="run.completed",
                            step=1,
                            data={"answer": "done"},
                        ),
                    ),
                )

        token = CancellationToken()
        task = asyncio.create_task(
            ManualRuntime(lambda request, token: BlockingLoop()).run(
                RuntimeRequest(run_id="run-1", input_text="hello"),
                emit=_collecting_sink([]),
                control=RuntimeControl(token),
            )
        )
        await asyncio.to_thread(entered.wait, 1)
        task.cancel()
        await asyncio.sleep(0)

        self.assertTrue(token.is_cancelled)
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(finished.is_set())

    async def test_blocked_worker_cannot_defeat_bounded_cancellation_grace(
        self,
    ) -> None:
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()

        class BlockingLoop:
            def run(self, user_input: str) -> AgentRunResult:
                del user_input
                entered.set()
                release.wait(timeout=2)
                finished.set()
                return AgentRunResult(
                    status="completed",
                    final_answer="late",
                    messages=(),
                    events=(
                        AgentEvent(type="run.started", step=0),
                        AgentEvent(type="run.completed", step=1, data={}),
                    ),
                )

        token = CancellationToken()
        task = asyncio.create_task(
            ManualRuntime(
                lambda request, token: BlockingLoop(),
                cancellation_grace_ms=10,
            ).run(
                RuntimeRequest(run_id="run-1", input_text="hello"),
                emit=_collecting_sink([]),
                control=RuntimeControl(token),
            )
        )
        await asyncio.to_thread(entered.wait, 1)
        task.cancel()

        with self.assertRaises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=0.2)
        self.assertTrue(token.is_cancelled)
        self.assertFalse(finished.is_set())

        release.set()
        self.assertTrue(await asyncio.to_thread(finished.wait, 1))


def _collecting_sink(events: list[RuntimeEvent]):
    async def collect(event: RuntimeEvent) -> None:
        events.append(event)

    return collect


if __name__ == "__main__":
    unittest.main()
