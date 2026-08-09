from __future__ import annotations

import math
import unittest
from typing import Sequence

from backend.app.knowledge import (
    BatchingEmbeddingModel,
    EmbeddingBatchError,
    EmbeddingDimensionError,
    EmbeddingInputError,
    EmbeddingMetadata,
    EmbeddingMetadataError,
    EmbeddingRetryExhaustedError,
    EmbeddingValueError,
    InMemoryEmbeddingCache,
    RetryableEmbeddingError,
    RetryingEmbeddingProvider,
    build_embedding_cache_key,
    create_deterministic_embedding_model,
)


class _RecordingProvider:
    def __init__(self, *, dimensions: int = 2) -> None:
        self._metadata = EmbeddingMetadata(
            provider="test",
            model="recording",
            revision="v1",
            dimensions=dimensions,
        )
        self.batches: list[tuple[str, ...]] = []

    @property
    def metadata(self) -> EmbeddingMetadata:
        return self._metadata

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        self.batches.append(tuple(texts))
        return tuple(
            (float(text),) * self._metadata.dimensions for text in texts
        )


class _TransientProvider(_RecordingProvider):
    def __init__(self, *, failures: int) -> None:
        super().__init__()
        self.failures = failures

    def embed_batch(
        self,
        texts: Sequence[str],
    ) -> tuple[tuple[float, ...], ...]:
        batch = tuple(texts)
        self.batches.append(batch)
        if self.failures > 0:
            self.failures -= 1
            raise RetryableEmbeddingError()
        return tuple(
            (float(text),) * self._metadata.dimensions for text in batch
        )


class EmbeddingMetadataTest(unittest.TestCase):
    def test_metadata_is_trimmed_frozen_and_dimensioned(self) -> None:
        metadata = EmbeddingMetadata(
            provider=" offline ",
            model=" model-v1 ",
            revision=" revision-1 ",
            dimensions=3,
        )

        self.assertEqual("offline", metadata.provider)
        self.assertEqual("model-v1", metadata.model)
        self.assertEqual("revision-1", metadata.revision)
        self.assertEqual(3, metadata.dimensions)
        with self.assertRaisesRegex(ValueError, "dimensions must be positive"):
            EmbeddingMetadata("offline", "model", "v1", 0)
        with self.assertRaisesRegex(ValueError, "dimensions must be positive"):
            EmbeddingMetadata("offline", "model", "v1", 3.5)  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "provider is invalid"):
            EmbeddingMetadata("bad\nprovider", "model", "v1", 3)
        with self.assertRaisesRegex(ValueError, "model is invalid"):
            EmbeddingMetadata("offline", "bad\x7fmodel", "v1", 3)


class DeterministicEmbeddingModelTest(unittest.TestCase):
    def test_same_normalized_text_has_stable_unit_vector(self) -> None:
        first = create_deterministic_embedding_model(
            dimensions=3,
            batch_size=2,
        )
        second = create_deterministic_embedding_model(
            dimensions=3,
            batch_size=5,
        )

        first_vector = first.embed("  Agent   loop\ncontrol  ")
        second_vector = second.embed("Agent loop control")

        self.assertEqual(first_vector, second_vector)
        self.assertEqual(3, len(first_vector))
        self.assertAlmostEqual(
            1.0,
            math.sqrt(sum(value * value for value in first_vector)),
        )
        self.assertEqual("offline", first.metadata.provider)
        self.assertEqual("sha256-token-hash", first.metadata.model)

    def test_empty_batch_is_noop_and_blank_text_fails_closed(self) -> None:
        provider = _RecordingProvider()
        model = BatchingEmbeddingModel(provider, batch_size=2)

        self.assertEqual((), model.embed_batch(()))
        with self.assertRaisesRegex(
            EmbeddingInputError,
            "embedding_input_invalid",
        ):
            model.embed(" \n\t ")

        self.assertEqual([], provider.batches)


