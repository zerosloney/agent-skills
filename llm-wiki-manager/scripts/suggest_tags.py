#!/usr/bin/env python3
"""
Tags / Concepts / Domains 自动建议 — 基于 jieba 分词 + FTS5 索引 + 概念匹配

根据文章正文内容，自动建议：
  1. tags（从 FTS5 已索引文章的 tags 字段聚合）
  2. 概念链接（从 concepts_index.json 匹配）
  3. domains（从已有文章的 frontmatter 统计）

用法:
    # 对指定页面做建议
    python scripts/suggest_tags.py pages/rust-async.md

    # 从 stdin 读取内容
    cat pages/rust-async.md | python scripts/suggest_tags.py --stdin

    # JSON 输出（给其他工具消费）
    python scripts/suggest_tags.py pages/rust-async.md --json

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import argparse
import json
import os
import re
import sqlite3
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Optional

from _common import get_wiki_root as _get_wiki_root
from index import load_concepts_index


# ============================================================================
# 停用词表（中文 + 英文常见无意义词）
# ============================================================================

_STOPWORDS: set[str] = {
    # 中文停用词
    "的",
    "了",
    "是",
    "在",
    "有",
    "和",
    "与",
    "也",
    "就",
    "都",
    "而",
    "及",
    "但",
    "或",
    "被",
    "把",
    "对",
    "为",
    "从",
    "以",
    "到",
    "这",
    "那",
    "其",
    "它",
    "之",
    "将",
    "不",
    "很",
    "更",
    "最",
    "等",
    "中",
    "上",
    "下",
    "会",
    "能",
    "可",
    "要",
    "让",
    "用",
    "通过",
    "进行",
    "实现",
    "包括",
    "其中",
    "以及",
    "使用",
    "可以",
    "需要",
    "基于",
    "相关",
    "作为",
    "一个",
    "这个",
    "那个",
    "这些",
    "那些",
    "每个",
    "所有",
    "一些",
    "没有",
    "不是",
    "如果",
    "因为",
    "所以",
    "但是",
    "然而",
    "虽然",
    "例如",
    "比如",
    "通常",
    "一般",
    "主要",
    "分为",
    "根据",
    "定义",
    "方式",
    "方法",
    "过程",
    "程度",
    "方面",
    "部分",
    "情况",
    "结果",
    "影响",
    "作用",
    "特点",
    "特性",
    "结构",
    "功能",
    "关系",
    "机制",
    "原理",
    "思想",
    "问题",
    "方案",
    "边界",
    "场景",
    "表示",
    "代表",
    "称为",
    "用于",
    "位于",
    "来自",
    "运行",
    "具有",
    "提供",
    "支持",
    "一种",
    "两种",
    "多个",
    "不同",
    "相同",
    "第一",
    "第二",
    "假设",
    # 英文停用词
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "do",
    "does",
    "did",
    "will",
    "would",
    "shall",
    "should",
    "may",
    "might",
    "can",
    "could",
    "must",
    "this",
    "that",
    "these",
    "those",
    "and",
    "or",
    "but",
    "if",
    "then",
    "else",
    "when",
    "where",
    "how",
    "what",
    "which",
    "who",
    "whom",
    "with",
    "without",
    "for",
    "to",
    "by",
    "from",
    "of",
    "in",
    "on",
    "at",
    "as",
    "not",
    "no",
    "so",
    "too",
    "very",
    "just",
    "about",
    "also",
    "only",
    "more",
    "most",
    "some",
    "any",
    "each",
    "every",
    "both",
    "all",
    "other",
    "such",
    "into",
    "over",
    "under",
    "after",
    "before",
    "between",
    "through",
    "during",
    "because",
    "than",
    "it",
    "its",
    "they",
    "them",
    "their",
    "we",
    "our",
    "he",
    "she",
    "his",
    "her",
    "my",
    "your",
    "our",
    "us",
    "up",
    "out",
    "off",
    "down",
    "about",
}


# ============================================================================
# 基础工具
# ============================================================================


def _parse_frontmatter(content: str) -> dict:
    """解析 YAML frontmatter（无需 yaml 库即可解析基本字段）"""
    if not content.startswith("---"):
        return {}

    end = content.find("\n---", 3)
    if end < 0:
        return {}

    fm_str = content[3:end]
    frontmatter: dict = {}

    try:
        import yaml

        frontmatter = yaml.safe_load(fm_str) or {}
    except ImportError:
        # 手动解析简单字段
        for line in fm_str.split("\n"):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                # 处理列表: [a, b, c]
                if value.startswith("[") and value.endswith("]"):
                    value = [v.strip().strip('"').strip("'") for v in value[1:-1].split(",")]
                if key:
                    frontmatter[key] = value
    except Exception:
        pass

    return frontmatter


def _extract_body(content: str) -> str:
    """提取 markdown body（跳过 frontmatter 和标题 #）"""
    body = content
    if body.startswith("---"):
        end = body.find("\n---", 3)
        if end > 0:
            body = body[end + 5 :]
    body = re.sub(r"^#\s+.*$", "", body, flags=re.MULTILINE)
    return body.strip()


