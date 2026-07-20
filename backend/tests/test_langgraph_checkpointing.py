from __future__ import annotations

import unittest
from datetime import UTC, datetime
from typing import TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from backend.app.agent import (
    CancellationToken,
    RuntimeCheckpointContext,
    RuntimeControl,
    RuntimeEvent,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.agent.checkpoint_runtime import (
    CHECKPOINT_STATE_VERSION,
    CheckpointedLangGraphRuntime,
)
from backend.app.agent.graph_runtime import LangGraphRuntime
from backend.app.domain import ModelDecision, ToolCall
from backend.app.domain.run import RunRecord, RunStatus
from backend.app.models import MockModel
from backend.app.services.run_coordinator import RunCoordinator
from backend.app.stores import InMemoryEventStore, InMemoryRunStore
from backend.app.tools.builtin import create_default_registry


NOW = datetime(2026, 7, 20, 4, 0, tzinfo=UTC)


class RuntimeCheckpointContextTest(unittest.TestCase):
    def test_context_is_deterministic_owner_scoped_and_repr_safe(self) -> None:
        first = RuntimeCheckpointContext.for_run(
            run_id="shared-run",
            owner_id="owner-a",
        )
        replay = RuntimeCheckpointContext.for_run(
            run_id="shared-run",
            owner_id="owner-a",
        )
        other_owner = RuntimeCheckpointContext.for_run(
            run_id="shared-run",
            owner_id="owner-b",
        )

        self.assertEqual(first, replay)
        self.assertNotEqual(first.thread_id, other_owner.thread_id)
        self.assertNotEqual(first.owner_scope, other_owner.owner_scope)
        self.assertNotIn("owner-a", repr(first))
        self.assertNotIn(first.thread_id, repr(first))

    def test_request_rejects_a_context_bound_to_another_run(self) -> None:
        wrong_context = RuntimeCheckpointContext.for_run(
            run_id="run-b",
            owner_id="owner-a",
        )

        with self.assertRaisesRegex(ValueError, "does not belong"):
            RuntimeRequest(
                run_id="run-a",
                input_text="hello",
                checkpoint_context=wrong_context,
            )


class CheckpointedLangGraphRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_shared_saver_restores_state_across_runtime_instances(
        self,
    ) -> None:
        saver = InMemorySaver()
        request = _request(run_id="restored-run", owner_id="owner-a")

        first = await CheckpointedLangGraphRuntime(
            delegate=_StaticRuntime("first"),
            checkpointer=saver,
        ).run(request, emit=_ignore_event, control=_control())
        first_values = await _checkpoint_values(saver, request)
        second = await CheckpointedLangGraphRuntime(
            delegate=_StaticRuntime("second"),
            checkpointer=saver,
        ).run(request, emit=_ignore_event, control=_control())
        second_values = await _checkpoint_values(saver, request)

        self.assertEqual("first", first.answer)
        self.assertEqual("second", second.answer)
        self.assertEqual(1, first_values["invocation_count"])
        self.assertEqual(2, second_values["invocation_count"])

    async def test_same_run_id_is_isolated_between_owners(self) -> None:
        saver = InMemorySaver()
        runtime = CheckpointedLangGraphRuntime(
            delegate=_StaticRuntime("done"),
            checkpointer=saver,
        )
        owner_a = _request(run_id="shared-run", owner_id="owner-a")
        owner_b = _request(run_id="shared-run", owner_id="owner-b")

        await runtime.run(owner_a, emit=_ignore_event, control=_control())
        await runtime.run(owner_b, emit=_ignore_event, control=_control())

        values_a = await _checkpoint_values(saver, owner_a)
        values_b = await _checkpoint_values(saver, owner_b)
        self.assertEqual(1, values_a["invocation_count"])
        self.assertEqual(1, values_b["invocation_count"])
        self.assertNotEqual(values_a["owner_scope"], values_b["owner_scope"])

    async def test_missing_thread_context_fails_closed_without_delegate(
        self,
    ) -> None:
        delegate = _StaticRuntime("must-not-run")
        runtime = CheckpointedLangGraphRuntime(delegate=delegate)

        result = await runtime.run(
            RuntimeRequest(run_id="missing-thread", input_text="hello"),
            emit=_ignore_event,
            control=_control(),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("checkpoint_thread_required", result.failure.code)
        self.assertEqual(0, delegate.calls)

    async def test_node_failure_keeps_the_prior_superstep_checkpoint(self) -> None:
        secret = "delegate-secret-error"
        saver = InMemorySaver()
        request = _request(run_id="retry-run", owner_id="owner-a")

        failed = await CheckpointedLangGraphRuntime(
            delegate=_RaisingRuntime(secret),
            checkpointer=saver,
        ).run(request, emit=_ignore_event, control=_control())
        failed_tuple = await _checkpoint_tuple(saver, request)
        succeeded = await CheckpointedLangGraphRuntime(
            delegate=_StaticRuntime("recovered"),
            checkpointer=saver,
        ).run(request, emit=_ignore_event, control=_control())
        recovered_values = await _checkpoint_values(saver, request)

        self.assertEqual("checkpoint_node_failed", failed.failure.code)
        self.assertNotIn(secret, repr(failed_tuple))
        self.assertEqual("recovered", succeeded.answer)
        self.assertEqual(2, recovered_values["invocation_count"])

    async def test_version_and_owner_scope_mismatches_fail_closed(self) -> None:
        request = _request(run_id="invalid-state", owner_id="owner-a")
        cases = (
            (
                {
                    "state_version": CHECKPOINT_STATE_VERSION + 1,
                    "owner_scope": request.checkpoint_context.owner_scope,
                    "invocation_count": 1,
                },
                "checkpoint_version_unsupported",
            ),
            (
                {
                    "state_version": CHECKPOINT_STATE_VERSION,
                    "owner_scope": "runtime-owner-v1-" + "0" * 64,
                    "invocation_count": 1,
                },
                "checkpoint_scope_mismatch",
            ),
            (
                {
                    "state_version": CHECKPOINT_STATE_VERSION,
                    "owner_scope": request.checkpoint_context.owner_scope,
                    "invocation_count": "corrupt",
                },
                "checkpoint_state_invalid",
            ),
        )

        for state, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                saver = InMemorySaver()
                await _seed_checkpoint(saver, request, state)
                delegate = _StaticRuntime("must-not-run")
                result = await CheckpointedLangGraphRuntime(
                    delegate=delegate,
                    checkpointer=saver,
                ).run(request, emit=_ignore_event, control=_control())

                self.assertEqual(expected_code, result.failure.code)
                self.assertEqual(0, delegate.calls)

    async def test_checkpoint_excludes_raw_request_prompt_and_owner(self) -> None:
        saver = InMemorySaver()
        owner_secret = "private-owner-id"
        input_secret = "private-user-input"
        prompt_secret = "private-skill-context"
        request = _request(
            run_id="secret-run",
            owner_id=owner_secret,
            input_text=input_secret,
            prompt_context=prompt_secret,
        )

        result = await CheckpointedLangGraphRuntime(
            delegate=_StaticRuntime("safe-answer"),
            checkpointer=saver,
        ).run(request, emit=_ignore_event, control=_control())
        serialized = repr(await _checkpoint_tuple(saver, request))

        self.assertEqual("safe-answer", result.answer)
        self.assertNotIn(owner_secret, serialized)
        self.assertNotIn(input_secret, serialized)
        self.assertNotIn(prompt_secret, serialized)

    async def test_real_langgraph_delegate_executes_tool_and_checkpoints(
        self,
    ) -> None:
        saver = InMemorySaver()
        events: list[RuntimeEvent] = []
        request = _request(run_id="tool-run", owner_id="owner-a")
        delegate = LangGraphRuntime(
            model_factory=lambda _request: MockModel(
                [
                    ModelDecision(
                        tool_call=ToolCall(
                            id="call-1",
                            name="add_numbers",
                            arguments={"a": 2, "b": 3},
                        )
                    ),
                    ModelDecision(final_answer="计算结果是 5"),
                ]
            ),
            tool_registry_factory=lambda _request: create_default_registry(),
        )

        result = await CheckpointedLangGraphRuntime(
            delegate=delegate,
            checkpointer=saver,
        ).run(request, emit=_collecting_sink(events), control=_control())
        values = await _checkpoint_values(saver, request)

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual("计算结果是 5", result.answer)
        self.assertEqual(
            ["tool.started", "tool.completed"],
            [event.type for event in events],
        )
        self.assertEqual(1, values["invocation_count"])
        self.assertEqual(RunStatus.COMPLETED.value, values["result_status"])

    async def test_coordinator_derives_checkpoint_context_from_stored_run(
        self,
    ) -> None:
        run_store = InMemoryRunStore()
        event_store = InMemoryEventStore(run_store)
        run = RunRecord.create(
            run_id="coordinator-run",
            session_id="session-1",
            owner_id="trusted-owner",
            runtime="langgraph",
            input_text="hello",
            idempotency_key="checkpoint-context-key",
            created_at=NOW,
        )
        await run_store.create(run)
        capture = _CaptureRuntime()
        coordinator = RunCoordinator(
            run_store=run_store,
            event_store=event_store,
            runtimes={"langgraph": capture},
            run_timeout_ms=1_000,
        )

        result = await coordinator.execute(run.id, owner_id=run.owner_id)

        self.assertEqual(RunStatus.COMPLETED, result.status)
        self.assertEqual(1, len(capture.requests))
        expected = RuntimeCheckpointContext.for_run(
            run_id=run.id,
            owner_id=run.owner_id,
        )
        self.assertEqual(expected, capture.requests[0].checkpoint_context)


class _SeedState(TypedDict, total=False):
    state_version: int
    owner_scope: str
    invocation_count: int


class _StaticRuntime:
    def __init__(self, answer: str) -> None:
        self.answer = answer
        self.calls = 0

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit, control
        self.calls += 1
        return RuntimeResult(status=RunStatus.COMPLETED, answer=self.answer)


class _RaisingRuntime:
    def __init__(self, message: str) -> None:
        self.message = message

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del request, emit, control
        raise RuntimeError(self.message)


class _CaptureRuntime:
    def __init__(self) -> None:
        self.requests: list[RuntimeRequest] = []

    async def run(self, request, *, emit, control) -> RuntimeResult:
        del emit, control
        self.requests.append(request)
        return RuntimeResult(status=RunStatus.COMPLETED, answer="done")


def _request(
    *,
    run_id: str,
    owner_id: str,
    input_text: str = "hello",
    prompt_context: str | None = None,
) -> RuntimeRequest:
    return RuntimeRequest(
        run_id=run_id,
        input_text=input_text,
        prompt_context=prompt_context,
        checkpoint_context=RuntimeCheckpointContext.for_run(
            run_id=run_id,
            owner_id=owner_id,
        ),
    )


def _control() -> RuntimeControl:
    return RuntimeControl(CancellationToken())


def _config(request: RuntimeRequest) -> dict[str, dict[str, str]]:
    context = request.checkpoint_context
    if context is None:
        raise AssertionError("test request has no checkpoint context")
    return {"configurable": {"thread_id": context.thread_id}}


async def _checkpoint_tuple(
    saver: InMemorySaver,
    request: RuntimeRequest,
):
    checkpoint_tuple = await saver.aget_tuple(_config(request))
    if checkpoint_tuple is None:
        raise AssertionError("checkpoint was not persisted")
    return checkpoint_tuple


async def _checkpoint_values(
    saver: InMemorySaver,
    request: RuntimeRequest,
) -> dict[str, object]:
    checkpoint_tuple = await _checkpoint_tuple(saver, request)
    return dict(checkpoint_tuple.checkpoint["channel_values"])


async def _seed_checkpoint(
    saver: InMemorySaver,
    request: RuntimeRequest,
    state: dict[str, object],
) -> None:
    graph = StateGraph(_SeedState)
    graph.add_node("seed", lambda _state: {})
    graph.add_edge(START, "seed")
    graph.add_edge("seed", END)
    compiled = graph.compile(checkpointer=saver)
    await compiled.ainvoke(state, _config(request))


async def _ignore_event(event: RuntimeEvent) -> None:
    del event


def _collecting_sink(events: list[RuntimeEvent]):
    async def collect(event: RuntimeEvent) -> None:
        events.append(event)

    return collect


if __name__ == "__main__":
    unittest.main()
