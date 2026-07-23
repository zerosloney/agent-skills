# -*- coding: utf-8 -*-
"""语义索引构建与缓存 — 从 _drivers.py 拆分

职责：
- 两级语义索引（Level 1 表名 → Level 2 完整列/外键/存储过程）
- 进程内缓存 + 磁盘缓存 + TTL 过期
- 批量 SQL 构建（各方言）

依赖方向：本模块 → _drivers（单向），不反向导入。
"""

import os
import time
import json
import hashlib
import logging
import threading
from pathlib import Path

logger = logging.getLogger(__name__)

# SQLAlchemy 可选导入（本模块只用 inspect/Engine，不需要自己 create_engine）
try:
    from sqlalchemy.engine import Engine
    from sqlalchemy import inspect

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

from _drivers import execute_query, default_schema


def _engine_db_type(url) -> str:
    """从 Engine URL 推断 db_type（用于无 cfg 上下文时）。"""
    backend = url.get_backend_name()
    mapping = {"mssql": "sqlserver", "mysql": "mysql", "postgresql": "postgresql", "sqlite": "sqlite"}
    return mapping.get(backend, "sqlserver")


# ═══════════════════════════════════════════════════════════════
#  常量
# ═══════════════════════════════════════════════════════════════

# Schema 扫描默认最大表/行数（避免超大库返回过重）
SCHEMA_SCAN_LIMIT = 5000

# 语义索引进程内缓存：key = (url_without_password, schema) → (timestamp, index dict)
# 避免同进程多次 search --semantic 重复拉取（单次 CLI 调用内也复用）
# TTL 300 秒后自动失效，防止 pipe 模式下 schema 变更后拿到陈旧数据
_SEMANTIC_CACHE: dict[tuple, tuple[float, dict]] = {}
_SEMANTIC_CACHE_TTL = 300  # seconds
_SEMANTIC_DISK_CACHE_MAX_BYTES = 50 * 1024 * 1024  # 50 MB total
_CACHE_LOCK = threading.Lock()  # 保护 _SEMANTIC_CACHE 的并发访问（--pipe 模式）


# ═══════════════════════════════════════════════════════════════
#  缓存管理
# ═══════════════════════════════════════════════════════════════


def invalidate_semantic_cache() -> None:
    """清除语义索引缓存（pipe 模式下连接切换或 DDL 后调用）。"""
    with _CACHE_LOCK:
        _SEMANTIC_CACHE.clear()


def _semantic_disk_cache_dir() -> Path:
    home = os.environ.get("DATABASE_EXPLORER_HOME")
    base = Path(home) if home else Path.home() / ".database-explorer"
    return base / "cache"


def _semantic_disk_cache_path(cache_key: tuple) -> Path:
    raw = json.dumps(cache_key, ensure_ascii=False, sort_keys=True)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return _semantic_disk_cache_dir() / f"{digest}.semantic.json"


def _load_semantic_disk_cache(cache_key: tuple) -> dict | None:
    path = _semantic_disk_cache_path(cache_key)
    try:
        if not path.is_file():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        if time.time() - float(payload.get("created_at", 0)) >= _SEMANTIC_CACHE_TTL:
            return None
        data = payload.get("data")
        return data if isinstance(data, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _save_semantic_disk_cache(cache_key: tuple, data: dict) -> None:
    path = _semantic_disk_cache_path(cache_key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"created_at": time.time(), "data": data}, ensure_ascii=False),
            encoding="utf-8",
        )
    except OSError:
        logger.debug("failed to write semantic disk cache: %s", path, exc_info=True)
    _semantic_disk_cache_evict_if_needed()


