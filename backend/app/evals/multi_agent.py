from __future__ import annotations

import asyncio
import json
import math
import re
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass, field
from time import perf_counter
from typing import Any, Literal

from agents import Runner
from agents.items import ModelResponse
from agents.model_settings import ModelSettings
from agents.models.interface import Model, ModelTracing
from agents.tracing import set_trace_provider
from agents.tracing.provider import DefaultTraceProvider
from agents.usage import Usage
from openai.types.responses import (
    ResponseFunctionToolCall,
    ResponseOutputMessage,
    ResponseOutputText,
)

from backend.app.agent.cancellation import CancellationToken
from backend.app.agent.multi_agent import (
    MANAGER_INSTRUCTIONS,
    MANAGER_MAX_TURNS,
    RESEARCHER_INSTRUCTIONS,
    REVIEWER_INSTRUCTIONS,
    SINGLE_AGENT_INSTRUCTIONS,
    WRITER_INSTRUCTIONS,
    OrchestrationComplexity,
    create_manager_as_tools_topology,
    create_safe_multi_agent_run_config,
    create_single_agent_topology,
)
from backend.app.agent.sdk_tools import (
    OpenAIAgentsRunContext,
    build_sdk_tools,
)
from backend.app.tools import ToolDefinition, ToolExecutionContext, ToolRegistry


StrategyName = Literal["manager_as_tools", "single_agent"]
Clock = Callable[[], float]
_CASE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,80}")
_FIXTURE_INPUT_TOKENS = 8
_FIXTURE_OUTPUT_TOKENS = 4


def _required_text(value: object, label: str, *, max_length: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > max_length
        or any(not character.isprintable() for character in value)
    ):
        raise ValueError(f"{label} has an invalid format")
    return value


@dataclass(frozen=True)
class CollaborationEvalCase:
    id: str
    input_text: str
    fact: str = field(repr=False)
    expected_terms: tuple[str, ...]

    def __post_init__(self) -> None:
        if _CASE_ID_PATTERN.fullmatch(self.id) is None:
            raise ValueError("case id has an invalid format")
        _required_text(self.input_text, "input_text", max_length=2_000)
        _required_text(self.fact, "fact", max_length=4_000)
        if not self.expected_terms:
            raise ValueError("expected_terms must not be empty")
        normalized = tuple(
            _required_text(term, "expected term", max_length=200)
            for term in self.expected_terms
        )
        if len(normalized) != len(set(normalized)):
            raise ValueError("expected_terms must be unique")
        object.__setattr__(self, "expected_terms", normalized)


@dataclass(frozen=True)
class StrategyCaseResult:
    case_id: str
    quality_score: float
    latency_ms: float
    model_requests: int | None
    total_tokens: int | None
    matched_terms: tuple[str, ...]
    expected_term_count: int
    role_model_calls: tuple[tuple[str, int], ...]
    tool_calls: tuple[tuple[str, int], ...]
    error_code: str | None = None

    @property
    def passed(self) -> bool:
        return self.error_code is None and self.quality_score == 1.0

    def to_record(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "quality_score": round(self.quality_score, 4),
            "latency_ms": round(self.latency_ms, 3),
            "model_requests": self.model_requests,
            "total_tokens": self.total_tokens,
            "matched_term_count": len(self.matched_terms),
            "expected_term_count": self.expected_term_count,
            "role_model_calls": dict(self.role_model_calls),
            "tool_calls": dict(self.tool_calls),
            "error_code": self.error_code,
        }


