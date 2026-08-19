from __future__ import annotations

import asyncio
import json
import unittest

from backend.app.agent import (
    CancellationToken,
    RuntimeApprovalPause,
    RuntimeCheckpointContext,
    RuntimeControl,
    RuntimeContextIdentity,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.context import (
    AsyncContextAwareRuntime,
    AsyncMemoryContextSourceCollector,
    ContextAssembler,
    ContextSource,
    ContextSystemConstraint,
    RuntimeContextBinding,
    RuntimeIdentityBindingFactory,
    prepare_async_context_request,
)
from backend.app.domain import Message
from backend.app.domain.run import RunStatus
from backend.app.knowledge import InMemoryKnowledgeBase
from backend.app.memory import ConversationMemory, MemoryFact, MemoryScope
from backend.app.skills import SkillContextBuilder
from backend.app.stores import AsyncLocalMemoryStore
from backend.app.stores.base import StoreUnavailableError
from backend.app.tools import ToolExecutionContext


class AsyncContextRuntimePreparationTest(unittest.IsolatedAsyncioTestCase):
    async def test_real_async_sources_prepare_one_bounded_request(self) -> None:
        memory = ConversationMemory()
        memory.append_message(
            "private-session",
            Message(role="user", content="Recent private context."),
        )
        memory.remember(
            owner_id="private-owner",
            key="locale",
            value="zh-CN",
            scope=MemoryScope.USER,
            approved=True,
        )
        request = _request(run_id="async-prepare")

        prepared = await prepare_async_context_request(
            request,
            binding_factory=RuntimeIdentityBindingFactory(
                system_constraints=(
                    ContextSystemConstraint(
                        id="policy-v1",
                        content="Keep server policy active.",
                    ),
                )
            ),
            collector=_collector(AsyncLocalMemoryStore(memory)),
            assembler=ContextAssembler(),
        )

        self.assertIsNot(request, prepared.request)
        self.assertIs(request.execution_context, prepared.request.execution_context)
        self.assertIs(request.checkpoint_context, prepared.request.checkpoint_context)
        self.assertIs(request.context_identity, prepared.request.context_identity)
        payload = _payload(prepared.request.prompt_context)
        self.assertEqual(
            ["system", "memory", "recent"],
            [fragment["source"] for fragment in payload["fragments"]],
        )

    async def test_empty_sources_keep_the_original_request(self) -> None:
        request = _request(run_id="async-empty")

        prepared = await prepare_async_context_request(
            request,
            binding_factory=RuntimeIdentityBindingFactory(),
            collector=_collector(_StaticAsyncMemoryStore()),
            assembler=ContextAssembler(),
        )

        self.assertIs(request, prepared.request)
        self.assertIsNone(prepared.assembly.prompt_context)
        self.assertEqual(
            (ContextSource.SUMMARY,),
            prepared.assembly.report.unavailable_sources,
        )


class AsyncContextAwareRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_delegates_once_with_same_emit_and_control(self) -> None:
        expected = RuntimeResult(
            status=RunStatus.COMPLETED,
            answer="async context-aware",
        )
        delegate = _CaptureRuntime(expected)
        runtime = AsyncContextAwareRuntime(
            delegate,
            binding_factory=RuntimeIdentityBindingFactory(
                system_constraints=(
                    ContextSystemConstraint("policy-v1", "Server policy."),
                )
            ),
            collector=_collector(_StaticAsyncMemoryStore()),
        )
        request = _request(run_id="async-delegated")
        control = RuntimeControl(CancellationToken())

        result = await runtime.run(
            request,
            emit=_ignore_event,
            control=control,
        )

        self.assertIs(expected, result)
        self.assertIs(delegate, runtime.delegate)
        self.assertEqual(1, len(delegate.calls))
        delegated, emit, delegated_control = delegate.calls[0]
        self.assertIsNot(request, delegated)
        self.assertIsNotNone(delegated.prompt_context)
        self.assertIs(_ignore_event, emit)
        self.assertIs(control, delegated_control)

    async def test_existing_prompt_fails_before_binding_or_memory(self) -> None:
        binding_factory = _RecordingBindingFactory()
        memory = _RecordingAsyncMemoryStore()
        delegate = _CaptureRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="unused")
        )
        runtime = AsyncContextAwareRuntime(
            delegate,
            binding_factory=binding_factory,
            collector=_collector(memory),
        )

        result = await runtime.run(
            RuntimeRequest(
                run_id="async-existing-prompt",
                input_text="private query",
                prompt_context="existing context",
                context_identity=RuntimeContextIdentity(
                    owner_id="private-owner",
                    session_id="private-session",
                ),
            ),
            emit=_ignore_event,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("context_unavailable", result.failure.code)
        self.assertEqual([], binding_factory.requests)
        self.assertEqual(0, memory.calls)
        self.assertEqual([], delegate.calls)

    async def test_missing_identity_fails_before_memory_or_delegate(self) -> None:
        memory = _RecordingAsyncMemoryStore()
        delegate = _CaptureRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="unused")
        )
        runtime = AsyncContextAwareRuntime(
            delegate,
            binding_factory=RuntimeIdentityBindingFactory(),
            collector=_collector(memory),
        )

        result = await runtime.run(
            RuntimeRequest(run_id="async-missing-identity", input_text="private"),
            emit=_ignore_event,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("context_unavailable", result.failure.code)
        self.assertEqual(0, memory.calls)
        self.assertEqual([], delegate.calls)
        self.assertNotIn("private", repr(result))

    async def test_cross_owner_context_returns_content_free_failure(self) -> None:
        delegate = _CaptureRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="unused")
        )
        runtime = AsyncContextAwareRuntime(
            delegate,
            binding_factory=RuntimeIdentityBindingFactory(),
            collector=_collector(
                _StaticAsyncMemoryStore(
                    facts=(
                        MemoryFact(
                            id="private-fact",
                            owner_id="unexpected-owner",
                            key="private-key",
                            value="private-value",
                            scope=MemoryScope.USER,
                        ),
                    )
                )
            ),
        )

        result = await runtime.run(
            _request(run_id="async-cross-owner"),
            emit=_ignore_event,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("context_unavailable", result.failure.code)
        self.assertEqual("runtime", result.failure.category)
        self.assertEqual("Context is unavailable", result.failure.public_message)
        self.assertEqual([], delegate.calls)
        rendered = repr(result) + str(result.failure)
        self.assertNotIn("unexpected-owner", rendered)
        self.assertNotIn("private-value", rendered)

    async def test_source_failure_returns_stable_failure(self) -> None:
        delegate = _CaptureRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="unused")
        )
        runtime = AsyncContextAwareRuntime(
            delegate,
            binding_factory=RuntimeIdentityBindingFactory(),
            collector=_collector(_FailingAsyncMemoryStore()),
        )

        result = await runtime.run(
            _request(run_id="async-source-failure"),
            emit=_ignore_event,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("context_unavailable", result.failure.code)
        self.assertEqual([], delegate.calls)

    async def test_source_timeout_returns_stable_failure(self) -> None:
        delegate = _CaptureRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="unused")
        )
        runtime = AsyncContextAwareRuntime(
            delegate,
            binding_factory=RuntimeIdentityBindingFactory(),
            collector=_collector(
                _BlockingAsyncMemoryStore(),
                memory_timeout_ms=10,
            ),
        )

        result = await runtime.run(
            _request(run_id="async-source-timeout"),
            emit=_ignore_event,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("context_unavailable", result.failure.code)
        self.assertEqual([], delegate.calls)

    async def test_caller_cancellation_propagates_without_delegate(self) -> None:
        memory = _BlockingAsyncMemoryStore()
        delegate = _CaptureRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="unused")
        )
        runtime = AsyncContextAwareRuntime(
            delegate,
            binding_factory=RuntimeIdentityBindingFactory(),
            collector=_collector(memory),
        )
        operation = asyncio.create_task(
            runtime.run(
                _request(run_id="async-cancelled"),
                emit=_ignore_event,
                control=RuntimeControl(CancellationToken()),
            )
        )
        await memory.started.wait()

        operation.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await operation

        self.assertTrue(memory.cancelled.is_set())
        self.assertEqual([], delegate.calls)

    async def test_binding_programmer_error_is_not_swallowed(self) -> None:
        delegate = _CaptureRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="unused")
        )

        def broken_factory(_request: RuntimeRequest) -> RuntimeContextBinding:
            raise TypeError("async binding programmer error")

        runtime = AsyncContextAwareRuntime(
            delegate,
            binding_factory=broken_factory,
            collector=_collector(_StaticAsyncMemoryStore()),
        )

        with self.assertRaisesRegex(TypeError, "async binding programmer error"):
            await runtime.run(
                _request(run_id="async-programmer-error"),
                emit=_ignore_event,
                control=RuntimeControl(CancellationToken()),
            )
        self.assertEqual([], delegate.calls)

    async def test_approval_pause_passes_through_unchanged(self) -> None:
        pause = RuntimeApprovalPause(
            approval_id="approval-1",
            tool_call_id="call-1",
            tool_name="guarded_tool",
            arguments_digest="0" * 64,
        )
        delegate = _CaptureRuntime(pause)
        runtime = AsyncContextAwareRuntime(
            delegate,
            binding_factory=RuntimeIdentityBindingFactory(),
            collector=_collector(_StaticAsyncMemoryStore()),
        )

        result = await runtime.run(
            _request(run_id="async-approval-pause"),
            emit=_ignore_event,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertIs(pause, result)
        self.assertEqual(1, len(delegate.calls))


class _RecordingBindingFactory:
    def __init__(self) -> None:
        self.requests: list[RuntimeRequest] = []

    def __call__(self, request: RuntimeRequest) -> RuntimeContextBinding:
        self.requests.append(request)
        return RuntimeContextBinding(
            owner_id="private-owner",
            session_id="private-session",
        )


class _CaptureRuntime:
    def __init__(self, outcome) -> None:
        self._outcome = outcome
        self.calls: list[tuple[RuntimeRequest, object, RuntimeControl]] = []

    async def run(self, request, *, emit, control):
        self.calls.append((request, emit, control))
        return self._outcome


class _StaticResolver:
    def resolve(self, query: str):
        del query
        return ()


class _StaticAsyncMemoryStore:
    def __init__(
        self,
        *,
        messages: tuple[Message, ...] = (),
        facts: tuple[MemoryFact, ...] = (),
    ) -> None:
        self._messages = messages
        self._facts = facts

    async def messages(self, session_id: str) -> tuple[Message, ...]:
        del session_id
        return self._messages

    async def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        del owner_id
        return self._facts


class _RecordingAsyncMemoryStore(_StaticAsyncMemoryStore):
    def __init__(self) -> None:
        super().__init__()
        self.calls = 0

    async def messages(self, session_id: str) -> tuple[Message, ...]:
        self.calls += 1
        return await super().messages(session_id)

    async def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        self.calls += 1
        return await super().facts(owner_id)


class _FailingAsyncMemoryStore:
    async def messages(self, session_id: str) -> tuple[Message, ...]:
        del session_id
        raise StoreUnavailableError()

    async def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        del owner_id
        raise AssertionError("facts must not run after message failure")


class _BlockingAsyncMemoryStore:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.cancelled = asyncio.Event()

    async def messages(self, session_id: str) -> tuple[Message, ...]:
        del session_id
        self.started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise

    async def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        del owner_id
        raise AssertionError("facts must not run after cancellation")


def _collector(
    memory_store,
    *,
    memory_timeout_ms: int = 5_000,
) -> AsyncMemoryContextSourceCollector:
    return AsyncMemoryContextSourceCollector(
        memory_store=memory_store,
        knowledge_base=InMemoryKnowledgeBase(),
        skill_context_builder=SkillContextBuilder(_StaticResolver()),
        memory_timeout_ms=memory_timeout_ms,
    )


def _request(*, run_id: str) -> RuntimeRequest:
    return RuntimeRequest(
        run_id=run_id,
        input_text="private async query",
        execution_context=ToolExecutionContext(
            principal_id="private-owner",
            roles=frozenset({"viewer"}),
        ),
        checkpoint_context=RuntimeCheckpointContext.for_run(
            run_id=run_id,
            owner_id="private-owner",
        ),
        context_identity=RuntimeContextIdentity(
            owner_id="private-owner",
            session_id="private-session",
        ),
    )


def _payload(prompt_context: str | None) -> dict[str, object]:
    assert prompt_context is not None
    return json.loads(prompt_context[prompt_context.index("{") :])


async def _ignore_event(event) -> None:
    del event


if __name__ == "__main__":
    unittest.main()
