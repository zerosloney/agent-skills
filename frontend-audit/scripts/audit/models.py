from __future__ import annotations
from dataclasses import dataclass, field, asdict


@dataclass
class Finding:
    """One audit finding (matches the dotnet-code-review CodeIssue shape)."""

    file: str
    line: int
    column: int = 0
    severity: str = "info"          # error | warning | info
    dimension: str = "best-practice"  # security | reliability | best-practice | arch | deps
    rule: str = ""                  # rule id, e.g. SEC-REACT-001
    message: str = ""
    source: str = "custom"          # custom | eslint | tsc | npm-audit
    evidence: str = ""              # the offending source snippet
    confidence: str = "high"        # high | medium | low  (drives Triage→Verify)
    fix_hint: str = ""
    triage: str = ""                # deterministic | agent_verify | agent_only (empty = auto)

    def to_dict(self) -> dict:
        return asdict(self)
