#!/usr/bin/env python3
"""
cli.data_cmds - 数据分析命令

实现 search、find、sample、profile、history 等数据分析命令。
"""

import sys
import argparse
import logging

logger = logging.getLogger(__name__)

from core.config import CONFIG_DIR
from core.connection import get_connection
from _drivers import execute_query, default_schema
from _formatters import format_result
from _security import quote_ident, check_read_only, count_statements


def _search_semantic(args: argparse.Namespace) -> None:
    """语义搜索表（search 命令入口，代理到 _build_semantic_payload 消除代码重复）。"""
    from .explore_cmds import _build_semantic_payload

    conn, cfg = get_connection()
    query = args.semantic
    limit = args.limit or 5
    fmt = getattr(args, "format", "table") or "table"

    try:
        payload = _build_semantic_payload(conn, cfg, query, limit, enable_level2=False)

        if fmt in ("json-compact", "json"):
            print(format_result(payload, fmt=fmt))
            return

        matches = payload.get("matches", [])
        if not matches:
            msg = f"未找到与 '{query}' 相关的表"
            if payload.get("hint"):
                msg += f"\n{payload['hint']}"
            print(msg)
            return

        total = payload.get("total_matched", len(matches))
        print(f"语义搜索: '{query}' → {min(limit, len(matches))}/{total} 个匹配")
        for rank, m in enumerate(matches, 1):
            cols = m.get("columns", [])
            fks = m.get("fk_targets", [])
            tag = f" [{m['type']}]" if m.get("type") else ""
            print(f"\n{rank}. **{m['name']}**{tag}  [{m['score']:.1f}]")
            print(f"   {len(cols)} 列: {', '.join(cols)}" + (" ..." if m.get("columns_truncated") else ""))
            if m.get("comment"):
                print(f"   说明: {m['comment']}")
            if fks:
                print(f"   FK → {', '.join(fks)}")

    finally:
        conn.dispose()


def cmd_search(args: argparse.Namespace) -> None:
    """搜索表名"""
    # 语义搜索路径
    if args.semantic:
        _search_semantic(args)
        return

    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    pattern = args.pattern or "%"

    try:
        if db_type == "sqlite":
            result = execute_query(
                conn,
                "SELECT name AS TABLE_NAME, type AS TABLE_TYPE FROM sqlite_master "
                "WHERE type IN ('table', 'view') AND name LIKE ? "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name",
                params=(pattern,),
            )
        elif db_type == "mysql":
            result = execute_query(
                conn,
                "SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME LIKE %s ORDER BY TABLE_NAME",
                params=(cfg.get("database", "mysql"), pattern),
            )
        elif db_type in ("postgresql", "kingbase"):
            s = args.schema or "public"
            result = execute_query(
                conn,
                "SELECT tablename AS TABLE_NAME, 'BASE TABLE' AS TABLE_TYPE FROM pg_tables "
                "WHERE schemaname = %s AND tablename LIKE %s "
                "ORDER BY tablename",
                params=(s, pattern),
            )
        else:
            schema = args.schema or default_schema("sqlserver")
            result = execute_query(
                conn,
                "SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
                "WHERE TABLE_NAME LIKE %s AND TABLE_SCHEMA LIKE %s "
                "ORDER BY TABLE_SCHEMA, TABLE_NAME",
                params=(pattern, schema),
            )

        if result["success"]:
            result["result_type"] = "search_tables"
            result["pattern"] = pattern
            result["tables"] = result.pop("rows", [])
            result["count"] = result.get("total_rows") or len(result["tables"])
            result["rows"] = None  # 标记为搜索结果
            print(format_result(result, title="表搜索"))
        else:
            print(format_result(result))
    finally:
        conn.dispose()


def cmd_find(args: argparse.Namespace) -> None:
    """搜索列名"""
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    pattern = args.pattern or "%"

    try:
        if db_type == "sqlite":
            result = execute_query(
                conn,
                "SELECT m.name AS TABLE_NAME, p.name AS COLUMN_NAME, p.type AS DATA_TYPE "
                "FROM sqlite_master m JOIN pragma_table_info(m.name) p "
                "WHERE m.type = 'table' AND p.name LIKE ? AND m.name NOT LIKE 'sqlite_%' "
                "ORDER BY m.name, p.cid",
                params=(pattern,),
            )
        elif db_type == "mysql":
            result = execute_query(
                conn,
                "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE "
                "FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND COLUMN_NAME LIKE %s "
                "ORDER BY TABLE_NAME, ORDINAL_POSITION",
                params=(cfg.get("database", "mysql"), pattern),
            )
        elif db_type in ("postgresql", "kingbase"):
            s = args.schema or "public"
            result = execute_query(
                conn,
                "SELECT table_name AS TABLE_NAME, column_name AS COLUMN_NAME, data_type AS DATA_TYPE "
                "FROM information_schema.columns WHERE table_schema = %s AND column_name LIKE %s "
                "ORDER BY table_name, ordinal_position",
                params=(s, pattern),
            )
        else:
            result = execute_query(
                conn,
                "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE "
                "FROM INFORMATION_SCHEMA.COLUMNS WHERE COLUMN_NAME LIKE %s "
                "ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION",
                params=(pattern,),
            )

        if result["success"]:
            result["result_type"] = "search_columns"
            result["pattern"] = pattern
            result["columns"] = result.pop("rows", [])
            # total_rows 在截断时为 None，用实际行数兜底（execute_query 不截断列搜索）
            result["count"] = result.get("total_rows") or len(result["columns"])
            result["rows"] = None
            print(format_result(result, title="列搜索"))
        else:
            print(format_result(result))
    finally:
        conn.dispose()


