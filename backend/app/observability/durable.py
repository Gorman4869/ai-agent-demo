from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Protocol

from backend.app.domain.run import StoredRunEvent
from backend.app.stores import EventStore


_TERMINAL_EVENT_TYPES = frozenset(
    {"run.completed", "run.failed", "run.cancelled"}
)


class TraceLayer(StrEnum):
    RUN = "run"
    NODE = "node"
    MODEL = "model"
    TOOL = "tool"


class TraceStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    RETRYING = "retrying"


@dataclass(frozen=True)
class TraceSpan:
    """One content-free span reconstructed from durable Run events."""

    id: str
    run_id: str
    parent_id: str | None
    layer: TraceLayer | str
    name: str
    status: TraceStatus | str
    step: int
    started_at: datetime
    finished_at: datetime
    duration_ms: float | None
    error_code: str | None = None
    error_category: str | None = None
    attempt: int | None = None

    def __post_init__(self) -> None:
        _require_label(self.id, "span id")
        _require_label(self.run_id, "span run id")
        if self.parent_id is not None:
            _require_label(self.parent_id, "span parent id")
        try:
            layer = TraceLayer(self.layer)
        except (TypeError, ValueError):
            raise ValueError("span layer is not supported") from None
        try:
            status = TraceStatus(self.status)
        except (TypeError, ValueError):
            raise ValueError("span status is not supported") from None
        _require_label(self.name, "span name")
        _require_nonnegative_int(self.step, "span step")
        _require_timestamp(self.started_at, "span started_at")
        _require_timestamp(self.finished_at, "span finished_at")
        if self.finished_at < self.started_at:
            raise ValueError("span finish must not precede its start")
        if self.duration_ms is not None:
            _require_nonnegative_number(self.duration_ms, "span duration_ms")
        if self.error_code is not None:
            _require_label(self.error_code, "span error_code")
        if self.error_category is not None:
            _require_label(self.error_category, "span error_category")
        if self.attempt is not None:
            _require_positive_int(self.attempt, "span attempt")
        object.__setattr__(self, "layer", layer)
        object.__setattr__(self, "status", status)

    def to_record(self) -> dict[str, object]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "parent_id": self.parent_id,
            "layer": self.layer.value,
            "name": self.name,
            "status": self.status.value,
            "step": self.step,
            "started_at": self.started_at.isoformat(),
            "finished_at": self.finished_at.isoformat(),
            "duration_ms": self.duration_ms,
            "error_code": self.error_code,
            "error_category": self.error_category,
            "attempt": self.attempt,
        }


@dataclass(frozen=True)
class MetricPoint:
    """One bounded metric point with no prompt, answer, or tool content."""

    id: str
    run_id: str
    name: str
    value: float
    unit: str
    layer: TraceLayer | str
    status: TraceStatus | str
    step: int
    observed_at: datetime

    def __post_init__(self) -> None:
        _require_label(self.id, "metric id")
        _require_label(self.run_id, "metric run id")
        _require_label(self.name, "metric name")
        _require_nonnegative_number(self.value, "metric value")
        _require_label(self.unit, "metric unit")
        try:
            layer = TraceLayer(self.layer)
        except (TypeError, ValueError):
            raise ValueError("metric layer is not supported") from None
        try:
            status = TraceStatus(self.status)
        except (TypeError, ValueError):
            raise ValueError("metric status is not supported") from None
        _require_nonnegative_int(self.step, "metric step")
        _require_timestamp(self.observed_at, "metric observed_at")
        object.__setattr__(self, "layer", layer)
        object.__setattr__(self, "status", status)

    def to_record(self) -> dict[str, object]:
        return {
            "id": self.id,
            "run_id": self.run_id,
            "name": self.name,
            "value": self.value,
            "unit": self.unit,
            "layer": self.layer.value,
            "status": self.status.value,
            "step": self.step,
            "observed_at": self.observed_at.isoformat(),
        }


