from __future__ import annotations
import json
import logging
from pathlib import Path

logger = logging.getLogger("dotnet-review")


DEFAULT_MAX_MESSAGE_LENGTH = 120
DEFAULT_MAX_ISSUES = 50


# ============================================================
# Output Formatters
# ============================================================


def format_json(result: dict) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False)


# SARIF severity mapping (SARIF levels: none|note|warning|error).
_SARIF_LEVEL = {
    "error": "error",
    "warning": "warning",
    "info": "note",
}


def format_sarif(result: dict) -> str:
    """Render findings as a SARIF v2.1.0 log.

    SARIF is the native format for GitHub Code Scanning and Azure DevOps, so a
    review run can be uploaded via `github/codeql-action/upload-sarif` and shown
    inline on PRs. One result per issue; rules collected into a single tool
    driver. Files without a path are attached to a synthetic ``<project>``.
    """
    issues = result.get("issues", []) or []

    # Build rule index (SARIF results reference rules by index).
    rules: list[dict] = []
    rule_index: dict[str, int] = {}
    for issue in issues:
        rule_id = issue.get("rule") or "UNKNOWN"
        if rule_id not in rule_index:
            rule_index[rule_id] = len(rules)
            sev = issue.get("severity", "warning")
            rules.append(
                {
                    "id": rule_id,
                    "name": rule_id,
                    "shortDescription": {"text": issue.get("message", rule_id)[:200]},
                    "defaultConfiguration": {
                        "level": _SARIF_LEVEL.get(sev, "warning"),
                    },
                    "properties": {
                        "category": issue.get("category", ""),
                        "source": issue.get("source", ""),
                        "severity": sev,
                        "confidence": issue.get("confidence", ""),
                        "evidence_type": issue.get("evidence_type", ""),
                    },
                }
            )

    results = []
    for issue in issues:
        rule_id = issue.get("rule") or "UNKNOWN"
        file_path = issue.get("file") or "<project>"
        line = int(issue.get("line") or 0)
        sev = issue.get("severity", "warning")
        region = {"startLine": max(1, line)} if line and line > 0 else None
        results.append(
            {
                "ruleId": rule_id,
                "ruleIndex": rule_index[rule_id],
                "level": _SARIF_LEVEL.get(sev, "warning"),
                "message": {"text": issue.get("message", "")},
                "locations": [
                    {
                        "physicalLocation": {
                            "artifactLocation": {"uri": file_path},
                            **({"region": region} if region else {}),
                        },
                    }
                ],
            }
        )

    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/"
        "Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "dotnet-code-review",
                        "informationUri": "https://github.com/",
                        "rules": rules,
                    },
                },
                "results": results,
            }
        ],
    }
    return json.dumps(sarif, indent=2, ensure_ascii=False)


