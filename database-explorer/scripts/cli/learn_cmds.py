#!/usr/bin/env python3
"""
cli.learn_cmds - 学习数据管理命令

实现 learn 子命令：
  show   — 查看学习数据摘要
  clear  — 清除所有学习数据
  approve — 将学习别名提升到 hot_tables.yaml
"""

import sys
import argparse
from pathlib import Path

from _query_learning import (
    get_learned_aliases,
    clear_learned,
    load_learned_aliases,
)
from _scoring import hot_tables_path_for_config


def cmd_learn(args: argparse.Namespace) -> None:
    """管理学习数据"""
    action = args.action or "show"

    if action == "show":
        _learn_show(args)
    elif action == "clear":
        _learn_clear(args)
    elif action == "approve":
        _learn_approve(args)
    elif action == "delete":
        _learn_delete(args)
    else:
        print(f"ERROR: 未知 action '{action}'，可选: show / clear / approve / delete", file=sys.stderr)
        sys.exit(1)


def _learn_show(args: argparse.Namespace) -> None:
    """显示学习数据摘要（用户友好格式，不暴露内部字段）"""
    aliases = get_learned_aliases()
    if not aliases:
        print("暂无学习数据（执行带 --learn 的 query 后自动生成）")
        return

    print(f"学习数据 ({len(aliases)} 张表，频率 ≥ {__import__('_query_learning').MIN_FREQ_FOR_SCORING}):\n")
    for tname, info in sorted(aliases.items()):
        freq = info.get("_freq", 0)
        als = info.get("aliases", [])
        als_str = ", ".join(als) if als else "(无别名)"
        print(f"  {tname}（访问 {freq} 次）")
        if als:
            print(f"    别名: {als_str}")


def _learn_clear(args: argparse.Namespace) -> None:
    """清除所有学习数据"""
    clear_learned()
    print("学习数据已清除")


def _learn_delete(args: argparse.Namespace) -> None:
    """删除指定表的学习数据（不影响其他表）"""
    table = getattr(args, "table", None)
    if not table:
        print("ERROR: delete 需要 --table 指定表名", file=sys.stderr)
        sys.exit(1)

    from _query_learning import _DEFAULT_LEARNED_PATH

    p = _DEFAULT_LEARNED_PATH
    if not p.is_file():
        print(f"无学习数据文件（{p}）", file=sys.stderr)
        sys.exit(1)

    try:
        import yaml

        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    except Exception as e:
        print(f"ERROR: 读取学习数据失败: {e}", file=sys.stderr)
        sys.exit(1)

    learned = data.get("learned", {})
    removed = False

    # 从 table_frequency 删除
    freq = learned.get("table_frequency", {})
    if table in freq:
        del freq[table]
        removed = True

    # 从 column_groups 删除
    col_groups = learned.get("column_groups", {})
    if table in col_groups:
        del col_groups[table]
        removed = True

    # 从 associations 删除含该表的关联对
    assocs = learned.get("associations", [])
    new_assocs = [a for a in assocs if not (isinstance(a, (list, tuple)) and table in a)]
    if len(new_assocs) != len(assocs):
        learned["associations"] = new_assocs
        removed = True

    # 从 column_enums 删除该表的枚举
    col_enums = learned.get("column_enums", {})
    keys_to_remove = [k for k in col_enums if k.startswith(table.lower() + ".")]
    for k in keys_to_remove:
        del col_enums[k]
        removed = True

    if not removed:
        print(f"表 '{table}' 在学习数据中不存在")
        return

    # 写回
    try:
        p.write_text(yaml.dump(data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
        print(f"已删除表 '{table}' 的学习数据")
    except Exception as e:
        print(f"ERROR: 写入失败: {e}", file=sys.stderr)
        sys.exit(1)


def _learn_approve(args: argparse.Namespace) -> None:
    """将学习别名提升到 hot_tables.yaml（人工确认后永久生效）"""
    table = getattr(args, "table", None)
    if not table:
        print("ERROR: approve 需要 --table <表名>", file=sys.stderr)
        sys.exit(1)

    learned = load_learned_aliases()
    entry = learned.get(table)
    if not entry:
        print(f"ERROR: 表中未找到学习别名 '{table}'，先用 learn show 查看可用表名", file=sys.stderr)
        sys.exit(1)

    aliases = entry.get("aliases", [])
    if not aliases:
        print(f"ERROR: 表 '{table}' 没有可提升的别名", file=sys.stderr)
        sys.exit(1)

    # 读取 hot_tables.yaml，追加别名
    hot_path = hot_tables_path_for_config({}) or (Path(__file__).resolve().parent.parent / "references" / "hot_tables.yaml")
    try:
        import yaml

        if hot_path.is_file():
            hot_data = yaml.safe_load(hot_path.read_text(encoding="utf-8")) or {}
        else:
            hot_data = {}
        hot_tables = hot_data.setdefault("hot_tables", {})
    except Exception as e:
        print(f"ERROR: 读取 hot_tables.yaml 失败: {e}", file=sys.stderr)
        sys.exit(1)

    existing = hot_tables.get(table, {})
    if not isinstance(existing, dict):
        # existing is a plain string (legacy format) — normalize to dict
        existing = {}
    existing_aliases = existing.get("aliases", [])
    if isinstance(existing_aliases, list):
        existing_aliases = [a.get("term", a) if isinstance(a, dict) else a for a in existing_aliases]

    added = []
    for alias in aliases:
        if alias not in existing_aliases:
            existing_aliases.append(alias)
            added.append(alias)

    if added:
        hot_tables[table] = {**existing, "aliases": existing_aliases}
        try:
            hot_path.parent.mkdir(parents=True, exist_ok=True)
            hot_path.write_text(yaml.dump(hot_data, allow_unicode=True, default_flow_style=False), encoding="utf-8")
            print(f"已将 {len(added)} 个别名从学习数据提升到 hot_tables.yaml [{table}]:")
            for a in added:
                print(f"  + {a}")
        except Exception as e:
            print(f"ERROR: 写入 hot_tables.yaml 失败: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        print(f"表 '{table}' 的别名已全部存在于 hot_tables.yaml 中，无需更新")