@dataclass(frozen=True)
class RunUsageLedgerEntry:
    """One validated Run-scoped usage snapshot from a persisted event."""

    event_id: str
    run_id: str
    sequence: int
    provider: str | None
    model: str | None
    requests: int | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: Decimal | None
    cost_source: str
    created_at: datetime

    def __post_init__(self) -> None:
        _require_label(self.event_id, "usage event id")
        _require_label(self.run_id, "usage run id")
        _require_positive_int(self.sequence, "usage sequence")
        if self.provider is not None:
            _require_label(self.provider, "usage provider")
        if self.model is not None:
            _require_label(self.model, "usage model")
        if self.requests is not None:
            _require_positive_int(self.requests, "usage requests")
        for value, label in (
            (self.input_tokens, "usage input_tokens"),
            (self.output_tokens, "usage output_tokens"),
            (self.total_tokens, "usage total_tokens"),
        ):
            _require_nonnegative_int(value, label)
        if (
            self.total_tokens == 0
            or self.total_tokens != self.input_tokens + self.output_tokens
        ):
            raise ValueError("usage total_tokens is inconsistent")
        _require_label(self.cost_source, "usage cost_source")
        if self.estimated_cost_usd is None:
            if self.cost_source != "unknown":
                raise ValueError("unknown usage cost requires unknown source")
        elif (
            not isinstance(self.estimated_cost_usd, Decimal)
            or not self.estimated_cost_usd.is_finite()
            or self.estimated_cost_usd < 0
            or self.cost_source == "unknown"
        ):
            raise ValueError("known usage cost has an invalid format")
        _require_timestamp(self.created_at, "usage created_at")

    def to_record(self) -> dict[str, object]:
        return {
            "event_id": self.event_id,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "provider": self.provider,
            "model": self.model,
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": (
                str(self.estimated_cost_usd)
                if self.estimated_cost_usd is not None
                else None
            ),
            "cost_source": self.cost_source,
            "created_at": self.created_at.isoformat(),
        }


@dataclass(frozen=True)
class RunCostSummary:
    """Latest cumulative Run usage; cumulative snapshots are never summed."""

    entry_count: int
    latest_sequence: int
    requests: int | None
    input_tokens: int
    output_tokens: int
    total_tokens: int
    estimated_cost_usd: Decimal | None
    cost_source: str

    def __post_init__(self) -> None:
        _require_positive_int(self.entry_count, "cost entry_count")
        _require_positive_int(self.latest_sequence, "cost latest_sequence")
        if self.requests is not None:
            _require_positive_int(self.requests, "cost requests")
        for value, label in (
            (self.input_tokens, "cost input_tokens"),
            (self.output_tokens, "cost output_tokens"),
            (self.total_tokens, "cost total_tokens"),
        ):
            _require_nonnegative_int(value, label)
        if (
            self.total_tokens == 0
            or self.total_tokens != self.input_tokens + self.output_tokens
        ):
            raise ValueError("cost total_tokens is inconsistent")
        _require_label(self.cost_source, "cost source")
        if self.estimated_cost_usd is None:
            if self.cost_source != "unknown":
                raise ValueError("unknown cost requires unknown source")
        elif (
            not isinstance(self.estimated_cost_usd, Decimal)
            or not self.estimated_cost_usd.is_finite()
            or self.estimated_cost_usd < 0
            or self.cost_source == "unknown"
        ):
            raise ValueError("known cost has an invalid format")

    def to_record(self) -> dict[str, object]:
        return {
            "entry_count": self.entry_count,
            "latest_sequence": self.latest_sequence,
            "requests": self.requests,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "estimated_cost_usd": (
                str(self.estimated_cost_usd)
                if self.estimated_cost_usd is not None
                else None
            ),
            "cost_source": self.cost_source,
        }


