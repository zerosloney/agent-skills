"""Output formatters: json / json-compact / sarif / markdown.

json-compact is the Agent's default (minimum tokens). markdown is for humans.
sarif is for GitHub Code Scanning.
"""
from __future__ import annotations

import json
from pathlib import Path

from .models import Finding
from .scoring import CATEGORY_WEIGHTS

DEFAULT_MAX_ISSUES = 50
DEFAULT_MAX_MESSAGE_LENGTH = 120

_SARIF_LEVEL = {"error": "error", "warning": "warning", "info": "note"}


def _finding_to_dict(f: Finding) -> dict:
    return {
        "file": f.file,
        "line": f.line,
        "column": f.column,
        "severity": f.severity,
        "dimension": f.dimension,
        "rule": f.rule,
        "message": f.message,
        "source": f.source,
        "evidence": f.evidence,
        "confidence": f.confidence,
        "fix_hint": f.fix_hint,
        "triage": f.triage,
    }


def format_json(result: dict) -> str:
    return json.dumps(result, indent=2, ensure_ascii=False)


def format_json_compact(result: dict) -> str:
    """Minimal JSON for maximum token efficiency (Agent's default)."""
    # score is None in the empty-path error state (B1); treat as missing so
    # the output stays well-formed (score/grade render as null).
    score = result.get("score") or {}
    by_sev = result.get("by_severity", {})
    compact = {
        "score": score.get("overall"),
        "grade": score.get("grade"),
        "issues": by_sev,
        "files": result.get("files_scanned"),
        "dimensions": {
            k: score.get(k) for k in CATEGORY_WEIGHTS
        },
        "findings": [
            {
                "id": f["rule"],
                "sev": f["severity"],
                "dim": f["dimension"],
                "file": f["file"],
                "line": f["line"],
                "conf": f["confidence"],
                "triage": f["triage"],
                "msg": f["message"][:DEFAULT_MAX_MESSAGE_LENGTH],
                "fix": f["fix_hint"][:80] if f.get("fix_hint") else "",
            }
            for f in result.get("findings", [])
        ][:DEFAULT_MAX_ISSUES],
    }
    # Surface the empty-path error state (B1) so consumers detect it without
    # parsing degradation_notices text.
    if result.get("error"):
        compact["error"] = result["error"]
    if result.get("degradation_notices"):
        compact["degradation_notices"] = result["degradation_notices"]
    if result.get("triage_summary"):
        compact["triage"] = result["triage_summary"]
    if result.get("deps_summary"):
        compact["deps"] = result["deps_summary"]
    return json.dumps(compact, ensure_ascii=False)


def format_sarif(result: dict) -> str:
    findings = result.get("findings", [])
    rules: list[dict] = []
    rule_index: dict[str, int] = {}
    for f in findings:
        rid = f["rule"] or "UNKNOWN"
        if rid not in rule_index:
            rule_index[rid] = len(rules)
            sev = f["severity"]
            rules.append({
                "id": rid,
                "name": rid,
                "shortDescription": {"text": f["message"][:200]},
                "defaultConfiguration": {"level": _SARIF_LEVEL.get(sev, "warning")},
                "properties": {
                    "dimension": f["dimension"],
                    "source": f["source"],
                    "confidence": f["confidence"],
                    "triage": f["triage"],
                },
            })

    results = []
    for f in findings:
        rid = f["rule"] or "UNKNOWN"
        line = int(f["line"] or 0)
        region = {"startLine": max(1, line)} if line and line > 0 else None
        results.append({
            "ruleId": rid,
            "ruleIndex": rule_index[rid],
            "level": _SARIF_LEVEL.get(f["severity"], "warning"),
            "message": {"text": f["message"]},
            "locations": [{
                "physicalLocation": {
                    "artifactLocation": {"uri": f["file"]},
                    **({"region": region} if region else {}),
                }
            }],
        })

    sarif = {
        "$schema": "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/Schemata/sarif-schema-2.1.0.json",
        "version": "2.1.0",
        "runs": [{
            "tool": {
                "driver": {
                    "name": "frontend-audit",
                    "informationUri": "https://github.com/",
                    "rules": rules,
                }
            },
            "results": results,
        }],
    }
    return json.dumps(sarif, indent=2, ensure_ascii=False)


def format_markdown(result: dict) -> str:
    score = result.get("score") or {}
    by_sev = result.get("by_severity", {})
    findings = result.get("findings", [])
    lines = [
        "# 前端代码审查报告",
        "",
        "## 概览",
        f"- **项目**: {result.get('project_root', 'N/A')}",
        f"- **审查文件**: {result.get('files_scanned', 0)}",
        f"- **综合评分**: {score.get('overall', 'N/A')} ({score.get('grade', 'N/A')})",
        f"- **问题统计**: 错误 {by_sev.get('error', 0)} / 警告 {by_sev.get('warning', 0)} / 建议 {by_sev.get('info', 0)}",
        "",
        "## 评分详情（5 维度加权）",
        "| 维度 | 分数 | 权重 |",
        "|------|------|------|",
    ]
    dim_names = {
        "security": "安全",
        "reliability": "可靠性",
        "best-practice": "最佳实践",
        "arch": "架构",
        "deps": "依赖",
    }
    for cat, weight in CATEGORY_WEIGHTS.items():
        lines.append(f"| {dim_names[cat]} | {score.get(cat, 'N/A')} | {int(weight * 100)}% |")

    if result.get("degradation_notices"):
        lines.extend(["", "## ⚠️ 降级提示"])
        for n in result["degradation_notices"]:
            lines.append(f"- {n}")

    deps = result.get("deps_summary")
    if deps and deps.get("npm_available"):
        v = deps.get("vulnerabilities", {})
        lines.extend([
            "",
            "## 依赖安全（npm audit）",
            f"- 包数量: {deps.get('packages', 0)}",
            f"- 漏洞: critical {v.get('critical', 0)} / high {v.get('high', 0)} / "
            f"moderate {v.get('moderate', 0)} / low {v.get('low', 0)}（共 {v.get('total', 0)}）",
        ])

    triage = result.get("triage_summary")
    if triage:
        lines.extend([
            "",
            "## Triage（Triage→Verify 协议）",
            f"- deterministic（可直接报告）: {triage.get('deterministic', 0)}",
            f"- agent_verify（需 Agent 确认）: {triage.get('agent_verify', 0)}",
            f"- agent_only（Agent 调查）: {triage.get('agent_only', 0)}",
        ])

    lines.extend([
        "",
        "## 问题列表",
        "",
        "| 严重度 | 维度 | 规则 | 文件 | 行号 | 描述 | triage |",
        "|--------|------|------|------|------|------|--------|",
    ])
    for f in findings[:DEFAULT_MAX_ISSUES]:
        short = Path(f["file"]).name if f["file"] else ""
        msg = (f["message"] or "")[:80]
        lines.append(
            f"| {f['severity']} | {f['dimension']} | {f['rule']} | {short} | {f['line']} | {msg} | {f['triage']} |"
        )
    if not findings:
        lines.append("| - | - | - | - | - | 无问题发现 ✅ | - |")
    if len(findings) > DEFAULT_MAX_ISSUES:
        lines.append(f"\n（另有 {len(findings) - DEFAULT_MAX_ISSUES} 条问题未列出，使用 --format json 查看完整列表）")
    return "\n".join(lines)
