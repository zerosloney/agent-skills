

from __future__ import annotations
import json
import logging
import os
import re
import subprocess
import tempfile
import concurrent.futures
from collections.abc import Callable
import time
from functools import lru_cache
from pathlib import Path
from .models import CodeIssue
from .rules import TEST_PROJECT_RELAXED_RULES, WIN_ONLY_API_RULES, AUTO_FIXES
from .files import (
    discover_files,
    get_diff_files,
    get_changed_line_ranges,
    find_csproj_files,
    normalize_review_path,
)
from .framework import (
    parse_target_frameworks,
    classify_framework,
    detect_project_type,
    detect_nuget_packages,
    get_project_metadata,
    pick_strictest_framework,
    detect_framework_from_global_json,
    detect_framework_from_directory_build_props,
)
from .duplication import detect_duplicates
from .coverage import load_coverage, analyze_coverage
from .docs import check_xml_documentation
from .nuget import check_nuget_versions, check_nuget_cves
from .history import save_report_history, compute_trend
from .api_compat import check_api_compatibility
from .scoring import (
    calculate_score,
    count_by_severity,
    estimate_technical_debt,
    dedup_issues,
)
from .auto_fix import apply_all_auto_fixes
from .errors import UserInputError, ToolMissingError, ReviewError, safe_read_file
from .evidence import build_review_integrity, serialize_issue

logger = logging.getLogger("dotnet-review")


# ============================================================
# Complexity Analyzer (Layer 2, retained for tests / compat API)
# NOTE: The Python complexity layer is no longer invoked from run_review().
# These functions remain so that tests can exercise CC001-CC004 detection
# and method-metric extraction via `from review import analyze_complexity`.
# ============================================================


def analyze_complexity(filepath: str, code: str) -> list[CodeIssue]:
    """Analyze cyclomatic complexity, method length, parameter count, nesting depth."""
    issues: list[CodeIssue] = []
    lines = code.split("\n")
    methods = _extract_methods(lines)

    for method in methods:
        # CC001: Cyclomatic complexity
        if method["complexity"] > 20:
            issues.append(
                CodeIssue(
                    file=filepath,
                    line=method["start_line"],
                    column=1,
                    severity="error",
                    category="complexity",
                    rule="CC001",
                    message=f"Cyclomatic complexity of {method['complexity']} in '{method['name']}' exceeds threshold (20)",
                    source="complexity",
                    suggestion=f"Break '{method['name']}' into smaller methods to reduce complexity below 20",
                )
            )
        elif method["complexity"] > 10:
            issues.append(
                CodeIssue(
                    file=filepath,
                    line=method["start_line"],
                    column=1,
                    severity="warning",
                    category="complexity",
                    rule="CC001",
                    message=f"Cyclomatic complexity of {method['complexity']} in '{method['name']}' exceeds threshold (10)",
                    source="complexity",
                    suggestion=f"Consider extracting logic from '{method['name']}' into helper methods",
                )
            )

        # CC002: Method length
        if method["line_count"] > 100:
            issues.append(
                CodeIssue(
                    file=filepath,
                    line=method["start_line"],
                    column=1,
                    severity="error",
                    category="complexity",
                    rule="CC002",
                    message=f"Method '{method['name']}' is {method['line_count']} lines long, exceeds threshold (100)",
                    source="complexity",
                    suggestion=f"Split '{method['name']}' into smaller focused methods (< 50 lines each)",
                )
            )
        elif method["line_count"] > 50:
            issues.append(
                CodeIssue(
                    file=filepath,
                    line=method["start_line"],
                    column=1,
                    severity="warning",
                    category="complexity",
                    rule="CC002",
                    message=f"Method '{method['name']}' is {method['line_count']} lines long, exceeds threshold (50)",
                    source="complexity",
                    suggestion=f"Consider extracting code blocks from '{method['name']}' into helper methods",
                )
            )

        # CC003: Parameter count
        if method["param_count"] > 8:
            issues.append(
                CodeIssue(
                    file=filepath,
                    line=method["start_line"],
                    column=1,
                    severity="error",
                    category="complexity",
                    rule="CC003",
                    message=f"Method '{method['name']}' has {method['param_count']} parameters, exceeds threshold (8)",
                    source="complexity",
                    suggestion="Introduce a parameter object to group related parameters",
                )
            )
        elif method["param_count"] > 5:
            issues.append(
                CodeIssue(
                    file=filepath,
                    line=method["start_line"],
                    column=1,
                    severity="warning",
                    category="complexity",
                    rule="CC003",
                    message=f"Method '{method['name']}' has {method['param_count']} parameters, exceeds threshold (5)",
                    source="complexity",
                    suggestion="Consider using a parameter object or builder pattern",
                )
            )

        # CC004: Nesting depth
        if method["max_nesting"] > 6:
            issues.append(
                CodeIssue(
                    file=filepath,
                    line=method["start_line"],
                    column=1,
                    severity="error",
                    category="complexity",
                    rule="CC004",
                    message=f"Maximum nesting depth of {method['max_nesting']} in '{method['name']}' exceeds threshold (6)",
                    source="complexity",
                    suggestion=f"Extract deeply nested blocks from '{method['name']}' into separate methods or use early returns",
                )
            )
        elif method["max_nesting"] > 4:
            issues.append(
                CodeIssue(
                    file=filepath,
                    line=method["start_line"],
                    column=1,
                    severity="warning",
                    category="complexity",
                    rule="CC004",
                    message=f"Maximum nesting depth of {method['max_nesting']} in '{method['name']}' exceeds threshold (4)",
                    source="complexity",
                    suggestion=f"Reduce nesting in '{method['name']}' by extracting inner blocks or using guard clauses",
                )
            )

    return issues


def _extract_methods(lines: list[str]) -> list[dict]:
    """Extract method signatures and compute metrics."""
    methods = []
    i = 0
    while i < len(lines):
        line = lines[i]
        trimmed = line.strip()
        if _is_method_signature(trimmed):
            name = _extract_method_name(trimmed)
            params = _extract_params(trimmed)
            param_count = (
                len([p for p in params.split(",") if p.strip()]) if params else 0
            )

            # Find opening brace
            brace_start = i
            if "{" not in trimmed:
                j = i + 1
                while j < len(lines):
                    if "{" in lines[j]:
                        brace_start = j
                        break
                    j += 1

            # Scan method body
            depth = 0
            body_started = False
            end_line = brace_start
            complexity = 0
            max_nesting = 0
            line_count = 0

            for j in range(brace_start, len(lines)):
                bl = lines[j]
                for ch in bl:
                    if ch == "{":
                        depth += 1
                        if not body_started:
                            body_started = True
                    elif ch == "}":
                        depth -= 1

                if body_started:
                    max_nesting = max(max_nesting, depth)
                    bt = bl.strip()
                    if _IF_RE.search(bt):
                        complexity += 1
                    if _ELSE_IF_RE.search(bt):
                        complexity += 1
                    if _ELSE_RE.search(bt) and not _ELSE_IF_RE.search(bt):
                        complexity += 1
                    if _FOR_RE.search(bt):
                        complexity += 1
                    if _FOREACH_RE.search(bt):
                        complexity += 1
                    if _WHILE_RE.search(bt):
                        complexity += 1
                    if _DO_RE.search(bt):
                        complexity += 1
                    if _SWITCH_RE.search(bt):
                        complexity += 1
                    if _CASE_RE.search(bt):
                        complexity += 1
                    if _CATCH_RE.search(bt):
                        complexity += 1
                    if _AND_RE.search(bt):
                        complexity += 1
                    if _OR_RE.search(bt):
                        complexity += 1
                    if _TERNARY_RE.search(bt):
                        complexity += 1
                    if _NULL_COALESCE_RE.search(bt):
                        complexity += 1
                    line_count += 1

                if body_started and depth == 0:
                    end_line = j
                    break

            methods.append(
                {
                    "name": name,
                    "start_line": i + 1,
                    "end_line": end_line + 1,
                    "complexity": complexity,
                    "line_count": line_count,
                    "max_nesting": max_nesting,
                    "param_count": param_count,
                }
            )
            i = end_line
        i += 1
    return methods


_CONTROL_FLOW_RE = re.compile(
    r"\b(?:if|for|foreach|while|switch|catch|using|lock|fixed)\s*\("
)
_IF_RE = re.compile(r"\bif\s*\(")
_ELSE_IF_RE = re.compile(r"\belse\s+if\s*\(")
_ELSE_RE = re.compile(r"\belse\b")
_FOR_RE = re.compile(r"\bfor\s*\(")
_FOREACH_RE = re.compile(r"\bforeach\s*\(")
_WHILE_RE = re.compile(r"\bwhile\s*\(")
_DO_RE = re.compile(r"\bdo\b")
_SWITCH_RE = re.compile(r"\bswitch\s*\(")
_CASE_RE = re.compile(r"\bcase\s+")
_CATCH_RE = re.compile(r"\bcatch\s*\(")
_AND_RE = re.compile(r"\b&&\b")
_OR_RE = re.compile(r"\b\|\|\b")
_TERNARY_RE = re.compile(r"\?\s*[^?:]")
_NULL_COALESCE_RE = re.compile(r"\?\?")


def _is_method_signature(trimmed: str) -> bool:
    if (
        not trimmed
        or trimmed.startswith("//")
        or trimmed.startswith("/*")
        or trimmed.startswith("*")
    ):
        return False
    modifiers = [
        "public",
        "private",
        "protected",
        "internal",
        "static",
        "virtual",
        "override",
        "abstract",
        "sealed",
        "async",
        "unsafe",
        "new",
    ]
    if not any(m in trimmed for m in modifiers):
        return False
    if "(" not in trimmed or ")" not in trimmed:
        return False
    if _CONTROL_FLOW_RE.search(trimmed):
        return False
    return True


def _extract_method_name(line: str) -> str:
    # Find last word before (
    paren_idx = line.index("(") if "(" in line else -1
    if paren_idx == -1:
        return "<anonymous>"
    before = line[:paren_idx].rstrip()
    tokens = before.split()
    return tokens[-1] if tokens else "<anonymous>"


def _extract_params(line: str) -> str:
    m = re.search(r"\(([^)]*)\)", line)
    return m.group(1) if m else ""


# ============================================================
# Roslyn AST Analyzer (Layer 3, optional)
# ============================================================


