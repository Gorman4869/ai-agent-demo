from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from backend.app.context.assembler import (
    ContextAssembler,
    ContextAssembly,
    ContextFragment,
    ContextSource,
)
from backend.app.domain import Message
from backend.app.knowledge.rag import Citation, KnowledgeBase, SearchResult
from backend.app.memory.store import MemoryFact, MemoryScope
from backend.app.skills.catalog import SkillCatalogError
from backend.app.skills.context import (
    SkillContext,
    SkillContextBuilder,
    SkillContextError,
)
from backend.app.skills.resolver import SkillResolverError
from backend.app.stores.base import StoreError


_MAX_QUERY_CHARS = 8_000
_MAX_SYSTEM_CONSTRAINTS = 16
_MAX_RAG_RESULTS = 16
_MESSAGE_ROLES = frozenset({"system", "user", "assistant", "tool"})


class ContextCollectionError(ValueError):
    """Stable collection failure without source content or owner IDs."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True)
class ContextSystemConstraint:
    id: str
    content: str = field(repr=False)
    ordinal: int = 0

    def __post_init__(self) -> None:
        _require_identifier(self.id, "system constraint id")
        ContextFragment(
            id=_stable_fragment_id(ContextSource.SYSTEM, self.id),
            source=ContextSource.SYSTEM,
            content=self.content,
            ordinal=self.ordinal,
        )


@dataclass(frozen=True)
class ContextCollectionInput:
    owner_id: str = field(repr=False)
    session_id: str = field(repr=False)
    query: str = field(repr=False)
    system_constraints: tuple[ContextSystemConstraint, ...] = ()

    def __post_init__(self) -> None:
        _require_scope_id(self.owner_id, "context owner")
        _require_scope_id(self.session_id, "context session")
        if (
            not isinstance(self.query, str)
            or len(self.query) > _MAX_QUERY_CHARS
            or any(
                not character.isprintable()
                and character not in "\r\n\t"
                for character in self.query
            )
        ):
            raise ValueError("context query has an invalid format")
        try:
            constraints = tuple(self.system_constraints)
        except TypeError:
            raise ValueError("system constraints have an invalid format") from None
        if (
            len(constraints) > _MAX_SYSTEM_CONSTRAINTS
            or any(
                not isinstance(constraint, ContextSystemConstraint)
                for constraint in constraints
            )
            or len({constraint.id for constraint in constraints})
            != len(constraints)
        ):
            raise ValueError("system constraints have an invalid format")
        object.__setattr__(self, "system_constraints", constraints)


@dataclass(frozen=True)
class ContextSummaryResult:
    available: bool
    content: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.available, bool):
            raise ValueError("context summary availability is invalid")
        if not self.available:
            if self.content is not None:
                raise ValueError("unavailable context summary has content")
            return
        if self.content is not None:
            ContextFragment(
                id="summary:validation",
                source=ContextSource.SUMMARY,
                content=self.content,
                owner_id="summary-validation-owner",
            )

    @classmethod
    def unavailable(cls) -> ContextSummaryResult:
        return cls(available=False)

    @classmethod
    def without_summary(cls) -> ContextSummaryResult:
        return cls(available=True)

    @classmethod
    def from_content(cls, content: str) -> ContextSummaryResult:
        return cls(available=True, content=content)


class ContextSummarizer(Protocol):
    def summarize(
        self,
        *,
        owner_id: str,
        session_id: str,
        messages: Sequence[Message],
    ) -> ContextSummaryResult: ...


class _ContextMemoryReader(Protocol):
    def messages(self, session_id: str) -> tuple[Message, ...]: ...

    def facts(self, owner_id: str) -> tuple[MemoryFact, ...]: ...


@dataclass(frozen=True)
class CollectedContext:
    owner_id: str = field(repr=False)
    fragments: tuple[ContextFragment, ...] = field(repr=False)
    unavailable_sources: tuple[ContextSource, ...] = ()

    def __post_init__(self) -> None:
        _require_scope_id(self.owner_id, "context owner")
        try:
            fragments = tuple(self.fragments)
        except TypeError:
            raise ValueError(
                "collected context contains an invalid fragment"
            ) from None
        if any(not isinstance(fragment, ContextFragment) for fragment in fragments):
            raise ValueError("collected context contains an invalid fragment")
        try:
            unavailable = tuple(
                ContextSource(source) for source in self.unavailable_sources
            )
        except (TypeError, ValueError):
            raise ValueError("collected context availability is invalid") from None
        if len(unavailable) != len(set(unavailable)):
            raise ValueError("collected context availability is invalid")
        object.__setattr__(self, "fragments", fragments)
        object.__setattr__(self, "unavailable_sources", unavailable)

    def assemble(
        self,
        assembler: ContextAssembler | None = None,
    ) -> ContextAssembly:
        checked_assembler = assembler or ContextAssembler()
        if not isinstance(checked_assembler, ContextAssembler):
            raise ValueError("context assembler has an invalid format")
        return checked_assembler.assemble(
            owner_id=self.owner_id,
            fragments=self.fragments,
            unavailable_sources=self.unavailable_sources,
        )


class ContextSourceCollector:
    """Map existing source contracts into owner-safe context fragments."""

    def __init__(
        self,
        *,
        memory_store: _ContextMemoryReader,
        knowledge_base: KnowledgeBase,
        skill_context_builder: SkillContextBuilder,
        summarizer: ContextSummarizer | None = None,
        rag_limit: int = 3,
    ) -> None:
        _validate_rag_limit(rag_limit)
        self._memory_store = memory_store
        self._knowledge_base = knowledge_base
        self._skill_context_builder = skill_context_builder
        self._summarizer = summarizer
        self._rag_limit = rag_limit

    def collect(self, request: ContextCollectionInput) -> CollectedContext:
        if not isinstance(request, ContextCollectionInput):
            raise ContextCollectionError("context_collection_input_invalid")

        messages, facts = self._load_memory(request)
        results = self._load_knowledge(request.query)
        skill_context = self._load_skill_context(request.query)
        summary = self._load_summary(request, messages)

        fragments = [
            _system_fragment(constraint)
            for constraint in request.system_constraints
        ]
        fragments.extend(
            _message_fragment(
                message,
                session_id=request.session_id,
                owner_id=request.owner_id,
                ordinal=ordinal,
            )
            for ordinal, message in enumerate(messages, start=1)
        )
        unavailable_sources: tuple[ContextSource, ...] = ()
        if not summary.available:
            unavailable_sources = (ContextSource.SUMMARY,)
        elif summary.content is not None:
            fragments.append(
                ContextFragment(
                    id=_stable_fragment_id(
                        ContextSource.SUMMARY,
                        request.session_id,
                        summary.content,
                    ),
                    source=ContextSource.SUMMARY,
                    content=summary.content,
                    owner_id=request.owner_id,
                    ordinal=len(messages),
                )
            )
        fragments.extend(
            _memory_fragment(
                fact,
                owner_id=request.owner_id,
                ordinal=ordinal,
            )
            for ordinal, fact in enumerate(facts, start=1)
        )
        fragments.extend(
            _rag_fragment(result, ordinal=ordinal)
            for ordinal, result in enumerate(results, start=1)
        )
        if skill_context is not None:
            fragments.append(_skill_fragment(skill_context))

        return CollectedContext(
            owner_id=request.owner_id,
            fragments=tuple(fragments),
            unavailable_sources=unavailable_sources,
        )

    def _load_memory(
        self,
        request: ContextCollectionInput,
    ) -> tuple[tuple[Message, ...], tuple[MemoryFact, ...]]:
        try:
            raw_messages = self._memory_store.messages(request.session_id)
            raw_facts = self._memory_store.facts(request.owner_id)
        except StoreError:
            raise ContextCollectionError("memory_context_unavailable") from None
        try:
            messages = tuple(raw_messages)
            facts = tuple(raw_facts)
        except TypeError:
            raise ContextCollectionError("context_source_invalid") from None

        if any(not isinstance(message, Message) for message in messages):
            raise ContextCollectionError("context_source_invalid")
        if any(not isinstance(fact, MemoryFact) for fact in facts):
            raise ContextCollectionError("context_source_invalid")
        if any(fact.owner_id != request.owner_id for fact in facts):
            raise ContextCollectionError("context_owner_mismatch")
        return messages, facts

    def _load_knowledge(self, query: str) -> tuple[SearchResult, ...]:
        raw_results = self._knowledge_base.search(
            query,
            limit=self._rag_limit,
        )
        try:
            results = tuple(raw_results)
        except TypeError:
            raise ContextCollectionError("context_source_invalid") from None
        if any(not isinstance(result, SearchResult) for result in results):
            raise ContextCollectionError("context_source_invalid")
        return results

    def _load_skill_context(self, query: str) -> SkillContext | None:
        try:
            context = self._skill_context_builder.build(query)
        except (SkillCatalogError, SkillContextError, SkillResolverError):
            raise ContextCollectionError("skill_context_unavailable") from None
        if context is not None and not isinstance(context, SkillContext):
            raise ContextCollectionError("context_source_invalid")
        return context

    def _load_summary(
        self,
        request: ContextCollectionInput,
        messages: tuple[Message, ...],
    ) -> ContextSummaryResult:
        if self._summarizer is None:
            return ContextSummaryResult.unavailable()
        summary = self._summarizer.summarize(
            owner_id=request.owner_id,
            session_id=request.session_id,
            messages=messages,
        )
        if not isinstance(summary, ContextSummaryResult):
            raise ContextCollectionError("summary_context_invalid")
        return summary


def _system_fragment(constraint: ContextSystemConstraint) -> ContextFragment:
    return ContextFragment(
        id=_stable_fragment_id(ContextSource.SYSTEM, constraint.id),
        source=ContextSource.SYSTEM,
        content=constraint.content,
        ordinal=constraint.ordinal,
    )


def _message_fragment(
    message: Message,
    *,
    session_id: str,
    owner_id: str,
    ordinal: int,
) -> ContextFragment:
    if (
        message.role not in _MESSAGE_ROLES
        or not isinstance(message.content, str)
        or (message.name is not None and not isinstance(message.name, str))
        or (
            message.tool_call_id is not None
            and not isinstance(message.tool_call_id, str)
        )
    ):
        raise ContextCollectionError("context_source_invalid")
    content = _render_record(
        {
            "content": message.content,
            "name": message.name,
            "role": message.role,
            "tool_call_id": message.tool_call_id,
        }
    )
    return ContextFragment(
        id=_stable_fragment_id(
            ContextSource.RECENT,
            session_id,
            ordinal,
            content,
        ),
        source=ContextSource.RECENT,
        content=content,
        owner_id=owner_id,
        ordinal=ordinal,
    )


def _memory_fragment(
    fact: MemoryFact,
    *,
    owner_id: str,
    ordinal: int,
) -> ContextFragment:
    if (
        not isinstance(fact.id, str)
        or not fact.id
        or not isinstance(fact.key, str)
        or not isinstance(fact.value, str)
    ):
        raise ContextCollectionError("context_source_invalid")
    try:
        scope = MemoryScope(fact.scope)
    except (TypeError, ValueError):
        raise ContextCollectionError("context_source_invalid") from None
    return ContextFragment(
        id=_stable_fragment_id(ContextSource.MEMORY, fact.id),
        source=ContextSource.MEMORY,
        content=_render_record(
            {
                "key": fact.key,
                "scope": scope.value,
                "value": fact.value,
            }
        ),
        owner_id=owner_id,
        ordinal=ordinal,
    )


def _rag_fragment(result: SearchResult, *, ordinal: int) -> ContextFragment:
    citation = result.citation
    if (
        not isinstance(result.score, (int, float))
        or isinstance(result.score, bool)
        or not math.isfinite(float(result.score))
        or not isinstance(citation, Citation)
        or not isinstance(citation.document_id, str)
        or not citation.document_id
        or not isinstance(citation.title, str)
        or not isinstance(citation.source, str)
        or not isinstance(citation.chunk_index, int)
        or isinstance(citation.chunk_index, bool)
        or citation.chunk_index < 0
        or not isinstance(citation.excerpt, str)
    ):
        raise ContextCollectionError("context_source_invalid")
    return ContextFragment(
        id=_stable_fragment_id(
            ContextSource.RAG,
            citation.document_id,
            citation.chunk_index,
        ),
        source=ContextSource.RAG,
        content=_render_record(
            {
                "chunk_index": citation.chunk_index,
                "document_id": citation.document_id,
                "excerpt": citation.excerpt,
                "score": float(result.score),
                "source": citation.source,
                "title": citation.title,
            }
        ),
        ordinal=ordinal,
    )


def _skill_fragment(context: SkillContext) -> ContextFragment:
    return ContextFragment(
        id=_stable_fragment_id(
            ContextSource.SKILL,
            context.skill_names,
            context.fragment,
        ),
        source=ContextSource.SKILL,
        content=context.fragment,
    )


def _render_record(record: dict[str, object]) -> str:
    return json.dumps(
        record,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _stable_fragment_id(source: ContextSource, *parts: object) -> str:
    canonical = json.dumps(
        parts,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"{source.value}:v1:{digest}"


def _require_identifier(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 160
        or any(
            character.isspace() or not character.isprintable()
            for character in value
        )
    ):
        raise ValueError(f"{field_name} has an invalid format")


def _require_scope_id(value: object, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 200
        or any(not character.isprintable() for character in value)
    ):
        raise ValueError(f"{field_name} has an invalid format")


def _validate_rag_limit(value: object) -> None:
    if (
        not isinstance(value, int)
        or isinstance(value, bool)
        or value < 1
        or value > _MAX_RAG_RESULTS
    ):
        raise ValueError("rag_limit is outside the allowed range")


__all__ = [
    "CollectedContext",
    "ContextCollectionError",
    "ContextCollectionInput",
    "ContextSourceCollector",
    "ContextSummarizer",
    "ContextSummaryResult",
    "ContextSystemConstraint",
]
