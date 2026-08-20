from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from backend.app.evals.rag_retrieval import (
    DEFAULT_RAG_RETRIEVAL_DATASET,
    RagEvalCase,
    RagEvalDocument,
    RagEvalThresholds,
    RagRetrievalDataset,
    RagRetrievalDatasetError,
    RagRetrievalEvaluator,
    load_rag_retrieval_dataset,
    run_default_sparse_rag_eval,
)
from backend.app.knowledge import Citation, SearchResult


class _StaticKnowledge:
    def __init__(self, results: tuple[SearchResult, ...]) -> None:
        self._results = results
        self.queries: list[tuple[str, int]] = []

    def add(self, document: object) -> int:
        del document
        raise AssertionError("evaluation must not mutate the retriever")

    def seed(self, document: object) -> int:
        del document
        raise AssertionError("evaluation must not mutate the retriever")

    def delete(self, document_id: str) -> bool:
        del document_id
        raise AssertionError("evaluation must not mutate the retriever")

    def search(
        self,
        query: str,
        *,
        limit: int = 3,
    ) -> tuple[SearchResult, ...]:
        self.queries.append((query, limit))
        return self._results[:limit]


def _result(document_id: str, excerpt: str) -> SearchResult:
    return SearchResult(
        score=1.0,
        citation=Citation(
            document_id=document_id,
            title=document_id,
            source=f"course/{document_id}.md",
            chunk_index=0,
            excerpt=excerpt,
        ),
    )


def _dataset(
    *,
    thresholds: RagEvalThresholds | None = None,
) -> RagRetrievalDataset:
    return RagRetrievalDataset(
        version="test-v1",
        digest="0" * 64,
        top_k=3,
        documents=(
            RagEvalDocument(
                id="relevant",
                title="Relevant",
                source="course/relevant.md",
                content="authoritative evidence",
            ),
            RagEvalDocument(
                id="noise",
                title="Noise",
                source="course/noise.md",
                content="unrelated text",
            ),
        ),
        cases=(
            RagEvalCase(
                id="case-01",
                query="private evaluation query",
                relevant_document_ids=("relevant",),
                required_evidence_terms=("authoritative evidence",),
            ),
        ),
        retriever_thresholds=(
            (
                "sparse",
                thresholds
                or RagEvalThresholds(
                    recall_at_k=1.0,
                    mean_reciprocal_rank=1.0,
                    grounding_accuracy=1.0,
                ),
            ),
        ),
    )