def _semantic_disk_cache_evict_if_needed() -> None:
    """LRU 清理：若磁盘缓存总大小超阈值，删除最旧的文件。"""
    cache_dir = _semantic_disk_cache_dir()
    if not cache_dir.is_dir():
        return
    try:
        files = list(cache_dir.glob("*.semantic.json"))
        if not files:
            return
        total_size = sum(f.stat().st_size for f in files)
        if total_size <= _SEMANTIC_DISK_CACHE_MAX_BYTES:
            return
        files.sort(key=lambda f: f.stat().st_mtime)
        for old_file in files:
            if total_size <= _SEMANTIC_DISK_CACHE_MAX_BYTES:
                break
            try:
                total_size -= old_file.stat().st_size
                old_file.unlink()
            except OSError:
                logger.debug("failed to evict cache file: %s", old_file, exc_info=True)
    except OSError:
        logger.debug("cache eviction scan failed", exc_info=True)


def _apply_max_tables(result: dict, max_tables: int | None) -> dict:
    if not max_tables:
        return result
    tables = result.get("tables", {})
    if len(tables) <= max_tables:
        return result
    limited = dict(list(tables.items())[:max_tables])
    return {
        **result,
        "tables": limited,
        "total": len(limited),
        "truncated": True,
        "full_count": len(tables),
    }


# ═══════════════════════════════════════════════════════════════
#  Level-1：表名索引
# ═══════════════════════════════════════════════════════════════


def _fetch_table_names(engine: Engine, db_type: str, schema: str) -> dict:
    """Level-1 语义索引：只取表名+表注释，单条 SQL，极快。

    用于首次语义搜索的快速评分，不含列数据。
    仅返回 {"tables": {name: {comment, type}}}
    """
    tables: dict[str, dict] = {}
    try:
        if db_type == "sqlite":
            sql = (
                "SELECT name AS TABLE_NAME, type AS TABLE_TYPE FROM sqlite_master "
                "WHERE type IN ('table', 'view') AND name NOT LIKE 'sqlite_%' "
                "ORDER BY name"
            )
            result = execute_query(engine, sql, max_rows=None)
        elif db_type == "mysql":
            db = engine.url.database or "mysql"
            sql = "SELECT TABLE_NAME, TABLE_TYPE, TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA = %s ORDER BY TABLE_NAME"
            result = execute_query(engine, sql, params=(db,), max_rows=None)
        elif db_type in ("postgresql", "kingbase"):
            sql = (
                "SELECT c.relname AS TABLE_NAME, 'BASE TABLE' AS TABLE_TYPE, "
                "obj_description(c.oid) AS TABLE_COMMENT "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = %s AND c.relkind IN ('r', 'v', 'f') "
                "ORDER BY c.relname"
            )
            result = execute_query(engine, sql, params=(schema,), max_rows=None)
        else:  # sqlserver
            sql = (
                "SELECT t.name AS TABLE_NAME, t.type_desc AS TABLE_TYPE, "
                "CAST(ep.value AS nvarchar(max)) AS TABLE_COMMENT "
                "FROM sys.tables t "
                "LEFT JOIN sys.extended_properties ep ON ep.major_id = t.object_id "
                "AND ep.minor_id = 0 AND ep.name = 'MS_Description' "
                "WHERE SCHEMA_NAME(t.schema_id) = %s "
                "ORDER BY t.name"
            )
            result = execute_query(engine, sql, params=(schema,), max_rows=None)

        if result.get("success"):
            for r in result["rows"]:
                tname = r.get("TABLE_NAME", "")
                if not tname:
                    continue
                tables[tname] = {
                    "comment": r.get("TABLE_COMMENT", "") or "",
                    "type": r.get("TABLE_TYPE") or r.get("type_desc", "") or "",
                    "_stub": True,
                }
    except Exception:
        logger.debug("table names fetch failed for %s/%s", db_type, schema, exc_info=True)
    return {"tables": tables, "total": len(tables)}


# ═══════════════════════════════════════════════════════════════
#  Level-2：列补充
# ═══════════════════════════════════════════════════════════════