class BatchingEmbeddingModelTest(unittest.TestCase):
    def test_batch_size_requires_a_positive_integer(self) -> None:
        provider = _RecordingProvider()

        for batch_size in (0, True, 1.5):
            with self.subTest(batch_size=batch_size):
                with self.assertRaisesRegex(ValueError, "batch_size"):
                    BatchingEmbeddingModel(
                        provider,
                        batch_size=batch_size,  # type: ignore[arg-type]
                    )

    def test_splits_batches_and_preserves_input_order(self) -> None:
        provider = _RecordingProvider()
        model = BatchingEmbeddingModel(provider, batch_size=2)

        vectors = model.embed_batch(("1", "2", "3", "4", "5"))

        self.assertEqual(
            [("1", "2"), ("3", "4"), ("5",)],
            provider.batches,
        )
        self.assertEqual(
            ((1.0, 1.0), (2.0, 2.0), (3.0, 3.0), (4.0, 4.0), (5.0, 5.0)),
            vectors,
        )

    def test_single_embedding_uses_normalized_batch_path(self) -> None:
        provider = _RecordingProvider()
        model = BatchingEmbeddingModel(provider, batch_size=8)

        vector = model.embed("  7   ")

        self.assertEqual((7.0, 7.0), vector)
        self.assertEqual([("7",)], provider.batches)

    def test_partial_provider_result_fails_without_returning_prefix(self) -> None:
        class _PartialProvider(_RecordingProvider):
            def embed_batch(
                self,
                texts: Sequence[str],
            ) -> tuple[tuple[float, ...], ...]:
                complete = super().embed_batch(texts)
                return complete[:-1]

        provider = _PartialProvider()
        model = BatchingEmbeddingModel(provider, batch_size=2)

        with self.assertRaisesRegex(
            EmbeddingBatchError,
            "embedding_batch_invalid",
        ):
            model.embed_batch(("1", "2"))

        self.assertEqual([("1", "2")], provider.batches)

    def test_dimension_drift_fails_with_stable_error(self) -> None:
        class _WrongDimensionProvider(_RecordingProvider):
            def embed_batch(
                self,
                texts: Sequence[str],
            ) -> tuple[tuple[float, ...], ...]:
                self.batches.append(tuple(texts))
                return tuple((1.0,) for _ in texts)

        model = BatchingEmbeddingModel(
            _WrongDimensionProvider(dimensions=2),
            batch_size=2,
        )

        with self.assertRaisesRegex(
            EmbeddingDimensionError,
            "embedding_dimension_mismatch",
        ):
            model.embed_batch(("1", "2"))

    def test_non_finite_or_non_numeric_values_fail_stably(self) -> None:
        class _InvalidValueProvider(_RecordingProvider):
            def __init__(self, vector: Sequence[object]) -> None:
                super().__init__(dimensions=2)
                self.vector = vector

            def embed_batch(
                self,
                texts: Sequence[str],
            ) -> tuple[Sequence[object], ...]:
                self.batches.append(tuple(texts))
                return tuple(self.vector for _ in texts)

        for vector in ((float("nan"), 1.0), ("invalid", 1.0)):
            with self.subTest(vector=vector):
                model = BatchingEmbeddingModel(
                    _InvalidValueProvider(vector),
                    batch_size=2,
                )
                with self.assertRaisesRegex(
                    EmbeddingValueError,
                    "embedding_value_invalid",
                ):
                    model.embed("1")

    def test_metadata_change_between_provider_batches_fails_closed(self) -> None:
        class _ChangingProvider(_RecordingProvider):
            def embed_batch(
                self,
                texts: Sequence[str],
            ) -> tuple[tuple[float, ...], ...]:
                vectors = super().embed_batch(texts)
                self._metadata = EmbeddingMetadata(
                    provider="test",
                    model="recording",
                    revision="v2",
                    dimensions=2,
                )
                return vectors

        provider = _ChangingProvider()
        model = BatchingEmbeddingModel(provider, batch_size=2)

        with self.assertRaisesRegex(
            EmbeddingMetadataError,
            "embedding_metadata_changed",
        ):
            model.embed_batch(("1", "2", "3"))

        self.assertEqual([("1", "2")], provider.batches)


