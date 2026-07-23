#!/usr/bin/env python3
"""
cli.repl_cmds - 交互式 REPL 命令

实现交互式 SQL 命令行模式。
"""

import sys
import argparse
import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

from sqlalchemy.engine import Engine

from core.config import load_config, CONFIG_DIR
from core.history import append_history as _append_history
from _drivers import connect, execute_query, default_schema, list_schemas
from _semantic_index import SCHEMA_SCAN_LIMIT
from _formatters import format_result
from _security import check_read_only, count_statements, quote_ident

from .connection_cmds import cmd_list, cmd_use, cmd_ping
from .explore_cmds import cmd_explore
from .data_cmds import cmd_sample, cmd_profile, cmd_history


# ── 类型别名 ──────────────────────────────────────────────────────────
DotHandler = Callable[["ReplState", list[str]], None]


@dataclass
class ReplState:
    """REPL 运行时状态，替代 nonlocal 变量闭包。"""

    conn: Engine
    conn_cfg: dict
    db_type: str
    schema: Optional[str]
    active: str
    max_rows: int = 1000
    hist_path: str = field(default="")


# ── Dot 命令实现 ──────────────────────────────────────────────────────


def _dot_schema(state: ReplState, rem: list[str]) -> None:
    detail = "--detail" in rem
    schema_args = [r for r in rem if r != "--detail"]
    schema_name = schema_args[0] if schema_args else state.schema
    s = schema_name or default_schema(state.db_type)
    conn = state.conn
    db_type = state.db_type
    cfg = state.conn_cfg
    if db_type == "sqlite":
        result = execute_query(
            conn,
            "SELECT name AS TABLE_NAME, type AS TABLE_TYPE FROM sqlite_master "
            "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' ORDER BY name",
            max_rows=SCHEMA_SCAN_LIMIT,
        )
    elif db_type == "mysql":
        db = cfg.get("database", "mysql")
        result = execute_query(
            conn,
            "SELECT TABLE_NAME, TABLE_TYPE FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME",
            params=(db,),
            max_rows=SCHEMA_SCAN_LIMIT,
        )
    elif db_type in ("postgresql", "kingbase"):
        result = execute_query(
            conn,
            "SELECT tablename AS TABLE_NAME, 'BASE TABLE' AS TABLE_TYPE "
            "FROM pg_tables WHERE schemaname = %s "
            "UNION ALL "
            "SELECT viewname, 'VIEW' FROM pg_views WHERE schemaname = %s "
            "ORDER BY TABLE_NAME",
            params=(s, s),
            max_rows=SCHEMA_SCAN_LIMIT,
        )
    else:
        result = execute_query(
            conn,
            "SELECT TABLE_NAME, TABLE_TYPE FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME",
            params=(s,),
            max_rows=SCHEMA_SCAN_LIMIT,
        )
    if not result.get("success"):
        print(format_result(result))
        return
    tables = [r["TABLE_NAME"] for r in result.get("rows", []) if r.get("TABLE_TYPE", "").upper() in ("BASE TABLE", "table")]
    views = [r["TABLE_NAME"] for r in result.get("rows", []) if r.get("TABLE_TYPE", "").upper() in ("VIEW", "view")]
    if not tables and not views:
        all_schemas = list_schemas(conn, db_type)
        if all_schemas:
            print(f"Schema '{s}' 下无表/视图。该数据库的所有 schema：")
            for sc in all_schemas:
                print(f"  - {sc}")
            print("提示：用 schema --schema <名称> 指定，或 columns/sample 加 --schema")
            return
    if db_type in ("sqlserver", "postgresql"):
        print(f"Schema: {s}")
    elif db_type == "mysql":
        print(f"数据库: {cfg.get('database', 'mysql')}")
    _TABLE_LINE_THRESHOLD = 50
    print(f"表 ({len(tables)}):")
    if len(tables) <= _TABLE_LINE_THRESHOLD:
        print(f"  {', '.join(tables)}" if tables else "  (无)")
    else:
        for i, t in enumerate(tables, 1):
            print(f"  {i:>4}. {t}")
    if views:
        print(f"视图 ({len(views)}):")
        if len(views) <= _TABLE_LINE_THRESHOLD:
            print(f"  {', '.join(views)}")
        else:
            for i, v in enumerate(views, 1):
                print(f"  {i:>4}. {v}")
    if detail and tables:
        if db_type == "sqlite":
            for t in tables[:50]:
                col_result = execute_query(conn, f"PRAGMA table_info({quote_ident(t, 'sqlite')})")
                if col_result.get("success") and col_result.get("rows"):
                    print(f"\n### {t}")
                    print(format_result(col_result, title=""))
        else:
            if db_type == "mysql":
                col_sql = (
                    "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, "
                    "IS_NULLABLE, ORDINAL_POSITION, COLUMN_DEFAULT "
                    "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = %s "
                    "ORDER BY TABLE_NAME, ORDINAL_POSITION"
                )
                col_params = (cfg.get("database", "mysql"),)
            elif db_type in ("postgresql", "kingbase"):
                col_sql = (
                    "SELECT table_name AS TABLE_NAME, column_name AS COLUMN_NAME, "
                    "data_type AS DATA_TYPE, character_maximum_length, "
                    "is_nullable AS IS_NULLABLE, ordinal_position AS ORDINAL_POSITION, "
                    "column_default AS COLUMN_DEFAULT "
                    "FROM information_schema.columns WHERE table_schema = %s "
                    "ORDER BY table_name, ordinal_position"
                )
                col_params = (s,)
            else:
                col_sql = (
                    "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, CHARACTER_MAXIMUM_LENGTH, "
                    "IS_NULLABLE, ORDINAL_POSITION, COLUMN_DEFAULT "
                    "FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = %s "
                    "ORDER BY TABLE_NAME, ORDINAL_POSITION"
                )
                col_params = (s,)
            col_result = execute_query(conn, col_sql, params=col_params, max_rows=SCHEMA_SCAN_LIMIT)
            if col_result.get("success"):
                current_table = None
                for r in col_result.get("rows", []):
                    if r["TABLE_NAME"] != current_table:
                        current_table = r["TABLE_NAME"]
                        print(f"\n### {current_table}")
                    print(f"  {r['COLUMN_NAME']} ({r['DATA_TYPE']}) {'NOT NULL' if r.get('IS_NULLABLE', '').upper() == 'NO' else ''}")