@lru_cache(maxsize=1)
def dotnet_available() -> bool:
    """Check if .NET SDK ≥ 6.0 is available (memoized — result cached for process lifetime).

    Returns True iff `dotnet` command exists AND its version is ≥ 6.0.
    Returns False when SDK is missing or version is below 6.0 — in either case
    `run_review()` will raise `ToolMissingError` (exit code 4) and refuse to
    produce a partial result. We deliberately do NOT soft-degrade to regex-only
    mode because partial findings mislead users into thinking their code was
    actually reviewed at semantic/AST level.
    """
    try:
        result = subprocess.run(
            ["dotnet", "--version"], capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            return False
        version_str = (result.stdout or "").strip()
        # `dotnet --version` outputs e.g. "8.0.101", "6.0.400", "10.0.100".
        parts = version_str.split(".")
        if len(parts) < 2:
            return False
        try:
            major, minor = int(parts[0]), int(parts[1])
        except ValueError:
            return False
        return (major, minor) >= (6, 0)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def get_dotnet_sdk_version() -> str | None:
    """Return the raw `dotnet --version` output string, or None if unavailable.

    Used by error messages to tell the user exactly what version (if any) was
    detected. Memoized via dotnet_available()'s lru_cache so we don't pay the
    subprocess cost twice.
    """
    try:
        result = subprocess.run(
            ["dotnet", "--version"], capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            return (result.stdout or "").strip() or None
        return None
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None

# Windows cmdline length limit: 8191 chars for CreateProcessW on the OS side.
# Python's subprocess.run joins the list with spaces, so the total can exceed this
# when passing 77+ file paths + references. These helpers split extra_args into
# batches that each fit within the limit.
_WINDOWS_CMDLINE_LIMIT: int = 8191
_CMDLINE_SAFETY_MARGIN: int = 200  # leave room for quote chars and edge cases


def _chunk_file_args(analyzer_name: str, extra_args: list[str]) -> list[list[str]]:
    """Split extra_args into batches that fit within Windows cmdline limit.

    The command prefix (``dotnet <dll_path> --``) uses ~150-200 chars.
    Remaining space is for ``--files <paths>``, ``--references <paths>``, etc.

    Returns a list of arg-lists, each safe to pass to subprocess.run.
    When no chunking is needed, returns ``[extra_args]``.
    """
    # Prefix: "dotnet " (7) + dll_path (~120-140) + " -- " (4) ≈ 170 chars
    _prefix_len = 170

    total_len = _prefix_len + sum(len(a) + 1 for a in extra_args)
    if total_len <= _WINDOWS_CMDLINE_LIMIT - _CMDLINE_SAFETY_MARGIN:
        return [extra_args]

    if "--files" not in extra_args:
        # Positional args (AST analyzer) — chunk directly by character length
        available = _WINDOWS_CMDLINE_LIMIT - _CMDLINE_SAFETY_MARGIN - _prefix_len
        chunks: list[list[str]] = []
        batch: list[str] = []
        batch_len = -1  # start at -1 so first item doesn't add a leading space
        for a in extra_args:
            a_len = len(a) + 1
            if batch_len + a_len > available and batch:
                chunks.append(batch)
                batch = []
                batch_len = -1
            batch.append(a)
            batch_len += a_len
        if batch:
            chunks.append(batch)
        return chunks

    # Split --files <paths> into batches, keeping suffix args (--references, etc.) intact
    fi = extra_args.index("--files")
    prefix = extra_args[:fi + 1]        # everything up to and including "--files"
    suffix_start = fi + 1
    file_args: list[str] = []
    for i in range(suffix_start, len(extra_args)):
        if extra_args[i].startswith("--"):
            suffix_start = i
            break
        file_args.append(extra_args[i])
    else:
        suffix_start = len(extra_args)
    suffix = extra_args[suffix_start:]  # --references, --incremental, etc.

    # How much room is left for file paths?
    fixed_len = _prefix_len
    fixed_len += sum(len(a) + 1 for a in prefix)
    fixed_len += sum(len(a) + 1 for a in suffix)
    available = _WINDOWS_CMDLINE_LIMIT - _CMDLINE_SAFETY_MARGIN - fixed_len

    chunks = []
    batch = []
    batch_len = -1
    for f in file_args:
        f_len = len(f) + 1
        if batch_len + f_len > available and batch:
            chunks.append(prefix + batch + suffix)
            batch = []
            batch_len = -1
        batch.append(f)
        batch_len += f_len
    if batch:
        chunks.append(prefix + batch + suffix)

    return chunks if chunks else [extra_args]


def _write_file_list(paths: list[str]) -> str:
    """Write a list of file paths to a temp file for --file-list / --references-file.

    Returns the path to the temp file. The caller should clean up the temp file
    in a try/finally block after the subprocess completes.
    """
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".filelist.txt", delete=False, encoding="utf-8")
    for p in paths:
        tmp.write(p + "\n")
    tmp.close()
    return tmp.name


def _build_analyzer_command(analyzer_name: str, extra_args: list[str]) -> list[str]:
    """Build the command to run a Roslyn analyzer.

    Prefers a prebuilt DLL (``dotnet <path>.dll``) when available — this skips
    the MSBuild project evaluation and per-run JIT cost of ``dotnet run``.
    Falls back to ``dotnet run --project <csproj>`` if the DLL is not found
    (e.g. fresh checkout before a build).

    The analyzer is expected to live in scripts/<analyzer_name>/ and be built
    via ``dotnet build`` (Debug output at bin/Debug/net6.0/).
    """
    analyzer_dir = Path(__file__).resolve().parent.parent / analyzer_name
    csproj = analyzer_dir / f"{analyzer_name}.csproj"
    # Check common build output locations (Debug first, then Release).
    dll = analyzer_dir / "bin" / "Debug" / "net6.0" / f"{analyzer_name}.dll"
    if not dll.exists():
        dll = analyzer_dir / "bin" / "Release" / "net6.0" / f"{analyzer_name}.dll"
    if dll.exists():
        return ["dotnet", str(dll), "--"] + extra_args
    # Fallback: dotnet run (incurs JIT on every call, but works without a build step)
    return ["dotnet", "run", "--project", str(csproj), "--"] + extra_args


def analyze_ast(files: list[str], project_root: str = "",
                cache_dir: str | None = None) -> list[CodeIssue]:
    """Run Roslyn-based AST analyzer on original file paths (requires .NET SDK).

    零误报的语法树级精确检测，直接传入原始文件路径，保留文件路径上下文。

    ``project_root`` is used to canonicalize the absolute ``source_file`` paths
    emitted by the C# analyzer (which echoes back the resolved absolute path it
    was given on argv) to project-root-relative form — so issues land in the
    correct file and survive the ``--changed-only`` line filter.

    When ``cache_dir`` is set, per-file AST results are cached by content hash.
    Files whose content is unchanged since the last run skip the subprocess call
    entirely (safe because the AST analyzer processes each file independently).
    """
    if not files:
        return []
    if not dotnet_available():
        return []

    ast_dir = Path(__file__).resolve().parent.parent / "csharp-ast-analyzer"
    if not (ast_dir / "csharp-ast-analyzer.csproj").exists():
        return []

    # Convert to absolute paths (AST analyzer needs absolute paths)
    abs_files = [str(Path(f).resolve()) for f in files]

    # ── Cache check: separate cached files from uncached ──
    cached_issues: list[CodeIssue] = []
    uncached_abs: list[str] = []
    if cache_dir:
        from .cache import load_cache
        for abs_f in abs_files:
            cached_raw = load_cache(cache_dir, abs_f)
            if cached_raw is not None:
                cached_issues.extend(
                    _parse_ast_diagnostics(cached_raw, project_root, files)
                )
            else:
                uncached_abs.append(abs_f)
    else:
        uncached_abs = abs_files

    if not uncached_abs:
        return cached_issues

    # ── Run AST analyzer on uncached files, chunked to avoid Windows cmdline limit ──
    args_chunks = _chunk_file_args("csharp-ast-analyzer", uncached_abs)
    all_new_issues: list[CodeIssue] = []
    for chunk_idx, chunk in enumerate(args_chunks):
        try:
            cmd = _build_analyzer_command("csharp-ast-analyzer", chunk)
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=120,
            )

            # dotnet run outputs warnings to stdout, JSON is in stderr
            output = result.stdout
            if result.returncode != 0 or not output.strip():
                output = result.stderr

            # Extract JSON from output (skip warnings)
            json_start = output.find("{")
            if json_start >= 0:
                json_text = output[json_start:]
            else:
                continue

            data = json.loads(json_text)
            new_issues = _parse_ast_diagnostics(
                data.get("diagnostics", []), project_root, files
            )
            if new_issues:
                all_new_issues.extend(new_issues)

            # ── Save cache per-file ──
            if cache_dir:
                from .cache import save_cache
                raw_diags = data.get("diagnostics", [])
                file_raw: dict[str, list[dict]] = {}
                for d in raw_diags:
                    raw_src = d.get("source_file", "")
                    if raw_src:
                        file_raw.setdefault(raw_src, []).append(d)
                for src_abs, diags in file_raw.items():
                    save_cache(cache_dir, src_abs, diags)

        except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError) as e:
            logger.warning("AST analyzer chunk %d/%d failed: %s",
                           chunk_idx + 1, len(args_chunks), e)
    return cached_issues + all_new_issues


def _parse_ast_diagnostics(
    raw_diags: list[dict],
    project_root: str,
    original_files: list[str],
) -> list[CodeIssue]:
    """Convert raw AST analyzer diagnostics to CodeIssue list.

    Shared between fresh analyzer output and cached results so both follow
    the same path normalization and rule-meta lookup.
    """
    from .rules import get_ast_rule_meta

    issues: list[CodeIssue] = []
    for d in raw_diags:
        src_file = d.get("source_file", "")
        if src_file:
            src_file = normalize_review_path(src_file, project_root)
        elif original_files:
            src_file = original_files[0]

        ast_code = d.get("code", "AST")
        meta = get_ast_rule_meta(ast_code)

        issues.append(
            CodeIssue(
                file=src_file,
                line=d.get("line", 0),
                column=0,
                severity=d.get("severity", "info"),
                category=meta["category"],
                rule=ast_code,
                message=d.get("message", ""),
                source="ast",
                suggestion=meta["suggestion"],
            )
        )
    return issues


# ============================================================
# Semantic Analyzer (Layer 3b, optional)
# ============================================================


def analyze_semantic(
    files: list[str], incremental: bool = False, cache_dir: str | None = None,
    project_root: str = "", references: list[str] | None = None,
    solution_path: str | None = None,
) -> tuple[list[CodeIssue], dict]:
    """Run Roslyn SemanticModel-based analyzer (requires .NET SDK).

    Args:
        files: List of C# files to analyze.
        incremental: Enable incremental compilation (reuse Compilation object).
        cache_dir: Directory for caching Compilation state.
        project_root: Used to canonicalize absolute file paths emitted by the
            analyzer into project-root-relative form.
        references: Additional DLL paths to add as compilation references
            (e.g. NuGet package DLLs from the project's obj/ directory).
            When provided, the semantic analyzer can resolve external types
            and produce more accurate SEM_* diagnostics.
        solution_path: Path to .sln file for cross-project type resolution.
            When set, the C# analyzer will resolve dependency DLLs and
            optionally expand to all solution source files.

    Returns (issues, extra_data) where extra_data contains
    cognitive_complexity and technical_debt_minutes from semantic analysis.
    """
    if not files:
        return [], {}
    if not dotnet_available():
        return [], {}

    sem_dir = Path(__file__).resolve().parent.parent / "csharp-semantic-analyzer"
    if not (sem_dir / "csharp-semantic-analyzer.csproj").exists():
        return [], {}

    # Convert to absolute paths (AST analyzer needs absolute paths)
    abs_files = [str(Path(f).resolve()) for f in files]

    # Build command — use --file-list / --references-file to avoid Windows cmdline limit.
    # The C# analyzers read paths line-by-line from these temp files.
    filelist_path = _write_file_list(abs_files)
    extra = ["--file-list", filelist_path]
    refs_path = None
    if references:
        refs_path = _write_file_list(references)
        extra += ["--references-file", refs_path]
    if incremental:
        extra.append("--incremental")
        if cache_dir:
            extra.extend(["--cache-dir", cache_dir])
    # Pass --solution to the C# analyzer for cross-project type resolution
    if solution_path:
        extra += ["--solution", solution_path]
    cmd = _build_analyzer_command("csharp-semantic-analyzer", extra)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        # dotnet run outputs warnings to stdout, JSON is in stderr
        output = result.stdout
        if result.returncode != 0 or not output.strip():
            output = result.stderr

        # Extract JSON from output (skip warnings)
        json_start = output.find("{")
        if json_start >= 0:
            json_text = output[json_start:]
        else:
            return [], {}
        data = json.loads(json_text)
        issues = []
        for d in data.get("diagnostics", []):
            # Canonicalize the absolute path emitted by the C# analyzer so the
            # issue lands in the correct file under --changed-only filtering.
            src_file = d.get("file", "")
            if src_file:
                src_file = normalize_review_path(src_file, project_root)
            elif files:
                src_file = files[0]

            issues.append(
                CodeIssue(
                    file=src_file,
                    line=d.get("line", 0),
                    column=0,
                    severity=d.get("severity", "info"),
                    category=d.get("category") or _fallback_semantic_category(d.get("code", "SEM")),
                    rule=d.get("code", "SEM"),
                    message=d.get("message", ""),
                    source="semantic",
                    suggestion=d.get("suggestion", ""),
                )
            )

        # Propagate incremental cache statistics (for hit-rate regression tests).
        extra = {}
        if "cache_stats" in data:
            extra["cache_stats"] = data["cache_stats"]
        # Propagate compilation error count so the engine can report degradation.
        comp_err_count = data.get("compilation_error_count", 0)
        if comp_err_count:
            extra["compilation_error_count"] = comp_err_count
            logger.warning("Semantic analyzer: %d compilation errors — "
                           "type-dependent rules (SEM_*) may be degraded", comp_err_count)

        # Log incremental compilation status
        if data.get("incremental_used"):
            logger.info("Semantic analyzer used incremental compilation")

        return issues, extra
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("Semantic analyzer failed (Layer 3b skipped): %s", e)
        return [], {}
    finally:
        # Clean up temp file lists created for --file-list / --references-file.
        for _p in [filelist_path, refs_path]:
            if _p:
                try:
                    os.unlink(_p)
                except OSError:
                    pass


def _fallback_semantic_category(code: str) -> str:
    """Infer a scoring category from a SEM_* rule code prefix.

    Used when the C# semantic analyzer did not emit a category for a
    particular diagnostic (older builds without the Category field).
    """
    prefix = code.split("_")[0] if "_" in code else code
    return {
        "SEM": "semantic",
        "EF": "reliability",
        "P": "performance",
        "ASYNC": "best-practice",
        "LAYER": "architecture",
        "ARCH": "architecture",
    }.get(prefix.upper(), "semantic")


def suppress_ast_semantic_overlap(
    ast_issues: list[CodeIssue],
    sem_issues: list[CodeIssue],
) -> tuple[list[CodeIssue], int]:
    """Suppress AST findings already validated as legal by the semantic layer.

    Handles:
    - SEM_OUTREF_NULL_SAFE -> suppresses LEGACY_null_assignment (R002)
      at the same (file, line) because SemanticModel confirms the identifier
      resolves to an out/ref parameter whose null-assignment is C# mandated.

    Returns (filtered_ast_issues, suppressed_count).
    """
    if not sem_issues:
        return ast_issues, 0

    safe_lines: set[tuple[str, int]] = {
        (i.file, i.line)
        for i in sem_issues
        if i.rule == "SEM_OUTREF_NULL_SAFE" and i.file and i.line
    }
    if not safe_lines:
        return ast_issues, 0

    before = len(ast_issues)
    kept = [
        i for i in ast_issues
        if not (
            i.rule == "LEGACY_null_assignment"
            and (i.file, i.line) in safe_lines
        )
    ]
    return kept, before - len(kept)


# ============================================================
# Project Analyzer (Layer 3c, optional)
# ============================================================


def analyze_project(files: list[str]) -> dict:
    """Run project-level cross-file analyzer (requires .NET SDK).

    Returns project analysis data including cycles, god_classes,
    architectural_violations, type_metrics, etc.
    """
    if not files:
        return {}
    if not dotnet_available():
        return {}

    proj_dir = Path(__file__).resolve().parent.parent / "csharp-project-analyzer"
    if not (proj_dir / "csharp-project-analyzer.csproj").exists():
        return {}

    abs_files = [str(Path(f).resolve()) for f in files]
    filelist_path = _write_file_list(abs_files)
    try:
        cmd = _build_analyzer_command(
            "csharp-project-analyzer", ["--file-list", filelist_path]
        )
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=120,
        )

        # dotnet run may emit build warnings to stdout before the JSON result.
        # The output always contains a top-level "tool" key; find it and
        # back up to the opening brace to get the exact JSON start.
        output = result.stdout or result.stderr
        if not output.strip():
            return {}

        tool_idx = output.find('"tool"')
        if tool_idx < 0:
            return {}
        json_start = output.rfind("{", 0, tool_idx)
        if json_start < 0:
            return {}

        try:
            return json.loads(output[json_start:])
        except json.JSONDecodeError:
            return {}
    except (json.JSONDecodeError, subprocess.TimeoutExpired, OSError) as e:
        logger.warning("Project analyzer failed (Layer 3c skipped): %s", e)
        return {}
    finally:
        try:
            os.unlink(filelist_path)
        except OSError:
            pass


