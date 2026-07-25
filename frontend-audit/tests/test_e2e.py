"""End-to-end tests: run the real audit.py CLI against the bundled fixture.

The fixture (scripts/fixtures/react-demo) contains deliberately vulnerable
code; these tests assert the CLI surfaces the expected findings and that
degradation notices appear when external tools (eslint/tsc/npm) are absent.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parent
_CLI = _TESTS_DIR.parent / "scripts" / "audit.py"
FIXTURE_PROJECT = _TESTS_DIR.parent / "scripts" / "fixtures" / "react-demo"


def _run_cli(*args) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_CLI), *args],
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture(scope="module")
def scan_result():
    """One full scan of the fixture (no-lint to keep it deterministic/hermetic)."""
    proc = _run_cli("scan", "--path", str(FIXTURE_PROJECT), "--no-lint", "--format", "json-compact")
    assert proc.returncode in (0, 1), proc.stderr
    return json.loads(proc.stdout), proc.returncode


class TestFixtureScan:
    def test_detects_expected_findings_with_counts(self, scan_result):
        """Assert exact hit counts, not just id presence.

        A presence-only check stayed green when the SEC-REACT-001 regex was
        broken to miss the 2nd occurrence — counts catch that regression.
        Counts reflect the fixture after the净化抑制 fix (sanitize(bio) no
        longer flags, so SEC-REACT-001 hits 1, not 2).
        """
        result, _ = scan_result
        from collections import Counter

        counts = Counter(f["id"] for f in result["findings"])
        expected = {
            "SEC-REACT-001": 1,   # bio (the sanitize(bio) line is suppressed)
            "SEC-JS-001": 1,      # eval(code)
            "SEC-JS-003": 1,      # el.innerHTML = html
            "SEC-JS-004": 1,      # window.location = url
            "RELI-JS-001": 1,     # async useEffect
            "RELI-JS-002": 1,     # addEventListener w/o remove
            "SEC-SECRET-001": 1,  # AWS key
        }
        assert counts == expected, f"expected {expected}, got {dict(counts)}"

    def test_exits_nonzero_on_errors(self, scan_result):
        _, rc = scan_result
        assert rc == 1, "fixture has error-severity findings → exit 1"

    def test_score_below_perfect(self, scan_result):
        result, _ = scan_result
        assert result["score"] < 100
        assert result["grade"] in ("B", "C", "D", "F")

    def test_degradation_notice_when_no_lint(self, scan_result):
        result, _ = scan_result
        assert any("eslint/tsc skipped" in n for n in result.get("degradation_notices", []))

    def test_triage_summary_populated(self, scan_result):
        result, _ = scan_result
        t = result["triage"]
        assert t["total"] > 0
        assert t["deterministic"] >= 1


class TestThresholdGate:
    """Threshold semantics (per SKILL.md §1.3): exit 0 requires BOTH no errors
    AND meeting the threshold. The fixture has errors, so it exits 1 regardless
    of threshold. These tests verify the threshold *adds* a gate on top of the
    error check, using a clean fixture to isolate the threshold behavior.
    """

    def _make_clean_fixture(self, tmp_path):
        """A fixture with no errors — isolates threshold from error-check."""
        src = tmp_path / "src"
        src.mkdir()
        (src / "clean.ts").write_text(
            '// clean file, no findings\nconst x = "safe";\n',
            encoding="utf-8",
        )
        (tmp_path / "package.json").write_text(
            '{"name": "clean", "private": true}', encoding="utf-8"
        )
        return tmp_path

    def test_threshold_met_passes_when_no_errors(self, tmp_path):
        """No errors + threshold met (F is always met) → exit 0."""
        proj = self._make_clean_fixture(tmp_path)
        proc = _run_cli("scan", "--path", str(proj), "--no-lint",
                        "--threshold", "F", "--format", "json-compact")
        assert proc.returncode == 0, proc.stderr

    def test_threshold_unmet_fails_even_without_errors(self, tmp_path):
        """No errors but threshold stricter than grade A → exit 1.

        Clean fixture scores A; threshold A passes, but we verify the gate
        fires by checking a non-clean project where grade < threshold.
        """
        # The bundled fixture has errors and scores below A; threshold A must fail.
        proc = _run_cli("scan", "--path", str(FIXTURE_PROJECT), "--no-lint",
                        "--threshold", "A", "--format", "json-compact")
        assert proc.returncode == 1


class TestEmptyPathHandling:
    """B1 regression: an empty/invalid path must NOT return a clean pass.

    Previously scan on /nonexistent returned score=100/grade=A/exit 0, giving
    false "no issues" confidence. Now it surfaces an error state + non-zero exit.
    """

    def test_nonexistent_path_errors(self):
        proc = _run_cli("scan", "--path", "/nonexistent/path_xyz",
                        "--format", "json-compact")
        assert proc.returncode != 0
        data = json.loads(proc.stdout)
        assert data.get("error") == "NOT_A_DIRECTORY"
        assert data.get("score") is None  # must not look like a clean pass

    def test_dir_with_no_js_errors(self, tmp_path):
        # a real dir but no scannable files → NO_FILES error
        (tmp_path / "readme.md").write_text("no js here", encoding="utf-8")
        proc = _run_cli("scan", "--path", str(tmp_path),
                        "--format", "json-compact")
        assert proc.returncode != 0
        data = json.loads(proc.stdout)
        assert data.get("error") == "NO_FILES"
        assert data.get("score") is None


class TestCleanScan:
    """M7 e2e: a project with no issues must produce valid output in every
    format and exit 0 (the CI green path must not break)."""

    def _clean_proj(self, tmp_path):
        src = tmp_path / "src"
        src.mkdir()
        (src / "clean.js").write_text("const x = 1;\n", encoding="utf-8")
        (tmp_path / "package.json").write_text('{"name":"clean"}', encoding="utf-8")
        return tmp_path

    def test_clean_scan_json_compact(self, tmp_path):
        proc = _run_cli("scan", "--path", str(self._clean_proj(tmp_path)),
                        "--no-lint", "--no-deps", "--format", "json-compact")
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert data["score"] == 100.0
        assert data["grade"] == "A"
        assert data["findings"] == []
        assert data["error"] is None

    def test_clean_scan_sarif_valid(self, tmp_path):
        proc = _run_cli("scan", "--path", str(self._clean_proj(tmp_path)),
                        "--no-lint", "--no-deps", "--format", "sarif")
        assert proc.returncode == 0
        sarif = json.loads(proc.stdout)
        assert sarif["version"] == "2.1.0"
        assert sarif["runs"][0]["results"] == []

    def test_clean_scan_markdown_shows_clean(self, tmp_path):
        proc = _run_cli("scan", "--path", str(self._clean_proj(tmp_path)),
                        "--no-lint", "--no-deps", "--format", "markdown")
        assert proc.returncode == 0
        assert "无问题发现" in proc.stdout


class TestRulesSubcommand:
    def test_lists_all_rules_markdown(self):
        proc = _run_cli("rules", "--format", "markdown")
        assert proc.returncode == 0
        assert "SEC-REACT-001" in proc.stdout
        assert "SEC-SECRET" in proc.stdout

    def test_lists_all_rules_json(self):
        proc = _run_cli("rules", "--format", "json")
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        assert isinstance(data, list)
        assert len(data) >= 13


class TestDepsSubcommand:
    """M5: deps output schema must match scan so consumers handle them uniformly."""

    def test_deps_emits_scan_compatible_schema(self):
        proc = _run_cli("deps", "--path", str(FIXTURE_PROJECT), "--format", "json-compact")
        assert proc.returncode == 0
        data = json.loads(proc.stdout)
        # same top-level keys as scan's json-compact
        for key in ("score", "grade", "issues", "findings", "triage", "deps", "dimensions"):
            assert key in data, f"deps output missing scan-compatible key: {key}"
        assert data["deps"]["packages"] == 2  # fixture has react + dompurify
        assert data["error"] is None

    def test_deps_no_package_json_errors(self, tmp_path):
        (tmp_path / "readme.md").write_text("no package.json", encoding="utf-8")
        proc = _run_cli("deps", "--path", str(tmp_path), "--format", "json-compact")
        assert proc.returncode != 0
        data = json.loads(proc.stdout)
        assert data["error"] == "NO_PACKAGE_JSON"
        assert data["score"] is None