def _dot_tables(state: ReplState, rem: list[str]) -> None:
    a2 = argparse.Namespace(
        object_type="table",
        table=None,
        schema=rem[0] if rem else state.schema,
        pattern="%",
        detail="names",
        semantic=None,
        limit=10,
        format="table",
    )
    cmd_explore(a2)


def _dot_columns(state: ReplState, rem: list[str]) -> None:
    if not rem:
        print("用法: .columns <table>")
        return
    a2 = argparse.Namespace(
        object_type="column",
        table=rem[0],
        schema=rem[1] if len(rem) > 1 else state.schema,
        pattern=None,
        detail="names",
        semantic=None,
        limit=10,
        format="table",
    )
    cmd_explore(a2)


def _dot_indexes(state: ReplState, rem: list[str]) -> None:
    if not rem:
        print("用法: .indexes <table>")
        return
    a2 = argparse.Namespace(
        object_type="index",
        table=rem[0],
        schema=rem[1] if len(rem) > 1 else state.schema,
        pattern=None,
        detail="names",
        semantic=None,
        limit=10,
        format="table",
    )
    cmd_explore(a2)


def _dot_fk(state: ReplState, rem: list[str]) -> None:
    if not rem:
        print("用法: .foreign-keys <table>")
        return
    a2 = argparse.Namespace(
        object_type="fk",
        table=rem[0],
        schema=rem[1] if len(rem) > 1 else state.schema,
        pattern=None,
        detail="names",
        semantic=None,
        limit=10,
        format="table",
    )
    cmd_explore(a2)


def _dot_constraints(state: ReplState, rem: list[str]) -> None:
    if not rem:
        print("用法: .constraints <table>")
        return
    a2 = argparse.Namespace(
        object_type="constraint",
        table=rem[0],
        schema=rem[1] if len(rem) > 1 else state.schema,
        pattern=None,
        detail="names",
        semantic=None,
        limit=10,
        format="table",
    )
    cmd_explore(a2)


def _dot_sample(state: ReplState, rem: list[str]) -> None:
    if not rem:
        print("用法: .sample <table> [n]")
        return
    try:
        n = int(rem[1]) if len(rem) > 1 else 5
    except ValueError:
        print("ERROR: n 必须是整数", file=sys.stderr)
        return
    a2 = argparse.Namespace(table=rem[0], n=n, schema=rem[2] if len(rem) > 2 else state.schema)
    cmd_sample(a2)


