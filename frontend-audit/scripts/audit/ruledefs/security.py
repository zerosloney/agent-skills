"""Security rule specs: XSS sinks, eval, open-redirect, postMessage."""
from __future__ import annotations

from ..rules import RuleSpec

RULES: list[RuleSpec] = [
    RuleSpec(
        id="SEC-REACT-001",
        dimension="security",
        severity="error",
        title="dangerouslySetInnerHTML with non-literal __html (potential XSS)",
        owasp="A03:2021",
        cwe="CWE-79",
        triage="deterministic",
        confidence="high",
        description=(
            "React's dangerouslySetInnerHTML injects raw HTML. When the __html "
            "value is not a string literal it likely originates from user input "
            "and enables stored/reflected XSS."
        ),
        fix_hint="Sanitize with DOMPurify.sanitize() or avoid dangerouslySetInnerHTML.",
    ),
    RuleSpec(
        id="SEC-REACT-002",
        dimension="security",
        severity="error",
        title="__html value not a literal (React XSS vector)",
        owasp="A03:2021",
        cwe="CWE-79",
        triage="deterministic",
        confidence="high",
        description="Bare __html: { ... } assignment is the same XSS vector as SEC-REACT-001.",
        fix_hint="Sanitize the value before assigning to __html.",
    ),
    RuleSpec(
        id="SEC-JS-001",
        dimension="security",
        severity="error",
        title="eval() / new Function() with non-literal argument (code injection)",
        owasp="A03:2021",
        cwe="CWE-94",
        triage="deterministic",
        confidence="high",
        description=(
            "Dynamic code execution with a non-literal argument allows arbitrary "
            "code injection if the input is attacker-controlled."
        ),
        fix_hint="Replace eval/Function with JSON.parse, a lookup map, or a parser.",
    ),
    RuleSpec(
        id="SEC-JS-002",
        dimension="security",
        severity="error",
        title="document.write with non-literal argument (XSS)",
        owasp="A03:2021",
        cwe="CWE-79",
        triage="deterministic",
        confidence="high",
        description="document.write injects raw HTML into the document stream.",
        fix_hint="Use DOM APIs (textContent, createElement) instead of document.write.",
    ),
    RuleSpec(
        id="SEC-JS-003",
        dimension="security",
        severity="error",
        title=".innerHTML assignment with non-literal value (XSS)",
        owasp="A03:2021",
        cwe="CWE-79",
        triage="deterministic",
        confidence="high",
        description="Assigning a non-literal to .innerHTML can execute injected scripts.",
        fix_hint="Use textContent, or sanitize with DOMPurify before assigning innerHTML.",
    ),
    RuleSpec(
        id="SEC-JS-004",
        dimension="security",
        severity="warning",
        title="window/document.location assignment from non-literal (open redirect)",
        owasp="A01:2021",
        cwe="CWE-601",
        triage="deterministic",
        confidence="medium",
        description=(
            "Assigning location from user-controlled input enables open-redirect "
            "and DOM-based XSS via javascript: URLs."
        ),
        fix_hint="Validate/allow-list the URL before assigning to location.",
    ),
    RuleSpec(
        id="SEC-JS-005",
        dimension="security",
        severity="warning",
        title="postMessage without origin check (potential data leak)",
        owasp="A08:2021",
        cwe="CWE-346",
        triage="agent_verify",
        confidence="low",
        description=(
            "postMessage sends data to any listening frame unless the receiver "
            "filters by event.origin. This rule flags every call for manual "
            "verification of the receiver-side origin check."
        ),
        fix_hint="On the receiving side, check event.origin against an allow-list.",
    ),
]