@dataclass(frozen=True)
class StrategyMetrics:
    strategy: StrategyName
    results: tuple[StrategyCaseResult, ...]
    complexity: OrchestrationComplexity

    @property
    def quality_score(self) -> float:
        if not self.results:
            return 0.0
        return sum(result.quality_score for result in self.results) / len(
            self.results
        )

    @property
    def failure_rate(self) -> float:
        if not self.results:
            return 0.0
        return sum(not result.passed for result in self.results) / len(
            self.results
        )

    @property
    def total_latency_ms(self) -> float:
        return sum(result.latency_ms for result in self.results)

    @property
    def total_model_requests(self) -> int | None:
        values = tuple(result.model_requests for result in self.results)
        if any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

    @property
    def total_tokens(self) -> int | None:
        values = tuple(result.total_tokens for result in self.results)
        if any(value is None for value in values):
            return None
        return sum(value for value in values if value is not None)

    def to_record(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "quality_score": round(self.quality_score, 4),
            "failure_rate": round(self.failure_rate, 4),
            "total_latency_ms": round(self.total_latency_ms, 3),
            "total_model_requests": self.total_model_requests,
            "total_tokens": self.total_tokens,
            "complexity": {
                "agent_count": self.complexity.agent_count,
                "business_tool_count": self.complexity.business_tool_count,
                "orchestration_tool_count": (
                    self.complexity.orchestration_tool_count
                ),
                "routing_edge_count": self.complexity.routing_edge_count,
                "complexity_units": self.complexity.complexity_units,
            },
            "results": [result.to_record() for result in self.results],
        }


@dataclass(frozen=True)
class CollaborationComparisonReport:
    manager_as_tools: StrategyMetrics
    single_agent: StrategyMetrics
    preferred_strategy: StrategyName
    decision_code: str
    evidence_level: str = "E2_offline_fixture"

    def to_record(self) -> dict[str, object]:
        return {
            "preferred_strategy": self.preferred_strategy,
            "decision_code": self.decision_code,
            "evidence_level": self.evidence_level,
            "trace_scope": "process_local_disabled_provider",
            "latency_scope": "local_runner_with_fixture_model_delay",
            "token_scope": "deterministic_fixture_usage_not_provider_billing",
            "manager_as_tools": self.manager_as_tools.to_record(),
            "single_agent": self.single_agent.to_record(),
        }


DEFAULT_COLLABORATION_CASES = (
    CollaborationEvalCase(
        id="approval-binding",
        input_text="Why must an approval be server-bound?",
        fact=(
            "Approval binds the run, principal, tool call, tool name, and "
            "argument digest, then consumes the exact grant once."
        ),
        expected_terms=("run", "principal", "argument digest", "once"),
    ),
    CollaborationEvalCase(
        id="checkpoint-boundary",
        input_text="What does InMemorySaver recovery prove?",
        fact=(
            "InMemorySaver proves same-process recovery across runtime "
            "instances; it does not prove process-restart persistence."
        ),
        expected_terms=("same-process", "runtime", "process-restart"),
    ),
    CollaborationEvalCase(
        id="replanning-gate",
        input_text="When may a failed step be replanned?",
        fact=(
            "Replanning requires a retryable failure, a server allowlist "
            "match, a safe category, and a step with no side effects."
        ),
        expected_terms=("retryable", "allowlist", "safe", "no side effects"),
    ),
)


async def run_offline_multi_agent_comparison(
    cases: Sequence[CollaborationEvalCase] = DEFAULT_COLLABORATION_CASES,
    *,
    model_delay_ms: float = 1.0,
    clock: Clock = perf_counter,
) -> CollaborationComparisonReport:
    """Compare both strategies in a dedicated offline evaluator process."""

    checked_cases = _checked_cases(cases)
    if (
        not isinstance(model_delay_ms, (int, float))
        or isinstance(model_delay_ms, bool)
        or not math.isfinite(model_delay_ms)
        or model_delay_ms < 0
        or model_delay_ms > 100
    ):
        raise ValueError("model_delay_ms must be between 0 and 100")
    _install_offline_trace_provider()

    manager_metrics = await _evaluate_strategy(
        "manager_as_tools",
        checked_cases,
        model_delay_ms=float(model_delay_ms),
        clock=clock,
    )
    single_metrics = await _evaluate_strategy(
        "single_agent",
        checked_cases,
        model_delay_ms=float(model_delay_ms),
        clock=clock,
    )
    if (
        manager_metrics.quality_score > single_metrics.quality_score
        and manager_metrics.failure_rate <= single_metrics.failure_rate
    ):
        preferred: StrategyName = "manager_as_tools"
        decision_code = "multi_agent_quality_gain"
    else:
        preferred = "single_agent"
        decision_code = "no_multi_agent_quality_gain"
    return CollaborationComparisonReport(
        manager_as_tools=manager_metrics,
        single_agent=single_metrics,
        preferred_strategy=preferred,
        decision_code=decision_code,
    )


