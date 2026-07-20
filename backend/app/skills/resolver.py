from __future__ import annotations

import re

from backend.app.skills.catalog import SkillCatalog, SkillDefinition


_EXPLICIT_TRIGGER_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_-])\$([a-z0-9][a-z0-9-]{0,63})"
    r"(?![A-Za-z0-9_-])",
    re.IGNORECASE,
)
_WORD_PATTERN = re.compile(r"[a-z0-9]+", re.IGNORECASE)
_MAX_QUERY_CHARS = 8_000


class SkillResolverError(ValueError):
    """Stable trigger resolution failure without raw query content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Skill resolution failed with {code}")


class SkillResolver:
    """Resolve explicit or deterministic name-token Skill triggers."""

    def __init__(self, catalog: SkillCatalog) -> None:
        self._catalog = catalog

    def resolve(self, query: str) -> tuple[SkillDefinition, ...]:
        if (
            not isinstance(query, str)
            or len(query) > _MAX_QUERY_CHARS
            or any(
                not character.isprintable()
                and character not in "\r\n\t"
                for character in query
            )
        ):
            raise SkillResolverError("invalid_query")

        skills = self._catalog.load()
        by_name = {skill.name: skill for skill in skills}
        explicit_names = tuple(
            dict.fromkeys(
                match.group(1).lower()
                for match in _EXPLICIT_TRIGGER_PATTERN.finditer(query)
            )
        )
        if explicit_names:
            try:
                return tuple(by_name[name] for name in explicit_names)
            except KeyError:
                raise SkillResolverError("skill_not_found") from None

        query_words = {
            match.group(0).lower() for match in _WORD_PATTERN.finditer(query)
        }
        return tuple(
            skill
            for skill in skills
            if set(skill.name.split("-")).issubset(query_words)
        )
