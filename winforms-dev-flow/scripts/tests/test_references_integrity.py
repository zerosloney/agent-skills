"""Tests for reference integrity — ensures no dangling or orphan files.

For a documentation skill, the "bone" is the cross-reference graph between
SKILL.md → references/*.md → examples/*.md. These tests guard against drift.
"""

import re
import os
import sys
from pathlib import Path

import pytest

_SKILL_ROOT = Path(__file__).resolve().parent.parent.parent
SKILL_MD = _SKILL_ROOT / "SKILL.md"
REFS_DIR = _SKILL_ROOT / "references"
EXAMPLES_DIR = _SKILL_ROOT / "examples"


def _extract_refs_from_skillmd() -> set[str]:
    """Extract all references/*.md filenames mentioned in SKILL.md."""
    text = SKILL_MD.read_text(encoding="utf-8")
    return set(re.findall(r"references/([a-zA-Z0-9._-]+\.md)", text))


def _extract_examples_from_skillmd() -> set[str]:
    """Extract all examples/*.md filenames mentioned in SKILL.md."""
    text = SKILL_MD.read_text(encoding="utf-8")
    return set(re.findall(r"examples/(example-[a-zA-Z0-9._-]+\.md)", text))


# ============================================================
# Reference files exist
# ============================================================

class TestReferencesExist:
    def test_all_referenced_files_exist(self):
        """Every references/*.md cited in SKILL.md must exist on disk."""
        cited = _extract_refs_from_skillmd()
        missing = {f for f in cited if not (REFS_DIR / f).is_file()}
        assert not missing, f"SKILL.md references missing files: {sorted(missing)}"

    def test_no_orphan_reference_files(self):
        """Every reference file on disk should be cited in SKILL.md (except indirect refs)."""
        cited = _extract_refs_from_skillmd()
        # designer-template-a-crud.md and designer-template-b-form.md are
        # referenced via designer-template-list.md (indirect), not SKILL.md directly
        indirect = {"designer-template-a-crud.md", "designer-template-b-form.md"}
        disk = {f for f in os.listdir(str(REFS_DIR)) if f.endswith(".md")}
        orphans = disk - cited - indirect
        assert not orphans, f"Orphan reference files (not cited anywhere): {sorted(orphans)}"


# ============================================================
# Example files exist
# ============================================================

class TestExamplesExist:
    def test_all_cited_examples_exist(self):
        """Every examples/*.md cited in SKILL.md must exist on disk."""
        cited = _extract_examples_from_skillmd()
        missing = {f for f in cited if not (EXAMPLES_DIR / f).is_file()}
        assert not missing, f"SKILL.md cites missing examples: {sorted(missing)}"

    def test_no_orphan_examples(self):
        """Every example file on disk should be cited in SKILL.md."""
        cited = _extract_examples_from_skillmd()
        disk = {f for f in os.listdir(str(EXAMPLES_DIR)) if f.endswith(".md")}
        orphans = disk - cited
        assert not orphans, f"Orphan example files: {sorted(orphans)}"


# ============================================================
# Cross-references between reference files resolve
# ============================================================

class TestCrossReferences:
    def test_cross_refs_resolve(self):
        """References that cite other references/*.md must point to existing files."""
        disk_refs = {f for f in os.listdir(str(REFS_DIR)) if f.endswith(".md")}
        for ref_file in sorted(disk_refs):
            text = (REFS_DIR / ref_file).read_text(encoding="utf-8")
            # Only check references/ prefixed paths (not bare filenames in prose)
            cited = set(re.findall(r"references/([a-zA-Z0-9._-]+\.md)", text))
            missing = {f for f in cited if f not in disk_refs}
            if missing:
                pytest.fail(f"{ref_file} references non-existent files: {sorted(missing)}")
