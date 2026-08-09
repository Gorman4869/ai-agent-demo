from __future__ import annotations

import os
import re
import unicodedata
from collections.abc import Mapping
from decimal import Decimal
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)

from backend.app.domain.run import ModelProviderName, RuntimeName


_MCP_SERVER_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")


class SettingsError(ValueError):
    """Raised when server-owned configuration is invalid or incomplete."""


class RunBudgetSettings(BaseModel):
    """Server-owned bounds consumed incrementally by Runtime milestones."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    max_steps: int = Field(default=8, ge=1, le=64)
    max_model_calls: int = Field(default=8, ge=1, le=64)
    run_timeout_ms: int = Field(default=30_000, ge=100, le=120_000)
    model_timeout_ms: int = Field(default=20_000, ge=100, le=120_000)
    max_input_tokens: int = Field(default=16_000, ge=1, le=200_000)
    max_output_tokens: int = Field(default=2_000, ge=1, le=32_000)
    max_cost_usd: Decimal = Field(
        default=Decimal("0.25"),
        gt=Decimal("0"),
        le=Decimal("10"),
        allow_inf_nan=False,
    )
    max_model_retries: int = Field(default=2, ge=0, le=5)

    @model_validator(mode="after")
    def validate_timeout_order(self) -> RunBudgetSettings:
        if self.model_timeout_ms > self.run_timeout_ms:
            raise ValueError("model timeout must not exceed the run timeout")
        return self


class EmbeddingSettings(BaseModel):
    """Server-owned embedding selection, metadata, and request bounds."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    provider: Literal["offline", "openai"] = "offline"
    model: str | None = None
    revision: str | None = None
    dimensions: int = Field(default=3, ge=1, le=32_768)
    batch_size: int = Field(default=32, ge=1, le=2_048)
    cache_max_entries: int = Field(default=256, ge=1, le=100_000)
    request_timeout_ms: int = Field(default=20_000, ge=100, le=120_000)
    max_retries: int = Field(default=2, ge=0, le=5)

    @field_validator("model", mode="before")
    @classmethod
    def normalize_model(cls, value: object) -> object:
        return _normalize_optional_provider_label(
            value,
            "AI_AGENT_EMBEDDING_MODEL",
        )

    @field_validator("revision", mode="before")
    @classmethod
    def normalize_revision(cls, value: object) -> object:
        return _normalize_optional_provider_label(
            value,
            "AI_AGENT_EMBEDDING_REVISION",
        )

    def safe_summary(self) -> dict[str, object]:
        return {
            "provider": self.provider,
            "model_configured": self.model is not None,
            "revision_configured": self.revision is not None,
            "dimensions": self.dimensions,
            "batch_size": self.batch_size,
            "cache_max_entries": self.cache_max_entries,
            "request_timeout_ms": self.request_timeout_ms,
            "max_retries": self.max_retries,
        }


class McpClientSettings(BaseModel):
    """Server-owned MCP selectors and connection bounds."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    server_ids: tuple[str, ...] = ()
    startup_timeout_ms: int = Field(default=5_000, ge=100, le=30_000)
    request_timeout_ms: int = Field(default=5_000, ge=100, le=30_000)

    @field_validator("server_ids")
    @classmethod
    def validate_server_ids(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) > 8:
            raise ValueError("at most 8 MCP servers may be enabled")
        if len(value) != len(set(value)):
            raise ValueError("MCP server IDs must be unique")
        if any(
            _MCP_SERVER_ID_PATTERN.fullmatch(server_id) is None
            for server_id in value
        ):
            raise ValueError("MCP server ID has an invalid format")
        return value


class PersistenceSettings(BaseModel):
    """Server-owned persistence selection and secret connection data."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    backend: Literal["memory", "postgres"] = "memory"
    postgres_dsn: SecretStr | None = Field(
        default=None,
        repr=False,
        exclude=True,
    )

    @field_validator("postgres_dsn", mode="before")
    @classmethod
    def normalize_postgres_dsn(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, SecretStr):
            raw_value = value.get_secret_value()
        elif isinstance(value, str):
            raw_value = value
        else:
            return value
        normalized = raw_value.strip()
        if not normalized:
            return None
        if len(normalized) > 2_048 or any(
            _is_control_character(character) for character in normalized
        ):
            raise ValueError("AI_AGENT_POSTGRES_DSN has an invalid format")
        return SecretStr(normalized)

    @model_validator(mode="after")
    def validate_postgres_gate(self) -> PersistenceSettings:
        if self.backend != "postgres":
            return self
        if self.postgres_dsn is None:
            raise ValueError("postgres persistence requires AI_AGENT_POSTGRES_DSN")
        from psycopg import ProgrammingError
        from psycopg.conninfo import conninfo_to_dict

        try:
            conninfo_to_dict(self.postgres_dsn.get_secret_value())
        except ProgrammingError:
            raise ValueError("AI_AGENT_POSTGRES_DSN has an invalid format") from None
        return self

    def safe_summary(self) -> dict[str, object]:
        return {
            "backend": self.backend,
            "postgres_dsn_configured": self.postgres_dsn is not None,
        }


