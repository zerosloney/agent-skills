#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wiki 健康检查 — 生成可读报告

检查项:
  1. 孤悬页面（无入链）
  2. 断链（[[目标页面]] 不存在）
  3. 缺少标签 / 摘要
  4. 缺少必要章节（相关页面、来源）
  5. 概念一致性（concepts_index 指向不存在的文件）
#
# OKF (Open Knowledge Format) v0.1 校验 — 2026-06 Google 规范
# 来源: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
#
# OKF 校验内容:
#   - 必填字段: type（OKF v0.1 §4.1 唯一必须字段）
#   - 状态合法性: status 必须为 draft | review | published | archived
#   - 置信度范围: confidence 必须在 0.0~1.0
#   - 时间戳格式: timestamp 必须符合 ISO 8601
#   - 引用有效性: related_articles 中引用的页面必须存在
#   - 推荐字段缺失警告: title, description, resource, tags, timestamp

用法:
  python scripts/lint.py
  WIKI_ROOT=<path> python scripts/lint.py
"""

import json
import os
import re
import sys
import yaml

# Windows console UTF-8 支持
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from collections import defaultdict
from datetime import datetime
from pathlib import Path

from _common import get_wiki_root as _get_wiki_root

WIKI_ROOT = _get_wiki_root()
PAGES_DIR = os.path.join(WIKI_ROOT, "pages")
SKILL_DIR = os.path.join(os.path.dirname(__file__), "..")
OKF_SCHEMA_PATH = os.path.join(SKILL_DIR, "schema", "okf-schema.yaml")

LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]")

# OKF v0.1 Required（spec §4.1: 只有 type 是必须的）
OKF_REQUIRED = {"type"}

# OKF v0.1 Recommended（spec §4.1, priority order）
OKF_RECOMMENDED = {"title", "description", "resource", "tags", "timestamp"}

# OKF 合法状态值（项目扩展）
OKF_STATUSES = {"draft", "review", "published", "archived"}


def _check_concepts() -> list[str]:
    """检查 concepts_index 一致性"""
    issues: list[str] = []
    meta_dir = Path(WIKI_ROOT) / "meta"
    concepts_path = meta_dir / "concepts_index.json"
    if not concepts_path.exists():
        return issues

    try:
        concepts = json.loads(concepts_path.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        issues.append("concepts_index.json 格式错误")
        return issues

    for name, info in concepts.items():
        concept_file = Path(WIKI_ROOT) / info.get("path", "")
        if not concept_file.exists():
            issues.append(f"概念 '{name}' 指向不存在的文件: {info.get('path')}")

    return issues


def _load_all_pages() -> tuple[list[Path], dict[str, str]]:
    pages = sorted(Path(PAGES_DIR).rglob("*.md"))
    pages = [p for p in pages if "_archived" not in p.parts]
    aliases: dict[str, str] = {}
    for p in pages:
        name = p.stem
        aliases[name] = str(p.relative_to(Path(PAGES_DIR)))
        if p.parent != Path(PAGES_DIR):
            aliases[p.parent.name] = str(p.relative_to(Path(PAGES_DIR).parent))
    return pages, aliases


# ============================================================
# OKF (Open Knowledge Format) 校验
# ============================================================

OKF_RE = re.compile(r"^---\n(.*?)\n---", re.DOTALL)


def _parse_okf_frontmatter(text: str) -> dict:
    """用 PyYAML 解析 frontmatter，支持嵌套结构和复杂类型。"""
    m = OKF_RE.search(text)
    if not m:
        return {}
    fm_text = m.group(1)
    try:
        fm = yaml.safe_load(fm_text)
        if fm is None:
            return {}
        if not isinstance(fm, dict):
            return {}
        return fm
    except yaml.YAMLError:
        # Fallback: 简易行解析
        fm: dict = {}
        for line in fm_text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                continue
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip()
            if val.startswith("[") and val.endswith("]"):
                items = [x.strip().strip('"').strip("'") for x in val[1:-1].split(",")]
                fm[key] = items
            else:
                val = val.strip('"').strip("'")
                fm[key] = val
        return fm


def _check_okf_page(fp: Path, aliases: dict[str, str]) -> list[str]:
    """对单个页面执行 OKF v0.1 校验，返回问题列表。"""
    issues: list[str] = []
    rel = str(fp.relative_to(Path(PAGES_DIR)))

    try:
        raw = fp.read_text("utf-8")
    except OSError:
        return issues

    fm = _parse_okf_frontmatter(raw)

    # 1. OKF Required: type（spec §4.1）
    # 也接受 entity_type 作为向后兼容别名
    type_val = fm.get("type", "") or fm.get("entity_type", "")
    if not type_val:
        issues.append(f"[{rel}] OKF v0.1 缺失必须字段: type")

    # 2. status 合法性检查（项目扩展字段，双读 status/okf_status）
    status = fm.get("status", fm.get("okf_status", "")).strip()
    if status and status not in OKF_STATUSES:
        issues.append(f"[{rel}] OKF status 非法值: '{status}'（应为 {OKF_STATUSES}）")

    # 3. confidence 范围检查 [0.0, 1.0]（项目扩展字段）
    conf_raw = fm.get("confidence", fm.get("okf_confidence", None))
    if conf_raw is not None:
        try:
            conf = float(conf_raw)
            if not (0.0 <= conf <= 1.0):
                issues.append(f"[{rel}] OKF confidence 越界: {conf}（应为 0.0~1.0）")
        except (ValueError, TypeError):
            issues.append(f"[{rel}] OKF confidence 非数字: '{conf_raw}'")

    # 4. timestamp 格式检查（ISO 8601）
    ts = fm.get("timestamp", "")
    if ts:
        ts_str = str(ts)
        # 兼容 ISO 8601 完整格式和简化 YYYY-MM-DD
        if not re.match(r"^\d{4}-\d{2}-\d{2}", ts_str):
            issues.append(f"[{rel}] OKF timestamp 格式错误: '{ts_str}'（应为 ISO 8601）")

    # 5. related_articles 引用检查（双读 related_articles/okf_related）
    related = fm.get("related_articles", fm.get("okf_related", []))
    if related:
        if isinstance(related, list):
            for item in related:
                if isinstance(item, dict):
                    mid = item.get("id", "").strip('"').strip("'")
                    if mid and mid not in aliases:
                        issues.append(f"[{rel}] OKF related_articles 引用不存在的页面: '{mid}'")
                elif isinstance(item, str):
                    mid = item.strip('"').strip("'").lstrip("pages/")
                    if mid and mid not in aliases:
                        issues.append(f"[{rel}] OKF related_articles 引用不存在的页面: '{item}'")
        else:
            related_text = str(related)
            id_matches = re.findall(r"id:\s*(\S+)", related_text)
            for mid in id_matches:
                mid = mid.strip('"').strip("'")
                if mid not in aliases:
                    issues.append(f"[{rel}] OKF related_articles 引用不存在的页面: '{mid}'")

    # 6. OKF 推荐字段缺失警告（warning 级别）
    for field in OKF_RECOMMENDED:
        if field not in fm or not fm[field]:
            # timestamp 可以来自旧 okf_modified
            if field == "timestamp" and fm.get("okf_modified"):
                continue
            issues.append(f"[{rel}] OKF 警告: 推荐字段缺失 '{field}'（非强制）")

    return issues


def _check_okf(aliases: dict[str, str]) -> list[str]:
    """对全 wiki 执行 OKF 校验"""
    issues: list[str] = []
    pages = sorted(Path(PAGES_DIR).rglob("*.md"))
    pages = [p for p in pages if "_archived" not in p.parts]
    for p in pages:
        issues.extend(_check_okf_page(p, aliases))
    return issues


def lint() -> dict:
    report: dict = {
        "total": 0,
        "orphans": [],
        "broken": [],
        "no_tag": [],
        "no_summary": [],
        "no_section": [],
        "concept_issues": [],
        "okf_issues": [],
        "incoming": defaultdict(list),
    }

    pages, aliases = _load_all_pages()
    report["total"] = len(pages)

    for fp in pages:
        rel = str(fp.relative_to(Path(PAGES_DIR)))
        try:
            raw = fp.read_text("utf-8")
        except OSError:
            continue

        lines = raw.split("\n")

        # 标签
        tag_ok = any("> 标签：" in ln and "`" in ln for ln in lines)
        if not tag_ok:
            report["no_tag"].append(rel)

        # 摘要（紧接标题后的 > 开头行，非标签）
        summary_ok = False
        for ln in lines:
            s = ln.strip()
            if s.startswith(">") and "标签：" not in s and len(s) > 4:
                summary_ok = True
                break
        if not summary_ok:
            report["no_summary"].append(rel)

        # 必要章节
        missing_sections = []
        # 匹配 "相关页面" 和 "来源" 章节，支持可选的中文或阿拉伯数字编号（如 "八、"、"1、"）
        if not re.search(r"^##\s*(\d+、|[一二三四五六七八九十]+、)?相关页面", raw, re.MULTILINE):
            missing_sections.append("相关页面")
        if not re.search(r"^##\s*(\d+、|[一二三四五六七八九十]+、)?来源", raw, re.MULTILINE):
            missing_sections.append("来源")
        if missing_sections:
            report["no_section"].append((rel, missing_sections))

        # 遍历链接
        page_name = fp.stem
        for m in LINK_RE.finditer(raw):
            target = m.group(1).strip()
            if target.startswith("http") or target.startswith("#"):
                continue
            if target not in aliases and target != page_name:
                report["broken"].append(f"{rel} → [[{target}]]")
            elif target != page_name:
                report["incoming"][target].append(rel)

    # 孤悬页面
    for fp in pages:
        name = fp.stem
        rel = str(fp.relative_to(Path(PAGES_DIR)))
        if name in ("index", "log") or rel == "index.md":
            continue
        if name not in report["incoming"]:
            report["orphans"].append(rel)

    # 概念一致性检查
    report["concept_issues"] = _check_concepts()

    # OKF (Open Knowledge Format) 校验 — Phase 3
    report["okf_issues"] = _check_okf(aliases)

    return report


def format_report(r: dict) -> str:
    now = datetime.now()
    lines = [
        "# 📊 Wiki 健康检查",
        "",
        f"> 时间: {now:%Y-%m-%d %H:%M}  |  页面: {r['total']}",
        "",
    ]

    if r["orphans"]:
        lines.append(f"## 🔗 孤悬页面（{len(r['orphans'])}）")
        lines.append("| 页面 | 建议方向 |")
        lines.append("|------|----------|")
        for p in sorted(r["orphans"]):
            lines.append(f"| [{p}](pages/{p}) | 分析后建议用户补充 |")
        lines.append("")

    if r["broken"]:
        lines.append(f"## 💔 断链（{len(r['broken'])}）")
        lines.append("")
        for item in sorted(r["broken"]):
            lines.append(f"- ❌ {item}")
        lines.append("")

    if r["no_tag"]:
        lines.append(f"## 🏷 缺少标签（{len(r['no_tag'])}）")
        lines.append("")
        for p in sorted(r["no_tag"]):
            lines.append(f"- {p}")
        lines.append("")

    if r["no_summary"]:
        lines.append(f"## 📝 缺少摘要（{len(r['no_summary'])}）")
        lines.append("")
        for p in sorted(r["no_summary"]):
            lines.append(f"- {p}")
        lines.append("")

    if r["no_section"]:
        lines.append(f"## 📋 缺少必要章节（{len(r['no_section'])}）")
        lines.append("")
        for p, sections in sorted(r["no_section"]):
            lines.append(f"- {p}: 缺少 {'、'.join(sections)}")
        lines.append("")

    if r["concept_issues"]:
        lines.append(f"## 🧩 概念一致性问题（{len(r['concept_issues'])}）")
        lines.append("")
        for issue in sorted(r["concept_issues"]):
            lines.append(f"- ❌ {issue}")
        lines.append("")

    if r["okf_issues"]:
        # OKF 问题分为两类：错误（error）和警告（warning）
        errors = [i for i in r["okf_issues"] if not i.startswith(f"[{r.get('_dummy', '')}] OKF 警告")]
        warnings = [i for i in r["okf_issues"] if i.endswith("(非强制)") or "推荐字段缺失" in i]
        # 简化分类：包含"警告"字样的为 warning，其余为 error
        errors = []
        warnings = []
        for i in r["okf_issues"]:
            if "警告" in i or "推荐字段" in i:
                warnings.append(i)
            else:
                errors.append(i)

        lines.append(f"## 📋 OKF 规范校验（{len(r['okf_issues'])}）")
        if errors:
            lines.append(f"### 错误（{len(errors)}）")
            lines.append("")
            for issue in sorted(errors):
                lines.append(f"- ❌ {issue}")
            lines.append("")
        if warnings:
            lines.append(f"### 警告（{len(warnings)}）")
            lines.append("")
            for issue in sorted(warnings):
                lines.append(f"- ⚠️  {issue}")
            lines.append("")

    ok = not any(r[k] for k in ("orphans", "broken", "no_tag", "no_summary", "no_section", "concept_issues"))
    if ok:
        lines.append("## ✅ 一切正常")
        lines.append("")
        lines.append("未发现问题。")

    # LLM 行动指南
    lines.append("")
    lines.append("---")
    lines.append("### 🤖 LLM 行动指南")
    lines.append("")
    if r["orphans"]:
        lines.append("1. 分析孤悬页面 — 是知识缺口（需补充素材）还是未被链接（补回链即可）？")
        lines.append("2. 对明显的知识缺口，**主动向用户建议**补充方向")
    if r["orphans"] and r["no_tag"]:
        lines.append("3. 对缺少标签的孤悬页面，优先归入 index.md 的分区")
    if r["broken"]:
        lines.append("4. 修复断链：删除无效 [[链接]] 或修正为正确页面名")
    if r["okf_issues"]:
        lines.append("5. OKF 校验问题 — 错误项需修复（缺失必填字段、非法状态、越界置信度），警告项可后续优化")
    if not ok:
        lines.append("6. 修复完成后，**再次运行 lint 确认闭环**")
    lines.append("")
    lines.append("### 🔍 矛盾检测（LLM 手动执行）")
    lines.append("")
    lines.append("上列检查由脚本自动完成。以下需 LLM 读取页面后人工判断：")
    lines.append("")
    lines.append("1. 同一概念在不同页面中是否有**不一致的描述**？")
    lines.append("2. 同一实体在不同来源中是否有**矛盾的数值/日期/事实**？")
    lines.append("3. 过时的页面是否需要更新？")
    lines.append("4. 是否存在**知识空白**（概念被引用但无独立页面）？")
    lines.append("")
    lines.append("如发现矛盾，在相关页面追加 `⚠️ 矛盾标注` 区块，并通知用户确认。")

    return "\n".join(lines)


def main() -> None:
    print(f"🔍 健康检查 | WIKI_ROOT={WIKI_ROOT}\n")
    r = lint()
    output = format_report(r)

    # 快速查阅
    dest = Path(WIKI_ROOT) / ".lint_report.md"
    dest.write_text(output, "utf-8")

    # 存档到 outputs/reports/
    archive_dir = Path(WIKI_ROOT) / "outputs" / "reports"
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive = archive_dir / f"{datetime.now():%Y-%m-%d}.md"
    archive.write_text(output, "utf-8")

    print(output)
    print(f"\n📄 快速查阅: {dest}")
    print(f"📄 存档: {archive}")


if __name__ == "__main__":
    main()
