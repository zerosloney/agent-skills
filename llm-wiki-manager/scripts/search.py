#!/usr/bin/env python3
"""Wiki 搜索 — 基于 FTS5 全文索引

支持两种模式，自动适配 wiki 规模：
  1. grep 模式（默认）：直接对 pages/*.md 做关键词匹配，无需索引
  2. --rebuild: 扫描 pages/ 构建 FTS5 搜索索引（首次或大量变更后执行）

用法:
  # 小型 wiki：直接搜
  python scripts/search.py "异步 并发"

  # 中大型 wiki：先建索引再搜
  python scripts/search.py --rebuild
  python scripts/search.py --query "Rust 异步"

  # 指定 wiki 目录
  WIKI_ROOT=<path> python scripts/search.py "关键词"
"""

import os
import re
import sys
from pathlib import Path


from _common import get_wiki_root as _get_wiki_root

WIKI_ROOT = _get_wiki_root()
PAGES_DIR = os.path.join(WIKI_ROOT, "pages")


# -- grep 模式（小型 wiki / 无索引降级） --


def grep_search(query: str) -> list[tuple[str, str]]:
    """文件级关键词匹配（不依赖索引）"""
    keywords = [k.strip().lower() for k in query.split() if k.strip()]
    if not keywords:
        return []

    pages = Path(PAGES_DIR)
    if not pages.exists():
        return []

    out: list[tuple[str, str]] = []
    for fp in sorted(pages.rglob("*.md")):
        if "_archived" in fp.parts:
            continue
        rel = str(fp.relative_to(pages)).replace("\\", "/")
        try:
            raw = fp.read_text("utf-8", errors="replace").lower()
        except OSError:
            continue
        if any(k not in raw for k in keywords):
            continue
        title = re.search(r"^# (.+)", raw, re.MULTILINE)
        out.append((rel, title.group(1).strip() if title else rel))
    return out


# -- FTS5 引擎模式（中大型 wiki） --


def _ensure_fts5_index() -> bool:
    """检查 SQLite 索引是否存在"""
    db_path = os.path.join(WIKI_ROOT, "search_index.db")
    return Path(db_path).exists()


def fts5_search(query: str, limit: int = 20) -> list[dict]:
    """使用 search_engine 进行 FTS5 搜索（委托 search_engine.search_articles）"""
    sys.path.insert(0, os.path.dirname(__file__))
    from search_engine import search_articles as _engine_search

    return _engine_search(query, limit=limit)


def rebuild_index() -> None:
    """重建 FTS5 + 倒排索引"""
    sys.path.insert(0, os.path.dirname(__file__))
    from search_engine import rebuild as engine_rebuild

    print("重建搜索索引（FTS5 + 倒排）")
    engine_rebuild()
    print("索引重建完成")


# -- 主入口 --


def main() -> None:
    if "--rebuild" in sys.argv:
        rebuild_index()
        return

    query: str | None = None
    if "--query" in sys.argv:
        i = sys.argv.index("--query")
        query = sys.argv[i + 1] if i + 1 < len(sys.argv) else ""
    elif len(sys.argv) >= 2 and not sys.argv[1].startswith("--"):
        query = sys.argv[1]

    if not query:
        print("用法: python search.py <关键词>")
        return

    # 1) 优先 FTS5 引擎
    if _ensure_fts5_index():
        hits = fts5_search(query)
        if hits:
            print(f"索引搜索: {query}  |  {len(hits)} 个结果\n")
            for hit in hits:
                path = hit.get("file_path", "?")
                title = hit.get("title", Path(path).stem if path != "?" else "?")
                try:
                    rel = str(Path(path).relative_to(PAGES_DIR)).replace("\\", "/")
                except (ValueError, OSError):
                    rel = path
                print(f"  {title}  ({rel})")
            return

    # 2) 降级到 grep
    hits = grep_search(query)
    if hits:
        print(f"grep 搜索: {query}  |  {len(hits)} 个匹配页面\n")
        for rel, title in hits:
            print(f"  {title}  ({rel})")
    else:
        print(f"搜索: {query}")
        print("  未匹配到页面")
        if not _ensure_fts5_index():
            print("  提示: 页面较多时可执行 --rebuild 建索引，搜索更高效")


if __name__ == "__main__":
    main()