@dataclass
class _FixtureRunState:
    case: CollaborationEvalCase
    fact: str | None = None
    draft: str | None = None
    review_passed: bool | None = None
    model_calls: dict[str, int] = field(default_factory=dict)
    tool_calls: dict[str, int] = field(default_factory=dict)


class _DeterministicCollaborationModel(Model):
    """Offline model fixture that drives the public SDK Runner/tool loop."""

    def __init__(self, state: _FixtureRunState, *, delay_ms: float) -> None:
        self._state = state
        self._delay_seconds = delay_ms / 1_000

    async def get_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: ModelSettings,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> ModelResponse:
        del (
            input,
            model_settings,
            output_schema,
            handoffs,
            tracing,
            previous_response_id,
            conversation_id,
            prompt,
        )
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        role = _role_from_instructions(system_instructions)
        turn = self._state.model_calls.get(role, 0) + 1
        self._state.model_calls[role] = turn
        tool_names = {tool.name for tool in tools}
        output = self._next_output(role, turn, tool_names)
        return ModelResponse(
            output=[output],
            usage=Usage(
                requests=1,
                input_tokens=_FIXTURE_INPUT_TOKENS,
                output_tokens=_FIXTURE_OUTPUT_TOKENS,
                total_tokens=(
                    _FIXTURE_INPUT_TOKENS + _FIXTURE_OUTPUT_TOKENS
                ),
            ),
            response_id=None,
        )

    async def stream_response(
        self,
        system_instructions: str | None,
        input: str | list[Any],
        model_settings: ModelSettings,
        tools: list[Any],
        output_schema: Any,
        handoffs: list[Any],
        tracing: ModelTracing,
        *,
        previous_response_id: str | None,
        conversation_id: str | None,
        prompt: Any,
    ) -> AsyncIterator[Any]:
        del (
            system_instructions,
            input,
            model_settings,
            tools,
            output_schema,
            handoffs,
            tracing,
            previous_response_id,
            conversation_id,
            prompt,
        )
        if False:
            yield None
        raise RuntimeError("fixture streaming is not supported")

    def _next_output(
        self,
        role: str,
        turn: int,
        tool_names: set[str],
    ) -> ResponseFunctionToolCall | ResponseOutputMessage:
        if role == "manager":
            sequence = (
                (
                    "research_course_fact",
                    {"input": self._state.case.input_text},
                ),
                (
                    "draft_course_answer",
                    {"input": self._state.fact or "research unavailable"},
                ),
                (
                    "review_course_answer",
                    {"input": self._state.draft or "draft unavailable"},
                ),
            )
            if turn <= len(sequence):
                name, arguments = sequence[turn - 1]
                return _tool_call(role, turn, name, arguments, tool_names)
            if turn == 4 and self._state.review_passed is True:
                return _message(role, turn, self._state.draft or "")
        elif role == "researcher":
            if turn == 1:
                return _tool_call(
                    role,
                    turn,
                    "lookup_course_fact",
                    {"topic": self._state.case.input_text},
                    tool_names,
                )
            if turn == 2 and self._state.fact is not None:
                return _message(role, turn, self._state.fact)
        elif role == "writer":
            if turn == 1 and self._state.fact is not None:
                self._state.draft = self._state.fact
                return _message(role, turn, self._state.draft)
        elif role == "reviewer":
            if turn == 1 and self._state.draft is not None:
                return _tool_call(
                    role,
                    turn,
                    "check_required_terms",
                    {"answer": self._state.draft},
                    tool_names,
                )
            if turn == 2 and self._state.review_passed is not None:
                verdict = "approved" if self._state.review_passed else "revise"
                return _message(role, turn, verdict)
        elif role == "single":
            if turn == 1:
                return _tool_call(
                    role,
                    turn,
                    "lookup_course_fact",
                    {"topic": self._state.case.input_text},
                    tool_names,
                )
            if turn == 2 and self._state.fact is not None:
                self._state.draft = self._state.fact
                return _tool_call(
                    role,
                    turn,
                    "check_required_terms",
                    {"answer": self._state.draft},
                    tool_names,
                )
            if turn == 3 and self._state.review_passed is True:
                return _message(role, turn, self._state.draft or "")
        raise RuntimeError("fixture model reached an invalid collaboration state")


