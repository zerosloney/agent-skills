#!/usr/bin/env python3
# ruff: noqa: E402
"""
frontend-audit — JS/TS + React frontend code review CLI.

Agent entry: subprocess ``python scripts/audit.py <subcommand> ...``.
Users never call this directly.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

_PKG_DIR = Path(__file__).resolve().parent
if str(_PKG_DIR) not in sys.path:
    sys.path.insert(0, str(_PKG_DIR))

from audit.engine import run_scan  # noqa: E402
from audit.errors import AuditError, EXIT_OK, EXIT_ERROR, EXIT_CONFIG_ERROR  # noqa: E402
from audit.output import (  # noqa: E402
    format_json,
    format_json_compact,
    format_markdown,
    format_sarif,
)
from audit.rules import all_rules  # noqa: E402

logger = logging.getLogger("frontend-audit")

DIMENSIONS = ["security", "reliability", "best-practice", "arch", "deps"]


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="frontend-audit",
        description="JS/TS + React frontend code review CLI.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_scan = sub.add_parser("scan", help="Run a full audit on a directory.")
    p_scan.add_argument("--path", "-p", required=True, help="Target project directory.")
    p_scan.add_argument(
        "--dimensions",
        "-d",
        nargs="+",
        choices=DIMENSIONS,
        default=None,
        help=f"Subset of dimensions (default: all). Choices: {DIMENSIONS}",
    )
    p_scan.add_argument(
        "--format",
        "-f",
        choices=["json-compact", "json", "sarif", "markdown"],
        default="json-compact",
        help="Output format (json-compact = minimal tokens, the Agent default).",
    )
    p_scan.add_argument("--no-lint", action="store_true", help="Skip eslint/tsc tiers.")
    p_scan.add_argument("--no-deps", action="store_true", help="Skip npm audit tier.")
    p_scan.add_argument(
        "--include-lint",
        action="store_true",
        help="Include every eslint finding instead of a summary (raises token usage).",
    )
    p_scan.add_argument(
        "--threshold",
        choices=["A", "B", "C", "D", "F"],
        help="Quality gate: exit non-zero if grade is below this.",
    )
    p_scan.add_argument("--quiet", "-q", action="store_true", help="Suppress progress output.")
    p_scan.add_argument("--verbose", "-v", action="store_true", help="Verbose logging.")

    p_deps = sub.add_parser("deps", help="Run dependency (npm audit) analysis only.")
    p_deps.add_argument("--path", "-p", required=True, help="Target project directory.")
    p_deps.add_argument("--format", "-f", choices=["json", "json-compact"], default="json-compact")

    p_rules = sub.add_parser("rules", help="List all self-authored rules.")
    p_rules.add_argument("--format", "-f", choices=["json", "json-compact", "markdown"], default="markdown")

    return parser


def _grade_rank(g: str) -> int:
    return {"A": 5, "B": 4, "C": 3, "D": 2, "F": 1}.get(g, 0)


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)

    level = logging.DEBUG if getattr(args, "verbose", False) else (logging.WARNING if getattr(args, "quiet", False) else logging.INFO)
    logging.basicConfig(level=level, format="%(message)s")

    try:
        if args.command == "scan":
            result = run_scan(
                root=args.path,
                dimensions=args.dimensions,
                run_lint=not args.no_lint,
                run_deps=not args.no_deps,
                include_lint_detail=args.include_lint,
            )
            _emit(result, args.format)
            # B1: an empty/invalid scan surfaces an explicit error state and
            # must exit non-zero — never let it look like a clean pass.
            if result.get("error"):
                return EXIT_CONFIG_ERROR
            # Exit code logic: error findings → 1, else 0. Threshold gate overrides.
            by_sev = result.get("by_severity", {})
            exit_code = EXIT_ERROR if by_sev.get("error", 0) > 0 else EXIT_OK
            if args.threshold:
                score = result.get("score") or {}
                grade = score.get("grade", "F")
                if _grade_rank(grade) < _grade_rank(args.threshold):
                    exit_code = EXIT_ERROR
            return exit_code

        if args.command == "deps":
            # M5: emit a scan-compatible schema so consumers can treat `deps`
            # and `scan -d deps` uniformly. We reuse the scan result shape
            # (score / grade / issues / triage / deps_summary / findings) and
            # the shared output formatters instead of an ad-hoc payload.
            from audit.deps import analyze_dependencies
            from audit.scoring import calculate_score, count_by_severity
            from audit.triage import apply_triage, triage_summary

            findings, summary, notice = analyze_dependencies(args.path)
            # package.json missing → surface as error state like scan does
            if summary.get("packages") == 0 and notice:
                result = {
                    "project_root": args.path, "files_scanned": 0,
                    "findings": [], "score": None,
                    "by_severity": {"error": 0, "warning": 0, "info": 0},
                    "triage_summary": {"deterministic": 0, "agent_verify": 0, "agent_only": 0, "total": 0},
                    "degradation_notices": [notice] if notice else [],
                    "deps_summary": summary, "error": "NO_PACKAGE_JSON" if "package.json not found" in (notice or "") else None,
                }
                _emit(result, args.format)
                return EXIT_CONFIG_ERROR if result["error"] else EXIT_OK

            apply_triage(findings)
            score = calculate_score(findings)
            result = {
                "project_root": args.path,
                "files_scanned": 1,  # package.json
                "findings": [f.to_dict() for f in findings],
                "score": score,
                "by_severity": count_by_severity(findings),
                "triage_summary": triage_summary(findings),
                "degradation_notices": [notice] if notice else [],
                "deps_summary": summary,
                "error": None,
            }
            _emit(result, args.format)
            return EXIT_ERROR if result["by_severity"]["error"] > 0 else EXIT_OK
            return EXIT_ERROR if summary.get("vulnerabilities", {}).get("total", 0) > 0 else EXIT_OK

        if args.command == "rules":
            rules = all_rules()
            if args.format == "json" or args.format == "json-compact":
                print(json.dumps([r.to_dict() for r in rules], indent=(2 if args.format == "json" else None), ensure_ascii=False))
            else:
                lines = [
                    "# frontend-audit 自研规则集",
                    "",
                    "| 规则 ID | 维度 | 严重度 | triage | CWE | 标题 |",
                    "|---------|------|--------|--------|-----|------|",
                ]
                for r in rules:
                    lines.append(f"| {r.id} | {r.dimension} | {r.severity} | {r.triage} | {r.cwe} | {r.title} |")
                print("\n".join(lines))
            return EXIT_OK

        # unreachable (argparse enforces subcommand choice)
        return EXIT_OK

    except AuditError as e:
        print(json.dumps(e.to_dict(), ensure_ascii=False), file=sys.stderr)
        return e.exit_code


def _emit(result: dict, fmt: str) -> None:
    if fmt == "json":
        print(format_json(result))
    elif fmt == "json-compact":
        print(format_json_compact(result))
    elif fmt == "sarif":
        print(format_sarif(result))
    elif fmt == "markdown":
        print(format_markdown(result))
    else:  # pragma: no cover
        print(format_json(result))


if __name__ == "__main__":
    sys.exit(main())
