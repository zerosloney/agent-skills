"""Tests for the maintenance scripts (count_rules.py, find_uncovered.py).

These run the scripts as subprocesses and assert their contracts:
- count_rules exits 0 when code matches DECLARED_TOTAL, non-zero on drift
- find_uncovered exits 0 when all rules have tests, non-zero on gaps
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_CLI_DIR = Path(__file__).resolve().parent.parent / "scripts"


def _run(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(_CLI_DIR / script)],
        capture_output=True, text=True, timeout=30,
    )


class TestCountRules:
    def test_exits_zero_when_no_drift(self):
        # The fixture set is in sync (13 rules). If this fails, either the
        # code changed (update DECLARED_TOTAL) or the docs drifted.
        proc = _run("count_rules.py")
        assert proc.returncode == 0, proc.stderr or proc.stdout
        assert "Total self-authored rules : 13" in proc.stdout

    def test_reports_dimension_and_triage_breakdown(self):
        proc = _run("count_rules.py")
        assert "By dimension:" in proc.stdout
        assert "By triage:" in proc.stdout
        assert "By severity:" in proc.stdout

    def test_lists_all_rule_ids(self):
        proc = _run("count_rules.py")
        for rid in ("SEC-REACT-001", "SEC-REACT-002", "RELI-JS-002", "SEC-SECRET-004"):
            assert rid in proc.stdout


class TestFindUncovered:
    def test_exits_zero_when_all_covered(self):
        proc = _run("find_uncovered.py")
        assert proc.returncode == 0, proc.stderr or proc.stdout
        assert "Uncovered (no test)   : 0" in proc.stdout
        assert "All registered rules have at least one test reference" in proc.stdout

    def test_reports_counts(self):
        proc = _run("find_uncovered.py")
        assert "Registered rules      : 13" in proc.stdout
        assert "Referenced in tests   : 13" in proc.stdout
