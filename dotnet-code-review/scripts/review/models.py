from __future__ import annotations
from dataclasses import dataclass

@dataclass
class CodeIssue:
    file: str
    line: int
    column: int = 0
    severity: str = "info"      # error | warning | info
    category: str = "style"     # security | best-practice | semantic | style | complexity
    rule: str = ""
    message: str = ""
    source: str = "builtin"     # builtin | complexity | ast | semantic | project | build | format | nuget | doc | coverage | custom | duplicate
    suggestion: str = ""
    triage: str = ""            # deterministic | agent_verify | agent_only (empty = auto from RULE_TRIAGE)
