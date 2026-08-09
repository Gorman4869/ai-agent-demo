from __future__ import annotations

import json
import unittest
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from unittest.mock import Mock, patch

import httpx
import openai

from backend.app.container import create_embedding_model
from backend.app.knowledge import (
    EmbeddingAuthenticationError,
    EmbeddingBatchError,
    EmbeddingDimensionError,
    EmbeddingProviderRequestError,
    EmbeddingQuotaError,
    EmbeddingUsage,
    EmbeddingUsageError,
    OpenAIEmbeddingClient,
    OpenAIEmbeddingClientFactory,
    OpenAIEmbeddingProvider,
    create_openai_embedding_client_factory,
)
from backend.app.settings import Settings


def _online_embedding_settings(*, max_retries: int = 1) -> Settings:
    return Settings.from_environment(
        {
            "AI_AGENT_ONLINE_ENABLED": "true",
            "OPENAI_API_KEY": "offline-sdk-fixture",
            "AI_AGENT_EMBEDDING_PROVIDER": "openai",
            "AI_AGENT_EMBEDDING_MODEL": "configured-embedding",
            "AI_AGENT_EMBEDDING_REVISION": "course-v1",
            "AI_AGENT_EMBEDDING_DIMENSIONS": "3",
            "AI_AGENT_EMBEDDING_BATCH_SIZE": "2",
            "AI_AGENT_EMBEDDING_CACHE_MAX_ENTRIES": "8",
            "AI_AGENT_EMBEDDING_REQUEST_TIMEOUT_MS": "1500",
            "AI_AGENT_EMBEDDING_MAX_RETRIES": str(max_retries),
        }
    )


def _sdk_client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> OpenAIEmbeddingClientFactory:
    transport = httpx.MockTransport(handler)

    @contextmanager
    def create_client() -> Iterator[OpenAIEmbeddingClient]:
        client = openai.OpenAI(
            api_key="offline-sdk-fixture",
            max_retries=0,
            http_client=httpx.Client(transport=transport),
        )
        try:
            yield client
        finally:
            client.close()

    return create_client


def _success_response(
    request: httpx.Request,
    indexed_vectors: Sequence[tuple[int, Sequence[float]]],
    *,
    prompt_tokens: int = 4,
    total_tokens: int = 4,
) -> httpx.Response:
    return httpx.Response(
        200,
        request=request,
        json={
            "object": "list",
            "data": [
                {
                    "object": "embedding",
                    "index": index,
                    "embedding": list(vector),
                }
                for index, vector in indexed_vectors
            ],
            "model": "configured-embedding",
            "usage": {
                "prompt_tokens": prompt_tokens,
                "total_tokens": total_tokens,
            },
        },
    )


