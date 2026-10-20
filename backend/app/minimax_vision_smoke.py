from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import sys
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from importlib.util import find_spec
from time import perf_counter
from typing import TextIO
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from backend.app.advanced.multimodal import (
    MINIMAX_CN_BASE_URL,
    MINIMAX_VISION_MODEL,
    MiniMaxVisionClientFactory,
    MiniMaxVisionModel,
    MultimodalVisionAgent,
    VisionRunResult,
    create_minimax_vision_client_factory,
)
from backend.app.settings import RunBudgetSettings, Settings, SettingsError
from backend.app.vision_online_smoke import build_vision_fixture


_AUTHORIZATION_EXIT_CODE = 64
_CONFIGURATION_EXIT_CODE = 65
_ACCEPTANCE_EXIT_CODE = 1
_COST_QUANTUM = Decimal("0.00000001")
_MILLION = Decimal("1000000")
_FIXTURE_ID = "prompt-injection-png-v1"
_BUDGET_ENVIRONMENT_NAMES = (
    "AI_AGENT_MAX_STEPS",
    "AI_AGENT_MAX_MODEL_CALLS",
    "AI_AGENT_RUN_TIMEOUT_MS",
    "AI_AGENT_MODEL_TIMEOUT_MS",
    "AI_AGENT_MAX_INPUT_TOKENS",
    "AI_AGENT_MAX_OUTPUT_TOKENS",
    "AI_AGENT_MAX_MODEL_RETRIES",
    "AI_AGENT_MODEL_RETRY_INITIAL_DELAY_MS",
    "AI_AGENT_MODEL_RETRY_MAX_DELAY_MS",
    "AI_AGENT_MAX_TOOL_RETRIES",
    "AI_AGENT_TOOL_RETRY_INITIAL_DELAY_MS",
    "AI_AGENT_TOOL_RETRY_MAX_DELAY_MS",
)
_PROXY_ENVIRONMENT_NAMES = (
    "HTTP_PROXY",
    "http_proxy",
    "HTTPS_PROXY",
    "https_proxy",
    "ALL_PROXY",
    "all_proxy",
)


