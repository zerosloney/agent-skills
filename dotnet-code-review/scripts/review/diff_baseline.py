"""PR diff-aware baseline comparison.

Compares the current run's issues against a baseline JSON report to classify
each issue as introduced / fixed / unchanged / severity_changed. The baseline
is a full review.py JSON output (--format json) produced on a reference branch
(e.g. main). This answers the PR question: "did this change make things better
or worse?"

Matching key: (rule, normalize_review_path(file), line). Message and
suggestion are deliberately excluded — wording may drift without the issue
itself changing. Severity is excluded from the key so that a warning→error
change on the same rule/file/line surfaces as `severity_changed`, not as a
fresh `introduced` + `fixed` pair.

Suppression interaction: this comparison runs AFTER suppressions are applied
in engine.py. A suppressed issue is invisible in both the current run and the
baseline comparison (consistent with "suppress = treat as nonexistent"). A
baseline issue that is suppressed in the current run will count as `fixed`.
This is documented, intentional behavior.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .files import normalize_review_path

# Maximum line drift to still consider two same-(rule,file) findings as the
# SAME issue. A PR that inserts N lines shifts every subsequent finding down
# by N; without this tolerance, those moved findings would be misclassified
# as introduced+fixed pairs. 5 rows balances tolerance for typical edits
# against the risk of merging genuinely distinct adjacent issues.
LINE_PROXIMITY = 5


def load_baseline(path: str) -> list[dict] | None:
    """Load a baseline issues list from a review.py JSON report.

    Returns the ``issues`` array, or None if the file cannot be read / parsed
    / has no issues key. None (not []) signals "no baseline available" so the
    caller can distinguish "baseline load failed" from "baseline had zero
    issues" — only the former warrants a warning.
    """
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    issues = data.get("issues")
    if not isinstance(issues, list):
        return None
    return issues


def _get(issue: Any, attr: str, default: Any = "") -> Any:
    """Read a field from either a CodeIssue (attr access) or a dict (key)."""
    if isinstance(issue, dict):
        return issue.get(attr, default)
    return getattr(issue, attr, default)


def _issue_key(issue: Any, project_root: str) -> tuple[str, str, int]:
    """Normalized matching key: (rule, file, line).

    `file` is normalized via normalize_review_path so absolute, relative, and
    git-relative paths all collapse to the same canonical form. `line` is the
    raw int — line=0 means file-level (e.g. csproj_audit issues); two file-
    level issues on the same rule+file match regardless of line drift.
    """
    rule = _get(issue, "rule", "")
    raw_file = _get(issue, "file", "")
    norm_file = normalize_review_path(raw_file, project_root) if raw_file else ""
    line = _get(issue, "line", 0)
    try:
        line_int = int(line) if line is not None else 0
    except (TypeError, ValueError):
        line_int = 0
    return (str(rule), norm_file, line_int)


def compute_diff(
    current_issues: list,
    baseline_issues: list[dict],
    project_root: str = "",
) -> dict:
    """Classify current vs baseline issues into introduced/fixed/unchanged.

    Returns:
        {
            "introduced": [issue dicts present now, absent in baseline],
            "fixed":      [issue dicts present in baseline, absent now],
            "unchanged_count": int,
            "severity_changed": [
                {"key": (rule, file, line),
                 "baseline_severity": str, "current_severity": str,
                 "file": str, "line": int, "rule": str}
            ],
            "baseline_total": int,
            "current_total": int,
        }

    `introduced` and `fixed` entries are plain dicts (serialized form) so they
    can be emitted directly in JSON output. `unchanged_count` is a count only
    — listing every unchanged issue would drown the signal in noise.
    """
    baseline_by_key: dict[tuple, dict] = {}
    for b in baseline_issues:
        baseline_by_key[_issue_key(b, project_root)] = b

    current_by_key: dict[tuple, Any] = {}
    for c in current_issues:
        current_by_key[_issue_key(c, project_root)] = c

    baseline_keys = set(baseline_by_key)
    current_keys = set(current_by_key)

    # Pass 1: exact (rule, file, line) match — zero line drift.
    common_keys = current_keys & baseline_keys
    unmatched_current = current_keys - common_keys
    unmatched_baseline = baseline_keys - common_keys

    # Pass 2: line-proximity match. Same (rule, file) with line drift ≤
    # LINE_PROXIMITY rows is treated as the SAME issue that just moved.
    # This is the common PR case: inserting/deleting a few lines shifts every
    # subsequent finding down without changing the issue itself. Greedy
    # nearest-match per (rule, file) group.
    proximity_matched: list[tuple[tuple, tuple]] = []
    remaining_current: dict[tuple, list[tuple]] = {}
    for ck in unmatched_current:
        rf = (ck[0], ck[1])
        remaining_current.setdefault(rf, []).append(ck)
    remaining_baseline: dict[tuple, list[tuple]] = {}
    for bk in unmatched_baseline:
        rf = (bk[0], bk[1])
        remaining_baseline.setdefault(rf, []).append(bk)

    for rf, c_keys in remaining_current.items():
        b_keys = remaining_baseline.get(rf, [])
        used_b: set[tuple] = set()
        for ck in c_keys:
            # Find nearest unused baseline key by line distance.
            best_bk = None
            best_dist = LINE_PROXIMITY + 1
            for bk in b_keys:
                if bk in used_b:
                    continue
                dist = abs(ck[2] - bk[2])
                if dist < best_dist:
                    best_dist = dist
                    best_bk = bk
            if best_bk is not None and best_dist <= LINE_PROXIMITY:
                proximity_matched.append((ck, best_bk))
                used_b.add(best_bk)
        # Mark matched baseline keys as consumed.
        for _ck, bk in proximity_matched:
            if bk[0] == rf[0] and bk[1] == rf[1]:
                unmatched_baseline.discard(bk)
    proximity_current = {ck for ck, _ in proximity_matched}
    unmatched_current -= proximity_current

    introduced = [_serialize_issue(current_by_key[k]) for k in unmatched_current]
    fixed = [_serialize_issue(baseline_by_key[k]) for k in unmatched_baseline]

    # Severity changes: check both exact-match and proximity-match pairs.
    severity_changed = []
    unchanged_count = 0

    def _compare_pair(b_item: Any, c_item: Any, rule: str, file: str, line: int) -> None:
        nonlocal unchanged_count
        b_sev = str(_get(b_item, "severity", "info"))
        c_sev = str(_get(c_item, "severity", "info"))
        if b_sev != c_sev:
            severity_changed.append({
                "rule": rule, "file": file, "line": line,
                "baseline_severity": b_sev, "current_severity": c_sev,
            })
        else:
            unchanged_count += 1

    for k in common_keys:
        _compare_pair(baseline_by_key[k], current_by_key[k], k[0], k[1], k[2])
    for ck, bk in proximity_matched:
        # Report the current line (where the issue lives now).
        _compare_pair(baseline_by_key[bk], current_by_key[ck], ck[0], ck[1], ck[2])

    return {
        "introduced": introduced,
        "fixed": fixed,
        "unchanged_count": unchanged_count,
        "severity_changed": severity_changed,
        "baseline_total": len(baseline_issues),
        "current_total": len(current_issues),
    }


def _serialize_issue(issue: Any) -> dict:
    """Coerce a CodeIssue or dict to a plain dict for JSON output.

    Keeps only the fields useful for diff reporting; full message/suggestion
    are available in the main issues[] array and need not be duplicated here.
    """
    if isinstance(issue, dict):
        return {
            "rule": issue.get("rule", ""),
            "file": issue.get("file", ""),
            "line": issue.get("line", 0),
            "severity": issue.get("severity", "info"),
            "category": issue.get("category", ""),
            "source": issue.get("source", ""),
            "message": issue.get("message", "")[:120],
        }
    # CodeIssue dataclass
    return {
        "rule": issue.rule,
        "file": issue.file,
        "line": issue.line,
        "severity": issue.severity,
        "category": issue.category,
        "source": issue.source,
        "message": (issue.message or "")[:120],
    }
