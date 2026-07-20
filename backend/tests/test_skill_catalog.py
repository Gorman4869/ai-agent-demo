from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from backend.app.skills import (
    SkillCatalog,
    SkillCatalogError,
    SkillDefinition,
    SkillResolver,
    SkillResolverError,
    default_skill_catalog,
)


class ExistingSkillCatalogTest(unittest.TestCase):
    def test_research_summary_loads_with_bounded_reference(self) -> None:
        catalog = default_skill_catalog()

        first = catalog.load()
        second = catalog.load()

        self.assertIs(first, second)
        self.assertEqual(1, len(first))
        skill = first[0]
        self.assertEqual("research-summary", skill.name)
        self.assertIn("evidence-grounded", skill.description)
        self.assertIn("## Workflow", skill.instructions)
        self.assertEqual(1, len(skill.references))
        self.assertEqual(
            "references/output-contract.md",
            skill.references[0].path,
        )
        self.assertIn("citation correctness", skill.references[0].content)
        self.assertNotIn("openai.yaml", repr(skill.references))

    def test_resolver_supports_explicit_automatic_and_no_match(self) -> None:
        resolver = SkillResolver(default_skill_catalog())

        explicit = resolver.resolve("Use $research-summary for these notes.")
        automatic = resolver.resolve("Prepare a research summary from evidence.")
        unmatched = resolver.resolve("Refactor this Python module.")

        self.assertEqual(("research-summary",), _names(explicit))
        self.assertEqual(("research-summary",), _names(automatic))
        self.assertEqual((), unmatched)

        with self.assertRaises(SkillResolverError) as raised:
            resolver.resolve("Use $missing-skill now.")
        self.assertEqual("skill_not_found", raised.exception.code)