class RagRetrievalEvalTest(unittest.TestCase):
    def test_default_dataset_is_versioned_bounded_and_has_fifty_cases(
        self,
    ) -> None:
        dataset = load_rag_retrieval_dataset()

        self.assertEqual("m11-rag-v1", dataset.version)
        self.assertEqual(10, len(dataset.documents))
        self.assertEqual(50, len(dataset.cases))
        self.assertEqual(3, dataset.top_k)
        self.assertEqual(64, len(dataset.digest))
        self.assertEqual(50, len({case.id for case in dataset.cases}))
        self.assertEqual(
            {"pgvector", "sparse"},
            {item[0] for item in dataset.retriever_thresholds},
        )

    def test_dataset_digest_is_independent_of_json_formatting(self) -> None:
        payload = json.loads(DEFAULT_RAG_RETRIEVAL_DATASET.read_text("utf-8"))

        with tempfile.TemporaryDirectory() as temporary_directory:
            compact_path = Path(temporary_directory) / "compact.json"
            compact_path.write_text(
                json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                encoding="utf-8",
            )
            compact = load_rag_retrieval_dataset(compact_path)

        self.assertEqual(load_rag_retrieval_dataset().digest, compact.digest)

    def test_default_sparse_baseline_passes_fixed_thresholds(self) -> None:
        report = run_default_sparse_rag_eval()

        self.assertTrue(report.passed)
        self.assertEqual(50, len(report.results))
        self.assertGreaterEqual(
            report.recall_at_k,
            report.thresholds.recall_at_k,
        )
        self.assertGreaterEqual(
            report.mean_reciprocal_rank,
            report.thresholds.mean_reciprocal_rank,
        )
        self.assertGreaterEqual(
            report.grounding_accuracy,
            report.thresholds.grounding_accuracy,
        )
        self.assertEqual({}, report.failure_analysis)

    def test_metrics_use_first_relevant_rank_and_annotated_evidence(self) -> None:
        knowledge = _StaticKnowledge(
            (
                _result("noise", "unrelated text"),
                _result("relevant", "authoritative evidence"),
            )
        )

        report = RagRetrievalEvaluator(
            knowledge,
            _dataset(
                thresholds=RagEvalThresholds(
                    recall_at_k=1.0,
                    mean_reciprocal_rank=0.5,
                    grounding_accuracy=1.0,
                )
            ),
            retriever_id="sparse",
        ).evaluate()

        self.assertTrue(report.passed)
        self.assertEqual(1.0, report.recall_at_k)
        self.assertEqual(0.5, report.mean_reciprocal_rank)
        self.assertEqual(1.0, report.grounding_accuracy)
        self.assertEqual([("private evaluation query", 3)], knowledge.queries)

    def test_unrelated_excerpt_cannot_mask_missing_relevant_grounding(
        self,
    ) -> None:
        knowledge = _StaticKnowledge(
            (
                _result("noise", "authoritative evidence"),
                _result("relevant", "different relevant text"),
            )
        )

        report = RagRetrievalEvaluator(
            knowledge,
            _dataset(),
            retriever_id="sparse",
        ).evaluate()

        self.assertFalse(report.passed)
        self.assertEqual(1.0, report.recall_at_k)
        self.assertEqual(0.0, report.grounding_accuracy)
        self.assertEqual(
            {"grounding_evidence_missing": 1},
            report.failure_analysis,
        )
        self.assertIn(
            "grounding_accuracy_below_threshold",
            report.threshold_failure_codes,
        )

    def test_empty_retrieval_has_stable_failure_analysis(self) -> None:
        report = RagRetrievalEvaluator(
            _StaticKnowledge(()),
            _dataset(),
            retriever_id="sparse",
        ).evaluate()

        self.assertFalse(report.passed)
        self.assertEqual(0.0, report.recall_at_k)
        self.assertEqual(0.0, report.mean_reciprocal_rank)
        self.assertEqual(0.0, report.grounding_accuracy)
        self.assertEqual(
            {
                "grounding_evidence_missing": 1,
                "no_results": 1,
                "relevant_document_not_ranked": 1,
                "relevant_document_not_recalled": 1,
            },
            report.failure_analysis,
        )

    def test_report_does_not_expose_queries_terms_or_excerpts(self) -> None:
        report = RagRetrievalEvaluator(
            _StaticKnowledge((_result("relevant", "authoritative evidence"),)),
            _dataset(),
            retriever_id="sparse",
        ).evaluate()

        serialized = json.dumps(report.to_record(), ensure_ascii=False)

        self.assertNotIn("private evaluation query", serialized)
        self.assertNotIn("authoritative evidence", serialized)
        self.assertNotIn("unrelated text", serialized)
        self.assertIn("relevant", serialized)
        self.assertFalse(report.to_record()["provider_usage_available"])
        self.assertIsNone(report.to_record()["estimated_cost_usd"])

    def test_unconfigured_document_id_is_redacted_from_report(self) -> None:
        report = RagRetrievalEvaluator(
            _StaticKnowledge((_result("private-document-id", "private text"),)),
            _dataset(),
            retriever_id="sparse",
        ).evaluate()

        serialized = json.dumps(report.to_record(), ensure_ascii=False)

        self.assertNotIn("private-document-id", serialized)
        self.assertNotIn("private text", serialized)
        self.assertIn("unconfigured-document", serialized)
        self.assertEqual(
            1,
            report.failure_analysis["unconfigured_document_retrieved"],
        )

    def test_loader_rejects_unknown_relevant_document_content_free(self) -> None:
        payload = json.loads(DEFAULT_RAG_RETRIEVAL_DATASET.read_text("utf-8"))
        payload["cases"][0]["relevant_document_ids"] = ["missing"]

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "dataset.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(RagRetrievalDatasetError) as caught:
                load_rag_retrieval_dataset(path)

        self.assertEqual(
            "rag_eval_relevant_document_unknown",
            caught.exception.code,
        )
        self.assertNotIn("missing", str(caught.exception))

    def test_loader_rejects_evidence_not_supported_by_relevant_content(
        self,
    ) -> None:
        payload = json.loads(DEFAULT_RAG_RETRIEVAL_DATASET.read_text("utf-8"))
        payload["cases"][0]["required_evidence_terms"] = ["secret-term"]

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "dataset.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaises(RagRetrievalDatasetError) as caught:
                load_rag_retrieval_dataset(path)

        self.assertEqual(
            "rag_eval_evidence_annotation_invalid",
            caught.exception.code,
        )
        self.assertNotIn("secret-term", str(caught.exception))

    def test_loader_enforces_minimum_case_count_and_schema(self) -> None:
        payload = json.loads(DEFAULT_RAG_RETRIEVAL_DATASET.read_text("utf-8"))
        payload["cases"] = payload["cases"][:49]

        with tempfile.TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "dataset.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                RagRetrievalDatasetError,
                "rag_eval_case_count_below_minimum",
            ):
                load_rag_retrieval_dataset(path)

            payload["schema"] = "rag-retrieval-dataset-v2"
            path.write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(
                RagRetrievalDatasetError,
                "rag_eval_schema_unsupported",
            ):
                load_rag_retrieval_dataset(path, minimum_case_count=1)

    def test_invalid_threshold_and_unknown_retriever_fail_closed(self) -> None:
        with self.assertRaisesRegex(
            RagRetrievalDatasetError,
            "rag_eval_threshold_invalid",
        ):
            RagEvalThresholds(
                recall_at_k=True,
                mean_reciprocal_rank=1.0,
                grounding_accuracy=1.0,
            )

        with self.assertRaisesRegex(
            RagRetrievalDatasetError,
            "rag_eval_retriever_not_configured",
        ):
            RagRetrievalEvaluator(
                _StaticKnowledge(()),
                _dataset(),
                retriever_id="pgvector",
            )


if __name__ == "__main__":
    unittest.main()
