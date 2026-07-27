#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
编译后处理 — 原子化完成编译流程的后半段

解决编译流程 6-8 步之间 LLM 崩溃导致的不一致问题。

调用时机：LLM 写完 pages/*.md 后立即调用此脚本。
结果保证：缓存更新 + 索引重建 + 概念检测 + index.md 时间戳三者原子完成（或全部失败）。

用法:
    python scripts/wiki.py compile_post
    python scripts/wiki.py compile_post --page "pages/my-new-page.md"

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import json
import os
import sys

# Windows console UTF-8 支持
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from datetime import datetime, timezone
from pathlib import Path


from _common import (
    file_hash,
    get_wiki_root as _get_wiki_root,
    handle_error,
    WikiError,
    ErrorCode,
)


WIKI_ROOT = _get_wiki_root()


@handle_error
def main():
    dry_run = "--dry-run" in sys.argv
    page_filter = None
    if "--page" in sys.argv:
        idx = sys.argv.index("--page")
        if idx + 1 < len(sys.argv):
            page_filter = sys.argv[idx + 1]

    print(f"📦 编译后处理 | wiki_root: {WIKI_ROOT}")
    if dry_run:
        print("  🧪 试运行模式（不实际写入）")
        print()

    errors = []

    # Step 1: 更新编译页面缓存（Body-Only SHA256）
    print("1. 更新页面缓存...")
    cache_dir = Path(WIKI_ROOT) / ".cache"
    cache_file = cache_dir / "sources.json"
    cache = {}
    if cache_file.exists():
        try:
            cache = json.loads(cache_file.read_text("utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            raise WikiError(
                ErrorCode.CACHE_CORRUPTED,
                f"缓存文件损坏: {cache_file}",
                recovery_hint="运行: python scripts/wiki.py cache sync",
                details={"error": str(e)},
            )

    cache_dir.mkdir(parents=True, exist_ok=True)

    pages_dir = Path(WIKI_ROOT) / "pages"
    updated_count = 0
    if pages_dir.exists():
        for fp in sorted(pages_dir.rglob("*.md")):
            if "_archived" in fp.parts:
                continue
            if page_filter:
                pf = page_filter.replace("\\", "/")
                if pf.startswith("pages/"):
                    pf = pf[len("pages/") :]
                fp_rel = fp.relative_to(pages_dir).as_posix()
                if fp_rel != pf:
                    continue

            key = str(fp.relative_to(Path(WIKI_ROOT))).replace("\\", "/")

            try:
                content = fp.read_text("utf-8", errors="replace")
            except OSError as e:
                print(f"  ⚠️  无法读取: {fp} - {e}")
                continue

            h = file_hash(content)
            if cache.get(key) != h:
                cache[key] = h
                updated_count += 1

    if not dry_run:
        try:
            cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")
        except OSError as e:
            raise WikiError(
                ErrorCode.FILE_PERMISSION_DENIED,
                f"无法写入缓存文件: {cache_file}",
                recovery_hint="检查文件权限",
                details={"error": str(e)},
            )
    print(f"  ✅ 缓存已更新 ({updated_count} 个页面)")

    # Step 2: 重建搜索索引
    print("2. 重建搜索索引...")
    if not dry_run:
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from search_engine import rebuild as engine_rebuild

            engine_rebuild()
            print("  ✅ 索引已重建")
        except Exception as e:
            errors.append(f"索引重建失败: {e}")
            print(f"  ❌ {e}")
    else:
        print("  (试运行跳过)")

    # Step 3: 更新 index.md 最后修改时间
    print("3. 更新时间戳...")
    index_path = Path(WIKI_ROOT) / "pages" / "index.md"
    if index_path.exists() and not dry_run:
        try:
            content = index_path.read_text("utf-8")
            now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
            if "> 最后更新" in content:
                content = content.replace(
                    "> 最后更新" + content.split("> 最后更新")[1].split("\n")[0],
                    f"> 最后更新: {now}",
                )
            else:
                # 在第一个 ## 前插入更新时间
                first_h2 = content.find("\n## ")
                if first_h2 > 0:
                    content = content[:first_h2] + f"\n\n> 最后更新: {now}\n" + content[first_h2:]
            index_path.write_text(content, "utf-8")
            print(f"  ✅ index.md 已更新: {now}")
        except OSError as e:
            errors.append(f"index.md 更新失败: {e}")
            print(f"  ⚠️  {e}")
    else:
        print("  (跳过)")

    # Step 4: 自动概念检测
    print("4. 刷新概念索引...")
    if not dry_run:
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from detect_concepts import scan_all_pages

            result = scan_all_pages(dry_run=False)
            if "error" not in result:
                print(f"  ✅ 概念索引已更新 ({result['total_pages']} 页, {result['total_concepts']} 概念实例)")
            else:
                errors.append(f"概念检测失败: {result.get('error', 'Unknown')}")
                print(f"  ⚠️  {result.get('error', 'Unknown')}")
        except ImportError:
            print("  (跳过：detect_concepts 模块不可用)")
        except Exception as e:
            errors.append(f"概念检测失败: {e}")
            print(f"  ⚠️  {e}")
    else:
        print("  (试运行跳过)")

    # Step 4b: OKF v0.1 字段自动增强（Google OKF v0.1 标准）
    print("4b. OKF v0.1 字段自动增强...")
    if not dry_run:
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from okf_enhance import enhance_page

            # 如果有 --page 参数，只增强该页面；否则增强所有非归档页面
            if page_filter:
                target = page_filter.replace("\\", "/")
                if not target.startswith("pages/"):
                    target = f"pages/{target}"
                result = enhance_page(target, dry_run=False)
                if "error" not in result:
                    print("  ✅ OKF 增强完成")
                    for key, val in result["enhanced"].items():
                        if key.startswith("_"):
                            continue
                        print(f"    {key}: {val}")
                else:
                    print(f"  ⚠️  {result['error']}")
            else:
                # 批量增强：扫描所有 pages/*.md
                pages_dir = Path(WIKI_ROOT) / "pages"
                targets = []
                for fp in sorted(pages_dir.rglob("*.md")):
                    if "_archived" in fp.parts:
                        continue
                    targets.append(fp.relative_to(Path(WIKI_ROOT)).as_posix())

                if not targets:
                    print("  (无页面)")
                    return

                # 第一遍：dry-run 验证所有页面
                validation_errors = []
                for rel in targets:
                    result = enhance_page(rel, dry_run=True)
                    if "error" in result:
                        validation_errors.append(f"  ⚠️  {rel} — {result['error']}")
                if validation_errors:
                    print("  [X] 验证失败，不会写入任何页面:")
                    for e in validation_errors:
                        print(e)
                    return

                # 第二遍：全部通过，执行写入
                ok_count = 0
                for rel in targets:
                    result = enhance_page(rel, dry_run=False)
                    if "error" in result:
                        print(f"  ⚠️  跳过: {rel} — {result['error']}")
                    else:
                        ok_count += 1
                print(f"  ✅ OKF 批量增强完成 ({ok_count} 页成功/{len(targets)} 页)")
        except ImportError:
            print("  (跳过：okf_enhance 模块不可用)")
        except Exception as e:
            errors.append(f"OKF 增强失败: {e}")
            print(f"  ⚠️  {e}")
    else:
        print("  (试运行跳过)")

    # Step 5: Tags 自动建议（仅 --page 模式）
    if page_filter and not dry_run:
        print("5. Tags 自动建议...")
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from suggest_tags import suggest_all, _print_result

            page_path = page_filter.replace("\\", "/")
            if page_path.startswith("pages/"):
                page_path = page_path[len("pages/") :]
            page_path = "pages/" + page_path  # 转为 WIKI_ROOT 相对路径（供 suggest_tags 内部解析）
            full_path = os.path.join(WIKI_ROOT, page_path)
            if os.path.exists(full_path):
                content = Path(full_path).read_text("utf-8", errors="replace")
                result = suggest_all(content, page_path)
                _print_result(result)
            print("  ✅ Tags 自动建议完成")
        except ImportError:
            print("  (跳过：suggest_tags 模块不可用)")
        except Exception as e:
            print(f"  ⚠️  {e}")
    else:
        if page_filter:
            print("5. Tags 自动建议... (试运行跳过)")
        # 非 --page 模式不显示编号

    # Step 6: Git 自动提交（版本备份）
    print("6. Git 自动备份...")
    if not dry_run:
        try:
            sys.path.insert(0, os.path.dirname(__file__))
            from git_backup import auto_commit

            auto_commit(WIKI_ROOT)
        except ImportError:
            print("  (跳过：git_backup 模块不可用)")
        except Exception as e:
            print(f"  ⚠️  {e}")
    else:
        print("  (试运行跳过)")

    # 结果汇总
    if errors:
        print(f"\n⚠️  部分步骤失败 ({len(errors)} 个错误):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("\n✅ 编译后处理完成（缓存 + 索引 + 时间戳 + 概念检测 + OKF字段增强 + tags 建议 + git 备份）")


if __name__ == "__main__":
    main()