async def _evaluate_strategy(
    strategy: StrategyName,
    cases: tuple[CollaborationEvalCase, ...],
    *,
    model_delay_ms: float,
    clock: Clock,
) -> StrategyMetrics:
    results: list[StrategyCaseResult] = []
    complexity: OrchestrationComplexity | None = None
    for case in cases:
        state = _FixtureRunState(case)
        model = _DeterministicCollaborationModel(
            state,
            delay_ms=model_delay_ms,
        )
        run_context = _run_context(case, strategy)
        agent, current_complexity, max_turns = _build_strategy(
            strategy,
            state=state,
            model=model,
            run_context=run_context,
        )
        complexity = current_complexity
        started_at = clock()
        answer = ""
        usage: Usage | None = None
        error_code: str | None = None
        try:
            result = await Runner.run(
                starting_agent=agent,
                input=case.input_text,
                context=run_context,
                max_turns=max_turns,
                run_config=create_safe_multi_agent_run_config(),
            )
            usage = result.context_wrapper.usage
            if isinstance(result.final_output, str):
                answer = result.final_output
            else:
                error_code = "collaboration_output_invalid"
        except Exception:
            error_code = "collaboration_execution_failed"
        latency_ms = max(0.0, (clock() - started_at) * 1_000)
        normalized_answer = answer.casefold()
        matched_terms = tuple(
            term
            for term in case.expected_terms
            if term.casefold() in normalized_answer
        )
        quality_score = len(matched_terms) / len(case.expected_terms)
        results.append(
            StrategyCaseResult(
                case_id=case.id,
                quality_score=quality_score,
                latency_ms=latency_ms,
                model_requests=(usage.requests if usage is not None else None),
                total_tokens=(usage.total_tokens if usage is not None else None),
                matched_terms=matched_terms,
                expected_term_count=len(case.expected_terms),
                role_model_calls=tuple(sorted(state.model_calls.items())),
                tool_calls=tuple(sorted(state.tool_calls.items())),
                error_code=error_code,
            )
        )
    if complexity is None:
        raise ValueError("at least one evaluation case is required")
    return StrategyMetrics(
        strategy=strategy,
        results=tuple(results),
        complexity=complexity,
    )


def _build_strategy(
    strategy: StrategyName,
    *,
    state: _FixtureRunState,
    model: Model,
    run_context: OpenAIAgentsRunContext,
) -> tuple[Any, OrchestrationComplexity, int]:
    research_registry, review_registry, combined_registry = _registries(state)
    research_tools = build_sdk_tools(research_registry, run_context=run_context)
    review_tools = build_sdk_tools(review_registry, run_context=run_context)
    if strategy == "manager_as_tools":
        topology = create_manager_as_tools_topology(
            model=model,
            researcher_tools=research_tools,
            reviewer_tools=review_tools,
        )
        return topology.manager, topology.complexity, MANAGER_MAX_TURNS
    topology = create_single_agent_topology(
        model=model,
        tools=build_sdk_tools(combined_registry, run_context=run_context),
    )
    return topology.agent, topology.complexity, 5


