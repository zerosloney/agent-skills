# ruff: noqa: F401
from __future__ import annotations

from .errors import (
    ReviewError, ConfigError, ToolMissingError, UserInputError,
    safe_read_file, run_with_retry,
    EXIT_OK, EXIT_ERROR, EXIT_WARNING, EXIT_CONFIG_ERROR,
    EXIT_TOOL_MISSING, EXIT_INTERNAL, EXIT_USER_ERROR,
)
from .rules import (
    AUTO_FIXES, TEST_PROJECT_RELAXED_RULES,
)
from .models import CodeIssue
from .scoring import (
    calculate_score, count_by_severity, estimate_technical_debt, dedup_issues,
    SEVERITY_PENALTIES, CATEGORY_WEIGHTS,
)
from .complexity import (
    calculate_cognitive_complexity,
    _is_cognitive_method, _compute_method_cc, _cognitive_increment,
)
from .output import (
    format_json, format_markdown, format_json_compact, format_sarif,
    format_human_review_checklist,
    format_project_analysis_markdown, truncate_message, group_issues_by_rule,
    apply_output_mode, DEFAULT_MAX_MESSAGE_LENGTH, DEFAULT_MAX_ISSUES,
)
from .files import (
    discover_files, get_diff_files, get_changed_line_ranges, find_csproj_files,
)
from .cache import file_hash, load_cache, save_cache
from .framework import (
    parse_target_framework, parse_target_frameworks,
    _map_legacy_framework, classify_framework, detect_project_type,
    detect_nullable, detect_nuget_packages, get_project_metadata,
    filter_rules_for_framework,
    pick_strictest_framework, detect_framework_from_global_json,
    detect_framework_from_directory_build_props,
)
from .duplication import _normalize_code_block, _code_hash, detect_duplicates
from .coverage import load_coverage, analyze_coverage
from .nuget import (
    check_nuget_versions, _parse_version,
    _load_cve_db, _load_cve_db_meta, _db_age_days,
    CVE_DB_AUTO_REFRESH_DAYS, CVE_DB_WARN_DAYS,
    _get_cve_db_path, check_nuget_cves, refresh_cve_db,
)
from .docs import check_xml_documentation
from .history import (
    _history_file, save_report_history, _load_history, compute_trend,
)
from .api_compat import _extract_public_api, check_api_compatibility
from .auto_fix import apply_auto_fix, apply_all_auto_fixes
from .engine import (
    dotnet_available, analyze_ast, analyze_semantic, analyze_project,
    analyze_build, analyze_format, load_custom_rules, analyze_custom,
    analyze_complexity, _extract_methods, _is_method_signature,
    _extract_method_name, _extract_params,
    calculate_maintainability_index, run_review,
    load_suppressions, apply_suppressions,
)
from .rules import (
    RULE_TRIAGE, RULE_VERIFICATION_HINTS,
    get_triage_for_rule, get_verification_hints,
)
from .context_bundle import extract_context_bundle, build_context_bundles
from .agent_verdicts import (
    load_verdicts, save_verdicts, apply_verdicts, count_verdict_matches,
)
from .cli import main, _calculate_exit_code