def format_markdown(result: dict) -> str:
    score = result.get("score", {})
    by_sev = result.get("by_severity", {})
    issues = result.get("issues", [])
    layers = result.get("layers", {})

    lines = [
        "# C# 代码审查报告",
        "",
        "## 概览",
        f"- **项目**: {result.get('project_root', 'N/A')}",
        f"- **目标框架**: {result.get('framework_version', 'N/A')} ({result.get('framework_type', 'unknown')})",
    ]

    # Project type
    project_type = result.get("project_type", "unknown")
    if project_type != "unknown":
        lines.append(f"- **项目类型**: {project_type}")

    # Multiple frameworks
    frameworks = result.get("frameworks", [])
    if frameworks and len(frameworks) > 1:
        lines.append(f"- **多目标框架**: {', '.join(frameworks)}")

    # NuGet packages
    nuget_packages = result.get("nuget_packages", [])
    if nuget_packages:
        pkg_str = ", ".join(f"{p['name']}@{p['version']}" for p in nuget_packages[:5])
        if len(nuget_packages) > 5:
            pkg_str += f" 等 {len(nuget_packages)} 个"
        lines.append(f"- **NuGet 包**: {pkg_str}")

    # Filtered rules
    filtered_rules = result.get("filtered_rules", [])
    if filtered_rules:
        lines.append(f"- **已过滤规则**: {', '.join(filtered_rules)}")

    lines.extend(
        [
            f"- **审查文件**: {result.get('files_scanned', 0)}",
            f"- **综合评分**: {score.get('overall', 'N/A')} ({score.get('grade', 'N/A')})",
            f"- **问题统计**: 错误 {by_sev.get('error', 0)} / 警告 {by_sev.get('warning', 0)} / 建议 {by_sev.get('info', 0)}",
            "",
            "## 评分详情",
            "| 维度 | 分数 | 权重 |",
            "|------|------|------|",
            f"| 安全 | {score.get('security', 'N/A')} | 20% |",
            f"| 最佳实践 | {score.get('best_practice', 'N/A')} | 20% |",
            f"| 语义 | {score.get('semantic', 'N/A')} | 10% |",
            f"| 风格 | {score.get('style', 'N/A')} | 5% |",
            f"| 复杂度 | {score.get('complexity', 'N/A')} | 10% |",
            f"| 测试 | {score.get('test', 'N/A')} | 5% |",
            f"| 性能 | {score.get('performance', 'N/A')} | 5% |",
            f"| 命名 | {score.get('naming', 'N/A')} | 5% |",
            f"| 可靠性 | {score.get('reliability', 'N/A')} | 5% |",
            f"| 安全热点 | {score.get('security_hotspot', 'N/A')} | 5% |",
            f"| 代码异味 | {score.get('code_smell', 'N/A')} | 10% |",
            "",
            "## 认知复杂度 & 技术债务",
            f"- **认知复杂度**: {result.get('cognitive_complexity', 'N/A')}",
            f"- **技术债务**: {result.get('technical_debt_minutes', 'N/A')} 分钟",
            "",
            "## 分析层统计",
            f"- 内置规则: {layers.get('builtin', 0)}",
            f"- 复杂度分析: {layers.get('complexity', 0)}",
            f"- AST 分析: {layers.get('ast', 0)}",
            f"- 语义分析: {layers.get('semantic', 0)}",
            f"- 项目分析: {layers.get('project', 0)}",
            f"- 编译诊断: {layers.get('build', 0)}",
            f"- 代码风格: {layers.get('format', 0)}",
            "",
            "## 可信度与边界",
        ]
    )

    integrity = result.get("review_integrity", {})
    if integrity:
        skipped = integrity.get("layers_skipped", [])
        skipped_text = (
            ", ".join(
                f"{item.get('layer')} ({item.get('reason')})" for item in skipped[:8]
            )
            if skipped
            else "无"
        )
        lines.extend(
            [
                f"- **.NET SDK 已检查**: {integrity.get('dotnet_sdk_checked', False)}",
                f"- **.NET SDK 版本**: {integrity.get('dotnet_sdk_version') or 'N/A'}",
                f"- **已执行层**: {', '.join(integrity.get('layers_executed', [])) or '无'}",
                f"- **跳过层**: {skipped_text}",
                f"- **CVE 结论可信**: {integrity.get('cve_conclusion_valid', False)}",
                f"- **覆盖率结论可信**: {integrity.get('coverage_conclusion_valid', False)}",
                "",
            ]
        )
        # Explicit downgrade notice when the build/format layers were skipped:
        # in --files mode these are not run, so this is an AST-level review, not a
        # full one — CAxxxx (~500 rules) and compile diagnostics did NOT
        # participate. Surface it so readers don't mistake the report for complete.
        skipped_layer_names = {
            item.get("layer") for item in skipped
        }
        if skipped_layer_names & {"build", "format"}:
            lines.extend(
                [
                    "> ⚠️ **降级审查提示**: build/format 层已跳过，本次为 AST 级审查。"
                    "NetAnalyzers (CAxxxx) 与编译诊断未参与检测，依赖完整类型解析的"
                    "问题可能未报出。如需完整审查，改用 `--target <项目目录>`。",
                    "",
                ]
            )
    else:
        lines.extend(["(未提供 review_integrity 元数据)", ""])

    lines.extend(
        [
            "## 项目级分析",
        ]
    )

    proj = result.get("project_analysis", {})
    if proj:
        proj_analysis_lines = format_project_analysis_markdown(proj)
        lines.extend(proj_analysis_lines)
    else:
        lines.append("(项目级分析需 .NET SDK)")

    # ── Diff Baseline (PR diff-aware) ──
    diff = result.get("diff_baseline")
    if isinstance(diff, dict):
        lines.extend(["", "## Diff Baseline（PR 引入/修复对比）", ""])
        if "error" in diff:
            lines.append(
                f"⚠️ 基线报告加载失败（{diff.get('baseline_report', '')}），"
                f"对比已跳过。请确认路径正确且文件是 review.py JSON 输出。"
            )
        else:
            introduced = diff.get("introduced", [])
            fixed = diff.get("fixed", [])
            sev_changed = diff.get("severity_changed", [])
            unchanged = diff.get("unchanged_count", 0)
            lines.extend([
                f"- **引入（introduced）**: {len(introduced)} 条",
                f"- **修复（fixed）**: {len(fixed)} 条",
                f"- **未变（unchanged）**: {unchanged} 条",
                f"- **严重度变化**: {len(sev_changed)} 条",
            ])
            introduced_score = result.get("introduced_score")
            if isinstance(introduced_score, dict):
                lines.append(
                    f"- **引入问题分数**: {introduced_score.get('overall', 'N/A')}/100"
                )
            # Show introduced issues (the actionable part of a PR review).
            if introduced:
                lines.extend([
                    "",
                    "### 新引入的问题（需关注）",
                    "",
                    "| 严重度 | 规则 | 文件 | 行号 | 描述 |",
                    "|--------|------|------|------|------|",
                ])
                for iss in introduced[:20]:  # cap at 20 to bound output size
                    msg = (iss.get("message") or "")[:60]
                    lines.append(
                        f"| {iss.get('severity', '')} | {iss.get('rule', '')} | "
                        f"{iss.get('file', '')} | {iss.get('line', 0)} | {msg} |"
                    )
                if len(introduced) > 20:
                    lines.append(f"\n（另有 {len(introduced) - 20} 条引入问题未列出）")
            if sev_changed:
                lines.extend([
                    "",
                    "### 严重度变化",
                    "",
                ])
                for sc in sev_changed[:10]:
                    lines.append(
                        f"- {sc.get('rule', '')} @ {sc.get('file', '')}:{sc.get('line', 0)} "
                        f"— {sc.get('baseline_severity', '')} → {sc.get('current_severity', '')}"
                    )

    lines.extend(
        [
            "",
            "## 问题列表",
            "",
            "| 严重度 | 规则 | 文件 | 行号 | 描述 |",
            "|--------|------|------|------|------|",
        ]
    )

    for issue in issues:
        # Support both CodeIssue objects and dicts
        if isinstance(issue, dict):
            file_path = issue.get("file", "")
            severity = issue.get("severity", "")
            rule = issue.get("rule", "")
            line = issue.get("line", 0)
            message = issue.get("message", "")
        else:
            file_path = issue.file
            severity = issue.severity
            rule = issue.rule
            line = issue.line
            message = issue.message
        file_short = Path(file_path).name if file_path else ""
        lines.append(
            f"| {severity} | {rule} | {file_short} | {line} | {message[:80]} |"
        )

    if not issues:
        lines.append("| - | - | - | - | 无问题发现 ✅ |")

    # ── Optional: Issues by rule (when --output-mode by-rule) ──
    issues_by_rule = result.get("issues_by_rule", [])
    if issues_by_rule:
        lines.extend(
            [
                "",
                "## 问题按规则分组",
                "",
                "| 严重度 | 规则 | 类别 | 数量 | 文件数 | 描述 |",
                "|--------|------|------|------|--------|------|",
            ]
        )
        for grp in issues_by_rule[:20]:
            lines.append(
                f"| {grp['severity']} | {grp['rule']} | {grp['category']} | "
                f"{grp['count']} | {grp['file_count']} | {grp['message'][:60]} |"
            )

    # ── Truncation notice ──
    if result.get("truncated"):
        lines.extend(
            [
                "",
                f"> ⚠️ 输出已截断，显示前 {result.get('total_issues', '?')} 个问题中的 "
                f"{len(issues)} 个。使用 `--max-issues` 调整。",
            ]
        )

    return "\n".join(lines)