def _get_jieba():
    """延迟加载 jieba"""
    import jieba as _j

    _j.setLogLevel(_j.logging.INFO)
    return _j


def _tokenize_for_fts5(text: str) -> str:
    """jieba 分词 + 保留非 CJK 原文，空格连接供 FTS5 unicode61 消费。"""
    jieba = _get_jieba()
    parts = []
    for segment in re.split(r"([\u4e00-\u9fff]+)", text):
        if re.match(r"[\u4e00-\u9fff]+", segment):
            parts.extend(jieba.lcut(segment))
        elif segment.strip():
            parts.append(segment)
    return " ".join(parts)


# ============================================================================
# 关键词提取
# ============================================================================


def extract_keywords(text: str, top_n: int = 20) -> list[tuple[str, int]]:
    """
    从正文提取关键词。
    返回: [(关键词, TF 频次), ...] 按频次降序。
    """
    if not text.strip():
        return []

    jieba = _get_jieba()
    words = jieba.lcut(text)

    tf = Counter[str]()
    for w in words:
        w = w.strip().lower()
        if not w:
            continue
        if w in _STOPWORDS:
            continue
        if len(w) < 2:
            continue
        if w.isdigit():
            continue
        # 过滤纯标点
        if re.match(r"^[^\w\u4e00-\u9fff]+$", w):
            continue
        tf[w] += 1

    return tf.most_common(top_n)


# ============================================================================
# 概念匹配
# ============================================================================


def suggest_concepts(
    keywords: list[str],
    concepts_index: dict,
    existing_names: set[str],
    top_n: int = 10,
) -> list[dict]:
    """
    关键词 → 概念匹配。
    返回: [{name, path, score, matched_term}]
    score ∈ [0, 1] 归一化。
    """
    if not concepts_index:
        return []

    raw: list[dict] = []
    for term, _tf in keywords:
        for concept_name, info in concepts_index.items():
            if concept_name in existing_names:
                continue
            all_names = [concept_name] + info.get("aliases", [])
            for alias in all_names:
                alias_lower = alias.lower().strip()
                term_lower = term.lower().strip()
                if not term_lower or not alias_lower:
                    continue
                # 精确包含匹配
                if term_lower in alias_lower or alias_lower in term_lower:
                    # score: 子串长度 / 概念名长度（越长越相关）
                    longer = max(len(term_lower), len(alias_lower))
                    shorter = min(len(term_lower), len(alias_lower))
                    raw.append(
                        {
                            "name": concept_name,
                            "path": info.get("path", ""),
                            "score": round(shorter / longer, 2) if longer > 0 else 1.0,
                            "matched_term": term,
                        }
                    )
                    break  # 一个概念只匹配一次

    # 聚合评分（同一个概念可能被多个关键词匹配）
    agg: dict[str, dict] = {}
    for r in raw:
        name = r["name"]
        if name not in agg:
            agg[name] = {"name": name, "path": r["path"], "score": 0.0, "matched_terms": []}
        agg[name]["score"] = max(agg[name]["score"], r["score"])
        agg[name]["matched_terms"].append(r["matched_term"])

    sorted_results = sorted(agg.values(), key=lambda x: -x["score"])
    return sorted_results[:top_n]


# ============================================================================
# Tags 建议（基于 FTS5 已有文章的 tags 聚合）
# ============================================================================


def _get_db():
    """获取 SQLite 数据库连接"""
    WIKI_ROOT = _get_wiki_root()
    path = os.path.join(WIKI_ROOT, "search_index.db")
    if not Path(path).exists():
        return None
    import sqlite3

    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    # 检查表是否存在
    tables = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='wiki_fts'").fetchall()
    if not tables:
        conn.close()
        return None
    return conn


