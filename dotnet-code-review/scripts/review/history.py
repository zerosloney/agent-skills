from __future__ import annotations
import json
import logging
import time
from pathlib import Path

logger = logging.getLogger('dotnet-review')



# ============================================================
# Report History & Trends
# ============================================================

def _history_file(history_dir: str) -> str:
    """Path to the rolling history JSONL file."""
    return str(Path(history_dir) / "history.jsonl")



def save_report_history(
    history_dir: str,
    snapshot: dict,
    cs_files: list[str],
    issues: list,
) -> dict:
    """Append a review snapshot to the history log and return summary.

    Args:
        history_dir: Directory to store history files
        snapshot: Dict with files_scanned, total_issues, by_severity, score,
                  cognitive_complexity, technical_debt_minutes
        cs_files: Files reviewed
        issues: Issues found

    Returns:
        {
            "total_runs": N,
            "files_scanned": N,
            "total_issues": N,
            "avg_score": N,
            "trend": {"issues_delta": N, "score_delta": N, "direction": "up|down|same"}
        }
    """
    try:
        Path(history_dir).mkdir(parents=True, exist_ok=True)
    except OSError:
        return {"error": f"Cannot create history dir: {history_dir}"}

    entry = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files_scanned": snapshot.get("files_scanned", 0),
        "total_issues": snapshot.get("total_issues", 0),
        "by_severity": snapshot.get("by_severity", {}),
        "score": snapshot.get("score", {}).get("overall", 0),
        "cognitive_complexity": snapshot.get("cognitive_complexity", 0),
        "technical_debt_minutes": snapshot.get("technical_debt_minutes", 0),
        "files": cs_files,
        "issue_rules": [i.rule for i in issues],
    }

    hist_path = Path(_history_file(history_dir))
    try:
        with hist_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return {"error": f"Cannot write history: {hist_path}"}

    # Load all runs for summary
    runs = _load_history(history_dir)
    scores = [r.get("score", 0) for r in runs if r.get("score")]
    avg_score = round(sum(scores) / len(scores), 1) if scores else 0

    # Compute trend vs previous run
    trend = compute_trend(history_dir)

    return {
        "total_runs": len(runs),
        "files_scanned": entry["files_scanned"],
        "total_issues": entry["total_issues"],
        "avg_score": avg_score,
        "trend": trend,
    }



def _load_history(history_dir: str) -> list[dict]:
    """Load all history entries from the JSONL file."""
    hist_path = Path(_history_file(history_dir))
    if not hist_path.exists():
        return []
    entries = []
    try:
        for line in hist_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    entries.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        pass
    return entries



def compute_trend(history_dir: str) -> dict:
    """Compare the last two history entries and return trend.

    Returns:
        {
            "issues_delta": N,   # positive = more issues, negative = fewer
            "score_delta": N,    # positive = better, negative = worse
            "direction": "up|down|same",
            "prev_run": timestamp or null,
            "prev_issues": N or null,
            "prev_score": N or null,
        }
    """
    runs = _load_history(history_dir)
    if len(runs) < 2:
        return {
            "issues_delta": 0,
            "score_delta": 0,
            "direction": "same",
            "prev_run": runs[0]["timestamp"] if runs else None,
            "prev_issues": runs[0]["total_issues"] if runs else None,
            "prev_score": runs[0]["score"] if runs else None,
        }

    curr = runs[-1]
    prev = runs[-2]
    curr_issues = curr.get("total_issues", 0)
    prev_issues = prev.get("total_issues", 0)
    curr_score = curr.get("score", 0)
    prev_score = prev.get("score", 0)

    issues_delta = curr_issues - prev_issues
    score_delta = curr_score - prev_score

    if score_delta > 0:
        direction = "up"
    elif score_delta < 0:
        direction = "down"
    else:
        direction = "same"

    return {
        "issues_delta": issues_delta,
        "score_delta": score_delta,
        "direction": direction,
        "prev_run": prev["timestamp"],
        "prev_issues": prev_issues,
        "prev_score": prev_score,
    }