# ============================================================
# CLI
# ============================================================

# ============================================================
# Output Modes (Token Efficiency)
# ============================================================

DEFAULT_MAX_MESSAGE_LENGTH = 120
DEFAULT_MAX_ISSUES = 50


def truncate_message(msg: str, max_length: int = DEFAULT_MAX_MESSAGE_LENGTH) -> str:
    """Truncate a message to max length with ellipsis."""
    if not msg or len(msg) <= max_length:
        return msg
    return msg[: max_length - 3] + "..."


def group_issues_by_rule(issues: list[dict]) -> list[dict]:
    """Group issues by rule, returning one entry per rule with count."""
    grouped: dict[tuple, dict] = {}
    for issue in issues:
        key = (
            issue.get("rule", ""),
            issue.get("severity", ""),
            issue.get("category", ""),
        )
        if key not in grouped:
            grouped[key] = {
                "rule": key[0],
                "severity": key[1],
                "category": key[2],
                "count": 0,
                "files": set(),
                "message": issue.get("message", ""),
                "suggestion": issue.get("suggestion", ""),
            }
        grouped[key]["count"] += 1
        if issue.get("file"):
            grouped[key]["files"].add(issue["file"])

    result = []
    for g in grouped.values():
        g["files"] = sorted(g["files"])
        g["file_count"] = len(g["files"])
        result.append(g)
    # Sort by severity, then count
    sev_rank = {"error": 0, "warning": 1, "info": 2}
    result.sort(key=lambda x: (sev_rank.get(x["severity"], 3), -x["count"]))
    return result


