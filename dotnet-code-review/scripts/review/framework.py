from __future__ import annotations
import logging
import re
from pathlib import Path
from .rules import TEST_PROJECT_RELAXED_RULES

logger = logging.getLogger('dotnet-review')



# Framework strictness ordering: legacy > older modern > newer modern
# Used when a multi-target project needs a single "strictest" framework
# for rule filtering.
_FRAMEWORK_STRICTNESS = {
    # .NET Framework (legacy) — strictest
    "netframework-v4.8": 0, "net48": 0, "net472": 0, "net471": 0, "net47": 0,
    "net46": 0, "net45": 0, "net40": 0,
    # .NET Standard / .NET Core 3.1 (mapped to modern but still restrictive)
    "netstandard2.1": 1, "netstandard2.0": 1, "netcoreapp3.1": 1,
    # .NET 5-10 (newer = less strict for rule filtering)
    "net5.0": 2, "net6.0": 3, "net7.0": 4, "net8.0": 5, "net9.0": 6, "net10.0": 7,
}


def _framework_strictness(fw: str) -> int:
    """Return strictness rank (lower = stricter). Unknown frameworks default to mid."""
    return _FRAMEWORK_STRICTNESS.get(fw.lower(), 3)


def pick_strictest_framework(frameworks: list[str]) -> str:
    """Pick the strictest framework from a list (e.g. multi-target csproj).

    For ``net48;net8.0`` returns ``net48`` — the framework with the tightest
    rule constraints. Unrecognized frameworks fall back to the first entry.
    """
    if not frameworks:
        return ""
    if len(frameworks) == 1:
        return frameworks[0]
    return min(frameworks, key=_framework_strictness)


def detect_framework_from_global_json(project_root: str) -> str:
    """Read global.json MSBuild SDK version as fallback framework hint.

    Returns the mapped framework string or "" if not found.
    Only used when no csproj is present (files-only / diff scans).
    """
    gj = Path(project_root) / "global.json"
    if not gj.exists():
        return ""
    try:
        content = gj.read_text(encoding="utf-8")
    except OSError:
        return ""
    m = re.search(r'"msBuildSdks"\s*:\s*\{[^}]*"microsoft\.NET\.Sdk"\s*:\s*"([^"]+)"', content)
    if not m:
        m = re.search(r'"sdk"\s*:\s*\{[^}]*"version"\s*:\s*"([^"]+)"', content)
    if not m:
        m = re.search(r'"version"\s*:\s*"([^"]+)"', content)
    if not m:
        return ""
    sdk_ver = m.group(1).strip().lstrip("v")
    # Map SDK version to framework: SDK 8.x -> net8.0, etc.
    major = sdk_ver.split(".")[0]
    try:
        major_int = int(major)
        if major_int >= 8:
            return f"net{major_int}.0"
        elif major_int >= 6:
            return f"net{major_int}.0"
    except ValueError:
        pass
    return "net8.0"  # default to modern if unrecognized


def detect_framework_from_directory_build_props(project_root: str) -> str:
    """Read Directory.Build.props TargetFramework as fallback hint.

    Returns the raw framework string or "" if not found.
    """
    dbf = Path(project_root) / "Directory.Build.props"
    if not dbf.exists():
        return ""
    try:
        content = dbf.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
    m = re.search(r"<TargetFramework>([^<]+)</TargetFramework>", content)
    if not m:
        m = re.search(r"<TargetFrameworks>([^<]+)</TargetFrameworks>", content)
        if m:
            # Multi-target — pick strictest
            fws = [f.strip() for f in m.group(1).split(";") if f.strip()]
            return pick_strictest_framework(fws)
    if m:
        return m.group(1).strip()
    return ""


def parse_target_framework(csproj_path: str) -> str:
    """Parse TargetFramework from csproj (first one if multiple, with legacy mapping)."""
    frameworks = parse_target_frameworks(csproj_path)
    if not frameworks:
        return ""
    # Apply legacy mapping to first framework
    return _map_legacy_framework(frameworks[0])


