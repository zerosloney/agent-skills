#!/usr/bin/env python3
"""
动态权重更新 — 基于用户反馈调整搜索结果权重

用途：
   读取 feedback_log.yaml，分析用户点击和满意度数据，
   为每个页面计算动态权重并更新 search_index.db 中的 wiki_pages.weight 字段。
   权重越高，该页面在搜索结果中排序越靠前。

用法:
    # 更新权重（默认动作）
    python scripts/update_weights.py

    # 查看当前权重分布
    python scripts/update_weights.py --show

    # 重置所有权重为 1.0
    python scripts/update_weights.py --reset

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）

权重算法:
    base = 1.0
    click_bonus = 0.15 * click_count          # 每次点击 +0.15
    helpful_bonus = 0.25 * helpful_count      # 每次 helpful=yes +0.25
    impression_bonus = -0.05 * impression_count  # 每次展示了但没点 -0.05
    weight = max(0.3, min(5.0, base + click_bonus + helpful_bonus + impression_bonus))

    限制范围 [0.3, 5.0] 防止极端值。
"""

import os
import sys
import yaml
import json
import sqlite3
from pathlib import Path
from collections import defaultdict


from _common import get_wiki_root as _get_wiki_root


def _get_feedback_file():
    return os.path.join(_get_wiki_root(), "feedback_log.yaml")


def _get_index_db():
    return os.path.join(_get_wiki_root(), "search_index.db")


def _get_weights_output():
    return os.path.join(_get_wiki_root(), "page_weights.json")


# ============================================================================
# 权重计算
# ============================================================================


def _load_feedback() -> list[dict]:
    """加载反馈日志"""
    p = Path(_get_feedback_file())
    if not p.exists():
        return []
    try:
        with open(p, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, list):
            return []
        return data
    except Exception as e:
        print(f"⚠️  读取反馈日志失败: {e}")
        return []


def compute_weights() -> dict[str, float]:
    """
    基于反馈日志计算每个文件的权重。

    统计维度:
    - click_count: 被用户点击次数
    - helpful_count: 被标记为 helpful=yes 的次数
    - impression_count: 被展示但未被点击的次数（仅统计 click_index >= 0 的条目中未被点击的页面）

    Returns:
        {file_path: weight}
    """
    log = _load_feedback()
    if not log:
        return {}

    # 统计：每个页面在每条反馈中的角色
    clicked_count = defaultdict(int)
    helpful_count = defaultdict(int)
    impress_no_click = defaultdict(int)
    total_impressions = defaultdict(int)

    for entry in log:
        results = entry.get("results", [])
        click_idx = entry.get("click_index", -1)
        helpful = entry.get("helpful", "yes")

        # 记录每个页面的展示次数
        for r in results:
            total_impressions[r] += 1

        # 有点击：被点击的页面加分，其他展示但没被点的减分
        if 0 <= click_idx < len(results):
            clicked_page = results[click_idx]
            clicked_count[clicked_page] += 1
            if helpful == "yes":
                helpful_count[clicked_page] += 1

            # 其他展示但没被点击的页面
            for i, r in enumerate(results):
                if i != click_idx:
                    impress_no_click[r] += 1
        else:
            # 无点击：所有展示页面都未命中
            for r in results:
                impress_no_click[r] += 1

    # 计算权重
    weights = {}
    all_pages = set(clicked_count.keys()) | set(helpful_count.keys()) | set(total_impressions.keys())

    for page in all_pages:
        base = 1.0
        click_bonus = 0.15 * clicked_count.get(page, 0)
        helpful_bonus = 0.25 * helpful_count.get(page, 0)
        penalty = -0.05 * impress_no_click.get(page, 0)

        weight = base + click_bonus + helpful_bonus + penalty
        weight = max(0.3, min(5.0, weight))  # 夹紧
        weights[page] = round(weight, 2)

    return weights


# ============================================================================
# 更新搜索索引
# ============================================================================


def update_search_index(weights: dict[str, float]) -> tuple[int, int]:
    """
    将权重写入 search_index.db 的 wiki_pages.weight 列。

    Returns:
        (updated, total) 成功更新的行数，总行数
    """
    db_path = Path(_get_index_db())
    if not db_path.exists():
        print(f"⚠️  搜索索引不存在: {_get_index_db()}")
        return (0, 0)

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        # 检查 weight 列是否存在
        cols = [row["name"] for row in conn.execute("PRAGMA table_info(wiki_pages)").fetchall()]
        if "weight" not in cols:
            conn.execute("ALTER TABLE wiki_pages ADD COLUMN weight REAL DEFAULT 1.0")
            conn.commit()
            print("  📦 weight 列已添加到 wiki_pages 表")

        # 获取所有页面
        all_pages = conn.execute("SELECT id, file_path FROM wiki_pages").fetchall()
        total = len(all_pages)
        updated = 0

        for row in all_pages:
            file_path = row["file_path"]
            db_name = Path(file_path).name
            matched_weight = None
            for key, w in weights.items():
                if key == db_name or key == file_path:
                    matched_weight = w
                    break

            if matched_weight is not None:
                conn.execute(
                    "UPDATE wiki_pages SET weight = ? WHERE id = ?",
                    (matched_weight, row["id"]),
                )
                updated += 1
            else:
                # 没有反馈数据的页面保持默认
                conn.execute(
                    "UPDATE wiki_pages SET weight = 1.0 WHERE id = ? AND weight IS NULL",
                    (row["id"],),
                )

        conn.commit()
        return (updated, total)
    finally:
        conn.close()