def _project_findings_to_issues(project_analysis: dict) -> list[CodeIssue]:
    """Convert project-level findings into CodeIssues.

    The project analyzer (Layer 3c) computes dependency cycles, cross-layer
    violations and god classes. Previously these only surfaced in a side
    ``project_analysis`` summary block and never entered ``issues``, so they
    did not affect the score/quality gate. This materializes them as concrete
    issues with stable rule IDs:

    - ``LAYER001`` — cross-layer dependency violation (architecture/design)
    - ``ARCH001``  — dependency cycle (architecture/design)
    - ``CS006``    — god class (maintainability; reuses the cataloged id)

    Each issue is attached at ``line=0`` (file/project-level finding).
    """
    issues: list[CodeIssue] = []
    if not isinstance(project_analysis, dict):
        return issues

    cross_layer_violations = (
        project_analysis.get("crossLayerViolations")
        or project_analysis.get("cross_layer_violations")
        or []
    )
    god_classes = (
        project_analysis.get("godClasses")
        or project_analysis.get("god_classes")
        or []
    )
    orphan_types = (
        project_analysis.get("orphanTypes")
        or project_analysis.get("orphan_types")
        or []
    )
    architectural_violations = (
        project_analysis.get("architecturalViolations")
        or project_analysis.get("architectural_violations")
        or []
    )

    for viol in cross_layer_violations:
        # viol is a human-readable string like "Foo.cs:Controllers 依赖了低层模块 Data"
        text = str(viol)
        first_file = text.split(":", 1)[0] or "project"
        issues.append(
            CodeIssue(
                file=first_file,
                line=0,
                column=0,
                severity="warning",
                category="architecture",
                rule="LAYER001",
                message=text,
                source="project",
                suggestion="将跨层依赖改为通过接口/抽象层注入，避免高层直接依赖低层实现。",
            )
        )

    for cyc in project_analysis.get("cycles", []) or []:
        files = cyc.get("files", []) if isinstance(cyc, dict) else []
        desc = (
            cyc.get("description", " → ".join(files))
            if isinstance(cyc, dict)
            else str(cyc)
        )
        first_file = (files[0] if files else desc.split(":", 1)[0]) or "project"
        issues.append(
            CodeIssue(
                file=first_file,
                line=0,
                column=0,
                severity="warning",
                category="architecture",
                rule="ARCH001",
                message=f"依赖循环: {desc}",
                source="project",
                suggestion="打破循环：提取共享抽象到独立程序集，或用接口反转依赖方向。",
            )
        )

    for gc in god_classes:
        if isinstance(gc, dict):
            name = gc.get("name") or gc.get("type") or gc.get("file") or "project"
            file_name = gc.get("file") or name
            members = gc.get("memberCount") or gc.get("members") or gc.get("totalMembers") or "?"
            issues.append(
                CodeIssue(
                    file=str(file_name),
                    line=0,
                    column=0,
                    severity="warning",
                    category="maintainability",
                    rule="CS006",
                    message=f"God class '{name}': 成员数 {members} 过多，违反单一职责",
                    source="project",
                    suggestion="按职责拆分为多个高内聚类，每个类聚焦单一变更原因。",
                )
            )

    for ot in orphan_types:
        if isinstance(ot, dict):
            otype = ot.get("type") or "unknown"
            ofile = ot.get("file") or "project"
            issues.append(
                CodeIssue(
                    file=str(ofile),
                    line=0,
                    column=0,
                    severity="info",
                    category="architecture",
                    rule="LAYER002",
                    message=f"孤儿类型 '{otype}': 定义但未被其他文件引用",
                    source="project",
                    suggestion="若类型确实需要则确保有引用方；若为遗留代码考虑删除。",
                )
            )

    for av in architectural_violations:
        if isinstance(av, dict):
            atype = av.get("type") or "unknown"
            afile = av.get("file") or "project"
            problem = av.get("problem") or ""
            issues.append(
                CodeIssue(
                    file=str(afile),
                    line=0,
                    column=0,
                    severity="warning",
                    category="architecture",
                    rule="ARCH002",
                    message=f"架构违反: '{atype}' — {problem}",
                    source="project",
                    suggestion="重新评估该类型的抽象度与稳定性，考虑提取接口或拆分实现。",
                )
            )

    # ── ARCH003: Uncalled public methods ──
    uncalled = (
        project_analysis.get("uncalled_public_methods")
        or project_analysis.get("uncalledPublicMethods")
        or []
    )
    for um in uncalled:
        method_name = um.get("method", "?")
        file_name = um.get("file", "")
        issues.append(
            CodeIssue(
                file=file_name,
                line=0,
                severity="info",
                category="architecture",
                rule="ARCH003",
                message=f"未调用的 public 方法: {method_name}",
                source="project",
                suggestion="确认是否为入口点/反射调用/Web API endpoint，否则标记为已废弃或移除。",
            )
        )

    # ── ARCH004: Interfaces without implementation ──
    no_impl = (
        project_analysis.get("interfaces_without_impl")
        or project_analysis.get("interfacesWithoutImpl")
        or []
    )
    for ni in no_impl:
        iface_name = ni.get("type", "?")
        file_name = ni.get("file", "")
        issues.append(
            CodeIssue(
                file=file_name,
                line=0,
                severity="warning",
                category="architecture",
                rule="ARCH004",
                message=f"接口 {iface_name} 在所有输入文件中无实现类",
                source="project",
                suggestion="添加实现类，或标记为已废弃接口。",
            )
        )

    return issues


# ============================================================
# Build Diagnostics (Layer 4, optional)
# ============================================================


# Properties in csproj that explicitly disable .NET analyzers. MSBuild property
# precedence: a value declared inside the csproj overrides a `/p:` passed on the
# command line, so when the project opts out we must NOT inject (it would be a
# silent no-op). We surface that case as a skipped-project reason instead.
# intentional-simple: regex scan, no XML parse. MSBuild property syntax is stable
# enough that a case-insensitive tag + value match is reliable; upgrade to an XML
# parser only if `<Choose>`/conditional `<PropertyGroup>` complexity is needed.
_NETANALYZERS_DISABLE_PATTERNS = [
    re.compile(r"<EnableNETAnalyzers\s*>\s*false\s*</EnableNETAnalyzers>", re.I),
    re.compile(r"<AnalysisLevel\s*>\s*none\s*</AnalysisLevel>", re.I),
    re.compile(r"<AnalysisMode\s*>\s*none\s*</AnalysisMode>", re.I),
]


def _csproj_disables_netanalyzers(content: str) -> bool:
    """Return True if the csproj explicitly opts out of .NET analyzers."""
    return any(p.search(content) for p in _NETANALYZERS_DISABLE_PATTERNS)


def analyze_build(
    csproj_path: str,
    project_root: str,
    framework_type: str | None = None,
    enable_netanalyzers: bool = True,
) -> tuple[list[CodeIssue], dict]:
    """Run dotnet build for compile diagnostics.

    Parses MSBuild's standard diagnostic line format:
        <file>(<line>,<col>): <severity> <CODE>: <message> [<project>]
    The previous implementation split on the *severity token* and then re-derived
    the file path with `^([^(]+)`, which truncated Windows drive letters (the `:` in
    `C:\\` collided with the colon lexer) and dropped the project suffix on
    continuation lines. We now anchor on the leading `file(line,col)` segment so
    drive letters and UNC paths survive, and tolerate `file:line:col` (the
    console-logger alternative form) as a fallback.

    Returns ``(issues, netanalyzers_info)`` where ``netanalyzers_info`` reports
    whether the official Microsoft .NET analyzers (CAxxxx) were injected for this
    project::

        {"injected": bool, "skipped_reason": str | None}

    Injection is opt-in per call: ``enable_netanalyzers=True`` AND
    ``framework_type=="modern"`` AND the csproj does not explicitly disable them
    (csproj-level opt-out wins over ``/p:`` per MSBuild precedence, so we respect
    it instead of silently no-op'ing). Legacy (.NET Framework) projects are not
    injected because they lack the SDK-bundled analyzer and would require a
    PackageReference (out of scope — that would mutate project files).
    """
    no_inject_reason: str | None = None
    if not dotnet_available():
        return [], {"injected": False, "skipped_reason": "dotnet SDK unavailable"}

    full_path = Path(project_root) / csproj_path
    if not full_path.exists():
        return [], {"injected": False, "skipped_reason": "csproj not found"}

    try:
        content = full_path.read_text(encoding="utf-8", errors="ignore")
        is_sdk = "<Project Sdk=" in content

        # Decide NetAnalyzers injection before constructing cmd.
        inject_na = False
        if enable_netanalyzers and is_sdk:
            if framework_type != "modern":
                no_inject_reason = (
                    ".NET Framework requires manual PackageReference "
                    "(Microsoft.CodeAnalysis.NetAnalyzers)"
                )
            elif _csproj_disables_netanalyzers(content):
                no_inject_reason = "project explicitly disabled NetAnalyzers"
            else:
                inject_na = True
        elif not enable_netanalyzers:
            no_inject_reason = "--skip-netanalyzers"

        if is_sdk:
            cmd = ["dotnet", "build", csproj_path, "--no-restore", "-nologo"]
            if inject_na:
                cmd += ["/p:EnableNETAnalyzers=true",
                        "/p:AnalysisLevel=latest-recommended"]
        else:
            cmd = [
                "dotnet",
                "msbuild",
                csproj_path,
                "/t:Build",
                "/p:Configuration=Debug",
                "/p:TreatWarningsAsErrors=false",
                "/clp:ErrorsOnly",
                "/nologo",
            ]

        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=120, cwd=project_root
        )
        combined = result.stdout + result.stderr
    except (subprocess.TimeoutExpired, OSError):
        return [], {"injected": False, "skipped_reason": "build invocation failed"}

    issues = _parse_msbuild_diagnostics(combined)
    return issues, {
        "injected": inject_na,
        "skipped_reason": no_inject_reason,
    }


# MSBuild console-logger diagnostic line. Anchored on the leading file path +
# (line,col) parenthesised segment so drive letters (`C:\`) and UNC paths are
# preserved (previous `^([^(]+)` regex truncated them). Severity token follows,
# then the code (CS/CA/IDE/NET/...) and message; optional `[project]` suffix.
_MSBUILD_DIAG_RE = re.compile(
    r"^(?P<file>.+?)\((?P<line>\d+)(?:,(?P<col>\d+))?\):\s+"
    r"(?P<sev>error|warning)\s+"
    r"(?P<code>[A-Z][A-Z0-9]+):\s*(?P<msg>.+?)"  # code must be all-caps letters/digits
    r"\s*(?:\[(?P<proj>[^\]]+)\])?\s*$",
    re.IGNORECASE,
)

_MSBUILD_DIAG_COLON_RE = re.compile(
    r"^(?P<file>.+?):(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<sev>error|warning)\s+"
    r"(?P<code>[A-Z][A-Z0-9]+):\s*(?P<msg>.+?)"
    r"\s*(?:\[(?P<proj>[^\]]+)\])?\s*$",
    re.IGNORECASE,
)


def _iter_msbuild_diag_fields(text: str):
    """Yield parsed diagnostic fields for each matching line.

    Handles ``file(line,col): severity CODE: message [proj]`` and
    ``file:line:col: severity CODE: message [proj]``. Does NOT filter by code —
    callers decide which diagnostic IDs they care about (build keeps CS/CA/IDE,
    format keeps IDE/WHITESPACE/...). Yields dicts with keys: file, line, sev,
    code, msg.
    """
    for line in text.splitlines():
        stripped = line.strip()
        m = _MSBUILD_DIAG_RE.match(stripped) or _MSBUILD_DIAG_COLON_RE.match(stripped)
        if not m:
            continue
        try:
            line_num = int(m.group("line"))
        except (TypeError, ValueError):
            line_num = 0
        yield {
            "file": m.group("file").strip(),
            "line": line_num,
            "sev": "error" if m.group("sev").lower() == "error" else "warning",
            "code": m.group("code").upper(),
            "msg": m.group("msg").strip() or stripped[:200],
        }


def _parse_msbuild_diagnostics(text: str) -> list[CodeIssue]:
    """Parse MSBuild console output into CodeIssue objects.

    Handles `file(line,col): severity CODE: message [proj]` and
    `file:line:col: severity CODE: message [proj]`. Lines that don't match
    (continuation lines, summaries) are skipped. Keeps only CS/CA/IDE codes —
    other MSBuild tokens (NET-, MSB...) are not review issues.
    """
    issues: list[CodeIssue] = []
    for d in _iter_msbuild_diag_fields(text):
        code = d["code"]
        if not re.match(r"^(CS|CA|IDE)\d+$", code):
            continue
        category = _build_rule_category(code)
        suggestion = _build_rule_suggestion(code, d["msg"])
        issues.append(
            CodeIssue(
                file=d["file"],
                line=d["line"],
                column=0,
                severity=d["sev"],
                category=category,
                rule=code,
                message=d["msg"],
                source="build",
                suggestion=suggestion,
            )
        )
    return issues


