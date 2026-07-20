from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from threading import Lock
from urllib.parse import urlsplit


_SKILL_NAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9-]{0,63}")
_REFERENCE_PART_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_MARKDOWN_LINK_PATTERN = re.compile(
    r"\[[^\]\r\n]{1,256}\]\(([^)\r\n]{1,512})\)"
)
_MAX_SKILLS = 64
_MAX_SKILL_BYTES = 64_000
_MAX_REFERENCE_BYTES = 64_000
_MAX_TOTAL_REFERENCE_BYTES = 128_000
_MAX_REFERENCES = 16
_MAX_FRONTMATTER_LINES = 32


class SkillCatalogError(ValueError):
    """Stable Skill loading failure without raw paths or file content."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"Skill catalog failed with {code}")


@dataclass(frozen=True)
class SkillReference:
    path: str
    content: str


@dataclass(frozen=True)
class SkillDefinition:
    name: str
    description: str
    instructions: str
    references: tuple[SkillReference, ...] = ()


class SkillCatalog:
    """Load immutable Skill snapshots from one server-owned root."""

    def __init__(self, root: str | Path) -> None:
        try:
            resolved_root = Path(root).resolve(strict=True)
        except (OSError, RuntimeError):
            raise SkillCatalogError("invalid_root") from None
        if not resolved_root.is_dir():
            raise SkillCatalogError("invalid_root")
        self._root = resolved_root
        self._snapshot: tuple[SkillDefinition, ...] | None = None
        self._lock = Lock()

    def load(self) -> tuple[SkillDefinition, ...]:
        with self._lock:
            if self._snapshot is None:
                self._snapshot = self._scan()
            return self._snapshot

    def refresh(self) -> tuple[SkillDefinition, ...]:
        with self._lock:
            self._snapshot = self._scan()
            return self._snapshot

    def _scan(self) -> tuple[SkillDefinition, ...]:
        try:
            entries = sorted(
                self._root.iterdir(),
                key=lambda entry: entry.name.casefold(),
            )
        except OSError:
            raise SkillCatalogError("catalog_io_error") from None

        directories: list[Path] = []
        for entry in entries:
            try:
                if entry.is_symlink():
                    raise SkillCatalogError("symlink_not_allowed")
                if entry.is_dir():
                    directories.append(entry)
            except OSError:
                raise SkillCatalogError("catalog_io_error") from None
        if len(directories) > _MAX_SKILLS:
            raise SkillCatalogError("too_many_skills")

        skills: list[SkillDefinition] = []
        names: set[str] = set()
        for directory in directories:
            if _SKILL_NAME_PATTERN.fullmatch(directory.name) is None:
                raise SkillCatalogError("invalid_skill_directory")
            skill = self._load_skill(directory)
            if skill.name in names:
                raise SkillCatalogError("duplicate_skill_name")
            names.add(skill.name)
            skills.append(skill)
        return tuple(skills)

    def _load_skill(self, directory: Path) -> SkillDefinition:
        document = self._read_utf8(
            directory / "SKILL.md",
            max_bytes=_MAX_SKILL_BYTES,
            missing_code="skill_file_missing",
            too_large_code="skill_too_large",
            invalid_type_code="skill_file_invalid",
            invalid_utf8_code="skill_not_utf8",
        )
        name, description, instructions = _parse_skill_document(document)
        if name != directory.name:
            raise SkillCatalogError("invalid_frontmatter")

        targets = _extract_reference_targets(instructions)
        if len(targets) > _MAX_REFERENCES:
            raise SkillCatalogError("too_many_references")
        references: list[SkillReference] = []
        total_reference_bytes = 0
        for target in targets:
            content = self._read_utf8(
                directory.joinpath(*PurePosixPath(target).parts),
                max_bytes=_MAX_REFERENCE_BYTES,
                missing_code="reference_missing",
                too_large_code="reference_too_large",
                invalid_type_code="reference_invalid",
                invalid_utf8_code="reference_not_utf8",
            )
            total_reference_bytes += len(content.encode("utf-8"))
            if total_reference_bytes > _MAX_TOTAL_REFERENCE_BYTES:
                raise SkillCatalogError("references_too_large")
            references.append(SkillReference(path=target, content=content))

        return SkillDefinition(
            name=name,
            description=description,
            instructions=instructions,
            references=tuple(references),
        )

    def _read_utf8(
        self,
        candidate: Path,
        *,
        max_bytes: int,
        missing_code: str,
        too_large_code: str,
        invalid_type_code: str,
        invalid_utf8_code: str,
    ) -> str:
        resolved = self._resolve_file(candidate, missing_code=missing_code)
        try:
            with resolved.open("rb") as source:
                if os.fstat(source.fileno()).st_size > max_bytes:
                    raise SkillCatalogError(too_large_code)
                payload = source.read(max_bytes + 1)
        except SkillCatalogError:
            raise
        except IsADirectoryError:
            raise SkillCatalogError(invalid_type_code) from None
        except PermissionError:
            raise SkillCatalogError("file_permission_denied") from None
        except OSError:
            raise SkillCatalogError("file_io_error") from None
        if len(payload) > max_bytes:
            raise SkillCatalogError(too_large_code)
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError:
            raise SkillCatalogError(invalid_utf8_code) from None

    def _resolve_file(self, candidate: Path, *, missing_code: str) -> Path:
        try:
            relative = candidate.relative_to(self._root)
        except ValueError:
            raise SkillCatalogError("path_outside_root") from None

        current = self._root
        try:
            for part in relative.parts:
                current /= part
                if current.is_symlink():
                    raise SkillCatalogError("symlink_not_allowed")
            resolved = candidate.resolve(strict=True)
            resolved.relative_to(self._root)
        except SkillCatalogError:
            raise
        except FileNotFoundError:
            raise SkillCatalogError(missing_code) from None
        except (OSError, RuntimeError, ValueError):
            raise SkillCatalogError("path_outside_root") from None
        if not resolved.is_file():
            raise SkillCatalogError("path_not_file")
        return resolved


def default_skill_catalog() -> SkillCatalog:
    project_root = Path(__file__).resolve().parents[3]
    return SkillCatalog(project_root / "skills")


def _parse_skill_document(document: str) -> tuple[str, str, str]:
    lines = document.splitlines()
    if not lines or lines[0] != "---":
        raise SkillCatalogError("invalid_frontmatter")

    closing_index: int | None = None
    for index, line in enumerate(
        lines[1 : _MAX_FRONTMATTER_LINES + 1],
        start=1,
    ):
        if line == "---":
            closing_index = index
            break
    if closing_index is None:
        raise SkillCatalogError("invalid_frontmatter")

    metadata: dict[str, str] = {}
    for line in lines[1:closing_index]:
        if not line or line != line.strip() or ":" not in line:
            raise SkillCatalogError("invalid_frontmatter")
        key, raw_value = line.split(":", maxsplit=1)
        if key not in {"name", "description"} or key in metadata:
            raise SkillCatalogError("invalid_frontmatter")
        metadata[key] = _parse_metadata_scalar(raw_value.strip())

    name = metadata.get("name", "")
    description = metadata.get("description", "")
    instructions = "\n".join(lines[closing_index + 1 :]).strip()
    if _SKILL_NAME_PATTERN.fullmatch(name) is None:
        raise SkillCatalogError("invalid_frontmatter")
    if (
        not description
        or len(description) > 2_000
        or any(not character.isprintable() for character in description)
        or not instructions
    ):
        raise SkillCatalogError("invalid_frontmatter")
    return name, description, instructions


def _parse_metadata_scalar(raw_value: str) -> str:
    if not raw_value:
        raise SkillCatalogError("invalid_frontmatter")
    if raw_value.startswith('"'):
        try:
            value = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            raise SkillCatalogError("invalid_frontmatter") from None
        if not isinstance(value, str):
            raise SkillCatalogError("invalid_frontmatter")
        return value
    if raw_value.startswith("'"):
        if len(raw_value) < 2 or not raw_value.endswith("'"):
            raise SkillCatalogError("invalid_frontmatter")
        return raw_value[1:-1].replace("''", "'")
    if raw_value[0] in "[{&*!|>@`" or " #" in raw_value:
        raise SkillCatalogError("invalid_frontmatter")
    return raw_value


def _extract_reference_targets(instructions: str) -> tuple[str, ...]:
    targets: list[str] = []
    seen: set[str] = set()
    for match in _MARKDOWN_LINK_PATTERN.finditer(instructions):
        raw_target = match.group(1).strip()
        try:
            parsed = urlsplit(raw_target)
        except ValueError:
            raise SkillCatalogError("invalid_reference") from None
        if parsed.scheme or parsed.netloc or not parsed.path:
            continue
        if (
            parsed.query
            or "\\" in raw_target
            or "%" in raw_target
            or raw_target.startswith("#")
        ):
            raise SkillCatalogError("invalid_reference")
        path = PurePosixPath(parsed.path)
        parts = path.parts
        if (
            path.is_absolute()
            or len(parts) < 2
            or parts[0] != "references"
            or any(part in {"", ".", ".."} for part in parts)
            or any(
                _REFERENCE_PART_PATTERN.fullmatch(part) is None
                for part in parts
            )
            or path.suffix.lower() != ".md"
        ):
            raise SkillCatalogError("invalid_reference")
        normalized = path.as_posix()
        if normalized not in seen:
            seen.add(normalized)
            targets.append(normalized)
    return tuple(targets)