# ============================================================================
# 输出权重文件
# ============================================================================


def save_weights_json(weights: dict[str, float]) -> None:
    """将权重保存为 JSON 文件（供 search_engine.py 或其他工具读取）"""
    if not weights:
        return
    with open(_get_weights_output(), "w", encoding="utf-8") as f:
        json.dump(weights, f, ensure_ascii=False, indent=2)
    print(f"  📄 权重文件已写入: {_get_weights_output()}")


# ============================================================================
# 显示
# ============================================================================


def show_weights(weights: dict[str, float]) -> None:
    """展示当前权重分布"""
    if not weights:
        print("📊 无权重数据")
        return

    sorted_w = sorted(weights.items(), key=lambda x: -x[1])
    print(f"\n📊 权重分布 ({len(sorted_w)} 个页面)")
    print(f"{'=' * 50}")
    print(f"  {'页面':<40} {'权重':>6}")
    print(f"  {'-' * 40} {'-' * 6}")
    for page, w in sorted_w:
        bar = "█" * int(w * 4)
        print(f"  {page:<40} {w:>5.2f}  {bar}")

    if sorted_w:
        avg = sum(w for _, w in sorted_w) / len(sorted_w)
        print(f"\n  平均权重: {avg:.2f}")
        print(f"  最高: {sorted_w[0][1]:.2f} ({sorted_w[0][0]})")
        print(f"  最低: {sorted_w[-1][1]:.2f} ({sorted_w[-1][0]})")


def show_db_weights() -> None:
    """从数据库直接显示权重"""
    db_path = Path(_get_index_db())
    if not db_path.exists():
        print("⚠️  搜索索引不存在")
        return

    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            "SELECT file_path, title, weight FROM wiki_pages WHERE weight != 1.0 ORDER BY weight DESC"
        ).fetchall()
        if not rows:
            print("📊 所有页面权重均为默认值 1.0（尚无反馈数据）")
            return

        print("\n📊 数据库权重（非默认值）")
        print(f"{'=' * 50}")
        print(f"  {'页面':<45} {'权重':>6}")
        print(f"  {'-' * 45} {'-' * 6}")
        for r in rows:
            bar = "█" * int(r["weight"] * 4)
            name = Path(r["file_path"]).name if r["file_path"] else r["title"]
            print(f"  {name:<45} {r['weight']:>5.2f}  {bar}")
    finally:
        conn.close()


# ============================================================================
# 重置权重
# ============================================================================


def reset_weights() -> bool:
    """重置所有权重为 1.0"""
    db_path = Path(_get_index_db())
    if not db_path.exists():
        print("⚠️  搜索索引不存在")
        return False

    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute("UPDATE wiki_pages SET weight = 1.0")
        conn.commit()
        print("✅ 所有权重已重置为 1.0")
        return True
    except Exception as e:
        print(f"❌ 重置失败: {e}")
        return False
    finally:
        conn.close()


# ============================================================================
# CLI 主入口
# ============================================================================


def main():
    if len(sys.argv) > 1:
        arg = sys.argv[1].lower()
    else:
        arg = "update"

    if arg == "--show":
        # 先显示计算出的权重
        weights = compute_weights()
        show_weights(weights)
        print()
        show_db_weights()
    elif arg == "--reset":
        confirm = input("⚠️  确定重置所有权重为 1.0？(yes/no): ")
        if confirm.lower() == "yes":
            reset_weights()
        else:
            print("已取消")
    elif arg == "update" or arg == "--update":
        print(f"🔄 更新搜索权重 | wiki_root: {_get_wiki_root()}")
        weights = compute_weights()
        if not weights:
            print("  ℹ️  无反馈数据，跳过权重更新")
            return

        print(f"  反馈数据分析完成: {len(weights)} 个页面有影响")

        updated, total = update_search_index(weights)
        print(f"  ✅ 搜索索引已更新: {updated}/{total} 行")

        save_weights_json(weights)
        print("  ✅ 权重更新完成")

        # 展示 Top 5 变化
        sorted_w = sorted(weights.items(), key=lambda x: -x[1])
        if sorted_w:
            print("\n📈 权重提升 Top 3:")
            for page, w in sorted_w[:3]:
                print(f"  +{w - 1.0:+.2f}  {page}")
    else:
        print(f"未知参数: {arg}")
        print("用法: python scripts/update_weights.py [--show | --reset | --update]")


if __name__ == "__main__":
    main()
