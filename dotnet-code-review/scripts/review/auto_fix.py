from __future__ import annotations
import logging
import re
import time
from pathlib import Path
from .rules import AUTO_FIXES

logger = logging.getLogger('dotnet-review')


# LEGACY_* rule IDs from the Roslyn AST/semantic layer map to their
# corresponding AUTO_FIX entry keys (the regex-style rule IDs like BP010, P010,
# S003, BP011, S006, R021).  Without this alias map, an authoritative
# Roslyn finding like "LEGACY_throw_ex" would not resolve to the BP011
# auto-fix entry.
RULE_ID_ALIASES: dict[str, str] = {
    "LEGACY_NotImplementedException": "BP010",
    "LEGACY_empty_string_compare": "P010",
    "LEGACY_S003_excessive_region": "S003",
    "LEGACY_throw_ex": "BP011",
    "LEGACY_new_string_char_int": "S006",
    "LEGACY_R021_broad_exception": "R021",
}


def _resolve_fix_rule_id(rule_id: str) -> str:
    """Return the AUTO_FIXES key for an issue's rule id, following aliases."""
    if rule_id in AUTO_FIXES:
        return rule_id
    return RULE_ID_ALIASES.get(rule_id, rule_id)



def apply_auto_fix(
    filepath: str,
    rule_id: str,
    create_backup: bool = True,
) -> tuple[int, str]:
    """Apply auto-fix for a rule on a file.

    Args:
        filepath: Path to .cs file
        rule_id: Rule ID whose fix should be applied
        create_backup: Whether to write a .bak before modifying

    Returns:
        (num_fixes, new_content) — number of replacements applied and the new file content.
        Returns (0, original_content) if rule has no fix or file is unreadable.
    """
    fix_rule_id = _resolve_fix_rule_id(rule_id)
    fixes = AUTO_FIXES.get(fix_rule_id, [])
    if not fixes:
        return 0, ""

    try:
        original = Path(filepath).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return 0, ""

    new_content = original
    total_fixes = 0
    for fix in fixes:
        try:
            pattern = re.compile(fix["find"], re.MULTILINE)
            new_content, n = pattern.subn(fix["replace"], new_content)
            total_fixes += n
        except re.error:
            logger.error("Invalid regex in auto-fix for rule %s: %s", rule_id, fix.get("find", ""))
            continue

    if total_fixes == 0:
        return 0, original

    if create_backup:
        # Primary backup: always .bak (only the latest)
        backup_path = Path(str(filepath) + ".bak")
        try:
            Path(backup_path).write_text(original, encoding="utf-8")
        except OSError:
            backup_path = None
        # Timestamped backup: unique to avoid accidental overwrite
        ts_backup = Path(str(filepath) + f".{int(time.time())}.autofix-bak")
        try:
            Path(ts_backup).write_text(original, encoding="utf-8")
        except OSError:
            pass

    try:
        Path(filepath).write_text(new_content, encoding="utf-8")
        # Optional: verify written content (simple CRC)
        written_check = Path(filepath).read_text(encoding="utf-8", errors="replace")
        if written_check != new_content:
            # restore from primary backup if we created one
            if backup_path and backup_path.exists():
                Path(filepath).write_text(original, encoding="utf-8")
                logger.error(
                    "Write mismatch for %s, reverted from backup", filepath
                )
                return 0, original
    except OSError:
        return 0, original

    return total_fixes, new_content



def apply_all_auto_fixes(
    issues: list,
    create_backup: bool = True,
) -> dict:
    """Apply auto-fixes for all fixable issues.

    Groups issues by file and applies each file's fixes once. A single backup
    (.bak) is written per file capturing the TRUE original content — not an
    intermediate state — so multi-rule fixes can be rolled back atomically.

    Returns:
        {
            "fixed": [{"file": ..., "rule": ..., "count": ..., "description": ...}, ...],
            "skipped": [{"rule": ..., "reason": "no_fix_available"}],
            "files_modified": [...],
            "backup_dir": str,
        }
    """
    fixed_records = []
    skipped = []
    files_modified = set()

    # Group rules per file (preserve first-seen order for deterministic output).
    # Resolve AST/semantic aliases so authoritative findings from the Roslyn
    # layer still attach to their deterministic builtin fix.
    rules_by_file: dict[str, list[str]] = {}
    for issue in issues:
        fix_rule_id = _resolve_fix_rule_id(issue.rule)
        if fix_rule_id in AUTO_FIXES:
            rules_by_file.setdefault(issue.file, [])
            if fix_rule_id not in rules_by_file[issue.file]:
                rules_by_file[issue.file].append(fix_rule_id)
        else:
            skipped.append({"rule": issue.rule, "reason": "no_fix_available"})

    for filepath, rule_ids in rules_by_file.items():
        try:
            original = Path(filepath).read_text(encoding="utf-8", errors="replace")
        except OSError:
            skipped.append({"file": filepath, "reason": "unreadable"})
            continue

        # Apply all of this file's fixes in memory against one content stream.
        content = original
        any_changed = False
        per_rule_counts: list[tuple[str, int, str]] = []
        for rule_id in rule_ids:
            fixes = AUTO_FIXES.get(rule_id, [])
            description = fixes[0]["description"] if fixes else ""
            rule_total = 0
            for fix in fixes:
                pattern = re.compile(fix["find"], re.MULTILINE)
                content, n = pattern.subn(fix["replace"], content)
                rule_total += n
            if rule_total > 0:
                any_changed = True
            per_rule_counts.append((rule_id, rule_total, description))

        if not any_changed:
            for rule_id, _, _ in per_rule_counts:
                skipped.append({"rule": rule_id, "file": filepath, "reason": "pattern_no_match"})
            continue

        # One backup of the TRUE original (not an intermediate state).
        if create_backup:
            backup_path = Path(str(filepath) + ".bak")
            try:
                Path(backup_path).write_text(original, encoding="utf-8")
            except OSError:
                pass

        try:
            Path(filepath).write_text(content, encoding="utf-8")
        except OSError:
            skipped.append({"file": filepath, "reason": "write_failed"})
            continue

        files_modified.add(filepath)
        for rule_id, count, description in per_rule_counts:
            if count > 0:
                fixed_records.append({
                    "file": filepath,
                    "rule": rule_id,
                    "count": count,
                    "description": description,
                })

    return {
        "fixed": fixed_records,
        "skipped": skipped,
        "files_modified": sorted(files_modified),
    }