def aggregate_tags_from_fts5(
    keywords: list[str],
    db,
    existing_tags: set[str],
    top_n: int = 10,
) -> list[dict]:
    """
    对每个关键词 FTS5 搜索 → 聚合命中文章的 tags。
    返回: [{tag, score, matched_terms}]
    score: 0~1 (出现频率 / 最大频率)
    """
    if db is None:
        return []

    tag_counter: Counter[str] = Counter()
    tag_terms: dict[str, set[str]] = defaultdict(set)

    for term, _tf in keywords:
        tokenized = _tokenize_for_fts5(term)
        if not tokenized.strip():
            continue
        try:
            rows = db.execute(
                """
                SELECT tags FROM wiki_fts
                WHERE wiki_fts MATCH ?
                LIMIT 20
                """,
                (tokenized,),
            ).fetchall()
        except Exception:
            continue

        for row in rows:
            tags_str = row[0] if isinstance(row, sqlite3.Row) else row[0]
            if not tags_str:
                continue
            # tags 在 FTS5 中是空格分隔
            article_tags = tags_str.split()
            for tag in article_tags:
                tag = tag.strip()
                if not tag or tag in existing_tags:
                    continue
                tag_counter[tag] += 1
                tag_terms[tag].add(term)

    if not tag_counter:
        return []

    max_freq = max(tag_counter.values())
    results = []
    for tag, freq in tag_counter.most_common(top_n):
        results.append(
            {
                "tag": tag,
                "score": round(freq / max_freq, 2),
                "matched_terms": sorted(tag_terms[tag]),
            }
        )
    return results


# ============================================================================
# Domains 建议（基于已有文章的 frontmatter）
# ============================================================================


def _collect_existing_domains() -> Counter[str]:
    """扫描 WIKI_ROOT/pages/ 下所有 markdown 文件，收集 domains。"""
    WIKI_ROOT = _get_wiki_root()
    pages_dir = Path(WIKI_ROOT) / "pages"
    if not pages_dir.exists():
        return Counter()

    counter: Counter[str] = Counter()
    for md_file in pages_dir.rglob("*.md"):
        try:
            content = md_file.read_text("utf-8", errors="replace")
            fm = _parse_frontmatter(content)
            domains = fm.get("domains", [])
            if isinstance(domains, list):
                for d in domains:
                    counter[d.strip()] += 1
            elif isinstance(domains, str):
                counter[domains.strip()] += 1
        except Exception:
            continue
    return counter


def suggest_domains(
    keywords: list[str],
    domain_counter: Counter[str],
    existing_domains: set[str],
    top_n: int = 5,
) -> list[dict]:
    """
    关键词 → domains 匹配。
    返回: [{domain, score}] 按匹配度排序。
    """
    if not domain_counter:
        return []

    scored: list[dict] = []
    for domain, freq in domain_counter.most_common(50):
        if domain in existing_domains:
            continue
        domain_lower = domain.lower()
        # 检查关键词是否与 domain 相关
        match_score = 0.0
        for term, _tf in keywords:
            term_lower = term.lower()
            if term_lower in domain_lower or domain_lower in term_lower:
                match_score = max(match_score, 0.8)
            # 部分匹配
            elif len(term_lower) >= 2 and term_lower in domain_lower:
                match_score = max(match_score, 0.5)

        if match_score > 0:
            # 综合：匹配度 + 流行度因子
            pop_factor = min(freq / 5, 1.0) * 0.2
            scored.append({"domain": domain, "score": round(match_score + pop_factor, 2), "frequency": freq})

    scored.sort(key=lambda x: -x["score"])
    return scored[:top_n]


# ============================================================================
# 主建议流程
# ============================================================================


def suggest_all(content: str, file_path: Optional[str] = None) -> dict:
    """
    对 markdown 内容进行完整建议。
    返回: {tags: [...], concepts: [...], domains: [...], keywords: [...]}
    """
    # 1. 解析 frontmatter
    fm = _parse_frontmatter(content)
    existing_tags = set(fm.get("tags", []) or [])
    existing_domains = set(fm.get("domains", []) or [])
    existing_links: set[str] = set()
    # 从 body 中提取已有 [[链接]]
    for m in re.finditer(r"\[\[([^\]]+)\]\]", content):
        existing_links.add(m.group(1))

    # 2. 提取关键词
    body = _extract_body(content)
    keywords = extract_keywords(body)
    if not keywords:
        return {"tags": [], "concepts": [], "domains": [], "keywords": [], "stats": {}}

    # 3. Tags 建议
    db = _get_db()
    tags = aggregate_tags_from_fts5(keywords, db, existing_tags)

    # 4. 概念建议
    concepts_index = load_concepts_index()
    concepts = suggest_concepts(keywords, concepts_index, existing_links)

    # 5. Domains 建议
    domain_counter = _collect_existing_domains()
    domains = suggest_domains(keywords, domain_counter, existing_domains)

    return {
        "tags": tags,
        "concepts": concepts,
        "domains": domains,
        "keywords": [{"word": w, "freq": f} for w, f in keywords],
        "stats": {
            "keyword_count": len(keywords),
            "existing_tags": list(existing_tags),
            "existing_domains": list(existing_domains),
            "existing_links_count": len(existing_links),
        },
    }