class SkillCatalogBoundaryTest(unittest.TestCase):
    def test_refresh_replaces_the_cached_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_file = _write_skill(root, description="First description.")
            catalog = SkillCatalog(root)

            first = catalog.load()
            skill_file.write_text(
                _skill_document(description="Second description."),
                encoding="utf-8",
            )
            cached = catalog.load()
            refreshed = catalog.refresh()

            self.assertIs(first, cached)
            self.assertEqual("First description.", cached[0].description)
            self.assertIsNot(first, refreshed)
            self.assertEqual("Second description.", refreshed[0].description)

    def test_invalid_frontmatter_fails_with_stable_error(self) -> None:
        cases = (
            "# Missing frontmatter",
            "---\nname: demo-skill\nunknown: value\n---\nBody",
            "---\nname: other-skill\ndescription: Safe.\n---\nBody",
            (
                "---\nname: demo-skill\n"
                "description: !python/object:danger\n---\nBody"
            ),
        )

        for document in cases:
            with self.subTest(document=document[:20]):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    _write_raw_skill(root, document)
                    with self.assertRaises(SkillCatalogError) as raised:
                        SkillCatalog(root).load()
                    self.assertEqual(
                        "invalid_frontmatter",
                        raised.exception.code,
                    )
                    self.assertNotIn(str(root), str(raised.exception))

    def test_missing_and_escaping_references_are_rejected(self) -> None:
        cases = (
            ("[missing](references/missing.md)", "reference_missing"),
            ("[outside](../outside.md)", "invalid_reference"),
            (
                "[escape](references/../../outside.md)",
                "invalid_reference",
            ),
            ("[malformed](http://[)", "invalid_reference"),
        )

        for body, expected_code in cases:
            with self.subTest(expected_code=expected_code):
                with tempfile.TemporaryDirectory() as temporary:
                    root = Path(temporary)
                    _write_skill(root, body=body)
                    with self.assertRaises(SkillCatalogError) as raised:
                        SkillCatalog(root).load()
                    self.assertEqual(expected_code, raised.exception.code)

    def test_oversized_skill_and_reference_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_skill(root, body="x" * 65_000)
            with self.assertRaises(SkillCatalogError) as oversized_skill:
                SkillCatalog(root).load()
            self.assertEqual("skill_too_large", oversized_skill.exception.code)

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_skill(
                root,
                body="[large](references/large.md)",
                references={"large.md": "x" * 65_000},
            )
            with self.assertRaises(SkillCatalogError) as oversized_reference:
                SkillCatalog(root).load()
            self.assertEqual(
                "reference_too_large",
                oversized_reference.exception.code,
            )

    def test_non_utf8_skill_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_root = root / "demo-skill"
            skill_root.mkdir()
            (skill_root / "SKILL.md").write_bytes(b"\xff\xfe")

            with self.assertRaises(SkillCatalogError) as raised:
                SkillCatalog(root).load()
            self.assertEqual("skill_not_utf8", raised.exception.code)

    def test_symlinked_reference_outside_root_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "skills"
            outside = Path(temporary) / "outside.md"
            outside.write_text("outside-secret", encoding="utf-8")
            _write_skill(
                root,
                body="[outside](references/outside.md)",
            )
            link = root / "demo-skill" / "references" / "outside.md"
            link.parent.mkdir(exist_ok=True)
            try:
                link.symlink_to(outside)
            except OSError:
                link.write_text("fallback", encoding="utf-8")
                original_is_symlink = Path.is_symlink
                with patch.object(
                    Path,
                    "is_symlink",
                    new=lambda candidate: (
                        candidate == link or original_is_symlink(candidate)
                    ),
                ):
                    self._assert_symlink_rejected(root)
                return

            self._assert_symlink_rejected(root)

    def test_unrelated_files_are_not_loaded_or_executed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            skill_file = _write_skill(root)
            marker = root / "executed.txt"
            (skill_file.parent / "payload.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
                encoding="utf-8",
            )

            skills = SkillCatalog(root).load()

            self.assertEqual(1, len(skills))
            self.assertEqual((), skills[0].references)
            self.assertFalse(marker.exists())

    def test_invalid_query_is_bounded_without_exposing_content(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_skill(root)
            resolver = SkillResolver(SkillCatalog(root))
            secret = "private-query" + "x" * 8_000

            with self.assertRaises(SkillResolverError) as raised:
                resolver.resolve(secret)
            self.assertEqual("invalid_query", raised.exception.code)
            self.assertNotIn("private-query", str(raised.exception))

    def _assert_symlink_rejected(self, root: Path) -> None:
        with self.assertRaises(SkillCatalogError) as raised:
            SkillCatalog(root).load()
        self.assertEqual("symlink_not_allowed", raised.exception.code)
        self.assertNotIn("outside-secret", str(raised.exception))


def _write_skill(
    root: Path,
    *,
    description: str = "Demo skill description.",
    body: str = "Follow the bounded workflow.",
    references: dict[str, str] | None = None,
) -> Path:
    skill_root = root / "demo-skill"
    skill_root.mkdir(parents=True)
    skill_file = skill_root / "SKILL.md"
    skill_file.write_text(
        _skill_document(description=description, body=body),
        encoding="utf-8",
    )
    for name, content in (references or {}).items():
        reference_root = skill_root / "references"
        reference_root.mkdir(exist_ok=True)
        (reference_root / name).write_text(content, encoding="utf-8")
    return skill_file


def _write_raw_skill(root: Path, document: str) -> Path:
    skill_root = root / "demo-skill"
    skill_root.mkdir(parents=True)
    skill_file = skill_root / "SKILL.md"
    skill_file.write_text(document, encoding="utf-8")
    return skill_file


def _skill_document(
    *,
    description: str = "Demo skill description.",
    body: str = "Follow the bounded workflow.",
) -> str:
    return (
        "---\n"
        "name: demo-skill\n"
        f"description: {description}\n"
        "---\n\n"
        f"{body}\n"
    )


def _names(skills: tuple[SkillDefinition, ...]) -> tuple[str, ...]:
    return tuple(skill.name for skill in skills)


if __name__ == "__main__":
    unittest.main()