def parse_target_frameworks(csproj_path: str) -> list[str]:
    """Parse ALL TargetFrameworks from csproj (raw values, no mapping)."""
    try:
        content = Path(csproj_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    # Modern SDK style: <TargetFramework>net8.0</TargetFramework>
    m = re.search(r"<TargetFramework>([^<]+)</TargetFramework>", content)
    if m:
        return [m.group(1).strip()]

    # Multi-target: <TargetFrameworks>net48;net8.0</TargetFrameworks>
    m = re.search(r"<TargetFrameworks>([^<]+)</TargetFrameworks>", content)
    if m:
        return [tf.strip() for tf in m.group(1).split(";") if tf.strip()]

    # Legacy: <TargetFrameworkVersion>v4.8</TargetFrameworkVersion>
    m = re.search(r"<TargetFrameworkVersion>v([^<]+)</TargetFrameworkVersion>", content)
    if m:
        return [f"netframework-v{m.group(1)}"]
    # Fallback: check Directory.Build.props in parent directories
    # (csproj may inherit TargetFramework from Directory.Build.props
    #  or Directory.Build.targets — a common pattern for multi-project repos)
    csproj_dir = Path(csproj_path).resolve().parent
    for parent in [csproj_dir] + list(csproj_dir.parents):
        dbp = parent / "Directory.Build.props"
        if dbp.exists():
            try:
                dbp_content = dbp.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            m = re.search(r"<TargetFramework>([^<]+)</TargetFramework>", dbp_content)
            if m:
                return [m.group(1).strip()]
            m = re.search(r"<TargetFrameworks>([^<]+)</TargetFrameworks>", dbp_content)
            if m:
                return [tf.strip() for tf in m.group(1).split(";") if tf.strip()]
    return []



def _map_legacy_framework(framework: str) -> str:
    """Map old frameworks to net8.0 for unified analysis (except .NET Framework).

    Note: net472/net471/net48 are .NET Framework versions and should NOT be mapped
    to net8.0 - they are legacy frameworks that don't support modern .NET APIs.
    """
    mapping = {
        # .NET Standard is compatible with modern .NET
        "netstandard2.0": "net8.0", "netstandard2.1": "net8.0",
        # .NET Core 3.1 and 5+ can use modern patterns
        "netcoreapp3.1": "net8.0", "net5.0": "net8.0",
    }
    # Note: net48, net472, net471 are .NET Framework and should NOT be mapped
    # They will be classified as legacy by classify_framework()
    return mapping.get(framework.lower(), framework)



def classify_framework(framework: str) -> str:
    """Classify framework as modern/legacy/unknown.

    Legacy = .NET Framework (TFMs: netframework-v*, or the bare net4x aliases
    net40/net45/net46/net47/net48 and their point releases net451/net472 etc.).
    Modern = .NET Core 2.x+ / .NET 5+ (net5.0 .. net10.0, netcoreapp*).
    """
    if not framework:
        return "unknown"

    fw_lower = framework.lower()

    # .NET Framework: explicit "netframework-v*" form (our own legacy mapping)
    # or bare net4x aliases (net40, net45, net451, net472, net48, ...).
    # These must be classified BEFORE the modern check — net48 is .NET Framework,
    # NOT modern .NET, despite not matching net6/net7/.../net10.
    if "netframework" in fw_lower or re.match(r"^net4\d", fw_lower):
        return "legacy"

    mapped = _map_legacy_framework(framework)
    return "modern" if mapped.startswith(("net5", "net6", "net7", "net8", "net9", "net10")) else "legacy"



def detect_project_type(csproj_path: str) -> str:
    """Detect project type from csproj OutputType and SDK.

    Returns: exe, library, web, test, or unknown
    """
    try:
        content = Path(csproj_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return "unknown"

    # Check for test SDK first
    if "Microsoft.NET.Test.Sdk" in content or "xunit" in content.lower() or "nunit" in content.lower():
        return "test"

    # Check for web SDK
    if "Microsoft.NET.Sdk.Web" in content or "Microsoft.AspNetCore" in content:
        return "web"

    # Check OutputType
    m = re.search(r"<OutputType>\s*(\w+)\s*</OutputType>", content)
    if m:
        otype = m.group(1).strip().lower()
        if otype == "exe":
            return "exe"
        elif otype == "library" or otype == "dll":
            return "library"
        elif otype == "winexe":
            return "exe"

    # SDK style without OutputType defaults to library for non-web
    if "<Project Sdk=" in content:
        return "library"

    return "unknown"



def detect_nullable(csproj_path: str) -> bool:
    """Detect if nullable reference types are enabled."""
    try:
        content = Path(csproj_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False

    return re.search(r"<Nullable>\s*enable", content, re.IGNORECASE) is not None



def detect_nuget_packages(csproj_path: str) -> list[dict]:
    """Detect NuGet package references from csproj.

    Returns list of {name, version} dicts.
    """
    try:
        content = Path(csproj_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return []

    packages = []
    # SDK style: <PackageReference Include="..." Version="..." />
    for m in re.finditer(r'<PackageReference\s+Include="([^"]+)"\s+Version="([^"]+)"', content):
        packages.append({"name": m.group(1), "version": m.group(2)})

    return packages



def get_project_metadata(csproj_path: str) -> dict:
    """Extract comprehensive project metadata from csproj."""
    try:
        content = Path(csproj_path).read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}

    metadata = {}

    # AssemblyName
    m = re.search(r"<AssemblyName>([^<]+)</AssemblyName>", content)
    if m:
        metadata["assembly_name"] = m.group(1).strip()

    # Version
    m = re.search(r"<Version>([^<]+)</Version>", content)
    if m:
        metadata["version"] = m.group(1).strip()

    # RootNamespace
    m = re.search(r"<RootNamespace>([^<]+)</RootNamespace>", content)
    if m:
        metadata["root_namespace"] = m.group(1).strip()

    # LangVersion
    m = re.search(r"<LangVersion>([^<]+)</LangVersion>", content)
    if m:
        metadata["lang_version"] = m.group(1).strip()

    # Nullable
    metadata["nullable"] = detect_nullable(csproj_path)

    # TreatWarningsAsErrors
    metadata["warnings_as_errors"] = re.search(
        r"<TreatWarningsAsErrors>\s*true", content, re.IGNORECASE
    ) is not None

    return metadata



def filter_rules_for_framework(
    rules: list[dict],
    framework_type: str,
    project_type: str = "unknown",
) -> list[dict]:
    """Filter rules based on framework and project type.

    - Legacy projects: exclude .NET 8+ specific rules
    - Test projects: relax certain rules
    """
    filtered = []
    for rule in rules:
        rule_id = rule.get("id", "")

        # Skip test-specific relaxed rules for test projects
        if project_type == "test" and rule_id in TEST_PROJECT_RELAXED_RULES:
            continue

        # Adjust severity for test projects
        rule_copy = dict(rule)
        if project_type == "test" and rule_id in TEST_PROJECT_RELAXED_RULES:
            # Lower severity by one level
            if rule_copy.get("severity") == "warning":
                rule_copy["severity"] = "info"
            elif rule_copy.get("severity") == "error":
                rule_copy["severity"] = "warning"

        filtered.append(rule_copy)
    return filtered
