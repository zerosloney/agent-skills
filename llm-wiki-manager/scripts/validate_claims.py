#!/usr/bin/env python3
"""
事实校验器 — 独立检查页面的来源标注和事实准确性

用途：
   提取页面中的事实性陈述（数字、日期、名称、具体声明），
   检查每条声明是否有来源标注 [source:...]，并在搜索索引中交叉验证。

用法:
    # 校验单个页面
    python scripts/validate_claims.py pages/redis-intro.md

    # 校验全部页面
    python scripts/validate_claims.py --all

    # 统计报告
    python scripts/validate_claims.py --stats

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import os
import re
import sys
import json
from pathlib import Path
from collections import defaultdict


from _common import get_wiki_root as _get_wiki_root


def _get_pages_dir():
    return os.path.join(_get_wiki_root(), "pages")


def _get_index_db():
    return os.path.join(_get_wiki_root(), "search_index.db")


# ============================================================================
# 事实性陈述提取
# ============================================================================

# 数字模式：百分比、金额、版本号、年份、数量
_NUMBER_PATTERNS = [
    r"\d+%",  # 百分比
    r"\d+\.\d+",  # 小数
    r"\$\d+(?:[.,]\d+)?[kKmMbB]?",  # 美元金额
    r"\d{4}-\d{1,2}-\d{1,2}",  # 日期
    r"v?\d+\.\d+\.\d+",  # 版本号
    r"(?:19|20)\d{2}",  # 年份
    r"\d+[,，]\d+",  # 大数（带千分位）
]

# 名称模式：专有名词、产品名、人名、缩写
_NAME_PATTERNS = [
    r"(?:[A-Z][a-z]+(?: [A-Z][a-z]+)*)",  # 英文专有名词
    r"(?:[A-Z]{2,})",  # 全大写缩写
]


def _extract_raw_claims(content: str) -> list[str]:
    """从页面 body 中提取疑似事实的原始片段"""
    claims = []
    lines = content.split("\n")
    for line in lines:
        line = line.strip()
        # 跳过空行、标题、代码块、链接、frontmatter
        if not line or line.startswith("#") or line.startswith("```") or line.startswith("---"):
            continue
        if line.startswith("//") or line.startswith("[//"):
            continue
        # 跳过纯列表项（但保留带数字的列表项）
        if re.match(r"^[-*]\s", line) and not re.search(r"\d", line):
            continue

        # 检查是否包含数字或专有名词
        has_number = any(re.search(p, line) for p in _NUMBER_PATTERNS)
        has_name = any(re.search(p, line) for p in _NAME_PATTERNS)
        if has_number or has_name:
            # 去重（相似的行合并）
            normalized = re.sub(r"\s+", " ", line)[:120]
            if normalized not in claims:
                claims.append(normalized)
    return claims


# ============================================================================
# 来源标注检查
# ============================================================================

_SOURCE_PATTERNS = {
    "has_source": re.compile(r"\[source:.*?\]|\[来源:.*?\]", re.IGNORECASE),
    "needs_verify": re.compile(r"\[需要验证\]|\[待确认\]", re.IGNORECASE),
    "opinion": re.compile(r"通常来说|一般来说|我认为|个人认为|可能|也许|大概"),
    "citation": re.compile(r"\[\[(.+?)\]\]"),  # wiki 内部链接
}


def _check_source(claim: str) -> dict:
    """检查一条 claim 的来源状态"""
    result = {
        "text": claim,
        "has_source": bool(_SOURCE_PATTERNS["has_source"].search(claim)),
        "needs_verify": bool(_SOURCE_PATTERNS["needs_verify"].search(claim)),
        "is_opinion": bool(_SOURCE_PATTERNS["opinion"].search(claim)),
        "has_wiki_link": bool(_SOURCE_PATTERNS["citation"].search(claim)),
    }
    return result


# ============================================================================
# 交叉验证（search_index.db）
# ============================================================================


def _cross_reference(claim: str) -> dict:
    """在搜索索引中查找 claim 的关键词是否出现在其他页面"""
    try:
        import sqlite3

        db_path = _get_index_db()
        if not Path(db_path).exists():
            return {"found_elsewhere": False, "note": "搜索索引不存在，跳过交叉验证"}

        # 提取关键词（中文词、英文词）
        terms = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z]\w+", claim.lower())
        terms = [t for t in terms if len(t) >= 2][:5]  # 最多 5 个关键词
        if not terms:
            return {"found_elsewhere": False, "note": "无可用于交叉验证的关键词"}

        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        try:
            # 检查 FTS5 索引
            has_fts = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wiki_fts'").fetchone()
            if not has_fts:
                return {"found_elsewhere": False, "note": "FTS5 索引不存在"}

            # 构建模糊查询
            query_parts = " OR ".join(terms)
            results = conn.execute(
                """
                SELECT wp.file_path, wp.title
                FROM wiki_fts wf
                JOIN wiki_pages wp ON wp.id = wf.rowid
                WHERE wiki_fts MATCH ?
                LIMIT 5
                """,
                (query_parts,),
            ).fetchall()

            if results:
                return {
                    "found_elsewhere": True,
                    "matches": [{"path": r["file_path"], "title": r["title"]} for r in results],
                    "note": f"在 {len(results)} 个页面中找到相关引用",
                }
            return {"found_elsewhere": False, "note": "索引中未找到相关引用"}
        finally:
            conn.close()
    except Exception as e:
        return {"found_elsewhere": False, "note": f"交叉验证异常: {e}"}


# ============================================================================
# 单页面校验
# ============================================================================


def validate_page(page_path: str) -> dict:
    """
    校验一个 wiki 页面。

    Args:
        page_path: 页面路径（绝对路径或相对于 pages/ 的相对路径）

    Returns:
        dict 包含校验报告
    """
    # 解析路径
    p = Path(page_path)
    if not p.exists():
        p = Path(_get_pages_dir()) / page_path
    if not p.exists():
        return {"error": f"页面不存在: {page_path}", "status": "error"}

    try:
        content = p.read_text(encoding="utf-8")
    except Exception as e:
        return {"error": f"读取失败: {e}", "status": "error"}

    # 提取文件名和标题
    file_name = p.name
    title_match = re.search(r"^# (.+)", content, re.MULTILINE)
    title = title_match.group(1).strip() if title_match else file_name.replace(".md", "")

    # 提取 frontmatter
    fm = {}
    fm_match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if fm_match:
        for line in fm_match.group(1).split("\n"):
            if ":" in line:
                k, v = line.split(":", 1)
                fm[k.strip()] = v.strip()

    # 提取 body（跳过 frontmatter）
    body = content
    if fm_match:
        body = content[fm_match.end() :].strip()

    # 提取 claims
    raw_claims = _extract_raw_claims(body)

    # 检查每个 claim
    claims_checked = []
    for c in raw_claims:
        source_info = _check_source(c)
        cross_info = _cross_reference(c) if not source_info["has_source"] else {"note": "已有来源标注，跳过交叉验证"}
        claims_checked.append({**source_info, "cross_ref": cross_info})

    # 统计
    total = len(claims_checked)
    with_source = sum(1 for c in claims_checked if c["has_source"])
    needs_verify = sum(1 for c in claims_checked if c["needs_verify"])
    is_opinion = sum(1 for c in claims_checked if c["is_opinion"])
    cross_found = sum(1 for c in claims_checked if c.get("cross_ref", {}).get("found_elsewhere"))
    unsourced = total - with_source - needs_verify - is_opinion

    report = {
        "status": "ok",
        "file": file_name,
        "title": title,
        "entity_type": fm.get("entity_type", "unknown"),
        "stats": {
            "total_claims": total,
            "with_source": with_source,
            "needs_verify": needs_verify,
            "opinion_statements": is_opinion,
            "cross_validated": cross_found,
            "unsourced": unsourced,
            "source_rate": round(with_source / total * 100, 1) if total > 0 else 0,
        },
        "claims": claims_checked[:20],  # 只返回前 20 条避免输出过长
    }
    return report


# ============================================================================
# 全量校验
# ============================================================================


def validate_all() -> dict:
    """校验所有页面"""
    pages = Path(_get_pages_dir())
    if not pages.exists():
        return {"error": f"pages 目录不存在: {_get_pages_dir()}", "status": "error"}

    files = sorted(pages.glob("**/*.md"))
    reports = []
    totals = defaultdict(int)

    for f in files:
        r = validate_page(str(f))
        if r["status"] == "ok":
            reports.append(r)
            for k, v in r["stats"].items():
                if isinstance(v, (int, float)):
                    totals[k] += v

    totals["pages_checked"] = len(reports)
    if totals.get("total_claims", 0) > 0:
        totals["source_rate"] = round(totals["with_source"] / totals["total_claims"] * 100, 1)
    else:
        totals["source_rate"] = 0

    return {"status": "ok", "totals": dict(totals), "reports": reports}


# ============================================================================
# CLI 主入口
# ============================================================================


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/validate_claims.py <page_path> | --all | --stats")
        print()
        print("示例:")
        print("  python scripts/validate_claims.py pages/redis-intro.md")
        print("  python scripts/validate_claims.py --all")
        print("  python scripts/validate_claims.py --stats")
        sys.exit(1)

    arg = sys.argv[1]

    if arg == "--all":
        result = validate_all()
        if result["status"] != "ok":
            print(f"❌ {result['error']}")
            sys.exit(1)

        t = result["totals"]
        print(f"\n📋 全量校验报告 ({t['pages_checked']} 页)")
        print(f"{'=' * 50}")
        print(f"  事实性陈述总数: {t['total_claims']}")
        print(f"  有来源标注:     {t['with_source']} ({t['source_rate']}%)")
        print(f"  需验证标记:     {t['needs_verify']}")
        print(f"  观点性陈述:     {t['opinion_statements']}")
        print(f"  交叉验证通过:   {t['cross_validated']}")
        print(f"  无来源:         {t['unsourced']}")

        print("\n📄 各页面详情:")
        for r in result["reports"]:
            s = r["stats"]
            flag = "✅" if s["source_rate"] >= 60 else "⚠️" if s["source_rate"] >= 30 else "❌"
            print(f"  {flag} [{r['entity_type']}] {r['file']}")
            print(
                f"     陈述 {s['total_claims']} | 来源 {s['with_source']} ({s['source_rate']}%) | 待验证 {s['needs_verify']}"
            )
    elif arg == "--stats":
        result = validate_all()
        if result["status"] != "ok":
            print(f"❌ {result['error']}")
            sys.exit(1)
        t = result["totals"]
        print(json.dumps(t, ensure_ascii=False, indent=2))
    else:
        result = validate_page(arg)
        if result["status"] != "ok":
            print(f"❌ {result['error']}")
            sys.exit(1)

        s = result["stats"]
        flag = "✅" if s["source_rate"] >= 60 else "⚠️" if s["source_rate"] >= 30 else "❌"
        print(f"\n{flag} 校验: {result['file']} ({result['title']})")
        print(f"  实体类型: {result['entity_type']}")
        print(f"{'=' * 50}")
        print(f"  事实性陈述:     {s['total_claims']}")
        print(f"  有来源标注:     {s['with_source']}")
        print(f"  需验证标记:     {s['needs_verify']}")
        print(f"  观点性陈述:     {s['opinion_statements']}")
        print(f"  交叉验证通过:   {s['cross_validated']}")
        print(f"  无来源:         {s['unsourced']}")
        print(f"  来源覆盖率:     {s['source_rate']}%")

        print("\n📝 陈述详情:")
        for c in result["claims"][:10]:
            status = ""
            if c["has_source"]:
                status += "📌[有来源]"
            if c["needs_verify"]:
                status += "❓[待验证]"
            if c["is_opinion"]:
                status += "💭[观点]"
            if not status:
                status = "⚠️[无来源]"
            print(f"  {status} {c['text'][:80]}")

        if result["stats"]["unsourced"] > 0:
            print(f"\n💡 建议：{result['stats']['unsourced']} 条无来源陈述，建议添加 [source:...] 标注")


if __name__ == "__main__":
    main()
