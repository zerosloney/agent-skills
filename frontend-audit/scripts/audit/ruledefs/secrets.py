"""Secret detection: hardcoded API keys / passwords / tokens.

Patterns are intentionally conservative — they target common key *formats*
(AWS, Google, Slack, GitHub, generic high-entropy) to keep the false-positive
rate low. Anything matched here is high-severity and must be verified before
reporting (no credentials in output; evidence is redacted).
"""
from __future__ import annotations

import re

from ..rules import RuleSpec

RULES: list[RuleSpec] = [
    RuleSpec(
        id="SEC-SECRET-001",
        dimension="security",
        severity="error",
        title="Hardcoded AWS access key id (AKIA...)",
        owasp="A02:2021",
        cwe="CWE-798",
        triage="deterministic",
        confidence="high",
        description="AWS access key ids are long-lived credentials. Never commit them.",
        fix_hint="Move to an environment variable or secrets manager; rotate the key.",
    ),
    RuleSpec(
        id="SEC-SECRET-002",
        dimension="security",
        severity="error",
        title="Hardcoded GitHub personal access token (ghp_...)",
        owasp="A02:2021",
        cwe="CWE-798",
        triage="deterministic",
        confidence="high",
        description="GitHub PATs grant repository access. Never commit them.",
        fix_hint="Move to an environment variable; revoke and rotate the token.",
    ),
    RuleSpec(
        id="SEC-SECRET-003",
        dimension="security",
        severity="error",
        title="Hardcoded Google API key (AIza...)",
        owasp="A02:2021",
        cwe="CWE-798",
        triage="deterministic",
        confidence="high",
        description="Google API keys are long-lived. Never commit them.",
        fix_hint="Move to an environment variable; restrict/rotate the key.",
    ),
    RuleSpec(
        id="SEC-SECRET-004",
        dimension="security",
        severity="warning",
        title="Suspicious password/secret assignment",
        owasp="A02:2021",
        cwe="CWE-798",
        # heuristic on variable-name shape only — not a definitive secret. The
        # agent_only triage lets the Agent investigate and dismiss false hits
        # (test fixtures, mock values) without it counting as a real finding.
        triage="agent_only",
        confidence="medium",
        description=(
            "Assignment to a variable whose name contains a credential word "
            "(password/secret/api_key/access_token/auth_token) with a non-empty "
            "string literal. Mock/test-prefixed names are suppressed; the rest "
            "are surfaced for Agent investigation and may be dismissed."
        ),
        fix_hint="Replace with a value read from process.env or a secrets manager.",
    ),
]

# Compiled patterns paired with their rule id, consumed by visitors.scan_secrets.
SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("SEC-SECRET-001", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("SEC-SECRET-002", re.compile(r"\bghp_[A-Za-z0-9]{36}\b")),
    ("SEC-SECRET-003", re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b")),
    (
        "SEC-SECRET-004",
        # Match `const/let/var NAME = "..."` (or `NAME: "..."`) where NAME is a
        # single identifier containing a credential word. The variable name is
        # captured greedily as a whole token, then the credential check happens
        # on that token — this avoids the old non-greedy bug that mis-matched
        # `mockApiKey` (treated `mock` as a prefix of the credential word) and
        # missed `apiKey` (real style). We also reject obvious test/mock names
        # via the negative prefix alternation.
        #
        # intentional-simple: a single regex still can't see scope/context, so
        # this stays heuristic (rule triage = agent_only). Upgrade path: AST
        # tier resolves the assignment target and skips test files entirely.
        re.compile(
            r"(?:const|let|var)\s+"
            r"(?P<name>[A-Za-z_$][\w$]*)\s*[:=]\s*"
            r"['\"`][^'\"`]{3,}['\"`]",
            re.IGNORECASE,
        ),
    ),
]