@dataclass(frozen=True)
class RunObservabilitySnapshot:
    run_id: str
    spans: tuple[TraceSpan, ...]
    metrics: tuple[MetricPoint, ...]
    usage_ledger: tuple[RunUsageLedgerEntry, ...]
    cost_summary: RunCostSummary | None

    def to_record(self) -> dict[str, object]:
        return {
            "run_id": self.run_id,
            "spans": [span.to_record() for span in self.spans],
            "metrics": [metric.to_record() for metric in self.metrics],
            "usage_ledger": [entry.to_record() for entry in self.usage_ledger],
            "cost_summary": (
                self.cost_summary.to_record()
                if self.cost_summary is not None
                else None
            ),
        }


class TraceSink(Protocol):
    async def record(self, span: TraceSpan) -> None: ...


class MetricsSink(Protocol):
    async def record(self, metric: MetricPoint) -> None: ...


class NullTraceSink:
    async def record(self, span: TraceSpan) -> None:
        del span


class NullMetricsSink:
    async def record(self, metric: MetricPoint) -> None:
        del metric


class InMemoryTraceSink:
    """Deterministic sink for local inspection and adapter contract tests."""

    def __init__(self) -> None:
        self._spans: list[TraceSpan] = []

    async def record(self, span: TraceSpan) -> None:
        self._spans.append(span)

    def spans(self, *, run_id: str | None = None) -> tuple[TraceSpan, ...]:
        return tuple(
            span
            for span in self._spans
            if run_id is None or span.run_id == run_id
        )


class InMemoryMetricsSink:
    """Deterministic sink for local inspection and adapter contract tests."""

    def __init__(self) -> None:
        self._metrics: list[MetricPoint] = []

    async def record(self, metric: MetricPoint) -> None:
        self._metrics.append(metric)

    def metrics(self, *, run_id: str | None = None) -> tuple[MetricPoint, ...]:
        return tuple(
            metric
            for metric in self._metrics
            if run_id is None or metric.run_id == run_id
        )


class EventRunObservability:
    """Rebuild Trace, Metrics, and the usage ledger from durable Run events."""

    def __init__(self, event_store: EventStore) -> None:
        self._event_store = event_store

    async def snapshot(
        self,
        run_id: str,
        *,
        owner_id: str,
    ) -> RunObservabilitySnapshot:
        events = await self._events_for_run(run_id, owner_id=owner_id)
        return self.project(run_id, events)

    def project(
        self,
        run_id: str,
        events: tuple[StoredRunEvent, ...],
    ) -> RunObservabilitySnapshot:
        _require_label(run_id, "observability run id")
        if any(event.run_id != run_id for event in events):
            raise ValueError("observability events must belong to one run")
        ordered = tuple(sorted(events, key=lambda event: event.sequence))
        usage_ledger = tuple(
            entry
            for event in ordered
            if (entry := _usage_entry(event)) is not None
        )
        cost_summary = _cost_summary(usage_ledger)
        spans = _trace_spans(run_id, ordered)
        metrics = _metric_points(run_id, spans, cost_summary)
        return RunObservabilitySnapshot(
            run_id=run_id,
            spans=spans,
            metrics=metrics,
            usage_ledger=usage_ledger,
            cost_summary=cost_summary,
        )

    async def _events_for_run(
        self,
        run_id: str,
        *,
        owner_id: str,
    ) -> tuple[StoredRunEvent, ...]:
        cursor = 0
        events: list[StoredRunEvent] = []
        while True:
            batch = await self._event_store.list_for_run(
                run_id,
                owner_id=owner_id,
                after_sequence=cursor,
                limit=500,
            )
            if not batch:
                return tuple(events)
            events.extend(batch)
            cursor = batch[-1].sequence
            if len(batch) < 500:
                return tuple(events)


class TelemetryExportError(RuntimeError):
    code = "telemetry_export_failed"

    def __init__(self) -> None:
        super().__init__(self.code)