def _fetch_columns_for_tables(engine: Engine, db_type: str, schema: str, table_names: list[str]) -> dict[str, dict]:
    """Level-2 列补充：为指定表列表补全列信息（仅 1 条批量 SQL）。"""
    if not table_names:
        return {}
    tables_out: dict[str, dict] = {t: {"columns": [], "column_meta": {}} for t in table_names}
    try:
        if db_type == "sqlite":
            placeholders = ", ".join(["?"] * len(table_names))
            sql = (
                f"SELECT m.name AS TABLE_NAME, p.name AS COLUMN_NAME, p.type AS DATA_TYPE "
                f"FROM sqlite_master m JOIN pragma_table_info(m.name) p "
                f"WHERE m.type = 'table' AND m.name IN ({placeholders}) "
                f"ORDER BY m.name, p.cid"
            )
            result = execute_query(engine, sql, params=tuple(table_names), max_rows=None)
        elif db_type == "mysql":
            placeholders = ", ".join(["%s"] * len(table_names))
            db = engine.url.database or "mysql"
            sql = (
                f"SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT "
                f"FROM information_schema.COLUMNS "
                f"WHERE TABLE_SCHEMA = %s AND TABLE_NAME IN ({placeholders}) "
                f"ORDER BY TABLE_NAME, ORDINAL_POSITION"
            )
            result = execute_query(engine, sql, params=(db, *table_names), max_rows=None)
        elif db_type in ("postgresql", "kingbase"):
            placeholders = ", ".join(["%s"] * len(table_names))
            sql = (
                f"SELECT ic.table_name AS TABLE_NAME, ic.column_name AS COLUMN_NAME, "
                f"ic.data_type AS DATA_TYPE, "
                f"col_description(a.attrelid, a.attnum) AS COLUMN_COMMENT "
                f"FROM information_schema.columns ic "
                f"JOIN pg_class c ON c.relname = ic.table_name "
                f"JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = ic.column_name "
                f"WHERE ic.table_schema = %s AND ic.table_name IN ({placeholders}) "
                f"ORDER BY ic.table_name, ic.ordinal_position"
            )
            result = execute_query(engine, sql, params=(schema, *table_names), max_rows=None)
        else:  # sqlserver
            placeholders = ", ".join(["%s"] * len(table_names))
            sql = (
                f"SELECT c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, "
                f"CAST(ep.value AS nvarchar(max)) AS COLUMN_COMMENT "
                f"FROM INFORMATION_SCHEMA.COLUMNS c "
                f"LEFT JOIN sys.extended_properties ep "
                f"ON ep.major_id = OBJECT_ID(c.TABLE_SCHEMA + '.' + c.TABLE_NAME) "
                f"AND ep.minor_id = c.ORDINAL_POSITION AND ep.name = 'MS_Description' "
                f"WHERE c.TABLE_SCHEMA = %s AND c.TABLE_NAME IN ({placeholders}) "
                f"ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION"
            )
            result = execute_query(engine, sql, params=(schema, *table_names), max_rows=None)

        if result.get("success"):
            for r in result["rows"]:
                tname = r.get("TABLE_NAME", "")
                if tname not in tables_out:
                    continue
                cname = r.get("COLUMN_NAME", "")
                if not cname:
                    continue
                tables_out[tname]["columns"].append(cname)
                tables_out[tname]["column_meta"][cname] = {
                    "type": r.get("DATA_TYPE", "") or "",
                    "comment": r.get("COLUMN_COMMENT") or r.get("COLUMN_COMMENT", "") or "",
                }
    except Exception:
        logger.debug("columns fetch for %d tables failed", len(table_names), exc_info=True)
    return tables_out


# ═══════════════════════════════════════════════════════════════
#  批量索引构建
# ═══════════════════════════════════════════════════════════════


