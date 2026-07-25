"""Tests for file discovery (discover_files) — path safety + scoping.

Covers H6 (symlink traversal) and the skip-dir / extension filtering contract.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from audit.visitors import discover_files


def _write(path: Path, content: str = "x"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestDiscoverFiles:
    def test_finds_js_ts_variants(self, tmp_path):
        for ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte"):
            _write(tmp_path / f"f{ext}")
        _write(tmp_path / "ignore.txt")
        files = {p.name for p in discover_files(tmp_path)}
        assert files == {f"f{ext}" for ext in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs", ".vue", ".svelte")}
        assert "ignore.txt" not in files

    def test_skips_lockfiles(self, tmp_path):
        for name in ("package-lock.json", "yarn.lock", "pnpm-lock.yaml"):
            _write(tmp_path / name)
        assert discover_files(tmp_path) == []

    def test_skips_common_build_dirs(self, tmp_path):
        for d in ("node_modules", "dist", "build", ".next"):
            _write(tmp_path / d / "x.js")
        _write(tmp_path / "keep.js")
        found = {p.name for p in discover_files(tmp_path)}
        assert found == {"keep.js"}

    def test_does_not_follow_symlinked_dirs(self, tmp_path):
        """H6 regression: a symlinked directory must NOT pull in external files.

        Without this, a symlink inside the project could aim the audit at an
        arbitrary location (e.g. ~/.ssh) and leak secrets via SEC-SECRET-*.
        """
        external = tmp_path.parent / "external_target"
        external.mkdir()
        _write(external / "secret.js", 'const k = "AKIA" + "A"*16;')
        _write(tmp_path / "safe.js")

        link = tmp_path / "evil"
        try:
            os.symlink(external, link, target_is_directory=True)
        except (OSError, NotImplementedError):
            pytest.skip("symlinks not supported on this platform/privilege level")

        found = {p.name for p in discover_files(tmp_path)}
        assert "safe.js" in found
        assert "secret.js" not in found, "discover_files followed a symlink out of the target tree"
