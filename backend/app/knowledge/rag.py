from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Document:
    id: str
    title: str
    content: str
    source: str


@dataclass(frozen=True)
class Citation:
    document_id: str
    title: str
    source: str
    chunk_index: int
    excerpt: str


@dataclass(frozen=True)
class SearchResult:
    score: float
    citation: Citation


class KnowledgeBase(Protocol):
    """Storage boundary shared by in-memory and persistent retrieval adapters."""

    def add(self, document: Document) -> int:
        """Index a document and return its chunk count."""

    def seed(self, document: Document) -> int:
        """Idempotently index one application-owned document."""

    def delete(self, document_id: str) -> bool:
        """Delete one document and return whether it existed."""

    def search(self, query: str, *, limit: int = 3) -> tuple[SearchResult, ...]:
        """Return relevant chunks in descending similarity order."""


@dataclass(frozen=True)
class _IndexedChunk:
    citation: Citation
    vector: Counter[str]


class InMemoryKnowledgeBase:
    """A deterministic teaching index; it is not a production embedding model."""

    def __init__(self, *, chunk_size: int = 160, overlap: int = 30) -> None:
        if chunk_size < 20:
            raise ValueError("chunk_size must be at least 20")
        if overlap < 0 or overlap >= chunk_size:
            raise ValueError("overlap must be between 0 and chunk_size")
        self._chunk_size = chunk_size
        self._overlap = overlap
        self._chunks: list[_IndexedChunk] = []
        self._document_digests: dict[str, str] = {}

    def add(self, document: Document) -> int:
        if not document.content.strip():
            raise ValueError("document content must not be empty")
        chunks = _split_text(document.content, self._chunk_size, self._overlap)
        digest = _document_digest(document, chunks)
        self._chunks = [
            chunk
            for chunk in self._chunks
            if chunk.citation.document_id != document.id
        ]
        for index, content in enumerate(chunks):
            citation = Citation(
                document_id=document.id,
                title=document.title,
                source=document.source,
                chunk_index=index,
                excerpt=content,
            )
            self._chunks.append(
                _IndexedChunk(citation=citation, vector=_vectorize(content))
            )
        self._document_digests[document.id] = digest
        return len(chunks)

    def seed(self, document: Document) -> int:
        if not document.content.strip():
            raise ValueError("document content must not be empty")
        chunks = _split_text(document.content, self._chunk_size, self._overlap)
        if self._document_digests.get(document.id) == _document_digest(
            document,
            chunks,
        ):
            return sum(
                chunk.citation.document_id == document.id
                for chunk in self._chunks
            )
        return self.add(document)

    def delete(self, document_id: str) -> bool:
        if not isinstance(document_id, str) or not document_id:
            return False
        original_count = len(self._chunks)
        self._chunks = [
            chunk
            for chunk in self._chunks
            if chunk.citation.document_id != document_id
        ]
        self._document_digests.pop(document_id, None)
        return len(self._chunks) != original_count

    def search(self, query: str, *, limit: int = 3) -> tuple[SearchResult, ...]:
        if not query.strip() or limit < 1:
            return ()
        query_vector = _vectorize(query)
        ranked = [
            SearchResult(score=_cosine(query_vector, chunk.vector), citation=chunk.citation)
            for chunk in self._chunks
        ]
        return tuple(
            result
            for result in sorted(ranked, key=lambda item: item.score, reverse=True)[:limit]
            if result.score > 0
        )


def _split_text(text: str, chunk_size: int, overlap: int) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= chunk_size:
        return [normalized]
    step = chunk_size - overlap
    return [
        normalized[start : start + chunk_size]
        for start in range(0, len(normalized), step)
        if normalized[start : start + chunk_size]
    ]


def _document_digest(document: Document, chunks: list[str]) -> str:
    canonical = json.dumps(
        {
            "id": document.id,
            "title": document.title,
            "source": document.source,
            "chunks": chunks,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _vectorize(text: str) -> Counter[str]:
    lowered = text.lower()
    words = re.findall(r"[a-z0-9_]+", lowered)
    chinese = "".join(re.findall(r"[\u4e00-\u9fff]", lowered))
    bigrams = [chinese[index : index + 2] for index in range(len(chinese) - 1)]
    return Counter(words + bigrams)


def _cosine(left: Counter[str], right: Counter[str]) -> float:
    if not left or not right:
        return 0.0
    dot = sum(value * right.get(token, 0) for token, value in left.items())
    left_norm = math.sqrt(sum(value * value for value in left.values()))
    right_norm = math.sqrt(sum(value * value for value in right.values()))
    return dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