class RunTelemetryExporter:
    """Export a terminal event projection without exposing event content."""

    def __init__(
        self,
        observability: EventRunObservability,
        *,
        trace_sink: TraceSink | None = None,
        metrics_sink: MetricsSink | None = None,
    ) -> None:
        self._observability = observability
        self._trace_sink = trace_sink or NullTraceSink()
        self._metrics_sink = metrics_sink or NullMetricsSink()

    async def observe(
        self,
        event: StoredRunEvent,
        *,
        owner_id: str,
    ) -> None:
        if event.type not in _TERMINAL_EVENT_TYPES:
            return
        snapshot = await self._observability.snapshot(
            event.run_id,
            owner_id=owner_id,
        )
        try:
            for span in snapshot.spans:
                await self._trace_sink.record(span)
            for metric in snapshot.metrics:
                await self._metrics_sink.record(metric)
        except Exception:
            raise TelemetryExportError() from None


def _trace_spans(
    run_id: str,
    events: tuple[StoredRunEvent, ...],
) -> tuple[TraceSpan, ...]:
    if not events:
        return ()
    started = next((event for event in events if event.type == "run.started"), None)
    terminal = next(
        (event for event in reversed(events) if event.type in _TERMINAL_EVENT_TYPES),
        None,
    )
    spans: list[TraceSpan] = []
    run_span: TraceSpan | None = None
    if started is not None and terminal is not None:
        run_span = _span(
            run_id=run_id,
            parent_id=None,
            layer=TraceLayer.RUN,
            name="agent.run",
            status=_terminal_status(terminal),
            step=terminal.step,
            start_event=started,
            finish_event=terminal,
            error_code=_safe_optional_label(terminal.data.get("failure_code")),
            error_category=_safe_optional_label(
                terminal.data.get("failure_category")
            ),
        )
        spans.append(run_span)
        runtime_name = _safe_optional_label(started.data.get("runtime")) or "runtime"
        spans.append(
            _span(
                run_id=run_id,
                parent_id=run_span.id,
                layer=TraceLayer.NODE,
                name=f"runtime.{runtime_name}",
                status=run_span.status,
                step=terminal.step,
                start_event=started,
                finish_event=terminal,
                error_code=run_span.error_code,
                error_category=run_span.error_category,
            )
        )

    parent_id = run_span.id if run_span is not None else None
    spans.extend(_tool_spans(run_id, events, terminal, parent_id=parent_id))
    spans.extend(_plan_spans(run_id, events, terminal, parent_id=parent_id))
    spans.extend(_context_spans(run_id, events, parent_id=parent_id))
    model_spans = _model_spans(run_id, events, terminal, parent_id=parent_id)
    spans.extend(model_spans)
    return tuple(
        sorted(
            spans,
            key=lambda span: (
                span.started_at,
                _layer_order(span.layer),
                span.step,
                span.id,
            ),
        )
    )


