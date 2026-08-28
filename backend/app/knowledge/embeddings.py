from __future__ import annotations

import math
import re
from collections import OrderedDict
from dataclasses import dataclass
from hashlib import sha256
from json import dumps
from threading import Lock
from typing import Protocol, Sequence


_MAX_METADATA_TEXT = 200
_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]")
_CACHE_KEY_VERSION = 1
_CACHE_KEY_PATTERN = re.compile(
    rf"embedding:v{_CACHE_KEY_VERSION}:[0-9a-f]{{64}}"
)


class EmbeddingError(RuntimeError):
    code = "embedding_error"

    def __init__(self) -> None:
        super().__init__(self.code)


class EmbeddingInputError(EmbeddingError):
    code = "embedding_input_invalid"


class EmbeddingBatchError(EmbeddingError):
    code = "embedding_batch_invalid"


class EmbeddingDimensionError(EmbeddingError):
    code = "embedding_dimension_mismatch"


class EmbeddingValueError(EmbeddingError):
    code = "embedding_value_invalid"


class EmbeddingMetadataError(EmbeddingError):
    code = "embedding_metadata_changed"


class EmbeddingAuthenticationError(EmbeddingError):
    code = "embedding_provider_authentication_failed"


class EmbeddingClientConfigurationError(EmbeddingError):
    code = "embedding_provider_client_configuration_invalid"


class EmbeddingQuotaError(EmbeddingError):
    code = "embedding_provider_quota_or_rate_limited"


class EmbeddingProviderRequestError(EmbeddingError):
    code = "embedding_provider_request_invalid"


class EmbeddingUsageError(EmbeddingError):
    code = "embedding_usage_invalid"


class RetryableEmbeddingError(EmbeddingError):
    code = "embedding_provider_temporarily_unavailable"


class EmbeddingRetryExhaustedError(EmbeddingError):
    code = "embedding_retry_exhausted"


@dataclass(frozen=True)
class EmbeddingMetadata:
    provider: str
    model: str
    revision: str
    dimensions: int

    def __post_init__(self) -> None:
        for name in ("provider", "model", "revision"):
            value = getattr(self, name)
            normalized = value.strip() if isinstance(value, str) else ""
            if (
                not normalized
                or len(normalized) > _MAX_METADATA_TEXT
                or any(
                    ord(character) < 32 or ord(character) == 127
                    for character in normalized
                )
            ):
                raise ValueError(f"embedding {name} is invalid")
            object.__setattr__(self, name, normalized)
        if (
            not isinstance(self.dimensions, int)
            or isinstance(self.dimensions, bool)
            or self.dimensions < 1
        ):
            raise ValueError("embedding dimensions must be positive")


@dataclass(frozen=True)
class EmbeddingUsage:
    input_tokens: int
    total_tokens: int

    def __post_init__(self) -> None:
        if (
            not isinstance(self.input_tokens, int)
            or isinstance(self.input_tokens, bool)
            or self.input_tokens < 0
            or not isinstance(self.total_tokens, int)
            or isinstance(self.total_tokens, bool)
            or self.total_tokens < self.input_tokens
        ):
            raise ValueError("embedding usage must contain valid token counts")


class EmbeddingProvider(Protocol):
    @property
    def metadata(self) -> EmbeddingMetadata: ...

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> Sequence[Sequence[float]]: ...


class EmbeddingCache(Protocol):
    def get(self, key: str) -> Sequence[float] | None: ...

    def put(self, key: str, vector: Sequence[float]) -> None: ...


class EmbeddingModel(Protocol):
    @property
    def metadata(self) -> EmbeddingMetadata: ...

    def embed(self, text: str) -> Sequence[float]: ...

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> Sequence[Sequence[float]]: ...


