#!/usr/bin/env python3
"""
cli.explore_cmds - 统一结构探索命令

实现 explore 命令--用一个命令 + object_type/detail 参数组合替代
schema/schemas/columns/indexes/foreign-keys/constraints/search/find 共 8 个碎片命令。
旧命令保留向后兼容,explore 是 Agent 调用首选。

object_type 支持值:
  schema     → 等价 schemas / schema
  table      → 等价 schema / search --pattern
  view       → 视图列表(dbhub 对齐)
  column     → 等价 columns / find --pattern
  index      → 等价 indexes
  fk         → 等价 foreign-keys
  constraint → 等价 constraints
  procedure  → 存储过程/函数(dbhub 对齐)
  function   → 自定义函数(dbhub 对齐)

detail_level 支持值:
  names   → 仅名称(最省 token)
  summary → 名称 + 关键元信息(行数/列数/类型等)
  full    → 完整结构(当前默认行为)
"""

import sys
import argparse
import logging

logger = logging.getLogger(__name__)

from core.connection import get_connection
from _drivers import (
    execute_query,
    default_schema,
    list_schemas,
)
from _semantic_index import (
    fetch_semantic_index,
    _fetch_columns_for_tables,
    SCHEMA_SCAN_LIMIT,
)
from _formatters import format_result
from _scoring import build_semantic_matches, load_all_alias_sources
from _security import quote_ident

_DETAIL_NAMES = "names"
_DETAIL_SUMMARY = "summary"
_DETAIL_FULL = "full"
_DETAIL_CHOICES = [_DETAIL_NAMES, _DETAIL_SUMMARY, _DETAIL_FULL]

