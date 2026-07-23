from __future__ import annotations
import logging
from .models import CodeIssue

logger = logging.getLogger('dotnet-review')


FIX_TIME_MINUTES: dict[str, dict[str, int]] = {
    "error": {
        "security": 30, "best-practice": 20, "semantic": 20,
        "reliability": 25, "performance": 20, "complexity": 45,
        "style": 10, "test": 10, "naming": 5, "security-hotspot": 15,
        "code-smell": 15, "architecture": 60,
    },
    "warning": {
        "security": 15, "best-practice": 10, "semantic": 10,
        "reliability": 12, "performance": 10, "complexity": 20,
        "style": 5, "test": 5, "naming": 3, "security-hotspot": 10,
        "code-smell": 8, "architecture": 30,
    },
    "info": {
        "security": 5, "best-practice": 3, "semantic": 3,
        "reliability": 5, "performance": 3, "complexity": 10,
        "style": 2, "test": 2, "naming": 2, "security-hotspot": 5,
        "code-smell": 3, "architecture": 10,
    },
}


# ============================================================
# Scoring
# ============================================================

SEVERITY_PENALTIES = {"error": 10, "warning": 5, "info": 1}
CATEGORY_WEIGHTS = {
    "security": 0.20,
    "best-practice": 0.20,
    "semantic": 0.10,
    "style": 0.05,
    "complexity": 0.10,
    "test": 0.05,
    "performance": 0.05,
    "naming": 0.05,
    "reliability": 0.05,
    "security-hotspot": 0.05,
    "code-smell": 0.05,
    "architecture": 0.05,  # project-level ARCH_*/LAYER_* rules
}

# Weights sum to 1.00: 0.20+0.20+0.10+0.05+0.10+0.05*6 = 1.00

# CAxxxx sub-categories carried on issues for display/grouping but not part of
# CATEGORY_WEIGHTS. Folded into the closest scoring dimension so calculate_score
# never crashes on a real NetAnalyzers finding (e.g. CA1310 → "globalization").
# Mirrored in engine._NON_SCORING_CATEGORIES for discoverability.
CATEGORY_NORMALIZATION = {
    "globalization": "best-practice",  # culture/locale correctness → review hygiene
    "design": "best-practice",         # API design guidance (CA10xx/CA17xx)
    "usage": "reliability",            # usage rules (CA22xx) → reliability hygiene
    "maintainability": "code-smell",   # maintainability index → code smell
    "portability": "best-practice",    # platform portability → review hygiene
}


def _scoring_category(category: str) -> str:
    """Normalize an issue category to a valid scoring dimension."""
    return CATEGORY_NORMALIZATION.get(category, category)


def calculate_score(issues: list[CodeIssue]) -> dict:
    """Calculate review score from issues."""
    penalty_by_category: dict[str, int] = {}
    for issue in issues:
        cat = _scoring_category(issue.category)
        penalty_by_category[cat] = penalty_by_category.get(cat, 0) + SEVERITY_PENALTIES.get(issue.severity, 0)

    category_scores: dict[str, int] = {}
    for cat in CATEGORY_WEIGHTS:
        penalty = penalty_by_category.get(cat, 0)
        category_scores[cat] = max(0, 100 - penalty)

    overall = sum(category_scores.get(cat, 100) * weight for cat, weight in CATEGORY_WEIGHTS.items())
    overall = round(overall * 10) / 10

    if overall >= 90:
        grade = "A"
    elif overall >= 80:
        grade = "B"
    elif overall >= 70:
        grade = "C"
    elif overall >= 60:
        grade = "D"
    else:
        grade = "F"

    return {
        "overall": overall,
        "grade": grade,
        "security": category_scores.get("security", 100),
        "best_practice": category_scores.get("best-practice", 100),
        "semantic": category_scores.get("semantic", 100),
        "style": category_scores.get("style", 100),
        "complexity": category_scores.get("complexity", 100),
        "test": category_scores.get("test", 100),
        "performance": category_scores.get("performance", 100),
        "naming": category_scores.get("naming", 100),
        "reliability": category_scores.get("reliability", 100),
        "security_hotspot": category_scores.get("security-hotspot", 100),
        "code_smell": category_scores.get("code-smell", 100),
        "architecture": category_scores.get("architecture", 100),
    }



def estimate_technical_debt(issues: list[CodeIssue]) -> int:
    """Estimate total fix time in minutes."""
    total = 0
    for issue in issues:
        severity = issue.severity
        category = issue.category
        time_table = FIX_TIME_MINUTES.get(severity, FIX_TIME_MINUTES.get("info", {}))
        total += time_table.get(category, 5)
    return total



def count_by_severity(issues: list[CodeIssue]) -> dict:
    errors = sum(1 for i in issues if i.severity == "error")
    warnings = sum(1 for i in issues if i.severity == "warning")
    infos = sum(1 for i in issues if i.severity == "info")
    return {"error": errors, "warning": warnings, "info": infos}



# ============================================================
# Deduplication
# ============================================================

def dedup_issues(issues: list[CodeIssue]) -> list[CodeIssue]:
    """Deduplicate issues by file:line:rule, keeping the most severe."""
    seen: dict[str, CodeIssue] = {}
    severity_rank = {"error": 3, "warning": 2, "info": 1}

    for issue in issues:
        key = f"{issue.file}:{issue.line}:{issue.rule}"
        if key not in seen or severity_rank.get(issue.severity, 0) > severity_rank.get(seen[key].severity, 0):
            seen[key] = issue
    return list(seen.values())


# ============================================================
# Layer 1→3 Suppression (concept-level dedup)
# ============================================================


def suppress_builtin_overlap(
    issues: list[CodeIssue],
    project_root: str = "",
) -> tuple[list[CodeIssue], int]:
    """Suppress builtin (regex) issues authoritatively covered by AST/semantic.

    The regex layer is permanently disabled — no builtin issues are produced,
    so no suppression is needed. Returns (kept_issues, 0).
    """
    return issues, 0
