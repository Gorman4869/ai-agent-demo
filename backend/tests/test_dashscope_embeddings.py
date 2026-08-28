from __future__ import annotations

import json
import unittest
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from unittest.mock import Mock, patch

import httpx
import openai

from backend.app.container import ApplicationContainer, create_embedding_model
from backend.app.knowledge import (
    EmbeddingAuthenticationError,
    EmbeddingClientConfigurationError,
    OpenAIEmbeddingClient,
    OpenAIEmbeddingClientFactory,
    create_openai_embedding_client_factory,
)
from backend.app.settings import Settings, SettingsError


_BASE_URL = "https://workspace-id.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"


def _dashscope_settings() -> Settings:
    return Settings.from_environment(
        {
            "AI_AGENT_ONLINE_ENABLED": "true",
            "DASHSCOPE_API_KEY": "dashscope-fixture-secret",
            "AI_AGENT_DASHSCOPE_BASE_URL": _BASE_URL,
            "AI_AGENT_EMBEDDING_PROVIDER": "dashscope",
            "AI_AGENT_EMBEDDING_MODEL": "text-embedding-v4",
            "AI_AGENT_EMBEDDING_REVISION": "m11-t7-dashscope-v1",
            "AI_AGENT_EMBEDDING_DIMENSIONS": "64",
            "AI_AGENT_EMBEDDING_BATCH_SIZE": "2",
            "AI_AGENT_EMBEDDING_CACHE_MAX_ENTRIES": "8",
            "AI_AGENT_EMBEDDING_MAX_RETRIES": "0",
        }
    )


def _client_factory(
    handler: Callable[[httpx.Request], httpx.Response],
) -> OpenAIEmbeddingClientFactory:
    transport = httpx.MockTransport(handler)

    @contextmanager
    def create_client() -> Iterator[OpenAIEmbeddingClient]:
        client = openai.OpenAI(
            api_key="dashscope-fixture-secret",
            base_url=_BASE_URL,
            max_retries=0,
            http_client=httpx.Client(transport=transport),
        )
        try:
            yield client
        finally:
            client.close()

    return create_client


class DashScopeEmbeddingAdapterTest(unittest.TestCase):
    def test_settings_fail_closed_for_missing_or_invalid_dashscope_values(self) -> None:
        complete = {
            "AI_AGENT_ONLINE_ENABLED": "true",
            "DASHSCOPE_API_KEY": "dashscope-fixture-secret",
            "AI_AGENT_DASHSCOPE_BASE_URL": _BASE_URL,
            "AI_AGENT_EMBEDDING_PROVIDER": "dashscope",
            "AI_AGENT_EMBEDDING_MODEL": "text-embedding-v4",
            "AI_AGENT_EMBEDDING_REVISION": "m11-t7-dashscope-v1",
            "AI_AGENT_EMBEDDING_DIMENSIONS": "64",
        }
        cases = (
            {key: value for key, value in complete.items() if key != "DASHSCOPE_API_KEY"},
            {
                **complete,
                "AI_AGENT_DASHSCOPE_BASE_URL": "https://example.test/v1",
            },
            {
                **complete,
                "AI_AGENT_EMBEDDING_MODEL": "text-embedding-v3",
            },
            {**complete, "AI_AGENT_EMBEDDING_DIMENSIONS": "3"},
        )

        for environment in cases:
            with self.subTest(environment=environment):
                with self.assertRaises(SettingsError):
                    Settings.from_environment(environment)

    def test_dashscope_secret_and_workspace_endpoint_are_not_in_safe_outputs(self) -> None:
        settings = _dashscope_settings()

        self.assertNotIn("dashscope-fixture-secret", repr(settings))
        self.assertNotIn(_BASE_URL, repr(settings))
        self.assertNotIn(_BASE_URL, str(settings.safe_summary()))

    def test_container_composition_is_lazy_for_dashscope(self) -> None:
        with patch(
            "backend.app.knowledge.openai_embeddings.openai.OpenAI"
        ) as constructor:
            container = ApplicationContainer.create(settings=_dashscope_settings())

        constructor.assert_not_called()
        self.assertEqual("dashscope", container.embedding_model.metadata.provider)

    def test_composition_uses_dashscope_metadata_and_openai_compatible_shape(self) -> None:
        requests: list[dict[str, object]] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append(json.loads(request.content))
            return httpx.Response(
                200,
                request=request,
                json={
                    "object": "list",
                    "data": [
                        {
                            "object": "embedding",
                            "index": index,
                            "embedding": [float(index + 1)] + [0.0] * 63,
                        }
                        for index in range(2)
                    ],
                    "model": "text-embedding-v4",
                    "usage": {"prompt_tokens": 3, "total_tokens": 3},
                },
            )

        model = create_embedding_model(
            _dashscope_settings(),
            openai_client_factory=_client_factory(handler),
        )

        vectors = model.embed_batch(("first", "second"))

        self.assertEqual("dashscope", model.metadata.provider)
        self.assertEqual(64, model.metadata.dimensions)
        self.assertEqual(64, len(vectors[0]))
        self.assertEqual(64, len(vectors[1]))
        self.assertEqual(
            [
                {
                    "input": ["first", "second"],
                    "model": "text-embedding-v4",
                    "dimensions": 64,
                    "encoding_format": "float",
                }
            ],
            requests,
        )

    def test_provider_errors_remain_content_free(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                401,
                request=request,
                json={"error": {"message": "private DashScope detail"}},
            )

        model = create_embedding_model(
            _dashscope_settings(),
            openai_client_factory=_client_factory(handler),
        )

        with self.assertRaises(EmbeddingAuthenticationError) as context:
            model.embed("private course text")

        self.assertNotIn("private", str(context.exception))

    def test_sdk_client_import_error_is_stable_and_content_free(self) -> None:
        @contextmanager
        def missing_optional_client_dependency() -> Iterator[OpenAIEmbeddingClient]:
            raise ImportError("private SOCKS dependency detail")
            yield Mock()

        model = create_embedding_model(
            _dashscope_settings(),
            openai_client_factory=missing_optional_client_dependency,
        )

        with self.assertRaises(EmbeddingClientConfigurationError) as context:
            model.embed("private course text")

        self.assertEqual(
            "embedding_provider_client_configuration_invalid",
            str(context.exception),
        )
        self.assertNotIn("private", str(context.exception))

    def test_client_factory_adds_a_configured_base_url_without_eager_io(self) -> None:
        client = Mock()

        with patch(
            "backend.app.knowledge.openai_embeddings.openai.OpenAI",
            return_value=client,
        ) as constructor:
            factory = create_openai_embedding_client_factory(
                api_key="dashscope-fixture-secret",
                timeout_ms=1_500,
                base_url=_BASE_URL,
            )
            constructor.assert_not_called()
            with factory() as resolved:
                self.assertIs(client, resolved)

        constructor.assert_called_once_with(
            api_key="dashscope-fixture-secret",
            timeout=1.5,
            max_retries=0,
            base_url=_BASE_URL,
        )


if __name__ == "__main__":
    unittest.main()
