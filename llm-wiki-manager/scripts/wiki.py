#!/usr/bin/env python3
"""
Wiki 统一入口脚本

用法：
    python scripts/wiki.py <command> [args...]

示例：
    python scripts/wiki.py compile_post
    python scripts/wiki.py detect_concepts --dry-run
    python scripts/wiki.py search rebuild

自动检测 WIKI_ROOT：
    1. 环境变量 WIKI_ROOT
    2. 当前目录的 .wiki_root 文件
    3. 默认 ~/wiki
"""

import os
import sys
from pathlib import Path


def get_wiki_root():
    """自动检测 WIKI_ROOT"""
    # 1. 环境变量
    if "WIKI_ROOT" in os.environ:
        return os.environ["WIKI_ROOT"]

    # 2. 当前目录的 .wiki_root 文件
    wiki_root_file = Path(".wiki_root")
    if wiki_root_file.exists():
        return wiki_root_file.read_text(encoding="utf-8").strip()

    # 3. 默认 ~/wiki
    default_root = Path.home() / "wiki"
    return str(default_root)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    # 设置 WIKI_ROOT 环境变量
    wiki_root = get_wiki_root()
    os.environ["WIKI_ROOT"] = wiki_root

    # 获取命令
    command = sys.argv[1]
    args = sys.argv[2:]

    # 执行对应脚本
    script_map = {
        "compile_post": "compile_post.py",
        "detect_concepts": "detect_concepts.py",
        "search": "search_engine.py",
        "promote": "promote.py",
        "lint": "lint.py",
        "delete": "delete.py",
        "cache": "cache.py",
        "validate": "validate_entities.py",
        "graph": "graph_analyze.py",
        "init": "init.py",
        "fetch": "fetch.py",
        "index": "index.py",
    }

    if command not in script_map:
        print(f"❌ 未知命令: {command}")
        print(f"可用命令: {', '.join(script_map.keys())}")
        sys.exit(1)

    # 构造脚本路径
    script_dir = Path(__file__).parent
    script_path = script_dir / script_map[command]

    if not script_path.exists():
        print(f"❌ 脚本不存在: {script_path}")
        sys.exit(1)

    # 执行脚本
    print(f"📍 WIKI_ROOT: {wiki_root}")
    print(f"🚀 执行: {script_path.name} {' '.join(args)}")
    print()

    # 使用 exec 执行脚本（保持在同一进程）
    sys.argv = [str(script_path)] + args
    with open(script_path, encoding="utf-8") as f:
        code = compile(f.read(), str(script_path), "exec")
        exec(code, {"__name__": "__main__", "__file__": str(script_path)})


if __name__ == "__main__":
    main()
