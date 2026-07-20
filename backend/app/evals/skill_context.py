from __future__ import annotations

import asyncio
import json
import re
from collections.abc import Sequence
from dataclasses import dataclass, field

from backend.app.agent.cancellation import CancellationToken
from backend.app.agent.graph_runtime import LangGraphRuntime
from backend.app.agent.runtime import (
    AgentRuntime,
    RuntimeControl,
    RuntimeEvent,
    RuntimeRequest,
)
from backend.app.domain import Message, ModelDecision
from backend.app.domain.run import RunStatus
from backend.app.skills.context import (
    SkillContextBuilder,
    SkillContextCost,
    default_skill_context_builder,
)
from backend.app.skills.runtime import prepare_skill_request
from backend.app.tools import ToolDefinition, ToolRegistry


_CASE_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")


@dataclass(frozen=True)
class SkillContextEvalCase:
    id: str
    input_text: str = field(repr=False)
    expected_skill_names: tuple[str, ...] = ()
    answer_contains: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if _CASE_ID_PATTERN.fullmatch(self.id) is None:
            raise ValueError("Skill evaluation case id has an invalid format")
        if not isinstance(self.input_text, str) or not self.input_text.strip():
            raise ValueError("Skill evaluation input must not be empty")


@dataclass(frozen=True)
class SkillContextEvalFailure:
    check: str
    expected: str
    actual: str = field(repr=False)

    def to_record(self) -> dict[str, str]:
        return {
            "check": self.check,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True)
class SkillContextEvalResult:
    case_id: str
    status: RunStatus
    answer: str | None = field(repr=False)
    matched_skill_names: tuple[str, ...]
    input_cost: SkillContextCost
    context_cost: SkillContextCost
    failures: tuple[SkillContextEvalFailure, ...]

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_record(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "status": self.status.value,
            "answer": self.answer,
            "matched_skill_names": list(self.matched_skill_names),
            "input_cost": self.input_cost.to_record(),
            "context_cost": self.context_cost.to_record(),
            "failures": [failure.to_record() for failure in self.failures],
        }


@dataclass(frozen=True)
class SkillContextEvalReport:
    evidence: str
    results: tuple[SkillContextEvalResult, ...]

    @property
    def passed_cases(self) -> int:
        return sum(result.passed for result in self.results)

    @property
    def failed_cases(self) -> int:
        return len(self.results) - self.passed_cases

    @property
    def total_context_bytes(self) -> int:
        return sum(result.context_cost.utf8_bytes for result in self.results)

    @property
    def total_estimated_context_tokens(self) -> int:
        return sum(
            result.context_cost.estimated_input_tokens
            for result in self.results
        )

    def to_record(self) -> dict[str, object]:
        return {
            "evidence": self.evidence,
            "total_cases": len(self.results),
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "total_context_bytes": self.total_context_bytes,
            "total_estimated_context_tokens": (
                self.total_estimated_context_tokens
            ),
            "provider_usage_available": False,
            "estimated_cost_usd": None,
            "results": [result.to_record() for result in self.results],
        }


