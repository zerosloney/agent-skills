"""In-process tests for engine.run_scan (covers the orchestration logic that
e2e tests exercise only via subprocess, where coverage is not attributed).

Covers: tier ordering, dimension filtering, dedup, triage back-fill, the
B1 empty-path error state, and degradation-notice collection.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from audit.engine import run_scan, safe_read_file


def _make_proj(tmp_path: Path, files: dict[str, str]) -> Path:
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    return tmp_path


class TestRunScanBasics:
    def test_returns_well_formed_result(self, tmp_path):
        proj = _make_proj(tmp_path, {"src/a.js": "eval(x);\n"})
        r = run_scan(str(proj), run_lint=False, run_deps=False)
        assert r["error"] is None
        assert r["files_scanned"] == 1
        assert any(f["rule"] == "SEC-JS-001" for f in r["findings"])
        assert r["score"]["overall"] < 100
        assert r["by_severity"]["error"] >= 1
        assert r["triage_summary"]["total"] >= 1
        assert r["deps_summary"] is None  # run_deps=False

    def test_dedup_collapses_same_file_line_rule(self, tmp_path):
        # two eval calls on the same line produce two matches but the same
        # file:line:rule key → dedup keeps just one (the dedup contract).
        proj = _make_proj(tmp_path, {"a.js": "eval(x); eval(x);\n"})
        r = run_scan(str(proj), run_lint=False, run_deps=False)
        sev001 = [f for f in r["findings"] if f["rule"] == "SEC-JS-001"]
        assert len(sev001) == 1

    def test_distinct_lines_not_deduped(self, tmp_path):
        # eval on two different lines stays as two findings.
        proj = _make_proj(tmp_path, {"a.js": "eval(x);\neval(y);\n"})
        r = run_scan(str(proj), run_lint=False, run_deps=False)
        sev001 = [f for f in r["findings"] if f["rule"] == "SEC-JS-001"]
        assert len(sev001) == 2

    def test_findings_sorted_by_severity_then_file(self, tmp_path):
        proj = _make_proj(tmp_path, {
            "z.js": "el.innerHTML = x;\n",   # error
            "a.js": "useEffect(async () => { await f(); }, []);\n",  # warning
        })
        r = run_scan(str(proj), run_lint=False, run_deps=False)
        sevs = [f["severity"] for f in r["findings"]]
        # errors before warnings
        assert sevs == sorted(sevs, key=lambda s: {"error": 0, "warning": 1, "info": 2}[s])


class TestDimensionFiltering:
    def test_security_only_excludes_reliability(self, tmp_path):
        proj = _make_proj(tmp_path, {
            "a.js": "eval(x);\n",                              # SEC-JS-001 (security)
            "b.js": "useEffect(async () => { await f(); }, []);\n",  # RELI-JS-001
        })
        r = run_scan(str(proj), dimensions=["security"], run_lint=False, run_deps=False)
        rules = {f["rule"] for f in r["findings"]}
        assert "SEC-JS-001" in rules
        assert "RELI-JS-001" not in rules

    def test_all_dimensions_keeps_everything(self, tmp_path):
        proj = _make_proj(tmp_path, {
            "a.js": "eval(x);\n",
            "b.js": "useEffect(async () => { await f(); }, []);\n",
        })
        r = run_scan(str(proj), dimensions=None, run_lint=False, run_deps=False)
        rules = {f["rule"] for f in r["findings"]}
        assert "SEC-JS-001" in rules
        assert "RELI-JS-001" in rules


class TestEmptyPathState:
    """B1: empty/invalid paths surface an error state, not a clean pass."""

    def test_nonexistent_dir_returns_error(self, tmp_path):
        r = run_scan(str(tmp_path / "nope"), run_lint=False, run_deps=False)
        assert r["error"] == "NOT_A_DIRECTORY"
        assert r["score"] is None
        assert r["files_scanned"] == 0

    def test_dir_with_no_js_returns_no_files(self, tmp_path):
        (tmp_path / "readme.md").write_text("no js", encoding="utf-8")
        r = run_scan(str(tmp_path), run_lint=False, run_deps=False)
        assert r["error"] == "NO_FILES"
        assert r["score"] is None


class TestDegradationNotices:
    def test_no_lint_adds_skip_notice(self, tmp_path):
        proj = _make_proj(tmp_path, {"a.js": "const x = 1;\n"})
        r = run_scan(str(proj), run_lint=False, run_deps=False)
        assert any("eslint/tsc skipped" in n for n in r["degradation_notices"])

    def test_no_deps_adds_skip_notice(self, tmp_path):
        proj = _make_proj(tmp_path, {"a.js": "const x = 1;\n"})
        r = run_scan(str(proj), run_lint=False, run_deps=False)
        assert any("dependency analysis skipped" in n for n in r["degradation_notices"])


class TestSafeReadFile:
    def test_reads_utf8(self, tmp_path):
        p = tmp_path / "f.js"
        p.write_text("const x = 'héllo';\n", encoding="utf-8")
        assert "héllo" in safe_read_file(str(p))

    def test_falls_back_on_bad_encoding(self, tmp_path):
        p = tmp_path / "f.js"
        p.write_bytes(b"const x = '\xff\xfe';\n")
        # should not raise (latin-1 catches any byte)
        content = safe_read_file(str(p))
        assert "const x" in content

    def test_raises_on_unreadable(self, tmp_path):
        from audit.errors import AuditError
        with pytest.raises(AuditError):
            safe_read_file(str(tmp_path / "missing.js"))
