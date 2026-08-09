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
    EmbeddingValueError,
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


if __name__ == "__main__":
    unittest.main()
