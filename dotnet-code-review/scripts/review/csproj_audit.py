"""csproj configuration audit — detect project-level misconfigurations.

Checks TargetFramework EOL, Nullable enable, Debug in production config,
and missing metadata. Pure text/regex, no Roslyn needed.
"""
from __future__ import annotations

import re
from pathlib import Path
from .models import CodeIssue
from .files import normalize_review_path

# EOL frameworks (no security updates). Map: framework prefix → EOL info
_EOL_FRAMEWORKS = {
    "netcoreapp1": "1.x",
    "netcoreapp2": "2.x",
    "netcoreapp3": "3.x",
    "net4.5": "4.5",
    "net4.6": "4.6",
    "net4.6.1": "4.6.1",
    "net4.7": "4.7",
    "net4.7.1": "4.7.1",
    "net4.7.2": "4.7.2",
    "net5.0": "5.0",
    "net6.0": "6.0",
}

_RE_TFM = re.compile(r"<TargetFramework(?:s)?>([^<]+)</TargetFramework?", re.IGNORECASE)
_RE_NULLABLE = re.compile(r"<Nullable>([^<]+)</Nullable>", re.IGNORECASE)
_RE_DEBUG = re.compile(r"<Configuration>\s*Debug", re.IGNORECASE)


def audit_csproj(csproj_path: str, project_root: str = "") -> list[CodeIssue]:
    """Audit a .csproj file for configuration issues.

    Returns list of CodeIssue with source="csproj".
    """
    issues: list[CodeIssue] = []
    try:
        content = Path(csproj_path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    file_display = normalize_review_path(csproj_path, project_root) or Path(csproj_path).name

    # CSPROJ001: EOL target framework
    tfm_match = _RE_TFM.search(content)
    if tfm_match:
        tfm = tfm_match.group(1).strip()
        for eol_prefix, eol_ver in _EOL_FRAMEWORKS.items():
            if tfm.startswith(eol_prefix):
                issues.append(CodeIssue(
                    file=file_display, line=0, severity="warning",
                    category="best-practice", rule="CSPROJ001",
                    message=f"目标框架 {tfm} ({eol_ver}) 已结束支持(EOL)，无安全更新",
                    source="csproj",
                    suggestion="升级到 LTS 版本(net8.0 或 net10.0)。",
                ))
                break

    # CSPROJ002: Nullable not enabled (modern .NET only)
    if tfm_match and not tfm.startswith("net4"):
        nullable_match = _RE_NULLABLE.search(content)
        if not nullable_match or nullable_match.group(1).strip().lower() != "enable":
            issues.append(CodeIssue(
                file=file_display, line=0, severity="info",
                category="best-practice", rule="CSPROJ002",
                message="可空引用类型未启用(<Nullable>enable</Nullable>)——C# 8+ 最重要的空安全特性",
                source="csproj",
                suggestion="在 <PropertyGroup> 中添加 <Nullable>enable</Nullable>。",
            ))

    # CSPROJ007: TreatWarningsAsErrors not enabled (modern .NET only)
    # Production-grade baseline: warnings as errors catches issues at build time
    # rather than letting them accumulate. info-level — it's a project choice.
    if tfm_match and not tfm.startswith("net4"):
        if not re.search(r"<TreatWarningsAsErrors>\s*true\s*<", content, re.IGNORECASE):
            issues.append(CodeIssue(
                file=file_display, line=0, severity="info",
                category="best-practice", rule="CSPROJ007",
                message="TreatWarningsAsErrors 未启用——生产项目建议将警告视为错误，在构建时捕获问题而非积累",
                source="csproj",
                suggestion="在 <PropertyGroup> 中添加 <TreatWarningsAsErrors>true</TreatWarningsAsErrors>。",
            ))

    # CSPROJ008: NoWarn suppresses security-relevant CA rules
    # Only flags CA codes in the security/crypto/data ranges — blanket NoWarn
    # of style/performance rules is a legitimate project choice.
    for m in re.finditer(r"<NoWarn>\s*([^<]+)\s*</NoWarn>", content, re.IGNORECASE):
        suppressed = m.group(1)
        sec_codes = _security_can_codes_in_nowarn(suppressed)
        if sec_codes:
            issues.append(CodeIssue(
                file=file_display, line=0, severity="warning",
                category="security", rule="CSPROJ008",
                message=f"<NoWarn> 抑制了安全相关分析器规则 {', '.join(sorted(sec_codes))}——可能掩盖安全漏洞",
                source="csproj",
                suggestion="移除安全相关 CA 规则的 NoWarn，或针对具体场景用 #pragma/suppress 精确抑制。",
            ))

    # CSPROJ009: pre-release package versions in production
    # Flags -preview / -rc / -beta / -alpha suffixes in PackageReference or
    # PackageVersion. Pre-release packages are not supported for production use.
    # MSBuild allows both single and double quotes around attribute values.
    for m in re.finditer(
        r"<Package(?:Reference|Version)\s+(?:[^>]*\s)?Version\s*=\s*[\"']([^\"']+)[\"']",
        content, re.IGNORECASE,
    ):
        version = m.group(1)
        if _is_prerelease_version(version):
            issues.append(CodeIssue(
                file=file_display, line=0, severity="warning",
                category="reliability", rule="CSPROJ009",
                message=f"预览版/候选版包版本 '{version}' 不适合生产环境——预发布版本无稳定性/安全更新保证",
                source="csproj",
                suggestion="在生产发布前将预发布版替换为稳定版。",
            ))
            break  # one CSPROJ009 per csproj (avoid noise on multi-package files)

    return issues


# CA rule prefixes that touch security / cryptography / data protection.
# We only flag NoWarn of THESE ranges — not generic style/perf CA codes.
#   CA21xx — Security (usage, crypto, injection vectors)
#   CA30xx — Security (data exposure, X509, XML)
#   CA53xx — Security (newer additions: hardening, supply chain)
_SECURITY_CA_PREFIXES = ("CA21", "CA30", "CA53")


def _security_can_codes_in_nowarn(nwarn_value: str) -> set[str]:
    """Extract security-relevant CA codes from a <NoWarn> value string.

    NoWarn accepts space/comma/semicolon-separated codes. Returns only the
    codes in the security/crypto/data ranges — style/perf NoWarn is a valid
    project choice and is not flagged.
    """
    codes: set[str] = set()
    for token in re.split(r"[\s,;]+", nwarn_value):
        token = token.strip().upper()
        if not token:
            continue
        if any(token.startswith(p) for p in _SECURITY_CA_PREFIXES):
            codes.add(token)
    return codes


def _is_prerelease_version(version: str) -> bool:
    """True if a NuGet version string is a pre-release (not stable).

    NuGet semantics: any '-' in the version introduces a pre-release suffix.
    Common suffixes: -preview, -rc, -beta, -alpha. We accept the simplest
    reliable signal: presence of '-' (stable versions never contain it).
    """
    return "-" in version


def audit_production_config(project_root: str, files_scanned: list[str]) -> list[CodeIssue]:
    """Audit appsettings.json / web.config for production misconfigurations.

    Checks for Debug=true, detailed errors, development environment,
    and plaintext credentials in config values.
    """
    issues: list[CodeIssue] = []
    root = Path(project_root)

    for pattern in ["appsettings.json", "appsettings.*.json", "web.config"]:
        for cfg_path in root.glob(pattern):
            if "Development" in cfg_path.name:
                continue  # skip appsettings.Development.json
            try:
                content = cfg_path.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            file_display = normalize_review_path(str(cfg_path), project_root) or cfg_path.name

            # CSPROJ003: Debug=true in production config
            if re.search(r'"Debug"\s*:\s*true', content, re.IGNORECASE):
                issues.append(CodeIssue(
                    file=file_display, line=0, severity="warning",
                    category="best-practice", rule="CSPROJ003",
                    message="生产配置含 Debug=true",
                    source="csproj",
                    suggestion="确保生产环境的 Debug 为 false。",
                ))

            # CSPROJ004: DetailedErrors in production
            if re.search(r'"DetailedErrors"\s*:\s*true', content, re.IGNORECASE):
                issues.append(CodeIssue(
                    file=file_display, line=0, severity="warning",
                    category="security", rule="CSPROJ004",
                    message="生产配置含 DetailedErrors=true——可能泄漏堆栈信息",
                    source="csproj",
                    suggestion="设置 DetailedErrors 为 false。",
                ))

            # CSPROJ005 / CSPROJ006: plaintext credentials in config values
            issues.extend(_scan_config_for_credentials(content, file_display))

    return issues


# Credential-bearing JSON keys (case-insensitive substring match on the key).
# Conservative whitelist — only keys whose values are almost always secrets.
_CREDENTIAL_KEY_STEMS = (
    "connectionstring", "apikey", "api_key", "apisecret", "secret",
    "clientsecret", "signingkey", "password", "passwd", "pwd",
    "accesstoken", "authtoken", "refreshtoken", "privatekey",
)

# Placeholder syntaxes that indicate the value is not yet a real secret.
# Matches ASP.NET Core (${VAR}), Docker (__VAR__), XML (<VAR>), env (@VAR@),
# and common literal placeholders. Mirrors the C# CheckHardcodedSecret list.
_PLACEHOLDER_TOKENS = ("your_", "placeholder", "example", "changeme", "xxx")


def _is_placeholder_value(value: str) -> bool:
    """True if the value is a placeholder rather than a real secret."""
    if not value or value.strip() in ("", "null", "none", "todo"):
        return True
    # Templating syntaxes: ${VAR}, __VAR__, <VAR>, @VAR@, %VAR%
    if re.search(r"\$\{[^}]+\}", value) or re.search(r"__[A-Z_]+__", value):
        return True
    if value.startswith("<") and value.endswith(">") and len(value) > 2:
        return True
    lower = value.lower()
    return any(tok in lower for tok in _PLACEHOLDER_TOKENS)


def _scan_config_for_credentials(content: str, file_display: str) -> list[CodeIssue]:
    """Scan JSON/config content for plaintext credential keys/values.

    Returns CSPROJ005 (sensitive key with plaintext value) and CSPROJ006
    (value looks like a connection string with inline credentials) issues.
    Regex-based — tolerant of .json5 comments and minor formatting variations.

    Two orthogonal triggers:
      - key matches a credential stem (catches top-level "ApiKey": "...")
      - value matches inline-credential connection-string pattern, regardless
        of key name (catches nested "ConnectionStrings": {"Default": "Server=...;Password=...;"})
    """
    issues: list[CodeIssue] = []
    # Match "Key" : "value" with optional inline whitespace.
    pair_re = re.compile(r'"([^"]+)"\s*:\s*"([^"]*)"', re.MULTILINE)
    for m in pair_re.finditer(content):
        key, value = m.group(1), m.group(2)
        if _is_placeholder_value(value):
            continue
        key_lower = key.lower()
        value_is_connstring = bool(
            re.search(r"(password|pwd|user\s*id|uid)\s*=", value, re.IGNORECASE)
        )

        # CSPROJ006: value contains inline DB credentials — fires regardless
        # of key name (covers nested ConnectionStrings sections).
        if value_is_connstring:
            issues.append(CodeIssue(
                file=file_display, line=0, severity="warning",
                category="security", rule="CSPROJ006",
                message=f"配置键 '{key}' 的值内嵌明文凭据（Password=/User ID=）——应使用集成认证或密钥管理服务注入",
                source="csproj",
                suggestion="改用 Integrated Security 或从 Azure Key Vault / 环境变量注入凭据。",
            ))
            continue  # CSPROJ006 is more specific; skip the generic CSPROJ005

        # CSPROJ005: sensitive key with plaintext (non-placeholder) value.
        # Minimum length 6 to skip short / empty-ish values that slipped through.
        if len(value) >= 6 and any(stem in key_lower for stem in _CREDENTIAL_KEY_STEMS):
            issues.append(CodeIssue(
                file=file_display, line=0, severity="warning",
                category="security", rule="CSPROJ005",
                message=f"配置键 '{key}' 含疑似明文凭据——生产环境应从密钥管理服务或环境变量注入",
                source="csproj",
                suggestion=f"将 '{key}' 的值移到环境变量、Azure Key Vault 或 user-secrets，配置文件只保留占位符。",
            ))
    return issues
