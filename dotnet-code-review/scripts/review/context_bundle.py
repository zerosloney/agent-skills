"""Context Bundle — extract code context for agent_verify issues.

Provides the Agent with surrounding code context so it can judge whether
an issue is a true positive without needing extra read_files calls.
"""
from __future__ import annotations
import re
from pathlib import Path


def extract_context_bundle(
    file_path: str,
    line: int,
    project_root: str = "",
    context_lines: int = 5,
) -> dict:
    """Extract a context bundle for a single issue.

    Returns a dict with:
    - lines: "start-end" range string
    - code: the source code snippet
    - target_line: the issue line (1-based)
    - enclosing_method: name of the enclosing method (if detectable)
    - enclosing_class: name of the enclosing class (if detectable)
    """
    try:
        full_path = Path(file_path)
        if not full_path.is_absolute() and project_root:
            full_path = Path(project_root) / file_path
        if not full_path.exists():
            return {}

        source_lines = full_path.read_text(
            encoding="utf-8", errors="ignore"
        ).splitlines()

        if line < 1 or line > len(source_lines):
            return {}

        start = max(1, line - context_lines)
        end = min(len(source_lines), line + context_lines)
        code_snippet = "\n".join(source_lines[start - 1:end])

        bundle: dict = {
            "lines": f"{start}-{end}",
            "code": code_snippet,
            "target_line": line,
        }

        # Try to detect enclosing method and class
        method_name = _find_enclosing_method(source_lines, line)
        if method_name:
            bundle["enclosing_method"] = method_name
        class_name = _find_enclosing_class(source_lines, line)
        if class_name:
            bundle["enclosing_class"] = class_name

        return bundle
    except Exception:
        return {}


def _find_enclosing_method(lines: list[str], target_line: int) -> str | None:
    """Walk backwards from target_line to find the enclosing method declaration."""
    # C# method patterns: access_modifier return_type method_name(
    _method_re = re.compile(
        r"^\s*(?:(?:public|private|protected|internal|static|virtual|override|"
        r"abstract|sealed|async|readonly|extern|unsafe|new)\s+)*"
        r"(?:\w+(?:<[^>]+>)?(?:\[\])?)\s+"  # return type
        r"(\w+)\s*\("  # method name + open paren
    )
    for i in range(min(target_line - 1, len(lines) - 1), -1, -1):
        m = _method_re.match(lines[i])
        if m:
            return m.group(1)
    return None


def _find_enclosing_class(lines: list[str], target_line: int) -> str | None:
    """Walk backwards from target_line to find the enclosing class declaration."""
    _class_re = re.compile(
        r"^\s*(?:(?:public|private|protected|internal|abstract|sealed|static|"
        r"partial)\s+)*(?:class|record|struct|interface)\s+(\w+)"
    )
    for i in range(min(target_line - 1, len(lines) - 1), -1, -1):
        m = _class_re.match(lines[i])
        if m:
            return m.group(1)
    return None


def build_context_bundles(
    issues: list,
    project_root: str = "",
    context_lines: int = 5,
) -> dict[tuple[str, int], dict]:
    """Build context bundles for a list of issues.

    Returns a dict keyed by (file, line) for lookup during serialization.
    Only builds bundles for issues with line > 0.
    """
    bundles: dict[tuple[str, int], dict] = {}
    # Group by file to minimize file reads
    file_lines: dict[str, set[int]] = {}
    for issue in issues:
        if issue.line > 0:
            file_lines.setdefault(issue.file, set()).add(issue.line)

    for file_path, line_set in file_lines.items():
        for line in line_set:
            key = (file_path, line)
            if key not in bundles:
                bundle = extract_context_bundle(
                    file_path, line, project_root, context_lines
                )
                if bundle:
                    bundles[key] = bundle

    return bundles
