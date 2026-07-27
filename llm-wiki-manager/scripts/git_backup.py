#!/usr/bin/env python3
"""
Git 自动备份 — 每次 compile_post 成功后的增量提交

用途：
  为 wiki_root 启用 git 版本管理，每次编译成功自动提交，
  提供回滚能力和变更历史。

  不会影响用户已有的 git 工作流：
  - 如果 wiki_root 已是 git 仓库，直接使用
  - 如果不是，自动初始化并配置 .gitignore

用法:
    # 手动调用
    python scripts/git_backup.py

    # 指定消息
    python scripts/git_backup.py --message "编译: Rust 异步并发"

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


from _common import get_wiki_root as _get_wiki_root


def auto_commit(wiki_root: str | None = None, message: str | None = None) -> bool:
    """
    对 wiki_root 执行 git commit（自动初始化/add）。

    Args:
        wiki_root: wiki 根目录路径
        message:   提交信息（自动生成如果未提供）

    Returns:
        True 表示提交成功（或无需提交），False 表示失败
    """
    if wiki_root is None:
        wiki_root = _get_wiki_root()

    root = Path(wiki_root)
    if not root.exists():
        return False

    git_dir = root / ".git"

    # 如果不是 git 仓库，自动初始化
    if not git_dir.exists():
        try:
            subprocess.run(
                ["git", "init"],
                cwd=str(root),
                capture_output=True,
                text=True,
                timeout=10,
            )
            print("  📦 git 仓库已初始化")
        except Exception as e:
            print(f"  ⚠️  git init 失败: {e}")
            return False

        # 创建 .gitignore（不覆盖已有）
        gitignore = root / ".gitignore"
        if not gitignore.exists():
            gitignore.write_text(
                "# wiki manager auto-ignore\n.cache/\nsearch_index.db\n__pycache__/\n*.pyc\n.DS_Store\nthumbs.db\n",
                encoding="utf-8",
            )

    # 检查是否有变更
    try:
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if not status.stdout.strip():
            return True  # 无变更，跳过提交
    except Exception as e:
        print(f"  ⚠️  git status 失败: {e}")
        return False

    # git add
    try:
        subprocess.run(
            ["git", "add", "."],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as e:
        print(f"  ⚠️  git add 失败: {e}")
        return False

    # git commit
    if not message:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        message = f"compile_post: 自动增量提交 @ {now}"

    try:
        result = subprocess.run(
            ["git", "commit", "-m", message],
            cwd=str(root),
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            # 提取简短的统计信息
            summary = result.stdout.strip().split("\n")[-1] if result.stdout else "提交完成"
            print(f"  📦 {summary}")
            return True
        else:
            print(f"  ⚠️  git commit 失败: {result.stderr.strip()}")
            return False
    except Exception as e:
        print(f"  ⚠️  git commit 异常: {e}")
        return False


def main() -> None:
    message = None
    args = sys.argv[1:]
    for i, a in enumerate(args):
        if a == "--message" and i + 1 < len(args):
            message = args[i + 1]
            break

    auto_commit(message=message)


if __name__ == "__main__":
    main()