class EmbeddingCacheKeyTest(unittest.TestCase):
    def test_key_is_versioned_normalized_and_omits_raw_text(self) -> None:
        metadata = EmbeddingMetadata("test", "fixture", "v1", 2)
        raw_text = "private customer 42"

        first = build_embedding_cache_key(metadata, f"  {raw_text}\n")
        second = build_embedding_cache_key(metadata, raw_text)

        self.assertEqual(first, second)
        self.assertRegex(first, r"^embedding:v1:[0-9a-f]{64}$")
        self.assertNotIn(raw_text, first)
        self.assertNotIn("customer", first)

    def test_metadata_namespace_changes_the_key(self) -> None:
        text = "shared input"
        keys = {
            build_embedding_cache_key(metadata, text)
            for metadata in (
                EmbeddingMetadata("provider-a", "model", "v1", 2),
                EmbeddingMetadata("provider-b", "model", "v1", 2),
                EmbeddingMetadata("provider-a", "model-2", "v1", 2),
                EmbeddingMetadata("provider-a", "model", "v2", 2),
                EmbeddingMetadata("provider-a", "model", "v1", 3),
            )
        }

        self.assertEqual(5, len(keys))


class InMemoryEmbeddingCacheTest(unittest.TestCase):
    def test_cache_is_bounded_lru_and_copies_vectors(self) -> None:
        metadata = EmbeddingMetadata("test", "fixture", "v1", 2)
        keys = tuple(
            build_embedding_cache_key(metadata, text)
            for text in ("one", "two", "three")
        )
        cache = InMemoryEmbeddingCache(max_entries=2)
        first_vector = [1.0, 1.0]

        cache.put(keys[0], first_vector)
        first_vector[0] = 9.0
        cache.put(keys[1], (2.0, 2.0))
        self.assertEqual((1.0, 1.0), cache.get(keys[0]))
        cache.put(keys[2], (3.0, 3.0))

        self.assertIsNone(cache.get(keys[1]))
        self.assertEqual((1.0, 1.0), cache.get(keys[0]))
        self.assertEqual((3.0, 3.0), cache.get(keys[2]))

    def test_cache_limits_and_key_shape_fail_closed(self) -> None:
        for max_entries in (0, True, 1.5):
            with self.subTest(max_entries=max_entries):
                with self.assertRaisesRegex(ValueError, "max_entries"):
                    InMemoryEmbeddingCache(
                        max_entries=max_entries,  # type: ignore[arg-type]
                    )

        cache = InMemoryEmbeddingCache()
        with self.assertRaisesRegex(ValueError, "cache key is invalid"):
            cache.put("private raw text", (1.0, 2.0))


