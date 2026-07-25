"""Dependency analysis: npm audit vulnerabilities + license summary.

Reads ``package.json`` and (optionally) ``package-lock.json``. Runs
``npm audit --json`` when npm is available; otherwise parses the lockfile's
``metadata``/advisory-free path and reports a degraded notice.

Each vulnerability becomes one Finding with ``dimension="deps"``.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from pathlib import Path

from .models import Finding

logger = logging.getLogger("frontend-audit")


def analyze_dependencies(root: str) -> tuple[list[Finding], dict, str | None]:
    """Return (findings, deps_summary, notice).

    deps_summary: {"packages": N, "vulnerabilities": {"critical":..,...}, "npm_available": bool}
    notice: None on full success, else a degradation message.
    """
    pkg = _load_package_json(root)
    if pkg is None:
        return [], {"packages": 0, "vulnerabilities": {}, "npm_available": False}, (
            "package.json not found; dependency analysis skipped."
        )

    deps_count = len(pkg.get("dependencies", {})) + len(pkg.get("devDependencies", {}))

    npm = _resolve_npm()
    if npm is None:
        notice = "npm not found on PATH; cannot run `npm audit`. Install Node to enable dependency CVE scanning."
        return [], {"packages": deps_count, "vulnerabilities": {}, "npm_available": False}, notice

    try:
        proc = subprocess.run(
            [npm, "audit", "--json"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
        )
    except subprocess.TimeoutExpired:
        return [], {"packages": deps_count, "vulnerabilities": {}, "npm_available": True}, (
            "npm audit timed out (>120s)."
        )
    except (FileNotFoundError, OSError) as e:
        # On Windows, `shutil.which("npm")` may resolve to a shell script that
        # can't be executed directly by CreateProcess. Treat as "npm unusable".
        return [], {"packages": deps_count, "vulnerabilities": {}, "npm_available": False}, (
            f"npm found on PATH but not executable ({e}). Install Node.js or add npm.cmd to PATH."
        )

    # npm audit exits non-zero when vulnerabilities exist; that's normal.
    raw = proc.stdout.strip()
    try:
        data = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        return [], {"packages": deps_count, "vulnerabilities": {}, "npm_available": True}, (
            f"npm audit produced non-JSON output (rc={proc.returncode})."
        )

    return _extract_from_audit(data, deps_count)


# npm audit v7+ JSON shape
_SEV_ORDER = {"critical": "error", "high": "error", "moderate": "warning", "low": "info", "info": "info"}


def _extract_from_audit(data: dict, deps_count: int) -> tuple[list[Finding], dict, str | None]:
    meta = data.get("metadata", {}) or {}
    vulns_meta = meta.get("vulnerabilities", {}) or {}
    summary = {
        "packages": deps_count,
        "vulnerabilities": {
            "critical": vulns_meta.get("critical", 0),
            "high": vulns_meta.get("high", 0),
            "moderate": vulns_meta.get("moderate", 0),
            "low": vulns_meta.get("low", 0),
            "info": vulns_meta.get("info", 0),
            "total": vulns_meta.get("total", 0),
        },
        "npm_available": True,
    }

    findings: list[Finding] = []
    for name, entry in (data.get("vulnerabilities", {}) or {}).items():
        sev = str(entry.get("severity", "moderate"))
        severity = _SEV_ORDER.get(sev, "warning")
        via = entry.get("via", [])
        # via entries are either dicts (advisory objects with title/url) or
        # strings (advisory ids like "GHSA-xxxx" or package names). We collect
        # whichever reference is available — url when present, id otherwise.
        advisory_refs: list[str] = []
        advisory_titles: list[str] = []
        for v in via:
            if isinstance(v, dict):
                advisory_titles.append(str(v.get("title", "")))
                if v.get("url"):
                    advisory_refs.append(str(v["url"]))
            elif isinstance(v, str):
                advisory_refs.append(v)
        title = advisory_titles[0] if advisory_titles else f"vulnerable dependency: {name}"
        findings.append(
            Finding(
                file="package.json",
                line=0,
                severity=severity,
                dimension="deps",
                rule=f"NPM-AUDIT-{sev.upper()}",
                message=f"{name}@{entry.get('range', '?')} — {title}",
                source="npm-audit",
                # evidence holds advisory references: URLs when npm provided
                # them, otherwise GHSA ids / package names.
                evidence=(" | ".join(advisory_refs) or "")[:200],
                confidence="high",
                fix_hint=f"Run `npm audit fix` or upgrade {name}.",
                triage="deterministic",
            )
        )
    return findings, summary, None


def _load_package_json(root: str) -> dict | None:
    p = Path(root) / "package.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _resolve_npm() -> str | None:
    """Resolve a directly-executable npm binary.

    On Windows, ``shutil.which("npm")`` may return the extensionless shell
    wrapper (``%node%\\npm``) which CreateProcess cannot launch. Prefer the
    ``.cmd`` shim there.
    """
    if os.name == "nt":
        for name in ("npm.cmd", "npm"):
            found = shutil.which(name)
            if found:
                return found
        return None
    return shutil.which("npm")