# ── Build rule category mapping (CS/CA → review category) ──
# Fallback chain: explicit map → keyword heuristic → "style".
_BUILD_RULE_CATEGORIES: dict[str, str] = {
    # Security
    "CA5350": "security", "CA5351": "security", "CA5379": "security",
    "CA5380": "security", "CA5381": "security", "CA5382": "security",
    "CA5383": "security", "CA5384": "security", "CA5385": "security",
    "CA5386": "security", "CA5387": "security", "CA5388": "security",
    "CA5389": "security", "CA5390": "security", "CA5391": "security",
    "CA5392": "security", "CA5393": "security", "CA5394": "security",
    "CA5395": "security", "CA5396": "security", "CA5397": "security",
    "CA5398": "security", "CA5399": "security",
    "CA3001": "security", "CA3002": "security", "CA3003": "security",
    "CA3004": "security", "CA3005": "security", "CA3006": "security",
    "CA3007": "security", "CA3008": "security", "CA3009": "security",
    "CA3010": "security", "CA3011": "security", "CA3012": "security",
    "CA3013": "security", "CA3014": "security", "CA3015": "security",
    "CA3016": "security", "CA3017": "security", "CA3018": "security",
    "CA3019": "security", "CA3020": "security", "CA3021": "security",
    "CA3022": "security", "CA3023": "security",
    "CA2257": "security",
    # Performance
    "CA1822": "performance", "CA1823": "performance", "CA1824": "performance",
    "CA1825": "performance", "CA1826": "performance", "CA1827": "performance",
    "CA1828": "performance", "CA1829": "performance", "CA1830": "performance",
    "CA1831": "performance", "CA1832": "performance", "CA1833": "performance",
    "CA1834": "performance", "CA1835": "performance", "CA1836": "performance",
    "CA1837": "performance", "CA1838": "performance", "CA1839": "performance",
    "CA1840": "performance", "CA1841": "performance", "CA1842": "performance",
    "CA1843": "performance", "CA1844": "performance", "CA1845": "performance",
    "CA1846": "performance", "CA1847": "performance", "CA1848": "performance",
    "CA1849": "performance", "CA1850": "performance", "CA1851": "performance",
    "CA1852": "performance", "CA1853": "performance", "CA1854": "performance",
    "CA1855": "performance", "CA1856": "performance", "CA1857": "performance",
    "CA1858": "performance", "CA1859": "performance", "CA1860": "performance",
    "CA1861": "performance", "CA1862": "performance", "CA1863": "performance",
    "CA1864": "performance", "CA1865": "performance", "CA1866": "performance",
    "CA1867": "performance", "CA1868": "performance", "CA1869": "performance",
    "CA1870": "performance", "CA1871": "performance",
    "CA2007": "performance",
    # Reliability
    "CA2000": "reliability", "CA2001": "reliability", "CA2002": "reliability",
    "CA2003": "reliability", "CA2004": "reliability", "CA2005": "reliability",
    "CA2006": "reliability", "CA2008": "reliability", "CA2009": "reliability",
    "CA2010": "reliability", "CA2011": "reliability", "CA2012": "reliability",
    "CA2013": "reliability", "CA2014": "reliability", "CA2015": "reliability",
    "CA2016": "reliability", "CA2017": "reliability", "CA2018": "reliability",
    "CA2019": "reliability", "CA2020": "reliability", "CA2021": "reliability",
    "CA2022": "reliability", "CA2023": "reliability", "CA2024": "reliability",
    "CA2025": "reliability", "CA2026": "reliability", "CA2027": "reliability",
    "CA2028": "reliability", "CA2029": "reliability", "CA2030": "reliability",
    "CA2031": "reliability", "CA2032": "reliability", "CA2033": "reliability",
    "CA2034": "reliability", "CA2035": "reliability", "CA2036": "reliability",
    "CA2201": "reliability", "CA2202": "reliability", "CA2207": "reliability",
    "CA2208": "reliability", "CA2211": "reliability", "CA2213": "reliability",
    "CA2214": "reliability", "CA2215": "reliability", "CA2216": "reliability",
    "CA2217": "reliability", "CA2218": "reliability", "CA2219": "reliability",
    "CA2220": "reliability", "CA2221": "reliability", "CA2222": "reliability",
    "CA2223": "reliability", "CA2224": "reliability", "CA2225": "reliability",
    "CA2226": "reliability", "CA2227": "reliability", "CA2228": "reliability",
    "CA2229": "reliability", "CA2230": "reliability", "CA2231": "reliability",
    "CA2232": "reliability", "CA2233": "reliability", "CA2234": "reliability",
    "CA2235": "reliability", "CA2236": "reliability", "CA2237": "reliability",
    "CA2238": "reliability", "CA2240": "reliability", "CA2241": "reliability",
    "CA2242": "reliability", "CA2243": "reliability",
    "CA1031": "reliability",
    # Globalization
    "CA1303": "globalization", "CA1304": "globalization", "CA1305": "globalization",
    "CA1306": "globalization", "CA1307": "globalization", "CA1308": "globalization",
    "CA1309": "globalization", "CA1310": "globalization", "CA1311": "globalization",
    "CA1312": "globalization", "CA1313": "globalization",
    # Design / API compatibility
    "CA1000": "design", "CA1001": "design", "CA1002": "design", "CA1003": "design",
    "CA1004": "design", "CA1005": "design", "CA1006": "design", "CA1007": "design",
    "CA1008": "design", "CA1009": "design", "CA1010": "design", "CA1011": "design",
    "CA1012": "design", "CA1013": "design", "CA1014": "design", "CA1015": "design",
    "CA1016": "design", "CA1017": "design", "CA1018": "design", "CA1019": "design",
    "CA1020": "design", "CA1021": "design", "CA1022": "design", "CA1023": "design",
    "CA1024": "design", "CA1025": "design", "CA1026": "design", "CA1027": "design",
    "CA1028": "design", "CA1029": "design", "CA1030": "design",
    "CA1040": "design", "CA1041": "design", "CA1042": "design", "CA1043": "design",
    "CA1044": "design", "CA1045": "design", "CA1046": "design", "CA1047": "design",
    "CA1050": "design", "CA1051": "design", "CA1052": "design", "CA1053": "design",
    "CA1054": "design", "CA1055": "design", "CA1056": "design", "CA1057": "design",
    "CA1060": "design", "CA1061": "design", "CA1062": "design", "CA1063": "design",
    "CA1064": "design", "CA1065": "design", "CA1066": "design", "CA1067": "design",
    "CA1068": "design", "CA1069": "design", "CA1070": "design",
    "CA1200": "design", "CA1201": "design", "CA1202": "design", "CA1203": "design",
    "CA1300": "design", "CA1301": "design", "CA1302": "design",
    # Note: CA1707-CA1757 are Naming rules, categorized below in the Naming
    # block — not duplicated here. CA1810-1821 stay under design.
    "CA1810": "design", "CA1812": "design", "CA1813": "design",
    "CA1814": "design", "CA1815": "design", "CA1816": "design", "CA1817": "design",
    "CA1819": "design", "CA1820": "design", "CA1821": "design",
    "CA2100": "design", "CA2101": "design", "CA2102": "design", "CA2103": "design",
    "CA2104": "design", "CA2105": "design", "CA2106": "design", "CA2107": "design",
    "CA2108": "design", "CA2109": "design", "CA2110": "design", "CA2111": "design",
    "CA2112": "design", "CA2113": "design", "CA2114": "design", "CA2115": "design",
    "CA2116": "design", "CA2117": "design", "CA2118": "design", "CA2119": "design",
    "CA2120": "design", "CA2121": "design", "CA2122": "design", "CA2123": "design",
    "CA2124": "design", "CA2125": "design", "CA2126": "design", "CA2127": "design",
    "CA2128": "design", "CA2129": "design", "CA2130": "design", "CA2131": "design",
    "CA2132": "design", "CA2133": "design", "CA2134": "design", "CA2135": "design",
    "CA2136": "design", "CA2137": "design", "CA2138": "design", "CA2139": "design",
    "CA2140": "design", "CA2141": "design", "CA2142": "design", "CA2143": "design",
    "CA2144": "design", "CA2145": "design", "CA2146": "design", "CA2147": "design",
    "CA2148": "design", "CA2149": "design", "CA2150": "design", "CA2151": "design",
    "CA2152": "design", "CA2153": "design", "CA2154": "design", "CA2155": "design",
    "CA2156": "design", "CA2157": "design", "CA2158": "design", "CA2159": "design",
    # Usage
    "CA2200": "usage",
    "CA2244": "usage", "CA2245": "usage", "CA2246": "usage",
    "CA2247": "usage", "CA2248": "usage", "CA2249": "usage",
    "CA2250": "usage", "CA2251": "usage", "CA2252": "usage", "CA2253": "usage",
    "CA2254": "usage", "CA2255": "usage", "CA2256": "usage",
    # Naming
    "CA1700": "naming", "CA1701": "naming", "CA1702": "naming", "CA1703": "naming",
    "CA1704": "naming", "CA1705": "naming", "CA1706": "naming", "CA1707": "naming",
    "CA1708": "naming", "CA1709": "naming", "CA1710": "naming", "CA1711": "naming",
    "CA1712": "naming", "CA1713": "naming", "CA1714": "naming", "CA1715": "naming",
    "CA1716": "naming", "CA1717": "naming", "CA1720": "naming", "CA1721": "naming",
    "CA1724": "naming", "CA1725": "naming", "CA1726": "naming", "CA1727": "naming",
    "CA1728": "naming", "CA1730": "naming", "CA1731": "naming", "CA1732": "naming",
    "CA1733": "naming", "CA1734": "naming", "CA1735": "naming", "CA1736": "naming",
    "CA1737": "naming", "CA1738": "naming", "CA1739": "naming", "CA1740": "naming",
    "CA1741": "naming", "CA1742": "naming", "CA1743": "naming", "CA1744": "naming",
    "CA1745": "naming", "CA1746": "naming", "CA1747": "naming", "CA1748": "naming",
    "CA1749": "naming", "CA1750": "naming", "CA1751": "naming", "CA1752": "naming",
    "CA1753": "naming", "CA1754": "naming", "CA1755": "naming", "CA1756": "naming",
    "CA1757": "naming",
}


# CAxxxx sub-categories produced by _BUILD_RULE_CATEGORIES that are NOT scoring
# dimensions. These are kept as-is on the issue (useful for display/grouping),
# and scoring.calculate_score folds them into the closest scoring dimension.
# See scoring.CATEGORY_NORMALIZATION. Map is mirrored here so the data flow is
# discoverable from either direction.
_NON_SCORING_CATEGORIES = {"globalization", "design", "usage"}


def _build_rule_category(code: str) -> str:
    mapped = _BUILD_RULE_CATEGORIES.get(code.upper())
    if mapped:
        return mapped
    # Fallback: keyword heuristic on the code prefix
    if code.startswith("CA30") or code.startswith("CA21"):
        return "security"
    if code.startswith("CA18") or code.startswith("CA18"):
        return "performance"
    if code.startswith("CA10") or code.startswith("CS0067"):
        return "semantic"
    return "style"


# ── Build rule suggestion mapping (CS/CA → review suggestion) ──
_BUILD_RULE_SUGGESTIONS: dict[str, str] = {
    "CA1822": "Mark the method as static (static keyword) since it does not access instance data.",
    "CA1305": "Specify IFormatProvider/CultureInfo explicitly for culture-sensitive operations.",
    "CA1307": "Specify StringComparison (e.g., StringComparison.Ordinal) for string comparisons.",
    "CA5350": "Replace weak cryptographic algorithms (MD5, SHA1, DES) with stronger alternatives (SHA256, AES).",
    "CA2000": "Ensure disposable objects are explicitly disposed (using statement or Dispose() call).",
    "CA2201": "Do not throw exceptions from Dispose() — log or suppress instead.",
    "CA1031": "Catch specific exception types rather than catching generic Exception.",
    "CA2007": "Consider awaiting Task directly (add ConfigureAwait(false) for library code).",
    "CA1062": "Validate input parameters (Guard.Against.Null/ArgumentNullException) before dereferencing.",
    "CA2241": "Use Path.GetRandomFileName() or a safe temp file approach instead of Path.GetTempFileName().",
    "CA2257": "Mark obsolete members with [Obsolete] attribute and provide migration guidance.",
    "CS0168": "Variable is declared but never used — remove or prefix with _ to indicate intentional.",
    "CS0219": "Variable is assigned but never read — remove assignment or use the value.",
    "CS0649": "Field is never assigned — initialize or remove if unnecessary.",
    "CS1998": "Async method lacks await — remove async keyword or add await to fix compiler warning.",
    "CA1810": "Add a static constructor to initialize static fields explicitly (deterministic type initialization).",
    "CA1812": "Remove the internal class or mark it as used if it is part of the API surface.",
    "CA1815": "Override Equals and GetHashCode on value types for correct equality semantics.",
    "CA1819": "Properties should not return arrays — return IReadOnlyList<T> or ImmutableArray<T>.",
    "CA1825": "Avoid zero-length array allocations — use Array.Empty<T>() instead of new T[0].",
    "CA1848": "Use string.Concat or string.Create for string concatenation with 2-3 strings instead of StringBuilder.",
    "CA1851": "Avoid multiple enumerations of IEnumerable — cache with ToList() or iterate once.",
    "CA1860": "Use Span<T>.IndexOf instead of string.IndexOf for substring search in hot paths.",
}


def _build_rule_suggestion(code: str, msg: str) -> str:
    return _BUILD_RULE_SUGGESTIONS.get(code.upper(), "")


# ── Format/IDE rule mapping (Layer 5: dotnet format diagnostics) ──
_FORMAT_RULE_CATEGORIES: dict[str, str] = {
    # Formatting
    "IDE0055": "style",
    "IDE0005": "style",
    "WHITESPACE": "style",
    # Performance
    "IDE0057": "performance",
    "IDE0059": "performance",
    "IDE0067": "performance",
    "IDE0017": "performance",
    "IDE0019": "performance",
    "IDE0029": "performance",
    "IDE0030": "performance",
    "IDE0031": "performance",
    "IDE0032": "performance",
    "IDE0033": "performance",
    "IDE0040": "performance",
    "IDE0071": "performance",
    "IDE0290": "performance",
    "IDE0300": "performance",
    # Naming
    "IDE0060": "naming",
    "IDE1006": "naming",
    "IDE0056": "naming",
    "IDE0058": "naming",
    "IDE0075": "naming",
    "IDE0082": "naming",
    "IDE0095": "naming",
    "IDE0105": "naming",
    # Reliability / correctness
    "IDE0039": "reliability",
    "IDE0044": "reliability",
    "IDE0160": "reliability",
    "IDE0161": "reliability",
    "IDE0180": "reliability",
    "IDE0305": "reliability",
}


def _format_rule_category(code: str) -> str:
    mapped = _FORMAT_RULE_CATEGORIES.get(code.upper())
    if mapped:
        return mapped
    # Default: style
    return "style"


_FORMAT_RULE_SUGGESTIONS: dict[str, str] = {
    "IDE0055": "Apply dotnet format or configure .editorconfig to fix this formatting rule.",
    "IDE0005": "Remove the unnecessary using directive to clean up imports.",
    "IDE0057": "Use string.Create or StringBuilder for complex string concatenation.",
    "IDE0059": "Use the assigned value or remove the unnecessary assignment.",
    "IDE0067": "Unsubscribe from the event to prevent memory leaks.",
    "IDE0017": "Inline simple object allocation into its single use site.",
    "IDE0029": "Simplify null check using pattern matching: `if (x is null)`.",
    "IDE1006": "Name the parameter with meaningful camelCase name.",
    "IDE0060": "Remove unused parameter or use the discard pattern `_`.",
    "IDE0075": "Simplify conditional expression using pattern matching or null-coalescing.",
    "IDE0082": "Use `nameof(Class)` instead of `typeof(Class)` for string comparisons.",
}


def _format_rule_suggestion(code: str, msg: str) -> str:
    return _FORMAT_RULE_SUGGESTIONS.get(code.upper(), "")