class Settings(BaseModel):
    """Immutable application configuration parsed from explicit environment data.

    Merely configuring an API key never enables network access. The OpenAI
    provider is valid only when the runtime, provider, online switch, key and
    model form one complete server-owned configuration.
    """

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    runtime: RuntimeName = "manual"
    model_provider: ModelProviderName = "mock"
    online_enabled: bool = False
    trace_include_sensitive: bool = False
    openai_api_key: SecretStr | None = Field(
        default=None,
        repr=False,
        exclude=True,
    )
    openai_model: str | None = None
    budget: RunBudgetSettings = Field(default_factory=RunBudgetSettings)
    embedding: EmbeddingSettings = Field(default_factory=EmbeddingSettings)
    mcp: McpClientSettings = Field(default_factory=McpClientSettings)
    persistence: PersistenceSettings = Field(default_factory=PersistenceSettings)

    @field_validator("openai_api_key", mode="before")
    @classmethod
    def normalize_openai_api_key(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, SecretStr):
            raw_value = value.get_secret_value()
        elif isinstance(value, str):
            raw_value = value
        else:
            return value
        normalized = raw_value.strip()
        if not normalized:
            return None
        if len(normalized) > 512 or any(
            _is_control_or_whitespace(character) for character in normalized
        ):
            raise ValueError("OPENAI_API_KEY has an invalid format")
        return SecretStr(normalized)

    @field_validator("openai_model", mode="before")
    @classmethod
    def normalize_openai_model(cls, value: object) -> object:
        if value is None or not isinstance(value, str):
            return value
        normalized = value.strip()
        if not normalized:
            return None
        if len(normalized) > 200 or any(
            _is_control_or_whitespace(character) for character in normalized
        ):
            raise ValueError("OPENAI_MODEL has an invalid format")
        return normalized

    @model_validator(mode="after")
    def validate_provider_gate(self) -> Settings:
        if self.trace_include_sensitive:
            raise ValueError("sensitive trace content is disabled")
        if self.model_provider == "openai":
            if not self.online_enabled:
                raise ValueError("openai provider requires the explicit online switch")
            if self.runtime not in {"agents_sdk", "langgraph"}:
                raise ValueError("openai provider requires an online-capable runtime")
            if self.openai_api_key is None:
                raise ValueError("openai provider requires OPENAI_API_KEY")
            if self.openai_model is None:
                raise ValueError("openai provider requires OPENAI_MODEL")
        else:
            if self.runtime == "agents_sdk":
                raise ValueError("agents_sdk runtime requires the openai provider")
        if self.embedding.provider == "openai":
            if not self.online_enabled:
                raise ValueError(
                    "openai embedding requires the explicit online switch"
                )
            if self.openai_api_key is None:
                raise ValueError("openai embedding requires OPENAI_API_KEY")
            if self.embedding.model is None:
                raise ValueError(
                    "openai embedding requires AI_AGENT_EMBEDDING_MODEL"
                )
            if self.embedding.revision is None:
                raise ValueError(
                    "openai embedding requires AI_AGENT_EMBEDDING_REVISION"
                )
        if (
            self.online_enabled
            and self.model_provider != "openai"
            and self.embedding.provider != "openai"
        ):
            raise ValueError("online switch requires an online provider")
        return self

    @property
    def online_provider_enabled(self) -> bool:
        return self.model_provider == "openai" and self.online_enabled

    @property
    def online_embedding_enabled(self) -> bool:
        return self.embedding.provider == "openai" and self.online_enabled

    def safe_summary(self) -> dict[str, object]:
        """Return fields suitable for logs without exposing provider secrets."""
        return {
            "runtime": self.runtime,
            "model_provider": self.model_provider,
            "online_enabled": self.online_enabled,
            "trace_include_sensitive": self.trace_include_sensitive,
            "openai_api_key_configured": self.openai_api_key is not None,
            "openai_model_configured": self.openai_model is not None,
            "budget": self.budget.model_dump(mode="json"),
            "embedding": self.embedding.safe_summary(),
            "mcp": self.mcp.model_dump(mode="json"),
            "persistence": self.persistence.safe_summary(),
        }

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
    ) -> Settings:
        values = os.environ if environment is None else environment
        try:
            settings = cls(
                runtime=_read_name(values, "AI_AGENT_RUNTIME", "manual"),
                model_provider=_read_name(
                    values,
                    "AI_AGENT_MODEL_PROVIDER",
                    "mock",
                ),
                online_enabled=_read_bool(
                    values,
                    "AI_AGENT_ONLINE_ENABLED",
                    False,
                ),
                trace_include_sensitive=_read_bool(
                    values,
                    "AI_AGENT_TRACE_INCLUDE_SENSITIVE",
                    False,
                ),
                openai_api_key=_read_optional_secret(values, "OPENAI_API_KEY"),
                openai_model=_read_optional_text(values, "OPENAI_MODEL"),
                budget=RunBudgetSettings(
                    max_steps=_read_int(values, "AI_AGENT_MAX_STEPS", 8),
                    max_model_calls=_read_int(
                        values,
                        "AI_AGENT_MAX_MODEL_CALLS",
                        8,
                    ),
                    run_timeout_ms=_read_int(
                        values,
                        "AI_AGENT_RUN_TIMEOUT_MS",
                        30_000,
                    ),
                    model_timeout_ms=_read_int(
                        values,
                        "AI_AGENT_MODEL_TIMEOUT_MS",
                        20_000,
                    ),
                    max_input_tokens=_read_int(
                        values,
                        "AI_AGENT_MAX_INPUT_TOKENS",
                        16_000,
                    ),
                    max_output_tokens=_read_int(
                        values,
                        "AI_AGENT_MAX_OUTPUT_TOKENS",
                        2_000,
                    ),
                    max_cost_usd=_read_decimal(
                        values,
                        "AI_AGENT_MAX_COST_USD",
                        Decimal("0.25"),
                    ),
                    max_model_retries=_read_int(
                        values,
                        "AI_AGENT_MAX_MODEL_RETRIES",
                        2,
                    ),
                ),
                embedding=EmbeddingSettings(
                    provider=_read_name(
                        values,
                        "AI_AGENT_EMBEDDING_PROVIDER",
                        "offline",
                    ),
                    model=_read_optional_text(
                        values,
                        "AI_AGENT_EMBEDDING_MODEL",
                    ),
                    revision=_read_optional_text(
                        values,
                        "AI_AGENT_EMBEDDING_REVISION",
                    ),
                    dimensions=_read_int(
                        values,
                        "AI_AGENT_EMBEDDING_DIMENSIONS",
                        3,
                    ),
                    batch_size=_read_int(
                        values,
                        "AI_AGENT_EMBEDDING_BATCH_SIZE",
                        32,
                    ),
                    cache_max_entries=_read_int(
                        values,
                        "AI_AGENT_EMBEDDING_CACHE_MAX_ENTRIES",
                        256,
                    ),
                    request_timeout_ms=_read_int(
                        values,
                        "AI_AGENT_EMBEDDING_REQUEST_TIMEOUT_MS",
                        20_000,
                    ),
                    max_retries=_read_int(
                        values,
                        "AI_AGENT_EMBEDDING_MAX_RETRIES",
                        2,
                    ),
                ),
                mcp=McpClientSettings(
                    server_ids=_read_csv_names(
                        values,
                        "AI_AGENT_MCP_SERVERS",
                    ),
                    startup_timeout_ms=_read_int(
                        values,
                        "AI_AGENT_MCP_STARTUP_TIMEOUT_MS",
                        5_000,
                    ),
                    request_timeout_ms=_read_int(
                        values,
                        "AI_AGENT_MCP_REQUEST_TIMEOUT_MS",
                        5_000,
                    ),
                ),
                persistence=PersistenceSettings(
                    backend=_read_name(
                        values,
                        "AI_AGENT_PERSISTENCE",
                        "memory",
                    ),
                    postgres_dsn=_read_optional_secret(
                        values,
                        "AI_AGENT_POSTGRES_DSN",
                    ),
                ),
            )
        except SettingsError:
            raise
        except ValidationError as error:
            raise SettingsError(_safe_validation_message(error)) from None
        return settings