# ============================================================================
# 格式化输出
# ============================================================================


def _format_human(result: dict) -> str:
    """格式化为人类可读的输出"""
    lines: list[str] = []
    keywords = result.get("keywords", [])
    tags = result.get("tags", [])
    concepts = result.get("concepts", [])
    domains = result.get("domains", [])

    # 关键词
    if keywords:
        top_kw = [kw["word"] for kw in keywords[:10]]
        lines.append(f"📊 关键词 (top-{len(top_kw)}): {' · '.join(top_kw)}")
        lines.append("")

    # Tags 建议
    if tags:
        lines.append("📌 Tags 建议 —")
        for i, t in enumerate(tags, 1):
            star = "★" if t["score"] >= 0.6 else "☆"
            terms = ", ".join(t["matched_terms"][:3])
            lines.append(f"  {star} {t['tag']}  (score={t['score']:.2f}, from: {terms})")
        lines.append("")
    else:
        lines.append("📌 Tags 建议 — (暂无建议)")
        lines.append("")

    # 概念建议
    if concepts:
        lines.append("🔗 概念链接建议 —")
        for i, c in enumerate(concepts, 1):
            star = "★" if c["score"] >= 0.7 else "☆"
            terms = ", ".join(c["matched_terms"][:3])
            path = c.get("path", "")
            if path:
                lines.append(f"  {star} [[{c['name']}]]  (score={c['score']:.2f}, from: {terms})")
            else:
                lines.append(f"  {star} {c['name']}  (score={c['score']:.2f}, from: {terms})")
        lines.append("")
    else:
        lines.append("🔗 概念链接建议 — (暂无建议)")
        lines.append("")

    # Domains 建议
    if domains:
        lines.append("🏷️ Domains 建议 —")
        for i, d in enumerate(domains, 1):
            star = "★" if d["score"] >= 0.7 else "☆"
            lines.append(f"  {star} {d['domain']}  (score={d['score']:.2f})")
        lines.append("")
    else:
        lines.append("🏷️ Domains 建议 — (暂无建议)")

    return "\n".join(lines)


# ============================================================================
# CLI 入口
# ============================================================================


def main():
    parser = argparse.ArgumentParser(
        description="Tags / Concepts / Domains 自动建议",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/suggest_tags.py pages/rust-async.md
  cat pages/rust-async.md | python scripts/suggest_tags.py --stdin
  python scripts/suggest_tags.py pages/rust-async.md --json
        """,
    )
    parser.add_argument("file", nargs="?", help="markdown 文件路径（相对于 WIKI_ROOT 或绝对路径）")
    parser.add_argument("--stdin", action="store_true", help="从 stdin 读取 markdown 内容")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式")
    args = parser.parse_args()

    if not args.file and not args.stdin:
        parser.print_help()
        sys.exit(1)

    if args.stdin:
        content = sys.stdin.read()
        file_path = None
    else:
        file_path = args.file
        # 1. 绝对路径
        if os.path.isabs(file_path):
            full_paths_to_try = [file_path]
        else:
            # 2. 先试相对于 WIKI_ROOT，再试 CWD
            full_paths_to_try = [
                os.path.join(_get_wiki_root(), file_path),
                os.path.join(os.getcwd(), file_path),
            ]
        full_path = None
        for p in full_paths_to_try:
            if os.path.exists(p):
                full_path = p
                break
        if full_path is None:
            print(f"❌ 文件不存在 (已尝试: {', '.join(full_paths_to_try)})", file=sys.stderr)
            sys.exit(1)
        content = Path(full_path).read_text("utf-8", errors="replace")

    result = suggest_all(content, file_path)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(_format_human(result))


if __name__ == "__main__":
    main()