class CachedBatchingEmbeddingModelTest(unittest.TestCase):
    def test_cache_hit_skips_provider_and_deduplicates_misses(self) -> None:
        cache = InMemoryEmbeddingCache()
        first_provider = _RecordingProvider()
        first_model = BatchingEmbeddingModel(
            first_provider,
            batch_size=2,
            cache=cache,
        )

        first = first_model.embed_batch(("1", "2", "  1  "))

        self.assertEqual([("1", "2")], first_provider.batches)
        self.assertEqual(((1.0, 1.0), (2.0, 2.0), (1.0, 1.0)), first)

        second_provider = _RecordingProvider()
        second_model = BatchingEmbeddingModel(
            second_provider,
            batch_size=1,
            cache=cache,
        )

        self.assertEqual(first, second_model.embed_batch(("1", "2", "1")))
        self.assertEqual([], second_provider.batches)

    def test_retry_exhaustion_does_not_cache_completed_prefix(self) -> None:
        class _FailsLastBatch(_RecordingProvider):
            def embed_batch(
                self,
                texts: Sequence[str],
            ) -> tuple[tuple[float, ...], ...]:
                vectors = super().embed_batch(texts)
                if tuple(texts) == ("3",):
                    raise RetryableEmbeddingError()
                return vectors

        cache = InMemoryEmbeddingCache()
        provider = _FailsLastBatch()
        model = BatchingEmbeddingModel(
            RetryingEmbeddingProvider(provider, max_retries=1),
            batch_size=2,
            cache=cache,
        )

        with self.assertRaisesRegex(
            EmbeddingRetryExhaustedError,
            "embedding_retry_exhausted",
        ):
            model.embed_batch(("1", "2", "3"))

        recovery_provider = _RecordingProvider()
        recovery_model = BatchingEmbeddingModel(
            recovery_provider,
            cache=cache,
        )
        self.assertEqual((1.0, 1.0), recovery_model.embed("1"))
        self.assertEqual([("1",)], recovery_provider.batches)

    def test_invalid_cached_vector_fails_before_provider(self) -> None:
        metadata = EmbeddingMetadata("test", "recording", "v1", 2)
        cache = InMemoryEmbeddingCache()
        cache.put(build_embedding_cache_key(metadata, "1"), (1.0,))
        provider = _RecordingProvider()
        model = BatchingEmbeddingModel(provider, cache=cache)

        with self.assertRaisesRegex(
            EmbeddingDimensionError,
            "embedding_dimension_mismatch",
        ):
            model.embed("1")

        self.assertEqual([], provider.batches)


class RetryingEmbeddingProviderTest(unittest.TestCase):
    def test_retryable_failure_retries_only_the_same_provider_batch(self) -> None:
        provider = _TransientProvider(failures=1)
        model = BatchingEmbeddingModel(
            RetryingEmbeddingProvider(provider, max_retries=1),
            batch_size=2,
        )

        vectors = model.embed_batch(("1", "2", "3"))

        self.assertEqual(
            [("1", "2"), ("1", "2"), ("3",)],
            provider.batches,
        )
        self.assertEqual(
            ((1.0, 1.0), (2.0, 2.0), (3.0, 3.0)),
            vectors,
        )

    def test_retry_exhaustion_has_a_stable_error_and_attempt_limit(self) -> None:
        provider = _TransientProvider(failures=10)
        model = BatchingEmbeddingModel(
            RetryingEmbeddingProvider(provider, max_retries=2),
            batch_size=2,
        )
        raw_text = "private customer text"

        with self.assertRaises(EmbeddingRetryExhaustedError) as context:
            model.embed(raw_text)

        self.assertEqual("embedding_retry_exhausted", str(context.exception))
        self.assertNotIn(raw_text, str(context.exception))
        self.assertEqual(3, len(provider.batches))

    def test_non_retryable_error_is_not_retried(self) -> None:
        class _ProtocolFailureProvider(_RecordingProvider):
            def embed_batch(
                self,
                texts: Sequence[str],
            ) -> tuple[tuple[float, ...], ...]:
                self.batches.append(tuple(texts))
                raise EmbeddingDimensionError()

        provider = _ProtocolFailureProvider()
        model = BatchingEmbeddingModel(
            RetryingEmbeddingProvider(provider, max_retries=3),
        )

        with self.assertRaisesRegex(
            EmbeddingDimensionError,
            "embedding_dimension_mismatch",
        ):
            model.embed("1")

        self.assertEqual([("1",)], provider.batches)

    def test_retry_limit_requires_a_non_negative_integer(self) -> None:
        provider = _RecordingProvider()

        for max_retries in (-1, True, 1.5):
            with self.subTest(max_retries=max_retries):
                with self.assertRaisesRegex(ValueError, "max_retries"):
                    RetryingEmbeddingProvider(
                        provider,
                        max_retries=max_retries,  # type: ignore[arg-type]
                    )


if __name__ == "__main__":
    unittest.main()