def _dot_profile(state: ReplState, rem: list[str]) -> None:
    if not rem:
        print("用法: .profile <table>")
        return
    a2 = argparse.Namespace(table=rem[0], schema=rem[1] if len(rem) > 1 else state.schema)
    cmd_profile(a2)


def _dot_use(state: ReplState, rem: list[str]) -> None:
    if not rem:
        print("用法: .use <name>")
        return
    cmd_use(argparse.Namespace(name=rem[0]))
    new_cfg = load_config()
    new_active = new_cfg.get("active")
    if new_active and new_active in new_cfg.get("connections", {}):
        try:
            state.conn.dispose()
        except Exception:
            logger.debug("dispose of old connection failed", exc_info=True)
        state.conn_cfg = new_cfg["connections"][new_active]
        state.conn = connect(state.conn_cfg)
        state.db_type = state.conn_cfg.get("db_type", "sqlserver")
        state.schema = state.schema or default_schema(state.db_type)
        state.active = new_active


def _dot_list(state: ReplState, rem: list[str]) -> None:
    cmd_list(argparse.Namespace())


def _dot_ping(state: ReplState, rem: list[str]) -> None:
    cmd_ping(argparse.Namespace(name=None))


def _dot_history(state: ReplState, rem: list[str]) -> None:
    try:
        n = int(rem[0]) if rem else 50
    except ValueError:
        print("ERROR: n 必须是整数", file=sys.stderr)
        return
    cmd_history(argparse.Namespace(n=n))


def _dot_help(state: ReplState, rem: list[str]) -> None:
    print(REPL_HELP)


# ── 命令分发表 ────────────────────────────────────────────────────────

REPL_HELP = """\
命令: .schema [detail] | .tables | .columns <tbl> | .indexes <tbl> | .fk <tbl> | .constraints <tbl>
      .sample <tbl> [n] | .profile <tbl> | .history [n] | .use <name> | .list | .ping | .help | .exit/.quit"""

DOT_COMMANDS: dict[str, DotHandler] = {
    ".schema": _dot_schema,
    ".tables": _dot_tables,
    ".columns": _dot_columns,
    ".indexes": _dot_indexes,
    ".fk": _dot_fk,
    ".foreign-keys": _dot_fk,
    ".constraints": _dot_constraints,
    ".sample": _dot_sample,
    ".profile": _dot_profile,
    ".use": _dot_use,
    ".list": _dot_list,
    ".ping": _dot_ping,
    ".history": _dot_history,
    ".help": _dot_help,
}


# ── REPL 主入口 ────────────────────────────────────────────────────────


def cmd_repl(args: argparse.Namespace) -> None:
    """交互式 SQL 命令行"""
    cfg = load_config()
    active = cfg.get("active")
    if not active:
        print("ERROR: 无活动连接，请先使用 connect 命令建立连接", file=sys.stderr)
        sys.exit(1)

    conn = connect(cfg["connections"][active])
    conn_cfg = cfg["connections"][active]
    db_type = conn_cfg.get("db_type", "sqlserver")
    hist_path = CONFIG_DIR / "history.txt"
    hist_path.parent.mkdir(parents=True, exist_ok=True)

    state = ReplState(
        conn=conn,
        conn_cfg=conn_cfg,
        db_type=db_type,
        schema=args.schema or default_schema(db_type),
        active=active,
        max_rows=args.max_rows or 1000,
        hist_path=str(hist_path),
    )

    def _handle_dot(cmd: str) -> bool:
        parts = cmd.strip().split()
        if not parts:
            return False
        sub = parts[0]
        rem = parts[1:]

        if sub in (".exit", ".quit"):
            raise SystemExit
        handler = DOT_COMMANDS.get(sub)
        if handler is not None:
            handler(state, rem)
            return True
        return False

    print(f"REPL 模式 [{active}] | .help 查看命令 | .exit 退出")
    try:
        while True:
            try:
                line = input("db> ").strip()
            except EOFError:
                print()
                break
            if not line:
                continue
            _append_history(line)
            if not _handle_dot(line):
                if count_statements(line) > 1:
                    print("拒绝: 多语句 SQL 不被允许")
                    continue
                is_ro, first, reason = check_read_only(line, strict=True)
                if not is_ro:
                    print(f"拒绝: {reason}，当前模式不允许写操作")
                    continue
                result = execute_query(state.conn, line, max_rows=state.max_rows)
                print(format_result(result, title="查询结果"))
    finally:
        state.conn.dispose()
