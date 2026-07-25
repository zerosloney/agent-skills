"""Engine: orchestrate the scan tiers and assemble the result dict.

Tiers, in order:
1. **custom rules** (always run) — regex/AST security + reliability + secrets.
2. **eslint** (optional) — style/best-practice, folded into a summary unless --include-lint.
3. **tsc** (optional) — type errors, surfaced as a single finding on failure.
4. **deps** (optional) — npm audit vulnerabilities.

Each optional tier that is missing or fails contributes a degradation notice
so the Agent can prominently report what was *not* checked.
"""
from __future__ import annotations

import logging
from pathlib import Path

from .deps import analyze_dependencies
from .linters import run_eslint, run_tsc
from .models import Finding
from .output import _finding_to_dict
from .ruledefs.secrets import SECRET_PATTERNS
from .scoring import calculate_score, count_by_severity, dedup_findings
from .triage import apply_triage, triage_summary
from .visitors import discover_files, scan_secrets, scan_text

logger = logging.getLogger("frontend-audit")


def safe_read_file(filepath: str) -> str:
    """Read a file with encoding fallback (utf-8 → gbk → latin-1)."""
    from .errors import AuditError

    encodings = ["utf-8", "utf-8-sig", "gbk", "latin-1"]
    last = None
    for enc in encodings:
        try:
            return Path(filepath).read_text(encoding=enc)
        except (UnicodeDecodeError, OSError) as e:
            last = e
            continue
    raise AuditError(
        f"Failed to read file: {filepath}",
        details={"file": filepath, "last_error": str(last)},
        fix="Check file encoding and permissions.",
    )


def run_scan(
    root: str,
    dimensions: list[str] | None = None,
    run_lint: bool = True,
    run_deps: bool = True,
    include_lint_detail: bool = False,
) -> dict:
    """Run a full audit and return the result dict (findings + score + summary).

    dimensions: None = all. Otherwise subset of
        {"security", "reliability", "best-practice", "arch", "deps"}.
    """
    dimensions = dimensions or ["security", "reliability", "best-practice", "arch", "deps"]
    root_path = Path(root).resolve()
    findings: list[Finding] = []
    notices: list[str] = []

    # ---- Path validation (B1): a non-existent dir or one with no scannable
    # files must NOT return a perfect score — that gives false "A grade / no
    # issues" confidence. Surface as an explicit error state and let the CLI
    # exit non-zero.
    if not root_path.is_dir():
        return _empty_result(str(root_path), [f"target is not a directory: {root_path}"], error="NOT_A_DIRECTORY")
    files = discover_files(root_path)
    files_scanned = len(files)
    if files_scanned == 0:
        return _empty_result(
            str(root_path),
            [f"no JS/TS files found under {root_path} (checked .js/.jsx/.ts/.tsx/.mjs/.cjs/.vue/.svelte). "
             "Verify the path points at a frontend project root."],
            error="NO_FILES",
        )
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            notices.append(f"skip unreadable file {f}: {e}")
            continue
        rel = _rel(f, root_path)
        if "security" in dimensions or "reliability" in dimensions:
            findings.extend(scan_text(text, rel))
        if "security" in dimensions:
            findings.extend(scan_secrets(text, rel, SECRET_PATTERNS))

    # ---- Tier 2: eslint (optional) ----
    if run_lint and ("best-practice" in dimensions or "arch" in dimensions):
        lint_findings, lint_notice = run_eslint(str(root_path), include_detail=include_lint_detail)
        findings.extend(lint_findings)
        if lint_notice:
            notices.append(lint_notice)
        tsc_findings, tsc_notice = run_tsc(str(root_path))
        findings.extend(tsc_findings)
        if tsc_notice:
            notices.append(tsc_notice)
    else:
        if not run_lint:
            notices.append("eslint/tsc skipped (--no-lint).")

    # ---- Tier 3: deps (optional) ----
    deps_summary = None
    if run_deps and "deps" in dimensions:
        dep_findings, deps_summary, dep_notice = analyze_dependencies(str(root_path))
        findings.extend(dep_findings)
        if dep_notice:
            notices.append(dep_notice)
    else:
        notices.append("dependency analysis skipped (--no-deps).")

    # ---- Dimension filter on the merged set ----
    # Findings already carry their scoring dimension (eslint/tsc → best-practice,
    # npm-audit → deps), so a plain membership check is sufficient. The previous
    # form had a dead `or ... and ...` branch that reduced to this same filter.
    if dimensions and len(dimensions) < 5:
        findings = [f for f in findings if f.dimension in dimensions]

    # ---- Dedup, triage, score ----
    findings = dedup_findings(findings)
    findings = apply_triage(findings)
    score = calculate_score(findings)
    by_sev = count_by_severity(findings)
    tri_sum = triage_summary(findings)

    # stable order: severity desc, then file, then line
    sev_rank = {"error": 0, "warning": 1, "info": 2}
    findings.sort(key=lambda f: (sev_rank.get(f.severity, 3), f.file, f.line))

    return {
        "project_root": str(root_path),
        "files_scanned": files_scanned,
        "findings": [_finding_to_dict(f) for f in findings],
        "score": score,
        "by_severity": by_sev,
        "triage_summary": tri_sum,
        "degradation_notices": notices,
        "deps_summary": deps_summary,
        "error": None,
    }


def _empty_result(root: str, notices: list[str], error: str) -> dict:
    """Build a result dict for the empty/invalid-path case (B1).

    score is None (not 100) so consumers cannot mistake this for a clean pass.
    The CLI inspects ``error`` to decide the exit code.
    """
    return {
        "project_root": root,
        "files_scanned": 0,
        "findings": [],
        "score": None,
        "by_severity": {"error": 0, "warning": 0, "info": 0},
        "triage_summary": {"deterministic": 0, "agent_verify": 0, "agent_only": 0, "total": 0},
        "degradation_notices": notices,
        "deps_summary": None,
        "error": error,
    }


def _rel(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root)).replace("\\", "/")
    except ValueError:
        return str(path)
