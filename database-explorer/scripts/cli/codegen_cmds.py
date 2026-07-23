#!/usr/bin/env python3
"""
cli.codegen_cmds - 代码生成命令

实现 script（DDL 生成）、crud（CRUD SQL 生成）等代码生成命令。
"""

import sys
import argparse

from core.connection import get_connection
from _drivers import execute_query, DRIVERS, default_schema
from _security import quote_ident

# SQL Server 主键列查询 — cmd_script 和 cmd_crud 共享
_SQLSERVER_PK_SQL = (
    "SELECT c.name AS COLUMN_NAME FROM sys.indexes i "
    "JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id "
    "JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id "
    "JOIN sys.tables t ON i.object_id = t.object_id "
    "WHERE SCHEMA_NAME(t.schema_id) = %s AND t.name = %s AND i.is_primary_key = 1 "
    "ORDER BY ic.key_ordinal"
)


def cmd_script(args: argparse.Namespace) -> None:
    """生成建表脚本"""
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")

    try:
        if db_type == "sqlite":
            result = execute_query(conn, "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", params=(args.table,))
            if result["success"] and result["rows"]:
                script = result["rows"][0].get("sql", "")
                print(f"**表**: {args.table}")
                print("```sql")
                print(script)
                print("```")
            else:
                print(f"ERROR: 表 '{args.table}' 不存在", file=sys.stderr)
        elif db_type == "mysql":
            result = execute_query(conn, "SHOW CREATE TABLE " + quote_ident(args.table, "mysql"))
            if result["success"] and result["rows"]:
                key = [k for k in result["rows"][0] if "create" in k.lower()]
                script = result["rows"][0].get(key[0] if key else list(result["rows"][0].keys())[-1], "")
                print(f"**表**: {args.table}")
                print("```sql")
                print(script)
                print("```")
        elif db_type in ("postgresql", "kingbase"):
            s = args.schema or "public"
            ident = quote_ident(args.table, db_type, s)
            col_result = execute_query(
                conn,
                "SELECT column_name, data_type, character_maximum_length, "
                "is_nullable, column_default "
                "FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                "ORDER BY ordinal_position",
                params=(s, args.table),
            )
            if col_result["success"] and col_result["rows"]:
                lines = [f"CREATE TABLE {ident} ("]
                for r in col_result["rows"]:
                    line = f'  "{r["column_name"]}" {r["data_type"]}'
                    if r.get("character_maximum_length"):
                        line += f"({r['character_maximum_length']})"
                    if r["is_nullable"] == "NO":
                        line += " NOT NULL"
                    if r.get("column_default"):
                        line += f" DEFAULT {r['column_default']}"
                    lines.append(line)
                lines.append(");")
                print(f"**表**: {s}.{args.table}")
                print("```sql")
                print("\n".join(lines))
                print("```")
        else:
            # SQL Server
            s = args.schema or default_schema("sqlserver")
            ident = quote_ident(args.table, "sqlserver", s)
            col_result = execute_query(
                conn,
                "SELECT COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, "
                "IS_NULLABLE, COLUMN_DEFAULT, "
                "COLUMNPROPERTY(OBJECT_ID(%s), COLUMN_NAME, 'IsIdentity') AS is_identity "
                "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s "
                "ORDER BY ORDINAL_POSITION",
                params=(ident, s, args.table),
            )
            if col_result["success"] and col_result["rows"]:
                lines = [f"CREATE TABLE {ident} ("]
                for r in col_result["rows"]:
                    line = f"[{r['COLUMN_NAME']}] {r['DATA_TYPE']}"
                    mlen = r.get("CHARACTER_MAXIMUM_LENGTH")
                    if mlen and r["DATA_TYPE"] in ("varchar", "nvarchar", "char", "nchar"):
                        line += f"({mlen})"
                    if r["IS_NULLABLE"] == "NO":
                        line += " NOT NULL"
                    if r.get("is_identity"):
                        line += " IDENTITY(1,1)"
                    if r.get("COLUMN_DEFAULT"):
                        line += f" DEFAULT {r['COLUMN_DEFAULT']}"
                    lines.append(line)

                # 主键信息
                pk_result = execute_query(conn, _SQLSERVER_PK_SQL, params=(s, args.table))
                if pk_result.get("success") and pk_result["rows"]:
                    pk_cols = ", ".join(f"[{r['COLUMN_NAME']}]" for r in pk_result["rows"])
                    lines.append(f"    CONSTRAINT [PK_{args.table}] PRIMARY KEY ({pk_cols})")

                # 非聚集索引提示
                idx_sql = (
                    "SELECT i.name AS INDEX_NAME, i.type_desc FROM sys.indexes i "
                    "JOIN sys.tables t ON i.object_id = t.object_id "
                    "WHERE SCHEMA_NAME(t.schema_id) = %s AND t.name = %s "
                    "AND i.is_primary_key = 0 AND i.type > 0 "
                    "ORDER BY i.name"
                )
                idx_result = execute_query(conn, idx_sql, params=(s, args.table))
                idx_count = len(idx_result.get("rows", [])) if idx_result.get("success") else 0

                lines.append(");")
                print(f"**表**: {s}.{args.table}")
                print("```sql")
                print("\n".join(lines))
                print("```")
                if idx_count:
                    print(f"> 另有 {idx_count} 个非聚集索引，请用 `sp_helpindex [{args.table}]` 查看详情。")
            else:
                print(f"ERROR: 表 '{s}.{args.table}' 不存在或无列信息", file=sys.stderr)
    finally:
        conn.dispose()


