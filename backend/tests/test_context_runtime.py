from __future__ import annotations

import json
import unittest
from collections.abc import Sequence

from backend.app.agent import (
    CancellationToken,
    RuntimeApprovalPause,
    RuntimeCheckpointContext,
    RuntimeControl,
    RuntimeRequest,
    RuntimeResult,
)
from backend.app.context import (
    ContextAssembler,
    ContextAwareRuntime,
    ContextSource,
    ContextSourceCollector,
    ContextSummaryResult,
    ContextSystemConstraint,
    RuntimeContextBinding,
    prepare_context_request,
)
from backend.app.domain import Message
from backend.app.domain.run import RunStatus
from backend.app.knowledge import Document, InMemoryKnowledgeBase
from backend.app.memory import ConversationMemory, MemoryFact, MemoryScope
from backend.app.skills import SkillContextBuilder, SkillDefinition
from backend.app.tools import ToolExecutionContext


class ContextRuntimePreparationTest(unittest.TestCase):
    def test_real_sources_prepare_one_bounded_runtime_request(self) -> None:
        memory = ConversationMemory()
        memory.append_message(
            "private-session",
            Message(role="user", content="Earlier private turn."),
        )
        memory.remember(
            owner_id="private-owner",
            key="locale",
            value="zh-CN",
            scope=MemoryScope.USER,
            approved=True,
        )
        knowledge = InMemoryKnowledgeBase()
        knowledge.add(
            Document(
                id="context-runtime",
                title="Context Runtime",
                source="docs/context-runtime.md",
                content="Runtime context evidence is assembled before delegation.",
            )
        )
        resolver = _RecordingResolver(
            (_skill("context-runtime", "Keep context bounded."),)
        )
        collector = _collector(
            memory=memory,
            knowledge=knowledge,
            resolver=resolver,
            summarizer=_SummaryProvider(
                ContextSummaryResult.from_content("Earlier private summary.")
            ),
        )
        binding_factory = _BindingFactory(
            owner_id="private-owner",
            session_id="private-session",
            system_constraints=(
                ContextSystemConstraint(
                    id="policy-v1",
                    content="Keep server policy active.",
                ),
            ),
        )
        execution_context = ToolExecutionContext(
            principal_id="private-owner",
            roles=frozenset({"viewer"}),
        )
        checkpoint_context = RuntimeCheckpointContext.for_run(
            run_id="context-run",
            owner_id="private-owner",
        )
        request = RuntimeRequest(
            run_id="context-run",
            input_text="Use context runtime evidence.",
            execution_context=execution_context,
            checkpoint_context=checkpoint_context,
        )

        prepared = prepare_context_request(
            request,
            binding_factory=binding_factory,
            collector=collector,
            assembler=ContextAssembler(),
        )

        self.assertEqual(1, len(binding_factory.requests))
        self.assertIs(request, binding_factory.requests[0])
        self.assertEqual([request.input_text], resolver.queries)
        self.assertIsNot(request, prepared.request)
        self.assertIs(request.run_id, prepared.request.run_id)
        self.assertIs(request.input_text, prepared.request.input_text)
        self.assertIs(execution_context, prepared.request.execution_context)
        self.assertIs(checkpoint_context, prepared.request.checkpoint_context)
        payload = _payload(prepared.request.prompt_context)
        self.assertEqual(
            {
                "system",
                "skill",
                "summary",
                "memory",
                "recent",
                "rag",
            },
            {fragment["source"] for fragment in payload["fragments"]},
        )

    def test_empty_sources_keep_the_original_request(self) -> None:
        request = RuntimeRequest(run_id="empty-context", input_text="nothing")

        prepared = prepare_context_request(
            request,
            binding_factory=_BindingFactory(),
            collector=_collector(),
            assembler=ContextAssembler(),
        )

        self.assertIs(request, prepared.request)
        self.assertIsNone(prepared.assembly.prompt_context)
        self.assertEqual(
            (ContextSource.SUMMARY,),
            prepared.assembly.report.unavailable_sources,
        )

    def test_binding_and_prepared_repr_hide_private_values(self) -> None:
        binding = RuntimeContextBinding(
            owner_id="private-owner",
            session_id="private-session",
            system_constraints=(
                ContextSystemConstraint(
                    id="safe-policy-id",
                    content="private-policy-content",
                ),
            ),
        )
        request = RuntimeRequest(
            run_id="private-repr",
            input_text="private-query-content",
        )

        prepared = prepare_context_request(
            request,
            binding_factory=lambda _request: binding,
            collector=_collector(),
            assembler=ContextAssembler(),
        )

        rendered = repr((binding, prepared))
        self.assertNotIn("private-owner", rendered)
        self.assertNotIn("private-session", rendered)
        self.assertNotIn("private-policy-content", rendered)
        self.assertNotIn("private-query-content", rendered)
        self.assertIn("safe-policy-id", rendered)


