#!/usr/bin/env python3
"""
cli.safe - 安全工具

提供 SQL 危险操作确认、查询安全检查等功能。
"""

from _security import split_statements, check_read_only


def confirm_danger(sql: str, confirmed: bool = False) -> bool:
    """对危险 SQL 做交互式确认，返回 True=允许执行

    检查所有语句（不仅是首句），任一语句含写操作即触发确认。
    多语句场景下，即使首句是 SELECT，后续 INSERT/UPDATE 等仍需确认。

    Args:
        sql: SQL 语句（可能含多条分号分隔语句）
        confirmed: 非交互预确认标志（--yes）。为 True 时跳过交互直接放行，
            用于 Agent 通过 subprocess 调用时无需 TTY 即可执行已确认的写操作。
    """
    has_write = False
    first_write_kw = ""
    for stmt in split_statements(sql):
        is_ro, kw, reason = check_read_only(stmt, strict=True)
        if not is_ro:
            has_write = True
            first_write_kw = kw
            break
    if not has_write:
        return True
    if confirmed:
        return True
    prompt = f"检测到写操作语句 ({first_write_kw})，确认执行？(yes/no): "
    try:
        ans = input(prompt).strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def confirm_overwrite(filepath: str, confirmed: bool = False) -> bool:
    """文件覆写确认：目标文件已存在时询问是否覆盖。

    Args:
        filepath: 目标文件路径
        confirmed: 非交互预确认标志（--yes）。为 True 时跳过交互直接放行，
            适用于 Agent 已在聊天层向用户确认的场景。
    """
    import os

    if not os.path.exists(filepath):
        return True  # 不存在，无需确认
    if confirmed:
        return True
    prompt = f"文件 '{filepath}' 已存在，是否覆盖？(yes/no): "
    try:
        ans = input(prompt).strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def is_read_only_sql(sql: str) -> bool:
    """检查 SQL 是否为只读

    Args:
        sql: SQL 语句

    Returns:
        True=只读, False=包含写操作
    """
    return all(check_read_only(stmt, strict=True)[0] for stmt in split_statements(sql))
