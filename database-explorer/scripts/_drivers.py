# -*- coding: utf-8 -*-
"""数据库驱动抽象层 - 统一接口

支持 SQL Server / MySQL / PostgreSQL / SQLite
- 统一连接和查询 API（基于 SQLAlchemy）
- 自动参数绑定和 SQL 方言适配
- 连接池管理
- 完整的结构探索功能

向后兼容：保留与原版 CLI 的接口一致。
"""

import sys
import time
import logging
from typing import Any
from urllib.parse import urlparse, unquote, quote

logger = logging.getLogger(__name__)

# SQLAlchemy 支持
try:
    from sqlalchemy import create_engine, text
    from sqlalchemy.engine import Engine
    from sqlalchemy import inspect

    HAS_SQLALCHEMY = True
except ImportError:
    HAS_SQLALCHEMY = False

# ═══════════════════════════════════════════════════════════════
#  驱动配置
# ═══════════════════════════════════════════════════════════════

DRIVERS: dict[str, dict[str, Any]] = {
    "sqlserver": {
        "package": "pymssql",
        "install": "pip install pymssql",
        "default_port": 1433,
        "default_user": "sa",
        "placeholder": "@p0",
    },
    "mysql": {
        "package": "pymysql",
        "install": "pip install pymysql",
        "default_port": 3306,
        "default_user": "root",
        "placeholder": "%s",
    },
    "postgresql": {
        "package": "psycopg2",
        "install": "pip install psycopg2-binary",
        "default_port": 5432,
        "default_user": "postgres",
        "placeholder": "%s",
    },
    "kingbase": {
        "package": "psycopg2",
        "install": "pip install psycopg2-binary",
        "default_port": 54321,
        "default_user": "system",
        "placeholder": "%s",
    },
    "sqlite": {
        "package": "sqlite3",
        "install": None,
        "default_port": None,
        "placeholder": "?",
    },
}
DRIVERS["mssql"] = DRIVERS["sqlserver"]

# SQLAlchemy 方言映射
DIALECTS = {
    "sqlserver": "mssql+pymssql",
    "mysql": "mysql+pymysql",
    "postgresql": "postgresql+psycopg2",
    "kingbase": "postgresql+psycopg2",
    "sqlite": "sqlite",
    "mssql": "mssql+pymssql",
}

# db_type 别名归一化表：所有等价写法映射到规范 key。
# 在信任边界（配置加载、CLI 参数解析）统一调用 normalize_db_type()，
# 让下游 == "sqlserver" 等判断只面对规范值。
_DB_TYPE_ALIASES = {
    "mssql": "sqlserver",
    "kingbasees": "kingbase",
}

def normalize_db_type(db_type: str) -> str:
    """将 db_type 别名（如 mssql）归一化为规范 key（如 sqlserver）。

    未注册的值原样返回（让 _check_driver 在下游报"不支持的类型"）。
    """
    return _DB_TYPE_ALIASES.get(db_type, db_type)


# ═══════════════════════════════════════════════════════════════
#  驱动检查
# ═══════════════════════════════════════════════════════════════


def _check_driver(db_type: str) -> None:
    """检查驱动是否已安装，未安装则提示并退出"""
    info = DRIVERS.get(db_type)
    if not info:
        print(f"ERROR: 不支持的数据库类型: {db_type}", file=sys.stderr)
        print(f"支持的类型: {', '.join(DRIVERS.keys())}", file=sys.stderr)
        sys.exit(1)

    pkg = info["package"]
    if db_type == "sqlite":
        return  # 内置

    try:
        __import__(pkg)
    except ImportError:
        print(f"ERROR: 驱动 '{pkg}' 未安装", file=sys.stderr)
        print(f"Install: {info['install']}", file=sys.stderr)
        sys.exit(1)


def check_driver(db_type: str) -> None:
    """检查驱动是否已安装（原版接口兼容）"""
    _check_driver(db_type)


# ═══════════════════════════════════════════════════════════════
#  连接 URL 构建
# ═══════════════════════════════════════════════════════════════


