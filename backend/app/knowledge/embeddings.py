from __future__ import annotations

import math
import re
from dataclasses import dataclass
from hashlib import sha256
from typing import Protocol, Sequence


_MAX_METADATA_TEXT = 200
_TOKEN_PATTERN = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]")


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


class EmbeddingProvider(Protocol):
    @property
    def metadata(self) -> EmbeddingMetadata: ...

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> Sequence[Sequence[float]]: ...


class EmbeddingModel(Protocol):
    @property
    def metadata(self) -> EmbeddingMetadata: ...

    def embed(self, text: str) -> Sequence[float]: ...

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> Sequence[Sequence[float]]: ...


class BatchingEmbeddingModel:
    """Validate and split arbitrary input into provider-owned batches."""

    def __init__(
        self,
        provider: EmbeddingProvider,
        *,
        batch_size: int = 32,
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

        vectors: list[tuple[float, ...]] = []
        for start in range(0, len(normalized), self._batch_size):
            if self._provider.metadata != self._metadata:
                raise EmbeddingMetadataError()
            batch = normalized[start : start + self._batch_size]
            provided = tuple(self._provider.embed_batch(batch))
            if len(provided) != len(batch):
                raise EmbeddingBatchError()
            vectors.extend(
                _validate_vector(vector, self._metadata.dimensions)
                for vector in provided
            )
        return tuple(vectors)


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
) -> BatchingEmbeddingModel:
    return BatchingEmbeddingModel(
        DeterministicEmbeddingProvider(dimensions=dimensions),
        batch_size=batch_size,
    )


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


__all__ = [
    "BatchingEmbeddingModel",
    "DeterministicEmbeddingProvider",
    "EmbeddingBatchError",
    "EmbeddingDimensionError",
    "EmbeddingError",
    "EmbeddingInputError",
    "EmbeddingMetadata",
    "EmbeddingMetadataError",
    "EmbeddingModel",
    "EmbeddingProvider",
    "EmbeddingValueError",
    "create_deterministic_embedding_model",
]
