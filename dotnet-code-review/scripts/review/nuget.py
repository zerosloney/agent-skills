from __future__ import annotations
import json
import logging
import time
from pathlib import Path
from .models import CodeIssue

logger = logging.getLogger("dotnet-review")


KNOWN_OUTDATED_PACKAGES = {
    "Newtonsoft.Json": {
        "min_safe": "13.0.0",
        "note": "Consider migrating to System.Text.Json for .NET 8+",
    },
    "EntityFramework": {
        "min_safe": "6.0.0",
        "note": "Consider migrating to Entity Framework Core",
    },
    "log4net": {
        "min_safe": "2.0.10",
        "note": "log4net is in maintenance mode, consider Microsoft.Extensions.Logging",
    },
    "System.Data.SqlClient": {
        "min_safe": "4.8.5",
        "note": "Microsoft.Data.SqlClient is recommended for new development",
    },
    "Newtonsoft.Json.Schema": {
        "min_safe": "3.0.16",
        "note": "Update to latest version for security fixes",
    },
}


def _parse_version(version: str) -> tuple[int, ...]:
    """Parse version string into comparable tuple."""
    try:
        return tuple(int(x) for x in version.split(".")[:3])
    except (ValueError, AttributeError):
        return (0,)


# NuGet FlatContainer: returns all published versions (listed + unlisted) of a
# package. Used by refresh_cve_db to expand OSV ECOSYSTEM ranges into the
# explicit per-version index the offline DB requires.
_NUGET_FLATCONTAINER = "https://api.nuget.org/v3-flatcontainer/{pkg_lower}/index.json"