def _tool_spans(
    run_id: str,
    events: tuple[StoredRunEvent, ...],
    terminal: StoredRunEvent | None,
    *,
    parent_id: str | None,
) -> list[TraceSpan]:
    spans: list[TraceSpan] = []
    open_tools: dict[str, StoredRunEvent] = {}
    for event in events:
        if event.type == "tool.started":
            call_id = _safe_optional_label(event.data.get("id"))
            if call_id is not None:
                open_tools[call_id] = event
            continue
        if event.type not in {"tool.completed", "tool.failed"}:
            continue
        call_id = _safe_optional_label(event.data.get("id"))
        start_event = open_tools.pop(call_id, None) if call_id is not None else None
        start_event = start_event or event
        name = (
            _safe_optional_label(start_event.data.get("name"))
            or _safe_optional_label(event.data.get("name"))
            or "tool"
        )
        spans.append(
            _span(
                run_id=run_id,
                parent_id=parent_id,
                layer=TraceLayer.TOOL,
                name=f"tool.{name}",
                status=(
                    TraceStatus.COMPLETED
                    if event.type == "tool.completed"
                    else TraceStatus.FAILED
                ),
                step=event.step,
                start_event=start_event,
                finish_event=event,
                explicit_duration=_safe_duration(event.data.get("duration_ms")),
                error_code=(
                    _safe_optional_label(event.data.get("error_code"))
                    if event.type == "tool.failed"
                    else None
                ),
                error_category=(
                    "tool" if event.type == "tool.failed" else None
                ),
            )
        )
    if terminal is not None:
        for start_event in open_tools.values():
            name = _safe_optional_label(start_event.data.get("name")) or "tool"
            spans.append(
                _span(
                    run_id=run_id,
                    parent_id=parent_id,
                    layer=TraceLayer.TOOL,
                    name=f"tool.{name}",
                    status=(
                        TraceStatus.CANCELLED
                        if terminal.type == "run.cancelled"
                        else TraceStatus.FAILED
                    ),
                    step=start_event.step,
                    start_event=start_event,
                    finish_event=terminal,
                    error_code="tool_span_incomplete",
                    error_category="tool",
                )
            )
    return spans


def _plan_spans(
    run_id: str,
    events: tuple[StoredRunEvent, ...],
    terminal: StoredRunEvent | None,
    *,
    parent_id: str | None,
) -> list[TraceSpan]:
    spans: list[TraceSpan] = []
    open_steps: dict[tuple[int, int], StoredRunEvent] = {}
    for event in events:
        key = _plan_key(event)
        if event.type == "plan.step.started" and key is not None:
            open_steps[key] = event
            continue
        if event.type not in {"plan.step.completed", "plan.step.failed"}:
            continue
        start_event = open_steps.pop(key, None) if key is not None else None
        start_event = start_event or event
        spans.append(
            _span(
                run_id=run_id,
                parent_id=parent_id,
                layer=TraceLayer.NODE,
                name="plan.step",
                status=(
                    TraceStatus.COMPLETED
                    if event.type == "plan.step.completed"
                    else TraceStatus.FAILED
                ),
                step=event.step,
                start_event=start_event,
                finish_event=event,
                error_code=(
                    _safe_optional_label(event.data.get("error_code"))
                    if event.type == "plan.step.failed"
                    else None
                ),
                error_category=(
                    _safe_optional_label(event.data.get("category"))
                    if event.type == "plan.step.failed"
                    else None
                ),
                attempt=_safe_positive_int(event.data.get("attempt")),
            )
        )
    if terminal is not None:
        for start_event in open_steps.values():
            spans.append(
                _span(
                    run_id=run_id,
                    parent_id=parent_id,
                    layer=TraceLayer.NODE,
                    name="plan.step",
                    status=(
                        TraceStatus.CANCELLED
                        if terminal.type == "run.cancelled"
                        else TraceStatus.FAILED
                    ),
                    step=start_event.step,
                    start_event=start_event,
                    finish_event=terminal,
                    error_code="node_span_incomplete",
                    error_category="workflow",
                    attempt=_safe_positive_int(start_event.data.get("attempt")),
                )
            )
    return spans


def _context_spans(
    run_id: str,
    events: tuple[StoredRunEvent, ...],
    *,
    parent_id: str | None,
) -> list[TraceSpan]:
    spans: list[TraceSpan] = []
    for event in events:
        if event.type not in {"rag.citations", "context.failed"}:
            continue
        failed = event.type == "context.failed"
        spans.append(
            _span(
                run_id=run_id,
                parent_id=parent_id,
                layer=TraceLayer.NODE,
                name="context.rag" if not failed else "context.prepare",
                status=TraceStatus.FAILED if failed else TraceStatus.COMPLETED,
                step=event.step,
                start_event=event,
                finish_event=event,
                explicit_duration=None,
                error_code=(
                    _safe_optional_label(event.data.get("code"))
                    if failed
                    else None
                ),
                error_category="context" if failed else None,
            )
        )
    return spans


