from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from time import perf_counter_ns
from collections.abc import Iterable
from typing import Any

from backend.app.knowledge import Document, InMemoryKnowledgeBase, KnowledgeBase


RAG_RETRIEVAL_DATASET_SCHEMA = "rag-retrieval-dataset-v1"
DEFAULT_RAG_RETRIEVAL_DATASET = (
    Path(__file__).with_name("fixtures") / "rag_retrieval_v1.json"
)

_ID_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_DIGEST_PATTERN = re.compile(r"[0-9a-f]{64}")
_MAX_DOCUMENTS = 128
_MAX_CASES = 1_000
_MAX_CONTENT_LENGTH = 20_000
_MAX_QUERY_LENGTH = 1_000
_MAX_EVIDENCE_TERMS = 16


class RagRetrievalDatasetError(ValueError):
    """Stable, content-free error for an invalid evaluation fixture."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class RagEvalDocument:
    id: str
    title: str
    source: str
    content: str = field(repr=False)

    def __post_init__(self) -> None:
        _required_id(self.id)
        _required_text(self.title, maximum=200)
        _required_text(self.source, maximum=500)
        _required_text(self.content, maximum=_MAX_CONTENT_LENGTH)

    def to_document(self) -> Document:
        return Document(
            id=self.id,
            title=self.title,
            source=self.source,
            content=self.content,
        )


@dataclass(frozen=True)
class RagEvalCase:
    id: str
    query: str = field(repr=False)
    relevant_document_ids: tuple[str, ...]
    required_evidence_terms: tuple[str, ...] = field(repr=False)

    def __post_init__(self) -> None:
        _required_id(self.id)
        _required_text(self.query, maximum=_MAX_QUERY_LENGTH)
        if not self.relevant_document_ids or len(
            self.relevant_document_ids
        ) != len(set(self.relevant_document_ids)):
            raise RagRetrievalDatasetError(
                "rag_eval_relevant_documents_invalid"
            )
        for document_id in self.relevant_document_ids:
            _required_id(document_id)
        if (
            not self.required_evidence_terms
            or len(self.required_evidence_terms) > _MAX_EVIDENCE_TERMS
            or len(self.required_evidence_terms)
            != len(set(self.required_evidence_terms))
        ):
            raise RagRetrievalDatasetError("rag_eval_evidence_terms_invalid")
        for term in self.required_evidence_terms:
            _required_text(term, maximum=200)


@dataclass(frozen=True)
class RagEvalThresholds:
    recall_at_k: float
    mean_reciprocal_rank: float
    grounding_accuracy: float

    def __post_init__(self) -> None:
        for value in (
            self.recall_at_k,
            self.mean_reciprocal_rank,
            self.grounding_accuracy,
        ):
            if (
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
            ):
                raise RagRetrievalDatasetError("rag_eval_threshold_invalid")
            if value < 0 or value > 1:
                raise RagRetrievalDatasetError("rag_eval_threshold_invalid")

    def to_record(self) -> dict[str, float]:
        return {
            "recall_at_k": self.recall_at_k,
            "mean_reciprocal_rank": self.mean_reciprocal_rank,
            "grounding_accuracy": self.grounding_accuracy,
        }


@dataclass(frozen=True)
class RagRetrievalDataset:
    version: str
    digest: str
    top_k: int
    documents: tuple[RagEvalDocument, ...]
    cases: tuple[RagEvalCase, ...]
    retriever_thresholds: tuple[tuple[str, RagEvalThresholds], ...]

    def __post_init__(self) -> None:
        if not self.version.strip() or len(self.version) > 64:
            raise RagRetrievalDatasetError("rag_eval_version_invalid")
        if _DIGEST_PATTERN.fullmatch(self.digest) is None:
            raise RagRetrievalDatasetError("rag_eval_digest_invalid")
        if not isinstance(self.top_k, int) or isinstance(self.top_k, bool):
            raise RagRetrievalDatasetError("rag_eval_top_k_invalid")
        if self.top_k < 1 or self.top_k > 20:
            raise RagRetrievalDatasetError("rag_eval_top_k_invalid")
        if not self.documents or len(self.documents) > _MAX_DOCUMENTS:
            raise RagRetrievalDatasetError("rag_eval_documents_invalid")
        if not self.cases or len(self.cases) > _MAX_CASES:
            raise RagRetrievalDatasetError("rag_eval_cases_invalid")

        document_ids = tuple(document.id for document in self.documents)
        if len(document_ids) != len(set(document_ids)):
            raise RagRetrievalDatasetError("rag_eval_document_ids_not_unique")
        case_ids = tuple(case.id for case in self.cases)
        if len(case_ids) != len(set(case_ids)):
            raise RagRetrievalDatasetError("rag_eval_case_ids_not_unique")
        threshold_ids = tuple(item[0] for item in self.retriever_thresholds)
        if not threshold_ids or len(threshold_ids) != len(set(threshold_ids)):
            raise RagRetrievalDatasetError("rag_eval_retriever_ids_invalid")
        if any(_ID_PATTERN.fullmatch(value) is None for value in threshold_ids):
            raise RagRetrievalDatasetError("rag_eval_retriever_ids_invalid")
        known_document_ids = set(document_ids)
        if any(
            document_id not in known_document_ids
            for case in self.cases
            for document_id in case.relevant_document_ids
        ):
            raise RagRetrievalDatasetError("rag_eval_relevant_document_unknown")

    def thresholds_for(self, retriever_id: str) -> RagEvalThresholds:
        for current_id, thresholds in self.retriever_thresholds:
            if current_id == retriever_id:
                return thresholds
        raise RagRetrievalDatasetError("rag_eval_retriever_not_configured")


@dataclass(frozen=True)
class RagEvalCaseResult:
    case_id: str
    retrieved_document_ids: tuple[str, ...]
    recall_at_k: float
    reciprocal_rank: float
    grounding_correct: bool
    latency_ms: float
    failure_codes: tuple[str, ...]

    def to_record(self) -> dict[str, object]:
        return {
            "case_id": self.case_id,
            "retrieved_document_ids": list(self.retrieved_document_ids),
            "recall_at_k": round(self.recall_at_k, 6),
            "reciprocal_rank": round(self.reciprocal_rank, 6),
            "grounding_correct": self.grounding_correct,
            "latency_ms": round(self.latency_ms, 3),
            "failure_codes": list(self.failure_codes),
        }


@dataclass(frozen=True)
class RagRetrievalEvalReport:
    dataset_version: str
    dataset_digest: str
    retriever_id: str
    top_k: int
    thresholds: RagEvalThresholds
    results: tuple[RagEvalCaseResult, ...]

    @property
    def recall_at_k(self) -> float:
        return _mean(result.recall_at_k for result in self.results)

    @property
    def mean_reciprocal_rank(self) -> float:
        return _mean(result.reciprocal_rank for result in self.results)

    @property
    def grounding_accuracy(self) -> float:
        return _mean(
            1.0 if result.grounding_correct else 0.0
            for result in self.results
        )

    @property
    def total_latency_ms(self) -> float:
        return sum(result.latency_ms for result in self.results)

    @property
    def threshold_failure_codes(self) -> tuple[str, ...]:
        failures: list[str] = []
        if self.recall_at_k < self.thresholds.recall_at_k:
            failures.append("recall_at_k_below_threshold")
        if self.mean_reciprocal_rank < self.thresholds.mean_reciprocal_rank:
            failures.append("mrr_below_threshold")
        if self.grounding_accuracy < self.thresholds.grounding_accuracy:
            failures.append("grounding_accuracy_below_threshold")
        return tuple(failures)

    @property
    def passed(self) -> bool:
        return not self.threshold_failure_codes

    @property
    def failure_analysis(self) -> dict[str, int]:
        counts = Counter(
            code
            for result in self.results
            for code in result.failure_codes
        )
        return dict(sorted(counts.items()))

    def to_record(self) -> dict[str, object]:
        return {
            "evidence": (
                "offline deterministic retrieval evaluation; grounding checks "
                "annotated retrieved excerpts, not model answer quality"
            ),
            "dataset_version": self.dataset_version,
            "dataset_digest": self.dataset_digest,
            "retriever_id": self.retriever_id,
            "top_k": self.top_k,
            "total_cases": len(self.results),
            "passed": self.passed,
            "metrics": {
                "recall_at_k": round(self.recall_at_k, 6),
                "mean_reciprocal_rank": round(
                    self.mean_reciprocal_rank,
                    6,
                ),
                "grounding_accuracy": round(self.grounding_accuracy, 6),
            },
            "thresholds": self.thresholds.to_record(),
            "threshold_failure_codes": list(self.threshold_failure_codes),
            "failure_analysis": self.failure_analysis,
            "latency": {
                "scope": "local_process_wall_clock_not_production_latency",
                "total_ms": round(self.total_latency_ms, 3),
                "mean_ms": round(
                    self.total_latency_ms / len(self.results)
                    if self.results
                    else 0.0,
                    3,
                ),
            },
            "provider_usage_available": False,
            "estimated_cost_usd": None,
            "results": [result.to_record() for result in self.results],
        }


class RagRetrievalEvaluator:
    """Evaluate one KnowledgeBase against fixed, content-safe annotations."""

    def __init__(
        self,
        knowledge: KnowledgeBase,
        dataset: RagRetrievalDataset,
        *,
        retriever_id: str,
    ) -> None:
        if _ID_PATTERN.fullmatch(retriever_id) is None:
            raise ValueError("retriever_id has an invalid format")
        self._knowledge = knowledge
        self._dataset = dataset
        self._retriever_id = retriever_id
        self._thresholds = dataset.thresholds_for(retriever_id)
        self._configured_document_ids = {
            document.id for document in dataset.documents
        }

    def evaluate(self) -> RagRetrievalEvalReport:
        results = tuple(self._evaluate_case(case) for case in self._dataset.cases)
        return RagRetrievalEvalReport(
            dataset_version=self._dataset.version,
            dataset_digest=self._dataset.digest,
            retriever_id=self._retriever_id,
            top_k=self._dataset.top_k,
            thresholds=self._thresholds,
            results=results,
        )

    def _evaluate_case(self, case: RagEvalCase) -> RagEvalCaseResult:
        started_at = perf_counter_ns()
        retrieved = self._knowledge.search(
            case.query,
            limit=self._dataset.top_k,
        )
        latency_ms = (perf_counter_ns() - started_at) / 1_000_000
        retrieved_ids = tuple(
            result.citation.document_id for result in retrieved
        )
        safe_retrieved_ids = tuple(
            document_id
            if document_id in self._configured_document_ids
            else "unconfigured-document"
            for document_id in retrieved_ids
        )
        relevant_ids = set(case.relevant_document_ids)
        recalled_ids = relevant_ids.intersection(retrieved_ids)
        recall = len(recalled_ids) / len(relevant_ids)
        relevant_rank = next(
            (
                index
                for index, document_id in enumerate(retrieved_ids, start=1)
                if document_id in relevant_ids
            ),
            None,
        )
        reciprocal_rank = 1.0 / relevant_rank if relevant_rank is not None else 0.0

        relevant_excerpts = " ".join(
            result.citation.excerpt
            for result in retrieved
            if result.citation.document_id in relevant_ids
        )
        grounding_correct = bool(relevant_excerpts) and all(
            _normalize_text(term) in _normalize_text(relevant_excerpts)
            for term in case.required_evidence_terms
        )

        failure_codes: list[str] = []
        if not retrieved:
            failure_codes.append("no_results")
        if any(
            document_id not in self._configured_document_ids
            for document_id in retrieved_ids
        ):
            failure_codes.append("unconfigured_document_retrieved")
        if recall < 1.0:
            failure_codes.append("relevant_document_not_recalled")
        if relevant_rank is None:
            failure_codes.append("relevant_document_not_ranked")
        if not grounding_correct:
            failure_codes.append("grounding_evidence_missing")

        return RagEvalCaseResult(
            case_id=case.id,
            retrieved_document_ids=safe_retrieved_ids,
            recall_at_k=recall,
            reciprocal_rank=reciprocal_rank,
            grounding_correct=grounding_correct,
            latency_ms=latency_ms,
            failure_codes=tuple(failure_codes),
        )


def load_rag_retrieval_dataset(
    path: Path = DEFAULT_RAG_RETRIEVAL_DATASET,
    *,
    minimum_case_count: int = 50,
) -> RagRetrievalDataset:
    if not isinstance(minimum_case_count, int) or isinstance(
        minimum_case_count,
        bool,
    ):
        raise ValueError("minimum_case_count must be an integer")
    if minimum_case_count < 1 or minimum_case_count > _MAX_CASES:
        raise ValueError("minimum_case_count is out of range")
    try:
        payload_bytes = path.read_bytes()
        payload = json.loads(payload_bytes.decode("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise RagRetrievalDatasetError("rag_eval_dataset_unavailable") from None
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "version",
        "evaluation",
        "documents",
        "cases",
    }:
        raise RagRetrievalDatasetError("rag_eval_dataset_invalid")
    if payload.get("schema") != RAG_RETRIEVAL_DATASET_SCHEMA:
        raise RagRetrievalDatasetError("rag_eval_schema_unsupported")

    documents = _load_documents(payload.get("documents"))
    cases = _load_cases(payload.get("cases"), documents)
    if len(cases) < minimum_case_count:
        raise RagRetrievalDatasetError("rag_eval_case_count_below_minimum")
    top_k, thresholds = _load_evaluation_config(payload.get("evaluation"))
    return RagRetrievalDataset(
        version=_required_text(payload.get("version"), maximum=64),
        digest=hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
        top_k=top_k,
        documents=documents,
        cases=cases,
        retriever_thresholds=thresholds,
    )


def run_default_sparse_rag_eval() -> RagRetrievalEvalReport:
    dataset = load_rag_retrieval_dataset()
    knowledge = InMemoryKnowledgeBase(chunk_size=240, overlap=30)
    for document in dataset.documents:
        knowledge.add(document.to_document())
    return RagRetrievalEvaluator(
        knowledge,
        dataset,
        retriever_id="sparse",
    ).evaluate()


def main() -> None:
    report = run_default_sparse_rag_eval()
    print(json.dumps(report.to_record(), ensure_ascii=False, indent=2))
    if not report.passed:
        raise SystemExit(1)


def _load_documents(value: Any) -> tuple[RagEvalDocument, ...]:
    if not isinstance(value, list) or not value or len(value) > _MAX_DOCUMENTS:
        raise RagRetrievalDatasetError("rag_eval_documents_invalid")
    documents: list[RagEvalDocument] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "title",
            "source",
            "content",
        }:
            raise RagRetrievalDatasetError("rag_eval_document_invalid")
        document_id = _required_id(item.get("id"))
        documents.append(
            RagEvalDocument(
                id=document_id,
                title=_required_text(item.get("title"), maximum=200),
                source=_required_text(item.get("source"), maximum=500),
                content=_required_text(
                    item.get("content"),
                    maximum=_MAX_CONTENT_LENGTH,
                ),
            )
        )
    return tuple(documents)


def _load_cases(
    value: Any,
    documents: tuple[RagEvalDocument, ...],
) -> tuple[RagEvalCase, ...]:
    if not isinstance(value, list) or not value or len(value) > _MAX_CASES:
        raise RagRetrievalDatasetError("rag_eval_cases_invalid")
    documents_by_id = {document.id: document for document in documents}
    cases: list[RagEvalCase] = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {
            "id",
            "query",
            "relevant_document_ids",
            "required_evidence_terms",
        }:
            raise RagRetrievalDatasetError("rag_eval_case_invalid")
        relevant_ids = _required_id_tuple(item.get("relevant_document_ids"))
        if any(document_id not in documents_by_id for document_id in relevant_ids):
            raise RagRetrievalDatasetError("rag_eval_relevant_document_unknown")
        evidence_terms = _required_text_tuple(
            item.get("required_evidence_terms"),
            maximum_items=_MAX_EVIDENCE_TERMS,
        )
        relevant_content = " ".join(
            documents_by_id[document_id].content
            for document_id in relevant_ids
        )
        if any(
            _normalize_text(term) not in _normalize_text(relevant_content)
            for term in evidence_terms
        ):
            raise RagRetrievalDatasetError("rag_eval_evidence_annotation_invalid")
        cases.append(
            RagEvalCase(
                id=_required_id(item.get("id")),
                query=_required_text(
                    item.get("query"),
                    maximum=_MAX_QUERY_LENGTH,
                ),
                relevant_document_ids=relevant_ids,
                required_evidence_terms=evidence_terms,
            )
        )
    return tuple(cases)


def _load_evaluation_config(
    value: Any,
) -> tuple[int, tuple[tuple[str, RagEvalThresholds], ...]]:
    if not isinstance(value, dict) or set(value) != {"top_k", "thresholds"}:
        raise RagRetrievalDatasetError("rag_eval_config_invalid")
    top_k = value.get("top_k")
    if not isinstance(top_k, int) or isinstance(top_k, bool):
        raise RagRetrievalDatasetError("rag_eval_top_k_invalid")
    thresholds_value = value.get("thresholds")
    if not isinstance(thresholds_value, dict) or not thresholds_value:
        raise RagRetrievalDatasetError("rag_eval_thresholds_invalid")
    thresholds: list[tuple[str, RagEvalThresholds]] = []
    for retriever_id, item in sorted(thresholds_value.items()):
        if not isinstance(retriever_id, str) or _ID_PATTERN.fullmatch(
            retriever_id
        ) is None:
            raise RagRetrievalDatasetError("rag_eval_retriever_ids_invalid")
        if not isinstance(item, dict) or set(item) != {
            "recall_at_k",
            "mean_reciprocal_rank",
            "grounding_accuracy",
        }:
            raise RagRetrievalDatasetError("rag_eval_threshold_invalid")
        thresholds.append(
            (
                retriever_id,
                RagEvalThresholds(
                    recall_at_k=item["recall_at_k"],
                    mean_reciprocal_rank=item["mean_reciprocal_rank"],
                    grounding_accuracy=item["grounding_accuracy"],
                ),
            )
        )
    return top_k, tuple(thresholds)


def _required_id(value: Any) -> str:
    if not isinstance(value, str) or _ID_PATTERN.fullmatch(value) is None:
        raise RagRetrievalDatasetError("rag_eval_id_invalid")
    return value


def _required_text(value: Any, *, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum:
        raise RagRetrievalDatasetError("rag_eval_text_invalid")
    return value


def _required_id_tuple(value: Any) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or len(value) > _MAX_DOCUMENTS:
        raise RagRetrievalDatasetError("rag_eval_relevant_documents_invalid")
    checked = tuple(_required_id(item) for item in value)
    if len(checked) != len(set(checked)):
        raise RagRetrievalDatasetError("rag_eval_relevant_documents_invalid")
    return checked


def _required_text_tuple(value: Any, *, maximum_items: int) -> tuple[str, ...]:
    if not isinstance(value, list) or not value or len(value) > maximum_items:
        raise RagRetrievalDatasetError("rag_eval_evidence_terms_invalid")
    checked = tuple(_required_text(item, maximum=200) for item in value)
    if len(checked) != len(set(checked)):
        raise RagRetrievalDatasetError("rag_eval_evidence_terms_invalid")
    return checked


def _normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _mean(values: Iterable[float]) -> float:
    checked = tuple(values)
    return sum(checked) / len(checked) if checked else 0.0


if __name__ == "__main__":
    main()


__all__ = [
    "DEFAULT_RAG_RETRIEVAL_DATASET",
    "RAG_RETRIEVAL_DATASET_SCHEMA",
    "RagEvalCase",
    "RagEvalCaseResult",
    "RagEvalDocument",
    "RagEvalThresholds",
    "RagRetrievalDataset",
    "RagRetrievalDatasetError",
    "RagRetrievalEvalReport",
    "RagRetrievalEvaluator",
    "load_rag_retrieval_dataset",
    "run_default_sparse_rag_eval",
]
