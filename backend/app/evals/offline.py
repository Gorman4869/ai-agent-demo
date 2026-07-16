from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal
from uuid import uuid4

from backend.app.domain import AgentRunResult
from backend.app.observability import RunObservation, RunObserver


@dataclass(frozen=True)
class EvalCase:
    id: str
    input: str
    expected_status: Literal["completed", "failed"] = "completed"
    answer_contains: tuple[str, ...] = ()
    required_event_types: tuple[str, ...] = ()
    required_tool_names: tuple[str, ...] = ()
    required_successful_tool_names: tuple[str, ...] = ()
    required_error_categories: tuple[str, ...] = ()
    error_contains: tuple[str, ...] = ()
    max_duration_ms: float | None = None
    expected_usage_available: bool | None = None
    max_estimated_cost_usd: float | None = None

    def __post_init__(self) -> None:
        if not self.id.strip():
            raise ValueError("evaluation case id must not be empty")
        if not self.input.strip():
            raise ValueError("evaluation case input must not be empty")
        if self.max_duration_ms is not None and self.max_duration_ms < 0:
            raise ValueError("max_duration_ms must not be negative")
        if (
            self.max_estimated_cost_usd is not None
            and self.max_estimated_cost_usd < 0
        ):
            raise ValueError("max_estimated_cost_usd must not be negative")


@dataclass(frozen=True)
class EvalFailure:
    check: str
    expected: str
    actual: str

    def to_record(self) -> dict[str, str]:
        return {
            "check": self.check,
            "expected": self.expected,
            "actual": self.actual,
        }


@dataclass(frozen=True)
class EvalCaseResult:
    case_id: str
    observation: RunObservation
    failures: tuple[EvalFailure, ...]

    @property
    def passed(self) -> bool:
        return not self.failures

    def to_record(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "passed": self.passed,
            "observation": self.observation.to_record(),
            "failures": [failure.to_record() for failure in self.failures],
        }


@dataclass(frozen=True)
class EvalReport:
    batch_id: str
    results: tuple[EvalCaseResult, ...]

    @property
    def total_cases(self) -> int:
        return len(self.results)

    @property
    def passed_cases(self) -> int:
        return sum(result.passed for result in self.results)

    @property
    def failed_cases(self) -> int:
        return self.total_cases - self.passed_cases

    @property
    def pass_rate(self) -> float:
        return self.passed_cases / self.total_cases if self.total_cases else 0.0

    @property
    def failures(self) -> tuple[EvalCaseResult, ...]:
        return tuple(result for result in self.results if not result.passed)

    def to_record(self) -> dict[str, object]:
        return {
            "batch_id": self.batch_id,
            "total_cases": self.total_cases,
            "passed_cases": self.passed_cases,
            "failed_cases": self.failed_cases,
            "pass_rate": round(self.pass_rate, 4),
            "results": [result.to_record() for result in self.results],
        }


AgentRunner = Callable[[str], AgentRunResult]
BatchIdFactory = Callable[[], str]


class OfflineEvaluator:
    """Run deterministic, network-free checks against an Agent runner."""

    def __init__(
        self,
        runner: AgentRunner,
        *,
        observer: RunObserver | None = None,
        batch_id_factory: BatchIdFactory | None = None,
    ) -> None:
        self._runner = runner
        self._observer = observer or RunObserver()
        self._batch_id_factory = batch_id_factory or (lambda: str(uuid4()))

    def evaluate(self, cases: Sequence[EvalCase]) -> EvalReport:
        _validate_cases(cases)
        batch_id = self._batch_id_factory().strip()
        if not batch_id:
            raise ValueError("evaluation batch id must not be empty")
        results = [self._evaluate_case(case, batch_id) for case in cases]
        return EvalReport(batch_id=batch_id, results=tuple(results))

    def _evaluate_case(self, case: EvalCase, batch_id: str) -> EvalCaseResult:
        span = self._observer.start(run_id=f"eval-{batch_id}-{case.id}")
        try:
            result = self._runner(case.input)
        except Exception as error:
            observation = self._observer.fail(span, error)
            failure = EvalFailure(
                check="runner_exception",
                expected="runner returns AgentRunResult",
                actual=f"{type(error).__name__}: {error}",
            )
            return EvalCaseResult(case.id, observation, (failure,))

        observation = self._observer.complete(span, result)
        failures = _check_expectations(case, result, observation)
        return EvalCaseResult(case.id, observation, failures)


def _validate_cases(cases: Sequence[EvalCase]) -> None:
    if not cases:
        raise ValueError("at least one evaluation case is required")
    case_ids = [case.id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise ValueError("evaluation case ids must be unique")


def _check_expectations(
    case: EvalCase,
    result: AgentRunResult,
    observation: RunObservation,
) -> tuple[EvalFailure, ...]:
    failures: list[EvalFailure] = []
    if result.status != case.expected_status:
        failures.append(
            EvalFailure("status", case.expected_status, result.status)
        )

    answer = result.final_answer or ""
    for expected in case.answer_contains:
        if expected not in answer:
            failures.append(EvalFailure("answer_contains", expected, answer))

    event_types = tuple(event.type for event in result.events)
    for expected in case.required_event_types:
        if expected not in event_types:
            failures.append(
                EvalFailure("required_event_type", expected, repr(event_types))
            )

    tool_names = tuple(
        str(event.data["name"])
        for event in result.events
        if event.type == "tool.started" and "name" in event.data
    )
    for expected in case.required_tool_names:
        if expected not in tool_names:
            failures.append(
                EvalFailure("required_tool_name", expected, repr(tool_names))
            )

    successful_tool_names = tuple(
        str(event.data["name"])
        for event in result.events
        if event.type == "tool.completed" and "name" in event.data
    )
    for expected in case.required_successful_tool_names:
        if expected not in successful_tool_names:
            failures.append(
                EvalFailure(
                    "required_successful_tool_name",
                    expected,
                    repr(successful_tool_names),
                )
            )

    error_categories = tuple(error.category for error in observation.errors)
    for expected in case.required_error_categories:
        if expected not in error_categories:
            failures.append(
                EvalFailure(
                    "required_error_category",
                    expected,
                    repr(error_categories),
                )
            )

    error_text = "\n".join(error.message for error in observation.errors)
    for expected in case.error_contains:
        if expected not in error_text:
            failures.append(EvalFailure("error_contains", expected, error_text))

    if (
        case.max_duration_ms is not None
        and observation.duration_ms > case.max_duration_ms
    ):
        failures.append(
            EvalFailure(
                "max_duration_ms",
                f"<= {case.max_duration_ms:g}",
                f"{observation.duration_ms:g}",
            )
        )
    usage_available = observation.usage is not None
    if (
        case.expected_usage_available is not None
        and usage_available is not case.expected_usage_available
    ):
        failures.append(
            EvalFailure(
                "usage_available",
                str(case.expected_usage_available),
                str(usage_available),
            )
        )
    if case.max_estimated_cost_usd is not None:
        actual_cost = (
            observation.usage.estimated_cost_usd
            if observation.usage is not None
            else None
        )
        if actual_cost is None or actual_cost > case.max_estimated_cost_usd:
            failures.append(
                EvalFailure(
                    "max_estimated_cost_usd",
                    f"<= {case.max_estimated_cost_usd:g}",
                    "unavailable" if actual_cost is None else f"{actual_cost:g}",
                )
            )
    return tuple(failures)