def _build_semantic_index_bulk(engine: Engine, db_type: str, schema: str | None) -> dict:
    """用批量 SQL 一次往返拿全表列+外键，按表名分组建索引。"""
    if db_type == "sqlite":
        return _semantic_index_sqlite(engine)

    if db_type == "sqlserver":
        col_sql = (
            "SELECT c.TABLE_NAME, c.COLUMN_NAME, c.DATA_TYPE, "
            "CAST(ep.value AS nvarchar(max)) AS COLUMN_COMMENT "
            "FROM INFORMATION_SCHEMA.COLUMNS c "
            "LEFT JOIN sys.extended_properties ep "
            "ON ep.major_id = OBJECT_ID(c.TABLE_SCHEMA + '.' + c.TABLE_NAME) "
            "AND ep.minor_id = c.ORDINAL_POSITION AND ep.name = 'MS_Description' "
            "WHERE c.TABLE_SCHEMA = :s ORDER BY c.TABLE_NAME, c.ORDINAL_POSITION"
        )
    elif db_type == "mysql":
        col_sql = (
            "SELECT TABLE_NAME, COLUMN_NAME, DATA_TYPE, COLUMN_COMMENT "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_SCHEMA = :s ORDER BY TABLE_NAME, ORDINAL_POSITION"
        )
    else:  # postgresql
        col_sql = (
            "SELECT ic.table_name AS TABLE_NAME, ic.column_name AS COLUMN_NAME, "
            "ic.data_type AS DATA_TYPE, col_description(c.oid, a.attnum) AS COLUMN_COMMENT "
            "FROM information_schema.columns ic "
            "JOIN pg_class c ON c.relname = ic.table_name "
            "JOIN pg_namespace n ON n.nspname = ic.table_schema AND c.relnamespace = n.oid "
            "JOIN pg_attribute a ON a.attrelid = c.oid AND a.attname = ic.column_name "
            "WHERE ic.table_schema = :s ORDER BY ic.table_name, ic.ordinal_position"
        )

    s = schema or ("public" if db_type in ("postgresql", "kingbase") else "dbo")
    col_result = execute_query(engine, col_sql, params={"s": s}, max_rows=None)

    tables: dict[str, dict] = {}
    if col_result.get("success"):
        for r in col_result["rows"]:
            tname = r["TABLE_NAME"]
            tables.setdefault(tname, {"columns": [], "column_meta": {}, "fks": []})
            tables[tname]["columns"].append(r["COLUMN_NAME"])
            tables[tname]["column_meta"][r["COLUMN_NAME"]] = {
                "type": r.get("DATA_TYPE", ""),
                "comment": r.get("COLUMN_COMMENT") or "",
            }

    table_comments = _fetch_table_comments_bulk(engine, db_type, s)
    for tname, comment in table_comments.items():
        if tname in tables and comment:
            tables[tname]["comment"] = comment

    fk_result = _fetch_fks_bulk(engine, db_type, s)
    if fk_result:
        fk_map: dict[tuple[str, str], dict] = {}
        for row in fk_result:
            key = (row["TABLE_NAME"], row["CONSTRAINT_NAME"])
            entry = fk_map.setdefault(
                key,
                {
                    "referred_table": row["REFERENCED_TABLE"],
                    "constrained_columns": [],
                    "referred_columns": [],
                },
            )
            if row["COLUMN_NAME"]:
                entry["constrained_columns"].append(row["COLUMN_NAME"])
            if row["REFERENCED_COLUMN"]:
                entry["referred_columns"].append(row["REFERENCED_COLUMN"])
        for (tname, _), fk in fk_map.items():
            if tname in tables:
                tables[tname]["fks"].append(fk)

    routines = _fetch_routines_bulk(engine, db_type, s)
    skipped_routines: list[str] = []
    for rname, rinfo in routines.items():
        if rname in tables and tables[rname].get("columns"):
            skipped_routines.append(rname)
            continue
        entry = tables.setdefault(rname, {"columns": [], "column_meta": {}, "fks": []})
        entry["type"] = rinfo["type"]
        if rinfo.get("comment"):
            entry["comment"] = rinfo["comment"]

    return {"tables": tables, "total": len(tables), "skipped_routines": skipped_routines}