def _fetch_nuget_versions(pkg_name: str, timeout: int = 15) -> list[str]:
    """Fetch all published versions of a NuGet package from FlatContainer.

    Returns ``[]`` on any network/parse error — callers treat this as "cannot
    expand ranges for this package" and gracefully degrade to versions-only
    indexing (the historical behavior). Never raises: this runs inside DB
    construction where one package's network failure must not abort the build.
    """
    import json as _json
    import urllib.error
    import urllib.request

    url = _NUGET_FLATCONTAINER.format(pkg_lower=pkg_name.lower())
    req = urllib.request.Request(
        url, headers={"User-Agent": "dotnet-code-review"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = _json.loads(resp.read().decode("utf-8"))
        versions = data.get("versions", [])
        versions = versions[-100:]  # cap to last 100 versions
        return [str(v) for v in versions if isinstance(v, str)]
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return []


def _parse_ecosystem_ranges(ranges: list) -> list[tuple[str | None, str | None]]:
    """Parse OSV ``ranges[]`` entries of ``type == "ECOSYSTEM"`` into
    ``(introduced, fixed)`` pairs.

    OSV encodes each range as ``{"type": "ECOSYSTEM", "events": [...]}`` where
    events alternate ``{"introduced": v}`` / ``{"fixed": v}``. We pair them up:
    an ``introduced`` with no following ``fixed`` means ``[v, +∞)``. A leading
    ``fixed`` without ``introduced`` means ``[0, fixed)``. Non-ECOSYSTEM ranges
    (e.g. GIT) are ignored — NuGet advisories only use ECOSYSTEM.

    Returns ``[]`` when there are no ECOSYSTEM ranges.
    """
    pairs: list[tuple[str | None, str | None]] = []
    for r in ranges or []:
        if not isinstance(r, dict) or r.get("type") != "ECOSYSTEM":
            continue
        introduced: str | None = None
        for ev in r.get("events", []):
            if not isinstance(ev, dict):
                continue
            if "introduced" in ev:
                introduced = ev["introduced"]
            elif "fixed" in ev:
                pairs.append((introduced, ev["fixed"]))
                introduced = None
        # Trailing introduced with no fixed → unbounded upper.
        if introduced is not None:
            pairs.append((introduced, None))
    return pairs


def _version_in_range(
    version: str, introduced: str | None, fixed: str | None
) -> bool:
    """True iff ``version`` ∈ ``[introduced, fixed)``.

    ``introduced=None`` → ``-∞``; ``fixed=None`` → ``+∞``. Comparison uses
    ``_parse_version`` (numeric tuple, first 3 components), consistent with the
    existing ``check_nuget_versions`` outdated-package check. Versions that
    fail to parse compare as ``(0,)``.
    """
    v = _parse_version(version)
    if introduced is not None:
        if v < _parse_version(introduced):
            return False
    if fixed is not None:
        if v >= _parse_version(fixed):
            return False
    return True


def check_nuget_versions(packages: list[dict]) -> list[CodeIssue]:
    """Check NuGet packages for outdated versions."""
    issues = []
    for pkg in packages:
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        if name in KNOWN_OUTDATED_PACKAGES:
            min_safe = _parse_version(KNOWN_OUTDATED_PACKAGES[name]["min_safe"])
            current = _parse_version(version)
            if current < min_safe:
                issues.append(
                    CodeIssue(
                        file="*.csproj",
                        line=0,
                        column=0,
                        severity="warning",
                        category="best-practice",
                        rule="NUG001",
                        message=f"Outdated package: {name} {version} (recommended: {KNOWN_OUTDATED_PACKAGES[name]['min_safe']})",
                        source="nuget",
                        suggestion=KNOWN_OUTDATED_PACKAGES[name]["note"],
                    )
                )
    return issues


# ============================================================
# NuGet CVE Check (offline, optional)
# ============================================================


def _read_db_bytes(path: Path) -> bytes:
    """Read a CVE DB file, transparently decompressing ``.gz`` content.

    Accepts plain JSON (``*.json``) or gzip-compressed JSON (``*.json.gz``).
    The compressed form is the default for the shipped baseline because the
    fully-expanded per-version index is large (>50 MB raw) but compresses to
    <1 MB thanks to highly repetitive advisory text.
    """
    data = path.read_bytes()
    if path.suffix == ".gz" or data[:2] == b"\x1f\x8b":
        import gzip

        return gzip.decompress(data)
    return data


def _load_cve_db(db_path: str) -> dict:
    """Load local CVE database JSON.

    Returns the ``packages`` mapping only (kept for backwards compatibility
    with existing callers/tests). Use :func:`_load_cve_db_meta` when the
    ``updated_at`` timestamp is also needed.

    Expected format:
    {
      "packages": {
        "Newtonsoft.Json": {
          "12.0.1": [{"id": "CVE-2021-XXXX", "severity": "high", "title": "..."}],
          ...
        },
        ...
      },
      "updated_at": "2024-01-01T00:00:00Z"
    }

    Accepts gzip-compressed files (``*.json.gz``). Returns empty dict if file
    missing/invalid.
    """
    if not db_path:
        return {}
    path = Path(db_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(_read_db_bytes(path).decode("utf-8"))
        if not isinstance(data.get("packages"), dict):
            return {}
        return data["packages"]
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _load_cve_db_meta(db_path: str) -> dict:
    """Load the full CVE database document (packages + updated_at + age).

    Returns ``{"packages": {}, "updated_at": "", "age_days": None}`` if the
    file is missing/invalid. ``age_days`` is ``None`` when the timestamp is
    absent/unparseable, otherwise whole days since ``updated_at`` (>= 0).
    """
    empty = {"packages": {}, "updated_at": "", "age_days": None}
    if not db_path:
        return empty
    path = Path(db_path)
    if not path.exists():
        return empty
    try:
        data = json.loads(_read_db_bytes(path).decode("utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return empty
    if not isinstance(data.get("packages"), dict):
        return empty
    updated_at = data.get("updated_at", "") or ""
    return {
        "packages": data["packages"],
        "updated_at": updated_at,
        "age_days": _db_age_days(updated_at),
    }


def _db_age_days(updated_at: str) -> int | None:
    """Whole days between ``updated_at`` (ISO-8601 UTC) and now.

    Returns ``None`` when the timestamp is empty/unparseable (caller treats
    that as "freshness unknown"). Accepts the trailing ``Z`` used by
    ``refresh_cve_db`` as well as explicit numeric offsets.
    """
    if not updated_at:
        return None
    ts = updated_at.strip()
    # datetime.fromisoformat (3.11+) accepts "Z"; for 3.10/3.11- normalize it.
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    try:
        from datetime import datetime, timezone

        dt = datetime.fromisoformat(ts)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return max(0, (datetime.now(timezone.utc) - dt).days)


# A CVE DB older than this (days) is auto-refreshed silently.
# When 3 < age <= 7, a warning is shown. When > 7, an auto-refresh is attempted
# even if --ensure-cve-db was not specified, because a "no vulnerabilities"
# result from an old DB is misleading in CI.
CVE_DB_AUTO_REFRESH_DAYS = 7
CVE_DB_WARN_DAYS = 3


def _get_cve_db_path(configured: str | None = None) -> str:
    """Resolve CVE DB path: user-specified > bundled > none.

    The bundled baseline is shipped as a gzip-compressed file
    (``cve-db/nuget-cve.json.gz``) because the fully-expanded per-version
    index is large; an uncompressed ``nuget-cve.json`` is also accepted for
    back-compat with older checkouts.
    """
    if configured and Path(configured).exists():
        return configured
    # Look for bundled DB next to review.py (prefer compressed baseline)
    base = Path(__file__).parent / "cve-db"
    for name in ("nuget-cve.json.gz", "nuget-cve.json"):
        bundled = base / name
        if bundled.exists():
            return str(bundled)
    return ""


def ensure_cve_db(configured: str | None = None) -> dict:
    """Ensure a CVE database is present, downloading it if missing.

    Used by --ensure-cve-db: if no DB is found at the resolved path, fetch the
    latest NuGet CVE data from OSV.dev into the bundled location. Network errors
    are reported but never raised — the caller still gets a result dict.

    Returns:
        {
            "db_path": str,           # path now present ("" if still missing)
            "ensured": bool,          # True if a download happened
            "updated": int,           # records written by refresh, if any
            "error": str | None,      # error message on failure
        }
    """
    existing = _get_cve_db_path(configured)
    if existing:
        return {"db_path": existing, "ensured": False, "updated": 0, "error": None}

    # Download into the bundled location (matches refresh_cve_db.py default).
    target = str(Path(__file__).parent / "cve-db" / "nuget-cve.json.gz")
    result = refresh_cve_db(target)
    if result.get("error"):
        return {"db_path": "", "ensured": False, "updated": 0, "error": result["error"]}
    return {
        "db_path": target if Path(target).exists() else "",
        "ensured": True,
        "updated": result.get("updated", 0),
        "error": None,
    }


def _extract_dlls_from_assets_json(assets_json_path: str) -> list[str]:
    """Extract DLL paths from obj/{tfm}/project.assets.json.

    The assets.json is the NuGet V3 single source of truth for all package
    references, including transitive dependencies. It records the exact physical
    DLL path in the global package cache (pkgid/version/lib/{tfm}/{pkg}.dll),
    which is more precise than parsing csproj PackageReference entries.

    Returns empty list if file/parsing fails (non-blocking loss for semantic
    analysis; AdhocWorkspace gracefully degrades).
    """
    import json as _json
    dlls: list[str] = []
    try:
        with open(assets_json_path, "r", encoding="utf-8") as f:
            data = _json.load(f)
    except (OSError, _json.JSONDecodeError):
        return dlls

    # The "targets" section maps each TFM to a list of resolved packages.
    targets = data.get("targets", {})
    if not isinstance(targets, dict):
        return dlls
    for target_tfm, packages in targets.items():
        if not isinstance(packages, dict):
            continue
        for pkg_id_ver, pkg_data in packages.items():
            if not isinstance(pkg_data, dict):
                continue
            # Look for DLL paths under "compile" keys
            compile = pkg_data.get("compile", {})
            if not isinstance(compile, dict):
                continue
            for rel_path, disk_path in compile.items():
                if not isinstance(disk_path, str):
                    continue
                # rel_path is like "lib/net6.0/Newtonsoft.Json.dll"
                # disk_path is the absolute path in the global package cache
                if rel_path.endswith(".dll") and disk_path.endswith(".dll"):
                    d_path = Path(disk_path)
                    if d_path.is_absolute() and d_path.is_file():
                        dlls.append(str(d_path.resolve()))
    return dlls


def check_nuget_cves(
    packages: list[dict],
    cve_db_path: str | None = None,
) -> dict:
    """Check NuGet packages against a local CVE database.

    Args:
        packages: List of {"name": ..., "version": ...} dicts from csproj parsing
        cve_db_path: Optional path to CVE DB JSON

    Returns:
        {
            "vulnerabilities": [
                {"package": "Newtonsoft.Json", "version": "12.0.1",
                 "cve_id": "CVE-2021-XXXX", "severity": "high", "title": "..."},
                ...
            ],
            "scanned": 5,
            "db_updated_at": "2024-01-01",
            "db_path": "..."
        }
    """
    db_path = _get_cve_db_path(cve_db_path)
    db_present = bool(db_path)
    meta = (
        _load_cve_db_meta(db_path)
        if db_path
        else {"packages": {}, "updated_at": "", "age_days": None}
    )
    packages_db = meta["packages"]
    updated_at = meta["updated_at"]
    age_days = meta["age_days"]
    vulns = []
    for pkg in packages:
        name = pkg.get("name", "")
        version = pkg.get("version", "")
        if not name:
            continue
        # Lookup exact version
        pkg_vulns = packages_db.get(name, {}).get(version, [])
        for v in pkg_vulns:
            vulns.append(
                {
                    "package": name,
                    "version": version,
                    "cve_id": v.get("id", "UNKNOWN"),
                    "severity": v.get("severity", "unknown"),
                    "title": v.get("title", ""),
                }
            )

    result: dict = {
        "vulnerabilities": vulns,
        "scanned": len(packages),
        "db_path": db_path or "",
        "db_present": db_present,
    }
    if db_present:
        result["db_updated_at"] = updated_at
        result["db_age_days"] = age_days
        # Freshness guard: a present-but-stale (or untimestamped) DB cannot
        # support a trustworthy "clean" conclusion. Surface this explicitly so
        # callers cannot mistake an empty vulnerabilities list for safety.
        if age_days is None:
            result["warning"] = (
                "CVE database has no parseable updated_at timestamp — "
                "freshness unknown. A 'no vulnerabilities' result may miss "
                "recent advisories; re-run refresh_cve_db.py."
            )
        elif age_days > CVE_DB_WARN_DAYS:
            result["warning"] = (
                f"CVE database is {age_days} days old (updated {updated_at}), "
                f"older than the {CVE_DB_WARN_DAYS}-day warn threshold. "
                "Recent vulnerabilities may be missing; re-run refresh_cve_db.py."
            )
    else:
        # No DB available — an empty result is meaningless. Make the limitation
        # explicit so callers (and the review SKILL) cannot mistake "no DB"
        # for "scanned and clean".
        result["warning"] = (
            "No CVE database available. Run `python scripts/refresh_cve_db.py` "
            "to build it before relying on CVE results. 'vulnerabilities' is "
            "empty because nothing was scanned, not because packages are safe."
        )
    return result


def _osv_fetch_vulns(timeout: int = 30) -> list:
    """Single attempt to fetch all NuGet vulnerabilities from OSV.dev.

    The OSV JSON API (``/v1/query``) is *query-based*: it requires a specific
    package name (+ optional version) and rejects ecosystem-only queries with
    HTTP 400/404. To build a full offline baseline for the entire NuGet
    ecosystem we instead consume the official bulk export zip published by the
    OSV GCS mirror (``https://osv-vulnerabilities.storage.googleapis.com/``),
    which contains one JSON record per advisory.

    Returns a list of OSV vulnerability records. Raises on any
    network/parse error so the caller can retry.
    """
    import io
    import urllib.request
    import urllib.error
    import zipfile

    # Bulk export of every NuGet advisory. One .json file per advisory inside.
    url = "https://osv-vulnerabilities.storage.googleapis.com/NuGet/all.zip"
    req = urllib.request.Request(url, headers={"User-Agent": "dotnet-code-review"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()

    vulns: list = []
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for name in zf.namelist():
            if not name.endswith(".json"):
                continue
            try:
                vulns.append(json.loads(zf.read(name)))
            except (OSError, json.JSONDecodeError):
                # Skip malformed individual records; the rest are still useful.
                continue
    return vulns


def refresh_cve_db(output_path: str, retries: int = 0, timeout: int = 30) -> dict:
    """Download latest CVE data from OSV API and save to output_path.

    Uses the OSV.dev bulk export (the OSV JSON ``/v1/query`` endpoint is
    query-based and cannot enumerate a whole ecosystem). Downloads the
    per-advisory record zip for NuGet and indexes every affected package
    version into ``{"packages": {<name>: {<version>: [...]}}}``.

    Args:
        output_path: Where to write the JSON database.
        retries: Number of retry attempts on transient network errors
                 (exponential backoff: 2s, 4s, 8s, ...). Default 0.
        timeout: Per-request timeout in seconds.

    Returns:
        {"updated": N, "path": output_path, "retries_used": int}
        On failure: {"updated": 0, "error": str, "retries_used": int}
    """
    try:
        import urllib.request  # noqa: F401
    except ImportError:
        return {"updated": 0, "error": "urllib not available", "retries_used": 0}

    import urllib.error

    last_error: str | None = None
    retries_used = 0
    vulns: list = []

    # Total attempts = 1 + retries. Retry on transient errors with exponential
    # backoff; do NOT retry on 4xx client errors (the request itself is wrong).
    for attempt in range(retries + 1):
        try:
            vulns = _osv_fetch_vulns(timeout=timeout)
            break
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}: {e.reason}"
            # 4xx = client error, retrying won't help.
            if 400 <= e.code < 500:
                break
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            last_error = str(e)
        except Exception as e:  # JSON parse errors etc.
            last_error = str(e)

        # Not the last attempt → back off and retry.
        if attempt < retries:
            retries_used += 1
            backoff = 2 ** (attempt + 1)  # 2s, 4s, 8s, ...
            time.sleep(backoff)

    else:
        # Loop exhausted without break (all attempts failed).
        return {
            "updated": 0,
            "error": last_error or "unknown error",
            "retries_used": retries_used,
        }

    if not vulns and last_error:
        return {"updated": 0, "error": last_error, "retries_used": retries_used}

    # Transform to our format. The per-advisory package name lives in
    # ``affected[].package.name`` (the bulk export records have no top-level
    # ``package`` field), so iterate affected entries rather than the record.
    # Severity: prefer the GitHub-style string in ``database_specific.severity``
    # (LOW/MODERATE/HIGH/CRITICAL); the record-level ``severity`` field is a
    # list of CVSS score objects rather than a level, so we only use the string
    # labels and leave CVSS-only records as "unknown".
    def _classify(rec_ds, rec_sev_field) -> str:
        if isinstance(rec_ds, str):
            return rec_ds.lower()
        if isinstance(rec_sev_field, list):
            return "unknown"
        return "unknown"

    packages: dict[str, dict[str, list]] = {}
    # FlatContainer results are memoized per package: a single advisory stream
    # typically references the same runtime packages many times, and one HTTP
    # call per package covers all its ranges-only advisories.
    nuget_version_cache: dict[str, list[str]] = {}
    for v in vulns:
        cve_id = v.get("id", "")
        title = v.get("summary", cve_id)
        rec_ds = v.get("database_specific", {}).get("severity")
        rec_severity = _classify(rec_ds, v.get("severity"))
        for a in v.get("affected", []):
            pkg_name = a.get("package", {}).get("name", "")
            if not pkg_name:
                continue
            aff_ds = a.get("database_specific", {}).get("severity")
            severity = aff_ds.lower() if isinstance(aff_ds, str) else rec_severity

            # Start from the explicit versions list (always authoritative when
            # present — OSV fills it for most GHSA records).
            affected_versions: set[str] = set(a.get("versions", []))

            # Expand ECOSYSTEM ranges. OSV NuGet records frequently express the
            # affected set ONLY as {introduced, fixed} with no `versions` list;
            # without this expansion those advisories are silently dropped and
            # the DB under-reports (Bug #1: ~317 entries / 94 packages missing).
            eco_ranges = _parse_ecosystem_ranges(a.get("ranges", []))
            if eco_ranges and not affected_versions:
                if pkg_name not in nuget_version_cache:
                    nuget_version_cache[pkg_name] = _fetch_nuget_versions(
                        pkg_name, timeout=30
                    )
                for ver in nuget_version_cache[pkg_name]:
                    if any(_version_in_range(ver, lo, hi) for lo, hi in eco_ranges):
                        affected_versions.add(ver)

            for version in affected_versions:
                packages.setdefault(pkg_name, {}).setdefault(version, []).append(
                    {
                        "id": cve_id,
                        "severity": severity,
                        "title": title,
                    }
                )
    out = {"packages": packages, "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ")}
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(out, ensure_ascii=False).encode("utf-8")
    if out_path.suffix == ".gz":
        import gzip

        out_path.write_bytes(gzip.compress(payload))
    else:
        out_path.write_bytes(payload)
    return {"updated": len(vulns), "path": output_path, "retries_used": retries_used}