class InMemoryEmbeddingCache:
    """Bounded process-local cache for validated embedding vectors."""

    def __init__(self, *, max_entries: int = 256) -> None:
        if (
            not isinstance(max_entries, int)
            or isinstance(max_entries, bool)
            or max_entries < 1
        ):
            raise ValueError("embedding cache max_entries must be positive")
        self._max_entries = max_entries
        self._entries: OrderedDict[str, tuple[float, ...]] = OrderedDict()
        self._lock = Lock()

    def get(self, key: str) -> tuple[float, ...] | None:
        _validate_cache_key(key)
        with self._lock:
            vector = self._entries.get(key)
            if vector is not None:
                self._entries.move_to_end(key)
            return vector

    def put(self, key: str, vector: Sequence[float]) -> None:
        _validate_cache_key(key)
        stored = tuple(vector)
        with self._lock:
            self._entries[key] = stored
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)


class RetryingEmbeddingProvider:
    """Retry only explicitly classified transient provider failures."""

    def __init__(
        self,
        provider: EmbeddingProvider,
        *,
        max_retries: int = 2,
    ) -> None:
        if (
            not isinstance(max_retries, int)
            or isinstance(max_retries, bool)
            or max_retries < 0
        ):
            raise ValueError("embedding max_retries must not be negative")
        self._provider = provider
        self._metadata = provider.metadata
        self._max_retries = max_retries

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._metadata

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> Sequence[Sequence[float]]:
        batch = tuple(texts)
        for retry_attempt in range(self._max_retries + 1):
            self._ensure_metadata()
            try:
                vectors = self._provider.embed_batch(batch)
            except RetryableEmbeddingError:
                self._ensure_metadata()
                if retry_attempt >= self._max_retries:
                    raise EmbeddingRetryExhaustedError() from None
                continue
            self._ensure_metadata()
            return vectors
        raise AssertionError("embedding retry loop exhausted unexpectedly")

    def _ensure_metadata(self) -> None:
        if self._provider.metadata != self._metadata:
            raise EmbeddingMetadataError()


class BatchingEmbeddingModel:
    """Validate and split arbitrary input into provider-owned batches."""

    def __init__(
        self,
        provider: EmbeddingProvider,
        *,
        batch_size: int = 32,
        cache: EmbeddingCache | None = None,
    ) -> None:
        if (
            not isinstance(batch_size, int)
            or isinstance(batch_size, bool)
            or batch_size < 1
        ):
            raise ValueError("embedding batch_size must be positive")
        self._provider = provider
        self._metadata = provider.metadata
        self._batch_size = batch_size
        self._cache = cache

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._metadata

    def embed(self, text: str) -> tuple[float, ...]:
        return self.embed_batch((text,))[0]

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        normalized = tuple(_normalize_text(text) for text in texts)
        if not normalized:
            return ()

        if self._cache is None:
            return self._embed_provider_batches(normalized)

        keys = tuple(
            build_embedding_cache_key(self._metadata, text)
            for text in normalized
        )
        resolved: dict[str, tuple[float, ...]] = {}
        missing: dict[str, str] = {}
        for key, text in zip(keys, normalized):
            if key in resolved or key in missing:
                continue
            cached = self._cache.get(key)
            if cached is None:
                missing[key] = text
            else:
                resolved[key] = _validate_vector(
                    cached,
                    self._metadata.dimensions,
                )

        new_entries: tuple[tuple[str, tuple[float, ...]], ...] = ()
        if missing:
            vectors = self._embed_provider_batches(tuple(missing.values()))
            new_entries = tuple(zip(missing, vectors))
            resolved.update(new_entries)

        for key, vector in new_entries:
            self._cache.put(key, vector)
        return tuple(resolved[key] for key in keys)

    def _embed_provider_batches(
        self,
        normalized: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(normalized), self._batch_size):
            self._ensure_metadata()
            batch = normalized[start : start + self._batch_size]
            provided = tuple(self._provider.embed_batch(batch))
            self._ensure_metadata()
            if len(provided) != len(batch):
                raise EmbeddingBatchError()
            vectors.extend(
                _validate_vector(vector, self._metadata.dimensions)
                for vector in provided
            )
        return tuple(vectors)

    def _ensure_metadata(self) -> None:
        if self._provider.metadata != self._metadata:
            raise EmbeddingMetadataError()