def _fetch_table_comments_bulk(engine: Engine, db_type: str, schema: str) -> dict[str, str]:
    """批量拉取 schema 内表注释。"""
    try:
        if db_type == "sqlserver":
            sql = (
                "SELECT t.name AS TABLE_NAME, CAST(ep.value AS nvarchar(max)) AS TABLE_COMMENT "
                "FROM sys.tables t LEFT JOIN sys.extended_properties ep "
                "ON ep.major_id = t.object_id AND ep.minor_id = 0 AND ep.name = 'MS_Description' "
                "WHERE SCHEMA_NAME(t.schema_id) = :s"
            )
        elif db_type == "mysql":
            sql = "SELECT TABLE_NAME, TABLE_COMMENT FROM information_schema.TABLES WHERE TABLE_SCHEMA = :s"
        else:  # postgresql
            sql = (
                "SELECT c.relname AS TABLE_NAME, obj_description(c.oid) AS TABLE_COMMENT "
                "FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = :s AND c.relkind IN ('r', 'p')"
            )
        result = execute_query(engine, sql, params={"s": schema}, max_rows=None)
        if result.get("success"):
            return {r["TABLE_NAME"]: r.get("TABLE_COMMENT", "") for r in result["rows"] if r.get("TABLE_COMMENT")}
    except Exception:
        logger.warning("fetch table comments failed for %s — returned empty dict", schema, exc_info=True)
    return {}


def _fetch_routines_bulk(engine: Engine, db_type: str, schema: str) -> dict[str, dict]:
    """批量拉取 schema 内存储过程/函数，纳入语义索引。"""
    if db_type == "sqlite":
        return {}
    try:
        if db_type == "mysql":
            sql = (
                "SELECT ROUTINE_NAME, ROUTINE_TYPE, "
                "ROUTINE_DEFINITION, DTD_IDENTIFIER AS return_type "
                "FROM information_schema.ROUTINES "
                "WHERE ROUTINE_SCHEMA = :s AND ROUTINE_TYPE IN ('PROCEDURE', 'FUNCTION') "
                "ORDER BY ROUTINE_NAME"
            )
            result = execute_query(engine, sql, params={"s": schema}, max_rows=None)
        elif db_type in ("postgresql", "kingbase"):
            sql = (
                "SELECT proname AS routine_name, "
                "CASE prokind WHEN 'p' THEN 'PROCEDURE' ELSE 'FUNCTION' END AS routine_type, "
                "pg_get_function_result(oid) AS return_type, "
                "pg_get_functiondef(oid) AS definition "
                "FROM pg_proc "
                "WHERE pronamespace = (SELECT oid FROM pg_namespace WHERE nspname = :s) "
                "AND prokind IN ('p', 'f') "
                "ORDER BY proname"
            )
            result = execute_query(engine, sql, params={"s": schema}, max_rows=None)
        else:
            sql = (
                "SELECT ROUTINE_NAME, ROUTINE_TYPE, "
                "CAST(ROUTINE_DEFINITION AS nvarchar(max)) AS ROUTINE_DEFINITION "
                "FROM INFORMATION_SCHEMA.ROUTINES WHERE ROUTINE_SCHEMA = :s"
            )
            result = execute_query(engine, sql, params={"s": schema}, max_rows=None)
        out: dict[str, dict] = {}
        if not result.get("success"):
            return out
        for r in result.get("rows", []):
            name = r.get("ROUTINE_NAME") or r.get("routine_name")
            if not name:
                continue
            rtype = str(r.get("ROUTINE_TYPE") or r.get("routine_type") or "").upper()
            defn = str(r.get("ROUTINE_DEFINITION") or r.get("definition") or "")
            kind = "function" if "FUNCTION" in rtype else "procedure"
            out[name] = {
                "columns": [],
                "column_meta": {},
                "fks": [],
                "type": kind,
                "comment": defn[:200],
            }
        return out
    except Exception:
        logger.warning("fetch routines failed for %s — returned empty dict", schema, exc_info=True)
        return {}


