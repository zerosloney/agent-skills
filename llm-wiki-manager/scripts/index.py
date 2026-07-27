#!/usr/bin/env python3
"""LLM Wiki 元数据索引管理

管理三个核心索引：
1. concepts_index.json — 概念名 → 路径 + 别名 + 摘要
2. source_map.json — SHA256 → 源文件 + 生成的页面
3. filename_index.json — 文件名 stem → SHA256 列表（重名检测）

用法:
    # 查看概念索引
    python scripts/index.py concepts-show

    # 动态重算 article_count
    python scripts/index.py concepts-recalc

    # 添加/更新概念
    python scripts/index.py concepts-add "AI Agent" --path "concepts/ai-agent.md" --aliases "智能代理,AI代理"

    # 匹配相关概念
    python scripts/index.py concepts-match "数字平台"

    # 查看源文件映射
    python scripts/index.py source-show

    # 查看文件名索引
    python scripts/index.py filename-show

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


from _common import get_wiki_root as _get_wiki_root

WIKI_ROOT = _get_wiki_root()
META_DIR = os.path.join(WIKI_ROOT, "meta")


def _read_json(path: str) -> dict:
    if Path(path).exists():
        try:
            return json.loads(Path(path).read_text("utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _write_json(data: dict, path: str) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2), "utf-8")


# ============================================================================
# concepts_index.json — 概念索引
# ============================================================================

CONCEPTS_INDEX_PATH = os.path.join(META_DIR, "concepts_index.json")


def load_concepts_index() -> dict:
    """加载概念索引：{concept_name: {path, aliases, summary, article_count}}"""
    return _read_json(CONCEPTS_INDEX_PATH)


def save_concepts_index(index: dict) -> None:
    _write_json(index, CONCEPTS_INDEX_PATH)


def update_concept(
    concept_name: str,
    concept_path: str,
    summary: str = "",
    aliases: list[str] | None = None,
    index: dict | None = None,
) -> dict:
    """添加或更新一个概念（article_count 由下次 scan 动态计算）"""
    if index is None:
        index = load_concepts_index()

    existing = index.get(concept_name, {})
    existing_aliases = existing.get("aliases", [])
    new_aliases = list(set(existing_aliases + (aliases or [])))

    index[concept_name] = {
        "path": concept_path,
        "aliases": new_aliases,
        "summary": summary or existing.get("summary", ""),
        "article_count": existing.get("article_count", 0),  # 保留旧值，由 recalc 刷新
    }
    return index


def recalc_article_counts(index: dict | None = None) -> dict:
    """
    动态重算所有概念的 article_count。
    扫描 pages/ 下 .md 文件，统计每个概念名/别名在文件中的出现次数。
    """
    if index is None:
        index = load_concepts_index()

    pages_path = Path(WIKI_ROOT) / "pages"
    if not pages_path.exists():
        return index

    # 初始化计数
    for info in index.values():
        info["article_count"] = 0

    # 遍历所有页面
    for fp in pages_path.rglob("*.md"):
        if "_archived" in fp.parts:
            continue
        try:
            content = fp.read_text("utf-8", errors="replace").lower()
        except OSError:
            continue

        # 匹配概念名 + 别名
        for concept_name, info in index.items():
            name_lower = concept_name.lower()
            all_names = [name_lower] + [a.lower() for a in info.get("aliases", [])]
            if any(name in content for name in all_names):
                info["article_count"] += 1

    return index


def match_related_concepts(
    key_terms: list[str],
    concepts_index: dict | None = None,
    top_n: int = 5,
) -> list[str]:
    """
    根据 key_terms 匹配相关概念。
    匹配 concept name + aliases。
    返回概念名列表（按匹配分数降序）。
    """
    if concepts_index is None:
        concepts_index = load_concepts_index()

    scores: dict[str, int] = {}
    terms_lower = [t.lower() for t in key_terms]

    for concept_name, info in concepts_index.items():
        score = 0
        name_lower = concept_name.lower()
        # 名字 + 别名 都参与匹配
        all_names = [name_lower] + [a.lower() for a in info.get("aliases", [])]

        for term in terms_lower:
            for name in all_names:
                # 包含匹配（双向）
                if term in name or name in term:
                    score += 1
                    break

        if score > 0:
            scores[concept_name] = score

    ranked = sorted(scores, key=lambda k: scores[k], reverse=True)
    return ranked[:top_n]


# ============================================================================
# source_map.json — 源文件追溯
# ============================================================================

SOURCE_MAP_PATH = os.path.join(META_DIR, "source_map.json")


def load_source_map() -> dict:
    """加载源文件映射：{sha256: {original_filename, raw_path, generated_pages, ...}}"""
    return _read_json(SOURCE_MAP_PATH)


def save_source_map(source_map: dict) -> None:
    _write_json(source_map, SOURCE_MAP_PATH)


def update_source_map(
    sha256: str,
    original_filename: str,
    raw_path: str,
    generated_pages: list[str] | None = None,
    uploader: str = "manual",
    source_map: dict | None = None,
) -> dict:
    """添加或更新一个源文件记录"""
    if source_map is None:
        source_map = load_source_map()

    source_map[sha256] = {
        "original_filename": original_filename,
        "raw_path": raw_path,
        "generated_pages": generated_pages or [],
        "uploader": uploader,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
    }
    return source_map


def find_source_by_page(page_path: str, source_map: dict | None = None) -> str:
    """根据页面路径反查源文件 SHA256"""
    if source_map is None:
        source_map = load_source_map()

    for sha, info in source_map.items():
        if page_path in info.get("generated_pages", []):
            return sha
    return ""


# ============================================================================
# filename_index.json — 文件名重名检测
# ============================================================================

FILENAME_INDEX_PATH = os.path.join(META_DIR, "filename_index.json")


def load_filename_index() -> dict[str, list[str]]:
    """加载文件名索引：{stem: [sha256, ...]}"""
    return _read_json(FILENAME_INDEX_PATH)


def save_filename_index(index: dict[str, list[str]]) -> None:
    _write_json(index, FILENAME_INDEX_PATH)


def check_duplicate_filename(
    stem: str,
    exclude_sha: str | None = None,
    index: dict[str, list[str]] | None = None,
) -> list[str]:
    """检查文件名是否已存在，返回 SHA256 列表"""
    if index is None:
        index = load_filename_index()

    candidates = index.get(stem, [])
    if exclude_sha:
        candidates = [s for s in candidates if s != exclude_sha]
    return candidates


def add_filename_index(stem: str, sha256: str, index: dict[str, list[str]] | None = None) -> dict:
    """向文件名索引添加一条记录"""
    if index is None:
        index = load_filename_index()

    existing = index.setdefault(stem, [])
    if sha256 not in existing:
        existing.append(sha256)
    return index


def sync_meta_from_files() -> dict:
    """
    扫描 raw/ 和 pages/ 自动填充 source_map 和 filename_index。
    应在 rebuild 后或定期调用。

    返回: {"source_map_updated": int, "filename_index_updated": int}
    """
    result = {"source_map_updated": 0, "filename_index_updated": 0}

    raw_dir = Path(WIKI_ROOT) / "raw"
    if not raw_dir.exists():
        return result

    # 加载现有索引
    source_map = load_source_map()
    filename_index = load_filename_index()

    # 遍历 raw/ 文件
    for fp in sorted(raw_dir.rglob("*")):
        if not fp.is_file() or fp.name in (".DS_Store",):
            continue
        try:
            content = fp.read_text("utf-8", errors="replace")
        except OSError:
            continue

        h = hashlib.sha256(content.encode("utf-8")).hexdigest()
        rel = str(fp.relative_to(raw_dir)).replace("\\", "/")

        # 更新 source_map
        if h not in source_map:
            source_map[h] = {
                "original_filename": fp.name,
                "raw_path": rel,
                "generated_pages": [],
                "uploader": "auto-sync",
                "uploaded_at": datetime.now(timezone.utc).isoformat(),
            }
            result["source_map_updated"] += 1

        # 更新 filename_index
        stem = fp.stem
        if h not in filename_index.get(stem, []):
            add_filename_index(stem, h, filename_index)
            result["filename_index_updated"] += 1

    # 扫描 pages/ 文件，链接到 source_map 的 generated_pages
    pages_dir = Path(WIKI_ROOT) / "pages"
    if pages_dir.exists():
        for page_fp in sorted(pages_dir.rglob("*.md")):
            if "_archived" in page_fp.parts:
                continue
            try:
                page_content = page_fp.read_text("utf-8", errors="replace")
            except OSError:
                continue

            # 解析 frontmatter sources
            sources = []
            if page_content.startswith("---"):
                fm_end = page_content.find("\n---", 3)
                if fm_end > 0:
                    fm = page_content[4:fm_end]
                    for line in fm.split("\n"):
                        if line.strip().startswith("- "):
                            sources.append(line.strip()[2:])

            page_rel = str(page_fp.relative_to(pages_dir)).replace("\\", "/")

            # 匹配 source_map 中的记录
            for h, info in source_map.items():
                raw_name = info.get("original_filename", "")
                if any(raw_name in s for s in sources):
                    if page_rel not in info.get("generated_pages", []):
                        info.setdefault("generated_pages", []).append(page_rel)

    # 保存
    save_source_map(source_map)
    save_filename_index(filename_index)

    return result


# ============================================================================
# CLI 命令
# ============================================================================


def cmd_concepts_show() -> None:
    index = load_concepts_index()
    if not index:
        print("  概念索引为空")
        return

    # 动态重算 article_count
    index = recalc_article_counts(index)
    save_concepts_index(index)

    print(f"  概念索引 ({len(index)} 个概念):\n")
    for name, info in sorted(index.items()):
        aliases = ", ".join(info.get("aliases", []))
        print(f"  📌 {name}")
        if aliases:
            print(f"     别名: {aliases}")
        print(f"     文章数: {info.get('article_count', 0)}")
        print()


def cmd_concepts_add(name: str, path: str, aliases: str | None, summary: str | None) -> None:
    if not path:
        print("  ❌ --path 为必填参数，指定概念页面的相对路径")
        sys.exit(1)
    index = load_concepts_index()
    aliases_list = [a.strip() for a in aliases.split(",")] if aliases else None
    index = update_concept(name, path, summary or "", aliases_list, index)
    save_concepts_index(index)
    print(f"  ✅ 已添加概念: {name}")


def cmd_concepts_match(terms: str) -> None:
    index = load_concepts_index()
    key_terms = [t.strip() for t in terms.split(",")]
    matched = match_related_concepts(key_terms, index)

    if not matched:
        print("  未匹配到相关概念")
        return

    print(f"  匹配到 {len(matched)} 个相关概念:\n")
    for name in matched:
        info = index.get(name, {})
        aliases = ", ".join(info.get("aliases", []))
        print(f"  📌 {name}")
        if aliases:
            print(f"     别名: {aliases}")
        print()


def cmd_source_show() -> None:
    source_map = load_source_map()
    if not source_map:
        print("  源文件映射为空")
        return

    print(f"  源文件映射 ({len(source_map)} 个源文件):\n")
    for sha, info in sorted(source_map.items()):
        pages = info.get("generated_pages", [])
        print(f"  📄 {info.get('original_filename', sha[:8])}")
        print(f"     SHA256: {sha[:16]}...")
        print(f"     生成页面: {len(pages)} 个")
        print()


def cmd_filename_show() -> None:
    index = load_filename_index()
    if not index:
        print("  文件名索引为空")
        return

    print(f"  文件名索引 ({len(index)} 个文件名):\n")
    for stem, shas in sorted(index.items()):
        if len(shas) > 1:
            print(f"  ⚠️  {stem}: {len(shas)} 个版本")
        else:
            print(f"  ✅ {stem}: 1 个版本")


def cmd_concepts_remove(name: str) -> None:
    """删除一个概念"""
    index = load_concepts_index()
    if name not in index:
        print(f"  ⚠️  概念不存在: {name}")
        return
    del index[name]
    save_concepts_index(index)
    print(f"  🗑️  已删除概念: {name}")


def cmd_concepts_recalc() -> None:
    """动态重算所有概念的 article_count"""
    index = load_concepts_index()
    if not index:
        print("  概念索引为空，无需重算")
        return
    index = recalc_article_counts(index)
    save_concepts_index(index)
    print("  ✅ article_count 已刷新（基于 pages/ 实际内容统计）")


def cmd_source_remove(sha256: str) -> None:
    """删除一个源文件记录"""
    source_map = load_source_map()
    if sha256 not in source_map:
        print(f"  ⚠️  源文件记录不存在: {sha256[:16]}...")
        return
    info = source_map[sha256]
    del source_map[sha256]
    save_source_map(source_map)
    print(f"  🗑️  已删除源文件记录: {info.get('original_filename', sha256[:16])}")


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n可用命令:")
        print("  concepts-show                    查看概念索引")
        print("  concepts-add NAME [OPTIONS]      添加/更新概念")
        print("  concepts-remove NAME             删除概念")
        print("  concepts-match TERMS             匹配相关概念")
        print("  source-show                      查看源文件映射")
        print("  source-remove SHA256             删除源文件记录")
        print("  filename-show                    查看文件名索引")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "concepts-show":
        cmd_concepts_show()
    elif cmd == "concepts-recalc":
        cmd_concepts_recalc()
    elif cmd == "concepts-add":
        if len(sys.argv) < 4:
            print("  用法: concepts-add NAME --path PATH [--aliases ALIASES] [--summary SUMMARY]")
            sys.exit(1)
        name = sys.argv[2]
        path = ""
        aliases = None
        summary = None
        i = 3
        while i < len(sys.argv):
            if sys.argv[i] == "--path" and i + 1 < len(sys.argv):
                path = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--aliases" and i + 1 < len(sys.argv):
                aliases = sys.argv[i + 1]
                i += 2
            elif sys.argv[i] == "--summary" and i + 1 < len(sys.argv):
                summary = sys.argv[i + 1]
                i += 2
            else:
                i += 1
        cmd_concepts_add(name, path, aliases, summary)
    elif cmd == "concepts-match":
        if len(sys.argv) < 3:
            print("  用法: concepts-match TERMS")
            sys.exit(1)
        cmd_concepts_match(sys.argv[2])
    elif cmd == "concepts-remove":
        if len(sys.argv) < 3:
            print("  用法: concepts-remove NAME")
            sys.exit(1)
        cmd_concepts_remove(sys.argv[2])
    elif cmd == "source-show":
        cmd_source_show()
    elif cmd == "source-remove":
        if len(sys.argv) < 3:
            print("  用法: source-remove SHA256")
            sys.exit(1)
        cmd_source_remove(sys.argv[2])
    elif cmd == "filename-show":
        cmd_filename_show()
    elif cmd == "sync-meta":
        result = sync_meta_from_files()
        print(f"  ✅ source_map 新增 {result['source_map_updated']} 条")
        print(f"  ✅ filename_index 新增 {result['filename_index_updated']} 条")
    else:
        print(f"  未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