def _model_spans(
    run_id: str,
    events: tuple[StoredRunEvent, ...],
    terminal: StoredRunEvent | None,
    *,
    parent_id: str | None,
) -> list[TraceSpan]:
    spans: list[TraceSpan] = []
    for event in events:
        if event.type == "model.retrying":
            spans.append(
                _span(
                    run_id=run_id,
                    parent_id=parent_id,
                    layer=TraceLayer.MODEL,
                    name="model.request",
                    status=TraceStatus.RETRYING,
                    step=event.step,
                    start_event=event,
                    finish_event=event,
                    explicit_duration=_safe_duration(
                        event.data.get("model_duration_ms")
                    ),
                    error_code="model_retry",
                    error_category="model",
                    attempt=_safe_positive_int(event.data.get("attempt")),
                )
            )
        elif event.type == "tool.started":
            duration = _safe_duration(event.data.get("model_duration_ms"))
            if duration is not None:
                spans.append(
                    _span(
                        run_id=run_id,
                        parent_id=parent_id,
                        layer=TraceLayer.MODEL,
                        name="model.request",
                        status=TraceStatus.COMPLETED,
                        step=event.step,
                        start_event=event,
                        finish_event=event,
                        explicit_duration=duration,
                    )
                )
        elif event.type == "model.usage" and _usage_entry(event) is not None:
            spans.append(
                _span(
                    run_id=run_id,
                    parent_id=parent_id,
                    layer=TraceLayer.MODEL,
                    name="model.run",
                    status=TraceStatus.COMPLETED,
                    step=event.step,
                    start_event=event,
                    finish_event=event,
                    explicit_duration=None,
                )
            )
    if terminal is not None:
        failure_category = _safe_optional_label(
            terminal.data.get("failure_category")
        )
        if failure_category == "model":
            spans.append(
                _span(
                    run_id=run_id,
                    parent_id=parent_id,
                    layer=TraceLayer.MODEL,
                    name="model.run",
                    status=TraceStatus.FAILED,
                    step=terminal.step,
                    start_event=terminal,
                    finish_event=terminal,
                    error_code=_safe_optional_label(
                        terminal.data.get("failure_code")
                    ),
                    error_category="model",
                )
            )
        elif terminal.type == "run.completed" and not spans:
            spans.append(
                _span(
                    run_id=run_id,
                    parent_id=parent_id,
                    layer=TraceLayer.MODEL,
                    name="model.run",
                    status=TraceStatus.COMPLETED,
                    step=terminal.step,
                    start_event=terminal,
                    finish_event=terminal,
                )
            )
    return spans


def _metric_points(
    run_id: str,
    spans: tuple[TraceSpan, ...],
    cost_summary: RunCostSummary | None,
) -> tuple[MetricPoint, ...]:
    metrics: list[MetricPoint] = []
    for span in spans:
        if span.duration_ms is not None:
            metrics.append(
                _metric(
                    run_id=run_id,
                    name="agent.span.duration",
                    value=span.duration_ms,
                    unit="ms",
                    layer=span.layer,
                    status=span.status,
                    step=span.step,
                    observed_at=span.finished_at,
                    discriminator=span.id,
                )
            )
        if span.status is TraceStatus.RETRYING:
            metrics.append(
                _metric(
                    run_id=run_id,
                    name="agent.model.retry",
                    value=1.0,
                    unit="count",
                    layer=span.layer,
                    status=span.status,
                    step=span.step,
                    observed_at=span.finished_at,
                    discriminator=span.id,
                )
            )
        if span.layer is TraceLayer.RUN:
            metrics.append(
                _metric(
                    run_id=run_id,
                    name="agent.run.total",
                    value=1.0,
                    unit="count",
                    layer=span.layer,
                    status=span.status,
                    step=span.step,
                    observed_at=span.finished_at,
                    discriminator=span.id,
                )
            )
    if cost_summary is not None and spans:
        observed_at = max(span.finished_at for span in spans)
        for name, value in (
            ("agent.model.input_tokens", cost_summary.input_tokens),
            ("agent.model.output_tokens", cost_summary.output_tokens),
            ("agent.model.total_tokens", cost_summary.total_tokens),
        ):
            metrics.append(
                _metric(
                    run_id=run_id,
                    name=name,
                    value=float(value),
                    unit="token",
                    layer=TraceLayer.MODEL,
                    status=TraceStatus.COMPLETED,
                    step=0,
                    observed_at=observed_at,
                    discriminator=str(cost_summary.latest_sequence),
                )
            )
    return tuple(sorted(metrics, key=lambda metric: (metric.observed_at, metric.id)))