def _fetch_fks_bulk(engine: Engine, db_type: str, schema: str) -> list[dict]:
    """批量拉取 schema 内所有外键（一条 SQL）。"""
    try:
        if db_type == "sqlserver":
            sql = (
                "SELECT OBJECT_NAME(f.parent_object_id) AS TABLE_NAME, "
                "f.name AS CONSTRAINT_NAME, "
                "COL_NAME(fc.parent_object_id, fc.parent_column_id) AS COLUMN_NAME, "
                "OBJECT_NAME(fc.referenced_object_id) AS REFERENCED_TABLE, "
                "COL_NAME(fc.referenced_object_id, fc.referenced_column_id) AS REFERENCED_COLUMN "
                "FROM sys.foreign_keys f "
                "JOIN sys.foreign_key_columns fc ON f.object_id = fc.constraint_object_id "
                "WHERE SCHEMA_NAME(f.parent_object_id) = :s"
            )
        elif db_type == "mysql":
            sql = (
                "SELECT k.TABLE_NAME, k.CONSTRAINT_NAME, k.COLUMN_NAME, "
                "k.REFERENCED_TABLE_NAME AS REFERENCED_TABLE, "
                "k.REFERENCED_COLUMN_NAME AS REFERENCED_COLUMN "
                "FROM information_schema.KEY_COLUMN_USAGE k "
                "WHERE k.TABLE_SCHEMA = :s AND k.REFERENCED_TABLE_NAME IS NOT NULL"
            )
        else:  # postgresql
            sql = (
                "SELECT tc.table_name AS TABLE_NAME, tc.constraint_name AS CONSTRAINT_NAME, "
                "kcu.column_name AS COLUMN_NAME, "
                "ccu.table_name AS REFERENCED_TABLE, "
                "ccu.column_name AS REFERENCED_COLUMN "
                "FROM information_schema.table_constraints tc "
                "JOIN information_schema.key_column_usage kcu "
                "ON tc.constraint_name = kcu.constraint_name "
                "JOIN information_schema.constraint_column_usage ccu "
                "ON ccu.constraint_name = tc.constraint_name "
                "WHERE tc.table_schema = :s AND tc.constraint_type = 'FOREIGN KEY'"
            )
        result = execute_query(engine, sql, params={"s": schema}, max_rows=None)
        if result.get("success"):
            return result["rows"]
    except Exception:
        logger.warning("get_constraints(%s) failed — returned empty list", schema, exc_info=True)
    return []


def _semantic_index_sqlite(engine: Engine) -> dict:
    """SQLite 批量索引：用 pragma_table_info 表值函数一次拿全表列。"""
    from _security import quote_ident

    col_result = execute_query(
        engine,
        "SELECT m.name AS TABLE_NAME, p.name AS COLUMN_NAME, p.type AS DATA_TYPE "
        "FROM sqlite_master m JOIN pragma_table_info(m.name) p "
        "WHERE m.type = 'table' AND m.name NOT LIKE 'sqlite_%' "
        "ORDER BY m.name, p.cid",
    )
    tables: dict[str, dict] = {}
    if col_result.get("success"):
        for r in col_result["rows"]:
            tname = r["TABLE_NAME"]
            tables.setdefault(tname, {"columns": [], "column_meta": {}, "fks": []})
            tables[tname]["columns"].append(r["COLUMN_NAME"])
            tables[tname]["column_meta"][r["COLUMN_NAME"]] = {
                "type": r.get("DATA_TYPE", ""),
                "comment": "",
            }

    for tname in list(tables.keys()):
        try:
            fk_result = execute_query(engine, f"PRAGMA foreign_key_list({quote_ident(tname, 'sqlite')})")
            if fk_result.get("success"):
                for row in fk_result["rows"]:
                    tables[tname]["fks"].append(
                        {
                            "referred_table": row.get("table", ""),
                            "constrained_columns": [row.get("from", "")] if row.get("from") else [],
                            "referred_columns": [row.get("to", "")] if row.get("to") else [],
                        }
                    )
        except Exception:
            logger.debug("PRAGMA foreign_key_list(%s) failed, skipping", tname, exc_info=True)
            continue

    return {"tables": tables, "total": len(tables)}


