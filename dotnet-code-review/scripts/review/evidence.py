from __future__ import annotations

from .models import CodeIssue
from .nuget import CVE_DB_AUTO_REFRESH_DAYS


ISSUE_EVIDENCE_BY_SOURCE = {
    "ast": {
        "confidence": "high",
        "evidence_type": "roslyn_ast",
        "checker": "csharp-ast-analyzer",
        "layer": "ast",
        "deterministic": True,
        "requires_build": False,
        "limitations": [],
    },
    "semantic": {
        "confidence": "high",
        "evidence_type": "roslyn_semantic",
        "checker": "csharp-semantic-analyzer",
        "layer": "semantic",
        "deterministic": True,
        "requires_build": True,
        "limitations": [],
    },
    "project": {
        "confidence": "high",
        "evidence_type": "roslyn_project",
        "checker": "csharp-project-analyzer",
        "layer": "project",
        "deterministic": True,
        "requires_build": True,
        "limitations": [],
    },
    "build": {
        "confidence": "high",
        "evidence_type": "compiler_diagnostic",
        "checker": "dotnet build",
        "layer": "build",
        "deterministic": True,
        "requires_build": True,
        "limitations": [],
    },
    "format": {
        "confidence": "medium",
        "evidence_type": "dotnet_format",
        "checker": "dotnet format",
        "layer": "format",
        "deterministic": True,
        "requires_build": True,
        "limitations": ["Depends on project .editorconfig and SDK analyzer availability."],
    },
    "coverage": {
        "confidence": "medium",
        "evidence_type": "coverage_report",
        "checker": "cobertura",
        "layer": "coverage",
        "deterministic": True,
        "requires_build": False,
        "limitations": ["Only as fresh and complete as the supplied coverage report."],
    },
    "nuget": {
        "confidence": "medium",
        "evidence_type": "package_metadata",
        "checker": "nuget",
        "layer": "nuget",
        "deterministic": True,
        "requires_build": False,
        "limitations": ["Version advice depends on package metadata, not runtime behavior."],
    },
    "custom": {
        "confidence": "low",
        "evidence_type": "user_defined_rule",
        "checker": ".dotnet-review/rules.json",
        "layer": "custom",
        "deterministic": False,
        "requires_build": False,
        "limitations": ["User-defined regex rules can be noisy and are never auto-fixed."],
    },
    "duplicate": {
        "confidence": "medium",
        "evidence_type": "text_similarity",
        "checker": "duplicate-detector",
        "layer": "duplicate",
        "deterministic": True,
        "requires_build": False,
        "limitations": ["Text-level duplicate detection does not prove semantic duplication."],
    },
    "doc": {
        "confidence": "medium",
        "evidence_type": "text_scan",
        "checker": "xml-doc-check",
        "layer": "doc",
        "deterministic": True,
        "requires_build": False,
        "limitations": ["Checks XML documentation presence, not documentation quality."],
    },
    "style": {
        "confidence": "medium",
        "evidence_type": "text_scan",
        "checker": "style-hints",
        "layer": "style",
        "deterministic": True,
        "requires_build": False,
        "limitations": ["Comment and hint checks are intentionally lightweight."],
    },
}


def serialize_issue(issue: CodeIssue) -> dict:
    evidence = ISSUE_EVIDENCE_BY_SOURCE.get(
        issue.source,
        {
            "confidence": "medium",
            "evidence_type": "unknown",
            "checker": issue.source or "unknown",
            "layer": issue.source or "unknown",
            "deterministic": False,
            "requires_build": False,
            "limitations": ["No explicit evidence mapping is defined for this source."],
        },
    )
    # Resolve triage: explicit on issue > RULE_TRIAGE lookup > source-based default
    triage = issue.triage
    if not triage:
        from .rules import get_triage_for_rule
        triage = get_triage_for_rule(issue.rule)
    # Build verification_hints only for agent_verify
    verification_hints = []
    if triage == "agent_verify":
        from .rules import get_verification_hints
        verification_hints = get_verification_hints(issue.rule)
    result = {
        "file": issue.file,
        "line": issue.line,
        "column": issue.column,
        "severity": issue.severity,
        "category": issue.category,
        "rule": issue.rule,
        "message": issue.message,
        "source": issue.source,
        "suggestion": issue.suggestion,
        "triage": triage,
        "confidence": evidence["confidence"],
        "evidence_type": evidence["evidence_type"],
        "verification": {
            "checker": evidence["checker"],
            "layer": evidence["layer"],
            "deterministic": evidence["deterministic"],
            "requires_build": evidence["requires_build"],
        },
        "limitations": list(evidence["limitations"]),
    }
    if verification_hints:
        result["verification_hints"] = verification_hints
    # Attach context_bundle if present (set by engine during run_review)
    if hasattr(issue, "_context_bundle") and issue._context_bundle:
        result["context_bundle"] = issue._context_bundle
    return result