def cmd_sample(args: argparse.Namespace) -> None:
    """随机采样 N 条记录"""
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    table = args.table
    n = args.n if args.n is not None else 5
    schema = args.schema or default_schema(db_type)

    try:
        ident = quote_ident(table, db_type, schema)
        if db_type == "sqlserver":
            sql = f"SELECT TOP {int(n)} * FROM {ident} ORDER BY NEWID()"
        elif db_type == "mysql":
            sql = f"SELECT * FROM {ident} ORDER BY RAND() LIMIT {int(n)}"
        elif db_type in ("postgresql", "kingbase"):
            sql = f"SELECT * FROM {ident} ORDER BY RANDOM() LIMIT {int(n)}"
        else:
            sql = f"SELECT * FROM {ident} ORDER BY RANDOM() LIMIT {int(n)}"
        result = execute_query(conn, sql, max_rows=int(n))
        print(format_result(result, title=f"{table} 随机采样"))
    finally:
        conn.dispose()


def cmd_profile(args: argparse.Namespace) -> None:
    """快速统计：行数（优先估算）、null 占比、最小/最大值"""
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    table = args.table
    schema = args.schema or default_schema(db_type)
    fmt = getattr(args, "format", "table")
    try:
        if db_type == "sqlite":
            ident = quote_ident(table, "sqlite")
            total = execute_query(conn, f"SELECT COUNT(*) AS cnt FROM {ident}")
            if not total["success"] or not total["rows"]:
                print(format_result(total))
                return
            cnt = total["rows"][0]["cnt"]
            result = {"success": True, "table": table, "row_count": cnt, "estimate": False, "columns": []}
            print(format_result(result, fmt=fmt))
            return

        if db_type == "mysql":
            cols = execute_query(
                conn,
                "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                params=(cfg.get("database"), table),
            )
        elif db_type in ("postgresql", "kingbase"):
            cols = execute_query(
                conn,
                "SELECT column_name AS COLUMN_NAME, data_type AS DATA_TYPE "
                "FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position",
                params=(schema or "public", table),
            )
        else:
            cols = execute_query(
                conn,
                "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                params=(schema, table),
            )

        if not cols["success"] or not cols["rows"]:
            print(format_result(cols))
            return

        ident = quote_ident(table, db_type, schema)

        row_count_est = _estimate_row_count(conn, db_type, table, schema, cfg)
        if row_count_est is not None:
            cnt, is_estimate = row_count_est
        else:
            total = execute_query(conn, f"SELECT COUNT(*) AS cnt FROM {ident}")
            if not total["success"] or not total["rows"]:
                print(format_result(total))
                return
            cnt = total["rows"][0]["cnt"]
            is_estimate = False

        total_n = cnt
        col_stats = []

        # 批量 NULL 统计：单条 SQL 替代逐列 COUNT(*)（92 列 = 1 次查询 vs 92 次）
        col_names = [r["COLUMN_NAME"] for r in cols["rows"]]
        cases = ", ".join(f'SUM(CASE WHEN {quote_ident(cn, db_type)} IS NULL THEN 1 ELSE 0 END) AS "{cn}_null"' for cn in col_names)
        batch_sql = f"SELECT COUNT(*) AS total, {cases} FROM {ident}"
        batch_result = execute_query(conn, batch_sql)
        if batch_result["success"] and batch_result["rows"]:
            row = batch_result["rows"][0]
            actual_total = int(row.get("total", total_n))
            for cn in col_names:
                nulls = int(row.get(f"{cn}_null", 0))
                pct = 0 if not actual_total else round(nulls * 100 / actual_total, 2)
                col_stats.append({"name": cn, "null_pct": pct, "nulls": nulls, "total": actual_total})
        else:
            # 回退：逐列查询（极少发生）
            for cn in col_names:
                col_ident = quote_ident(cn, db_type)
                nr = execute_query(conn, f"SELECT COUNT(*) AS n FROM {ident} WHERE {col_ident} IS NULL")
                if nr["success"] and nr["rows"]:
                    nulls = nr["rows"][0]["n"]
                    pct = 0 if not total_n else round(nulls * 100 / total_n, 2)
                    col_stats.append({"name": cn, "null_pct": pct, "nulls": nulls, "total": total_n})

        if fmt == "table":
            label = "~" if is_estimate else ""
            print(f"行数: {label}{cnt}" + (" (估算)" if is_estimate else ""))
            for s in col_stats:
                print(f"  {s['name']}: NULL 占比 {s['null_pct']}% ({s['nulls']}/{s['total']})")
        else:
            result = {
                "success": True,
                "table": table,
                "row_count": cnt,
                "estimate": is_estimate,
                "columns": col_stats,
            }
            print(format_result(result, fmt=fmt))
    finally:
        conn.dispose()


