"""Rule registry: defines :class:`RuleSpec` and the triage lookup used by engine."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RuleSpec:
    """Static description of a self-authored rule.

    Detection itself is performed by the visitor in ``_ast_visitor.py`` /
    ``_regex_visitor.py``. A RuleSpec is what the rule catalog and the
    ``audit.py rules`` command surface, and what triage/coverage reference.
    """

    id: str
    dimension: str          # security | reliability | best-practice | arch
    severity: str           # error | warning | info
    title: str
    owasp: str = ""         # OWASP Top 10 id, e.g. A03:2021
    cwe: str = ""           # CWE id, e.g. CWE-79
    triage: str = "deterministic"  # deterministic | agent_verify | agent_only
    confidence: str = "high"
    description: str = ""
    fix_hint: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "dimension": self.dimension,
            "severity": self.severity,
            "title": self.title,
            "owasp": self.owasp,
            "cwe": self.cwe,
            "triage": self.triage,
            "confidence": self.confidence,
            "description": self.description,
            "fix_hint": self.fix_hint,
        }


def get_triage_for_rule(rule_id: str, fallback: str = "deterministic") -> str:
    """Resolve a rule id to its triage class via the catalog."""
    spec = _rule_index().get(rule_id)
    return spec.triage if spec else fallback


def get_spec(rule_id: str) -> RuleSpec | None:
    return _rule_index().get(rule_id)


def all_rules():
    """Re-export the rule catalog from ruledefs for convenience."""
    from .ruledefs import all_rules as _all

    return _all()


_RULE_INDEX_CACHE: dict[str, RuleSpec] | None = None


def _rule_index() -> dict[str, RuleSpec]:
    """Build (once, lazily) the rule-id → spec index.

    Lazy because ruledefs.* import RuleSpec from this module, so building the
    index at import time would re-enter ruledefs before it finishes importing.
    """
    global _RULE_INDEX_CACHE
    if _RULE_INDEX_CACHE is None:
        from .ruledefs import all_rules

        _RULE_INDEX_CACHE = {spec.id: spec for spec in all_rules()}
    return _RULE_INDEX_CACHE