class SkillContextEvaluator:
    """Compare Skill-triggered behavior and prompt overhead offline."""

    def __init__(
        self,
        runtime: AgentRuntime,
        *,
        builder: SkillContextBuilder,
    ) -> None:
        self._runtime = runtime
        self._builder = builder

    async def evaluate(
        self,
        cases: Sequence[SkillContextEvalCase],
    ) -> SkillContextEvalReport:
        if not cases:
            raise ValueError("at least one Skill evaluation case is required")
        case_ids = tuple(case.id for case in cases)
        if len(case_ids) != len(set(case_ids)):
            raise ValueError("Skill evaluation case ids must be unique")
        results = []
        for case in cases:
            results.append(await self._evaluate_case(case))
        return SkillContextEvalReport(
            evidence=(
                "offline deterministic Runtime evaluation; token counts are "
                "UTF-8 heuristics, not Provider usage or billing"
            ),
            results=tuple(results),
        )

    async def _evaluate_case(
        self,
        case: SkillContextEvalCase,
    ) -> SkillContextEvalResult:
        prepared = prepare_skill_request(
            RuntimeRequest(
                run_id=f"skill-eval-{case.id}",
                input_text=case.input_text,
            ),
            builder=self._builder,
        )
        async def discard(event: RuntimeEvent) -> None:
            del event

        result = await self._runtime.run(
            prepared.request,
            emit=discard,
            control=RuntimeControl(CancellationToken()),
        )
        matched_names = (
            prepared.context.skill_names
            if prepared.context is not None
            else ()
        )
        failures: list[SkillContextEvalFailure] = []
        if result.status is not RunStatus.COMPLETED:
            failures.append(
                SkillContextEvalFailure(
                    check="status",
                    expected=RunStatus.COMPLETED.value,
                    actual=result.status.value,
                )
            )
        if matched_names != case.expected_skill_names:
            failures.append(
                SkillContextEvalFailure(
                    check="matched_skill_names",
                    expected=repr(case.expected_skill_names),
                    actual=repr(matched_names),
                )
            )
        answer = result.answer or ""
        for expected in case.answer_contains:
            if expected not in answer:
                failures.append(
                    SkillContextEvalFailure(
                        check="answer_contains",
                        expected=expected,
                        actual=answer,
                    )
                )
        return SkillContextEvalResult(
            case_id=case.id,
            status=result.status,
            answer=result.answer,
            matched_skill_names=matched_names,
            input_cost=SkillContextCost.from_text(case.input_text),
            context_cost=(
                prepared.context.cost
                if prepared.context is not None
                else SkillContextCost.from_text("")
            ),
            failures=tuple(failures),
        )


class _DeterministicSkillEvalModel:
    """Offline fixture model for a reproducible effect comparison."""

    def decide(
        self,
        messages: Sequence[Message],
        tools: Sequence[ToolDefinition],
    ) -> ModelDecision:
        del tools
        system_context = "\n".join(
            message.content for message in messages if message.role == "system"
        )
        if (
            "research-summary" in system_context
            and "citation correctness" in system_context
        ):
            return ModelDecision(
                final_answer=(
                    "结论：试点缩短了排队时间 [source-1]。"
                    "分歧与限制：仅有一个来源，证据仍有限。"
                )
            )
        return ModelDecision(final_answer="通用处理：试点缩短了排队时间。")


def default_skill_context_eval_cases() -> tuple[SkillContextEvalCase, ...]:
    return (
        SkillContextEvalCase(
            id="triggered-research-summary",
            input_text=(
                "Use $research-summary. Source source-1 says the pilot "
                "reduced queue time."
            ),
            expected_skill_names=("research-summary",),
            answer_contains=("source-1", "分歧与限制"),
        ),
        SkillContextEvalCase(
            id="untriggered-general-note",
            input_text=(
                "Rewrite this note briefly: the pilot reduced queue time."
            ),
            expected_skill_names=(),
            answer_contains=("通用处理",),
        ),
    )


async def run_default_skill_context_eval() -> SkillContextEvalReport:
    runtime = LangGraphRuntime(
        model_factory=lambda _request: _DeterministicSkillEvalModel(),
        tool_registry_factory=lambda _request: ToolRegistry(),
        max_steps=2,
        max_model_retries=0,
    )
    return await SkillContextEvaluator(
        runtime,
        builder=default_skill_context_builder(),
    ).evaluate(default_skill_context_eval_cases())


def main() -> None:
    report = asyncio.run(run_default_skill_context_eval())
    print(json.dumps(report.to_record(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()


__all__ = [
    "SkillContextEvalCase",
    "SkillContextEvalFailure",
    "SkillContextEvalReport",
    "SkillContextEvalResult",
    "SkillContextEvaluator",
    "default_skill_context_eval_cases",
    "run_default_skill_context_eval",
]