def _estimate_row_count(conn, db_type: str, table: str, schema: str | None, cfg: dict) -> tuple[int, bool] | None:
    """用统计信息估算行数（毫秒级），避免大表 COUNT(*)。

    Returns:
        (row_count, is_estimate) 或 None（估算不可用时回退到 COUNT(*)）。
    """
    try:
        if db_type in ("postgresql", "kingbase"):
            s = schema or "public"
            result = execute_query(
                conn,
                "SELECT reltuples::bigint AS estimate FROM pg_class c "
                "JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relname = %s",
                params=(s, table),
            )
            if result.get("success") and result.get("rows"):
                est = result["rows"][0].get("estimate")
                if est is not None and est >= 0:
                    return (int(est), True)
        elif db_type == "sqlserver":
            s = schema or "dbo"
            result = execute_query(
                conn,
                "SELECT SUM(p.rows) AS estimate FROM sys.partitions p "
                "JOIN sys.tables t ON p.object_id = t.object_id "
                "WHERE SCHEMA_NAME(t.schema_id) = %s AND t.name = %s "
                "AND p.index_id IN (0, 1)",
                params=(s, table),
            )
            if result.get("success") and result.get("rows"):
                est = result["rows"][0].get("estimate")
                if est is not None:
                    return (int(est), True)
        elif db_type == "mysql":
            db = cfg.get("database", "mysql")
            result = execute_query(
                conn,
                "SELECT TABLE_ROWS AS estimate FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s",
                params=(db, table),
            )
            if result.get("success") and result.get("rows"):
                est = result["rows"][0].get("estimate")
                if est is not None:
                    return (int(est), True)
    except Exception:
        logger.warning("_estimate_row_count failed for %s.%s", schema, table, exc_info=True)
    return None


def cmd_history(args: argparse.Namespace) -> None:
    """查看当前会话历史命令"""
    hist_path = CONFIG_DIR / "history.txt"
    if not hist_path.exists():
        print("无历史记录")
        return
    lines = hist_path.read_text(encoding="utf-8").splitlines()
    if not lines:
        print("无历史记录")
        return
    for i, line in enumerate(lines[-args.n or 50 :], 1):
        print(f"{i}\t{line}")


def cmd_explain(args: argparse.Namespace) -> None:
    """显示 SQL 查询执行计划。

    按数据库方言自动适配：
    - MySQL: EXPLAIN <sql>
    - PostgreSQL: EXPLAIN <sql>
    - SQLite: EXPLAIN QUERY PLAN <sql>
    - SQL Server: SET SHOWPLAN_TEXT ON; <sql>; SET SHOWPLAN_TEXT OFF;
    """
    from core.connection import get_connection

    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    fmt = getattr(args, "format", None) or "table"

    # 安全校验：explain 只接受单条只读 SQL。
    # EXPLAIN 本身不执行写操作，但 args.sql 原样拼入查询文本——
    # 多语句或写操作在此入口下没有正当语义，统一拒绝避免绕过 cmd_query 的确认协议。
    sql_text = args.sql or ""
    is_ro, _, _ = check_read_only(sql_text, strict=True)
    if not is_ro:
        print("ERROR: explain 拒绝写操作 SQL（仅支持只读查询的执行计划）", file=sys.stderr)
        conn.dispose()
        return
    if count_statements(sql_text) != 1:
        print("ERROR: explain 仅支持单条 SQL，拒绝多语句输入", file=sys.stderr)
        conn.dispose()
        return

    try:
        if db_type == "mysql":
            plan_sql = f"EXPLAIN {args.sql}"
        elif db_type in ("postgresql", "kingbase"):
            plan_sql = f"EXPLAIN {args.sql}"
        elif db_type == "sqlite":
            plan_sql = f"EXPLAIN QUERY PLAN {args.sql}"
        else:
            # SQL Server: SET SHOWPLAN_TEXT ON 将后续查询转为计划输出
            plan_sql = f"SET SHOWPLAN_TEXT ON;\n{args.sql}\nSET SHOWPLAN_TEXT OFF;"

        result = execute_query(conn, plan_sql, max_rows=5000)
        if result.get("success"):
            output = format_result(result, fmt=fmt, title="执行计划")
            print(output)
        else:
            print(format_result(result, fmt=fmt))
    except Exception as e:
        from _security import sanitize_error

        print(f"ERROR: 执行计划分析失败 - {sanitize_error(e)}", file=sys.stderr)
    finally:
        conn.dispose()