def _registries(
    state: _FixtureRunState,
) -> tuple[ToolRegistry, ToolRegistry, ToolRegistry]:
    def lookup(arguments: dict[str, Any]) -> dict[str, str]:
        del arguments
        state.tool_calls["lookup_course_fact"] = (
            state.tool_calls.get("lookup_course_fact", 0) + 1
        )
        state.fact = state.case.fact
        return {"fact": state.fact}

    def review(arguments: dict[str, Any]) -> dict[str, object]:
        state.tool_calls["check_required_terms"] = (
            state.tool_calls.get("check_required_terms", 0) + 1
        )
        answer = arguments["answer"].casefold()
        missing = tuple(
            term
            for term in state.case.expected_terms
            if term.casefold() not in answer
        )
        state.review_passed = not missing
        return {"approved": not missing, "missing_count": len(missing)}

    lookup_definition = ToolDefinition(
        name="lookup_course_fact",
        description="Look up one fixed course fact by topic.",
        input_schema={
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 2_000,
                }
            },
            "required": ["topic"],
            "additionalProperties": False,
        },
        handler=lookup,
        allowed_roles=frozenset({"course_reader"}),
    )
    review_definition = ToolDefinition(
        name="check_required_terms",
        description="Check a draft against server-owned required terms.",
        input_schema={
            "type": "object",
            "properties": {
                "answer": {
                    "type": "string",
                    "minLength": 1,
                    "maxLength": 4_000,
                }
            },
            "required": ["answer"],
            "additionalProperties": False,
        },
        handler=review,
        allowed_roles=frozenset({"course_reader"}),
    )
    research_registry = ToolRegistry()
    research_registry.register(lookup_definition)
    review_registry = ToolRegistry()
    review_registry.register(review_definition)
    combined_registry = ToolRegistry()
    combined_registry.register(lookup_definition)
    combined_registry.register(review_definition)
    return research_registry, review_registry, combined_registry


def _run_context(
    case: CollaborationEvalCase,
    strategy: StrategyName,
) -> OpenAIAgentsRunContext:
    run_id = f"m10-t4-{strategy}-{case.id}"
    return OpenAIAgentsRunContext(
        run_id=run_id,
        execution_context=ToolExecutionContext(
            principal_id="offline-evaluator",
            roles=frozenset({"course_reader"}),
            run_id=run_id,
        ),
        cancellation_token=CancellationToken(),
    )


def _install_offline_trace_provider() -> None:
    provider = DefaultTraceProvider()
    provider.set_disabled(True)
    set_trace_provider(provider)


def _role_from_instructions(instructions: str | None) -> str:
    markers = {
        MANAGER_INSTRUCTIONS: "manager",
        RESEARCHER_INSTRUCTIONS: "researcher",
        WRITER_INSTRUCTIONS: "writer",
        REVIEWER_INSTRUCTIONS: "reviewer",
        SINGLE_AGENT_INSTRUCTIONS: "single",
    }
    try:
        return markers[instructions]
    except KeyError:
        raise RuntimeError("fixture received unknown agent instructions") from None


def _tool_call(
    role: str,
    turn: int,
    name: str,
    arguments: dict[str, str],
    available_tools: set[str],
) -> ResponseFunctionToolCall:
    if name not in available_tools:
        raise RuntimeError("fixture attempted an unavailable role tool")
    return ResponseFunctionToolCall(
        arguments=json.dumps(
            arguments,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ),
        call_id=f"{role}-{turn}-call",
        name=name,
        type="function_call",
    )


def _message(role: str, turn: int, text: str) -> ResponseOutputMessage:
    return ResponseOutputMessage(
        id=f"{role}-{turn}-message",
        content=[
            ResponseOutputText(
                annotations=[],
                text=text,
                type="output_text",
            )
        ],
        role="assistant",
        status="completed",
        type="message",
    )


def _checked_cases(
    cases: Sequence[CollaborationEvalCase],
) -> tuple[CollaborationEvalCase, ...]:
    checked = tuple(cases)
    if not checked:
        raise ValueError("at least one evaluation case is required")
    if any(not isinstance(case, CollaborationEvalCase) for case in checked):
        raise ValueError("cases must contain CollaborationEvalCase values")
    ids = tuple(case.id for case in checked)
    if len(ids) != len(set(ids)):
        raise ValueError("evaluation case ids must be unique")
    return checked


async def _main() -> None:
    report = await run_offline_multi_agent_comparison()
    print(json.dumps(report.to_record(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(_main())


__all__ = [
    "CollaborationComparisonReport",
    "CollaborationEvalCase",
    "DEFAULT_COLLABORATION_CASES",
    "StrategyCaseResult",
    "StrategyMetrics",
    "run_offline_multi_agent_comparison",
]