def _build_url(cfg: dict) -> str:
    """根据配置构建 SQLAlchemy 连接 URL"""
    db_type = cfg.get("db_type", "sqlserver")

    if db_type == "sqlite":
        database = cfg.get("database", ":memory:")
        if database == ":memory:":
            return "sqlite:///:memory:"
        return f"sqlite:///{database}"

    server = cfg.get("server", "localhost")
    port = cfg.get("port", DRIVERS.get(db_type, {}).get("default_port", 1433))
    database = cfg.get("database", "")
    user = cfg.get("user", "")
    password = cfg.get("password", "")
    dialect = DIALECTS[db_type]

    return f"{dialect}://{quote(user, safe='')}:{quote(password, safe='')}@{server}:{port}/{database}"


# ═══════════════════════════════════════════════════════════════
#  连接函数
# ═══════════════════════════════════════════════════════════════


def connect(cfg: dict) -> Engine:
    """建立数据库连接

    Args:
        cfg: 连接配置，必须包含 db_type 字段

    Returns:
        SQLAlchemy Engine 对象
    """
    db_type = cfg.get("db_type", "sqlserver")
    _check_driver(db_type)
    url = _build_url(cfg)

    # SQLAlchemy create_engine 的关键字约定：
    #   connect_args=<dict>  → 透传给底层 DBAPI（pymysql/sqlite3 等）
    # 其他名字（如 charset）作为顶层 kwarg 会被 create_engine 拒绝并抛
    # TypeError: Invalid argument(s) 'charset' sent to create_engine()。
    # 因此所有 DBAPI 级参数（charset/check_same_thread/timeout/...）必须
    # 收纳到嵌套的 connect_args["connect_args"] 子字典里。
    connect_args: dict[str, Any] = {}
    dbapi_args: dict[str, Any] = connect_args.setdefault("connect_args", {})
    if db_type == "mysql":
        dbapi_args["charset"] = cfg.get("charset", "utf8mb4")
    elif db_type == "sqlite":
        dbapi_args["check_same_thread"] = False

    # 查询超时
    timeout = cfg.get("timeout")
    if timeout:
        if db_type == "sqlite":
            dbapi_args["timeout"] = timeout
        elif db_type == "sqlserver":
            dbapi_args["timeout"] = timeout
            dbapi_args["login_timeout"] = timeout
        else:
            dbapi_args["connect_timeout"] = timeout

    engine = create_engine(
        url,
        echo=cfg.get("echo", False),
        pool_pre_ping=False,
        pool_size=5,
        pool_recycle=3600,
        **connect_args,
    )

    if db_type == "kingbase":
        # KingbaseES 版本字符串格式不兼容 SQLAlchemy PostgreSQL 方言解析
        # 修补方言的版本解析方法
        orig_get_version = engine.dialect._get_server_version_info

        def _patched_get_version(conn):
            try:
                return orig_get_version(conn)
            except Exception:
                return (9, 0, 0)

        engine.dialect._get_server_version_info = _patched_get_version

        # KingbaseES 部分版本不支持 BEGIN 事务初始化
        # 在 SQLAlchemy dialect 的 on_connect 之前设置 autocommit
        from sqlalchemy import event
        @event.listens_for(engine, "connect", insert=True)
        def _set_autocommit(dbapi_conn, _connection_record):
            dbapi_conn.autocommit = True

    # 测试连接
    with engine.connect():
        pass

    return engine


def _find_placeholder_positions(sql: str, placeholder: str) -> list[int]:
    """Find positions of *placeholder* that are outside single-quoted string literals.

    Handles doubled-quote escapes ('' inside '...').  Returns a list of start
    indices sorted in **descending** order so callers can splice replacements
    from back to front without invalidating earlier indices.
    """
    positions: list[int] = []
    in_string = False
    i = 0
    n = len(sql)
    while i < n:
        ch = sql[i]
        if in_string:
            if ch == "'" and i + 1 < n and sql[i + 1] == "'":
                i += 2  # skip escaped quote ''
                continue
            if ch == "'":
                in_string = False
        else:
            if ch == "'":
                in_string = True
            elif sql[i : i + len(placeholder)] == placeholder:
                positions.append(i)
        i += 1
    positions.reverse()
    return positions


