"""Scoring: per-dimension weighted penalty model (mirrors dotnet-code-review).

5 scoring dimensions: security, reliability, best-practice, arch, deps.
Weights sum to 1.00.
"""
from __future__ import annotations

from .models import Finding

SEVERITY_PENALTIES = {"error": 10, "warning": 5, "info": 1}

CATEGORY_WEIGHTS = {
    "security": 0.35,
    "reliability": 0.20,
    "best-practice": 0.20,
    "arch": 0.10,
    "deps": 0.15,
}
# 0.35 + 0.20 + 0.20 + 0.10 + 0.15 = 1.00

# Findings whose source is eslint/tsc are folded into best-practice even if their
# rule name suggests otherwise; we trust the custom security tier for security.
_SOURCE_TO_DIMENSION = {
    "eslint": "best-practice",
    "tsc": "best-practice",
}


def _scoring_dimension(f: Finding) -> str:
    if f.source in _SOURCE_TO_DIMENSION:
        return _SOURCE_TO_DIMENSION[f.source]
    return f.dimension if f.dimension in CATEGORY_WEIGHTS else "best-practice"


def calculate_score(findings: list[Finding]) -> dict:
    penalty_by_cat: dict[str, int] = {}
    for f in findings:
        cat = _scoring_dimension(f)
        penalty_by_cat[cat] = penalty_by_cat.get(cat, 0) + SEVERITY_PENALTIES.get(f.severity, 0)

    category_scores = {cat: max(0, 100 - penalty_by_cat.get(cat, 0)) for cat in CATEGORY_WEIGHTS}
    overall = sum(category_scores[cat] * w for cat, w in CATEGORY_WEIGHTS.items())
    overall = round(overall * 10) / 10

    grade = (
        "A" if overall >= 90
        else "B" if overall >= 80
        else "C" if overall >= 70
        else "D" if overall >= 60
        else "F"
    )

    return {
        "overall": overall,
        "grade": grade,
        **{cat: category_scores[cat] for cat in CATEGORY_WEIGHTS},
    }


def count_by_severity(findings: list[Finding]) -> dict:
    return {
        "error": sum(1 for f in findings if f.severity == "error"),
        "warning": sum(1 for f in findings if f.severity == "warning"),
        "info": sum(1 for f in findings if f.severity == "info"),
    }


def dedup_findings(findings: list[Finding]) -> list[Finding]:
    """Deduplicate by file:line:rule, keeping the most severe."""
    seen: dict[str, Finding] = {}
    rank = {"error": 3, "warning": 2, "info": 1}
    for f in findings:
        key = f"{f.file}:{f.line}:{f.rule}"
        if key not in seen or rank.get(f.severity, 0) > rank.get(seen[key].severity, 0):
            seen[key] = f
    return list(seen.values())
