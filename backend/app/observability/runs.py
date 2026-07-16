from __future__ import annotations

import json
import logging
from collections import Counter
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from time import perf_counter
from uuid import uuid4

from backend.app.domain import AgentEvent, AgentRunResult, ModelUsage


Clock = Callable[[], float]
RunIdFactory = Callable[[], str]


@dataclass(frozen=True)
class RunError:
    category: str
    message: str
    event_type: str | None = None
    step: int | None = None

    def to_record(self) -> dict[str, object]:
        return {
            "category": self.category,
            "message": self.message,
            "event_type": self.event_type,
            "step": self.step,
        }


@dataclass(frozen=True)
class RunObservation:
    run_id: str
    status: str
    duration_ms: float
    event_count: int
    event_counts: Mapping[str, int]
    model_duration_ms: float
    tool_duration_ms: float
    tool_durations_ms: Mapping[str, float]
    usage: ModelUsage | None
    errors: tuple[RunError, ...]

    @property
    def error_count(self) -> int:
        return len(self.errors)

    def to_record(self) -> dict[str, object]:
        """Return a JSON-serializable record without prompts or message content."""
        return {
            "run_id": self.run_id,
            "status": self.status,
            "duration_ms": self.duration_ms,
            "event_count": self.event_count,
            "event_counts": dict(self.event_counts),
            "model_duration_ms": self.model_duration_ms,
            "tool_duration_ms": self.tool_duration_ms,
            "tool_durations_ms": dict(self.tool_durations_ms),
            "usage": _usage_record(self.usage),
            "error_count": self.error_count,
            "errors": [error.to_record() for error in self.errors],
        }


@dataclass(frozen=True)
class ObservedRun:
    result: AgentRunResult
    observation: RunObservation


class RunSpan:
    """Measure one run with an injected monotonic clock."""

    def __init__(self, run_id: str, clock: Clock) -> None:
        self.run_id = run_id
        self._clock = clock
        self._started_at = clock()
        self._finished = False

    def finish(self, result: AgentRunResult) -> RunObservation:
        duration_ms = self._finish_duration()
        event_counts = Counter(event.type for event in result.events)
        tool_durations = _collect_tool_durations(result.events)
        errors = _collect_errors(result)
        return RunObservation(
            run_id=self.run_id,
            status=result.status,
            duration_ms=duration_ms,
            event_count=len(result.events),
            event_counts=dict(sorted(event_counts.items())),
            model_duration_ms=_sum_event_metric(
                result.events,
                "model_duration_ms",
            ),
            tool_duration_ms=round(sum(tool_durations.values()), 3),
            tool_durations_ms=tool_durations,
            usage=result.usage,
            errors=errors,
        )

    def finish_error(self, error: Exception) -> RunObservation:
        duration_ms = self._finish_duration()
        return RunObservation(
            run_id=self.run_id,
            status="failed",
            duration_ms=duration_ms,
            event_count=0,
            event_counts={},
            model_duration_ms=0.0,
            tool_duration_ms=0.0,
            tool_durations_ms={},
            usage=None,
            errors=(
                RunError(
                    category=f"exception.{type(error).__name__}",
                    message=str(error),
                ),
            ),
        )

    def _finish_duration(self) -> float:
        if self._finished:
            raise RuntimeError("run span has already finished")
        self._finished = True
        elapsed = max(0.0, self._clock() - self._started_at)
        return round(elapsed * 1000, 3)


ObservationSink = Callable[[RunObservation], None]


class JsonLogSink:
    """Write a privacy-safe summary through the standard logging API.

    Raw error messages stay available on ``RunObservation`` for deterministic
    evaluation, but they are deliberately excluded from the default log sink.
    """

    def __init__(self, logger: logging.Logger | None = None) -> None:
        self._logger = logger or logging.getLogger("ai_agent.runs")

    def __call__(self, observation: RunObservation) -> None:
        record = {
            "event": "agent.run.observed",
            "run_id": observation.run_id,
            "status": observation.status,
            "duration_ms": observation.duration_ms,
            "event_count": observation.event_count,
            "event_counts": dict(observation.event_counts),
            "model_duration_ms": observation.model_duration_ms,
            "tool_duration_ms": observation.tool_duration_ms,
            "tool_durations_ms": dict(observation.tool_durations_ms),
            "usage": _usage_record(observation.usage),
            "error_count": observation.error_count,
            "error_categories": [error.category for error in observation.errors],
        }
        self._logger.info(json.dumps(record, ensure_ascii=False, sort_keys=True))


