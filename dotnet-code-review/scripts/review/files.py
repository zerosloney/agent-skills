from __future__ import annotations
import logging
import os
import subprocess
from pathlib import Path

logger = logging.getLogger('dotnet-review')


def normalize_review_path(path: str, project_root: str = "") -> str:
    """Normalize a file path for cross-layer comparison.

    Issue `file` values come from different sources (absolute paths from the
    AST analyzer, project-root-relative paths from builtin analysis, git-relative
    paths from build output). This collapses them to a single canonical form:
    POSIX-style, made relative to project_root when possible, else the basename.
    Shared so scoring-layer suppression and engine changed-only filter agree.
    """
    if not path:
        return ""
    try:
        p = Path(path)
        if project_root:
            try:
                root = Path(project_root).resolve()
                rel = p.resolve().relative_to(root)
                return str(rel).replace("\\", "/")
            except (ValueError, OSError):
                pass
        # Fallback: preserve the full path (POSIX-normalized) rather than just
        # the basename — otherwise identically-named files in different
        # directories collide in dedup_issues and the changed-only filter.
        return str(p).replace("\\", "/")
    except Exception:
        return str(path).replace("\\", "/")


# ============================================================
# File Discovery
# ============================================================

def discover_files(target: str, extensions: list[str]) -> list[str]:
    """Recursively discover files with given extensions."""
    results = []
    skip_dirs = {"node_modules", ".bin", "obj", "bin", ".git", ".nuget", "packages", ".vs"}

    def walk(directory: str):
        try:
            entries = sorted(Path(directory).iterdir(), key=lambda p: p.name)
        except PermissionError:
            return
        for entry in entries:
            if entry.is_dir():
                if entry.name in skip_dirs or entry.name.startswith("."):
                    continue
                walk(str(entry))
            elif entry.is_file():
                ext = entry.suffix.lower()
                if ext in extensions:
                    results.append(str(entry))

    if Path(target).is_file():
        ext = Path(target).suffix.lower()
        if ext in extensions:
            return [target]
        return []

    walk(target)
    return results



def get_diff_files(base_ref: str = "HEAD", target_dir: str = None) -> list[str]:
    """Get changed files from git diff."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=ACMR", base_ref],
            capture_output=True, text=True, timeout=15,
            cwd=target_dir or os.getcwd(),
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.splitlines() if f.strip()]
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return []



def get_changed_line_ranges(
    base_ref: str = "HEAD",
    target_dir: str = None,
) -> dict[str, set[int]]:
    """Get changed line numbers per file from git diff.

    Returns:
        {
            "path/to/file.cs": {10, 11, 12, 25},  # changed line numbers
            ...
        }

    Useful for filtering review issues to only those on newly-changed lines
    (so old issues in unchanged context don't pollute PR review output).
    """
    result_map: dict[str, set[int]] = {}
    try:
        # Use --unified=0 to get just the changed lines (no context)
        # Format: @@ -old_start,old_count +new_start,new_count @@
        proc = subprocess.run(
            ["git", "diff", "--unified=0", base_ref],
            capture_output=True, text=True, timeout=15,
            cwd=target_dir or os.getcwd(),
        )
        if proc.returncode != 0:
            return result_map

        current_file = None
        for line in proc.stdout.splitlines():
            if line.startswith("+++ b/"):
                current_file = line[6:].strip()
                result_map.setdefault(current_file, set())
            elif line.startswith("@@"):
                # Parse hunk header: @@ -a,b +c,d @@
                try:
                    plus = line.split("+")[1].split(" ")[0]
                    if "," in plus:
                        start, count = plus.split(",")
                    else:
                        start, count = plus, "1"
                    start = int(start)
                    count = int(count)
                    if current_file and count > 0:
                        for ln in range(start, start + count):
                            result_map[current_file].add(ln)
                except (ValueError, IndexError):
                    continue
            elif line.startswith("---") or line.startswith("diff"):
                current_file = None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return result_map



def find_csproj_files(target: str) -> list[str]:
    """Find all .csproj files in target directory.

    Prioritizes files not in 'scripts' subdirectories (user project csprojs).
    """
    all_csproj = discover_files(target, [".csproj"])
    if not all_csproj:
        return []

    # Prioritize csproj files NOT in scripts/ subdirectories
    # (these are more likely to be the user's actual project files)
    user_csproj = [f for f in all_csproj if "/scripts/" not in f.replace("\\", "/") and "\\scripts\\" not in f]
    if user_csproj:
        return user_csproj
    return all_csproj
