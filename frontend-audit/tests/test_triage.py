"""Tests for the triage back-fill and summary."""
from __future__ import annotations

from audit.models import Finding
from audit.triage import apply_triage, triage_summary


def test_empty_triage_backfilled_from_catalog():
    f = Finding(file="a.js", line=1, severity="error", dimension="security", rule="SEC-JS-001")
    assert f.triage == ""
    apply_triage([f])
    assert f.triage == "deterministic"


def test_agent_verify_rule_backfilled():
    f = Finding(file="a.js", line=1, severity="warning", dimension="security", rule="SEC-JS-005")
    apply_triage([f])
    assert f.triage == "agent_verify"


def test_unknown_rule_defaults_to_deterministic():
    f = Finding(file="a.js", line=1, severity="warning", dimension="best-practice", rule="UNKNOWN-123")
    apply_triage([f])
    assert f.triage == "deterministic"


def test_summary_counts():
    findings = [
        Finding(file="a", line=1, rule="SEC-JS-001", triage="deterministic"),
        Finding(file="a", line=2, rule="SEC-JS-001", triage="deterministic"),
        Finding(file="a", line=3, rule="SEC-JS-005", triage="agent_verify"),
    ]
    s = triage_summary(findings)
    assert s == {"deterministic": 2, "agent_verify": 1, "agent_only": 0, "total": 3}
