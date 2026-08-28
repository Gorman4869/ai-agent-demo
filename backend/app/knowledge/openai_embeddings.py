from __future__ import annotations

import unicodedata
from collections.abc import Callable, Sequence
from contextlib import contextmanager
from typing import ContextManager, Literal, Protocol, cast

import openai

from .embeddings import (
    EmbeddingAuthenticationError,
    EmbeddingBatchError,
    EmbeddingClientConfigurationError,
    EmbeddingMetadata,
    EmbeddingProviderRequestError,
    EmbeddingQuotaError,
    EmbeddingUsage,
    EmbeddingUsageError,
    RetryableEmbeddingError,
)


class OpenAIEmbeddingsEndpoint(Protocol):
    def create(
        self,
        *,
        input: Sequence[str],
        model: str,
        dimensions: int,
        encoding_format: Literal["float"],
    ) -> object: ...


class OpenAIEmbeddingClient(Protocol):
    @property
    def embeddings(self) -> OpenAIEmbeddingsEndpoint: ...


OpenAIEmbeddingClientFactory = Callable[
    [],
    ContextManager[OpenAIEmbeddingClient],
]
EmbeddingUsageSink = Callable[[EmbeddingUsage], None]


class OpenAIEmbeddingProvider:
    """Map the public OpenAI Embeddings API to the knowledge Provider contract."""

    def __init__(
        self,
        client_factory: OpenAIEmbeddingClientFactory,
        *,
        provider_name: str = "openai",
        model: str,
        revision: str,
        dimensions: int,
        usage_sink: EmbeddingUsageSink | None = None,
    ) -> None:
        self._client_factory = client_factory
        self._metadata = EmbeddingMetadata(
            provider=_required_label(provider_name, "provider"),
            model=_required_label(model, "model"),
            revision=_required_label(revision, "revision"),
            dimensions=dimensions,
        )
        self._usage_sink = usage_sink

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._metadata

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[Sequence[float], ...]:
        batch = tuple(texts)
        if not batch:
            return ()
        try:
            with self._client_factory() as client:
                response = client.embeddings.create(
                    input=batch,
                    model=self._metadata.model,
                    dimensions=self._metadata.dimensions,
                    encoding_format="float",
                )
        except (
            openai.APIConnectionError,
            openai.InternalServerError,
        ):
            raise RetryableEmbeddingError() from None
        except ImportError:
            raise EmbeddingClientConfigurationError() from None
        except (
            openai.AuthenticationError,
            openai.PermissionDeniedError,
        ):
            raise EmbeddingAuthenticationError() from None
        except openai.RateLimitError:
            raise EmbeddingQuotaError() from None
        except openai.APIResponseValidationError:
            raise EmbeddingBatchError() from None
        except openai.APIStatusError:
            raise EmbeddingProviderRequestError() from None

        vectors = _ordered_vectors(response, expected_count=len(batch))
        usage = _validated_usage(response)
        if self._usage_sink is not None:
            self._usage_sink(usage)
        return vectors


def create_openai_embedding_client_factory(
    *,
    api_key: str,
    timeout_ms: int,
    base_url: str | None = None,
) -> OpenAIEmbeddingClientFactory:
    """Create explicit per-batch SDK clients with SDK retries disabled."""

    resolved_key = _required_label(api_key, "api_key", max_length=512)
    if (
        not isinstance(timeout_ms, int)
        or isinstance(timeout_ms, bool)
        or timeout_ms < 1
    ):
        raise ValueError("timeout_ms must be a positive integer")

    client_options: dict[str, object] = {
        "api_key": resolved_key,
        "timeout": timeout_ms / 1_000,
        "max_retries": 0,
    }
    if base_url is not None:
        client_options["base_url"] = _required_label(base_url, "base_url")

    @contextmanager
    def create_client():
        client = openai.OpenAI(**client_options)
        try:
            yield cast(OpenAIEmbeddingClient, client)
        finally:
            client.close()

    return create_client


def _ordered_vectors(
    response: object,
    *,
    expected_count: int,
) -> tuple[Sequence[float], ...]:
    data = getattr(response, "data", None)
    if isinstance(data, (str, bytes)):
        raise EmbeddingBatchError()
    try:
        items = tuple(data)
    except TypeError:
        raise EmbeddingBatchError() from None
    if len(items) != expected_count:
        raise EmbeddingBatchError()

    ordered: list[Sequence[float] | None] = [None] * expected_count
    for item in items:
        index = getattr(item, "index", None)
        embedding = getattr(item, "embedding", None)
        if (
            not isinstance(index, int)
            or isinstance(index, bool)
            or index < 0
            or index >= expected_count
            or ordered[index] is not None
            or isinstance(embedding, (str, bytes))
        ):
            raise EmbeddingBatchError()
        try:
            ordered[index] = cast(Sequence[float], tuple(embedding))
        except TypeError:
            raise EmbeddingBatchError() from None
    if any(vector is None for vector in ordered):
        raise EmbeddingBatchError()
    return tuple(cast(Sequence[float], vector) for vector in ordered)


def _validated_usage(response: object) -> EmbeddingUsage:
    usage = getattr(response, "usage", None)
    try:
        return EmbeddingUsage(
            input_tokens=getattr(usage, "prompt_tokens"),
            total_tokens=getattr(usage, "total_tokens"),
        )
    except (AttributeError, TypeError, ValueError):
        raise EmbeddingUsageError() from None


def _required_label(
    value: object,
    name: str,
    *,
    max_length: int = 200,
) -> str:
    normalized = value.strip() if isinstance(value, str) else ""
    if (
        not normalized
        or len(normalized) > max_length
        or any(
            character.isspace()
            or unicodedata.category(character).startswith("C")
            for character in normalized
        )
    ):
        raise ValueError(f"{name} is invalid")
    return normalized


__all__ = [
    "EmbeddingUsageSink",
    "OpenAIEmbeddingClient",
    "OpenAIEmbeddingClientFactory",
    "OpenAIEmbeddingProvider",
    "create_openai_embedding_client_factory",
]
