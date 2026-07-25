"""Tests for the linter orchestration adapters.

We monkeypatch the resolver + subprocess.run to feed canned eslint/tsc output,
so these tests never depend on Node being installed.
"""
from __future__ import annotations

import json

import pytest

import audit.linters as L


# ───────────────────────── eslint ─────────────────────────

ESLINT_JSON_SAMPLE = json.dumps([
    {
        "filePath": "/proj/src/a.js",
        "messages": [
            {"line": 3, "column": 5, "severity": 2, "ruleId": "no-unused-vars", "message": "'x' is defined but never used."},
            {"line": 10, "column": 1, "severity": 1, "ruleId": "no-console", "message": "Unexpected console statement."},
        ],
    }
])


def _fake_run(rc, out, err=""):
    """Build the (rc, out, err) tuple that the patched _run must return."""
    return (rc, out, err)


class TestEslint:
    def test_missing_binary_returns_notice(self, monkeypatch):
        monkeypatch.setattr(L, "_resolve_eslint", lambda root: None)
        findings, notice = L.run_eslint("/proj")
        assert findings == []
        assert "eslint not found" in notice

    def test_parses_findings_and_folds_to_summary(self, monkeypatch, tmp_path):
        # create the project dir so relative_to works
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "src").mkdir()
        monkeypatch.setattr(L, "_resolve_eslint", lambda root: "eslint")
        monkeypatch.setattr(L, "_run", lambda cmd, cwd, timeout=120: _fake_run(1, ESLINT_JSON_SAMPLE))
        findings, notice = L.run_eslint(str(proj))
        assert notice is None
        # default folds to a single summary finding
        assert len(findings) == 1
        assert findings[0].rule == "ESLINT-SUMMARY"
        assert findings[0].source == "eslint"

    def test_include_detail_returns_all(self, monkeypatch, tmp_path):
        proj = tmp_path / "proj"
        proj.mkdir()
        monkeypatch.setattr(L, "_resolve_eslint", lambda root: "eslint")
        monkeypatch.setattr(L, "_run", lambda cmd, cwd, timeout=120: _fake_run(1, ESLINT_JSON_SAMPLE))
        findings, _ = L.run_eslint(str(proj), include_detail=True)
        assert len(findings) == 2
        assert findings[0].source == "eslint"
        assert findings[0].severity in ("error", "warning")

    def test_config_error_surfaces_as_notice(self, monkeypatch, tmp_path):
        monkeypatch.setattr(L, "_resolve_eslint", lambda root: "eslint")
        monkeypatch.setattr(L, "_run", lambda cmd, cwd, timeout=120: _fake_run(2, "", "ESLint config invalid"))
        findings, notice = L.run_eslint(str(tmp_path))
        assert findings == []
        assert "config error" in notice.lower()


# ───────────────────────── tsc ─────────────────────────

class TestTsc:
    def test_missing_binary(self, monkeypatch):
        monkeypatch.setattr(L, "_resolve_tsc", lambda root: None)
        findings, notice = L.run_tsc("/proj")
        assert findings == []
        assert "tsc not found" in notice

    def test_success_no_findings(self, monkeypatch):
        monkeypatch.setattr(L, "_resolve_tsc", lambda root: "tsc")
        monkeypatch.setattr(L, "_run", lambda cmd, cwd, timeout=180: _fake_run(0, ""))
        findings, notice = L.run_tsc("/proj")
        assert findings == []
        assert notice is None

    def test_type_errors_produce_finding(self, monkeypatch):
        monkeypatch.setattr(L, "_resolve_tsc", lambda root: "tsc")
        monkeypatch.setattr(L, "_run", lambda cmd, cwd, timeout=180: _fake_run(1, "src/a.ts(10,5): error TS2322: Type 'string' is not assignable to type 'number'."))
        findings, notice = L.run_tsc("/proj")
        assert notice is None
        assert len(findings) == 1
        assert findings[0].rule == "TSC-ERROR"
        assert findings[0].severity == "error"
        assert "TS2322" in findings[0].message