def _read_name(
    environment: Mapping[str, str],
    name: str,
    default: str,
) -> str:
    raw_value = environment.get(name)
    if raw_value is None:
        return default
    value = raw_value.strip().lower()
    if not value:
        raise SettingsError(f"{name} must not be empty")
    return value


def _read_bool(
    environment: Mapping[str, str],
    name: str,
    default: bool,
) -> bool:
    raw_value = environment.get(name)
    if raw_value is None:
        return default
    value = raw_value.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    raise SettingsError(f"{name} must be true or false")


def _read_int(
    environment: Mapping[str, str],
    name: str,
    default: int,
) -> int:
    raw_value = environment.get(name)
    if raw_value is None:
        return default
    try:
        return int(raw_value.strip())
    except ValueError:
        raise SettingsError(f"{name} must be an integer") from None


def _read_decimal(
    environment: Mapping[str, str],
    name: str,
    default: Decimal,
) -> Decimal:
    raw_value = environment.get(name)
    if raw_value is None:
        return default
    try:
        return Decimal(raw_value.strip())
    except ArithmeticError:
        raise SettingsError(f"{name} must be a decimal number") from None


def _read_optional_text(
    environment: Mapping[str, str],
    name: str,
) -> str | None:
    raw_value = environment.get(name)
    if raw_value is None:
        return None
    value = raw_value.strip()
    return value or None


