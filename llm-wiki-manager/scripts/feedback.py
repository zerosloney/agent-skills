#!/usr/bin/env python3
"""
搜索反馈日志 — 记录用户对搜索结果的点击和满意度

用途：
   每次 Agent 向用户展示搜索结果并得到反馈后调用此脚本记录，
   积累的数据用于 update_weights.py 自动调优搜索结果排序。

用法:
    # 记录点击反馈
    python scripts/feedback.py log \\
        --query "什么是Rust异步" \\
        --results "async-await.md,rust-future.md,tokio-overview.md" \\
        --click 1 \\
        --helpful yes

    # 记录无帮助的搜索
    python scripts/feedback.py log \\
        --query "Python协程原理" \\
        --results "python-async.md,coroutine-basics.md" \\
        --click 0 \\
        --helpful no

    # 查看统计
    python scripts/feedback.py stats

    # 清空日志（需要确认）
    python scripts/feedback.py clear

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import os
import sys
import yaml
from pathlib import Path
from datetime import datetime, timezone
from collections import defaultdict


from _common import get_wiki_root as _get_wiki_root


def _get_feedback_file():
    return os.path.join(_get_wiki_root(), "feedback_log.yaml")


# ============================================================================
# 日志读写
# ============================================================================


def _load_log() -> list[dict]:
    """加载已有反馈日志"""
    p = Path(_get_feedback_file())
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, list):
            return []
        return data
    except Exception:
        return []


def _save_log(entries: list[dict]) -> None:
    """保存反馈日志"""
    p = Path(_get_feedback_file())
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "w", encoding="utf-8") as f:
        yaml.dump(entries, f, allow_unicode=True, default_flow_style=False, sort_keys=False)


# ============================================================================
# 记录反馈
# ============================================================================


def log_feedback(
    query: str,
    results: list[str],
    click: int = 0,
    helpful: str = "yes",
    note: str = "",
) -> dict:
    """
    记录一条搜索反馈。

    Args:
        query:   用户原始查询
        results: 展示给用户的页面列表（文件名或路径）
        click:   用户点击的索引（0-based, -1 表示无点击）
        helpful: "yes" | "partial" | "no"
        note:    可选备注

    Returns:
        记录后的日志条目
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "query": query,
        "results": results,
        "click_index": click,
        "helpful": helpful,
    }
    if note:
        entry["note"] = note

    log = _load_log()
    log.append(entry)
    _save_log(log)

    return entry


# ============================================================================
# 统计
# ============================================================================


def compute_stats() -> dict:
    """基于反馈日志计算统计信息"""
    log = _load_log()
    if not log:
        return {"total": 0, "message": "尚无反馈记录"}

    total = len(log)
    helpful_count = sum(1 for e in log if e.get("helpful") == "yes")
    partial_count = sum(1 for e in log if e.get("helpful") == "partial")
    no_count = sum(1 for e in log if e.get("helpful") == "no")
    click_count = sum(1 for e in log if e.get("click_index", -1) >= 0)

    # 按页面统计点击
    page_clicks = defaultdict(int)
    page_helpful = defaultdict(int)
    for e in log:
        idx = e.get("click_index", -1)
        results = e.get("results", [])
        if 0 <= idx < len(results):
            clicked = results[idx]
            page_clicks[clicked] += 1
            if e.get("helpful") == "yes":
                page_helpful[clicked] += 1

    # 按页面统计展示次数
    page_impressions = defaultdict(int)
    for e in log:
        for r in e.get("results", []):
            page_impressions[r] += 1

    # 热门查询
    query_counts = defaultdict(int)
    for e in log:
        query_counts[e.get("query", "")] += 1
    top_queries = sorted(query_counts.items(), key=lambda x: -x[1])[:10]

    return {
        "total": total,
        "helpful": helpful_count,
        "partial": partial_count,
        "not_helpful": no_count,
        "with_click": click_count,
        "helpful_rate": round(helpful_count / total * 100, 1) if total > 0 else 0,
        "top_queries": top_queries,
        "page_clicks": dict(sorted(page_clicks.items(), key=lambda x: -x[1])[:20]),
        "page_impressions": dict(sorted(page_impressions.items(), key=lambda x: -x[1])[:20]),
    }


# ============================================================================
# CLI 主入口
# ============================================================================


def main():
    if len(sys.argv) < 2:
        print("用法: python scripts/feedback.py <command> [args...]")
        print()
        print("命令:")
        print("  log      记录一条反馈")
        print("    --query <查询词>")
        print("    --results <逗号分隔的结果文件名>")
        print("    --click <点击索引(0-based), -1=无点击>")
        print("    --helpful <yes|partial|no>")
        print("    --note <备注(可选)>")
        print()
        print("  stats    查看统计摘要")
        print("  clear    清空日志（需要确认）")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "log":
        query = ""
        results = []
        click = -1
        helpful = "yes"
        note = ""

        args = sys.argv[2:]
        i = 0
        while i < len(args):
            if args[i] == "--query" and i + 1 < len(args):
                query = args[i + 1]
                i += 2
            elif args[i] == "--results" and i + 1 < len(args):
                results = [r.strip() for r in args[i + 1].split(",") if r.strip()]
                i += 2
            elif args[i] == "--click" and i + 1 < len(args):
                click = int(args[i + 1])
                i += 2
            elif args[i] == "--helpful" and i + 1 < len(args):
                helpful = args[i + 1].lower()
                if helpful not in ("yes", "partial", "no"):
                    print(f"⚠️ 无效的 helpful 值: {helpful}，可选: yes|partial|no")
                    sys.exit(1)
                i += 2
            elif args[i] == "--note" and i + 1 < len(args):
                note = args[i + 1]
                i += 2
            else:
                i += 1

        if not query:
            print("❌ 必须提供 --query")
            sys.exit(1)

        entry = log_feedback(query, results, click, helpful, note)
        print(
            f"✅ 反馈已记录 ({len(entry.get('results', []))} 个结果, 点击 #{entry['click_index']}, helpful={entry['helpful']})"
        )

    elif cmd == "stats":
        stats = compute_stats()
        if "message" in stats:
            print(f"📊 {stats['message']}")
            sys.exit(0)

        print("\n📊 搜索反馈统计")
        print(f"{'=' * 50}")
        print(f"  总反馈数:       {stats['total']}")
        print(f"  有帮助:         {stats['helpful']} ({stats['helpful_rate']}%)")
        print(f"  部分有帮助:     {stats['partial']}")
        print(f"  无帮助:         {stats['not_helpful']}")
        print(f"  有点击:         {stats['with_click']}")

        print("\n🏆 热门查询 (Top 10):")
        for q, c in stats["top_queries"]:
            print(f"  {c}x  {q[:60]}")

        if stats.get("page_clicks"):
            print("\n👆 页面点击次数 (Top 10):")
            for page, c in list(stats["page_clicks"].items())[:10]:
                imp = stats["page_impressions"].get(page, 0)
                rate = round(c / imp * 100, 1) if imp > 0 else 0
                print(f"  {c}x  {page}  (展示 {imp}x, CT={rate}%)")

    elif cmd == "clear":
        confirm = input("⚠️  确定清空所有反馈日志？(yes/no): ")
        if confirm.lower() == "yes":
            _save_log([])
            print("✅ 反馈日志已清空")
        else:
            print("已取消")

    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
