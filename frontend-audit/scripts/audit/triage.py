"""Triage: classify each finding and produce a summary for the Triage→Verify protocol.

Three triage classes (same vocabulary as dotnet-code-review):

- ``deterministic``: high-confidence, statically provable. Report directly.
- ``agent_verify``: needs the Agent to confirm (e.g. postMessage without origin
  check — the rule can't see the receiver side).
- ``agent_only``: heuristic surfacing; the Agent investigates, may dismiss.

Each Finding carries its own ``triage`` set by the rule spec; this module
back-fills empty values and tallies the summary.
"""
from __future__ import annotations

from .models import Finding
from .rules import get_triage_for_rule


def apply_triage(findings: list[Finding]) -> list[Finding]:
    """Back-fill empty triage fields from the rule catalog."""
    for f in findings:
        if not f.triage:
            f.triage = get_triage_for_rule(f.rule, fallback="deterministic")
    return findings


def triage_summary(findings: list[Finding]) -> dict:
    counts = {"deterministic": 0, "agent_verify": 0, "agent_only": 0}
    for f in findings:
        counts[f.triage] = counts.get(f.triage, 0) + 1
    return {
        "deterministic": counts["deterministic"],
        "agent_verify": counts["agent_verify"],
        "agent_only": counts["agent_only"],
        "total": sum(counts.values()),
    }
