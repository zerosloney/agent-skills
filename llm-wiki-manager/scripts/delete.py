#!/usr/bin/env python3
"""LLM Wiki 安全删除 — 带级联清理

删除 raw 素材时，同步清理引用该素材的知识页面的 frontmatter sources[]。

用法:
    # 预览删除影响（不实际删除）
    python scripts/delete.py --dry-run raw/article.md

    # 确认后删除
    python scripts/delete.py raw/article.md

    # 强制删除（跳过确认）
    python scripts/delete.py --force raw/article.md

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import json
import os
import shutil
import sys
from pathlib import Path


from _common import get_wiki_root as _get_wiki_root

WIKI_ROOT = _get_wiki_root()
RAW_DIR = os.path.join(WIKI_ROOT, "raw")
PAGES_DIR = os.path.join(WIKI_ROOT, "pages")
CACHE_FILE = os.path.join(WIKI_ROOT, ".cache", "sources.json")


def _get_frontmatter_bounds(content: str) -> tuple[list[str], str] | None:
    """提取 frontmatter 内容。返回 (lines列表, body正文) 或 None（无有效 frontmatter）。"""
    if not content.startswith("---"):
        return None
    end = content.find("\n---", 3)
    if end < 0:
        return None
    fm = content[3:end]
    body = content[end + 4 :]
    return (fm.splitlines(), body)


def _parse_frontmatter_sources(content: str) -> list[str]:
    """
    从 markdown 文件的 frontmatter 中提取 sources 数组。
    使用状态机方式，避免偏移量错误。
    """
    bounds = _get_frontmatter_bounds(content)
    if bounds is None:
        return []

    lines, _ = bounds

    # 找到 sources: 行
    sources_start = -1
    for i, line in enumerate(lines):
        if line.strip().startswith("sources:"):
            sources_start = i
            break

    if sources_start < 0:
        return []

    # 从 sources: 下一行开始，收集所有 - 开头的列表项
    sources: list[str] = []
    for i in range(sources_start + 1, len(lines)):
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("-"):
            src = stripped.lstrip("-").strip()
            src = src.strip('"').strip("'").strip()
            if src:
                sources.append(src)
        else:
            # 非列表项，sources 数组结束
            break

    return sources


def _find_referring_pages(source_name: str) -> list[tuple[str, list[str]]]:
    """
    查找所有引用了 source_name 的知识页面。
    返回 [(page_path, [source_names...])]
    """
    if not Path(PAGES_DIR).exists():
        return []

    referring: list[tuple[str, list[str]]] = []
    source_lower = source_name.lower()

    for page in Path(PAGES_DIR).rglob("*.md"):
        if "_archived" in page.parts:
            continue
        try:
            content = page.read_text("utf-8", errors="replace")
        except OSError:
            continue

        sources = _parse_frontmatter_sources(content)

        # 检查是否引用了该 source（精确匹配，防止误匹配 article.md 和 old-article.md）
        if any(source_lower == s.lower() for s in sources):
            referring.append((str(page), sources))

    return referring


def _remove_source_from_frontmatter(content: str, source_to_remove: str) -> str:
    """
    从 frontmatter 的 sources 数组中移除指定 source。
    使用状态机方式，精确处理 frontmatter 结构。
    """
    if not source_to_remove:
        return content

    bounds = _get_frontmatter_bounds(content)
    if bounds is None:
        return content

    lines, body = bounds
    source_lower = source_to_remove.lower()
    new_lines: list[str] = []

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        if stripped.startswith("sources:"):
            new_lines.append(line)
            i += 1
            # 处理 sources 下的列表项
            while i < len(lines):
                item_stripped = lines[i].strip()
                if not item_stripped:
                    # 空行可能在列表中间，跳过但保留
                    new_lines.append(lines[i])
                    i += 1
                    continue
                if item_stripped.startswith("-"):
                    src = item_stripped.lstrip("-").strip()
                    src_clean = src.strip('"').strip("'").strip()
                    if source_lower in src_clean.lower():
                        # 跳过这一行（不加入 new_lines）
                        i += 1
                        continue
                    else:
                        new_lines.append(lines[i])
                        i += 1
                        continue
                else:
                    # 非列表项，sources 结束
                    break
            continue

        new_lines.append(line)
        i += 1

    new_fm = "\n".join(new_lines)
    # 移除因 splitlines 产生的首行空行（frontmatter 紧接 ---）
    new_fm = new_fm.lstrip("\n")
    return "---\n" + new_fm + "\n---" + body


def _find_compiled_pages(source_name: str) -> list[str]:
    """
    查找哪些知识页面是由该 raw 素材编译产生的。
    判据：frontmatter sources[] 中包含该文件名。
    返回 [page_rel_path, ...]
    """
    if not Path(PAGES_DIR).exists():
        return []

    compiled: list[str] = []
    source_lower = source_name.lower()

    for page in Path(PAGES_DIR).rglob("*.md"):
        if "_archived" in page.parts:
            continue
        try:
            content = page.read_text("utf-8", errors="replace")
        except OSError:
            continue

        sources = _parse_frontmatter_sources(content)

        # 如果该素材是唯一来源，则该页面由该素材编译产生（精确匹配）
        if any(source_lower == s.lower() for s in sources):
            compiled.append(str(page))

    return compiled


def cmd_preview(source_path: str) -> list[tuple[str, list[str]]]:
    """预览删除影响"""
    source = Path(source_path)
    if not source.exists():
        print(f"  ❌ 文件不存在: {source_path}")
        sys.exit(1)

    referring = _find_referring_pages(source.name)
    compiled = _find_compiled_pages(source.name)
    print(f"\n  📄 素材: {source.name}")
    print(f"  📌 引用页面: {len(referring)} 个")
    print(f"  📝 编译页面: {len(compiled)} 个（由该素材直接编译产生）\n")

    if not referring:
        print("  ✅ 无页面引用，可安全删除")
    else:
        print("  ⚠️  以下页面的 frontmatter sources[] 将被清理：\n")
        for page_path, sources in referring:
            rel = Path(page_path).relative_to(Path(WIKI_ROOT))
            print(f"  📄 {rel}")
            for s in sources:
                if source.name.lower() in s.lower():
                    print(f"     - {s}  ← 将移除")
                else:
                    print(f"     + {s}")
            print()

    if compiled:
        print("  ⚠️  以下页面由该素材编译产生，删除素材后建议归档这些页面：\n")
        for page_path in compiled:
            rel = Path(page_path).relative_to(Path(WIKI_ROOT))
            print(f"  📝 {rel}")
            # 判断该素材是否为唯一来源
            try:
                content = Path(page_path).read_text("utf-8", errors="replace")
                sources = _parse_frontmatter_sources(content)
                if len(sources) <= 1:
                    print("     ⚠️  唯一来源！删除后该页面将变成“无来源”页面")
                else:
                    print(f"     ℹ️  还有 {len(sources) - 1} 个其他来源")
            except OSError:
                pass
            print()

    return referring


def cmd_delete(source_path: str, force: bool = False) -> None:
    """执行安全删除"""
    source = Path(source_path)
    if not source.exists():
        print(f"  ❌ 文件不存在: {source_path}")
        sys.exit(1)

    referring = cmd_preview(source_path)

    # 确认删除
    if not force:
        if sys.stdin.isatty():
            response = input("  ❓ 确认删除素材并清理引用？(y/N): ").strip().lower()
            if response != "y":
                print("  ❌ 已取消")
                sys.exit(0)
        else:
            print("  ❌ 非交互模式，请使用 --force 参数强制删除")
            sys.exit(1)

    # 在清理 frontmatter 之前，先确定哪些编译页面需要归档
    # （因为清理后 _find_compiled_pages 将无法找到来源引用）
    compiled_before = _find_compiled_pages(source.name)
    # 同时记录清理前的 sources 数量，用于判断是否唯一来源
    compiled_before_count: dict[str, int] = {}
    for page_path_str in compiled_before:
        try:
            c = Path(page_path_str).read_text("utf-8", errors="replace")
            compiled_before_count[page_path_str] = len(_parse_frontmatter_sources(c))
        except OSError:
            compiled_before_count[page_path_str] = 0

    # 清理引用页面的 frontmatter
    for page_path, sources in referring:
        try:
            content = Path(page_path).read_text("utf-8")
        except OSError:
            continue

        new_content = _remove_source_from_frontmatter(content, source.name)
        if new_content != content:
            Path(page_path).write_text(new_content, "utf-8")
            rel = Path(page_path).relative_to(Path(WIKI_ROOT))
            print(f"  🔧 已清理: {rel}")

    # 删除源文件
    source.unlink()
    print(f"\n  🗑️  已删除: {source.name}")

    # 更新缓存
    if Path(CACHE_FILE).exists():
        try:
            cache = json.loads(Path(CACHE_FILE).read_text("utf-8"))
            try:
                source_key = str(source.relative_to(Path(RAW_DIR))).replace("\\", "/")
            except ValueError:
                source_key = source.name
            if source_key in cache:
                del cache[source_key]
                Path(CACHE_FILE).write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")
                print(f"  🗑️  缓存已清理: {source_key}")
        except (json.JSONDecodeError, OSError):
            pass  # 非关键路径：缓存更新失败不影响删除操作

    # 归档仅来源为该素材的编译页面（唯一来源 → 无来源，建议归档）
    orphaned_pages = []
    for page_path in compiled_before:
        orig_src_count = compiled_before_count.get(page_path, 0)
        if orig_src_count <= 1:
            orphaned_pages.append(page_path)

    if orphaned_pages:
        print(f"\n  ⚠️  以下 {len(orphaned_pages)} 个页面的唯一来源被删除，建议归档：\n")
        for op in orphaned_pages:
            rel = Path(op).relative_to(Path(WIKI_ROOT))
            print(f"     📝 {rel}")
        print()

        archive_ok = True
        if not force:
            if sys.stdin.isatty():
                response = input("  ❓ 是否归档这些页面？(y/N): ").strip().lower()
                archive_ok = response == "y"
            else:
                print("  ℹ️  非交互模式，跳过归档（使用 --force 则自动归档）")
                archive_ok = False
        if archive_ok:
            archived_dir = Path(WIKI_ROOT) / "_archived"
            archived_dir.mkdir(parents=True, exist_ok=True)
            for page_path in orphaned_pages:
                try:
                    page = Path(page_path)
                    dest = archived_dir / page.name
                    if dest.exists():
                        stem = dest.stem
                        suffix = dest.suffix
                        counter = 1
                        while dest.exists():
                            dest = archived_dir / f"{stem}_{counter}{suffix}"
                            counter += 1
                    shutil.move(str(page), str(dest))
                    rel = page.relative_to(Path(WIKI_ROOT))
                    print(f"  📦 已归档: {rel} → _archived/{dest.name}")
                except OSError:
                    pass
        else:
            print("  ℹ️  已跳过归档，孤儿页面保留在原位置")

    # D4: 提示重建搜索索引
    print("\n  💡 建议运行: python scripts/search.py --rebuild")
    print("\n  ✅ 删除完成")


# ── 主入口 ──


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n用法:")
        print("  python delete.py --dry-run <source>     # 预览影响")
        print("  python delete.py <source>               # 交互确认删除")
        print("  python delete.py --force <source>      # 强制删除")
        sys.exit(1)

    dry_run = "--dry-run" in sys.argv
    force = "--force" in sys.argv

    # 提取源文件路径（去除所有选项）
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("  ❌ 请指定要删除的素材文件")
        sys.exit(1)

    source_path = args[0]

    if dry_run:
        cmd_preview(source_path)
    else:
        cmd_delete(source_path, force=force)


if __name__ == "__main__":
    main()
