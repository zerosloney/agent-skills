#!/usr/bin/env python3
"""
cli.query_cmds - 查询执行命令

实现 query、export 等查询相关的 CLI 命令。
"""

import sys
import argparse
import logging
import re

from core.connection import get_connection
from _drivers import execute_query
from _formatters import format_result, _sanitize_csv_value, _normalize

logger = logging.getLogger(__name__)
from _security import (
    check_read_only,
    count_statements,
    split_statements,
    is_full_table_scan,
    is_protected_path,
)
from _query_learning import record_query
from core.history import append_history
from .safe import confirm_danger, confirm_overwrite


def _write_or_scan_confirmation(args) -> tuple[bool, bool]:
    """对 query 命令统一做写操作 + 全表扫描确认。

    多语句 SQL：逐条安全检查（替代一刀切拒绝）。
    每条语句独立做 check_read_only + 全表扫描检测。
    任一条语句触发写操作 → 整体视为写操作，需 --yes 确认。
    混合只读+写语句 → 写操作确认后逐条执行。

    Returns:
        (is_write, proceed): is_write 标识是否含写操作，
        proceed=False 表示用户取消或被拦截。
    """
    stmts = split_statements(args.sql)
    if not stmts:
        print("ERROR: 空语句", file=sys.stderr)
        return False, False

    confirmed = bool(getattr(args, "yes", False))

    is_write = False
    for stmt in stmts:
        is_ro, first_kw, reason = check_read_only(stmt, strict=True)
        if not is_ro:
            is_write = True
            break

    if is_write:
        if not confirm_danger(args.sql, confirmed=confirmed):
            print("用户取消执行", file=sys.stderr)
            return is_write, False

    for stmt in stmts:
        if not check_read_only(stmt, strict=True)[0]:
            continue
        if is_full_table_scan(stmt):
            print("警告: 检测到无 WHERE/LIMIT 的全表 SELECT * 扫描，大表上可能很慢。", file=sys.stderr)
            if not confirmed:
                try:
                    ans = input("确认继续全表扫描？(yes/no): ").strip().lower()
                except EOFError:
                    print("用户取消执行（无 TTY 且未传 --yes）", file=sys.stderr)
                    return is_write, False
                if ans not in ("y", "yes"):
                    print("用户取消执行", file=sys.stderr)
                    return is_write, False
            break

    return is_write, True


def cmd_query(args: argparse.Namespace) -> None:
    """执行 SQL 查询（支持多语句逐条执行）"""
    is_write, proceed = _write_or_scan_confirmation(args)
    if not proceed:
        return

    conn, cfg = get_connection()
    try:
        db_type = cfg.get("db_type", "sqlserver")
        fmt = args.format or "table"
        max_rows = args.max_rows or 1000
        offset = args.offset or 0

        stmts = split_statements(args.sql)
        if not stmts:
            print("ERROR: 空语句", file=sys.stderr)
            return

        query_timeout = getattr(args, "timeout", None)

        if len(stmts) == 1:
            sql = stmts[0]
            if not is_write:
                sql = _add_pagination(sql, db_type, max_rows, offset)
            result = execute_query(conn, sql, max_rows=max_rows, query_timeout=query_timeout)
            print(format_result(result, fmt=fmt, title="查询结果"))
            # 与多语句路径保持一致，便于下方学习分支统一读取
            all_results = [result]
        else:
            all_results = []
            for i, stmt in enumerate(stmts, 1):
                stmt_is_write = not check_read_only(stmt, strict=True)[0]
                sql = stmt
                if not stmt_is_write:
                    sql = _add_pagination(sql, db_type, max_rows, offset)
                result = execute_query(conn, sql, max_rows=max_rows, query_timeout=query_timeout)
                result["_statement_index"] = i
                all_results.append(result)

            if fmt in ("json", "json-compact"):
                combined = {
                    "success": all(r.get("success", False) for r in all_results),
                    "statements": len(all_results),
                    "results": all_results,
                }
                print(format_result(combined, fmt=fmt, title="多语句结果"))
            else:
                for r in all_results:
                    idx = r.pop("_statement_index", 0)
                    print(f"\n--- 语句 {idx}/{len(all_results)} ---")
                    print(format_result(r, fmt=fmt, title=""))

        # 记录到 history（与 REPL 行为一致：记录完整命令原文，含失败的语句）
        append_history(args.sql)

        # 学习模式：记录 SQL 结构知识
        if getattr(args, "learn", False):
            try:
                # 判定成功：单语句成功，或多语句全部成功
                # 注意：all_results 是一个包含 execute_query 返回值的列表
                is_success = False
                if len(stmts) == 1:
                    res = all_results[0]
                    is_success = res.get("success", False)
                    duration = res.get("duration", 0.0)
                else:
                    is_success = all(r.get("success", False) for r in all_results)
                    # 多语句学习记录取最慢单句耗时（max），而非 sum：
                    # 学习数据按表记录"典型查询耗时画像"，sum 会把多表 JOIN
                    # 的累计耗时归因到首表，误导 perf_metrics 的 avg/max_duration。
                    duration = max((r.get("duration", 0.0) for r in all_results), default=0.0)

                record_query(args.sql, success=is_success, duration=duration)
                logger.info("Learned from query (success=%s, dur=%.3fs): %s...", is_success, duration, args.sql[:80])
            except Exception as e:
                logger.warning("Failed to record query learning: %s", e)
    finally:
        conn.dispose()