class MiniMaxVisionSmokeError(RuntimeError):
    """Content-free operator refusal or M14-T4 acceptance failure."""

    def __init__(self, message: str, *, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


class MiniMaxVisionSmokeSettings(BaseModel):
    """One-call MiniMax CN credentials and server-owned budget snapshot."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    api_key: SecretStr = Field(repr=False, exclude=True)
    model: str
    budget: RunBudgetSettings
    max_cost_cny: Decimal = Field(
        gt=Decimal("0"),
        le=Decimal("10"),
        allow_inf_nan=False,
    )
    base_url: str = Field(default=MINIMAX_CN_BASE_URL, repr=False)

    @field_validator("api_key", mode="before")
    @classmethod
    def validate_api_key(cls, value: object) -> object:
        if isinstance(value, SecretStr):
            raw_value = value.get_secret_value()
        elif isinstance(value, str):
            raw_value = value
        else:
            return value
        normalized = raw_value.strip()
        if (
            not normalized
            or len(normalized) > 512
            or any(character.isspace() or ord(character) < 32 for character in normalized)
        ):
            raise ValueError("MINIMAX_API_KEY has an invalid format")
        return SecretStr(normalized)

    @field_validator("model")
    @classmethod
    def validate_model(cls, value: str) -> str:
        if value != MINIMAX_VISION_MODEL:
            raise ValueError("MiniMax vision requires MiniMax-M3")
        return value


@dataclass(frozen=True)
class MiniMaxCnyTokenPrices:
    """Operator-supplied CNY rates used only for this smoke estimate."""

    input_per_million_cny: Decimal
    output_per_million_cny: Decimal

    def __post_init__(self) -> None:
        for value, label in (
            (self.input_per_million_cny, "input token price"),
            (self.output_per_million_cny, "output token price"),
        ):
            if not value.is_finite() or value <= 0:
                raise MiniMaxVisionSmokeError(
                    f"{label} must be a positive finite decimal",
                    exit_code=_CONFIGURATION_EXIT_CODE,
                )

    @classmethod
    def from_strings(
        cls,
        input_price: str,
        output_price: str,
    ) -> MiniMaxCnyTokenPrices:
        try:
            return cls(
                input_per_million_cny=Decimal(input_price),
                output_per_million_cny=Decimal(output_price),
            )
        except InvalidOperation:
            raise MiniMaxVisionSmokeError(
                "token prices must be decimal numbers",
                exit_code=_CONFIGURATION_EXIT_CODE,
            ) from None

    def estimate(self, *, input_tokens: int, output_tokens: int) -> Decimal:
        if input_tokens < 0 or output_tokens < 0:
            raise ValueError("token counts must not be negative")
        return (
            Decimal(input_tokens) * self.input_per_million_cny
            + Decimal(output_tokens) * self.output_per_million_cny
        ) / _MILLION


MiniMaxVisionSmokeSummary = dict[str, object]
MiniMaxVisionSmokeExecutor = Callable[
    [MiniMaxVisionSmokeSettings, MiniMaxCnyTokenPrices],
    Awaitable[MiniMaxVisionSmokeSummary],
]


def load_minimax_vision_settings(
    environment: Mapping[str, str],
    *,
    authorized: bool,
    declared_model: str | None,
) -> MiniMaxVisionSmokeSettings:
    """Read the MiniMax credential only after one-time authorization."""

    if not authorized:
        raise MiniMaxVisionSmokeError(
            "M14-T4 MiniMax vision smoke requires explicit one-time authorization",
            exit_code=_AUTHORIZATION_EXIT_CODE,
        )
    if declared_model != MINIMAX_VISION_MODEL:
        raise MiniMaxVisionSmokeError(
            "--vision-model must be the reviewed MiniMax-M3 model",
            exit_code=_CONFIGURATION_EXIT_CODE,
        )
    online_value = environment.get("AI_AGENT_ONLINE_ENABLED")
    if not isinstance(online_value, str) or online_value.strip().lower() != "true":
        raise MiniMaxVisionSmokeError(
            "AI_AGENT_ONLINE_ENABLED must be true",
            exit_code=_CONFIGURATION_EXIT_CODE,
        )
    api_key = environment.get("MINIMAX_API_KEY")
    if not isinstance(api_key, str) or not api_key.strip():
        raise MiniMaxVisionSmokeError(
            "MINIMAX_API_KEY is required",
            exit_code=_CONFIGURATION_EXIT_CODE,
        )
    configured_model = environment.get("MINIMAX_MODEL")
    if not isinstance(configured_model, str) or configured_model.strip() != declared_model:
        raise MiniMaxVisionSmokeError(
            "--vision-model must exactly match MINIMAX_MODEL",
            exit_code=_CONFIGURATION_EXIT_CODE,
        )
    budget_environment = {
        name: value
        for name in _BUDGET_ENVIRONMENT_NAMES
        if (value := environment.get(name)) is not None
    }
    try:
        budget = Settings.from_environment(budget_environment).budget
        max_cost_cny = Decimal(
            environment.get("AI_AGENT_MAX_COST_CNY", "0.05").strip()
        )
        settings = MiniMaxVisionSmokeSettings(
            api_key=api_key,
            model=configured_model.strip(),
            budget=budget,
            max_cost_cny=max_cost_cny,
        )
    except (SettingsError, InvalidOperation, ValueError):
        raise MiniMaxVisionSmokeError(
            "MiniMax vision settings are invalid",
            exit_code=_CONFIGURATION_EXIT_CODE,
        ) from None
    _require_supported_proxy_environment(environment)
    return settings


def validate_minimax_vision_budget(
    settings: MiniMaxVisionSmokeSettings,
    prices: MiniMaxCnyTokenPrices,
) -> Decimal:
    """Reject broad limits and return the operator-declared CNY upper bound."""

    budget = settings.budget
    violations: list[str] = []
    if budget.max_model_calls != 1:
        violations.append("AI_AGENT_MAX_MODEL_CALLS")
    if budget.run_timeout_ms > 30_000:
        violations.append("AI_AGENT_RUN_TIMEOUT_MS")
    if budget.model_timeout_ms > 20_000:
        violations.append("AI_AGENT_MODEL_TIMEOUT_MS")
    if budget.max_input_tokens > 2_000:
        violations.append("AI_AGENT_MAX_INPUT_TOKENS")
    if budget.max_output_tokens > 256:
        violations.append("AI_AGENT_MAX_OUTPUT_TOKENS")
    if settings.max_cost_cny > Decimal("0.05"):
        violations.append("AI_AGENT_MAX_COST_CNY")
    if budget.max_model_retries != 0:
        violations.append("AI_AGENT_MAX_MODEL_RETRIES")
    if violations:
        raise MiniMaxVisionSmokeError(
            "MiniMax vision smoke requires low limits: " + ", ".join(violations),
            exit_code=_CONFIGURATION_EXIT_CODE,
        )
    upper_bound = prices.estimate(
        input_tokens=budget.max_input_tokens,
        output_tokens=budget.max_output_tokens,
    )
    if upper_bound > settings.max_cost_cny:
        raise MiniMaxVisionSmokeError(
            "declared token-price upper bound exceeds AI_AGENT_MAX_COST_CNY",
            exit_code=_CONFIGURATION_EXIT_CODE,
        )
    return upper_bound


async def execute_minimax_vision_smoke(
    settings: MiniMaxVisionSmokeSettings,
    prices: MiniMaxCnyTokenPrices,
    *,
    client_factory: MiniMaxVisionClientFactory | None = None,
    clock: Callable[[], float] = perf_counter,
) -> MiniMaxVisionSmokeSummary:
    """Execute exactly one bounded MiniMax request against the fixed PNG."""

    validate_minimax_vision_budget(settings, prices)
    resolved_factory = client_factory or create_minimax_vision_client_factory(
        api_key=settings.api_key.get_secret_value(),
        timeout_ms=settings.budget.model_timeout_ms,
    )
    agent = MultimodalVisionAgent(
        MiniMaxVisionModel(
            model=settings.model,
            max_output_tokens=settings.budget.max_output_tokens,
            client_factory=resolved_factory,
        ),
        timeout_ms=settings.budget.model_timeout_ms,
    )
    image = build_vision_fixture()
    started_at = clock()
    result = await agent.inspect(image, media_type="image/png")
    duration_ms = (clock() - started_at) * 1_000
    return build_minimax_vision_summary(
        result,
        duration_ms=duration_ms,
        prices=prices,
        settings=settings,
    )


def build_minimax_vision_summary(
    result: VisionRunResult,
    *,
    duration_ms: float,
    prices: MiniMaxCnyTokenPrices,
    settings: MiniMaxVisionSmokeSettings,
) -> MiniMaxVisionSmokeSummary:
    """Accept one MiniMax observation and return content-free evidence."""

    if not math.isfinite(duration_ms) or duration_ms < 0:
        raise MiniMaxVisionSmokeError(
            "MiniMax vision smoke duration is invalid",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    if result.failure is not None or result.observation is None:
        failure_code = (
            result.failure.code if result.failure is not None else "missing_observation"
        )
        raise MiniMaxVisionSmokeError(
            f"MiniMax vision smoke did not produce an observation: {failure_code}",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    observation = result.observation
    if (
        observation.offline
        or observation.provider != "minimax"
        or observation.model != settings.model
    ):
        raise MiniMaxVisionSmokeError(
            "MiniMax vision observation provider metadata is invalid",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    if (
        observation.trust != "untrusted_visual_data"
        or observation.visual_text.trust != "untrusted_visual_data"
        or observation.can_authorize_actions
        or observation.visual_text.can_authorize_actions
    ):
        raise MiniMaxVisionSmokeError(
            "visual content escaped the untrusted authorization boundary",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    if observation.visual_text.byte_length < 1:
        raise MiniMaxVisionSmokeError(
            "MiniMax vision smoke did not return visible-text evidence",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    if result.usage is None:
        raise MiniMaxVisionSmokeError(
            "MiniMax vision usage is missing",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    usage = {
        "requests": 1,
        "input_tokens": _positive_usage_value(
            result.usage.input_tokens,
            "input_tokens",
        ),
        "output_tokens": _positive_usage_value(
            result.usage.output_tokens,
            "output_tokens",
        ),
        "total_tokens": _positive_usage_value(
            result.usage.total_tokens,
            "total_tokens",
        ),
    }
    if usage["total_tokens"] != usage["input_tokens"] + usage["output_tokens"]:
        raise MiniMaxVisionSmokeError(
            "MiniMax vision usage token totals are inconsistent",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    if (
        usage["input_tokens"] > settings.budget.max_input_tokens
        or usage["output_tokens"] > settings.budget.max_output_tokens
    ):
        raise MiniMaxVisionSmokeError(
            "MiniMax vision usage exceeded the declared token budget",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    estimated_cost = prices.estimate(
        input_tokens=usage["input_tokens"],
        output_tokens=usage["output_tokens"],
    )
    if estimated_cost > settings.max_cost_cny:
        raise MiniMaxVisionSmokeError(
            "estimated MiniMax vision cost exceeded AI_AGENT_MAX_COST_CNY",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    return {
        "suite": "M14-T4",
        "status": "passed",
        "provider": "minimax",
        "platform": "cn",
        "model": observation.model,
        "duration_ms": round(duration_ms, 3),
        "fixture": {
            "id": _FIXTURE_ID,
            "sha256": observation.image.sha256,
            "width": observation.image.width,
            "height": observation.image.height,
            "byte_length": observation.image.byte_length,
        },
        "observation": {
            "structured": True,
            "offline": False,
            "trust": observation.trust,
            "visual_text_present": True,
            "visual_text_bytes": observation.visual_text.byte_length,
            "uncertainty_count": len(observation.uncertainties),
            "output_bytes": observation.output_byte_length,
            "can_authorize_actions": False,
            "tool_surface": "none",
        },
        "usage": usage,
        "estimated_cost_cny": _format_cost(estimated_cost),
        "cost_source": "operator_supplied_per_million_token_rates",
        "exit_code": 0,
    }


def run_cli(
    argv: Sequence[str] | None = None,
    *,
    environment: Mapping[str, str] | None = None,
    executor: MiniMaxVisionSmokeExecutor = execute_minimax_vision_smoke,
    stdout: TextIO = sys.stdout,
    stderr: TextIO = sys.stderr,
) -> int:
    args = _create_parser().parse_args(argv)
    if not args.authorized:
        print(
            "M14-T4 MiniMax vision smoke refused: explicit one-time authorization is missing",
            file=stderr,
        )
        return _AUTHORIZATION_EXIT_CODE
    try:
        prices = MiniMaxCnyTokenPrices.from_strings(
            args.input_price_per_million_cny,
            args.output_price_per_million_cny,
        )
        settings = load_minimax_vision_settings(
            os.environ if environment is None else environment,
            authorized=True,
            declared_model=args.vision_model,
        )
        validate_minimax_vision_budget(settings, prices)
        summary = asyncio.run(executor(settings, prices))
    except MiniMaxVisionSmokeError as error:
        print(f"M14-T4 MiniMax vision smoke refused: {error}", file=stderr)
        return error.exit_code
    except Exception:
        print(
            "M14-T4 MiniMax vision smoke failed with an internal error",
            file=stderr,
        )
        return _ACCEPTANCE_EXIT_CODE
    print(json.dumps(summary, ensure_ascii=True, sort_keys=True), file=stdout)
    return 0


def main() -> int:
    return run_cli()


def _require_supported_proxy_environment(environment: Mapping[str, str]) -> None:
    uses_socks_proxy = False
    for name in _PROXY_ENVIRONMENT_NAMES:
        value = environment.get(name)
        if not isinstance(value, str) or not value.strip():
            continue
        if urlsplit(value.strip()).scheme.lower().startswith("socks"):
            uses_socks_proxy = True
            break
    if uses_socks_proxy and find_spec("socksio") is None:
        raise MiniMaxVisionSmokeError(
            "configured SOCKS proxy requires installed HTTP client support",
            exit_code=_CONFIGURATION_EXIT_CODE,
        )


def _positive_usage_value(value: int, field: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise MiniMaxVisionSmokeError(
            f"MiniMax vision usage {field} must be a positive integer",
            exit_code=_ACCEPTANCE_EXIT_CODE,
        )
    return value


def _format_cost(value: Decimal) -> str:
    return format(value.quantize(_COST_QUANTUM, rounding=ROUND_HALF_UP), "f")


def _create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the explicitly authorized M14-T4 MiniMax CN vision smoke.",
    )
    parser.add_argument("--authorized", action="store_true")
    parser.add_argument("--suite", choices=("M14",), default="M14")
    parser.add_argument("--vision-model")
    parser.add_argument("--input-price-per-million-cny", default="0")
    parser.add_argument("--output-price-per-million-cny", default="0")
    return parser


if __name__ == "__main__":
    raise SystemExit(main())
