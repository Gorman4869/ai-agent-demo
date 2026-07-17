from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import secrets
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from time import perf_counter
from typing import TextIO
from uuid import uuid4

from backend.app.container import ApplicationContainer
from backend.app.domain.run import RunRecord, RunStatus, StoredRunEvent
from backend.app.security import StaticTokenAuthenticator
from backend.app.settings import Settings, SettingsError
from backend.app.tools import ToolExecutionContext


_AUTHORIZATION_EXIT_CODE = 64
_CONFIGURATION_EXIT_CODE = 65
_ACCEPTANCE_EXIT_CODE = 1
_COST_QUANTUM = Decimal("0.00000001")
_MILLION = Decimal("1000000")
_OWNER_ID = "m8-online-smoke"
_PROMPT = (
    "Use the add_numbers tool to calculate 2 + 3. "
    "Return only the resulting number in the answer."
)


class OnlineSmokeError(RuntimeError):
    """Safe, operator-facing refusal or acceptance failure."""

    def __init__(self, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass(frozen=True)
class TokenPrices:
    """Operator-supplied USD rates used only for this smoke estimate."""

    input_per_million_usd: Decimal
    output_per_million_usd: Decimal

    def __post_init__(self) -> None:
        for value, label in (
            (self.input_per_million_usd, "input token price"),
            (self.output_per_million_usd, "output token price"),
        ):
            if not value.is_finite() or value <= 0:
                raise OnlineSmokeError(
                    f"{label} must be a positive finite decimal",
                    exit_code=_CONFIGURATION_EXIT_CODE,
                )

    @classmethod
    def from_strings(cls, input_price: str, output_price: str) -> TokenPrices:
        try:
            return cls(
                input_per_million_usd=Decimal(input_price),
                output_per_million_usd=Decimal(output_price),
            )
        except InvalidOperation:
            raise OnlineSmokeError(
                "token prices must be decimal numbers",
                exit_code=_CONFIGURATION_EXIT_CODE,
            ) from None

    def estimate(self, *, input_tokens: int, output_tokens: int) -> Decimal:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must not be negative")
        return (
            Decimal(input_tokens) * self.input_per_million_usd
            + Decimal(output_tokens) * self.output_per_million_usd
        ) / _MILLION


SmokeSummary = dict[str, object]
SmokeExecutor = Callable[[Settings, TokenPrices], Awaitable[SmokeSummary]]
ContainerFactory = Callable[[Settings], ApplicationContainer]


def load_online_settings(
    environment: Mapping[str, str],
    *,
    authorized: bool,
) -> Settings:
    """Read provider configuration only after explicit one-time authorization."""

    if not authorized:
        raise OnlineSmokeError(
            "M8-T6 online smoke requires explicit one-time authorization",
            exit_code=_AUTHORIZATION_EXIT_CODE,
        )
    try:
        settings = Settings.from_environment(environment)
    except SettingsError as error:
        raise OnlineSmokeError(
            str(error),
            exit_code=_CONFIGURATION_EXIT_CODE,
        ) from None
    _require_online_settings(settings)
    return settings


def _require_online_settings(settings: Settings) -> None:
    if settings.runtime != "agents_sdk":
        raise OnlineSmokeError(
            "AI_AGENT_RUNTIME must be agents_sdk",
            exit_code=_CONFIGURATION_EXIT_CODE,
        )
    if not settings.online_provider_enabled or settings.model_provider != "openai":
        raise OnlineSmokeError(
            "the OpenAI provider and explicit online switch are required",
            exit_code=_CONFIGURATION_EXIT_CODE,
        )
    if settings.openai_api_key is None or settings.openai_model is None:
        raise OnlineSmokeError(
            "OPENAI_API_KEY and OPENAI_MODEL are required",
            exit_code=_CONFIGURATION_EXIT_CODE,
        )


def validate_low_budget(settings: Settings, prices: TokenPrices) -> Decimal:
    """Reject broad online limits and return the declared upper-bound estimate."""

    budget = settings.budget
    violations: list[str] = []
    if not 2 <= budget.max_steps <= 4:
        violations.append("AI_AGENT_MAX_STEPS")
    if budget.max_model_calls != 2:
        violations.append("AI_AGENT_MAX_MODEL_CALLS")
    if budget.run_timeout_ms > 60_000:
        violations.append("AI_AGENT_RUN_TIMEOUT_MS")
    if budget.model_timeout_ms > 30_000:
        violations.append("AI_AGENT_MODEL_TIMEOUT_MS")
    if budget.max_input_tokens > 4_000:
        violations.append("AI_AGENT_MAX_INPUT_TOKENS")
    if budget.max_output_tokens > 512:
        violations.append("AI_AGENT_MAX_OUTPUT_TOKENS")
    if budget.max_cost_usd > Decimal("0.25"):
        violations.append("AI_AGENT_MAX_COST_USD")
    if budget.max_model_retries != 0:
        violations.append("AI_AGENT_MAX_MODEL_RETRIES")
    if violations:
        raise OnlineSmokeError(
            "online smoke requires low limits: " + ", ".join(violations),
            exit_code=_CONFIGURATION_EXIT_CODE,
        )

    upper_bound = prices.estimate(
        input_tokens=budget.max_input_tokens,
        output_tokens=budget.max_output_tokens,
    )
    if upper_bound > budget.max_cost_usd:
        raise OnlineSmokeError(
            "declared token-price upper bound exceeds AI_AGENT_MAX_COST_USD",
            exit_code=_CONFIGURATION_EXIT_CODE,
        )
    return upper_bound


async def execute_online_smoke(
    settings: Settings,
    prices: TokenPrices,
    *,
    container_factory: ContainerFactory | None = None,
    clock: Callable[[], float] = perf_counter,
) -> SmokeSummary:
    """Execute one real Run and accept only streamed tool-backed evidence."""

    _require_online_settings(settings)
    validate_low_budget(settings, prices)
    factory = container_factory or _create_online_container
    container = factory(settings)
    run_id = f"m8-online-{uuid4().hex}"
    created_at = datetime.now(UTC)
    record = RunRecord.create(
        run_id=run_id,
        session_id=f"session-{uuid4().hex}",
        owner_id=_OWNER_ID,
        runtime="agents_sdk",
        model_provider="openai",
        model=settings.openai_model,
        input_text=_PROMPT,
        idempotency_key=secrets.token_urlsafe(32),
        created_at=created_at,
        request_options={
            "smoke_suite": "M8-T6",
            "expected_tool": "add_numbers",
        },
    )
    create_result = await container.run_store.create(record)
    if not create_result.created:
        raise OnlineSmokeError(
            "online smoke Run unexpectedly replayed",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )

    started_at = clock()
    completed = await container.run_coordinator.execute(
        run_id,
        owner_id=_OWNER_ID,
        execution_context=ToolExecutionContext(principal_id=_OWNER_ID),
    )
    duration_ms = (clock() - started_at) * 1_000
    events = await container.event_store.list_for_run(
        run_id,
        owner_id=_OWNER_ID,
    )
    return build_online_summary(
        completed,
        events,
        duration_ms=duration_ms,
        prices=prices,
        max_cost_usd=settings.budget.max_cost_usd,
    )


def build_online_summary(
    run: RunRecord,
    events: Sequence[StoredRunEvent],
    *,
    duration_ms: float,
    prices: TokenPrices,
    max_cost_usd: Decimal,
) -> SmokeSummary:
    """Validate durable evidence and return a content-free summary."""

    if not math.isfinite(duration_ms) or duration_ms < 0:
        raise OnlineSmokeError(
            "online smoke duration is invalid",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    if run.status is not RunStatus.COMPLETED:
        failure_code = run.failure.code if run.failure is not None else run.status.value
        raise OnlineSmokeError(
            f"online smoke Run did not complete: {failure_code}",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )

    event_types = [event.type for event in events]
    if (
        not event_types
        or event_types[0] != "run.started"
        or event_types[-1] != "run.completed"
        or any(event.run_id != run.id for event in events)
        or [event.sequence for event in events]
        != list(range(1, len(events) + 1))
    ):
        raise OnlineSmokeError(
            "durable Run lifecycle evidence is incomplete",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    delta_count = event_types.count("model.output.delta")
    if delta_count == 0:
        raise OnlineSmokeError(
            "streamed model output evidence is missing",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )

    started_tool_ids = {
        event.data.get("id")
        for event in events
        if event.type == "tool.started"
        and event.data.get("name") == "add_numbers"
        and isinstance(event.data.get("id"), str)
    }
    completed_tools = [
        event
        for event in events
        if event.type == "tool.completed"
        and event.data.get("name") == "add_numbers"
        and event.data.get("ok") is True
        and event.data.get("id") in started_tool_ids
    ]
    if not completed_tools:
        raise OnlineSmokeError(
            "add_numbers tool completion evidence is missing",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )

    usage_events = [event for event in events if event.type == "model.usage"]
    if len(usage_events) != 1:
        raise OnlineSmokeError(
            "exactly one model.usage event is required",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    usage = usage_events[0].data
    if usage.get("provider") != "openai" or usage.get("model") != run.model:
        raise OnlineSmokeError(
            "model.usage provider metadata does not match the Run",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    usage_values = {
        field: _positive_usage_value(usage, field)
        for field in (
            "requests",
            "input_tokens",
            "output_tokens",
            "total_tokens",
        )
    }
    if usage_values["total_tokens"] != (
        usage_values["input_tokens"] + usage_values["output_tokens"]
    ):
        raise OnlineSmokeError(
            "model.usage token totals are inconsistent",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )

    estimated_cost = prices.estimate(
        input_tokens=usage_values["input_tokens"],
        output_tokens=usage_values["output_tokens"],
    )
    if estimated_cost > max_cost_usd:
        raise OnlineSmokeError(
            "estimated online smoke cost exceeded AI_AGENT_MAX_COST_USD",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    return {
        "suite": "M8-T6",
        "run_id": run.id,
        "status": run.status.value,
        "model": run.model,
        "duration_ms": round(duration_ms, 3),
        "stream_delta_count": delta_count,
        "tool": {"name": "add_numbers", "completed": True},
        "usage": usage_values,
        "estimated_cost_usd": _format_cost(estimated_cost),
        "cost_source": "operator_supplied_per_million_token_rates",
        "event_count": len(events),
        "exit_code": 0,
    }


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    executor: SmokeExecutor = execute_online_smoke,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = _create_parser().parse_args(argv)
    if not args.authorized:
        print(
            "M8-T6 online smoke refused: explicit one-time authorization is missing",
            file=stderr,
        )
        return _AUTHORIZATION_EXIT_CODE

    try:
        prices = TokenPrices.from_strings(
            args.input_price_per_million_usd,
            args.output_price_per_million_usd,
        )
        settings = load_online_settings(
            os.environ if environment is None else environment,
            authorized=True,
        )
        validate_low_budget(settings, prices)
        summary = asyncio.run(executor(settings, prices))
    except OnlineSmokeError as error:
        print(f"M8-T6 online smoke refused: {error}", file=stderr)
        return error.exit_code
    except Exception:
        print("M8-T6 online smoke failed with an internal error", file=stderr)
        return _ACCEPTANCE_EXIT_CODE

    print(json.dumps(summary, ensure_ascii=True, sort_keys=True), file=stdout)
    return 0


def main() -> int:
    return run_cli()


def _create_online_container(settings: Settings) -> ApplicationContainer:
    return ApplicationContainer.create(
        settings=settings,
        authenticator=StaticTokenAuthenticator(),
    )


def _positive_usage_value(usage: Mapping[str, object], field: str) -> int:
    value = usage.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise OnlineSmokeError(
            f"model.usage {field} must be a positive integer",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    return value


def _format_cost(value: Decimal) -> str:
    return format(value.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP), "f")


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the explicitly authorized M8-T6 online smoke.",
    )
    parser.add_argument("--authorized", action="store_true")
    parser.add_argument("--suite", choices=("M8",), default="M8")
    parser.add_argument("--input-price-per-million-usd", default="0")
    parser.add_argument("--output-price-per-million-usd", default="0")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