class DeterministicEmbeddingProvider:
    """Standard-library provider for deterministic offline course paths."""

    def __init__(self, *, dimensions: int = 3) -> None:
        self._metadata = EmbeddingMetadata(
            provider="offline",
            model="sha256-token-hash",
            revision="v1",
            dimensions=dimensions,
        )

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._metadata

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        return tuple(self._embed_one(_normalize_text(text)) for text in texts)

    def _embed_one(self, text: str) -> tuple[float, ...]:
        values = [0.0] * self._metadata.dimensions
        tokens = _TOKEN_PATTERN.findall(text.lower()) or [text.lower()]
        for token in tokens:
            digest = sha256(token.encode("utf-8")).digest()
            bucket = int.from_bytes(digest[:4], "big") % len(values)
            values[bucket] += -1.0 if digest[4] & 1 else 1.0

        norm = math.sqrt(sum(value * value for value in values))
        if norm == 0:
            digest = sha256(text.encode("utf-8")).digest()
            values[int.from_bytes(digest[:4], "big") % len(values)] = 1.0
            norm = 1.0
        return tuple(value / norm for value in values)


def create_deterministic_embedding_model(
    *,
    dimensions: int = 3,
    batch_size: int = 32,
    cache: EmbeddingCache | None = None,
) -> BatchingEmbeddingModel:
    return BatchingEmbeddingModel(
        DeterministicEmbeddingProvider(dimensions=dimensions),
        batch_size=batch_size,
        cache=cache,
    )


def build_embedding_cache_key(
    metadata: EmbeddingMetadata,
    text: str,
) -> str:
    normalized = _normalize_text(text)
    payload = {
        "dimensions": metadata.dimensions,
        "model": metadata.model,
        "provider": metadata.provider,
        "revision": metadata.revision,
        "text_sha256": sha256(normalized.encode("utf-8")).hexdigest(),
        "version": _CACHE_KEY_VERSION,
    }
    canonical = dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    )
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    return f"embedding:v{_CACHE_KEY_VERSION}:{digest}"


def _normalize_text(text: str) -> str:
    if not isinstance(text, str):
        raise EmbeddingInputError()
    normalized = re.sub(r"\s+", " ", text).strip()
    if not normalized:
        raise EmbeddingInputError()
    return normalized


def _validate_vector(
    vector: Sequence[float],
    dimensions: int,
) -> tuple[float, ...]:
    try:
        values = tuple(float(value) for value in vector)
    except (TypeError, ValueError):
        raise EmbeddingValueError() from None
    if len(values) != dimensions:
        raise EmbeddingDimensionError()
    if not all(math.isfinite(value) for value in values):
        raise EmbeddingValueError()
    return values


def _validate_cache_key(key: str) -> None:
    if not isinstance(key, str) or _CACHE_KEY_PATTERN.fullmatch(key) is None:
        raise ValueError("embedding cache key is invalid")


__all__ = [
    "BatchingEmbeddingModel",
    "DeterministicEmbeddingProvider",
    "EmbeddingAuthenticationError",
    "EmbeddingBatchError",
    "EmbeddingCache",
    "EmbeddingClientConfigurationError",
    "EmbeddingDimensionError",
    "EmbeddingError",
    "EmbeddingInputError",
    "EmbeddingMetadata",
    "EmbeddingMetadataError",
    "EmbeddingModel",
    "EmbeddingProvider",
    "EmbeddingProviderRequestError",
    "EmbeddingQuotaError",
    "EmbeddingRetryExhaustedError",
    "EmbeddingUsage",
    "EmbeddingUsageError",
    "EmbeddingValueError",
    "InMemoryEmbeddingCache",
    "RetryableEmbeddingError",
    "RetryingEmbeddingProvider",
    "build_embedding_cache_key",
    "create_deterministic_embedding_model",
]
