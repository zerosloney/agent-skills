"""Reliability rule specs: unhandled async, leaked event listeners."""
from __future__ import annotations

from ..rules import RuleSpec

RULES: list[RuleSpec] = [
    RuleSpec(
        id="RELI-JS-001",
        dimension="reliability",
        severity="warning",
        title="async callback passed to useEffect (unhandled rejection risk)",
        cwe="CWE-754",
        triage="agent_verify",
        confidence="medium",
        description=(
            "Passing an async function to useEffect means the returned promise is "
            "ignored; rejections become unhandled and the cleanup return value is "
            "lost. The conventional fix is to define an inner async function and "
            "call it, returning a cleanup closure."
        ),
        fix_hint=(
            "useEffect(() => { const run = async () => { ... }; run(); }, [deps])"
        ),
    ),
    RuleSpec(
        id="RELI-JS-002",
        dimension="reliability",
        severity="info",
        title="addEventListener without matching removeEventListener (memory leak)",
        cwe="CWE-401",
        triage="agent_verify",
        confidence="medium",
        description=(
            "Event listeners added but never removed can leak, especially on "
            "long-lived objects or across remounts. This rule compares the set "
            "of event names added vs removed within a file (heuristic)."
        ),
        fix_hint="Remove the listener in the cleanup function (e.g. useEffect return).",
    ),
]