class OpenAIEmbeddingAdapterTest(unittest.TestCase):
    def test_empty_provider_batch_skips_sdk_client(self) -> None:
        client_factory = Mock()
        provider = OpenAIEmbeddingProvider(
            client_factory,
            model="configured-embedding",
            revision="course-v1",
            dimensions=3,
        )

        self.assertEqual((), provider.embed_batch(()))
        client_factory.assert_not_called()

    def test_real_sdk_api_maps_request_order_usage_and_cache(self) -> None:
        requests: list[dict[str, object]] = []
        usages: list[EmbeddingUsage] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return _success_response(
                request,
                (
                    (1, (0.0, 1.0, 0.0)),
                    (0, (1.0, 0.0, 0.0)),
                ),
            )

        model = create_embedding_model(
            _online_embedding_settings(),
            openai_client_factory=_sdk_client_factory(handler),
            usage_sink=usages.append,
        )

        first = model.embed_batch(("first", "second"))
        second = model.embed_batch((" first ", "second"))

        self.assertEqual(
            ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
            first,
        )
        self.assertEqual(first, second)
        self.assertEqual(
            [
                {
                    "input": ["first", "second"],
                    "model": "configured-embedding",
                    "dimensions": 3,
                    "encoding_format": "float",
                }
            ],
            requests,
        )
        self.assertEqual([EmbeddingUsage(input_tokens=4, total_tokens=4)], usages)

    def test_transient_sdk_error_retries_same_batch_then_succeeds(self) -> None:
        requests: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            if len(requests) == 1:
                return httpx.Response(
                    500,
                    request=request,
                    json={"error": {"message": "private provider failure"}},
                )
            return _success_response(request, ((0, (1.0, 0.0, 0.0)),))

        model = create_embedding_model(
            _online_embedding_settings(max_retries=1),
            openai_client_factory=_sdk_client_factory(handler),
        )

        self.assertEqual((1.0, 0.0, 0.0), model.embed("sensitive input"))
        self.assertEqual(2, len(requests))
        self.assertEqual(requests[0], requests[1])

    def test_non_retryable_sdk_errors_are_stable_and_content_free(self) -> None:
        cases = (
            (401, EmbeddingAuthenticationError, "embedding_provider_authentication_failed"),
            (429, EmbeddingQuotaError, "embedding_provider_quota_or_rate_limited"),
            (400, EmbeddingProviderRequestError, "embedding_provider_request_invalid"),
        )

        for status, error_type, error_code in cases:
            with self.subTest(status=status):
                calls = 0

                def handler(request: httpx.Request) -> httpx.Response:
                    nonlocal calls
                    calls += 1
                    return httpx.Response(
                        status,
                        request=request,
                        json={
                            "error": {
                                "message": "private provider response",
                                "type": "fixture_error",
                            }
                        },
                    )

                model = create_embedding_model(
                    _online_embedding_settings(max_retries=3),
                    openai_client_factory=_sdk_client_factory(handler),
                )
                raw_text = "private customer input"

                with self.assertRaises(error_type) as context:
                    model.embed(raw_text)

                self.assertEqual(error_code, str(context.exception))
                self.assertNotIn(raw_text, str(context.exception))
                self.assertNotIn("provider response", str(context.exception))
                self.assertEqual(1, calls)

    def test_invalid_indices_or_usage_fail_with_stable_errors(self) -> None:
        cases = (
            (
                ((0, (1.0, 0.0, 0.0)), (0, (0.0, 1.0, 0.0))),
                4,
                4,
                ("first", "second"),
                EmbeddingBatchError,
                "embedding_batch_invalid",
            ),
            (
                ((0, (1.0, 0.0, 0.0)),),
                -1,
                -1,
                ("first",),
                EmbeddingUsageError,
                "embedding_usage_invalid",
            ),
        )

        for vectors, prompt, total, texts, error_type, code in cases:
            with self.subTest(code=code):
                def handler(request: httpx.Request) -> httpx.Response:
                    return _success_response(
                        request,
                        vectors,
                        prompt_tokens=prompt,
                        total_tokens=total,
                    )

                model = create_embedding_model(
                    _online_embedding_settings(),
                    openai_client_factory=_sdk_client_factory(handler),
                )

                with self.assertRaises(error_type) as context:
                    model.embed_batch(texts)

                self.assertEqual(code, str(context.exception))

    def test_dimension_validation_remains_in_shared_batching_model(self) -> None:
        usages: list[EmbeddingUsage] = []

        def handler(request: httpx.Request) -> httpx.Response:
            return _success_response(
                request,
                ((0, (1.0, 0.0)),),
                prompt_tokens=2,
                total_tokens=2,
            )

        model = create_embedding_model(
            _online_embedding_settings(),
            openai_client_factory=_sdk_client_factory(handler),
            usage_sink=usages.append,
        )

        with self.assertRaisesRegex(
            EmbeddingDimensionError,
            "embedding_dimension_mismatch",
        ):
            model.embed("first")

        self.assertEqual([EmbeddingUsage(input_tokens=2, total_tokens=2)], usages)

    def test_default_client_factory_is_lazy_bounded_and_closes(self) -> None:
        secret = "factory-secret-that-must-not-leak"
        client = Mock()

        with patch(
            "backend.app.knowledge.openai_embeddings.openai.OpenAI",
            return_value=client,
        ) as constructor:
            factory = create_openai_embedding_client_factory(
                api_key=secret,
                timeout_ms=1_500,
            )
            constructor.assert_not_called()

            with factory() as resolved:
                self.assertIs(client, resolved)

        constructor.assert_called_once_with(
            api_key=secret,
            timeout=1.5,
            max_retries=0,
        )
        client.close.assert_called_once_with()
        self.assertNotIn(secret, repr(factory))


if __name__ == "__main__":
    unittest.main()