def _read_optional_secret(
    environment: Mapping[str, str],
    name: str,
) -> SecretStr | None:
    value = _read_optional_text(environment, name)
    return SecretStr(value) if value is not None else None


def _normalize_optional_provider_label(
    value: object,
    name: str,
) -> object:
    if value is None or not isinstance(value, str):
        return value
    normalized = value.strip()
    if not normalized:
        return None
    if len(normalized) > 200 or any(
        _is_control_or_whitespace(character) for character in normalized
    ):
        raise ValueError(f"{name} has an invalid format")
    return normalized


def _read_csv_names(
    environment: Mapping[str, str],
    name: str,
) -> tuple[str, ...]:
    raw_value = environment.get(name)
    if raw_value is None or not raw_value.strip():
        return ()
    values = tuple(part.strip().lower() for part in raw_value.split(","))
    if any(not value for value in values):
        raise SettingsError(f"{name} must be a comma-separated name list")
    return values


def _safe_validation_message(error: ValidationError) -> str:
    fields = sorted(
        {
            ".".join(str(part) for part in item["loc"]) or "settings"
            for item in error.errors(include_url=False, include_input=False)
        }
    )
    return f"invalid application settings: {', '.join(fields)}"


def _is_control_or_whitespace(character: str) -> bool:
    return character.isspace() or unicodedata.category(character).startswith("C")


def _is_control_character(character: str) -> bool:
    return unicodedata.category(character).startswith("C")