def cmd_crud(args: argparse.Namespace) -> None:
    """生成 CRUD SQL 语句"""
    conn, cfg = get_connection()
    db_type = cfg.get("db_type", "sqlserver")

    try:
        schema = args.schema or default_schema(db_type)

        # 先获取列信息
        if db_type == "sqlite":
            col_result = execute_query(conn, f"PRAGMA table_info({quote_ident(args.table, 'sqlite')})")
            cols = col_result.get("rows", [])
            col_names = [c["name"] for c in cols]
            pk_cols = [c["name"] for c in cols if c.get("pk")]
        else:
            if db_type == "mysql":
                col_result = execute_query(
                    conn,
                    "SELECT COLUMN_NAME, DATA_TYPE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                    params=(cfg.get("database"), args.table),
                )
            elif db_type in ("postgresql", "kingbase"):
                s = schema or "public"
                col_result = execute_query(
                    conn,
                    "SELECT column_name AS COLUMN_NAME, data_type AS DATA_TYPE "
                    "FROM information_schema.columns WHERE table_schema = %s AND table_name = %s "
                    "ORDER BY ordinal_position",
                    params=(s, args.table),
                )
            else:
                col_result = execute_query(
                    conn,
                    "SELECT COLUMN_NAME, DATA_TYPE FROM INFORMATION_SCHEMA.COLUMNS "
                    "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s ORDER BY ORDINAL_POSITION",
                    params=(schema, args.table),
                )
            col_names = [r["COLUMN_NAME"] for r in col_result.get("rows", [])]

            # 获取主键
            if db_type == "mysql":
                pk_result = execute_query(
                    conn,
                    "SELECT COLUMN_NAME FROM information_schema.KEY_COLUMN_USAGE "
                    "WHERE TABLE_SCHEMA = %s AND TABLE_NAME = %s AND CONSTRAINT_NAME = 'PRIMARY'",
                    params=(cfg.get("database"), args.table),
                )
            elif db_type in ("postgresql", "kingbase"):
                pk_result = execute_query(
                    conn,
                    "SELECT a.attname AS COLUMN_NAME FROM pg_index i "
                    "JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey) "
                    "JOIN pg_class t ON t.oid = i.indrelid "
                    "WHERE t.relname = %s AND i.indisprimary",
                    params=(args.table,),
                )
            else:
                pk_result = execute_query(conn, _SQLSERVER_PK_SQL, params=(schema, args.table))
            pk_cols = [r["COLUMN_NAME"] for r in pk_result.get("rows", [])]

        if not col_names:
            print(f"ERROR: 表 '{args.table}' 不存在或无列信息", file=sys.stderr)
            return

        ident = quote_ident(args.table, db_type, schema)
        ph = DRIVERS[db_type]["placeholder"]

        def _qcol(name: str) -> str:
            """引用列标识符（不附加 schema）"""
            return quote_ident(name, db_type)

        quoted_cols = [_qcol(c) for c in col_names]
        quoted_pks = [_qcol(c) for c in pk_cols]

        # INSERT
        cols_str = ", ".join(quoted_cols)
        vals_str = ", ".join([ph] * len(col_names))
        print("-- INSERT")
        print(f"INSERT INTO {ident} ({cols_str})")
        print(f"VALUES ({vals_str});\n")

        # SELECT
        print("-- SELECT ALL")
        print(f"SELECT {cols_str} FROM {ident};\n")

        if pk_cols:
            where = " AND ".join(f"{qc} = {ph}" for qc in quoted_pks)
            print("-- SELECT BY PK")
            print(f"SELECT {cols_str} FROM {ident} WHERE {where};\n")

        # UPDATE
        if pk_cols:
            set_parts = [f"{qc} = {ph}" for qc, cn in zip(quoted_cols, col_names) if cn not in pk_cols]
            set_clause = ", ".join(set_parts)
            where = " AND ".join(f"{qc} = {ph}" for qc in quoted_pks)
            if set_clause:
                print("-- UPDATE BY PK")
                print(f"UPDATE {ident} SET {set_clause} WHERE {where};\n")

        # DELETE
        if pk_cols:
            where = " AND ".join(f"{qc} = {ph}" for qc in quoted_pks)
            print("-- DELETE BY PK")
            print(f"DELETE FROM {ident} WHERE {where};\n")

    finally:
        conn.dispose()
