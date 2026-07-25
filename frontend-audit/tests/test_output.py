"""Tests for output formatters: json / json-compact / sarif / markdown."""
from __future__ import annotations

import json

from audit.output import format_json_compact, format_markdown, format_sarif


def _result():
    return {
        "project_root": "/proj",
        "files_scanned": 2,
        "findings": [
            {
                "file": "src/a.tsx", "line": 5, "column": 0, "severity": "error",
                "dimension": "security", "rule": "SEC-REACT-001",
                "message": "XSS", "source": "custom", "evidence": "x",
                "confidence": "high", "fix_hint": "sanitize", "triage": "deterministic",
            },
            {
                "file": "src/b.tsx", "line": 9, "column": 0, "severity": "warning",
                "dimension": "reliability", "rule": "RELI-JS-001",
                "message": "async", "source": "custom", "evidence": "x",
                "confidence": "medium", "fix_hint": "wrap", "triage": "agent_verify",
            },
        ],
        "score": {"overall": 88.0, "grade": "B", "security": 80, "reliability": 90, "best-practice": 100, "arch": 100, "deps": 100},
        "by_severity": {"error": 1, "warning": 1, "info": 0},
        "triage_summary": {"deterministic": 1, "agent_verify": 1, "agent_only": 0, "total": 2},
        "degradation_notices": ["eslint skipped."],
        "deps_summary": {"packages": 5, "npm_available": True, "vulnerabilities": {"critical": 0, "high": 1, "moderate": 0, "low": 0, "total": 1}},
    }


class TestJsonCompact:
    def test_parses_and_has_required_keys(self):
        out = json.loads(format_json_compact(_result()))
        assert out["score"] == 88.0
        assert out["grade"] == "B"
        assert out["issues"] == {"error": 1, "warning": 1, "info": 0}
        assert out["files"] == 2
        assert "dimensions" in out
        assert len(out["findings"]) == 2
        assert out["findings"][0]["id"] == "SEC-REACT-001"
        assert out["triage"]["total"] == 2
        assert out["degradation_notices"] == ["eslint skipped."]
        assert out["deps"]["vulnerabilities"]["total"] == 1

    def test_findings_capped_at_50(self):
        r = _result()
        r["findings"] = [
            {"rule": "R", "severity": "info", "dimension": "x", "file": "f", "line": i,
             "confidence": "low", "triage": "deterministic", "message": "m", "fix_hint": ""}
            for i in range(100)
        ]
        out = json.loads(format_json_compact(r))
        assert len(out["findings"]) == 50


class TestSarif:
    def test_valid_sarif_skeleton(self):
        sarif = json.loads(format_sarif(_result()))
        assert sarif["version"] == "2.1.0"
        run = sarif["runs"][0]
        assert run["tool"]["driver"]["name"] == "frontend-audit"
        assert len(run["results"]) == 2
        # rule index references must be valid
        for res in run["results"]:
            assert 0 <= res["ruleIndex"] < len(run["tool"]["driver"]["rules"])


class TestMarkdown:
    def test_contains_score_and_findings(self):
        md = format_markdown(_result())
        assert "前端代码审查报告" in md
        assert "88.0 (B)" in md
        assert "SEC-REACT-001" in md
        assert "降级提示" in md
        assert "npm audit" in md
        assert "agent_verify" in md

    def test_empty_findings_shows_ok_row(self):
        r = _result()
        r["findings"] = []
        md = format_markdown(r)
        assert "无问题发现" in md


class TestZeroFindingOutput:
    """M7: 0-finding output must stay well-formed across all four formats.

    SARIF uploaded to GitHub Code Scanning is rejected if malformed; markdown
    shown to users must say "no issues"; json variants must parse. A 0-finding
    scan is the common CI green path, so it cannot break here.
    """

    def _zero_result(self):
        return {
            "project_root": "/proj",
            "files_scanned": 1,
            "findings": [],
            "score": {"overall": 100.0, "grade": "A", "security": 100,
                      "reliability": 100, "best-practice": 100, "arch": 100, "deps": 100},
            "by_severity": {"error": 0, "warning": 0, "info": 0},
            "triage_summary": {"deterministic": 0, "agent_verify": 0, "agent_only": 0, "total": 0},
            "degradation_notices": [],
            "deps_summary": None,
            "error": None,
        }

    def test_json_compact_zero_findings_valid(self):
        out = json.loads(format_json_compact(self._zero_result()))
        assert out["score"] == 100.0
        assert out["grade"] == "A"
        assert out["findings"] == []

    def test_sarif_zero_findings_is_valid_skeleton(self):
        sarif = json.loads(format_sarif(self._zero_result()))
        # SARIF must always have runs[0].tool.driver and results (empty ok)
        assert sarif["version"] == "2.1.0"
        run = sarif["runs"][0]
        assert run["tool"]["driver"]["name"] == "frontend-audit"
        assert run["results"] == []
        assert run["tool"]["driver"]["rules"] == []

    def test_markdown_zero_findings_shows_clean(self):
        md = format_markdown(self._zero_result())
        assert "无问题发现" in md
        assert "100.0 (A)" in md
