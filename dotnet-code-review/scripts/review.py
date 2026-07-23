#!/usr/bin/env python3
# ruff: noqa: E402, F401
"""
C# Code Review — Standalone CLI (compat entry -> review/ package)
"""
from __future__ import annotations
import sys
from pathlib import Path

_pkg_dir = Path(__file__).resolve().parent
if str(_pkg_dir) not in sys.path:
    sys.path.insert(0, str(_pkg_dir))

from review.cli import main
from review.engine import run_review
from review.rules import AUTO_FIXES
from review.models import CodeIssue
from review.output import format_json, format_markdown, format_json_compact
from review.errors import ReviewError, ConfigError, ToolMissingError, UserInputError
from review.scoring import calculate_score, count_by_severity, estimate_technical_debt, dedup_issues
from review.complexity import calculate_cognitive_complexity
from review.framework import filter_rules_for_framework
from review.auto_fix import apply_auto_fix, apply_all_auto_fixes
from review.files import discover_files, get_diff_files, get_changed_line_ranges, find_csproj_files
from review.cache import file_hash, load_cache, save_cache
from review.framework import parse_target_framework, parse_target_frameworks, classify_framework
from review.framework import detect_project_type, detect_nuget_packages, get_project_metadata
from review.duplication import detect_duplicates
from review.coverage import load_coverage, analyze_coverage
from review.docs import check_xml_documentation
from review.nuget import check_nuget_versions, check_nuget_cves
from review.history import save_report_history, compute_trend
from review.api_compat import check_api_compatibility
from review.output import format_project_analysis_markdown, truncate_message, group_issues_by_rule, apply_output_mode

__all__ = [
    "AUTO_FIXES",
    "CodeIssue",
    "run_review", "format_json", "format_markdown", "format_json_compact",
    "calculate_score", "count_by_severity", "dedup_issues", "estimate_technical_debt",
    "calculate_cognitive_complexity",
    "filter_rules_for_framework",
    "ReviewError", "ConfigError", "ToolMissingError", "UserInputError",
    "apply_auto_fix", "apply_all_auto_fixes",
    "discover_files", "get_diff_files", "get_changed_line_ranges", "find_csproj_files",
    "detect_duplicates", "check_xml_documentation",
    "check_nuget_versions", "check_nuget_cves",
    "save_report_history", "compute_trend",
    "check_api_compatibility",
    "main",
]

if __name__ == "__main__":
    sys.exit(main())