def _usage_entry(event: StoredRunEvent) -> RunUsageLedgerEntry | None:
    if event.type != "model.usage" or event.data.get("scope") != "run":
        return None
    input_tokens = _safe_nonnegative_int(event.data.get("input_tokens"))
    output_tokens = _safe_nonnegative_int(event.data.get("output_tokens"))
    total_tokens = _safe_nonnegative_int(event.data.get("total_tokens"))
    if (
        input_tokens is None
        or output_tokens is None
        or total_tokens is None
        or total_tokens == 0
        or total_tokens != input_tokens + output_tokens
    ):
        return None
    requests_value = event.data.get("requests")
    requests = (
        None if requests_value is None else _safe_positive_int(requests_value)
    )
    if requests_value is not None and requests is None:
        return None
    provider = _safe_optional_label(event.data.get("provider"))
    model = _safe_optional_label(event.data.get("model"))
    if event.data.get("provider") is not None and provider is None:
        return None
    if event.data.get("model") is not None and model is None:
        return None

    raw_cost = event.data.get("estimated_cost_usd")
    cost: Decimal | None
    if raw_cost is None:
        cost = None
    elif (
        isinstance(raw_cost, (int, float))
        and not isinstance(raw_cost, bool)
        and math.isfinite(float(raw_cost))
        and raw_cost >= 0
    ):
        cost = Decimal(str(raw_cost))
    else:
        return None
    raw_source = event.data.get("cost_source")
    if cost is None:
        if raw_source not in {None, "unknown"}:
            return None
        cost_source = "unknown"
    else:
        if raw_source is None:
            cost_source = "event_reported_unversioned"
        else:
            cost_source = _safe_optional_label(raw_source) or ""
            if not cost_source or cost_source == "unknown":
                return None
    return RunUsageLedgerEntry(
        event_id=event.id,
        run_id=event.run_id,
        sequence=event.sequence,
        provider=provider,
        model=model,
        requests=requests,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        estimated_cost_usd=cost,
        cost_source=cost_source,
        created_at=event.created_at,
    )


def _cost_summary(
    entries: tuple[RunUsageLedgerEntry, ...],
) -> RunCostSummary | None:
    if not entries:
        return None
    latest = entries[-1]
    return RunCostSummary(
        entry_count=len(entries),
        latest_sequence=latest.sequence,
        requests=latest.requests,
        input_tokens=latest.input_tokens,
        output_tokens=latest.output_tokens,
        total_tokens=latest.total_tokens,
        estimated_cost_usd=latest.estimated_cost_usd,
        cost_source=latest.cost_source,
    )


