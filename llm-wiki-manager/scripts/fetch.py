#!/usr/bin/env python3
"""LLM Wiki 素材导入工具

将本地文件或 stdin 内容导入到 wiki raw/ 目录。
URL 抓取由 LLM 使用 web_fetch 工具完成，脚本不再负责。
导入后自动更新 SHA256 缓存（.cache/sources.json）。

用法:
    WIKI_ROOT=/path/to/wiki python fetch.py ~/Downloads/note.md
    echo "内容" | python fetch.py --stdin "标题"

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path


from _common import file_hash as _compute_file_hash, get_wiki_root as _get_wiki_root

WIKI_ROOT = _get_wiki_root()
RAW_DIR = os.path.join(WIKI_ROOT, "raw")


def _update_cache(filename: str, content: str) -> None:
    """更新 SHA256 缓存（委托 _common.file_hash）"""
    try:
        h = _compute_file_hash(content)
        cache_file = Path(WIKI_ROOT) / ".cache" / "sources.json"
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache = json.loads(cache_file.read_text("utf-8")) if cache_file.exists() else {}
        # 使用 raw/ 下的相对路径作为 key（支持子目录同名文件）
        raw_dir = Path(WIKI_ROOT) / "raw"
        dest_path = Path(RAW_DIR) / filename
        try:
            key = str(dest_path.relative_to(raw_dir)).replace("\\", "/")
        except ValueError:
            key = filename
        cache[key] = h
        cache_file.write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")
        print(f"  📦 缓存已更新: {key} [{h}]")
    except Exception:
        pass  # 缓存失败不影响主流程


def import_file(source: str) -> None:
    """导入本地文件到 raw/ 目录，自动更新缓存"""
    Path(RAW_DIR).mkdir(parents=True, exist_ok=True)

    src = Path(source)
    if not src.exists() or not src.is_file():
        print(f"  ❌ 文件不存在: {source}")
        sys.exit(1)

    dest = Path(RAW_DIR) / src.name
    if dest.exists():
        stem = dest.stem
        suffix = dest.suffix
        counter = 1
        while dest.exists():
            dest = Path(RAW_DIR) / f"{stem}_{counter}{suffix}"
            counter += 1

    shutil.copy2(src, dest)
    print(f"  ✅ 已复制: {src.name} -> {dest.name}")

    # 自动更新缓存
    try:
        content = dest.read_text("utf-8", errors="replace")
        _update_cache(dest.name, content)
    except Exception:
        pass


def import_stdin(title: str) -> None:
    """从 stdin 读取内容并保存到 raw/，自动更新缓存"""
    Path(RAW_DIR).mkdir(parents=True, exist_ok=True)

    if sys.stdin.isatty():
        print('  ❌ --stdin 需要管道输入，例: echo "内容" | python fetch.py --stdin "标题"')
        sys.exit(1)

    content = sys.stdin.read()
    if not content.strip():
        print("  ❌ 未接收到有效内容")
        sys.exit(1)

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", title)[:50]
    dest = Path(RAW_DIR) / f"{safe_title}_{timestamp}.txt"
    dest.write_text(content, encoding="utf-8")
    print(f"  ✅ 已保存: {dest}")

    # 自动更新缓存
    _update_cache(dest.name, content)


def main() -> None:
    if "--stdin" in sys.argv:
        stdin_index = sys.argv.index("--stdin")
        title = sys.argv[stdin_index + 1] if stdin_index + 1 < len(sys.argv) else "pasted"
        import_stdin(title)
        return

    if len(sys.argv) < 2:
        print(__doc__)
        print("\n用法示例:")
        print(f'  WIKI_ROOT=/path/to/wiki python {sys.argv[0]} "~/Downloads/note.md"')
        print(f'  echo "内容" | WIKI_ROOT=/path/to/wiki python {sys.argv[0]} --stdin "标题"')
        sys.exit(1)

    import_file(sys.argv[1])


if __name__ == "__main__":
    main()