def _bind_params(sql: str, params):
    """Convert positional params to named params, rewriting SQL placeholders.

    SQLAlchemy 2.x text().execute() treats tuple params as a list of
    execution dicts, failing for plain ? / %s positional styles.
    This rewrites ? → :_p0 and %s → :_p0 for all positional params,
    **skipping placeholders inside single-quoted string literals**.
    """
    if params is None:
        return sql, {}
    if isinstance(params, dict):
        return sql, params
    if isinstance(params, (list, tuple)):
        new_sql = sql
        named = {}
        for i, v in enumerate(params):
            key = f"_p{i}"
            named[key] = v
            if "?" in new_sql:
                positions = _find_placeholder_positions(new_sql, "?")
                if positions:
                    pos = positions[-1]
                    new_sql = new_sql[:pos] + f":{key}" + new_sql[pos + 1 :]
            elif "%s" in new_sql:
                positions = _find_placeholder_positions(new_sql, "%s")
                if positions:
                    pos = positions[-1]
                    new_sql = new_sql[:pos] + f":{key}" + new_sql[pos + 2 :]
        return new_sql, named
    return sql, {}


def execute_query(
    engine: Engine,
    sql: str,
    params: dict | tuple | None = None,
    max_rows: int | None = 1000,
    query_timeout: int | None = None,
) -> dict:
    """执行查询并返回结构化结果

    Args:
        engine: SQLAlchemy Engine
        sql: SQL 查询语句
        params: 参数（字典或元组）
        max_rows: 最大返回行数；None 表示不限制（用于批量元数据拉取，
            如 fetch_semantic_index 一次拿全表列，避免硬编码大数字上限
            在超大库上仍被截断）
        query_timeout: 单次查询执行超时秒数；None 使用连接默认值。
            超时后抛出 StatementTimeout 被捕获返回错误。

    Returns:
        {
            "success": bool,
            "columns": [...],
            "rows": [...],
            "total_rows": int,
            "displayed": int,
            "truncated": bool,
            "affected": int,
            "error": str | None
        }
    """
    start_time = time.perf_counter()
    try:
        with engine.connect() as conn:
            _timeout_set = query_timeout is not None and engine.dialect.name in ("postgresql", "mysql", "mssql")
            if _timeout_set:
                if engine.dialect.name == "postgresql":
                    conn.execute(text(f"SET statement_timeout = '{int(query_timeout * 1000)}ms'"))
                elif engine.dialect.name == "mysql":
                    conn.execute(text(f"SET SESSION max_execution_time = {int(query_timeout * 1000)}"))
                elif engine.dialect.name == "mssql":
                    conn.execute(text(f"SET LOCK_TIMEOUT {int(query_timeout * 1000)}"))
            try:
                bound_sql, bound_params = _bind_params(sql, params)
                result = conn.execute(text(bound_sql), bound_params)

                # 非查询语句
                if result.returns_rows is False:
                    conn.commit()
                    duration = time.perf_counter() - start_time
                    return {"success": True, "columns": [], "rows": [], "total_rows": 0, "affected": result.rowcount, "duration": duration}

                # 获取列名
                columns = list(result.keys())
                rows = []
                truncated = False

                for i, row in enumerate(result):
                    if max_rows is not None and i >= max_rows:
                        truncated = True
                        break
                    rows.append(dict(zip(columns, row)))

                duration = time.perf_counter() - start_time
                return {
                    "success": True,
                    "columns": columns,
                    "rows": rows,
                    "total_rows": None if truncated else len(rows),
                    "displayed": len(rows),
                    "truncated": truncated,
                    "duration": duration,
                }
            finally:
                # 归还连接前重置 session 级 timeout，防止连接池复用时泄漏到后续查询
                if _timeout_set:
                    if engine.dialect.name == "postgresql":
                        conn.execute(text("RESET statement_timeout"))
                    elif engine.dialect.name == "mysql":
                        conn.execute(text("SET SESSION max_execution_time = 0"))
                    elif engine.dialect.name == "mssql":
                        conn.execute(text("SET LOCK_TIMEOUT -1"))
    except Exception as e:
        logger.debug("execute_query failed: %s", e, exc_info=True)
        from _security import sanitize_error

        return {"success": False, "error": sanitize_error(e)}


