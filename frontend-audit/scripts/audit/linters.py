"""Orchestrate external linters: eslint + tsc.

Each adapter:
- Returns ``(findings, notice)`` where ``notice`` is ``None`` on success or a
  human-readable degradation string when the tool was missing/failed.
- Never raises on tool absence — the engine collects notices and the custom
  rule tier still runs. Configuration errors surface as findings (severity=error).

eslint/tsc output is parsed minimally (eslint JSON, tsc nothing — tsc only
sets exit code + stdout text). We deliberately do NOT replay eslint's full
finding set into our scoring; instead we surface a *summary count* and let
the Agent request the raw report via ``--include-lint`` if it wants detail.
This keeps token usage bounded (eslint on a real project emits thousands of
lines).
"""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
from pathlib import Path

from .models import Finding

logger = logging.getLogger("frontend-audit")

# Map eslint severity (1=warn, 2=error) to ours.
_ESLINT_SEV = {1: "warning", 2: "error"}


def _run(cmd: list[str], cwd: str, timeout: int = 120) -> tuple[int, str, str]:
    """Run a subprocess, returning (returncode, stdout, stderr). Never raises on non-zero."""
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_eslint(root: str, include_detail: bool = False) -> tuple[list[Finding], str | None]:
    """Run eslint in JSON mode. Returns (findings, notice).

    On missing binary or non-zero exit that isn't a normal lint failure,
    returns ([], notice) so the audit continues with the custom tier.
    """
    eslint_bin = _resolve_eslint(root)
    if eslint_bin is None:
        return [], "eslint not found (install: npm i -D eslint). Skipped lint tier."

    cmd = [eslint_bin, ".", "--format=json", "--no-error-on-unmatched-pattern"]
    try:
        rc, out, err = _run(cmd, cwd=root)
    except subprocess.TimeoutExpired:
        return [], "eslint timed out (>120s). Skipped lint tier."
    except FileNotFoundError:
        return [], "eslint not found. Skipped lint tier."

    # eslint exits 1 on lint errors, 2 on config errors. rc 2 → surface as notice.
    if rc == 2:
        return [], f"eslint config error: {(err or out).strip()[:200]}"

    try:
        data = json.loads(out) if out.strip() else []
    except json.JSONDecodeError:
        return [], f"eslint produced non-JSON output (rc={rc}). Skipped lint tier."

    findings: list[Finding] = []
    for file_entry in data:
        rel = file_entry.get("filePath", "")
        # make path relative to root when possible
        try:
            rel = str(Path(rel).relative_to(root))
        except ValueError:
            rel = Path(rel).name
        for msg in file_entry.get("messages", []):
            findings.append(
                Finding(
                    file=rel,
                    line=int(msg.get("line", 0)),
                    column=int(msg.get("column", 0)),
                    severity=_ESLINT_SEV.get(int(msg.get("severity", 1)), "warning"),
                    dimension="best-practice",
                    rule=str(msg.get("ruleId") or "eslint"),
                    message=str(msg.get("message", ""))[:200],
                    source="eslint",
                    evidence="",
                    confidence="high",
                    triage="deterministic",
                )
            )

    # Unless the caller asked for full detail, fold eslint output into a single
    # summary finding so it does not dominate the report / token budget.
    if not include_detail and findings:
        errs = sum(1 for f in findings if f.severity == "error")
        warns = sum(1 for f in findings if f.severity == "warning")
        summary = Finding(
            file="<eslint>",
            line=0,
            severity="error" if errs else "warning",
            dimension="best-practice",
            rule="ESLINT-SUMMARY",
            message=f"eslint reported {errs} error(s), {warns} warning(s). Use --include-lint for detail.",
            source="eslint",
            confidence="high",
            triage="deterministic",
        )
        return [summary], None
    return findings, None


def run_tsc(root: str) -> tuple[list[Finding], str | None]:
    """Run `tsc --noEmit` and report whether type checking passed.

    tsc does not emit structured output; we report a single finding on failure
    with the first few error lines as the message. Returns ([], notice) on
    missing binary.
    """
    tsc_bin = _resolve_tsc(root)
    if tsc_bin is None:
        return [], "tsc not found (no type checking). Skipped tsc tier."

    cmd = [tsc_bin, "--noEmit", "--pretty", "false"]
    try:
        rc, out, err = _run(cmd, cwd=root, timeout=180)
    except subprocess.TimeoutExpired:
        return [], "tsc timed out (>180s). Skipped tsc tier."
    except FileNotFoundError:
        return [], "tsc not found. Skipped tsc tier."

    if rc == 0:
        return [], None

    # rc != 0 → type errors. Collect up to 5 representative lines.
    lines = [ln for ln in (out or "").splitlines() if ln.strip()][:5]
    findings = [
        Finding(
            file="<tsc>",
            line=0,
            severity="error",
            dimension="best-practice",
            rule="TSC-ERROR",
            message=(
                f"tsc --noEmit failed ({len(lines)}+ errors shown). "
                + " | ".join(lines)
            )[:300],
            source="tsc",
            confidence="high",
            triage="deterministic",
        )
    ]
    return findings, None


# ============================================================
# binary resolution (prefer local node_modules, then PATH)
# ============================================================


def _resolve_eslint(root: str) -> str | None:
    local = Path(root) / "node_modules" / ".bin" / ("eslint.cmd" if _is_windows() else "eslint")
    if local.exists():
        return str(local)
    return shutil.which("eslint") or shutil.which("eslint.cmd")


def _resolve_tsc(root: str) -> str | None:
    local = Path(root) / "node_modules" / ".bin" / ("tsc.cmd" if _is_windows() else "tsc")
    if local.exists():
        return str(local)
    return shutil.which("tsc") or shutil.which("tsc.cmd")


def _is_windows() -> bool:
    import os

    return os.name == "nt"
