"""Agent Verdicts — persistent feedback loop for Agent-confirmed false positives.

When the Agent determines that a rule finding is a false positive for a
specific file/pattern, it can write a verdict that suppresses future matches.
This makes the review progressively more accurate per-project.

Verdicts are stored in `.dotnet-review/agent-verdicts.json`.
"""
from __future__ import annotations
import json
import logging
import fnmatch
import os
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("dotnet-review")

VERDICTS_DIR = ".dotnet-review"
VERDICTS_FILE = "agent-verdicts.json"


def _verdicts_path(project_root: str) -> Path:
    return Path(project_root) / VERDICTS_DIR / VERDICTS_FILE


def load_verdicts(project_root: str) -> list[dict]:
    """Load agent verdicts from the project's .dotnet-review directory.

    Returns an empty list if the file doesn't exist or is invalid.
    """
    path = _verdicts_path(project_root)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data.get("verdicts", [])
        if isinstance(data, list):
            return data
        return []
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Failed to load agent verdicts from %s: %s", path, e)
        return []


def save_verdicts(project_root: str, verdicts: list[dict]) -> None:
    """Save agent verdicts to the project's .dotnet-review directory."""
    path = _verdicts_path(project_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "version": 1,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "verdicts": verdicts,
    }
    path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def apply_verdicts(
    issues: list,
    verdicts: list[dict],
) -> tuple[list, int]:
    """Apply agent verdicts to suppress matching issues.

    A verdict matches an issue when ALL of:
    - verdict.rule matches issue.rule (exact match)
    - verdict.file_pattern matches issue.file (fnmatch glob)
    - verdict.verdict == "false_positive"

    Returns (filtered_issues, suppressed_count).
    """
    if not verdicts:
        return issues, 0

    suppressed = 0
    kept = []
    for issue in issues:
        matched = False
        for v in verdicts:
            if v.get("verdict") != "false_positive":
                continue
            if v.get("rule") != issue.rule:
                continue
            pattern = v.get("file_pattern", "*")
            # Match against both full path and basename
            if fnmatch.fnmatch(issue.file, pattern) or \
               fnmatch.fnmatch(os.path.basename(issue.file), pattern):
                matched = True
                break
        if matched:
            suppressed += 1
        else:
            kept.append(issue)
    return kept, suppressed


def count_verdict_matches(
    issues: list,
    verdicts: list[dict],
) -> int:
    """Count how many issues would be suppressed by verdicts (without filtering)."""
    if not verdicts:
        return 0
    count = 0
    for issue in issues:
        for v in verdicts:
            if v.get("verdict") != "false_positive":
                continue
            if v.get("rule") != issue.rule:
                continue
            pattern = v.get("file_pattern", "*")
            if fnmatch.fnmatch(issue.file, pattern) or \
               fnmatch.fnmatch(os.path.basename(issue.file), pattern):
                count += 1
                break
    return count
