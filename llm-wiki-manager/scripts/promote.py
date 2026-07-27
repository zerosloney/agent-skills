#!/usr/bin/env python3
"""
Promote 机制 — 查询提升为知识页面

扫描 outputs/queries/ 目录，判断哪些回答值得提升为正式知识页面。
提升标准：
1. 回答长度 > 500 字（排除模板）
2. 跨页面引用（多个 [[链接]]）
3. 包含新信息（无法从单个页面直接读出）

用法:
    WIKI_ROOT=<path> python scripts/promote.py --list          # 列出可提升的查询
    WIKI_ROOT=<path> python scripts/promote.py --promote <id> # 指定ID提升
    WIKI_ROOT=<path> python scripts/promote.py --auto         # 自动提升符合条件的

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import os
import re
import sys
import shutil
from datetime import datetime, timezone
from pathlib import Path


from _common import get_wiki_root as _get_wiki_root

WIKI_ROOT = _get_wiki_root()
QUERIES_DIR = os.path.join(WIKI_ROOT, "outputs", "queries")
RAW_DIR = os.path.join(WIKI_ROOT, "raw")

LINK_RE = re.compile(r"\[\[([^\]|#]+)(?:\|[^\]]+)?\]\]")


def _extract_query_metadata(content: str) -> dict:
    """从查询文件中提取元数据"""
    metadata = {"question": "", "answer_length": 0, "link_count": 0, "has_new_info": False, "timestamp": ""}

    # 提取问题（第一行 # 开头的标题）
    for line in content.split("\n"):
        if line.strip().startswith("#"):
            metadata["question"] = line.strip().lstrip("#").strip()
            break

    # 统计链接数量
    links = LINK_RE.findall(content)
    metadata["link_count"] = len(links)

    # 估算回答长度（排除标题和模板）
    lines = content.split("\n")
    answer_lines = []
    in_answer = False
    for line in lines:
        if line.strip().startswith("#") and not in_answer:
            continue
        if line.strip().startswith("##") or line.strip().startswith(">"):
            in_answer = True
        if in_answer and line.strip():
            answer_lines.append(line.strip())

    answer_text = " ".join(answer_lines)
    metadata["answer_length"] = len([c for c in answer_text if c.isalnum() or c.isspace()])

    # 判断是否有新信息（简单启发式：跨页面引用 + 长度）
    metadata["has_new_info"] = metadata["link_count"] >= 2 and metadata["answer_length"] > 400

    # 提取时间戳（文件名或元数据中）
    if "时间:" in content:
        time_match = re.search(r"时间:\s*(.+)", content)
        if time_match:
            metadata["timestamp"] = time_match.group(1).strip()

    return metadata


def _get_promote_candidates() -> list[dict]:
    """获取所有可提升的查询候选"""
    queries_path = Path(QUERIES_DIR)
    if not queries_path.exists():
        return []

    candidates = []
    for query_file in sorted(queries_path.glob("*.md")):
        try:
            content = query_file.read_text("utf-8", errors="replace")
        except OSError:
            continue

        metadata = _extract_query_metadata(content)
        metadata["file_path"] = str(query_file)
        metadata["file_name"] = query_file.name
        metadata["score"] = 0

        # 评分规则（总分100）
        # 1. 回答长度（40分）：>1000字=40, >500字=30, >200字=15, 其他=5
        if metadata["answer_length"] > 1000:
            metadata["score"] += 40
        elif metadata["answer_length"] > 500:
            metadata["score"] += 30
        elif metadata["answer_length"] > 200:
            metadata["score"] += 15
        else:
            metadata["score"] += 5

        # 2. 跨页面引用（30分）：>=3个=30, 2个=20, 1个=10, 0个=0
        if metadata["link_count"] >= 3:
            metadata["score"] += 30
        elif metadata["link_count"] == 2:
            metadata["score"] += 20
        elif metadata["link_count"] == 1:
            metadata["score"] += 10

        # 3. 新信息判断（30分）：有新信息=30, 否则=0
        if metadata["has_new_info"]:
            metadata["score"] += 30

        # 4. 提问质量（0/自动）
        # （暂时不自动评分，留给LLM判断）

        candidates.append(metadata)

    # 按分数降序排序
    candidates.sort(key=lambda x: x["score"], reverse=True)
    return candidates


def cmd_list() -> None:
    """列出可提升的查询"""
    candidates = _get_promote_candidates()

    if not candidates:
        print("📭 outputs/queries/ 目录为空或无可提升查询")
        return

    print(f"📋 可提升查询列表（共 {len(candidates)} 个）\n")

    for i, c in enumerate(candidates, 1):
        print(f"  [{i}] {c['file_name']}")
        print(f"      问题: {c['question']}")
        print(
            f"      长度: {c['answer_length']} 字 | 链接: {c['link_count']} | 新信息: {'是' if c['has_new_info'] else '否'}"
        )
        print(f"      评分: {c['score']}/100")
        print(f"      文件: {c['file_path']}")
        print()


def cmd_promote(file_path: str, force: bool = False) -> None:
    """提升指定查询为知识页面"""
    query_file = Path(file_path)
    if not query_file.exists():
        print(f"  ❌ 文件不存在: {file_path}")
        sys.exit(1)

    try:
        content = query_file.read_text("utf-8", errors="replace")
    except OSError:
        print(f"  ❌ 读取失败: {file_path}")
        sys.exit(1)

    metadata = _extract_query_metadata(content)

    # 生成新文件名（基于问题）
    safe_title = re.sub(r'[\\/:*?"<>|]', "_", metadata["question"])
    safe_title = re.sub(r"\s+", "-", safe_title.lower()).strip("-")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest_name = f"{safe_title}_{timestamp}.txt"
    dest_path = Path(RAW_DIR) / dest_name

    # 确认
    if not force:
        print(f"  📄 查询文件: {query_file.name}")
        print(f"  ❓ 问题: {metadata['question']}")
        print(f"  📊 评分: {metadata['score']}/100")
        print(f"  📝 目标: raw/{dest_name}")
        print()
        if sys.stdin.isatty():
            response = input("  ❓ 确认提升？(y/N): ").strip().lower()
            if response != "y":
                print("  ❌ 已取消")
                sys.exit(0)
        else:
            print("  ❌ 非交互模式，请使用 --force 参数")
            sys.exit(1)

    # 移动文件到 raw/
    Path(RAW_DIR).mkdir(parents=True, exist_ok=True)
    shutil.move(str(query_file), str(dest_path))
    print(f"  ✅ 已移动到: raw/{dest_name}")

    # 更新缓存
    cache_script = Path(__file__).parent / "cache.py"
    if cache_script.exists():
        import subprocess

        result = subprocess.run(
            [sys.executable, str(cache_script), "update", str(dest_path)], capture_output=True, text=True
        )
        if result.returncode != 0:
            print(f"  ⚠️  缓存更新失败: {result.stderr.strip()}")
    else:
        print("  ⚠️  cache.py 不存在，跳过缓存更新")

    # 输出编译指引
    print()
    print("  💡 下一步:")
    print("     1. LLM  编译流程触发")
    print("     2. python scripts/compile_post.py")


def cmd_auto(threshold: int = 60) -> None:
    """自动提升符合条件的查询"""
    candidates = _get_promote_candidates()

    if not candidates:
        print("📭 无可提升查询")
        return

    # 过滤高分查询
    auto_promote = [c for c in candidates if c["score"] >= threshold]

    if not auto_promote:
        print(f"📭 无查询达到提升阈值（{threshold}分）")
        print(f"   最高分: {candidates[0]['score']}/100")
        return

    print(f"🚀 自动提升（阈值: {threshold}分）| 共 {len(auto_promote)} 个\n")

    for c in auto_promote:
        print(f"  提升: {c['file_name']} ({c['score']}分)")
        try:
            cmd_promote(c["file_path"], force=True)
        except Exception as e:
            print(f"  ❌ 提升失败: {e}")
        print()


# ── 主入口 ──


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n用法:")
        print("  python promote.py --list               # 列出可提升的查询")
        print("  python promote.py --promote <file>     # 指定文件提升")
        print("  python promote.py --auto [--threshold N]  # 自动提升（默认60分）")
        sys.exit(1)

    if "--list" in sys.argv:
        cmd_list()
    elif "--promote" in sys.argv:
        force = "--force" in sys.argv
        # 提取文件路径（去除所有选项）
        args = [a for a in sys.argv[1:] if not a.startswith("--")]
        if not args:
            print("  ❌ 请指定要提升的查询文件")
            sys.exit(1)
        cmd_promote(args[0], force=force)
    elif "--auto" in sys.argv:
        threshold = 60
        if "--threshold" in sys.argv:
            idx = sys.argv.index("--threshold")
            if idx + 1 < len(sys.argv):
                try:
                    threshold = int(sys.argv[idx + 1])
                except ValueError:
                    print(f"  ❌ 阈值必须是数字: {sys.argv[idx + 1]}")
                    sys.exit(1)
        cmd_auto(threshold)
    else:
        print(f"  ❌ 未知参数: {sys.argv[1]}")
        print("  可用: --list | --promote | --auto")
        sys.exit(1)


if __name__ == "__main__":
    main()