# ═══════════════════════════════════════════════════════════════
# 结构探索函数
# ═══════════════════════════════════════════════════════════════


def get_tables(engine: Engine, schema: str | None = None) -> list[str]:
    """获取数据库中的表列表

    Args:
        engine: SQLAlchemy Engine
        schema: 可选的 schema 名称

    Returns:
        表名列表
    """
    if not HAS_SQLALCHEMY:
        return []

    try:
        inspector = inspect(engine)
        return inspector.get_table_names(schema=schema)
    except Exception:
        logger.debug("get_table_names(schema=%s) failed, falling back to no-schema", schema, exc_info=True)
        try:
            inspector = inspect(engine)
            return inspector.get_table_names()
        except Exception:
            return []


def get_columns(engine: Engine, table: str, schema: str | None = None) -> list[dict]:
    """获取表的列信息

    Args:
        engine: SQLAlchemy Engine
        table: 表名
        schema: 可选的 schema 名称

    Returns:
        SQLAlchemy inspector.get_columns 的原始结果（dict 列表，每项含
        name/type/nullable/default/primary_key 等键）。schema 查询失败时
        回退到无 schema 查询；两次都失败返回 []。
    """
    if not HAS_SQLALCHEMY:
        return []

    try:
        inspector = inspect(engine)
        columns = inspector.get_columns(table, schema=schema)
    except Exception:
        logger.debug("get_columns(%s, schema=%s) failed, falling back to no-schema", table, schema, exc_info=True)
        try:
            inspector = inspect(engine)
            columns = inspector.get_columns(table)
        except Exception:
            return []
    return columns


def get_indexes(engine: Engine, table: str, schema: str | None = None) -> list[dict]:
    """获取表的索引信息"""
    if not HAS_SQLALCHEMY:
        return []

    inspector = inspect(engine)
    try:
        return inspector.get_indexes(table, schema=schema)
    except Exception:
        logger.debug("get_indexes(%s, schema=%s) failed, falling back", table, schema, exc_info=True)
        return inspector.get_indexes(table)


def get_foreign_keys(engine: Engine, table: str, schema: str | None = None) -> list[dict]:
    """获取表的外键信息"""
    if not HAS_SQLALCHEMY:
        return []

    inspector = inspect(engine)
    try:
        return inspector.get_foreign_keys(table, schema=schema)
    except Exception:
        logger.debug("get_foreign_keys(%s, schema=%s) failed, falling back", table, schema, exc_info=True)
        return inspector.get_foreign_keys(table)


def get_pk_constraint(engine: Engine, table: str, schema: str | None = None) -> dict | None:
    """获取表的主键约束"""
    if not HAS_SQLALCHEMY:
        return None

    inspector = inspect(engine)
    try:
        return inspector.get_pk_constraint(table, schema=schema)
    except Exception:
        logger.debug("get_pk_constraint(%s, schema=%s) failed, falling back", table, schema, exc_info=True)
        return inspector.get_pk_constraint(table)


def default_schema(db_type: str) -> str | None:
    """返回各数据库类型的默认 schema 名。

    - SQL Server / PostgreSQL：有 schema 概念，默认 dbo / public
    - MySQL：schema 等价于 database，由连接决定，返回 None（不拼到查询里）
    - SQLite：无 schema 概念，返回 None

    统一此函数以替换散落各处的 ``("dbo" if db_type == "sqlserver" else None)``
    硬编码。
    """
    if db_type == "sqlserver":
        return "dbo"
    if db_type in ("postgresql", "kingbase"):
        return "dbo" if db_type == "kingbase" else "public"

