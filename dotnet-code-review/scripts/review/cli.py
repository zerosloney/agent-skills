from __future__ import annotations
import argparse
import json
import logging
import sys
from .engine import run_review
from .errors import (
    ReviewError,
    UserInputError,
    EXIT_OK,
    EXIT_ERROR,
    EXIT_WARNING,
    EXIT_INTERNAL,
    EXIT_INVALID_INPUT,
)
from .output import (
    format_json,
    format_markdown,
    format_json_compact,
    format_sarif,
    DEFAULT_MAX_MESSAGE_LENGTH,
    DEFAULT_MAX_ISSUES,
    apply_output_mode,
)

logger = logging.getLogger("dotnet-review")


# ============================================================
# CLI
# ============================================================


def main():
    parser = argparse.ArgumentParser(
        prog="dotnet-review",
        description="C# Code Review — Standalone CLI",
    )
    parser.add_argument("--target", "-t",
        help="Target directory or file. Auto-detects scope: runs git diff HEAD "
             "first, falls back to full directory scan when no changes found.")
    parser.add_argument("--diff", "-d", help="Git diff base ref (e.g., HEAD)")
    parser.add_argument("--files", "-f", nargs="+", help="Specific .cs files to review")
    parser.add_argument("--all", "-a", help="Scan entire directory")
    parser.add_argument(
        "--format",
        choices=["json", "markdown", "compact", "sarif"],
        default="json",
        help="Output format (compact = minimal token usage; sarif = SARIF 2.1.0 for GitHub/Azure DevOps Code Scanning)",
    )
    parser.add_argument(
        "--output-mode",
        choices=["default", "summary", "by-rule", "top"],
        default="default",
        help="Output mode (default/full, summary/by-rule/top=token-efficient)",
    )
    parser.add_argument(
        "--max-issues",
        type=int,
        default=DEFAULT_MAX_ISSUES,
        help=f"Max issues in output (default: {DEFAULT_MAX_ISSUES})",
    )
    parser.add_argument(
        "--max-message-length",
        type=int,
        default=DEFAULT_MAX_MESSAGE_LENGTH,
        help=f"Max message length (default: {DEFAULT_MAX_MESSAGE_LENGTH})",
    )
    parser.add_argument(
        "--fail-on",
        choices=["error", "warning", "info", "none"],
        default="error",
        help="Exit non-zero on this severity or higher",
    )
    parser.add_argument("--preview", action="store_true", help="Preview files only")
    parser.add_argument(
        "--quiet", "-q", action="store_true", help="Suppress progress output"
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")
    parser.add_argument(
        "--no-duplicates", action="store_true", help="Disable duplicate code detection"
    )
    parser.add_argument("--no-docs", action="store_true", help="Disable XML doc check")
    parser.add_argument(
        "--no-nuget-check", action="store_true", help="Disable NuGet version check"
    )
    parser.add_argument(
        "--quality-gate-score",
        type=float,
        default=None,
        help="Minimum overall score to pass (0-100). Exit 1 if score below threshold.",
    )
    parser.add_argument(
        "--skip-semantic", action="store_true", help="Skip semantic analysis (Layer 3b)"
    )
    parser.add_argument(
        "--skip-project",
        action="store_true",
        help="Skip project-level cross-file analysis (Layer 3c)",
    )
    parser.add_argument(
        "--context-bundles",
        action="store_true",
        help="Attach code context snippets to agent_verify issues (increases output size)",
    )
    parser.add_argument(
        "--skip-build",
        action="store_true",
        help="Skip MSBuild compilation diagnostics (Layer 4). "
        "Automatically enabled when --files is specified.",
    )
    parser.add_argument(
        "--skip-format",
        action="store_true",
        help="Skip dotnet format code-style diagnostics (Layer 5). "
        "Automatically enabled when --files is specified.",
    )
    parser.add_argument(
        "--skip-netanalyzers",
        action="store_true",
        help="Skip injecting Microsoft .NET analyzers (CAxxxx) into the build layer. "
        "By default the build layer injects NetAnalyzers (AnalysisLevel=latest-recommended) "
        "for modern .NET (net6.0+) projects to surface the official CAxxxx rule set; "
        "use this flag to disable. No effect on legacy (.NET Framework) projects.",
    )
    parser.add_argument(
        "--no-incremental-semantic",
        action="store_true",
        default=False,
        help="Disable incremental compilation for semantic analysis (Layer 3b). "
        "Enabled by default; use this flag to disable caching when files change between runs.",
    )
    parser.add_argument(
        "--semantic-cache-dir",
        metavar="DIR",
        help="Directory for semantic analysis cache (used with --incremental-semantic). "
        "Default: <project>/.review-cache/semantic",
    )
    parser.add_argument(
        "--coverage",
        metavar="PATH",
        help="Cobertura XML coverage report path (e.g., coverage.cobertura.xml from coverlet)",
    )
    parser.add_argument(
        "--coverage-threshold",
        type=float,
        default=0.6,
        metavar="RATIO",
        help="Minimum line coverage ratio (0-1). Default: 0.6 (60%%)",
    )
    parser.add_argument(
        "--changed-only",
        action="store_true",
        help="Only report issues on lines that were changed (requires --diff)",
    )
    parser.add_argument(
        "--cache",
        metavar="DIR",
        help="Cache directory for incremental analysis results",
    )
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Apply auto-fixes for fixable rules (creates .bak backups)",
    )
    parser.add_argument(
        "--fix-dry-run",
        action="store_true",
        help="Show what --fix would change without modifying files",
    )
    parser.add_argument(
        "--cve-check",
        action="store_true",
        help="Check NuGet packages against known CVE database (offline)",
    )
    parser.add_argument(
        "--cve-db",
        metavar="PATH",
        help="Path to local CVE database (JSON). Default: bundled cache.",
    )
    parser.add_argument(
        "--ensure-cve-db",
        action="store_true",
        help="When --cve-check is set and no CVE DB is present, "
        "download it from OSV.dev before scanning (requires network). "
        "Without this flag, a missing DB yields db_present=false + warning.",
    )
    parser.add_argument(
        "--history-dir",
        metavar="DIR",
        help="Directory for report history (enables trend tracking)",
    )
    parser.add_argument(
        "--api-compat",
        action="store_true",
        help="Check public API compatibility (requires --diff)",
    )
    parser.add_argument(
        "--baseline-report",
        metavar="PATH",
        help="Path to a baseline review.py JSON report. When set, classifies "
        "issues as introduced/fixed/unchanged against the baseline (PR "
        "diff-aware mode). Use with --output on the baseline branch first.",
    )
    parser.add_argument(
        "--fail-on-introduced",
        choices=["error", "warning", "none"],
        default="none",
        help="Exit non-zero only if the diff introduced issues at this severity "
        "or higher (requires --baseline-report). Independent of --fail-on: "
        "use both for layered gating. 'none' (default) disables this gate.",
    )
    parser.add_argument(
        "--target-framework",
        metavar="FRAMEWORK",
        help="Override target framework detection "
        "(e.g., net8.0, net48, netframework-v4.8). "
        "Use when no .csproj is found or to override auto-detection.",
    )
    parser.add_argument(
        "--checklist",
        action="store_true",
        help="Print the human-review checklist for dimensions the "
        "tool has no static detection capability for "
        "(observability, deployment/ops, log redaction, "
        "transport/session config). Read-only; runs no scan.",
    )
    parser.add_argument(
        "--solution", "-s",
        metavar="PATH",
        help="Path to .sln file. Enables solution-aware semantic analysis: "
        "resolves cross-project type references using dependency project DLLs. "
        "Pass 'full' to auto-discover and include ALL source files from the solution.",
    )

    args = parser.parse_args()

    # ── --checklist: print the human-review checklist and exit (no scan) ──
    if args.checklist:
        from .output import format_human_review_checklist

        print(format_human_review_checklist())
        sys.exit(EXIT_OK)

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG, format="%(name)s: %(message)s")
    elif args.quiet:
        logging.basicConfig(level=logging.ERROR, format="%(name)s: %(message)s")
    else:
        logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")

    # ── Run review with error handling ──
    try:
        result = run_review(args)
    except UserInputError as e:
        print(json.dumps(e.to_dict(), indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(e.exit_code)
    except ReviewError as e:
        print(json.dumps(e.to_dict(), indent=2, ensure_ascii=False), file=sys.stderr)
        sys.exit(e.exit_code)
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "error": "Interrupted by user",
                    "code": "INTERRUPTED",
                    "exit_code": 130,
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        sys.exit(130)
    except ValueError as e:
        print(f"Invalid input: {e}", file=sys.stderr)
        sys.exit(EXIT_INVALID_INPUT)
    except Exception as e:
        logger.exception("Unexpected error")
        print(
            json.dumps(
                {
                    "error": f"Unexpected error: {e}",
                    "code": "INTERNAL_ERROR",
                    "exit_code": EXIT_INTERNAL,
                    "type": type(e).__name__,
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        sys.exit(EXIT_INTERNAL)

    # ── Apply output mode (token efficiency) ──
    result = apply_output_mode(result, args)

    # ── Output ──
    if args.format == "markdown":
        print(format_markdown(result))
    elif args.format == "compact":
        print(format_json_compact(result))
    elif args.format == "sarif":
        print(format_sarif(result))
    else:
        print(format_json(result))

    # ── Exit code ──
    sys.exit(_calculate_exit_code(result, args))


def _calculate_exit_code(result: dict, args) -> int:
    """Calculate exit code based on --fail-on, --quality-gate-score, and
    --fail-on-introduced (PR baseline diff gate).

    Exit codes from the three gates are combined by taking the most severe:
    --fail-on (full-issue gate) and --fail-on-introduced (PR-introduced gate)
    are independent — both must pass for EXIT_OK. This means an existing
    --fail-on=error failure is NOT waived just because the issues pre-existed;
    use --fail-on=none to gate ONLY on introduced issues.
    """
    fail_on = getattr(args, "fail_on", "error")

    # ── Quality Gate Score Check ──
    quality_gate = getattr(args, "quality_gate_score", None)
    if quality_gate is not None:
        actual_score = result.get("score", {}).get("overall", 0)
        if actual_score < quality_gate:
            return EXIT_ERROR

    # Compute the --fail-on gate result first (may be overridden below if a
    # stricter gate fires).
    fail_on_result = EXIT_OK
    if fail_on != "none":
        sev_order = {"error": 3, "warning": 2, "info": 1}
        threshold = sev_order.get(fail_on, 3)
        by_sev = result.get("by_severity", {})
        for sev, count in by_sev.items():
            if sev_order.get(sev, 0) >= threshold and count > 0:
                if sev == "error":
                    fail_on_result = EXIT_ERROR
                elif sev == "warning":
                    fail_on_result = EXIT_WARNING
                break

    # ── Introduced-issue gate (--fail-on-introduced) ──
    # Independent of --fail-on: only counts issues NEW to this PR (vs baseline).
    # Result is combined with fail_on_result by taking the more severe.
    fail_on_introduced = getattr(args, "fail_on_introduced", "none")
    introduced_result = EXIT_OK
    if fail_on_introduced != "none":
        diff = result.get("diff_baseline")
        if isinstance(diff, dict) and "introduced" in diff:
            sev_rank = {"error": 3, "warning": 2, "info": 1}
            threshold = sev_rank.get(fail_on_introduced, 3)
            for issue in diff["introduced"]:
                sev = issue.get("severity", "info")
                if sev_rank.get(sev, 0) >= threshold:
                    if sev == "error":
                        introduced_result = EXIT_ERROR
                    elif sev == "warning":
                        introduced_result = EXIT_WARNING
                    break

    # Combine: return the more severe of the two gates.
    rank = {EXIT_OK: 0, EXIT_WARNING: 1, EXIT_ERROR: 2}
    return fail_on_result if rank.get(fail_on_result, 0) >= rank.get(introduced_result, 0) else introduced_result