def apply_output_mode(result: dict, args) -> dict:
    """Apply output mode filtering to reduce token usage.

    Modes:
    - summary: only score and counts (no issues)
    - by-rule: group issues by rule
    - top: top N issues by severity
    - default: all issues (with truncation)
    """
    mode = getattr(args, "output_mode", "default")
    max_issues = getattr(args, "max_issues", DEFAULT_MAX_ISSUES)
    max_msg = getattr(args, "max_message_length", DEFAULT_MAX_MESSAGE_LENGTH)

    issues = result.get("issues", [])

    if mode == "summary":
        # No issues, just summary
        result["issues"] = []
        result["output_mode"] = "summary"
        return result

    if mode == "by-rule":
        # Group by rule
        grouped = group_issues_by_rule(issues)
        result["issues_by_rule"] = grouped
        result["issues"] = []  # Remove raw issues
        result["output_mode"] = "by-rule"
        return result

    if mode == "top":
        # Top N issues
        sev_rank = {"error": 0, "warning": 1, "info": 2}
        sorted_issues = sorted(
            issues,
            key=lambda x: (
                sev_rank.get(x.get("severity", ""), 3),
                x.get("file", ""),
                x.get("line", 0),
            ),
        )
        result["issues"] = sorted_issues[:max_issues]
        result["total_issues"] = len(issues)
        result["truncated"] = len(issues) > max_issues
        result["output_mode"] = "top"
        return result

    # Default mode: truncate messages but keep all issues
    for issue in result.get("issues", []):
        if "message" in issue:
            issue["message"] = truncate_message(issue["message"], max_msg)
        if "suggestion" in issue:
            issue["suggestion"] = truncate_message(issue["suggestion"], max_msg)

    result["output_mode"] = "default"
    return result


def format_project_analysis_markdown(proj: dict) -> list[str]:
    """Format project analysis data as markdown lines."""
    lines = []

    instability = proj.get("project_instability")
    if instability is not None:
        lines.append(f"- **项目不稳定性指数**: {instability} (0=稳定, 1=不稳定)")

    cycles = proj.get("cycles", [])
    if cycles:
        lines.append(f"- **循环依赖**: 发现 {len(cycles)} 个循环")
        for cyc in cycles[:5]:
            desc = cyc.get("description", "")
            lines.append(f"  - {desc}")

    god_classes = proj.get("god_classes", [])
    if god_classes:
        lines.append(f"- **God Classes**: 发现 {len(god_classes)} 个上帝类")
        for gc in god_classes[:5]:
            problem = gc.get("problem", "")
            type_name = gc.get("type", "")
            lines.append(f"  - {type_name}: {problem}")

    arch_violations = proj.get("architecturalViolations", [])
    if arch_violations:
        lines.append(f"- **架构违反**: 发现 {len(arch_violations)} 处")

    violations = proj.get("cross_layer_violations", [])
    if violations:
        lines.append(f"- **跨层依赖违反**: {len(violations)} 处")
        for v in violations[:5]:
            lines.append(f"  - {v}")

    type_metrics = proj.get("type_metrics", [])
    if type_metrics:
        high_fanout = [
            m for m in type_metrics if (isinstance(m, dict) and m.get("fanOut", 0) > 10)
        ]
        if high_fanout:
            lines.append(f"- **高扇出类型**: {len(high_fanout)} 个 (依赖过多)")

    if not lines:
        lines.append("(无显著问题)")

    return lines