class ContextAwareRuntimeTest(unittest.IsolatedAsyncioTestCase):
    async def test_delegates_once_with_same_emit_and_control(self) -> None:
        expected = RuntimeResult(
            status=RunStatus.COMPLETED,
            answer="context-aware",
        )
        delegate = _CaptureRuntime(expected)
        runtime = ContextAwareRuntime(
            delegate,
            binding_factory=_BindingFactory(
                system_constraints=(
                    ContextSystemConstraint("policy-v1", "Server policy."),
                )
            ),
            collector=_collector(),
        )
        request = RuntimeRequest(run_id="delegated", input_text="hello")
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

    async def test_unavailable_summary_keeps_bounded_recent_context(self) -> None:
        memory = ConversationMemory(message_limit=2)
        for ordinal in range(1, 4):
            memory.append_message(
                "session-1",
                Message(role="user", content=f"recent-{ordinal}"),
            )
        assembler = _RecordingAssembler()
        delegate = _CaptureRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="bounded")
        )
        runtime = ContextAwareRuntime(
            delegate,
            binding_factory=_BindingFactory(session_id="session-1"),
            collector=_collector(memory=memory),
            assembler=assembler,
        )

        result = await runtime.run(
            RuntimeRequest(run_id="summary-unavailable", input_text="hello"),
            emit=_ignore_event,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.COMPLETED, result.status)
        prompt = delegate.calls[0][0].prompt_context
        self.assertNotIn("recent-1", prompt)
        self.assertIn("recent-2", prompt)
        self.assertIn("recent-3", prompt)
        assert assembler.assembly is not None
        self.assertEqual(
            (ContextSource.SUMMARY,),
            assembler.assembly.report.unavailable_sources,
        )

    async def test_existing_prompt_fails_before_binding_or_delegate(self) -> None:
        binding_factory = _BindingFactory()
        delegate = _CaptureRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="unused")
        )
        runtime = ContextAwareRuntime(
            delegate,
            binding_factory=binding_factory,
            collector=_collector(),
        )

        result = await runtime.run(
            RuntimeRequest(
                run_id="existing-prompt",
                input_text="private query",
                prompt_context="existing context",
            ),
            emit=_ignore_event,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("context_unavailable", result.failure.code)
        self.assertEqual([], binding_factory.requests)
        self.assertEqual([], delegate.calls)

    async def test_cross_owner_context_returns_content_free_failure(self) -> None:
        delegate = _CaptureRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="unused")
        )
        runtime = ContextAwareRuntime(
            delegate,
            binding_factory=_BindingFactory(owner_id="expected-owner"),
            collector=_collector(memory=_CrossOwnerMemory()),
        )

        result = await runtime.run(
            RuntimeRequest(run_id="cross-owner", input_text="private-query"),
            emit=_ignore_event,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("context_unavailable", result.failure.code)
        self.assertEqual("runtime", result.failure.category)
        self.assertEqual("Context is unavailable", result.failure.public_message)
        self.assertEqual(0, result.failure.step)
        self.assertEqual([], delegate.calls)
        rendered = repr(result) + str(result.failure)
        self.assertNotIn("expected-owner", rendered)
        self.assertNotIn("unexpected-owner", rendered)
        self.assertNotIn("private-value", rendered)
        self.assertNotIn("private-query", rendered)

    async def test_invalid_binding_returns_stable_failure(self) -> None:
        delegate = _CaptureRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="unused")
        )
        runtime = ContextAwareRuntime(
            delegate,
            binding_factory=lambda _request: object(),
            collector=_collector(),
        )

        result = await runtime.run(
            RuntimeRequest(run_id="invalid-binding", input_text="hello"),
            emit=_ignore_event,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertEqual(RunStatus.FAILED, result.status)
        self.assertEqual("context_unavailable", result.failure.code)
        self.assertEqual([], delegate.calls)

    async def test_binding_programmer_error_is_not_swallowed(self) -> None:
        delegate = _CaptureRuntime(
            RuntimeResult(status=RunStatus.COMPLETED, answer="unused")
        )

        def broken_factory(_request: RuntimeRequest) -> RuntimeContextBinding:
            raise TypeError("binding programmer error")

        runtime = ContextAwareRuntime(
            delegate,
            binding_factory=broken_factory,
            collector=_collector(),
        )

        with self.assertRaisesRegex(TypeError, "binding programmer error"):
            await runtime.run(
                RuntimeRequest(run_id="programmer-error", input_text="hello"),
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
        runtime = ContextAwareRuntime(
            delegate,
            binding_factory=_BindingFactory(),
            collector=_collector(),
        )

        result = await runtime.run(
            RuntimeRequest(run_id="approval-pause", input_text="hello"),
            emit=_ignore_event,
            control=RuntimeControl(CancellationToken()),
        )

        self.assertIs(pause, result)
        self.assertEqual(1, len(delegate.calls))


class _BindingFactory:
    def __init__(
        self,
        *,
        owner_id: str = "owner-1",
        session_id: str = "session-1",
        system_constraints: tuple[ContextSystemConstraint, ...] = (),
    ) -> None:
        self._binding = RuntimeContextBinding(
            owner_id=owner_id,
            session_id=session_id,
            system_constraints=system_constraints,
        )
        self.requests: list[RuntimeRequest] = []

    def __call__(self, request: RuntimeRequest) -> RuntimeContextBinding:
        self.requests.append(request)
        return self._binding


class _CaptureRuntime:
    def __init__(self, outcome) -> None:
        self._outcome = outcome
        self.calls: list[tuple[RuntimeRequest, object, RuntimeControl]] = []

    async def run(self, request, *, emit, control):
        self.calls.append((request, emit, control))
        return self._outcome


class _RecordingAssembler(ContextAssembler):
    def __init__(self) -> None:
        super().__init__()
        self.assembly = None

    def assemble(self, **kwargs):
        self.assembly = super().assemble(**kwargs)
        return self.assembly


class _RecordingResolver:
    def __init__(self, skills: tuple[SkillDefinition, ...] = ()) -> None:
        self._skills = skills
        self.queries: list[str] = []

    def resolve(self, query: str) -> tuple[SkillDefinition, ...]:
        self.queries.append(query)
        return self._skills


class _SummaryProvider:
    def __init__(self, result: ContextSummaryResult) -> None:
        self._result = result

    def summarize(
        self,
        *,
        owner_id: str,
        session_id: str,
        messages: Sequence[Message],
    ) -> ContextSummaryResult:
        del owner_id, session_id, messages
        return self._result


class _CrossOwnerMemory:
    def messages(self, session_id: str) -> tuple[Message, ...]:
        del session_id
        return ()

    def facts(self, owner_id: str) -> tuple[MemoryFact, ...]:
        del owner_id
        return (
            MemoryFact(
                id="private-fact",
                owner_id="unexpected-owner",
                key="private-key",
                value="private-value",
                scope=MemoryScope.USER,
            ),
        )


def _collector(
    *,
    memory=None,
    knowledge=None,
    resolver=None,
    summarizer=None,
) -> ContextSourceCollector:
    return ContextSourceCollector(
        memory_store=memory if memory is not None else ConversationMemory(),
        knowledge_base=(
            knowledge if knowledge is not None else InMemoryKnowledgeBase()
        ),
        skill_context_builder=SkillContextBuilder(
            resolver if resolver is not None else _RecordingResolver()
        ),
        summarizer=summarizer,
    )


def _skill(name: str, instructions: str) -> SkillDefinition:
    return SkillDefinition(
        name=name,
        description="Controlled test Skill.",
        instructions=instructions,
    )


def _payload(prompt_context: str | None) -> dict[str, object]:
    assert prompt_context is not None
    return json.loads(prompt_context[prompt_context.index("{") :])


async def _ignore_event(event) -> None:
    del event


if __name__ == "__main__":
    unittest.main()