def _add_pagination(sql: str, db_type: str, max_rows: int, offset: int) -> str:
    """为只读 SQL 追加分页语法（写操作不追加）。"""
    if db_type == "sqlserver":
        upper = sql.upper()
        _has_top = re.search(r"\bTOP\s+\d", upper) or "ROWCOUNT" in upper
        if not _has_top:
            if "ORDER BY" not in upper:
                sql += " ORDER BY (SELECT NULL)"
            sql += f" OFFSET {int(offset)} ROWS FETCH NEXT {int(max_rows)} ROWS ONLY"
    else:
        upper = sql.upper()
        if "LIMIT" not in upper:
            sql += f" LIMIT {int(max_rows)}"
            if offset > 0:
                sql += f" OFFSET {int(offset)}"
    return sql


def cmd_export(args: argparse.Namespace) -> None:
    """导出查询结果为 CSV

    安全护栏（对应 SKILL.md §4）：
    1. 多语句 SQL 拒绝（§4.5）
    2. 仅允许只读 SELECT，写操作拒绝（§4.1 的扩展：export 不可用于写）
    3. 禁止导出到系统保护目录（§4.9）
    4. 目标文件已存在时确认覆写（§4.8）
    """
    # 1. 多语句守卫：export 仍只允许单条 SELECT
    if count_statements(args.sql) > 1:
        print("ERROR: export 仅支持单条 SELECT，不支持多语句", file=sys.stderr)
        return

    # 2. 只读守卫：export 仅允许 SELECT，禁止任何写操作
    is_ro, first_kw, reason = check_read_only(args.sql, strict=True)
    if not is_ro:
        print(
            f"ERROR: export 仅允许 SELECT 查询，检测到写操作 ({first_kw})，已拒绝。",
            file=sys.stderr,
        )
        return

    # 3. 路径守卫：禁止系统保护目录
    filepath = args.filepath
    if is_protected_path(filepath):
        print(
            f"ERROR: 禁止导出到系统保护目录（Windows/Program Files/etc 等）。目标路径 '{filepath}' 被拦截。",
            file=sys.stderr,
        )
        return

    # 4. 覆写守卫
    confirmed = bool(getattr(args, "yes", False))
    if not confirm_overwrite(filepath, confirmed=confirmed):
        print("用户取消执行（拒绝覆写目标文件）", file=sys.stderr)
        return

    conn, cfg = get_connection()
    try:
        result = execute_query(conn, args.sql, max_rows=100000)
        if not result["success"]:
            print(format_result(result))
            return

        encoding = args.encoding or "utf-8-sig"

        cols = result.get("columns", [])
        rows = result.get("rows", [])

        import csv

        with open(filepath, "w", newline="", encoding=encoding) as f:
            writer = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
            writer.writeheader()
            for row in rows:
                # 与 _formatters._to_csv 一致：每格先 normalize(bytes/UUID) 再防公式注入
                writer.writerow({c: _sanitize_csv_value(_normalize(row.get(c, ""))) for c in cols})

        print(f"已导出 {len(rows)} 行到 {filepath}")
        if result.get("truncated"):
            print(
                "警告: 结果超过导出上限(100000 行)被截断,文件不完整。如需全量导出,请加 WHERE/LIMIT 缩小范围或分批导出。",
                file=sys.stderr,
            )
    finally:
        conn.dispose()