# ---------------------------------------------------------------------------
# SQL dialect registry
#
# Maps (function_name, db_type) or (function_name, db_type, variant) to SQL
# strings.  Each _explore_* function had an if/elif db_type chain whose only
# variation was the SQL text; the registry collapses those chains into a
# single dict lookup.  Param-building and output-formatting logic stays in
# each function because params and output shapes vary across callers.
#
# Key conventions:
#   variant "all" / "pattern"  – query with or without a LIKE filter
#   variant "names" / "full"   – query sized by detail level
# ---------------------------------------------------------------------------
_SQL = {
    # -- _explore_tables ----------------------------------------------------
    ("_explore_tables", "sqlite", "all"): (
        "SELECT name AS TABLE_NAME, type AS TABLE_TYPE FROM sqlite_master "
        "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ),
    ("_explore_tables", "sqlite", "pattern"): (
        "SELECT name AS TABLE_NAME, type AS TABLE_TYPE FROM sqlite_master "
        "WHERE type IN ('table', 'view') AND name LIKE ? AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ),
    ("_explore_tables", "mysql", "all"): (
        "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME"
    ),
    ("_explore_tables", "mysql", "pattern"): (
        "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_NAME LIKE %s ORDER BY TABLE_NAME"
    ),
    ("_explore_tables", "postgresql", "all"): (
        "SELECT tablename AS TABLE_NAME, 'BASE TABLE' AS TABLE_TYPE "
        "FROM pg_tables WHERE schemaname = %s "
        "UNION ALL SELECT viewname, 'VIEW' FROM pg_views WHERE schemaname = %s "
        "ORDER BY TABLE_NAME"
    ),
    ("_explore_tables", "postgresql", "pattern"): (
        "SELECT tablename AS TABLE_NAME, 'BASE TABLE' AS TABLE_TYPE "
        "FROM pg_tables WHERE schemaname = %s AND tablename LIKE %s "
        "ORDER BY TABLE_NAME"
    ),
    ("_explore_tables", "sqlserver", "all"): (
        "SELECT TABLE_SCHEMA, TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_SCHEMA LIKE %s ORDER BY TABLE_SCHEMA, TABLE_NAME"
    ),
    ("_explore_tables", "sqlserver", "pattern"): (
        "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES "
        "WHERE TABLE_NAME LIKE %s AND TABLE_SCHEMA LIKE %s "
        "ORDER BY TABLE_SCHEMA, TABLE_NAME"
    ),
    # -- _explore_columns ---------------------------------------------------
    ("_explore_columns", "mysql"): (
        "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, "
        "IS_NULLABLE, ORDINAL_POSITION, COLUMN_DEFAULT, COLUMN_KEY, "
        "COLUMN_COMMENT "
        "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
        "ORDER BY ORDINAL_POSITION"
    ),
    ("_explore_columns", "postgresql"): (
        "SELECT column_name AS COLUMN_NAME, data_type AS DATA_TYPE, "
        "character_maximum_length, is_nullable AS IS_NULLABLE, "
        "ordinal_position AS ORDINAL_POSITION, column_default AS COLUMN_DEFAULT, "
        "col_description(c.oid, a.attnum) AS description "
        "FROM information_schema.columns ic "
        "JOIN pg_class c ON c.relname = ic.table_name "
        "JOIN pg_namespace n ON n.nspname = ic.table_schema AND c.relnamespace = n.oid "
        "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = ic.column_name "
        "WHERE ic.table_schema = %s AND ic.table_name = %s "
        "ORDER BY ic.ordinal_position"
    ),
    ("_explore_columns", "sqlserver"): (
        "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, "
        "IS_NULLABLE, ORDINAL_POSITION, COLUMN_DEFAULT, "
        "ep.value AS COLUMN_DESCRIPTION "
        "FROM INFORMATION_SCHEMA.COLUMNS c "
        "LEFT JOIN sys.extended_properties ep ON ep.major_id = OBJECT_ID(c.TABLE_SCHEMA + '.' + c.TABLE_NAME) "
        "AND ep.minor_id = c.ORDINAL_POSITION AND ep.name = 'MS_Description' "
        "WHERE c.TABLE_SCHEMA = %s AND c.TABLE_NAME = %s "
        "ORDER BY c.ORDINAL_POSITION"
    ),
    # -- _explore_column_search ---------------------------------------------
    ("_explore_column_search", "sqlite"): (
        "SELECT m.name AS TABLE_NAME, p.name AS COLUMN_NAME, p.type AS DATA_TYPE "
        "FROM sqlite_master m JOIN pragma_table_info(m.name) p "
        "WHERE m.type = 'table' AND p.name LIKE ? AND m.name NOT LIKE 'sqlite_%' "
        "ORDER BY m.name, p.cid"
    ),
    ("_explore_column_search", "mysql"): (
        "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE "
        "FROM information_schema.COLUMNS "
        "WHERE TABLE_SCHEMA = %s AND COLUMN_NAME LIKE %s "
        "ORDER BY TABLE_NAME, ORDINAL_POSITION"
    ),
    ("_explore_column_search", "postgresql"): (
        "SELECT table_name AS TABLE_NAME, column_name AS COLUMN_NAME, data_type AS DATA_TYPE "
        "FROM information_schema.columns WHERE table_schema = %s AND column_name LIKE %s "
        "ORDER BY table_name, ordinal_position"
    ),
    ("_explore_column_search", "sqlserver"): (
        "SELECT TABLE_SCHEMA, TABLE_NAME, COLUMN_NAME, DATA_TYPE "
        "FROM INFORMATION_SCHEMA.COLUMNS WHERE COLUMN_NAME LIKE %s "
        "ORDER BY TABLE_SCHEMA, TABLE_NAME, ORDINAL_POSITION"
    ),
    # -- _explore_indexes ---------------------------------------------------
    ("_explore_indexes", "sqlite"): ("SELECT name AS index_name, tbl_name, sql FROM sqlite_master WHERE type = 'index' AND tbl_name = ?"),
    ("_explore_indexes", "mysql"): (
        "SELECT INDEX_NAME, COLUMN_NAME, NON_UNIQUE, SEQ_IN_INDEX "
        "FROM information_schema.STATISTICS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
        "ORDER BY INDEX_NAME, SEQ_IN_INDEX"
    ),
    ("_explore_indexes", "postgresql"): (
        "SELECT i.relname AS index_name, a.attname AS column_name, "
        "ix.indisunique AS is_unique, ix.indisprimary AS is_primary_key "
        "FROM pg_class t JOIN pg_index ix ON t.oid = ix.indrelid "
        "JOIN pg_class i ON i.oid = ix.indexrelid "
        "JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = ANY(ix.indkey) "
        "WHERE t.relname = %s AND t.relkind = 'r' "
        "ORDER BY i.relname"
    ),
    ("_explore_indexes", "sqlserver"): (
        "SELECT i.name AS index_name, i.is_unique, i.is_primary_key, i.type_desc "
        "FROM sys.indexes i JOIN sys.tables t ON i.object_id = t.object_id "
        "WHERE SCHEMA_NAME(t.schema_id) = %s AND t.name = %s "
        "ORDER BY i.is_primary_key DESC, i.name"
    ),
    # -- _explore_fks -------------------------------------------------------
    ("_explore_fks", "mysql"): (
        "SELECT k.CONSTRAINT_NAME, k.COLUMN_NAME, k.REFERENCED_TABLE_NAME, "
        "k.REFERENCED_COLUMN_NAME, r.UPDATE_RULE, r.DELETE_RULE "
        "FROM information_schema.KEY_COLUMN_USAGE k "
        "JOIN information_schema.REFERENTIAL_CONSTRAINTS r "
        "ON k.CONSTRAINT_NAME = r.CONSTRAINT_NAME "
        "WHERE k.TABLE_SCHEMA = %s AND k.TABLE_NAME = %s "
        "AND k.REFERENCED_TABLE_NAME IS NOT NULL "
        "ORDER BY k.CONSTRAINT_NAME, k.ORDINAL_POSITION"
    ),
    ("_explore_fks", "postgresql"): (
        "SELECT DISTINCT tc.constraint_name, kcu.column_name, "
        "ccu.table_name AS referenced_table, ccu.column_name AS referenced_column, "
        "rc.update_rule, rc.delete_rule "
        "FROM information_schema.table_constraints tc "
        "JOIN information_schema.key_column_usage kcu "
        "ON tc.constraint_name = kcu.constraint_name "
        "AND tc.table_schema = kcu.table_schema "
        "JOIN information_schema.constraint_column_usage ccu "
        "ON ccu.constraint_name = tc.constraint_name "
        "AND ccu.constraint_schema = tc.table_schema "
        "JOIN information_schema.referential_constraints rc "
        "ON tc.constraint_name = rc.constraint_name "
        "AND tc.constraint_schema = rc.constraint_schema "
        "WHERE tc.table_schema = %s AND tc.table_name = %s AND tc.constraint_type = 'FOREIGN KEY' "
        "ORDER BY tc.constraint_name"
    ),
    ("_explore_fks", "sqlserver"): (
        "SELECT f.name AS constraint_name, "
        "COL_NAME(fc.parent_object_id, fc.parent_column_id) AS column_name, "
        "OBJECT_NAME(fc.referenced_object_id) AS referenced_table, "
        "COL_NAME(fc.referenced_object_id, fc.referenced_column_id) AS referenced_column, "
        "delete_referential_action_desc AS delete_rule, "
        "update_referential_action_desc AS update_rule "
        "FROM sys.foreign_keys f "
        "JOIN sys.foreign_key_columns fc ON f.object_id = fc.constraint_object_id "
        "WHERE OBJECT_SCHEMA_NAME(f.parent_object_id) = %s AND OBJECT_NAME(f.parent_object_id) = %s"
    ),
    # -- _explore_constraints ------------------------------------------------
    ("_explore_constraints", "sqlite"): (
        "SELECT sql FROM sqlite_master WHERE type IN ('table', 'index') AND tbl_name = ? AND sql IS NOT NULL"
    ),
    ("_explore_constraints", "mysql"): (
        "SELECT CONSTRAINT_NAME, CONSTRAINT_TYPE "
        "FROM information_schema.TABLE_CONSTRAINTS "
        "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
        "ORDER BY CONSTRAINT_TYPE, CONSTRAINT_NAME"
    ),
    ("_explore_constraints", "postgresql"): (
        "SELECT conname AS constraint_name, contype AS constraint_type, "
        "pg_get_constraintdef(oid) AS definition "
        "FROM pg_constraint "
        "WHERE conrelid = %s::regclass "
        "ORDER BY contype, conname"
    ),
    ("_explore_constraints", "sqlserver"): (
        "SELECT name AS constraint_name, type_desc AS constraint_type "
        "FROM sys.objects WHERE parent_object_id = OBJECT_ID(%s) "
        "AND type IN ('PK', 'UQ', 'C', 'F') "
        "ORDER BY type, name"
    ),
    # -- _fetch_table_comments -----------------------------------------------
    # Template: caller must .format() the IN-clause placeholders before use.
    ("_fetch_table_comments", "mysql"): (
        "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders})"
    ),
    ("_fetch_table_comments", "postgresql"): (
        "SELECT c.relname AS TABLE_NAME, obj_description(c.oid) AS comment "
        "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = %s AND c.relname IN ({placeholders})"
    ),
    ("_fetch_table_comments", "sqlserver"): (
        "SELECT t.name AS TABLE_NAME, ep.value AS comment "
        "FROM sys.tables t JOIN sys.extended_properties ep "
        "ON ep.major_id = t.object_id AND ep.minor_id = 0 AND ep.name = 'MS_Description' "
        "WHERE SCHEMA_NAME(t.schema_id) = %s AND t.name IN ({placeholders})"
    ),
    # -- _explore_views ------------------------------------------------------
    ("_explore_views", "sqlite", "all"): (
        "SELECT name AS VIEW_NAME, sql AS definition FROM sqlite_master WHERE type = 'view' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ),
    ("_explore_views", "sqlite", "pattern"): (
        "SELECT name AS VIEW_NAME, sql AS definition FROM sqlite_master "
        "WHERE type = 'view' AND name LIKE ? AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ),
    ("_explore_views", "mysql", "all"): (
        "SELECT TABLE_NAME AS VIEW_NAME, VIEW_DEFINITION AS definition "
        "FROM information_schema.VIEWS WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME"
    ),
    ("_explore_views", "mysql", "pattern"): (
        "SELECT TABLE_NAME AS VIEW_NAME, VIEW_DEFINITION AS definition "
        "FROM information_schema.VIEWS WHERE TABLE_SCHEMA = %s AND TABLE_NAME LIKE %s "
        "ORDER BY TABLE_NAME"
    ),
    ("_explore_views", "postgresql", "all"): (
        "SELECT viewname AS VIEW_NAME, definition FROM pg_views WHERE schemaname = %s ORDER BY viewname"
    ),
    ("_explore_views", "postgresql", "pattern"): (
        "SELECT viewname AS VIEW_NAME, definition FROM pg_views WHERE schemaname = %s AND viewname LIKE %s ORDER BY viewname"
    ),
    ("_explore_views", "sqlserver", "all"): (
        "SELECT TABLE_NAME AS VIEW_NAME, VIEW_DEFINITION AS definition "
        "FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_SCHEMA LIKE %s "
        "ORDER BY TABLE_NAME"
    ),
    ("_explore_views", "sqlserver", "pattern"): (
        "SELECT TABLE_NAME AS VIEW_NAME, VIEW_DEFINITION AS definition "
        "FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_NAME LIKE %s AND TABLE_SCHEMA LIKE %s "
        "ORDER BY TABLE_NAME"
    ),
    # -- _explore_routines ---------------------------------------------------
    ("_explore_routines", "mysql", "names"): (
        "SELECT ROUTINE_NAME, ROUTINE_TYPE FROM information_schema.ROUTINES "
        "WHERE ROUTINE_SCHEMA = %s AND ROUTINE_TYPE = %s "
        "AND ROUTINE_NAME LIKE %s ORDER BY ROUTINE_NAME"
    ),
    ("_explore_routines", "mysql", "full"): (
        "SELECT ROUTINE_NAME, ROUTINE_TYPE, DTD_IDENTIFIER AS return_type, "
        "ROUTINE_DEFINITION AS definition "
        "FROM information_schema.ROUTINES "
        "WHERE ROUTINE_SCHEMA = %s AND ROUTINE_TYPE = %s "
        "AND ROUTINE_NAME LIKE %s ORDER BY ROUTINE_NAME"
    ),
    ("_explore_routines", "postgresql", "names"): (
        "SELECT proname AS routine_name, prokind FROM pg_proc "
        "WHERE pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = %s) "
        "AND prokind = %s AND proname LIKE %s ORDER BY proname"
    ),
    ("_explore_routines", "postgresql", "full"): (
        "SELECT proname AS routine_name, prokind, "
        "pg_get_function_result(oid) AS return_type, "
        "pg_get_functiondef(oid) AS definition "
        "FROM pg_proc "
        "WHERE pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = %s) "
        "AND prokind = %s AND proname LIKE %s ORDER BY proname"
    ),
    ("_explore_routines", "sqlserver", "names"): (
        "SELECT o.name AS routine_name FROM sys.objects o "
        "WHERE o.type = %s AND SCHEMA_NAME(o.schema_id) LIKE %s "
        "AND o.name LIKE %s ORDER BY o.name"
    ),
    ("_explore_routines", "sqlserver", "full"): (
        "SELECT o.name AS routine_name, o.type_desc, "
        "m.definition FROM sys.objects o "
        "LEFT JOIN sys.sql_modules m ON o.object_id = m.object_id "
        "WHERE o.type = %s AND SCHEMA_NAME(o.schema_id) LIKE %s "
        "AND o.name LIKE %s ORDER BY o.name"
    ),
}
# KingbaseES (人大金仓) — PostgreSQL-compatible, reuse same SQL
for _sql_key, _sql_val in list(_SQL.items()):
    if len(_sql_key) >= 2 and _sql_key[1] == "postgresql":
        _SQL[(_sql_key[0], "kingbase", *_sql_key[2:])] = _sql_val


def cmd_explore(args: argparse.Namespace) -> None:
    """统一结构探索命令"""
    obj = args.object_type
    detail = args.detail or _DETAIL_NAMES
    schema = args.schema
    table = args.table
    pattern = args.pattern
    semantic = args.semantic
    limit = args.limit or 5
    fmt = args.format or "json-compact"
    # --level2: legacy search --semantic 使用 False(仅表名+注释,无列数据展开)
    # explore --semantic 默认 True(探索模式:top 匹配不足时展开列数据重新打分)
    enable_level2 = getattr(args, "level2", True)

    if semantic and obj in (None, "table"):
        _explore_semantic(semantic, limit, fmt, enable_level2=enable_level2)
        return

    if obj == "schema" or obj is None:
        _explore_schemas(detail, fmt)
    elif obj == "table":
        _explore_tables(schema, pattern, detail, fmt)
    elif obj == "column":
        if table:
            _explore_columns(table, schema, detail, fmt)
        else:
            _explore_column_search(pattern, schema, detail, fmt)
    elif obj == "index":
        if not table:
            print("ERROR: --table required for object_type=index", file=sys.stderr)
            return
        _explore_indexes(table, schema, detail, fmt)
    elif obj == "fk":
        if not table:
            print("ERROR: --table required for object_type=fk", file=sys.stderr)
            return
        _explore_fks(table, schema, detail, fmt)
    elif obj == "constraint":
        if not table:
            print("ERROR: --table required for object_type=constraint", file=sys.stderr)
            return
        _explore_constraints(table, schema, detail, fmt)
    elif obj == "view":
        _explore_views(schema, pattern, detail, fmt)
    elif obj in ("procedure", "function"):
        _explore_routines(obj, schema, pattern, detail, fmt)


def _out(data: dict, fmt: str, title: str = "") -> None:
    print(format_result(data, fmt=fmt, title=title))


def _explore_schemas(detail: str, fmt: str) -> None:
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    try:
        schemas = list_schemas(conn, db_type)
        default_s = default_schema(db_type)
        if detail == _DETAIL_NAMES:
            _out({"success": True, "schemas": schemas, "default": default_s}, fmt)
        elif detail == _DETAIL_SUMMARY:
            _out({"success": True, "schemas": schemas, "default": default_s, "count": len(schemas)}, fmt)
        else:
            schema_tables = {}
            for s in schemas[:20]:
                try:
                    from _drivers import get_tables

                    tables = get_tables(conn, schema=s)
                    schema_tables[s] = {"table_count": len(tables), "tables": tables[:50]}
                except Exception:
                    logger.warning("failed to list tables for schema '%s', skipping", s, exc_info=True)
                    schema_tables[s] = {"table_count": 0, "tables": []}
            _out({"success": True, "schemas": schemas, "default": default_s, "detail": schema_tables}, fmt)
    finally:
        conn.dispose()


def _explore_tables(schema: str | None, pattern: str | None, detail: str, fmt: str) -> None:
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    s = schema or default_schema(db_type)
    # pattern 未带 LIKE 通配符(% _)时自动包成 %xxx%,避免用户写 "LES" 退化为精确匹配
    if pattern and "%" not in pattern and "_" not in pattern:
        pattern = f"%{pattern}%"
    pattern = pattern or "%"

    try:
        has_pattern = pattern != "%"
        variant = "pattern" if has_pattern else "all"
        sql = _SQL[("_explore_tables", db_type, variant)]

        if db_type == "sqlite":
            result = execute_query(conn, sql, params=(pattern,) if has_pattern else (), max_rows=SCHEMA_SCAN_LIMIT)
        elif db_type == "mysql":
            db = cfg.get("database", "mysql")
            params = (db, pattern) if has_pattern else (db,)
            result = execute_query(conn, sql, params=params, max_rows=SCHEMA_SCAN_LIMIT)
        elif db_type in ("postgresql", "kingbase"):
            s = s or "public"
            params = (s, pattern) if has_pattern else (s, s)
            result = execute_query(conn, sql, params=params, max_rows=SCHEMA_SCAN_LIMIT)
        else:
            schema_val = s or default_schema("sqlserver")
            params = (pattern, schema_val) if has_pattern else (schema_val,)
            result = execute_query(conn, sql, params=params, max_rows=SCHEMA_SCAN_LIMIT)

        if not result.get("success"):
            _out(result, fmt)
            return

        rows = result.get("rows", [])
        # 无 pattern 全库扫描 + names:硬上限拦截(防 28k token 黑洞)
        # summary/full:保留 hint 警告(这两个 detail 单行就大,硬拒太凶)
        HARD_LIMIT_NAMES = 200
        if detail == _DETAIL_NAMES and pattern == "%" and len(rows) > HARD_LIMIT_NAMES:
            _out(
                {
                    "success": False,
                    "error": (
                        f"无 --pattern 的全库 names 扫描命中硬上限({len(rows)} > {HARD_LIMIT_NAMES} 张表)。"
                        f"如继续返回约 {int(len(rows) * 30 / 3)} token,Agent 上下文无法承受。"
                    ),
                    "hint": (
                        "请用以下任一方式重试(按推荐度排序):"
                        "1) explore --object-type table --pattern <关键词>  --子串匹配,如 --pattern LES;"
                        "2) explore --semantic <中文关键词>  --语义搜索(带列名预览);"
                        "3) explore --object-type table --pattern <schema前缀>%  --按 schema 限定。"
                    ),
                    "count": len(rows),
                },
                fmt,
            )
            return

        # summary 模式硬上限(单行大,含注释/类型信息)
        HARD_LIMIT_SUMMARY = 100
        if detail == _DETAIL_SUMMARY and pattern == "%" and len(rows) > HARD_LIMIT_SUMMARY:
            _out(
                {
                    "success": False,
                    "error": (
                        f"无 --pattern 的全库 summary 扫描命中硬上限({len(rows)} > {HARD_LIMIT_SUMMARY} 张表)。"
                        f"summary 单行较大,{HARD_LIMIT_SUMMARY} 行已约 {int(HARD_LIMIT_SUMMARY * 80 / 3)} token。"
                    ),
                    "hint": ("请用 --pattern 缩小范围,或先用 --detail names 浏览表名后再对目标表单次 --detail full。"),
                    "count": len(rows),
                },
                fmt,
            )
            return

        # 无 pattern 全库扫描时,结果量大就附加提示,引导 Agent 加 pattern 省 token
        # token 估算改用实际字节数(名字列表 + JSON 包装),不再用 len(rows)*3 的过低估算
        warn = None
        if pattern == "%" and len(rows) >= 50:
            names_only = [r.get("TABLE_NAME", "") for r in rows]
            est_bytes = len(",".join(names_only)) + 80  # 80 = JSON 包装/键名/hint 开销
            est_tokens = max(len(rows) * 3, int(est_bytes / 3))  # 下限取旧公式,避免小幅低估
            warn = (
                f"全库扫描返回 {len(rows)} 张表(约 {est_tokens} token)。"
                "建议用 --pattern 缩小范围(如 --pattern LES),或用 --semantic 做语义搜索。"
            )
        if detail == _DETAIL_NAMES:
            names = [r.get("TABLE_NAME", "") for r in rows]
            payload = {"success": True, "tables": names, "count": len(names)}
            if warn:
                payload["hint"] = warn
            _out(payload, fmt)
        elif detail == _DETAIL_SUMMARY:
            comments = _fetch_table_comments(conn, db_type, cfg, s, rows)
            items = []
            for r in rows:
                tname = r.get("TABLE_NAME", "")
                item = {
                    "name": tname,
                    "schema": r.get("TABLE_SCHEMA", ""),
                    "type": r.get("TABLE_TYPE", ""),
                }
                cmt = comments.get(tname)
                if cmt:
                    item["comment"] = cmt
                items.append(item)
            payload = {"success": True, "tables": items, "count": len(items)}
            if warn:
                payload["hint"] = warn
            _out(payload, fmt)
        else:
            # full 级别:返回的仅是 system view 行(TABLE_SCHEMA/TABLE_NAME/TABLE_TYPE),
            # 不是完整列定义。如需列详情请改用 explore --object-type column --table X。
            payload = {
                "success": True,
                "tables": rows,
                "count": len(rows),
                "warning": (
                    "table --detail full 返回的是系统视图行(不含列定义)。"
                    "要看完整列,请用 explore --object-type column --table <表名> --detail full。"
                ),
            }
            if warn:
                payload["hint"] = warn
            _out(payload, fmt)
    finally:
        conn.dispose()


def _explore_columns(table: str, schema: str | None, detail: str, fmt: str) -> None:
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    s = schema or default_schema(db_type)

    try:
        if db_type == "sqlite":
            result = execute_query(conn, f"PRAGMA table_info({quote_ident(table, 'sqlite')})")
            if result.get("success") and result.get("rows"):
                if detail == _DETAIL_NAMES:
                    names = [r.get("name", "") for r in result["rows"]]
                    _out({"success": True, "table": table, "columns": names, "count": len(names)}, fmt)
                elif detail == _DETAIL_SUMMARY:
                    items = [
                        {"name": r.get("name", ""), "type": r.get("type", ""), "pk": bool(r.get("pk")), "nullable": not r.get("notnull")}
                        for r in result["rows"]
                    ]
                    _out({"success": True, "table": table, "columns": items, "count": len(items)}, fmt)
                else:
                    compact = [_compact_column(r) for r in result["rows"]]
                    _out({"success": True, "table": table, "columns": compact, "count": len(compact)}, fmt)
            else:
                _out(result, fmt, title=f"{table} columns")
        elif db_type == "mysql":
            sql = _SQL[("_explore_columns", "mysql")]
            result = execute_query(conn, sql, params=(cfg.get("database", "mysql"), table))
            _format_columns_result(result, table, detail, fmt)
        elif db_type in ("postgresql", "kingbase"):
            s = s or "public"
            sql = _SQL[("_explore_columns", "postgresql")]
            result = execute_query(conn, sql, params=(s, table))
            _format_columns_result(result, table, detail, fmt)
        else:
            sql = _SQL[("_explore_columns", "sqlserver")]
            result = execute_query(conn, sql, params=(s, table))
            _format_columns_result(result, table, detail, fmt)
    finally:
        conn.dispose()


def _format_columns_result(result: dict, table: str, detail: str, fmt: str) -> None:
    if not result.get("success"):
        _out(result, fmt)
        return
    rows = result.get("rows", [])
    if detail == _DETAIL_NAMES:
        names = [r.get("COLUMN_NAME", "") for r in rows]
        _out({"success": True, "table": table, "columns": names, "count": len(names)}, fmt)
    elif detail == _DETAIL_SUMMARY:
        items = [
            {"name": r.get("COLUMN_NAME", ""), "type": r.get("DATA_TYPE", ""), "nullable": r.get("IS_NULLABLE", "YES") == "YES"}
            for r in rows
        ]
        for i, r in enumerate(rows):
            desc = r.get("COLUMN_COMMENT") or r.get("description") or r.get("COLUMN_DESCRIPTION")
            if desc:
                items[i]["description"] = desc
        _out({"success": True, "table": table, "columns": items, "count": len(items)}, fmt)
    else:
        # full: 裁剪 null/空字段以降低 token 消耗(实测可省 ~30%)
        compact = [_compact_column(r) for r in rows]
        payload = {"success": True, "table": table, "columns": compact, "count": len(compact)}
        # 大表 full 是逐表 token 放大器:列越多 token 越高,且无 pattern 缩小空间。
        # 不硬拒(用户可能确实需要某张大表的完整列),但附加 hint 引导更省的路径。
        # 阈值 40:实测单表 ~40 列 full 约 1800 token,超过即值得提示。
        if len(compact) >= 40:
            payload["hint"] = (
                f"该表有 {len(compact)} 列,full 详情体积较大。"
                "若仅需列名,下次用 --detail names(省 ~80% token);"
                "若在多表间筛选,优先 explore --semantic 拿列名预览。"
            )
        _out(payload, fmt)


# full 级别永远保留的关键字段,其余字段值为 null/空则省略
_COLUMN_KEEP_KEYS = {"COLUMN_NAME", "DATA_TYPE", "IS_NULLABLE"}


def _compact_column(row: dict) -> dict:
    """裁剪 full 级别列定义中的 null/空字段,保留有效信息。

    COLUMN_NAME / DATA_TYPE / IS_NULLABLE 始终保留(语义必需);
    COLUMN_DEFAULT / CHARACTER_MAXIMUM_LENGTH / ORDINAL_POSITION / COLUMN_DESCRIPTION
    等仅在非空时保留。
    """
    out = {}
    for k, v in row.items():
        if k in _COLUMN_KEEP_KEYS:
            out[k] = v
            continue
        # None / 空字符串 / 空 bytes 视为"无信息",省略
        if v is None or v == "" or v == b"":
            continue
        out[k] = v
    return out


def _explore_column_search(pattern: str | None, schema: str | None, detail: str, fmt: str) -> None:
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    pattern = pattern or "%"

    try:
        sql = _SQL[("_explore_column_search", db_type)]

        if db_type == "sqlite":
            result = execute_query(conn, sql, params=(pattern,))
        elif db_type == "mysql":
            result = execute_query(conn, sql, params=(cfg.get("database", "mysql"), pattern))
        elif db_type in ("postgresql", "kingbase"):
            s = schema or "public"
            result = execute_query(conn, sql, params=(s, pattern))
        else:
            result = execute_query(conn, sql, params=(pattern,))

        if not result.get("success"):
            _out(result, fmt)
            return

        rows = result.get("rows", [])
        if detail == _DETAIL_NAMES:
            items = [{"t": r.get("TABLE_NAME", ""), "c": r.get("COLUMN_NAME", "")} for r in rows]
            _out({"success": True, "columns": items, "count": len(items)}, fmt)
        else:
            _out({"success": True, "columns": rows, "count": len(rows)}, fmt)
    finally:
        conn.dispose()


def _explore_indexes(table: str, schema: str | None, detail: str, fmt: str) -> None:
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")

    try:
        sql = _SQL[("_explore_indexes", db_type)]

        if db_type == "sqlite":
            result = execute_query(conn, sql, params=(table,))
        elif db_type == "mysql":
            result = execute_query(conn, sql, params=(cfg.get("database", "mysql"), table))
        elif db_type in ("postgresql", "kingbase"):
            result = execute_query(conn, sql, params=(table,))
        else:
            result = execute_query(conn, sql, params=(schema or default_schema("sqlserver"), table))

        if not result.get("success"):
            _out(result, fmt)
            return

        rows = result.get("rows", [])
        if detail == _DETAIL_NAMES:
            names = [r.get("index_name", r.get("INDEX_NAME", "")) for r in rows]
            _out({"success": True, "table": table, "indexes": names, "count": len(names)}, fmt)
        elif detail == _DETAIL_SUMMARY:
            items = []
            for r in rows:
                items.append(
                    {
                        "name": r.get("index_name", r.get("INDEX_NAME", "")),
                        "unique": bool(r.get("is_unique", not r.get("NON_UNIQUE", True))),
                        "primary": bool(r.get("is_primary_key", False)),
                    }
                )
            _out({"success": True, "table": table, "indexes": items, "count": len(items)}, fmt)
        else:
            _out({"success": True, "table": table, "indexes": rows}, fmt)
    finally:
        conn.dispose()


def _explore_fks(table: str, schema: str | None, detail: str, fmt: str) -> None:
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    s = schema or default_schema(db_type)

    try:
        if db_type == "sqlite":
            result = execute_query(conn, f"PRAGMA foreign_key_list({quote_ident(table, 'sqlite')})")
            if result.get("success") and result.get("rows"):
                rows = result["rows"]
                if detail == _DETAIL_NAMES:
                    refs = list({r.get("table", "") for r in rows if r.get("table")})
                    _out({"success": True, "table": table, "fk_targets": refs}, fmt)
                else:
                    items = [{"from": r.get("from", ""), "to": r.get("to", ""), "target": r.get("table", "")} for r in rows]
                    _out({"success": True, "table": table, "foreign_keys": items}, fmt)
            else:
                _out(result, fmt)
        elif db_type == "mysql":
            sql = _SQL[("_explore_fks", "mysql")]
            result = execute_query(conn, sql, params=(cfg.get("database", "mysql"), table))
            _format_fk_result(result, table, detail, fmt)
        elif db_type in ("postgresql", "kingbase"):
            s2 = s or "public"
            sql = _SQL[("_explore_fks", "postgresql")]
            result = execute_query(conn, sql, params=(s2, table))
            _format_fk_result(result, table, detail, fmt)
        else:
            sql = _SQL[("_explore_fks", "sqlserver")]
            result = execute_query(conn, sql, params=(s, table))
            _format_fk_result(result, table, detail, fmt)
    finally:
        conn.dispose()


def _format_fk_result(result: dict, table: str, detail: str, fmt: str) -> None:
    if not result.get("success"):
        _out(result, fmt)
        return
    rows = result.get("rows", [])
    if detail == _DETAIL_NAMES:
        refs = list({r.get("referenced_table", r.get("REFERENCED_TABLE", "")) for r in rows})
        _out({"success": True, "table": table, "fk_targets": refs}, fmt)
    elif detail == _DETAIL_SUMMARY:
        items = [
            {"column": r.get("column_name", r.get("COLUMN_NAME", "")), "target": r.get("referenced_table", r.get("REFERENCED_TABLE", ""))}
            for r in rows
        ]
        _out({"success": True, "table": table, "foreign_keys": items}, fmt)
    else:
        _out({"success": True, "table": table, "foreign_keys": rows}, fmt)


def _explore_constraints(table: str, schema: str | None, detail: str, fmt: str) -> None:
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    s = schema or default_schema(db_type)

    try:
        sql = _SQL[("_explore_constraints", db_type)]

        if db_type == "sqlite":
            result = execute_query(conn, sql, params=(table,))
            if result.get("success"):
                if detail == _DETAIL_NAMES:
                    _out({"success": True, "table": table, "ddl_count": len(result.get("rows", []))}, fmt)
                else:
                    _out({"success": True, "table": table, "constraints": result.get("rows", [])}, fmt)
            else:
                _out(result, fmt)
        elif db_type == "mysql":
            db = cfg.get("database", "mysql")
            result = execute_query(conn, sql, params=(db, table))
            _format_constraints_result(result, table, detail, fmt)
        elif db_type in ("postgresql", "kingbase"):
            s2 = s or "public"
            result = execute_query(conn, sql, params=(f"{s2}.{table}",))
            _format_constraints_result(result, table, detail, fmt)
        else:
            result = execute_query(conn, sql, params=(f"{s}.{table}",))
            _format_constraints_result(result, table, detail, fmt)
    finally:
        conn.dispose()


def _format_constraints_result(result: dict, table: str, detail: str, fmt: str) -> None:
    if not result.get("success"):
        _out(result, fmt)
        return
    rows = result.get("rows", [])
    if detail == _DETAIL_NAMES:
        names = [r.get("constraint_name", r.get("CONSTRAINT_NAME", "")) for r in rows]
        _out({"success": True, "table": table, "constraints": names, "count": len(names)}, fmt)
    elif detail == _DETAIL_SUMMARY:
        items = [
            {"name": r.get("constraint_name", r.get("CONSTRAINT_NAME", "")), "type": r.get("constraint_type", r.get("CONSTRAINT_TYPE", ""))}
            for r in rows
        ]
        _out({"success": True, "table": table, "constraints": items, "count": len(items)}, fmt)
    else:
        _out({"success": True, "table": table, "constraints": rows}, fmt)


def _fetch_table_comments(conn, db_type: str, cfg: dict, schema: str | None, table_rows: list[dict]) -> dict[str, str]:
    """批量获取表注释(MySQL TABLE_COMMENT / PostgreSQL obj_description / SQL Server MS_Description)。

    Returns:
        {table_name: comment} 仅包含有注释的表。
    """
    if db_type == "sqlite" or not table_rows:
        return {}

    table_names = [r.get("TABLE_NAME", "") for r in table_rows if r.get("TABLE_NAME")]
    if not table_names:
        return {}

    try:
        placeholders = ", ".join(["%s"] * len(table_names))
        sql_template = _SQL[("_fetch_table_comments", db_type)]
        sql = sql_template.format(placeholders=placeholders)

        if db_type == "mysql":
            db = cfg.get("database", "mysql")
            result = execute_query(conn, sql, params=(db, *table_names), max_rows=None)
            if result.get("success"):
                return {r["TABLE_NAME"]: r["TABLE_COMMENT"] for r in result["rows"] if r.get("TABLE_COMMENT")}
        elif db_type in ("postgresql", "kingbase"):
            s = schema or "public"
            result = execute_query(conn, sql, params=(s, *table_names), max_rows=None)
            if result.get("success"):
                return {r["TABLE_NAME"]: r["comment"] for r in result["rows"] if r.get("comment")}
        else:
            schema_val = schema or default_schema("sqlserver")
            result = execute_query(conn, sql, params=(schema_val, *table_names), max_rows=None)
            if result.get("success"):
                return {r["TABLE_NAME"]: r["comment"] for r in result["rows"] if r.get("comment")}
    except Exception:
        pass
    return {}


def _explore_views(schema: str | None, pattern: str | None, detail: str, fmt: str) -> None:
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    s = schema or default_schema(db_type)
    pattern = pattern or "%"

    try:
        has_pattern = pattern != "%"
        variant = "pattern" if has_pattern else "all"
        sql = _SQL[("_explore_views", db_type, variant)]

        if db_type == "sqlite":
            result = execute_query(conn, sql, params=(pattern,) if has_pattern else (), max_rows=SCHEMA_SCAN_LIMIT)
        elif db_type == "mysql":
            db = cfg.get("database", "mysql")
            params = (db, pattern) if has_pattern else (db,)
            result = execute_query(conn, sql, params=params, max_rows=SCHEMA_SCAN_LIMIT)
        elif db_type in ("postgresql", "kingbase"):
            s = s or "public"
            params = (s, pattern) if has_pattern else (s,)
            result = execute_query(conn, sql, params=params, max_rows=SCHEMA_SCAN_LIMIT)
        else:
            schema_val = s or default_schema("sqlserver")
            params = (pattern, schema_val) if has_pattern else (schema_val,)
            result = execute_query(conn, sql, params=params, max_rows=SCHEMA_SCAN_LIMIT)

        if not result.get("success"):
            _out(result, fmt)
            return

        rows = result.get("rows", [])
        if detail == _DETAIL_NAMES:
            names = [r.get("VIEW_NAME", "") for r in rows]
            _out({"success": True, "views": names, "count": len(names)}, fmt)
        elif detail == _DETAIL_SUMMARY:
            items = [{"name": r.get("VIEW_NAME", ""), "schema": s} for r in rows]
            _out({"success": True, "views": items, "count": len(items)}, fmt)
        else:
            _out({"success": True, "views": rows, "count": len(rows)}, fmt)
    finally:
        conn.dispose()


def _explore_routines(routine_type: str, schema: str | None, pattern: str | None, detail: str, fmt: str) -> None:
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")
    s = schema or default_schema(db_type)
    pattern = pattern or "%"

    try:
        if db_type == "sqlite":
            _out({"success": True, routine_type + "s": [], "count": 0, "note": "SQLite does not support stored procedures/functions"}, fmt)
            return

        if db_type == "mysql":
            db = cfg.get("database", "mysql")
            type_filter = "PROCEDURE" if routine_type == "procedure" else "FUNCTION"
            detail_variant = "names" if detail == _DETAIL_NAMES else "full"
            sql = _SQL[("_explore_routines", "mysql", detail_variant)]
            result = execute_query(conn, sql, params=(db, type_filter, pattern), max_rows=SCHEMA_SCAN_LIMIT)
        elif db_type in ("postgresql", "kingbase"):
            s = s or "public"
            kind = "p" if routine_type == "procedure" else "f"
            detail_variant = "names" if detail == _DETAIL_NAMES else "full"
            sql = _SQL[("_explore_routines", "postgresql", detail_variant)]
            result = execute_query(conn, sql, params=(s, kind, pattern), max_rows=SCHEMA_SCAN_LIMIT)
        else:
            schema_val = s or default_schema("sqlserver")
            type_filter = "P" if routine_type == "procedure" else "FN"
            detail_variant = "names" if detail == _DETAIL_NAMES else "full"
            sql = _SQL[("_explore_routines", "sqlserver", detail_variant)]
            result = execute_query(conn, sql, params=(type_filter, schema_val, pattern), max_rows=SCHEMA_SCAN_LIMIT)

        if not result.get("success"):
            _out(result, fmt)
            return

        rows = result.get("rows", [])
        key = routine_type + "s"
        if detail == _DETAIL_NAMES:
            names = [r.get("ROUTINE_NAME", r.get("routine_name", "")) for r in rows]
            _out({"success": True, key: names, "count": len(names)}, fmt)
        elif detail == _DETAIL_SUMMARY:
            items = []
            for r in rows:
                items.append(
                    {
                        "name": r.get("ROUTINE_NAME", r.get("routine_name", "")),
                        "type": r.get("ROUTINE_TYPE", r.get("prokind", r.get("type_desc", ""))),
                        "return_type": r.get("return_type", r.get("DTD_IDENTIFIER", "")),
                    }
                )
            _out({"success": True, key: items, "count": len(items)}, fmt)
        else:
            _out({"success": True, key: rows, "count": len(rows)}, fmt)
    finally:
        conn.dispose()


def _build_semantic_payload(
    conn,
    cfg,
    query: str,
    limit: int,
    enable_level2: bool = True,
) -> dict:
    """构建语义搜索载荷(共享内部函数,消除 data_cmds 与 explore_cmds 代码重复)。

    Args:
        conn: 数据库连接
        cfg: 连接配置
        query: 搜索关键词
        limit: 返回上限
        enable_level2: 是否启用两级补全(Level 1 表名 → Level 2 列数据)

    Returns:
        build_semantic_matches 返回的标准载荷字典(含 matches/score/complete 等)
    """
    db_type = cfg.get("db_type", "sqlserver")
    index = fetch_semantic_index(conn, mode="tables")
    tables = index.get("tables", {})
    hot = load_all_alias_sources(cfg)

    # L2 Feedback: 加载学习指标(表状态标记等)
    # 延迟导入：_query_learning → _security → _drivers，顶层导入会与 explore_cmds 形成循环
    from _query_learning import get_table_metrics, _DEFAULT_LEARNED_PATH

    metrics = get_table_metrics(_DEFAULT_LEARNED_PATH)
    index_level = index.get("level", "tables")

    # Level-1 评分(表名+注释,无列数据)
    scored_payload = build_semantic_matches(
        query,
        tables,
        hot,
        limit,
        skipped_routines=index.get("skipped_routines"),
        learned_metrics=metrics,
    )

    # 两级补全逻辑:若 top 匹配不足 limit 且当前是 tables 模式
    if enable_level2 and index_level == "tables" and scored_payload.get("total_matched", 0) < limit and scored_payload.get("matches"):
        # 补全 top 结果的列信息后重新打分
        eff_schema = index.get("schema") or ("public" if db_type in ("postgresql", "kingbase") else "dbo")
        match_names = [m["name"] for m in scored_payload["matches"]]
        col_data = _fetch_columns_for_tables(conn, db_type, eff_schema, match_names)
        # 合并列数据到 tables
        for tname, cols_info in col_data.items():
            if tname in tables and tables[tname].get("_stub"):
                tables[tname].pop("_stub", None)
                tables[tname]["columns"] = cols_info.get("columns", [])
                tables[tname]["column_meta"] = cols_info.get("column_meta", {})
                tables[tname]["fks"] = []
        # 重新评分(此时列数据已就位)
        scored_payload = build_semantic_matches(
            query,
            tables,
            hot,
            limit,
            skipped_routines=index.get("skipped_routines"),
            learned_metrics=metrics,
        )

    return scored_payload


def _explore_semantic(semantic: str, limit: int, fmt: str, enable_level2: bool = True) -> None:
    """两级语义搜索入口(统一 explore 命令调用)。

    Args:
        semantic: 搜索关键词
        limit: 返回上限
        fmt: 输出格式
        enable_level2: 是否启用两级补全。True = 探索默认(表名匹配不足时展开列数据重新打分),
                       False = 旧版 search --semantic 行为(仅表名+注释,无列数据展开)。
    """
    conn, cfg = get_connection()
    try:
        payload = _build_semantic_payload(conn, cfg, semantic, limit, enable_level2=enable_level2)
        _out(payload, fmt)
    finally:
        conn.dispose()
