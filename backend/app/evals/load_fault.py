from __future__ import annotations

import asyncio
import ctypes
import json
import math
import os
import secrets
import sys
from collections import Counter
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from time import perf_counter, sleep
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from backend.app.agent import RuntimeControl, RuntimeResult
from backend.app.agent.manual_loop import ManualAgentLoop
from backend.app.container import ApplicationContainer
from backend.app.domain import ModelDecision
from backend.app.domain.run import RunRecord, RunStatus
from backend.app.models import RetryableModelError
from backend.app.settings import Settings
from backend.app.tools import ToolRegistry


_SCHEMA_VERSION = "m13-load-fault-v1"
_OWNER_ID = "m13-load-fault-owner"
_SAFE_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost"})


class ScenarioOperationError(RuntimeError):
    """A stable, content-free failure emitted by one measured operation."""

    def __init__(self, code: str) -> None:
        _require_identifier(code, "scenario error code")
        super().__init__(code)
        self.code = code


class AsyncScenarioOperation(Protocol):
    async def __call__(self, index: int) -> None: ...


@dataclass(frozen=True)
class LoadFaultConfig:
    concurrent_runs: int = 24
    concurrency: int = 6
    runtime_delay_ms: int = 20
    slow_client_pause_ms: int = 100
    retry_delay_ms: int = 20
    operation_timeout_ms: int = 10_000
    sample_interval_ms: int = 10

    def __post_init__(self) -> None:
        _require_bounded_int(self.concurrent_runs, "concurrent runs", 1, 100)
        _require_bounded_int(self.concurrency, "concurrency", 1, 16)
        if self.concurrency > self.concurrent_runs:
            raise ValueError("concurrency must not exceed concurrent runs")
        _require_bounded_int(self.runtime_delay_ms, "runtime delay", 1, 2_000)
        _require_bounded_int(
            self.slow_client_pause_ms,
            "slow client pause",
            1,
            2_000,
        )
        _require_bounded_int(self.retry_delay_ms, "retry delay", 0, 2_000)
        _require_bounded_int(
            self.operation_timeout_ms,
            "operation timeout",
            100,
            120_000,
        )
        _require_bounded_int(
            self.sample_interval_ms,
            "sample interval",
            1,
            1_000,
        )