def list_schemas(engine: Engine, db_type: str) -> list[str]:
    """列出数据库中所有用户 schema。

    - SQL Server：``INFORMATION_SCHEMA.SCHEMATA``
    - PostgreSQL：排除 ``pg_*`` 系统 schema
    - MySQL：schema 等价于 database，返回当前连接的 database（单元素列表）
    - SQLite：固定 ``["main"]``

    用于 ``schemas`` 命令，以及在默认 schema 查询为空时提示用户选择。
    """
    if db_type == "sqlite":
        return ["main"]
    if db_type == "mysql":
        # MySQL 的 schema = database；列出所有可访问的 database
        result = execute_query(engine, "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA ORDER BY SCHEMA_NAME", max_rows=None)
        if result.get("success") and result.get("rows"):
            return [r["SCHEMA_NAME"] for r in result["rows"]]
        return []

    try:
        if db_type == "sqlserver":
            sql = "SELECT SCHEMA_NAME AS s FROM INFORMATION_SCHEMA.SCHEMATA ORDER BY SCHEMA_NAME"
        else:  # postgresql
            sql = (
                "SELECT schema_name AS s FROM information_schema.schemata "
                "WHERE schema_name NOT LIKE 'pg_%' AND schema_name <> 'information_schema' "
                "ORDER BY schema_name"
            )
        result = execute_query(engine, sql, max_rows=None)
        if result.get("success") and result.get("rows"):
            return [r["s"] for r in result["rows"]]
    except Exception:
        logger.warning("list_schemas(%s) failed — returned empty list", db_type, exc_info=True)
    return []


# ═══════════════════════════════════════════════════════════════
#  连接字符串解析
# ═══════════════════════════════════════════════════════════════


def parse_connection_uri(uri: str) -> dict:
    """解析数据库连接 URI

    支持格式:
    - mysql://user:pass@host:3306/dbname
    - postgresql://user:pass@host:5432/dbname
    - sqlite:///path/to/file.db    (Unix 绝对路径)
    - sqlite:///C:/path/to/file.db (Windows 绝对路径，保留 C: 前缀)
    - sqlite:///:memory:           (内存库)
    - mssql://user:pass@host:1433/dbname
    - Server=...;Database=...;User Id=...;Password=... (SQL Server 连接字符串)
    """
    if uri.startswith("sqlite:///"):
        path = uri[10:]  # 跳过 "sqlite:///"
        # Windows 路径以盘符开头，去掉前导 /
        if len(path) >= 2 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        return {"db_type": "sqlite", "database": path}
    if uri.startswith("sqlite://"):
        rest = uri[9:]
        return {"db_type": "sqlite", "database": rest or ":memory:"}
    if uri.startswith("mysql://"):
        return _parse_db_uri(uri, "mysql", "mysql")
    if uri.startswith(("postgresql://", "postgres://")):
        return _parse_db_uri(uri, "postgresql", "postgres")
    if uri.startswith(("kingbase://", "kingbasees://")):
        return _parse_db_uri(uri, "kingbase", "test")
    if uri.startswith("mssql://"):
        return _parse_db_uri(uri, "sqlserver", "master")
    if ";" in uri and "=" in uri:
        return _parse_sqlserver_connstr(uri)
    return {}


def _parse_db_uri(uri: str, db_type: str, default_db: str) -> dict:
    """通用 scheme://user:pass@host:port/db 解析。"""
    info = DRIVERS[db_type]
    p = urlparse(uri)
    return {
        "db_type": db_type,
        "server": p.hostname or "localhost",
        "port": p.port or info["default_port"],
        "database": p.path.lstrip("/") or default_db,
        "user": unquote(p.username or info["default_user"]),
        "password": unquote(p.password or ""),
    }


def _parse_sqlserver_connstr(conn_str: str) -> dict:
    """解析 SQL Server 连接字符串"""
    result: dict[str, Any] = {"db_type": "sqlserver"}
    for part in conn_str.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, _, value = part.partition("=")
        key = key.strip().lower()
        value = value.strip()
        if key in ("server", "data source", "address", "addr"):
            result["server"] = value
        elif key in ("database", "initial catalog"):
            result["database"] = value
        elif key in ("user id", "user", "uid"):
            result["user"] = value
        elif key in ("password", "pwd"):
            result["password"] = value
        elif key in ("connection timeout", "connect timeout", "timeout"):
            try:
                result["connection_timeout"] = int(value)
            except ValueError:
                pass
    return result