def format_json_compact(result: dict) -> str:
    """Format as minimal JSON for maximum token efficiency."""
    score = result.get("score", {})
    by_sev = result.get("by_severity", {})

    # Minimal output: just the essentials
    compact = {
        "score": score.get("overall"),
        "grade": score.get("grade"),
        "issues": by_sev,
        "files": result.get("files_scanned"),
        "framework": result.get("framework_version"),
        "cognitive_complexity": result.get("cognitive_complexity"),
        "technical_debt_minutes": result.get("technical_debt_minutes"),
    }
    if "review_integrity" in result:
        integrity = result["review_integrity"]
        compact_ri = {
            "layers_executed": integrity.get("layers_executed", []),
            "layers_skipped": integrity.get("layers_skipped", []),
            "cve_conclusion_valid": integrity.get("cve_conclusion_valid", False),
            "coverage_conclusion_valid": integrity.get(
                "coverage_conclusion_valid", False
            ),
        }
        # Surface semantic degradation so agents know SEM_* rules are unreliable
        comp_errs = integrity.get("semantic_compilation_errors")
        if comp_errs is not None:
            compact_ri["semantic_compilation_errors"] = comp_errs
            compact_ri["semantic_degraded"] = integrity.get("semantic_degraded", False)
            # List which rule families are affected (SEM/EF/ASP)
            degraded_families = integrity.get("degraded_rule_families")
            if degraded_families:
                compact_ri["degraded_rule_families"] = degraded_families
        # Surface NetAnalyzers injection status + build failures
        if integrity.get("netanalyzers"):
            compact_ri["netanalyzers"] = integrity["netanalyzers"]
        # Surface CVE database freshness at the top level
        cve_db_present = integrity.get("cve_db_present")
        if cve_db_present is not None:
            compact_ri["cve_db_present"] = cve_db_present
            if cve_db_present:
                compact_ri["cve_db_age_days"] = integrity.get("cve_db_age_days")
                compact_ri["cve_db_updated_at"] = integrity.get("cve_db_updated_at", "")
        compact["review_integrity"] = compact_ri

    # Surface degradation notices so the Agent can prominently report them
    notices = result.get("degradation_notices")
    if notices:
        compact["degradation_notices"] = notices

    # Add triage summary (Phase 1 triage for Agent workflow)
    triage = result.get("triage_summary")
    if triage:
        compact["triage"] = triage
    # Add verdict suppression count
    sv = result.get("suppressed_by_verdict", 0)
    if sv:
        compact["suppressed_by_verdict"] = sv

    # Add grouped issues if available
    if "issues_by_rule" in result:
        compact["top_rules"] = result["issues_by_rule"][:10]

    # Add project analysis data
    proj = result.get("project_analysis", {})
    if proj:
        compact["project_instability"] = proj.get("project_instability")
        compact["god_classes"] = proj.get("god_classes", [])[:5]
        compact["cycles"] = proj.get("cycles", [])

    return json.dumps(compact, ensure_ascii=False)


# ============================================================
# Human-review checklist (dimensions with no static detection)
# ============================================================


def format_human_review_checklist() -> str:
    """Render the production-readiness checklist for dimensions the tool has
    *no* static detection capability for.

    These items cannot be concluded by the reviewer (Agent must NOT pass/fail
    them); they are listed so a human can confirm them with runtime/ops tooling.
    Sourced from SKILL.md's "人工补充维度" so the printed text stays in sync
    with the authoritative document rather than being paraphrased by the Agent.
    """
    sections = [
        (
            "📊 可观测性与监控 (Observability)",
            [
                "结构化日志（Serilog / Microsoft.Extensions.Logging 的 JSON sink）",
                "指标收集（OpenTelemetry Metrics / Prometheus / Application Insights）",
                "分布式跟踪（OpenTelemetry Tracing / Application Insights / Jaeger）",
                "健康检查端点（/health, /healthz, IHealthCheck）",
                "统一错误报告与请求关联 ID（correlation ID）",
            ],
        ),
        (
            "📦 部署与运维 (Deployment & Ops)",
            [
                "配置外部化（appsettings / 环境变量 / Key Vault，非硬编码）",
                "数据库迁移版本化（EF Core migrations / DbUp）",
                "回滚策略（支持快速回滚到上一版本）",
                "蓝绿 / 灰度部署能力",
                "特性开关（feature flags）",
            ],
        ),
        (
            "🔐 日志脱敏 (Log Redaction)",
            [
                "禁止记录密码 / token / API key 明文",
                "禁止记录信用卡号 / CVV / SSN",
                "PII 处理符合合规要求（GDPR / 个保法）",
                "（工具缺口：LOG001 仅检测代码层疑似敏感字段，无法保证运行时不泄漏）",
            ],
        ),
        (
            "🌐 传输/会话配置 (Transport & Session)",
            [
                "强制 HTTPS / HSTS（IIS / Kestrel / 反向代理配置）",
                "TLS 1.2+（运行时/OS 级配置确认）",
                "Cookie: Secure / HttpOnly / SameSite 显式设置",
                "CORS 策略最小化（运行时中间件配置）",
            ],
        ),
    ]
    lines = [
        "# 生产就绪人工审查清单",
        "",
        "以下维度本工具**完全无静态检测能力**，Agent 不得对其给出通过/不通过结论。",
        "需人工 review 配合运行时 APM/运维工具逐项确认。",
        "",
    ]
    for title, items in sections:
        lines.append(f"## {title}")
        for it in items:
            lines.append(f"- [ ] {it}")
        lines.append("")
    return "\n".join(lines)