def _build_semantic_index_inspector(engine: Engine, db_type: str, schema: str | None) -> dict:
    """批量 SQL 失败时的回退：用 SQLAlchemy inspector 逐表查询。"""
    inspector = inspect(engine)
    tables_list = inspector.get_table_names(schema=schema)
    result = {}
    for table in tables_list:
        try:
            cols = inspector.get_columns(table, schema=schema)
            col_names = [c["name"] for c in cols]
            try:
                fks = inspector.get_foreign_keys(table, schema=schema)
            except Exception:
                logger.debug("inspector.get_foreign_keys(%s) failed, using empty", table, exc_info=True)
                fks = []
            result[table] = {
                "columns": col_names,
                "column_meta": {c["name"]: {"type": str(c.get("type", "")), "comment": c.get("comment", "") or ""} for c in cols},
                "fks": [
                    {
                        "referred_table": fk.get("referred_table", ""),
                        "constrained_columns": fk.get("constrained_columns", []),
                        "referred_columns": fk.get("referred_columns", []),
                    }
                    for fk in fks
                ],
            }
        except Exception:
            logger.debug("inspector fallback for table %s failed, skipping", table, exc_info=True)
            continue
    return {"tables": result, "total": len(result)}


# ═══════════════════════════════════════════════════════════════
#  公共 API
# ═══════════════════════════════════════════════════════════════


def fetch_semantic_index(engine: Engine, schema: str | None = None, max_tables: int | None = None, mode: str = "full") -> dict:
    """获取语义搜索索引。

    支持两级：
    - **Level 1（mode="tables"）**：只取表名+表注释，单条轻量 SQL，首次约 10ms。
    - **Level 2（mode="full"）**：全量索引（表名+列名+列注释+外键+存储过程）。

    Args:
        engine: SQLAlchemy Engine
        schema: 可选 schema 过滤；为 None 时用 default_schema
        max_tables: 保留参数，默认 None=不截断
        mode: "tables"（表级快速索引）或 "full"（完整索引，默认）
    """
    if not HAS_SQLALCHEMY:
        return {"tables": {}, "total": 0, "level": mode}

    url = engine.url
    db_type = _engine_db_type(url)
    eff_schema = schema or default_schema(db_type)

    safe_url = f"{url.drivername}://{url.username or ''}@{url.host or ''}:{url.port or ''}/{url.database or ''}"
    cache_key = (safe_url, eff_schema)

    # 缓存读取（加锁）
    with _CACHE_LOCK:
        cached = _SEMANTIC_CACHE.get(cache_key)
    if cached is not None:
        ts, data = cached
        if time.monotonic() - ts < _SEMANTIC_CACHE_TTL:
            if mode == "full" or data.get("level") == "full":
                return _apply_max_tables(data, max_tables)
            if mode == "tables":
                tables_full = {k: v for k, v in data.get("tables", {}).items() if not v.get("_stub")}
                return _apply_max_tables({"tables": tables_full, "total": len(tables_full), "level": "full"}, max_tables)

    disk_cached = _load_semantic_disk_cache(cache_key)
    if disk_cached is not None:
        with _CACHE_LOCK:
            _SEMANTIC_CACHE[cache_key] = (time.monotonic(), disk_cached)
        data = disk_cached
        if mode == "full" or data.get("level") == "full":
            return _apply_max_tables(data, max_tables)

    if mode == "tables":
        result = _fetch_table_names(engine, db_type, eff_schema)
        result["level"] = "tables"
        with _CACHE_LOCK:
            _SEMANTIC_CACHE[cache_key] = (time.monotonic(), result)
        return _apply_max_tables(result, max_tables)

    # mode == "full"
    try:
        result = _build_semantic_index_bulk(engine, db_type, eff_schema)
    except Exception:
        logger.debug("bulk build failed, falling back to inspector", exc_info=True)
        result = _build_semantic_index_inspector(engine, db_type, eff_schema)

    result["level"] = "full"
    with _CACHE_LOCK:
        _SEMANTIC_CACHE[cache_key] = (time.monotonic(), result)
    _save_semantic_disk_cache(cache_key, result)
    return _apply_max_tables(result, max_tables)