def analyze_format(csproj_path: str, project_root: str) -> list[CodeIssue]:
    """Run dotnet format for code style diagnostics (SDK Style only).

    ``--verbosity diagnostic`` is required: the default output has no file/line
    info, only the ``Format summary`` line. At diagnostic verbosity dotnet format
    emits the same ``file(line,col): severity IDExxxx: message`` format as
    MSBuild, so we reuse ``_parse_msbuild_diagnostics`` and then keep only IDE*
    codes, rewriting ``source``/``category`` to ``format``/``style``.
    """
    if not dotnet_available():
        return []

    full_path = Path(project_root) / csproj_path
    if not full_path.exists():
        return []

    try:
        content = full_path.read_text(encoding="utf-8", errors="ignore")
        if "<Project Sdk=" not in content:
            return []

        result = subprocess.run(
            [
                "dotnet", "format", csproj_path,
                "--verify-no-changes", "--no-restore",
                "--verbosity", "diagnostic",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=project_root,
        )
        combined = result.stdout + result.stderr

        # Reuse the MSBuild line parser: same `file(line,col): severity CODE: msg`
        # shape. dotnet format emits IDE* (code style) and WHITESPACE (formatter)
        # codes; CS/CA come from analyze_build and are excluded here. Other free-
        # text tokens (WHITESPACE is the dominant formatter one) are kept so the
        # format layer reports real formatting violations, not just style rules.
        _FORMAT_CODE = re.compile(r"^(IDE\d+|WHITESPACE|DOTNET_FORMAT)$")
        issues = [
            CodeIssue(
                file=d["file"],
                line=d["line"],
                column=0,
                severity="warning" if d["code"] == "WHITESPACE" else d["sev"],
                category=_format_rule_category(d["code"]),
                rule=d["code"],
                message=d["msg"],
                source="format",
                suggestion=_format_rule_suggestion(d["code"], d["msg"]),
            )
            for d in _iter_msbuild_diag_fields(combined)
            if _FORMAT_CODE.match(d["code"])
        ]
        return issues
    except (subprocess.TimeoutExpired, OSError):
        return []


# ============================================================
# Custom Rules
# ============================================================


def load_custom_rules(project_root: str) -> list[dict]:
    """Load custom rules from .dotnet-review/rules.json."""
    rule_path = Path(project_root) / ".dotnet-review" / "rules.json"
    if not rule_path.exists():
        return []
    try:
        data = json.loads(rule_path.read_text(encoding="utf-8"))
        return data.get("rules", [])
    except (json.JSONDecodeError, OSError):
        return []


def load_suppressions(project_root: str) -> list[dict]:
    """Load issue suppressions from ``.dotnet-review/suppress.json``.

    Format::

        {
          "suppressions": [
            {"rule": "LEGACY_async_void", "reason": "intentional fire-and-forget"},
            {"rule": "LEGACY_T016_datetime_now", "file": "Program.cs", "reason": "entry point"},
            {"rule": "CS006", "line": 42, "file": "Services/BigService.cs", "reason": "WIP"}
          ]
        }

    A suppression matches an issue when ``rule`` matches AND any specified
    ``file``/``line`` also matches (``file`` matches by basename or suffix so
    absolute/relative paths both work; ``line`` is exact). ``reason`` is
    optional but recommended.

    Security: suppression text is treated strictly as data — it is never
    executed, never interpreted as code, and never used to generate fixes
    (suppressed issues simply don't appear). This mirrors the custom-rules
    injection-trust boundary.
    """
    sup_path = Path(project_root) / ".dotnet-review" / "suppress.json"
    if not sup_path.exists():
        return []
    try:
        data = json.loads(sup_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    sups = data.get("suppressions", [])
    if not isinstance(sups, list):
        return []
    # Only keep dict entries with a rule id; drop malformed entries silently.
    return [s for s in sups if isinstance(s, dict) and s.get("rule")]


def _matches_suppression(issue: CodeIssue, sup: dict, project_root: str) -> bool:
    """True if ``issue`` is covered by suppression entry ``sup``."""
    if issue.rule != sup.get("rule"):
        return False
    sup_file = sup.get("file")
    if sup_file:
        # Match by suffix/basename so absolute & relative paths both work.
        norm_sup = str(sup_file).replace("\\", "/").lower()
        norm_issue = issue.file.replace("\\", "/").lower()
        if not (
            norm_issue == norm_sup
            or norm_issue.endswith("/" + norm_sup)
            or norm_issue.endswith(norm_sup)
            or norm_issue.rsplit("/", 1)[-1] == norm_sup.rsplit("/", 1)[-1]
        ):
            return False
    # Line range matching: line_from <= issue.line <= line_to
    sup_line_from = sup.get("line_from")
    sup_line_to = sup.get("line_to")
    if sup_line_from is not None or sup_line_to is not None:
        issue_line = issue.line
        if sup_line_from is not None and issue_line < int(sup_line_from):
            return False
        if sup_line_to is not None and issue_line > int(sup_line_to):
            return False
    elif sup.get("line") is not None:
        if issue.line != int(sup["line"]):
            return False
    return True


def apply_suppressions(
    issues: list[CodeIssue], suppressions: list[dict], project_root: str
) -> tuple[list[CodeIssue], int]:
    """Filter out suppressed issues.

    Returns ``(kept_issues, suppressed_count)``. ``suppressed_count`` is tracked
    so callers can report how many were hidden (transparency — silent mass
    suppression should be visible in the summary).
    """
    if not suppressions:
        return issues, 0
    kept: list[CodeIssue] = []
    suppressed = 0
    for issue in issues:
        if any(_matches_suppression(issue, s, project_root) for s in suppressions):
            suppressed += 1
        else:
            kept.append(issue)
    return kept, suppressed


def calculate_maintainability_index(
    halstead_volume: float,
    cyclomatic_complexity: float,
    lines_of_code: int,
) -> float:
    """Calculate Maintainability Index (MI).

    Uses the Microsoft variant of the formula:
        MI = MAX(0, (171 - 5.2 * ln(V) - 0.23 * CC - 16.2 * ln(LOC)) * 100 / 171)

    Args:
        halstead_volume: Halstead Volume (approximated if not measured)
        cyclomatic_complexity: Average cyclomatic complexity
        lines_of_code: Lines of code

    Returns:
        MI score (0-100), higher is more maintainable
    """
    import math

    if halstead_volume <= 0:
        halstead_volume = lines_of_code  # Rough approximation
    if lines_of_code <= 0:
        return 100.0
    raw = (
        171
        - 5.2 * math.log(halstead_volume)
        - 0.23 * cyclomatic_complexity
        - 16.2 * math.log(lines_of_code)
    )
    return max(0.0, min(100.0, raw * 100 / 171))


# ============================================================
# Custom Rules
# ============================================================


def analyze_custom(filepath: str, code: str, rules: list[dict]) -> list[CodeIssue]:
    """Analyze against custom rules."""
    issues = []
    lines = code.split("\n")
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        pattern = rule.get("pattern", "")
        if not pattern:
            continue
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error:
            continue
        for line_idx, line in enumerate(lines):
            for match in compiled.finditer(line):
                issues.append(
                    CodeIssue(
                        file=filepath,
                        line=line_idx + 1,
                        column=match.start() + 1,
                        severity=rule.get("severity", "warning"),
                        category=rule.get("category", "best-practice"),
                        rule=rule.get("id", "CUSTOM"),
                        message=rule.get("message", ""),
                        source="custom",
                        suggestion=rule.get("suggestion", ""),
                    )
                )
    return issues


def _normalize_review_path(path: str, project_root: str) -> str:
    """Normalize a file path for cross-layer comparison.

    Thin wrapper over the shared `files.normalize_review_path` so the engine's
    changed-only filter and the scoring layer's suppression agree on a single
    canonical form.
    """
    from .files import normalize_review_path

    return normalize_review_path(path, project_root)


def _csproj_for_files(cs_files: list[str], max_depth: int = 8) -> list[str]:
    """Find the .csproj owning each file in ``--files`` mode.

    For each reviewed source file, walk up the directory tree (bounded by
    ``max_depth``) to locate the nearest ``.csproj``. This scopes the csproj
    audit and framework detection to the projects the changed files actually
    belong to, instead of discovering every csproj under the repository root
    (which floods the report with unrelated CSPROJ001 EOL noise).

    Returns a deduplicated list of csproj absolute paths. Callers should fall
    back to ``find_csproj_files`` when this returns empty (e.g. files passed
    without an enclosing project).
    """
    found: list[str] = []
    seen: set[str] = set()
    for cs in cs_files:
        try:
            current = Path(cs).resolve().parent
        except OSError:
            continue
        for _ in range(max_depth):
            try:
                candidates = sorted(current.glob("*.csproj"))
            except (OSError, PermissionError):
                break
            if candidates:
                for proj in candidates:
                    p = str(proj.resolve())
                    if p not in seen:
                        seen.add(p)
                        found.append(p)
                break  # nearest csproj found for this file
            parent = current.parent
            if parent == current:
                break  # filesystem root
            current = parent
    return found



# ============================================================
# Main Review Logic
# ============================================================


def _cpu_count() -> int:
    """Return the number of available CPUs, defaulting to 1."""
    try:
        return os.cpu_count() or 1
    except NotImplementedError:
        return 1


def _parallel_map_files(
    func: Callable[[str, str], list[CodeIssue]],
    file_codes: dict[str, str],
    layer_name: str,
    max_workers: int | None = None,
) -> list[CodeIssue]:
    """Run a file-level analysis function across all files in parallel.

    Args:
        func: Function taking (filepath, code) and returning a list of CodeIssue.
        file_codes: Mapping of filepath to source code.
        layer_name: Human-readable layer name for logging.
        max_workers: Max parallel workers (default: min(8, cpu_count)).

    Returns:
        Combined list of issues from all files.
    """
    results: list[CodeIssue] = []
    workers = max_workers or min(8, _cpu_count())
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {
            pool.submit(func, fp, code): fp
            for fp, code in file_codes.items()
        }
        for f in concurrent.futures.as_completed(futures):
            try:
                results.extend(f.result())
            except Exception as e:
                logger.warning("%s check failed for %s: %s", layer_name, futures[f], e)
    return results


def run_review(args) -> dict:
    """Main review entry point."""
    start_time = time.time()
    project_root = os.getcwd()

    # ── .NET SDK hard gate (fail-fast, no soft degradation) ──
    # C# code review without Roslyn is misleading: regex-only mode misses
    # cross-file, type-aware, and AST-level defects, so a "0 issues" report
    # would falsely imply the code was actually reviewed. Refuse to run and
    # tell the user exactly what to install.
    if not dotnet_available():
        detected = get_dotnet_sdk_version()
        if detected is None:
            reason = "no `dotnet` command found on PATH"
        else:
            reason = (
                f"detected .NET SDK {detected} is below the required minimum (.NET 6.0)"
            )
        raise ToolMissingError(
            f".NET SDK ≥ 6.0 is required for C# code review ({reason}).",
            details={
                "required": ".NET SDK 6.0 or later",
                "detected": detected,
                "install_url": "https://dotnet.microsoft.com/download",
                "recommended": ".NET 8.0 LTS",
            },
            fix="Install .NET SDK 6+ from https://dotnet.microsoft.com/download "
            "(LTS recommended: .NET 8.0), then re-run this command. "
            "We do NOT fall back to regex-only review because partial "
            "findings would be misleading.",
        )

    # ── File Discovery ──
    cs_files = []
    if args.diff:
        cs_files = get_diff_files(args.diff, project_root)
        cs_files = [f for f in cs_files if f.endswith(".cs")]
    elif args.files:
        cs_files = args.files
        # 如果用户也指定了 --target，使用它作为项目根目录
        if args.target:
            project_root = args.target
        else:
            # Derive project root from the common parent of the reviewed files
            # instead of using CWD. This prevents finding unrelated csproj
            # files (e.g. the skill's own analyzer projects in scripts/) when
            # the user only wants to review specific .cs files.
            file_paths = [Path(f).resolve() for f in args.files if Path(f).exists()]
            if file_paths:
                common = Path(os.path.commonpath([p.parent for p in file_paths]))
                # Walk up to find a directory that actually contains a .csproj;
                # if none found, use the common parent as-is.
                search_dir = common
                for _ in range(5):
                    if list(search_dir.glob("*.csproj")):
                        project_root = str(search_dir)
                        break
                    if search_dir.parent == search_dir:
                        break
                    search_dir = search_dir.parent
                else:
                    project_root = str(common)
    elif args.all:
        # --all takes a directory argument; guard against an empty value
        # (e.g. a stray/unset arg) so we don't crash on Path(None).
        scan_dir = args.all or project_root
        cs_files = discover_files(scan_dir, [".cs"])
        project_root = scan_dir
    elif args.target:
        # Auto-detect: try git diff first, fall back to full scan
        cs_files = get_diff_files("HEAD", args.target)
        cs_files = [f for f in cs_files if f.endswith(".cs")]
        if not cs_files:
            cs_files = discover_files(args.target, [".cs"])
        project_root = args.target
    else:
        cs_files = discover_files(project_root, [".cs"])

    if not cs_files:
        # No .cs files found — distinguish explicit-target vs no-args for better UX
        explicit_target = bool(args.target or args.files or args.all or args.diff)
        if explicit_target:
            # User explicitly asked for something → return empty result (not an error)
            return {
                "project_root": project_root,
                "framework_version": "",
                "framework_type": "unknown",
                "project_type": "unknown",
                "frameworks": [],
                "nuget_packages": [],
                "metadata": {},
                "files_scanned": 0,
                "total_issues": 0,
                "score": calculate_score([]),
                "by_severity": {"error": 0, "warning": 0, "info": 0},
                "issues": [],
                "layers": {
                    "builtin": 0,
                    "complexity": 0,
                    "ast": 0,
                    "build": 0,
                    "format": 0,
                },
                "error": "No .cs files found",
            }
        # No args at all → user probably wants help
        raise UserInputError(
            f"No .cs files found in current directory: {project_root}",
            details={"project_root": project_root},
            fix="Specify --target <path>, --files <file.cs>, or --diff <ref> to review code.",
        )

    # ── Preview mode ──
    if args.preview:
        return {
            "project_root": project_root,
            "files_scanned": len(cs_files),
            "files": cs_files,
            "mode": "preview",
        }

    # ── Framework & Project Detection ──
    csproj_files = find_csproj_files(project_root)
    frameworks: list[str] = []
    framework = ""
    framework_type = "unknown"
    project_type = "unknown"
    nuget_packages: list[dict] = []
    project_metadata: dict = {}

    if csproj_files:
        frameworks = parse_target_frameworks(csproj_files[0])
        # Multi-target projects (e.g. net48;net8.0): pick the strictest
        # framework for rule filtering so the tightest constraints apply.
        if len(frameworks) > 1:
            framework = pick_strictest_framework(frameworks)
        elif frameworks:
            framework = frameworks[0]
        else:
            framework = ""
        framework_type = classify_framework(framework)
        project_type = detect_project_type(csproj_files[0])
        nuget_packages = detect_nuget_packages(csproj_files[0])
        # Detect whether the project has test framework references.
        _TEST_PACKAGE_PREFIXES = ("xunit", "nunit", "mstest", "shouldly", "fluentassertions", "moq", "nsubstitute")
        test_available = any(
            p.get("name", "").lower().startswith(_TEST_PACKAGE_PREFIXES)
            for p in nuget_packages
        ) if nuget_packages else False
        project_metadata = get_project_metadata(csproj_files[0])
    else:
        # No csproj found — try fallback sources for framework detection.
        # This handles --files / --diff scans where project files aren't included.
        fallback = (
            detect_framework_from_global_json(project_root)
            or detect_framework_from_directory_build_props(project_root)
        )
        if fallback:
            framework = fallback
            frameworks = [fallback]
            framework_type = classify_framework(framework)
            logger.info("Framework detected from fallback: %s", framework)

    # ── Allow --target-framework override (Agent-prompted or user-supplied) ──
    override_framework = getattr(args, "target_framework", None)
    if override_framework:
        framework = override_framework
        frameworks = [override_framework]
        framework_type = classify_framework(override_framework)

    # ── Analyze ──
    all_issues: list[CodeIssue] = []
    layer_counts = {
        "builtin": 0,
        "complexity": 0,
        "ast": 0,
        "semantic": 0,
        "project": 0,
        "build": 0,
        "format": 0,
    }
    executed_layers: set[str] = set()
    skipped_layer_details: list[dict] = []
    project_analysis: dict = {}
    sem_extra: dict = {}
    semantic_cache_stats: dict = {}

    # Cache file contents once per file — avoid re-reading in 5 downstream passes
    # (Layer 7 + duplicate detection + MI/cognitive computation all need source).
    file_codes: dict[str, str] = {}

    for filepath in cs_files:
        try:
            # safe_read_file falls back UTF-8 → BOM → GBK → latin-1, so non-UTF-8
            # source (common on Windows) reaches duplicate/XML-doc checks intact
            # instead of being silently corrupted by errors="replace" (U+FFFD).
            # Note: the authoritative Roslyn analyzers read files independently
            # via subprocess and are unaffected — this only feeds Python-layer
            # consumers (detect_duplicates, check_xml_documentation).
            code = safe_read_file(filepath)
        except (OSError, ReviewError):
            continue
        file_codes[filepath] = code

        # Python regex-based review layers are intentionally disabled. C# code
        # findings now come from Roslyn/dotnet layers only; this also avoids
        # replaying stale regex findings from the old --cache path.

    # ── Custom Rules (.dotnet-review/rules.json) ─
    # User-defined regex rules supplement the built-in Roslyn analyzers.
    # Only loaded when .dotnet-review/rules.json exists; skipped silently otherwise.
    custom_rules = load_custom_rules(project_root)
    if custom_rules:
        executed_layers.add("custom")
        for filepath, code in file_codes.items():
            custom_issues = analyze_custom(filepath, code, custom_rules)
            all_issues.extend(custom_issues)
        layer_counts["custom"] = sum(1 for i in all_issues if i.source == "custom")

    # ── Layer 6: Duplicate Code Detection (zero dependency) ──
    # CLI exposes --no-duplicates (store_true). Honor it; default = run.
    no_duplicates = getattr(args, "no_duplicates", False)
    if not no_duplicates:
        executed_layers.add("duplicate")
        # Reuse file_codes already loaded in the main pass (no re-reads)
        dup_issues = detect_duplicates(file_codes)
        # Suppress DUP001 noise from ORM entity boilerplate in Domain/Entities/
        # and Domain/Models/ directories. These files contain auto-generated
        # _field + property patterns that hash-identically match across entities.
        _ENTITY_BOILERPLATE_PATHS = [
            "/Domain/Entities/",
            "/Domain/Models/",
        ]
        for issue in dup_issues:
            if issue.rule == "DUP001":
                file_normalized = issue.file.replace("\\", "/")
                if any(p in file_normalized for p in _ENTITY_BOILERPLATE_PATHS):
                    issue.severity = "info"
        all_issues.extend(dup_issues)
        layer_counts["duplicate"] = len(dup_issues)
    else:
        skipped_layer_details.append({"layer": "duplicate", "reason": "--no-duplicates"})

    # ── Layer 6b: Coverage Analysis (optional, Cobertura XML) ──
    coverage_data = {}
    coverage_path = getattr(args, "coverage", None)
    if coverage_path:
        coverage_data = load_coverage(coverage_path)
        if coverage_data:
            executed_layers.add("coverage")
            coverage_threshold = getattr(args, "coverage_threshold", 0.6)
            coverage_issues = analyze_coverage(
                cs_files, coverage_data, coverage_threshold
            )
            all_issues.extend(coverage_issues)
            layer_counts["coverage"] = len(coverage_issues)
        else:
            skipped_layer_details.append(
                {"layer": "coverage", "reason": "coverage report missing or invalid"}
            )

    # ── Layer 7: XML Documentation Check (zero dependency) ──
    # CLI exposes --no-docs (store_true). Honor it; default = run.
    no_docs = getattr(args, "no_docs", False)
    if not no_docs:
        executed_layers.add("doc")
        _doc_issues = _parallel_map_files(check_xml_documentation, file_codes, "Doc")

        all_issues.extend(_doc_issues)
        layer_counts["doc"] = len(_doc_issues)
    else:
        skipped_layer_details.append({"layer": "doc", "reason": "--no-docs"})

    # ── Layer 7b: Style comment check (S001/S002/S005, zero dependency) ──
    # These detect TODO/FIXME without author and commented-out code. Pure text
    # scan. Parallelized across files.
    executed_layers.add("style")
    _style_issues: list[CodeIssue] = []

    def _check_style_file(filepath: str, code: str) -> list[CodeIssue]:
        issues: list[CodeIssue] = []
        for i, line in enumerate(code.split("\n"), 1):
            stripped = line.strip()
            # S001: TODO without author (// TODO not followed by ( or :)
            if re.search(r"//\s*TODO(?![(:])", stripped):
                issues.append(CodeIssue(
                    file=filepath, line=i, severity="info", category="style",
                    rule="S001", message="TODO without author",
                    source="style", suggestion="Format as `// TODO(username): message`."))
            # S002: FIXME without plan
            if re.search(r"//\s*FIXME", stripped):
                issues.append(CodeIssue(
                    file=filepath, line=i, severity="info", category="style",
                    rule="S002", message="FIXME without plan",
                    source="style", suggestion="Add a linked issue number and description."))
            # S005: commented-out code (// if|for|foreach|while|switch|return|var|int|string|bool)
            if re.match(r"//\s*(?:if|for|foreach|while|switch|return|var|int|string|bool)\b", stripped):
                issues.append(CodeIssue(
                    file=filepath, line=i, severity="info", category="style",
                    rule="S005", message="Commented-out code",
                    source="style", suggestion="Remove dead code. Use source control history if needed later."))
        return issues

    _style_issues = _parallel_map_files(_check_style_file, file_codes, "Style")
    all_issues.extend(_style_issues)
    layer_counts["style"] = len(_style_issues)

    # ── Layer 7c: Performance text hints (P021 Span, info only) ──
    executed_layers.add("perf_hint")
    _perf_issues: list[CodeIssue] = []

    def _check_perf_file(filepath: str, code: str) -> list[CodeIssue]:
        issues: list[CodeIssue] = []
        for i, line in enumerate(code.split("\n"), 1):
            stripped = line.strip()
            # P021: prefer Span<T> — flag byte[] parameters in hot-path signatures
            if re.search(r"\bbyte\[\]\s+\w+", stripped) and "override" not in stripped:
                issues.append(CodeIssue(
                    file=filepath, line=i, severity="info", category="performance",
                    rule="P021", message="byte[] parameter — consider Span<byte> for zero-copy",
                    source="style", suggestion="Use Span<T> or ReadOnlySpan<T> to avoid array allocations."))
        return issues

    _perf_issues = _parallel_map_files(_check_perf_file, file_codes, "Perf hint")
    all_issues.extend(_perf_issues)
    layer_counts["perf_hint"] = sum(1 for i in _perf_issues if i.rule == "P021")

    # ── Layer 8: NuGet Version Check ──
    if nuget_packages:
        executed_layers.add("nuget")
        nuget_issues = check_nuget_versions(nuget_packages)
        all_issues.extend(nuget_issues)
        layer_counts["nuget"] = len(nuget_issues)

    # ── Layer 3: AST (optional, batch mode for efficiency) ──
    sdk_present = dotnet_available()
    skipped_layers: list[str] = []
    if not sdk_present:
        # Defensive fallback only. `run_review()` already raises ToolMissingError
        # (exit code 4) when dotnet_available() is False, so under normal CLI
        # invocation we never reach this branch. It remains here to keep the
        # run_review() function usable from unit tests that monkeypatch
        # dotnet_available() mid-execution. Do NOT delete.
        skipped_layers = ["ast", "semantic", "project", "build", "format"]
        skipped_layer_details.extend(
            {"layer": layer, "reason": ".NET SDK unavailable"}
            for layer in skipped_layers
        )
        logger.warning(
            ".NET SDK not found mid-execution — skipping Layer 3/4/5 "
            "(AST, semantic, project-level, build, format). This path is "
            "unreachable from the CLI; reachable only from test monkeypatching."
        )
    else:
        if getattr(args, "skip_semantic", False):
            skipped_layers.append("semantic")
            skipped_layer_details.append({"layer": "semantic", "reason": "--skip-semantic"})
        if getattr(args, "skip_project", False):
            skipped_layers.append("project")
            skipped_layer_details.append({"layer": "project", "reason": "--skip-project"})
        # Auto-skip build/format when --files is specified: reviewing specific
        # files, not checking project-wide compilation. User can override by
        # NOT using --files (use --target instead) or by passing explicit flags.
        args_has_files = bool(getattr(args, "files", None))
        skip_build = getattr(args, "skip_build", False) or args_has_files
        skip_format = getattr(args, "skip_format", False) or args_has_files
        if skip_build:
            skipped_layers.append("build")
            skipped_layer_details.append(
                {
                    "layer": "build",
                    "reason": "--skip-build" if getattr(args, "skip_build", False) else "--files mode",
                }
            )
        if skip_format:
            skipped_layers.append("format")
            skipped_layer_details.append(
                {
                    "layer": "format",
                    "reason": "--skip-format" if getattr(args, "skip_format", False) else "--files mode",
                }
            )

    if sdk_present:
        executed_layers.add("ast")
        cache_dir = getattr(args, "cache", None) or None  # empty string → None
        ast_issues = analyze_ast(cs_files, project_root=project_root,
                                 cache_dir=cache_dir)
        all_issues.extend(ast_issues)
        layer_counts["ast"] += len(ast_issues)

    # ── Layer 4: Build diagnostics (optional, runs FIRST to produce DLLs) ──
    # NetAnalyzers (CAxxxx) injection is a build-layer enhancement, not a layer
    # of its own: skipped via `--skip-netanalyzers` but recorded under the build
    # layer's skipped_projects in `review_integrity.netanalyzers`.
    skip_netanalyzers = getattr(args, "skip_netanalyzers", False)
    na_injected = 0
    na_skipped: list[dict] = []
    if sdk_present and csproj_files and not skip_build:
        executed_layers.add("build")
        _na_results: list[dict] = []
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            fut_map = {
                pool.submit(
                    analyze_build, cp, project_root, framework_type, not skip_netanalyzers
                ): cp for cp in csproj_files
            }
            for future in concurrent.futures.as_completed(fut_map):
                build_issues, na_info = future.result()
                all_issues.extend(build_issues)
                layer_counts["build"] += len(build_issues)
                _na_results.append(na_info)
        for na_info in _na_results:
            if na_info.get("injected"):
                na_injected += 1
            elif na_info.get("skipped_reason"):
                na_skipped.append({
                    "csproj": na_info.get("csproj", "unknown"),
                    "reason": na_info["skipped_reason"],
                })
    elif sdk_present and not skip_build:
        skipped_layer_details.append({"layer": "build", "reason": "no .csproj/.sln found"})

    netanalyzers_summary = {
        "injected_for_projects": na_injected,
        "skipped_projects": na_skipped,
        "disabled_by_user": skip_netanalyzers,
        "build_failures": [s for s in na_skipped if "timed out" in s.get("reason", "") or "error" in s.get("reason", "").lower()],
    }

    # ── Collect build output DLLs for semantic analyzer ──
    _build_dlls: list[str] = []
    if sdk_present and csproj_files and not skip_build:
        for csproj in csproj_files:
            csproj_dir = Path(csproj).resolve().parent
            tfm = framework or "net6.0"
            # Prioritize Release over Debug when available (common in CI)
            for build_type in ["Release", "Debug"]:
                out_dir = csproj_dir / "bin" / build_type / tfm
                if out_dir.exists():
                    for dll in out_dir.glob("*.dll"):
                        dll_str = str(dll.resolve())
                        if dll_str not in _build_dlls:  # dedup across projects
                            _build_dlls.append(dll_str)
            # Also scan obj/ for NuGet reference DLLs (smaller than lib/, more reliable)
            obj_dir = csproj_dir / "obj" / "Debug" / tfm
            if not obj_dir.exists():
                obj_dir = csproj_dir / "obj" / "Release" / tfm
            if obj_dir.exists():
                # obj/{tfm}/project.assets.json is the single truth for all references
                assets_json = obj_dir / "project.assets.json"
                if assets_json.exists():
                    from .nuget import _extract_dlls_from_assets_json
                    obj_dlls = _extract_dlls_from_assets_json(str(assets_json))
                    for dll in obj_dlls:
                        if dll not in _build_dlls:
                            _build_dlls.append(dll)
        if _build_dlls:
            logger.info("Collected %d build output DLLs for semantic analysis", len(_build_dlls))

    # ── Layer 3b: Semantic Analysis (optional) ──
    # suppressed_by_ast counts AST false-positives the semantic layer proved
    # legal (out/ref null assignments). Initialized here because the semantic
    # block below can suppress in-loop; the value is reported in review_integrity.
    suppressed_by_ast = 0
    if sdk_present and not getattr(args, "skip_semantic", False):
        executed_layers.add("semantic")
        incremental = not getattr(args, "no_incremental_semantic", False)  # default True
        cache_dir = getattr(args, "semantic_cache_dir", None)
        if incremental and cache_dir is None:
            cache_dir = (
                str(Path(project_root) / ".review-cache" / "semantic")
                if project_root
                else None
            )
        # Use original file list (not expanded) to avoid Windows 32K cmdline limit.
        # Build output DLLs and NuGet references are still passed via --references.
        _sem_refs: list[str] = []
        if _build_dlls:
            _sem_refs.extend(_build_dlls)
        # Also try to resolve NuGet references from project csproj files
        for csproj in _csproj_for_files(cs_files):
            _sem_refs.extend(_nuget_references_for_csproj(csproj))

        # ── Solution-aware cross-project reference resolution ──
        # When --solution is set, collect NuGet refs from ALL solution projects.
        _sln_path = getattr(args, "solution", None)
        if _sln_path and csproj_files:
            # Resolve the actual .sln path
            _sln_resolved = str(Path(_sln_path).resolve()) if _sln_path != "full" else None
            if _sln_path == "full":
                # Auto-discover .sln from the first csproj
                for _cp in csproj_files:
                    _c = Path(_cp).resolve()
                    for _p in [_c] + list(_c.parents):
                        _slns = list(_p.glob("*.sln"))
                        if _slns:
                            _sln_resolved = str(_slns[0])
                            break
                    if _sln_resolved:
                        break
            if _sln_resolved and Path(_sln_resolved).exists():
                import re as _re
                _sln_dir = Path(_sln_resolved).resolve().parent
                _sln_csprojs: list[str] = []
                for _sl in Path(_sln_resolved).read_text(encoding="utf-8-sig").splitlines():
                    _m = _re.match(
                        r'Project\("\{([^}]+)\}"\)\s*=\s*"([^"]+)",\s*"([^"]+)",\s*"\{([^}]+)\}"',
                        _sl.strip(),
                    )
                    if _m and _m.group(3).endswith(".csproj"):
                        _p = str((_sln_dir / _m.group(3).replace("\\", "/")).resolve())
                        _sln_csprojs.append(_p)
                if _sln_csprojs:
                    # Collect NuGet refs from ALL solution projects
                    _sln_refs: list[str] = []
                    for _cp in _sln_csprojs:
                        _sln_refs.extend(_nuget_references_for_csproj(_cp))
                    # Deduplicate
                    _seen = set()
                    _deduped = []
                    for _r in _sln_refs:
                        if _r not in _seen:
                            _seen.add(_r)
                            _deduped.append(_r)
                    _sem_refs.extend(_deduped)
                    logger.info(
                        "Solution mode: collected %d NuGet DLL refs from %d projects",
                        len(_deduped), len(_sln_csprojs),
                    )
                    # For --solution full: expand cs_files to all solution .cs files
                    if _sln_path == "full":
                        _all_cs: list[str] = []
                        for _cp in _sln_csprojs:
                            _proj_dir = Path(_cp).resolve().parent
                            if _proj_dir.exists():
                                for _cs in _proj_dir.rglob("*.cs"):
                                    _all_cs.append(str(_cs.resolve()))
                        cs_files = _all_cs
                        logger.info(
                            "Solution full mode: expanded to %d source files from %d projects",
                            len(cs_files), len(_sln_csprojs),
                        )
        # Fallback: if no csproj found, try to locate popular NuGet DLLs from
        # the global package cache to enable at least basic platform-level analysis
        # (without csproj it's impossible to know the exact TFM, so we scan "lib/*")
        if not csproj_files:
            nuget_cache = _resolve_nuget_cache()
            if nuget_cache.exists():
                # Pick popular runtime DLLs that are likely to be in any project
                popular_pkgs = {
                    "newtonsoft.json": ["newtonsoft.json.dll"],
                    "microsoft.entityframeworkcore": ["microsoft.entityframeworkcore.dll"],
                    "system.text.json": ["system.text.json.dll"],
                }
                found = set()
                for pkg_lower, dll_names in popular_pkgs.items():
                    pkg_dir = nuget_cache / pkg_lower
                    if not pkg_dir.exists():
                        continue
                    for ver_dir in pkg_dir.iterdir():
                        if not ver_dir.is_dir() or not ver_dir.name.replace(".", "").isdigit():
                            continue
                        for tfm_dir in (ver_dir / "lib").iterdir():
                            if not tfm_dir.is_dir():
                                continue
                            for dll_name in dll_names:
                                cand = tfm_dir / dll_name
                                if cand.is_file() and str(cand.resolve()) not in found:
                                    found.add(str(cand.resolve()))
                                    _sem_refs.append(str(cand.resolve()))
                if _sem_refs:
                    logger.info(
                        "No .csproj detected, fallback loaded %d popular DLLs from NuGet cache for semantic analysis",
                        len([r for r in _sem_refs if "nuget" in r.lower()]),
                    )
        sem_issues, sem_extra = analyze_semantic(
            cs_files, incremental=incremental, cache_dir=cache_dir,
            project_root=project_root, references=_sem_refs,
            solution_path=getattr(args, "solution", None),
        )
        layer_counts["semantic"] += len(sem_issues)
        # Semantic diagnostics only enter the universal issue list here.
        # Earlier runs silently dropped them (only layer_counts was updated),
        # so SEM_* rules — including SEM_CANCELLATION_TOKEN and the new
        # SEM_OUTREF_NULL_SAFE exemption marker — never surfaced in reports.
        all_issues.extend(sem_issues)
        if isinstance(sem_extra, dict) and sem_extra.get("cache_stats"):
            semantic_cache_stats = sem_extra["cache_stats"]
        # Suppress AST false-positives already validated as legal by the
        # semantic layer (out/ref parameter null assignments).
        if sem_issues:
            _safe_lines: set[tuple[str, int]] = {
                (i.file, i.line)
                for i in sem_issues
                if i.rule == "SEM_OUTREF_NULL_SAFE" and i.file and i.line
            }
            if _safe_lines:
                before_suppress = len(ast_issues)
                ast_issues = [
                    i for i in ast_issues
                    if not (
                        i.rule == "LEGACY_null_assignment"
                        and (i.file, i.line) in _safe_lines
                    )
                ]
                suppressed_by_ast += before_suppress - len(ast_issues)

    # Semantic analysis status for output quality tracking.
    if "semantic" not in executed_layers:
        semantic_status = "skipped"
    elif isinstance(sem_extra, dict) and sem_extra.get("compilation_error_count", 0):
        semantic_status = "degraded"
    else:
        semantic_status = "ok"


    # ── Layer 3c: Project-level Cross-file Analysis (optional) ──
    if sdk_present and not getattr(args, "skip_project", False):
        executed_layers.add("project")
        project_analysis = analyze_project(cs_files)
        layer_counts["project"] = 1
        project_issues = _project_findings_to_issues(project_analysis)
        if project_issues:
            all_issues.extend(project_issues)
            layer_counts["project"] += len(project_issues)

    # Layer 5: dotnet format (SDK style only)
    if sdk_present and csproj_files and not skip_format:
        executed_layers.add("format")
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            fut_map = {
                pool.submit(analyze_format, cp, project_root): cp for cp in csproj_files
            }
            for future in concurrent.futures.as_completed(fut_map):
                format_issues = future.result()
                all_issues.extend(format_issues)
                layer_counts["format"] += len(format_issues)
    elif sdk_present and not skip_format:
        skipped_layer_details.append({"layer": "format", "reason": "no .csproj/.sln found"})

    # Layer 5b: csproj / config audit
    if csproj_files:
        from .csproj_audit import audit_csproj, audit_production_config
        for csproj in csproj_files:
            csproj_issues = audit_csproj(csproj, project_root)
            all_issues.extend(csproj_issues)
            layer_counts["csproj"] = layer_counts.get("csproj", 0) + len(csproj_issues)
        # Also audit production config files
        config_issues = audit_production_config(project_root, cs_files)
        all_issues.extend(config_issues)
        layer_counts["config"] = len(config_issues)

    if project_type == "test":
        before_relaxed = all_issues
        all_issues = [i for i in all_issues if i.rule not in TEST_PROJECT_RELAXED_RULES]
        relaxed_suppression_count = len(before_relaxed) - len(all_issues)
    else:
        relaxed_suppression_count = 0

    # ── Windows-only API filter ──
    # Suppress WIN rules when the target framework is itself Windows-only:
    #   - .NET Framework (legacy) — always Windows-only
    #   - modern TFM with -windows suffix (e.g. net8.0-windows)
    # In these targets, Windows-only APIs are expected and legitimate.
    # Cross-platform targets (net8.0, netstandard2.0, etc.) keep the rules.
    win_suppressed_count = 0
    if WIN_ONLY_API_RULES:
        _is_windows_target = (
            framework_type == "legacy"
            or "-windows" in framework.lower()
        )
        if _is_windows_target:
            before_win = len(all_issues)
            all_issues = [i for i in all_issues if i.rule not in WIN_ONLY_API_RULES]
            win_suppressed_count = before_win - len(all_issues)

    # ── Dedup & Score ──
    all_issues = dedup_issues(all_issues)

    # ── Suppressions (.dotnet-review/suppress.json) ──
    # Applied after dedup so a suppressed issue is fully removed from score and
    # output. Suppression text is data only — never executed (see
    # load_suppressions docstring).
    suppressions = load_suppressions(project_root)
    suppressed_count = 0
    if suppressions:
        all_issues, suppressed_count = apply_suppressions(
            all_issues, suppressions, project_root
        )

    # -- Agent Verdicts (.dotnet-review/agent-verdicts.json) --
    from .agent_verdicts import load_verdicts, apply_verdicts
    agent_verdicts = load_verdicts(project_root)
    verdict_suppressed_count = 0
    if agent_verdicts:
        all_issues, verdict_suppressed_count = apply_verdicts(
            all_issues, agent_verdicts
        )
        if verdict_suppressed_count:
            logger.info('Agent verdicts suppressed %d issues', verdict_suppressed_count)

    # -- Context Bundles for agent_verify issues --
    from .rules import get_triage_for_rule
    from .context_bundle import build_context_bundles
    _include_bundles = getattr(args, 'context_bundles', False)
    if _include_bundles:
        _verify_issues = [
            i for i in all_issues
            if get_triage_for_rule(i.rule) == 'agent_verify' and i.line > 0
        ]
        _bundles = build_context_bundles(_verify_issues, project_root)
        for issue in all_issues:
            key = (issue.file, issue.line)
            if key in _bundles:
                issue._context_bundle = _bundles[key]

    # ── Changed-only filter (for PR review) ──
    changed_lines = {}
    changed_only = getattr(args, "changed_only", False)
    if changed_only:
        base_ref = getattr(args, "diff", "HEAD") or "HEAD"
        try:
            changed_lines = get_changed_line_ranges(base_ref, project_root)
        except Exception:
            changed_lines = {}
        if changed_lines:
            # Build a path-normalized lookup so issues whose `file` is an
            # absolute path, a project-root-relative path, or a git-relative
            # path can all match. Keys are POSIX-style normalized basenames+paths.
            norm_changed: dict[str, set[int]] = {}
            for fpath, lns in changed_lines.items():
                key = _normalize_review_path(fpath, project_root)
                norm_changed[key] = norm_changed.get(key, set()) | lns

            before_count = len(all_issues)
            kept = []
            for issue in all_issues:
                key = _normalize_review_path(issue.file, project_root)
                lines = norm_changed.get(key)
                if lines is None:
                    continue
                # line==0 issues (file/project-level: nuget, format, etc.) are
                # not tied to a specific line — keep them if their file changed.
                if issue.line == 0 or issue.line in lines:
                    kept.append(issue)
            all_issues = kept
            logger.info(
                f"Changed-only filter: {before_count} → {len(all_issues)} issues"
            )

    # ── Deduplicate across layers (AST + Format + Build + custom) ──
    # Different layers may report the same issue with different location precision:
    # AST uses line; IDE format uses char; Build uses CSxx. We dedup by
    # (file, line, rule, message_norm) fingerprint to collapse duplicates, keeping
    # the first-seen entry (most specific/complete).
    def _fingerprint(issue: CodeIssue) -> tuple[str, int, str, str]:
        # Normalize message: remove absolute paths and line numbers to align
        # slight variations (e.g., "Program.cs(123,45):" vs "(123,45):").
        import re
        # Keep only the base message text
        msg_norm = issue.message.lower().strip()
        # Remove trailing absolute/relative path patterns
        msg_norm = re.sub(r"\([^)]*\.cs\:.*?\):?", "", msg_norm)  # (X,Y): CODE
        msg_norm = re.sub(r"\s+\(?\d+,.*?\)", "", msg_norm)     # loose (line,col)
        msg_norm = re.sub(r"\s+\(?\d+.*?\)", "", msg_norm)     # fallback (line)
        msg_norm = re.sub(r"[^a-zA-Z0-9\\u4e00-\\u9fff]", "", msg_norm)         # non-alphanum / Chinese
        msg_norm = msg_norm[:60]  # cap to reduce collision risk
        return (issue.file, issue.line, issue.rule, msg_norm)

    seen_fingerprints = set()
    deduped = []
    for issue in all_issues:
        key = _fingerprint(issue)
        if key in seen_fingerprints:
            continue
        seen_fingerprints.add(key)
        deduped.append(issue)
    if len(deduped) != len(all_issues):
        logger.info("Deduplicated issues: %d → %d", len(all_issues), len(deduped))
    all_issues = deduped

    score = calculate_score(all_issues)
    by_severity = count_by_severity(all_issues)

    # ── Baseline diff (PR diff-aware comparison) ──
    # When --baseline-report is provided, classify issues as introduced/fixed/
    # unchanged against the baseline JSON. Runs after suppressions + changed-
    # only filter so suppressed issues are invisible in both sides (consistent
    # with "suppress = treat as nonexistent"). See diff_baseline.py docstring.
    diff_baseline_result = None
    introduced_score = None
    baseline_report_path = getattr(args, "baseline_report", None)
    if baseline_report_path:
        from .diff_baseline import compute_diff, load_baseline
        baseline_issues = load_baseline(baseline_report_path)
        if baseline_issues is None:
            logger.warning(
                "Baseline report '%s' could not be loaded — diff comparison skipped.",
                baseline_report_path,
            )
            diff_baseline_result = {"error": "baseline_load_failed",
                                    "baseline_report": baseline_report_path}
        else:
            diff_baseline_result = compute_diff(
                all_issues, baseline_issues, project_root,
            )
            # Introduced-only score: net impact of issues this PR introduced.
            introduced_issues = [
                CodeIssue(
                    file=i["file"], line=i.get("line", 0),
                    severity=i.get("severity", "info"),
                    category=i.get("category", ""),
                    rule=i["rule"], source=i.get("source", ""),
                )
                for i in diff_baseline_result["introduced"]
            ]
            introduced_score = calculate_score(introduced_issues)

    elapsed = round(time.time() - start_time, 2)

    # Project-level Roslyn metrics from analyze_project (if available, else None).
    mi_score = project_analysis.get("maintainability_index")
    total_cognitive = project_analysis.get("cognitive_complexity")

    # Fallback: compute cognitive complexity and MI from Python when the C#
    # project analyzer doesn't emit them (ProjectAnalysisResult class has no
    # maintainability_index or cognitive_complexity fields).
    if mi_score is None or total_cognitive is None:
        if file_codes:
            # Cognitive complexity: sum across all files, catching import errors
            # in case the complexity module is unavailable.
            if total_cognitive is None:
                try:
                    from .complexity import calculate_cognitive_complexity
                    total_cognitive = sum(
                        calculate_cognitive_complexity(fp, code)
                        for fp, code in file_codes.items()
                    )
                except Exception:
                    total_cognitive = None

            # Maintainability Index: Microsoft variant
            #   MI = max(0, min(100, (171 - 5.2·ln(V) - 0.23·CC - 16.2·ln(LOC)) × 100 / 171))
            # where V≈LOC (Halstead Volume approximation), CC = average cyclomatic complexity.
            if mi_score is None:
                try:
                    import math
                    all_methods: list[dict] = []
                    total_loc = 0
                    for fp, code in file_codes.items():
                        lines = code.split("\n")
                        total_loc += len(lines)
                        all_methods.extend(_extract_methods(lines))
                    method_count = max(len(all_methods), 1)
                    avg_cc = sum(m["complexity"] for m in all_methods) / method_count
                    V = total_loc  # Halstead Volume ≈ LOC
                    mi_raw = 171 - 5.2 * math.log(max(V, 1)) - 0.23 * avg_cc - 16.2 * math.log(max(total_loc, 1))
                    mi_score = round(max(0, min(100, mi_raw * 100 / 171)), 1)
                except Exception:
                    mi_score = None

    # ── Technical Debt ──
    debt_minutes = estimate_technical_debt(all_issues)

    # ── Auto-fix ──
    fix_result = {"fixed": [], "skipped": [], "files_modified": []}
    if getattr(args, "fix", False) or getattr(args, "fix_dry_run", False):
        if getattr(args, "fix_dry_run", False):
            # Dry run: just count what would change.
            # Resolve AST/semantic aliases so authoritative findings from the
            # Roslyn layer attach to their deterministic builtin fix.
            from .auto_fix import _resolve_fix_rule_id

            for issue in all_issues:
                fix_rule_id = _resolve_fix_rule_id(issue.rule)
                fixes = AUTO_FIXES.get(fix_rule_id, [])
                if fixes:
                    fix_result["skipped"].append(
                        {
                            "rule": issue.rule,
                            "file": issue.file,
                            "reason": "dry_run",
                            "would_fix": fixes[0]["description"],
                        }
                    )
        else:
            fix_result = apply_all_auto_fixes(all_issues, create_backup=True)

    # ── CVE Check ──
    cve_result = {"vulnerabilities": [], "scanned": 0}
    if getattr(args, "cve_check", False):
        executed_layers.add("cve")
        cve_db_path = getattr(args, "cve_db", None)
        # --ensure-cve-db: download DB on demand if missing (network required).
        if getattr(args, "ensure_cve_db", False):
            from .nuget import ensure_cve_db

            ensured = ensure_cve_db(cve_db_path)
            if ensured.get("error"):
                logger.warning("ensure_cve_db failed: %s", ensured["error"])
            elif ensured.get("ensured"):
                logger.info(
                    "ensure_cve_db: downloaded %s records", ensured.get("updated", 0)
                )
        else:
            # Auto-refresh stale CVE DB (warn at 3d, refresh at 7d) so scan results stay current.
            from .nuget import _db_age_days, CVE_DB_AUTO_REFRESH_DAYS, CVE_DB_WARN_DAYS, _get_cve_db_path, ensure_cve_db, _load_cve_db_meta

            resolved_path = _get_cve_db_path(cve_db_path)
            if resolved_path:
                age = _db_age_days(
                    _load_cve_db_meta(resolved_path).get("updated_at", "")
                )
                if age is not None:
                    if age > CVE_DB_AUTO_REFRESH_DAYS:
                        logger.warning(
                            "CVE DB is %d days old (auto-refresh threshold %d) — auto-refreshing",
                            age, CVE_DB_AUTO_REFRESH_DAYS,
                        )
                        refreshed = ensure_cve_db(cve_db_path)
                        if refreshed.get("ensured"):
                            logger.info(
                                "auto-refresh: downloaded %d records",
                                refreshed.get("updated", 0),
                            )
                    elif age > CVE_DB_WARN_DAYS:
                        logger.warning(
                            "CVE DB is %d days old (warn threshold %d) — use --ensure-cve-db to update",
                            age, CVE_DB_WARN_DAYS,
                        )
        cve_result = check_nuget_cves(nuget_packages, cve_db_path)

    # ── Report History ──
    history_summary = {}
    history_dir = getattr(args, "history_dir", None)
    if history_dir:
        history_summary = save_report_history(
            history_dir,
            {
                "files_scanned": len(cs_files),
                "total_issues": len(all_issues),
                "by_severity": by_severity,
                "score": score,
                "cognitive_complexity": total_cognitive,
                "technical_debt_minutes": debt_minutes,
            },
            cs_files,
            all_issues,
        )
        # Compute trend if we have history
        trend = compute_trend(history_dir)
        history_summary["trend"] = trend

    # ── API Compatibility ──
    api_compat = {"added": [], "removed": [], "changed": [], "breaking": []}
    if getattr(args, "api_compat", False):
        base_ref = getattr(args, "diff", "HEAD") or "HEAD"
        try:
            api_compat = check_api_compatibility(project_root, base_ref, nuget_packages)
        except Exception as e:
            api_compat = {
                "error": str(e),
                "added": [],
                "removed": [],
                "changed": [],
                "breaking": [],
            }

    args_has_files = bool(getattr(args, "files", None))
    requested_layers = {
        "style",
        "perf_hint",
        "ast",
    }
    if custom_rules:
        requested_layers.add("custom")
    if not getattr(args, "no_duplicates", False):
        requested_layers.add("duplicate")
    if coverage_path:
        requested_layers.add("coverage")
    if not getattr(args, "no_docs", False):
        requested_layers.add("doc")
    if nuget_packages:
        requested_layers.add("nuget")
    if not getattr(args, "skip_semantic", False):
        requested_layers.add("semantic")
    if not getattr(args, "skip_project", False):
        requested_layers.add("project")
    if not getattr(args, "skip_build", False) and not args_has_files:
        requested_layers.add("build")
    if not getattr(args, "skip_format", False) and not args_has_files:
        requested_layers.add("format")
    if getattr(args, "cve_check", False):
        requested_layers.add("cve")

    # Deduplicate while preserving first-seen reasons.
    seen_skipped: set[str] = set()
    skipped_layer_details = [
        detail
        for detail in skipped_layer_details
        if not (detail["layer"] in seen_skipped or seen_skipped.add(detail["layer"]))
    ]
    # Add semantic analysis compilation error count to review_integrity
    sem_comp_errs = 0
    if isinstance(sem_extra, dict):
        sem_comp_errs = sem_extra.get("compilation_error_count", 0)
    review_integrity = build_review_integrity(
        sdk_present=sdk_present,
        sdk_version=get_dotnet_sdk_version() if sdk_present else None,
        requested_layers=requested_layers,
        executed_layers=executed_layers,
        skipped_layer_details=skipped_layer_details,
        cve_result=cve_result,
        cve_requested=bool(getattr(args, "cve_check", False)),
        coverage_data=coverage_data,
        coverage_requested=bool(coverage_path),
        netanalyzers_summary=netanalyzers_summary,
    )
    if sem_comp_errs:
        review_integrity["semantic_compilation_errors"] = sem_comp_errs
        review_integrity["semantic_degraded"] = True
        # List the specific rule families that are degraded so the Agent knows
        # exactly which findings may be false negatives.
        from .evidence import TYPE_DEPENDENT_RULE_PREFIXES
        review_integrity["degraded_rule_families"] = list(TYPE_DEPENDENT_RULE_PREFIXES)

    # ── Degradation Notices (human-readable, for Agent Findings/Summary) ──
    from .evidence import build_degradation_notices
    degradation_notices = build_degradation_notices(
        skipped_layer_details=skipped_layer_details,
        sem_comp_errs=sem_comp_errs,
    )

    # -- Triage Summary --
    from .rules import get_triage_for_rule
    _triage_counts = {"deterministic": 0, "agent_verify": 0, "agent_only": 0}
    for _i in all_issues:
        _t = get_triage_for_rule(_i.rule)
        _triage_counts[_t] = _triage_counts.get(_t, 0) + 1
    triage_summary = {
        "deterministic": _triage_counts["deterministic"],
        "agent_verify": _triage_counts["agent_verify"],
        "agent_only": _triage_counts["agent_only"],
        "total": sum(_triage_counts.values()),
    }

    return {
        "project_root": project_root,
        "framework_version": framework,
        "framework_type": framework_type,
        "frameworks": frameworks,
        "project_type": project_type,
        "nuget_packages": nuget_packages,
        "metadata": project_metadata,
        "semantic_status": semantic_status,
        "files_scanned": len(cs_files),
        "total_issues": len(all_issues),
        "score": score,
        "by_severity": by_severity,
        "maintainability_index": mi_score,
        "cognitive_complexity": total_cognitive,
        "technical_debt_minutes": debt_minutes,
        "test_available": test_available,
        "coverage_summary": coverage_data.get("summary", {}) if coverage_data else {},
        "fix_result": fix_result,
        "cve_check": cve_result,
        "history_summary": history_summary,
        "api_compatibility": api_compat,
        "diff_baseline": diff_baseline_result,
        "introduced_score": introduced_score,
        "changed_lines": {f: sorted(ls) for f, ls in changed_lines.items()}
        if changed_lines
        else {},
        "issues": [
            serialize_issue(i)
            for i in sorted(
                all_issues,
                key=lambda x: (
                    {"error": 0, "warning": 1, "info": 2}.get(x.severity, 3),
                    x.file,
                    x.line,
                ),
            )
        ],
        "layers": layer_counts,
        "skipped_layers": skipped_layers,
        "skipped_layer_details": skipped_layer_details,
        "review_integrity": review_integrity,
        "degradation_notices": degradation_notices,
        "sdk_present": sdk_present,
        "suppressed_by_ast": suppressed_by_ast,
        "suppressed_by_config": suppressed_count,
        "suppressed_by_verdict": verdict_suppressed_count,
        "relaxed_suppression_count": relaxed_suppression_count,
        "win_suppressed_count": win_suppressed_count,
        "project_analysis": project_analysis,
        "semantic_cache_stats": semantic_cache_stats,
        "filtered_rules": [],
        "analysis_time": elapsed,
        "triage_summary": triage_summary,
    }

# ============================================================
# Semantic Analysis Helpers: NuGet reference resolution + file expansion
# ============================================================


def _resolve_nuget_cache() -> Path:
    """Locate the NuGet global packages folder.

    Priority:
    1. ``NUGET_PACKAGES`` environment variable (standard .NET convention)
    2. ``D:/NugetPackages`` (this workstation's custom location)
    3. ``~/.nuget/packages`` (default)

    Returns the first path that exists, or the default as fallback.
    """
    env = os.environ.get("NUGET_PACKAGES")
    if env:
        p = Path(env)
        if p.exists():
            return p
    for candidate in [Path("D:/NugetPackages"), Path.home() / ".nuget" / "packages"]:
        if candidate.exists():
            return candidate
    return Path.home() / ".nuget" / "packages"

def _nuget_references_for_csproj(csproj_path: str) -> list[str]:
    """Resolve NuGet package DLL paths from a .csproj file.

    Reads ``PackageReference`` entries from the csproj and resolves them
    from the global NuGet cache (``D:/NugetPackages``). Returns existing
    DLL paths for the nearest target framework.
    """
    refs: list[str] = []
    try:
        content = Path(csproj_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return refs

    nuget_cache = _resolve_nuget_cache()
    if not nuget_cache.exists():
        return refs

    # Determine target framework from the csproj or Directory.Build.props
    tfm = ""
    m = re.search(r"<TargetFramework>([^<]+)</TargetFramework>", content)
    if m:
        tfm = m.group(1).strip()
    else:
        for parent in Path(csproj_path).resolve().parent.parents:
            dbp = parent / "Directory.Build.props"
            if dbp.exists():
                try:
                    dbp_content = dbp.read_text(encoding="utf-8", errors="ignore")
                    m2 = re.search(r"<TargetFramework>([^<]+)</TargetFramework>", dbp_content)
                    if m2:
                        tfm = m2.group(1).strip()
                        break
                except OSError:
                    continue

    tfm_candidates = [tfm] if tfm else []
    if tfm.startswith("net"):
        major = tfm.replace("net", "").split(".")[0]
        tfm_candidates += [f"net{major}", "netstandard2.0", "netstandard2.1", "net48", "net472"]

    for m in re.finditer(
        r'<PackageReference\s+Include="([^"]+)"\s+Version="([^"]+)"',
        content,
    ):
        pkg_name = m.group(1).lower()
        pkg_ver = m.group(2)
        pkg_dir = nuget_cache / pkg_name / pkg_ver
        if not pkg_dir.exists():
            continue
        found = False
        for candidate_tfm in tfm_candidates:
            lib_dir = pkg_dir / "lib" / candidate_tfm
            if lib_dir.exists():
                for dll_candidate in [
                    lib_dir / f"{m.group(1)}.dll",
                    lib_dir / f"{pkg_name}.dll",
                ]:
                    if dll_candidate.exists():
                        refs.append(str(dll_candidate.resolve()))
                        found = True
                        break
                if found:
                    break
        if not found:
            for lib_sub in pkg_dir.glob("lib/*/*.dll"):
                refs.append(str(lib_sub.resolve()))
                break

    return refs


def _expand_files_for_semantic_analysis(
    cs_files: list[str], project_root: str,
) -> tuple[list[str], list[str]]:
    """Expand a file list and collect NuGet references for semantic analysis.

    For each file in ``cs_files``, finds the owning csproj, discovers all
    .cs files in that csproj's directory tree, and resolves NuGet package
    DLLs. Returns ``(all_project_files, nuget_references)``.
    """
    all_files: list[str] = []
    seen: set[str] = set()
    all_refs: list[str] = []
    ref_seen: set[str] = set()

    for csproj in _csproj_for_files(cs_files):
        csproj_dir = Path(csproj).resolve().parent
        for f in csproj_dir.rglob("*.cs"):
            rel = f.relative_to(csproj_dir)
            if any(p.startswith(".") or p in ("obj", "bin") for p in rel.parts):
                continue
            fp = str(f.resolve())
            if fp not in seen:
                seen.add(fp)
                all_files.append(fp)
        for r in _nuget_references_for_csproj(csproj):
            if r not in ref_seen:
                ref_seen.add(r)
                all_refs.append(r)

    if not all_files:
        all_files = [str(Path(f).resolve()) for f in cs_files]

    return all_files, all_refs