def cve_conclusion_valid(cve_result: dict, cve_requested: bool) -> bool:
    if not cve_requested:
        return False
    if not cve_result.get("db_present"):
        return False
    age_days = cve_result.get("db_age_days")
    if age_days is None:
        return False
    return age_days <= CVE_DB_AUTO_REFRESH_DAYS


def coverage_conclusion_valid(coverage_data: dict, coverage_requested: bool) -> bool:
    return bool(coverage_requested and coverage_data.get("summary"))


# SEM_* and EF* rule prefixes that depend on type/symbol resolution via
# SemanticModel. When compilation errors occur, these rules are degraded
# (may produce false negatives) because the SemanticModel cannot reliably
# resolve types. Listed here so the review_integrity report can tell the
# Agent exactly which rule families are affected.
TYPE_DEPENDENT_RULE_PREFIXES = [
    "SEM",
    "EF",
    "ASP",
]

# Build/format layer impact: approximate number of CAxxxx rules skipped when
# these layers are not executed. Used in degradation notices so the Agent
# understands the magnitude of what was missed.
BUILD_LAYER_APPROX_RULES = "~500 CAxxxx (NetAnalyzers)"
FORMAT_LAYER_APPROX_RULES = "~30 IDE00xx (code style)"


def build_review_integrity(
    *,
    sdk_present: bool,
    sdk_version: str | None,
    requested_layers: set[str],
    executed_layers: set[str],
    skipped_layer_details: list[dict],
    cve_result: dict,
    cve_requested: bool,
    coverage_data: dict,
    coverage_requested: bool,
    netanalyzers_summary: dict | None = None,
) -> dict:
    integrity = {
        "dotnet_sdk_checked": True,
        "dotnet_sdk_version": sdk_version if sdk_present else None,
        "layers_requested": sorted(requested_layers),
        "layers_executed": sorted(executed_layers),
        "layers_skipped": skipped_layer_details,
        "cve_conclusion_valid": cve_conclusion_valid(cve_result, cve_requested),
        "coverage_conclusion_valid": coverage_conclusion_valid(
            coverage_data, coverage_requested
        ),
        "netanalyzers": netanalyzers_summary or {
            "injected_for_projects": 0,
            "skipped_projects": [],
            "disabled_by_user": False,
        },
    }

    # ── CVE database freshness ──
    # Surface db_age_days and db_updated_at at the top level of review_integrity
    # so agents don't need to dig into the nested cve_check object to determine
    # whether a "no vulnerabilities" conclusion is trustworthy.
    if cve_requested and cve_result:
        integrity["cve_db_present"] = cve_result.get("db_present", False)
        if cve_result.get("db_present"):
            integrity["cve_db_updated_at"] = cve_result.get("db_updated_at", "")
            integrity["cve_db_age_days"] = cve_result.get("db_age_days")

    return integrity


def build_degradation_notices(
    *,
    skipped_layer_details: list[dict],
    sem_comp_errs: int,
) -> list[dict]:
    """Build human-readable degradation notices for skipped/stale layers.

    Returns a list of {layer, impact, notice} dicts. Called by the engine
    after review_integrity is assembled so the Agent can surface these
    prominently in its Findings/Summary instead of burying them in
    layers_skipped.
    """
    notices: list[dict] = []

    # Build/format layer skips
    for detail in skipped_layer_details:
        layer = detail.get("layer", "")
        reason = detail.get("reason", "")
        if layer == "build" and reason in ("--files mode", "--skip-build"):
            notices.append({
                "layer": "build",
                "impact": BUILD_LAYER_APPROX_RULES,
                "notice": (
                    "Build layer skipped — compiler diagnostics (CSxxxx) and "
                    "NetAnalyzers (CAxxxx) are not running. Security/reliability "
                    "rules that only exist in the compiler layer will be missed. "
                    "Use --target <dir> instead of --files to enable this layer."
                ),
            })
        elif layer == "format" and reason in ("--files mode", "--skip-format"):
            notices.append({
                "layer": "format",
                "impact": FORMAT_LAYER_APPROX_RULES,
                "notice": (
                    "Format layer skipped — IDE00xx code style diagnostics are "
                    "not running. Style/naming violations detectable only by "
                    "dotnet format will be missed. Use --target <dir> instead "
                    "of --files to enable this layer."
                ),
            })

    # Semantic degradation due to compilation errors
    if sem_comp_errs and sem_comp_errs > 0:
        notices.append({
            "layer": "semantic",
            "impact": f"{len(TYPE_DEPENDENT_RULE_PREFIXES)} rule families ({', '.join(TYPE_DEPENDENT_RULE_PREFIXES)})",
            "notice": (
                f"Semantic analysis reported {sem_comp_errs} compilation "
                f"errors — type-dependent rules ({', '.join(TYPE_DEPENDENT_RULE_PREFIXES)}*) "
                "may produce false negatives because SemanticModel cannot "
                "reliably resolve types in code that does not compile. "
                "Fix compilation errors first, then re-run for full coverage."
            ),
        })

    return notices
