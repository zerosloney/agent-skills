#!/usr/bin/env python3
"""LLM Wiki SHA256 增量缓存 — 跳过未变更的 raw 素材

原理：记录每个 raw 文件的内容哈希，ingest 时对比哈希，
只有哈希变化时才重新 compile，避免无意义的重复编译。

用法:
    # 查看缓存状态
    python scripts/cache.py status

    # 更新单个文件的缓存
    python scripts/cache.py update raw/article.md

    # 批量更新所有 raw 文件（ingest 时自动调用）
    python scripts/cache.py sync

    # 检查文件是否有变化（有变化返回 exit 0，无变化 exit 1）
    python scripts/cache.py check raw/article.md

    # 清除缓存
    python scripts/cache.py clear

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import json
import os
import sys
from pathlib import Path


from _common import file_hash as _compute_file_hash, get_wiki_root as _get_wiki_root

WIKI_ROOT = _get_wiki_root()
CACHE_FILE = os.path.join(WIKI_ROOT, ".cache", "sources.json")


def _load_cache() -> dict[str, str]:
    """加载缓存字典 {filename: hash}"""
    if not Path(CACHE_FILE).exists():
        return {}
    try:
        return json.loads(Path(CACHE_FILE).read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_cache(cache: dict[str, str]) -> None:
    """保存缓存到 .cache/sources.json"""
    Path(CACHE_FILE).parent.mkdir(parents=True, exist_ok=True)
    Path(CACHE_FILE).write_text(json.dumps(cache, ensure_ascii=False, indent=2), "utf-8")


def _compute_hash(content: str) -> str:
    """计算内容 SHA256 哈希（委托 _common.file_hash）"""
    return _compute_file_hash(content)


def _file_hash(filepath: str) -> str | None:
    """计算单个文件的哈希，不存在返回 None"""
    try:
        return _compute_hash(Path(filepath).read_text("utf-8", errors="replace"))
    except OSError:
        return None


# ── 命令实现 ──


def cmd_status() -> None:
    """显示缓存状态"""
    cache = _load_cache()
    raw_dir = Path(WIKI_ROOT) / "raw"
    if not raw_dir.exists():
        print("  raw/ 目录不存在")
        return

    # C3: rglob 递归扫描子目录
    files = sorted(f for f in raw_dir.rglob("*") if f.is_file() and f.name not in (".DS_Store",))
    if not files:
        print("  raw/ 目录为空")
        return

    print(f"  缓存文件: {CACHE_FILE}")
    print(f"  缓存条目: {len(cache)} 个\n")
    for f in files:
        key = _relative_key(str(f))
        h = cache.get(key, "—")
        changed = "✨" if h == "—" else "  "
        rel = key if key != f.name else f.name
        print(f"  {changed} {rel}  [{h}]")


def _relative_key(filepath: str) -> str:
    """生成缓存 key：raw/ 下的相对路径（支持子目录同名文件）"""
    raw_dir = Path(WIKI_ROOT) / "raw"
    try:
        return str(Path(filepath).relative_to(raw_dir)).replace("\\", "/")
    except ValueError:
        # 不在 raw/ 下，降级为文件名
        return Path(filepath).name


def _update_one(cache: dict[str, str], filepath: str) -> tuple[bool, str]:
    """
    更新单个文件的缓存（内存操作，不写磁盘）。
    返回 (是否变化, 输出行)
    """
    new_hash = _file_hash(filepath)
    if new_hash is None:
        return False, f"  ❌ 文件不存在: {filepath}"

    key = _relative_key(filepath)
    old_hash = cache.get(key)
    cache[key] = new_hash

    if old_hash is None:
        return True, f"  ✨ 新增缓存: {key} [{new_hash}]"
    elif old_hash != new_hash:
        return True, f"  🔄 哈希变化: {key} [{old_hash} → {new_hash}]"
    else:
        return False, f"  ✅ 无变化，跳过: {key} [{new_hash}]"


def cmd_update(filepath: str) -> bool:
    """更新单个文件的缓存，返回是否变化"""
    cache = _load_cache()
    changed, msg = _update_one(cache, filepath)
    print(msg)
    if changed:
        _save_cache(cache)  # 只在有变化时写磁盘
    return changed


def cmd_sync() -> dict[str, bool]:
    """同步所有 raw 文件，返回 {filename: changed}"""
    cache = _load_cache()
    raw_dir = Path(WIKI_ROOT) / "raw"
    if not raw_dir.exists():
        return {}

    # C3: rglob 递归扫描子目录
    files = sorted(f for f in raw_dir.rglob("*") if f.is_file() and f.name not in (".DS_Store",))

    results: dict[str, bool] = {}
    for f in files:
        changed, msg = _update_one(cache, str(f))
        print(msg)
        results[f.name] = changed

    # C2: 批量写入 — 只在最后写一次磁盘
    _save_cache(cache)

    changed_files = [k for k, v in results.items() if v]
    print(f"\n  📊 同步完成: {len(changed_files)}/{len(results)} 个文件有变化")
    return results


def cmd_check(filepath: str) -> None:
    """
    检查文件是否有变化。
    Exit code: 0 = 有变化（需重新编译），1 = 无变化（可跳过）
    """
    key = _relative_key(filepath)
    cache = _load_cache()
    new_hash = _file_hash(filepath)

    if new_hash is None:
        print(f"  ❌ 文件不存在: {filepath}")
        sys.exit(1)

    old_hash = cache.get(key)
    if old_hash is None or old_hash != new_hash:
        print(f"  ✨ 有变化: {key}")
        sys.exit(0)
    else:
        print(f"  ✅ 无变化: {key}")
        sys.exit(1)


def cmd_clear() -> None:
    """清除所有缓存"""
    if Path(CACHE_FILE).exists():
        Path(CACHE_FILE).unlink()
        print(f"  🗑️  已清除缓存: {CACHE_FILE}")
    else:
        print("  ℹ️  缓存文件不存在，无需清除")


# ── 主入口 ──


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n可用命令: status | sync | update <file> | check <file> | clear")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "status":
        cmd_status()
    elif cmd == "sync":
        cmd_sync()
    elif cmd == "update":
        if len(sys.argv) < 3:
            print("  ❌ 用法: cache.py update <filepath>")
            sys.exit(1)
        cmd_update(sys.argv[2])
    elif cmd == "check":
        if len(sys.argv) < 3:
            print("  ❌ 用法: cache.py check <filepath>")
            sys.exit(1)
        cmd_check(sys.argv[2])
    elif cmd == "clear":
        cmd_clear()
    else:
        print(f"  ❌ 未知命令: {cmd}")
        print("  可用命令: status | sync | update <file> | check <file> | clear")
        sys.exit(1)


if __name__ == "__main__":
    main()