def _span(
    *,
    run_id: str,
    parent_id: str | None,
    layer: TraceLayer,
    name: str,
    status: TraceStatus,
    step: int,
    start_event: StoredRunEvent,
    finish_event: StoredRunEvent,
    explicit_duration: float | None = None,
    error_code: str | None = None,
    error_category: str | None = None,
    attempt: int | None = None,
) -> TraceSpan:
    duration = (
        explicit_duration
        if explicit_duration is not None
        else _elapsed_ms(start_event.created_at, finish_event.created_at)
    )
    if start_event.id == finish_event.id and explicit_duration is None:
        duration = None
    return TraceSpan(
        id=_stable_id(
            "span",
            run_id,
            layer.value,
            name,
            start_event.id,
            finish_event.id,
        ),
        run_id=run_id,
        parent_id=parent_id,
        layer=layer,
        name=name,
        status=status,
        step=step,
        started_at=start_event.created_at,
        finished_at=finish_event.created_at,
        duration_ms=duration,
        error_code=error_code,
        error_category=error_category,
        attempt=attempt,
    )


def _metric(
    *,
    run_id: str,
    name: str,
    value: float,
    unit: str,
    layer: TraceLayer,
    status: TraceStatus,
    step: int,
    observed_at: datetime,
    discriminator: str,
) -> MetricPoint:
    return MetricPoint(
        id=_stable_id(
            "metric",
            run_id,
            name,
            layer.value,
            status.value,
            str(step),
            discriminator,
        ),
        run_id=run_id,
        name=name,
        value=value,
        unit=unit,
        layer=layer,
        status=status,
        step=step,
        observed_at=observed_at,
    )


def _terminal_status(event: StoredRunEvent) -> TraceStatus:
    if event.type == "run.completed":
        return TraceStatus.COMPLETED
    if event.type == "run.cancelled":
        return TraceStatus.CANCELLED
    return TraceStatus.FAILED


def _plan_key(event: StoredRunEvent) -> tuple[int, int] | None:
    revision = _safe_positive_int(event.data.get("revision"))
    attempt = _safe_positive_int(event.data.get("attempt"))
    if revision is None or attempt is None:
        return None
    return revision, attempt


def _elapsed_ms(started_at: datetime, finished_at: datetime) -> float:
    return round(max(0.0, (finished_at - started_at).total_seconds() * 1_000), 3)


def _safe_duration(value: object) -> float | None:
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or value < 0
    ):
        return None
    return round(float(value), 3)


def _safe_optional_label(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
        or any(not character.isprintable() for character in value)
    ):
        return None
    return value


def _safe_nonnegative_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None
    return value


def _safe_positive_int(value: object) -> int | None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        return None
    return value


def _stable_id(prefix: str, *parts: str) -> str:
    digest = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        digest.update(len(encoded).to_bytes(4, byteorder="big"))
        digest.update(encoded)
    return f"{prefix}-{digest.hexdigest()}"


def _layer_order(layer: TraceLayer) -> int:
    return {
        TraceLayer.RUN: 0,
        TraceLayer.NODE: 1,
        TraceLayer.MODEL: 2,
        TraceLayer.TOOL: 3,
    }[layer]


def _require_label(value: object, label: str) -> None:
    if _safe_optional_label(value) is None:
        raise ValueError(f"{label} has an invalid format")


def _require_timestamp(value: object, label: str) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{label} must be timezone-aware")


def _require_nonnegative_int(value: object, label: str) -> None:
    if _safe_nonnegative_int(value) is None:
        raise ValueError(f"{label} must be a non-negative integer")


def _require_positive_int(value: object, label: str) -> None:
    if _safe_positive_int(value) is None:
        raise ValueError(f"{label} must be a positive integer")


def _require_nonnegative_number(value: object, label: str) -> None:
    if _safe_duration(value) is None:
        raise ValueError(f"{label} must be a finite non-negative number")


__all__ = [
    "EventRunObservability",
    "InMemoryMetricsSink",
    "InMemoryTraceSink",
    "MetricPoint",
    "MetricsSink",
    "NullMetricsSink",
    "NullTraceSink",
    "RunCostSummary",
    "RunObservabilitySnapshot",
    "RunTelemetryExporter",
    "RunUsageLedgerEntry",
    "TelemetryExportError",
    "TraceLayer",
    "TraceSink",
    "TraceSpan",
    "TraceStatus",
]
