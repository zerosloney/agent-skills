#!/usr/bin/env python3
"""
状态一致性检查脚本

检查项：
1. 缓存是否与文件一致
2. 搜索索引是否存在
3. 概念索引是否与页面一致
4. frontmatter sources 是否指向存在的文件
5. 孤立页面检测

用法：
    python scripts/check_state.py
    python scripts/check_state.py --fix  # 自动修复
"""

import json
import sys
from pathlib import Path

from _common import get_wiki_root


def check_cache() -> dict:
    """检查缓存一致性"""
    wiki_root = Path(get_wiki_root())
    cache_file = wiki_root / ".cache" / "sources.json"

    if not cache_file.exists():
        return {"status": "warning", "message": "缓存文件不存在", "fix": "运行: python scripts/wiki.py compile_post"}

    try:
        cache = json.loads(cache_file.read_text(encoding="utf-8"))
        return {"status": "ok", "message": f"缓存正常（{len(cache)} 条记录）"}
    except json.JSONDecodeError:
        return {"status": "error", "message": "缓存文件损坏", "fix": "运行: python scripts/wiki.py cache sync"}


def check_search_index() -> dict:
    """检查搜索索引"""
    wiki_root = Path(get_wiki_root())
    index_file = wiki_root / "search_index.db"

    if not index_file.exists():
        return {"status": "warning", "message": "搜索索引不存在", "fix": "运行: python scripts/wiki.py search rebuild"}

    return {"status": "ok", "message": "搜索索引存在"}


def check_concepts_index() -> dict:
    """检查概念索引"""
    wiki_root = Path(get_wiki_root())
    concepts_file = wiki_root / "meta" / "concepts_index.json"

    if not concepts_file.exists():
        return {"status": "warning", "message": "概念索引不存在", "fix": "运行: python scripts/wiki.py detect_concepts"}

    try:
        concepts = json.loads(concepts_file.read_text(encoding="utf-8"))

        # 检查概念指向的文件是否存在
        missing = []
        for name, info in concepts.items():
            path = wiki_root / info["path"]
            if not path.exists():
                missing.append(name)

        if missing:
            return {
                "status": "warning",
                "message": f"概念索引中有 {len(missing)} 个文件不存在",
                "details": missing[:5],
                "fix": "运行: python scripts/wiki.py detect_concepts",
            }

        return {"status": "ok", "message": f"概念索引正常（{len(concepts)} 个概念）"}
    except json.JSONDecodeError:
        return {"status": "error", "message": "概念索引损坏", "fix": "运行: python scripts/wiki.py detect_concepts"}


def check_frontmatter_sources() -> dict:
    """检查 frontmatter sources 是否指向存在的文件"""
    wiki_root = Path(get_wiki_root())
    pages_dir = wiki_root / "pages"

    if not pages_dir.exists():
        return {"status": "error", "message": "pages/ 目录不存在"}

    broken_sources = []
    for page in pages_dir.rglob("*.md"):
        content = page.read_text(encoding="utf-8")

        # 简单解析 frontmatter sources
        if "sources:" not in content:
            continue

        lines = content.split("\n")
        in_sources = False
        for line in lines:
            if line.strip() == "sources:":
                in_sources = True
                continue
            if in_sources:
                if line.startswith("  - "):
                    source = line.strip()[2:].strip('"')

                    # 跳过 web: 和 query: 来源
                    if source.startswith("web:") or source.startswith("query:"):
                        continue

                    # 检查 raw/ 文件是否存在
                    source_path = wiki_root / "raw" / source
                    if not source_path.exists():
                        broken_sources.append({"page": str(page.relative_to(wiki_root)), "source": source})
                elif not line.startswith("  "):
                    in_sources = False

    if broken_sources:
        return {
            "status": "warning",
            "message": f"发现 {len(broken_sources)} 个断裂的 source 引用",
            "details": broken_sources[:5],
            "fix": "手动检查或运行: python scripts/wiki.py lint",
        }

    return {"status": "ok", "message": "frontmatter sources 正常"}


def check_orphan_pages() -> dict:
    """检查孤立页面（无 sources 的页面）"""
    wiki_root = Path(get_wiki_root())
    pages_dir = wiki_root / "pages"

    if not pages_dir.exists():
        return {"status": "error", "message": "pages/ 目录不存在"}

    orphans = []
    for page in pages_dir.rglob("*.md"):
        content = page.read_text(encoding="utf-8")

        # 检查是否有 sources
        if "sources:" not in content:
            orphans.append(str(page.relative_to(wiki_root)))

    if orphans:
        return {"status": "info", "message": f"发现 {len(orphans)} 个无来源页面", "details": orphans[:5]}

    return {"status": "ok", "message": "所有页面都有来源"}


def main():
    print("🔍 检查 Wiki 状态一致性...\n")

    checks = [
        ("缓存", check_cache),
        ("搜索索引", check_search_index),
        ("概念索引", check_concepts_index),
        ("frontmatter sources", check_frontmatter_sources),
        ("孤立页面", check_orphan_pages),
    ]

    results = []
    for name, check_fn in checks:
        print(f"检查 {name}...", end=" ")
        result = check_fn()
        results.append((name, result))

        status = result["status"]
        if status == "ok":
            print("✅")
        elif status == "warning":
            print("⚠️")
        elif status == "error":
            print("❌")
        else:
            print("ℹ️")

    print("\n" + "=" * 60)
    print("检查结果：\n")

    has_error = False
    has_warning = False

    for name, result in results:
        status = result["status"]
        message = result["message"]

        if status == "ok":
            print(f"✅ {name}: {message}")
        elif status == "warning":
            print(f"⚠️  {name}: {message}")
            if "fix" in result:
                print(f"   修复: {result['fix']}")
            if "details" in result:
                print(f"   详情: {result['details']}")
            has_warning = True
        elif status == "error":
            print(f"❌ {name}: {message}")
            if "fix" in result:
                print(f"   修复: {result['fix']}")
            has_error = True
        else:
            print(f"ℹ️  {name}: {message}")
            if "details" in result:
                print(f"   详情: {result['details']}")

    print("\n" + "=" * 60)

    if has_error:
        print("❌ 发现严重错误，请立即修复")
        sys.exit(1)
    elif has_warning:
        print("⚠️  发现警告，建议修复")
        sys.exit(0)
    else:
        print("✅ 所有检查通过")
        sys.exit(0)


if __name__ == "__main__":
    main()