class RunObserver:
    """Create structured summaries while leaving execution behavior unchanged."""

    def __init__(
        self,
        *,
        clock: Clock = perf_counter,
        run_id_factory: RunIdFactory | None = None,
        sink: ObservationSink | None = None,
    ) -> None:
        self._clock = clock
        self._run_id_factory = run_id_factory or _create_run_id
        self._sink = sink

    def start(self, run_id: str | None = None) -> RunSpan:
        resolved_run_id = run_id if run_id is not None else self._run_id_factory()
        if not resolved_run_id.strip():
            raise ValueError("run_id must not be empty")
        return RunSpan(resolved_run_id, self._clock)

    def complete(self, span: RunSpan, result: AgentRunResult) -> RunObservation:
        observation = span.finish(result)
        self._publish(observation)
        return observation

    def fail(self, span: RunSpan, error: Exception) -> RunObservation:
        observation = span.finish_error(error)
        self._publish(observation)
        return observation

    def observe(
        self,
        execute: Callable[[], AgentRunResult],
        *,
        run_id: str | None = None,
    ) -> ObservedRun:
        span = self.start(run_id)
        try:
            result = execute()
        except Exception as error:
            self.fail(span, error)
            raise
        observation = self.complete(span, result)
        return ObservedRun(result=result, observation=observation)

    def _publish(self, observation: RunObservation) -> None:
        if self._sink is not None:
            try:
                self._sink(observation)
            except Exception as error:
                logging.getLogger("ai_agent.observability").warning(
                    "Observation sink failed with %s",
                    type(error).__name__,
                )


def _collect_errors(result: AgentRunResult) -> tuple[RunError, ...]:
    errors = [
        error
        for event in result.events
        if (error := _event_error(event)) is not None
    ]
    if result.error is not None and all(
        error.message != result.error for error in errors
    ):
        errors.append(
            RunError(
                category="run.failed",
                message=result.error,
                event_type="run.failed",
            )
        )
    return tuple(errors)


def _event_error(event: AgentEvent) -> RunError | None:
    if not event.type.endswith(".failed"):
        return None
    category = event.data.get("error_code") or event.type
    message = (
        event.data.get("error_message")
        or event.data.get("error")
        or event.type
    )
    return RunError(
        category=str(category),
        message=str(message),
        event_type=event.type,
        step=event.step,
    )


def _create_run_id() -> str:
    return str(uuid4())


def _sum_event_metric(events: tuple[AgentEvent, ...], field_name: str) -> float:
    values = [
        float(event.data[field_name])
        for event in events
        if isinstance(event.data.get(field_name), (int, float))
    ]
    return round(sum(values), 3)


def _collect_tool_durations(
    events: tuple[AgentEvent, ...],
) -> dict[str, float]:
    durations: Counter[str] = Counter()
    for event in events:
        if event.type not in {"tool.completed", "tool.failed"}:
            continue
        name = event.data.get("name")
        duration = event.data.get("duration_ms")
        if isinstance(name, str) and isinstance(duration, (int, float)):
            durations[name] += float(duration)
    return {
        name: round(duration, 3)
        for name, duration in sorted(durations.items())
    }


def _usage_record(usage: ModelUsage | None) -> dict[str, object] | None:
    if usage is None:
        return None
    return {
        "input_tokens": usage.input_tokens,
        "output_tokens": usage.output_tokens,
        "total_tokens": usage.total_tokens,
        "estimated_cost_usd": usage.estimated_cost_usd,
    }
