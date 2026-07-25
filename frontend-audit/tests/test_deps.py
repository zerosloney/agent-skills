"""In-process tests for deps.analyze_dependencies and _extract_from_audit.

Covers the JSON parsing paths (metadata, via-as-dict, via-as-string, empty),
the npm-missing degradation, and the package.json-less early return.
npm subprocess calls are monkeypatched so no Node is required.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import audit.deps as D
from audit.deps import _extract_from_audit, analyze_dependencies


class TestExtractFromAudit:
    def test_parses_vulnerabilities_with_dict_via(self):
        data = {
            "metadata": {"vulnerabilities": {"critical": 1, "high": 2, "moderate": 3, "low": 4, "total": 10}},
            "vulnerabilities": {
                "lodash": {"severity": "high", "range": "<4.17.21",
                           "via": [{"title": "Prototype Pollution", "url": "https://advisory.example"}]},
            },
        }
        findings, summary, notice = _extract_from_audit(data, deps_count=5)
        assert notice is None
        assert len(findings) == 1
        assert findings[0].severity == "error"  # high → error
        assert findings[0].rule == "NPM-AUDIT-HIGH"
        assert "Prototype Pollution" in findings[0].message
        assert "https://advisory.example" in findings[0].evidence
        assert summary["vulnerabilities"]["total"] == 10
        assert summary["packages"] == 5

    def test_via_as_string_uses_id_as_ref(self):
        data = {"vulnerabilities": {"x": {"severity": "low", "range": "*", "via": ["GHSA-abc"]}}}
        findings, _, _ = _extract_from_audit(data, 0)
        assert len(findings) == 1
        assert findings[0].evidence == "GHSA-abc"

    def test_severity_mapping(self):
        for npm_sev, expected in [("critical", "error"), ("high", "error"), ("moderate", "warning"), ("low", "info")]:
            data = {"vulnerabilities": {"p": {"severity": npm_sev, "range": "*", "via": []}}}
            fs, _, _ = _extract_from_audit(data, 0)
            assert fs[0].severity == expected, npm_sev

    def test_empty_metadata_is_safe(self):
        findings, summary, _ = _extract_from_audit({}, 0)
        assert findings == []
        assert summary["vulnerabilities"]["total"] == 0


class TestAnalyzeDependencies:
    def test_no_package_json_returns_notice(self, tmp_path):
        findings, summary, notice = analyze_dependencies(str(tmp_path))
        assert findings == []
        assert summary["packages"] == 0
        assert "package.json not found" in notice

    def test_npm_missing_returns_notice(self, tmp_path, monkeypatch):
        (tmp_path / "package.json").write_text(
            '{"name":"x","dependencies":{"a":"1.0.0"}}', encoding="utf-8"
        )
        monkeypatch.setattr(D, "_resolve_npm", lambda: None)
        findings, summary, notice = analyze_dependencies(str(tmp_path))
        assert findings == []
        assert summary["npm_available"] is False
        assert "npm not found" in notice

    def test_npm_returns_valid_json(self, tmp_path, monkeypatch):
        (tmp_path / "package.json").write_text(
            '{"name":"x","dependencies":{"a":"1.0.0"}}', encoding="utf-8"
        )
        monkeypatch.setattr(D, "_resolve_npm", lambda: "npm")
        audit_output = json.dumps({
            "metadata": {"vulnerabilities": {"high": 1, "total": 1}},
            "vulnerabilities": {"a": {"severity": "high", "range": "*", "via": []}},
        })

        class _FakeProc:
            returncode = 1
            stdout = audit_output
            stderr = ""

        monkeypatch.setattr(D.subprocess, "run", lambda *a, **kw: _FakeProc())
        findings, summary, notice = analyze_dependencies(str(tmp_path))
        assert notice is None
        assert len(findings) == 1
        assert summary["npm_available"] is True
        assert summary["vulnerabilities"]["high"] == 1

    def test_npm_returns_garbage_returns_notice(self, tmp_path, monkeypatch):
        (tmp_path / "package.json").write_text('{"name":"x"}', encoding="utf-8")
        monkeypatch.setattr(D, "_resolve_npm", lambda: "npm")

        class _FakeProc:
            returncode = 1
            stdout = "not json"
            stderr = ""

        monkeypatch.setattr(D.subprocess, "run", lambda *a, **kw: _FakeProc())
        findings, summary, notice = analyze_dependencies(str(tmp_path))
        assert findings == []
        assert "non-JSON" in (notice or "")


class TestResolveNpm:
    def test_returns_none_when_not_found(self, monkeypatch):
        monkeypatch.setattr(D.shutil, "which", lambda name: None)
        assert D._resolve_npm() is None

    def test_windows_prefers_cmd(self, monkeypatch):
        monkeypatch.setattr(D.os, "name", "nt")
        monkeypatch.setattr(D.shutil, "which", lambda name: f"/bin/{name}" if name else None)
        # npm.cmd should be preferred
        assert D._resolve_npm().endswith("npm.cmd")
