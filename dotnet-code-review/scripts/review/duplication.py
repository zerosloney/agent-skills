from __future__ import annotations
import hashlib
import logging
import re
from .models import CodeIssue

logger = logging.getLogger('dotnet-review')



DUPLICATE_THRESHOLD_LINES = 6  # Minimum lines to consider as duplicate


def _normalize_code_block(lines: list[str]) -> str:
    normalized = []
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("//"):
            continue
        if "//" in stripped:
            stripped = stripped.split("//")[0].strip()
        if stripped:
            # Replace identifiers with placeholders for fuzzy matching
            stripped = re.sub(r'\b[a-z_]\w*\b', 'x', stripped)
            stripped = re.sub(r'\b[A-Z][a-zA-Z0-9]*\b', 'X', stripped)
            # Collapse multiple spaces
            stripped = re.sub(r'\s+', ' ', stripped)
            normalized.append(stripped)
    return "\n".join(normalized)


def _code_hash(code: str) -> str:
    return hashlib.md5(code.encode("utf-8")).hexdigest()[:12]


def detect_duplicates(file_codes: dict[str, str]) -> list[CodeIssue]:
    """Detect duplicate code blocks across files.

    Args:
        file_codes: dict mapping filepath to source code

    Returns:
        List of CodeIssue for duplicate blocks (reports each duplicate location)
    """
    # Build hash → [(filepath, line_start, normalized_block)]
    blocks: dict[str, list[tuple[str, int, str]]] = {}
    for filepath, code in file_codes.items():
        lines = code.split("\n")
        # Sliding window of DUPLICATE_THRESHOLD_LINES lines
        for i in range(len(lines) - DUPLICATE_THRESHOLD_LINES + 1):
            chunk = lines[i:i + DUPLICATE_THRESHOLD_LINES]
            normalized = _normalize_code_block(chunk)
            if len(normalized.split("\n")) < DUPLICATE_THRESHOLD_LINES:
                continue  # Not enough actual code lines
            h = _code_hash(normalized)
            if h not in blocks:
                blocks[h] = []
            blocks[h].append((filepath, i + 1, normalized))

    # Find duplicates (hash with 2+ occurrences)
    issues = []
    for h, occurrences in blocks.items():
        if len(occurrences) < 2:
            continue
        # Only report if duplicates are in different files (more meaningful)
        files = {occ[0] for occ in occurrences}
        if len(files) < 2:
            continue
        for filepath, line_start, _ in occurrences:
            issues.append(CodeIssue(
                file=filepath,
                line=line_start,
                column=1,
                severity="warning",
                category="style",
                rule="DUP001",
                message=f"Duplicate code block (also in {len(files) - 1} other file(s))",
                source="duplicate",
                suggestion="Extract common code into a shared method or utility class.",
            ))
    return issues
