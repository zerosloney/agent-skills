"""Self-authored AST/regex rules for frontend-audit.

Rules are organized by dimension. Each rule module exposes ``RULES: list[RuleSpec]``
collected by :func:`all_rules`.
"""
from __future__ import annotations

from .security import RULES as _security_rules
from .reliability import RULES as _reliability_rules
from .secrets import RULES as _secret_rules

__all__ = ["all_rules"]


def all_rules():
    """Return the concatenated rule list across all dimensions."""
    return [*_security_rules, *_reliability_rules, *_secret_rules]