@dataclass(frozen=True)
class LatencySummary:
    minimum_ms: float
    p50_ms: float
    p95_ms: float
    maximum_ms: float
    mean_ms: float

    def __post_init__(self) -> None:
        for value in (
            self.minimum_ms,
            self.p50_ms,
            self.p95_ms,
            self.maximum_ms,
            self.mean_ms,
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError("latency values must be finite and non-negative")

    def to_record(self) -> dict[str, float]:
        return {
            "min_ms": self.minimum_ms,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "max_ms": self.maximum_ms,
            "mean_ms": self.mean_ms,
        }


@dataclass(frozen=True)
class ScenarioReport:
    name: str
    attempted: int
    succeeded: int
    failed: int
    elapsed_ms: float
    latency: LatencySummary
    peak_in_flight: int
    rss_start_bytes: int
    rss_peak_bytes: int
    rss_end_bytes: int
    error_counts: tuple[tuple[str, int], ...] = ()
    measurements: tuple[tuple[str, int | float | bool], ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.name, "scenario name")
        _require_bounded_int(self.attempted, "attempted", 1, 10_000)
        _require_bounded_int(self.succeeded, "succeeded", 0, self.attempted)
        _require_bounded_int(self.failed, "failed", 0, self.attempted)
        if self.succeeded + self.failed != self.attempted:
            raise ValueError("scenario outcome counts are inconsistent")
        if not math.isfinite(self.elapsed_ms) or self.elapsed_ms < 0:
            raise ValueError("scenario elapsed_ms must be finite and non-negative")
        _require_bounded_int(
            self.peak_in_flight,
            "peak in flight",
            1,
            self.attempted,
        )
        for value in (
            self.rss_start_bytes,
            self.rss_peak_bytes,
            self.rss_end_bytes,
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError("RSS values must be non-negative integers")
        if self.rss_peak_bytes < max(self.rss_start_bytes, self.rss_end_bytes):
            raise ValueError("peak RSS must include the start and end snapshots")
        for code, count in self.error_counts:
            _require_identifier(code, "scenario error code")
            _require_bounded_int(count, "scenario error count", 1, self.failed)
        if sum(count for _, count in self.error_counts) != self.failed:
            raise ValueError("scenario error counts are inconsistent")
        for name, value in self.measurements:
            _require_identifier(name, "measurement name")
            if isinstance(value, float) and (
                not math.isfinite(value) or value < 0
            ):
                raise ValueError("measurement values must be finite and non-negative")
            if isinstance(value, int) and not isinstance(value, bool) and value < 0:
                raise ValueError("measurement values must be non-negative")

    @property
    def passed(self) -> bool:
        return self.failed == 0

    @property
    def error_rate(self) -> float:
        return self.failed / self.attempted

    @property
    def throughput_per_second(self) -> float:
        if self.elapsed_ms == 0:
            return 0.0
        return self.succeeded / (self.elapsed_ms / 1_000)

    def to_record(self) -> dict[str, object]:
        return {
            "name": self.name,
            "passed": self.passed,
            "attempted": self.attempted,
            "succeeded": self.succeeded,
            "failed": self.failed,
            "error_rate": round(self.error_rate, 6),
            "throughput_per_second": round(self.throughput_per_second, 3),
            "elapsed_ms": round(self.elapsed_ms, 3),
            "latency": self.latency.to_record(),
            "peak_in_flight": self.peak_in_flight,
            "rss": {
                "start_bytes": self.rss_start_bytes,
                "peak_bytes": self.rss_peak_bytes,
                "end_bytes": self.rss_end_bytes,
                "peak_delta_bytes": max(
                    0,
                    self.rss_peak_bytes - self.rss_start_bytes,
                ),
            },
            "error_counts": dict(self.error_counts),
            "measurements": dict(self.measurements),
        }


@dataclass(frozen=True)
class LoadFaultReport:
    evidence_scope: str
    scenarios: tuple[ScenarioReport, ...]

    def __post_init__(self) -> None:
        _require_identifier(self.evidence_scope, "evidence scope")
        if not self.scenarios:
            raise ValueError("at least one scenario report is required")
        names = tuple(scenario.name for scenario in self.scenarios)
        if len(names) != len(set(names)):
            raise ValueError("scenario names must be unique")

    @property
    def passed(self) -> bool:
        return all(scenario.passed for scenario in self.scenarios)

    def to_record(self) -> dict[str, object]:
        return {
            "schema_version": _SCHEMA_VERSION,
            "evidence_scope": self.evidence_scope,
            "passed": self.passed,
            "scenarios": [scenario.to_record() for scenario in self.scenarios],
        }


RssReader = Callable[[], int]
Clock = Callable[[], float]


async def measure_async_scenario(
    name: str,
    *,
    attempted: int,
    concurrency: int,
    operation: AsyncScenarioOperation,
    sample_interval_ms: int = 10,
    operation_timeout_ms: int = 30_000,
    rss_reader: RssReader | None = None,
    clock: Clock = perf_counter,
    measurements: Sequence[tuple[str, int | float | bool]] = (),
) -> ScenarioReport:
    """Measure bounded async work without retaining inputs or exception text."""

    _require_identifier(name, "scenario name")
    _require_bounded_int(attempted, "attempted", 1, 10_000)
    _require_bounded_int(concurrency, "concurrency", 1, attempted)
    _require_bounded_int(sample_interval_ms, "sample interval", 1, 1_000)
    _require_bounded_int(
        operation_timeout_ms,
        "operation timeout",
        100,
        120_000,
    )
    resolved_rss_reader = rss_reader or read_process_rss_bytes
    rss_start = resolved_rss_reader()
    rss_samples = [rss_start]
    stop_sampling = asyncio.Event()
    semaphore = asyncio.Semaphore(concurrency)
    in_flight = 0
    peak_in_flight = 0
    latencies: list[float] = []
    errors: Counter[str] = Counter()

    async def sample_resources() -> None:
        while not stop_sampling.is_set():
            try:
                await asyncio.wait_for(
                    stop_sampling.wait(),
                    timeout=sample_interval_ms / 1_000,
                )
            except TimeoutError:
                rss_samples.append(resolved_rss_reader())

    async def execute(index: int) -> None:
        nonlocal in_flight, peak_in_flight
        async with semaphore:
            in_flight += 1
            peak_in_flight = max(peak_in_flight, in_flight)
            operation_started = clock()
            try:
                await asyncio.wait_for(
                    operation(index),
                    timeout=operation_timeout_ms / 1_000,
                )
            except asyncio.CancelledError:
                raise
            except TimeoutError:
                errors["scenario_timeout"] += 1
            except ScenarioOperationError as error:
                errors[error.code] += 1
            except Exception:
                errors["scenario_internal_error"] += 1
            finally:
                latencies.append(max(0.0, (clock() - operation_started) * 1_000))
                in_flight -= 1

    started_at = clock()
    sampler = asyncio.create_task(sample_resources(), name=f"{name}:rss")
    try:
        await asyncio.gather(*(execute(index) for index in range(attempted)))
    finally:
        stop_sampling.set()
        await sampler
    elapsed_ms = max(0.0, (clock() - started_at) * 1_000)
    rss_end = resolved_rss_reader()
    rss_samples.append(rss_end)
    failed = sum(errors.values())
    return ScenarioReport(
        name=name,
        attempted=attempted,
        succeeded=attempted - failed,
        failed=failed,
        elapsed_ms=round(elapsed_ms, 3),
        latency=_summarize_latencies(latencies),
        peak_in_flight=peak_in_flight,
        rss_start_bytes=rss_start,
        rss_peak_bytes=max(rss_samples),
        rss_end_bytes=rss_end,
        error_counts=tuple(sorted(errors.items())),
        measurements=tuple(measurements),
    )


async def execute_offline_load_fault_probe(
    config: LoadFaultConfig | None = None,
) -> LoadFaultReport:
    """Exercise deterministic production paths without a DSN, Key or network."""

    resolved = config or LoadFaultConfig()
    concurrent = await _measure_concurrent_runs(resolved)
    slow_client = await _measure_slow_client(resolved)
    rate_limit = await _measure_model_rate_limit(resolved)
    return LoadFaultReport(
        evidence_scope="offline_process",
        scenarios=(concurrent, slow_client, rate_limit),
    )


async def execute_local_http_load_probe(
    base_url: str,
    config: LoadFaultConfig | None = None,
) -> LoadFaultReport:
    """Measure one explicitly selected localhost deployment through durable HTTP."""

    resolved = config or LoadFaultConfig()
    normalized_base_url = normalize_local_base_url(base_url)

    async def execute(index: int) -> None:
        await asyncio.to_thread(
            _execute_local_http_run,
            normalized_base_url,
            index,
            resolved.operation_timeout_ms,
        )

    scenario = await measure_async_scenario(
        "deployed_concurrent_runs",
        attempted=resolved.concurrent_runs,
        concurrency=resolved.concurrency,
        operation=execute,
        sample_interval_ms=resolved.sample_interval_ms,
        operation_timeout_ms=resolved.operation_timeout_ms,
        measurements=(("configured_concurrency", resolved.concurrency),),
    )
    return LoadFaultReport(
        evidence_scope="localhost_deployment",
        scenarios=(scenario,),
    )


def normalize_local_base_url(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("base URL must be a string")
    parsed = urlsplit(value.strip())
    if (
        parsed.scheme != "http"
        or parsed.hostname not in _SAFE_LOCAL_HOSTS
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("base URL must be an explicit localhost HTTP origin")
    return f"http://{parsed.hostname}:{parsed.port}"


def read_process_rss_bytes() -> int:
    """Return current process RSS using only operating-system APIs."""

    if sys.platform == "win32":
        return _read_windows_rss_bytes()
    status_path = "/proc/self/statm"
    if os.path.exists(status_path):
        try:
            with open(status_path, encoding="ascii") as status_file:
                fields = status_file.read().split()
            return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")
        except (OSError, ValueError, IndexError):
            return 0
    try:
        import resource

        maximum_rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    except (ImportError, OSError, ValueError):
        return 0
    multiplier = 1 if sys.platform == "darwin" else 1_024
    return max(0, int(maximum_rss) * multiplier)


async def _measure_concurrent_runs(config: LoadFaultConfig) -> ScenarioReport:
    runtime = _DelayedRuntime(config.runtime_delay_ms / 1_000)
    container = ApplicationContainer.create(
        settings=Settings.from_environment({}),
        runtimes={"manual": runtime},
    )

    async def execute(index: int) -> None:
        run = RunRecord.create(
            run_id=f"m13-load-{index}",
            session_id=f"m13-load-session-{index}",
            owner_id=_OWNER_ID,
            runtime="manual",
            input_text="bounded load probe",
            idempotency_key=f"m13-load-idempotency-{index}",
            created_at=datetime.now(UTC),
        )
        created = await container.run_store.create(run)
        if not created.created:
            raise ScenarioOperationError("run_replayed")
        completed = await container.run_coordinator.execute(
            run.id,
            owner_id=run.owner_id,
        )
        if completed.status is not RunStatus.COMPLETED:
            raise ScenarioOperationError("run_not_completed")

    try:
        return await measure_async_scenario(
            "concurrent_runs",
            attempted=config.concurrent_runs,
            concurrency=config.concurrency,
            operation=execute,
            sample_interval_ms=config.sample_interval_ms,
            operation_timeout_ms=config.operation_timeout_ms,
            measurements=(("configured_concurrency", config.concurrency),),
        )
    finally:
        await container.close()


async def _measure_slow_client(config: LoadFaultConfig) -> ScenarioReport:
    from backend.app.main import _durable_event_stream

    runtime = _GatedRuntime()
    container = ApplicationContainer.create(
        settings=Settings.from_environment({}),
        runtimes={"manual": runtime},
    )
    completion_ms = 0.0

    async def execute(_: int) -> None:
        nonlocal completion_ms
        run = RunRecord.create(
            run_id="m13-slow-client-run",
            session_id="m13-slow-client-session",
            owner_id=_OWNER_ID,
            runtime="manual",
            input_text="bounded slow client probe",
            idempotency_key="m13-slow-client-idempotency",
            created_at=datetime.now(UTC),
        )
        await container.run_store.create(run)
        stream = _durable_event_stream(
            container,
            run_id=run.id,
            owner_id=run.owner_id,
            after_sequence=0,
        )
        execution = asyncio.create_task(
            container.run_coordinator.execute(run.id, owner_id=run.owner_id),
            name="m13-slow-client-execution",
        )
        try:
            first = await asyncio.wait_for(
                anext(stream),
                timeout=config.operation_timeout_ms / 1_000,
            )
            if "event: run.started" not in first:
                raise ScenarioOperationError("slow_client_start_missing")
            started_at = perf_counter()
            runtime.release.set()
            completed = await asyncio.wait_for(
                execution,
                timeout=config.operation_timeout_ms / 1_000,
            )
            completion_ms = round((perf_counter() - started_at) * 1_000, 3)
            await asyncio.sleep(config.slow_client_pause_ms / 1_000)
            if completed.status is not RunStatus.COMPLETED:
                raise ScenarioOperationError("slow_client_blocked_run")
        finally:
            if not execution.done():
                execution.cancel()
                await asyncio.gather(execution, return_exceptions=True)
            await stream.aclose()

    try:
        report = await measure_async_scenario(
            "slow_sse_client",
            attempted=1,
            concurrency=1,
            operation=execute,
            sample_interval_ms=config.sample_interval_ms,
            operation_timeout_ms=config.operation_timeout_ms,
        )
    finally:
        await container.close()
    return _replace_measurements(
        report,
        (
            ("client_pause_ms", config.slow_client_pause_ms),
            ("run_completion_ms", completion_ms),
        ),
    )


async def _measure_model_rate_limit(config: LoadFaultConfig) -> ScenarioReport:
    model = _RateLimitedOnceModel()
    retry_event_count = 0

    async def execute(_: int) -> None:
        nonlocal retry_event_count
        result = await asyncio.to_thread(
            ManualAgentLoop(
                model,
                ToolRegistry(),
                max_model_retries=1,
                model_retry_initial_delay_ms=config.retry_delay_ms,
                model_retry_max_delay_ms=config.retry_delay_ms,
            ).run,
            "bounded rate limit probe",
        )
        retry_event_count = sum(
            event.type == "model.retrying" for event in result.events
        )
        if result.status != "completed" or model.calls != 2:
            raise ScenarioOperationError("model_rate_limit_not_recovered")
        if retry_event_count != 1:
            raise ScenarioOperationError("model_retry_evidence_missing")

    report = await measure_async_scenario(
        "model_rate_limit",
        attempted=1,
        concurrency=1,
        operation=execute,
        sample_interval_ms=config.sample_interval_ms,
        operation_timeout_ms=config.operation_timeout_ms,
    )
    return _replace_measurements(
        report,
        (
            ("model_calls", model.calls),
            ("retry_events", retry_event_count),
            ("configured_retry_delay_ms", config.retry_delay_ms),
        ),
    )


def _execute_local_http_run(
    base_url: str,
    index: int,
    timeout_ms: int,
) -> None:
    capability = secrets.token_urlsafe(32)
    request = Request(
        f"{base_url}/api/durable/runs",
        data=json.dumps({"message": "2 + 3"}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Idempotency-Key": capability,
        },
        method="POST",
    )
    timeout_seconds = timeout_ms / 1_000
    payload = _read_json_response(request, timeout_seconds=timeout_seconds)
    run_id = payload.get("id")
    session_capability = payload.get("session_capability")
    if not isinstance(run_id, str) or session_capability != capability:
        raise ScenarioOperationError("http_create_contract_error")
    deadline = perf_counter() + timeout_seconds
    while perf_counter() < deadline:
        read_request = Request(
            f"{base_url}/api/durable/runs/{run_id}",
            headers={"X-Session-Token": capability},
            method="GET",
        )
        stored = _read_json_response(
            read_request,
            timeout_seconds=max(0.1, deadline - perf_counter()),
        )
        status = stored.get("status")
        if status == "completed":
            return
        if status in {"failed", "cancelled"}:
            raise ScenarioOperationError("http_run_not_completed")
        if status not in {"queued", "running", "waiting_approval"}:
            raise ScenarioOperationError("http_run_contract_error")
        # The sleep is local client polling only and stays inside the total deadline.
        sleep(0.01)
    raise ScenarioOperationError("http_run_timeout")


def _read_json_response(request: Request, *, timeout_seconds: float) -> Mapping[str, object]:
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status not in {200, 202}:
                raise ScenarioOperationError("http_unexpected_status")
            payload = json.loads(response.read().decode("utf-8"))
    except ScenarioOperationError:
        raise
    except HTTPError as error:
        code = "http_server_error" if error.code >= 500 else "http_client_error"
        raise ScenarioOperationError(code) from None
    except (URLError, TimeoutError, OSError):
        raise ScenarioOperationError("http_unavailable") from None
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ScenarioOperationError("http_response_invalid") from None
    if not isinstance(payload, dict):
        raise ScenarioOperationError("http_response_invalid")
    return payload


class _DelayedRuntime:
    def __init__(self, delay_seconds: float) -> None:
        self._delay_seconds = delay_seconds

    async def run(self, request, *, emit, control: RuntimeControl) -> RuntimeResult:
        del request, emit, control
        await asyncio.sleep(self._delay_seconds)
        return RuntimeResult(status=RunStatus.COMPLETED, answer="ok", step=1)


class _GatedRuntime:
    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def run(self, request, *, emit, control: RuntimeControl) -> RuntimeResult:
        del request, emit, control
        await self.release.wait()
        return RuntimeResult(status=RunStatus.COMPLETED, answer="ok", step=1)


class _RateLimitedOnceModel:
    def __init__(self) -> None:
        self.calls = 0

    def decide(self, messages, tools) -> ModelDecision:
        del messages, tools
        self.calls += 1
        if self.calls == 1:
            raise RetryableModelError("deterministic rate limit fixture")
        return ModelDecision(final_answer="recovered")


def _summarize_latencies(values: Sequence[float]) -> LatencySummary:
    if not values:
        raise ValueError("at least one latency value is required")
    normalized = sorted(round(max(0.0, value), 3) for value in values)
    return LatencySummary(
        minimum_ms=normalized[0],
        p50_ms=_nearest_rank(normalized, 0.50),
        p95_ms=_nearest_rank(normalized, 0.95),
        maximum_ms=normalized[-1],
        mean_ms=round(sum(normalized) / len(normalized), 3),
    )


def _nearest_rank(values: Sequence[float], percentile: float) -> float:
    if not values:
        raise ValueError("percentile requires at least one value")
    if not 0 < percentile <= 1:
        raise ValueError("percentile must be in (0, 1]")
    return values[max(0, math.ceil(percentile * len(values)) - 1)]


def _replace_measurements(
    report: ScenarioReport,
    measurements: Sequence[tuple[str, int | float | bool]],
) -> ScenarioReport:
    return ScenarioReport(
        name=report.name,
        attempted=report.attempted,
        succeeded=report.succeeded,
        failed=report.failed,
        elapsed_ms=report.elapsed_ms,
        latency=report.latency,
        peak_in_flight=report.peak_in_flight,
        rss_start_bytes=report.rss_start_bytes,
        rss_peak_bytes=report.rss_peak_bytes,
        rss_end_bytes=report.rss_end_bytes,
        error_counts=report.error_counts,
        measurements=tuple(measurements),
    )


def _read_windows_rss_bytes() -> int:
    from ctypes import wintypes

    class ProcessMemoryCounters(ctypes.Structure):
        _fields_ = (
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        )

    counters = ProcessMemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    psapi.GetProcessMemoryInfo.argtypes = (
        wintypes.HANDLE,
        ctypes.POINTER(ProcessMemoryCounters),
        wintypes.DWORD,
    )
    psapi.GetProcessMemoryInfo.restype = wintypes.BOOL
    process = kernel32.GetCurrentProcess()
    if not psapi.GetProcessMemoryInfo(
        process,
        ctypes.byref(counters),
        counters.cb,
    ):
        return 0
    return max(0, int(counters.WorkingSetSize))


def _require_identifier(value: str, label: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 100
        or any(
            not (
                character.islower()
                or character.isdigit()
                or character in "-_"
            )
            for character in value
        )
    ):
        raise ValueError(f"{label} has an invalid format")


def _require_bounded_int(value: int, label: str, minimum: int, maximum: int) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < minimum
        or value > maximum
    ):
        raise ValueError(f"{label} must be between {minimum} and {maximum}")


__all__ = [
    "LatencySummary",
    "LoadFaultConfig",
    "LoadFaultReport",
    "ScenarioOperationError",
    "ScenarioReport",
    "execute_local_http_load_probe",
    "execute_offline_load_fault_probe",
    "measure_async_scenario",
    "normalize_local_base_url",
    "read_process_rss_bytes",
]
