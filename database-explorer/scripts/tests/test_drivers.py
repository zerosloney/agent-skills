#!/usr/bin/env python3
"""_drivers.py 回归测试

覆盖：
- default_schema（P0-3：替换 15 处硬编码的统一 helper）
- _engine_db_type（从 URL 推断数据库类型）
- fetch_semantic_index 的缓存与覆盖行为（P0-1：批量 SQL + memoize）
- list_schemas（P0-3：SQLite 路径无驱动依赖，可直接测）

list_schemas/fetch_semantic_index 用 SQLite 内存库做真实集成测试，
无需外部数据库驱动，可在任何环境运行。
"""

import pytest
from sqlalchemy import create_engine, text

from _drivers import (
    default_schema,
    list_schemas,
    connect,
)
from _semantic_index import (
    _engine_db_type,
    fetch_semantic_index,
    _SEMANTIC_CACHE,
)


# ─────────────────────────────────────────────────────────────────
# default_schema（P0-3）
# ─────────────────────────────────────────────────────────────────


class TestDefaultSchema:
    def test_sqlserver(self):
        assert default_schema("sqlserver") == "dbo"

    def test_postgresql(self):
        assert default_schema("postgresql") == "public"

    def test_mysql_none(self):
        # MySQL schema=database，不拼到查询里
        assert default_schema("mysql") is None

    def test_sqlite_none(self):
        assert default_schema("sqlite") is None

    def test_unknown_returns_none(self):
        assert default_schema("oracle") is None


# ─────────────────────────────────────────────────────────────────
# _engine_db_type
# ─────────────────────────────────────────────────────────────────


class TestEngineDbType:
    def test_sqlite(self):
        eng = create_engine("sqlite://")
        assert _engine_db_type(eng.url) == "sqlite"

    def test_unknown_backend_defaults_sqlserver(self):
        # 用一个不存在的 backend 名测试映射兜底
        class FakeUrl:
            def get_backend_name(self):
                return "oracle"

        assert _engine_db_type(FakeUrl()) == "sqlserver"


# ─────────────────────────────────────────────────────────────────
# SQLite 集成测试夹具：建一个有表+外键的内存库
# ─────────────────────────────────────────────────────────────────


@pytest.fixture
def sqlite_engine():
    """建一个含 3 表 + 1 外键的 SQLite 内存库。"""
    eng = create_engine("sqlite://")
    with eng.connect() as conn:
        conn.execute(text("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)"))
        conn.execute(text("CREATE TABLE orders (id INTEGER PRIMARY KEY, user_id INTEGER, amount REAL)"))
        conn.execute(text("CREATE TABLE products (id INTEGER PRIMARY KEY, sku TEXT, price REAL)"))
        conn.execute(text("INSERT INTO users VALUES (1, 'alice', 'a@x.com')"))
        conn.execute(text("INSERT INTO orders VALUES (1, 1, 99.9)"))
        conn.commit()
    yield eng
    eng.dispose()


# ─────────────────────────────────────────────────────────────────
# list_schemas（P0-3）
# ─────────────────────────────────────────────────────────────────


class TestListSchemas:
    def test_sqlite_returns_main(self, sqlite_engine):
        assert list_schemas(sqlite_engine, "sqlite") == ["main"]

    def test_mysql_stub(self, monkeypatch):
        # MySQL 路径走 information_schema.SCHEMATA，用 monkeypatch 模拟
        import _drivers

        fake_result = {
            "success": True,
            "rows": [{"SCHEMA_NAME": "db1"}, {"SCHEMA_NAME": "db2"}],
        }
        monkeypatch.setattr(_drivers, "execute_query", lambda *a, **k: fake_result)
        assert list_schemas(sqlite_engine, "mysql") == ["db1", "db2"]


# ─────────────────────────────────────────────────────────────────
# fetch_semantic_index（P0-1：批量 SQL + 缓存）
# ─────────────────────────────────────────────────────────────────


class TestFetchSemanticIndex:
    def test_covers_all_tables(self, sqlite_engine):
        """P0-1 核心：不截断，覆盖全部表（非旧的 max_tables=500）。"""
        _SEMANTIC_CACHE.clear()
        idx = fetch_semantic_index(sqlite_engine)
        tables = idx.get("tables", {})
        assert idx["total"] == 3
        assert set(tables.keys()) == {"users", "orders", "products"}

    def test_columns_populated(self, sqlite_engine):
        _SEMANTIC_CACHE.clear()
        idx = fetch_semantic_index(sqlite_engine)
        assert idx["tables"]["users"]["columns"] == ["id", "name", "email"]
        assert idx["tables"]["orders"]["columns"] == ["id", "user_id", "amount"]

    def test_no_truncation_by_default(self, sqlite_engine):
        """默认不传 max_tables → 不截断（旧版默认 500 会截断，已废弃）。"""
        _SEMANTIC_CACHE.clear()
        idx = fetch_semantic_index(sqlite_engine)
        assert "truncated" not in idx  # 未截断时无此字段

    def test_explicit_max_tables_truncates(self, sqlite_engine):
        """显式传 max_tables 仍可截断（兼容旧签名）。"""
        _SEMANTIC_CACHE.clear()
        idx = fetch_semantic_index(sqlite_engine, max_tables=2)
        assert idx["total"] == 2
        assert idx.get("truncated") is True
        assert idx.get("full_count") == 3

    def test_cache_hit_on_second_call(self, sqlite_engine):
        """同一 engine 二次调用命中进程内缓存。"""
        _SEMANTIC_CACHE.clear()
        fetch_semantic_index(sqlite_engine)  # 填充缓存
        cache_key = next(iter(_SEMANTIC_CACHE.keys()))
        _ts, cached_data = _SEMANTIC_CACHE[cache_key]  # 缓存格式为 (timestamp, data)
        second = fetch_semantic_index(sqlite_engine)
        assert second is cached_data  # 同一对象引用 = 命中缓存


# ─────────────────────────────────────────────────────────────────
# execute_query max_rows=None 支持（动态上限修复）
# ─────────────────────────────────────────────────────────────────


class TestExecuteQueryMaxRows:
    """max_rows=None 表示不限制（用于批量元数据拉取，避免硬编码大数字
    在超大库上仍被截断）。"""

    def test_none_returns_all_rows(self, sqlite_engine):
        from _drivers import execute_query

        # 插入额外 5 行（fixture 已有 1 行 alice）
        with sqlite_engine.connect() as conn:
            from sqlalchemy import text

            for i in range(2, 7):
                conn.execute(text(f"INSERT INTO users (id, name) VALUES ({i}, 'u{i}')"))
            conn.commit()
        # max_rows=None 应返回全部 6 行
        result = execute_query(sqlite_engine, "SELECT * FROM users", max_rows=None)
        assert result["success"]
        assert len(result["rows"]) == 6
        assert result.get("truncated") is False

    def test_explicit_limit_truncates(self, sqlite_engine):
        from _drivers import execute_query

        # 插入足够数据（fixture 已有 1 行，再加 4 行 = 5 行）
        with sqlite_engine.connect() as conn:
            from sqlalchemy import text

            for i in range(2, 6):
                conn.execute(text(f"INSERT INTO users (id, name) VALUES ({i}, 'u{i}')"))
            conn.commit()
        # max_rows=2 但有 5 行 → 应截断
        result = execute_query(sqlite_engine, "SELECT * FROM users", max_rows=2)
        assert result["success"]
        assert len(result["rows"]) == 2
        assert result.get("truncated") is True


# ─────────────────────────────────────────────────────────────────
# execute_query 的 session timeout RESET（防止连接池复用泄漏）
#
# query_timeout 设置的 SET statement_timeout 是 session 级，连接归还连接池
# 后残留会导致后续查询继承超时。修复在 finally 中 RESET。
# ─────────────────────────────────────────────────────────────────


class TestExecuteQueryTimeoutReset:
    """execute_query 设置 timeout 后，归还连接前必须 RESET，防止连接池泄漏。"""

    def test_postgresql_timeout_is_reset_after_query(self):
        """带 query_timeout 的 PostgreSQL 查询：执行序列含 SET 和 RESET。"""
        from unittest.mock import MagicMock
        from _drivers import execute_query

        engine = MagicMock()
        engine.dialect.name = "postgresql"
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        # 模拟返回行
        mock_result = MagicMock()
        mock_result.returns_rows = True
        mock_result.keys.return_value = ["id"]
        mock_result.__iter__ = MagicMock(return_value=iter([(1,)]))
        mock_conn.execute.side_effect = [MagicMock(), mock_result, MagicMock()]  # SET / query / RESET
        engine.connect.return_value = mock_conn

        execute_query(engine, "SELECT 1", query_timeout=30)

        executed_sql = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
        assert any("SET statement_timeout" in s for s in executed_sql), f"缺少 SET: {executed_sql}"
        assert any("RESET statement_timeout" in s for s in executed_sql), f"缺少 RESET: {executed_sql}"

    def test_no_timeout_no_reset(self):
        """未设 timeout 时不执行任何 SET/RESET。"""
        from unittest.mock import MagicMock
        from _drivers import execute_query

        engine = MagicMock()
        engine.dialect.name = "postgresql"
        mock_conn = MagicMock()
        mock_conn.__enter__ = MagicMock(return_value=mock_conn)
        mock_conn.__exit__ = MagicMock(return_value=False)
        mock_result = MagicMock()
        mock_result.returns_rows = True
        mock_result.keys.return_value = ["id"]
        mock_result.__iter__ = MagicMock(return_value=iter([(1,)]))
        mock_conn.execute.side_effect = [mock_result]  # 只有 query，无 SET/RESET
        engine.connect.return_value = mock_conn

        execute_query(engine, "SELECT 1", query_timeout=None)

        executed_sql = [str(c.args[0]) for c in mock_conn.execute.call_args_list]
        assert len(executed_sql) == 1, f"无 timeout 时应只有 1 次执行（query）: {executed_sql}"
        assert not any("statement_timeout" in s for s in executed_sql)


# ─────────────────────────────────────────────────────────────────
# connect() 经 SQLite 真实路径（connect_args 嵌套格式的回归保护）
#
# connect() 把本地 connect_args dict 通过 **展开 传给 create_engine，
# 其中嵌套的 "connect_args" 键恰好成为 SQLAlchemy 的 connect_args 形参。
# 该路径此前零集成测试覆盖；以下用 SQLite 内存/文件库验证连接参数实际生效。
# ─────────────────────────────────────────────────────────────────


class TestConnectSqlite:
    """connect() 对 SQLite 的支持：memory 库、check_same_thread、timeout 参数。"""

    def test_memory_database_connects(self):
        """SQLite :memory: 经 connect() 能连接并查询（check_same_thread 生效）。"""
        engine = connect({"db_type": "sqlite", "database": ":memory:"})
        try:
            with engine.connect() as conn:
                assert conn.execute(text("SELECT 1")).scalar() == 1
        finally:
            engine.dispose()

    def test_memory_database_with_timeout(self):
        """SQLite :memory: + timeout 经 connect() 不报错且参数到达 DBAPI。

        check_same_thread + timeout 同时设置，验证 connect_args 嵌套格式
        能把两个参数都传给 sqlite3.connect。
        """
        engine = connect({"db_type": "sqlite", "database": ":memory:", "timeout": 30})
        try:
            with engine.connect() as conn:
                assert conn.execute(text("SELECT 1")).scalar() == 1
        finally:
            engine.dispose()

    def test_file_database_with_timeout(self, tmp_path):
        """SQLite 文件库 + timeout 经 connect() 能连接（非 memory 分支）。"""
        db_file = str(tmp_path / "test.db")
        engine = connect({"db_type": "sqlite", "database": db_file, "timeout": 30})
        try:
            with engine.connect() as conn:
                assert conn.execute(text("SELECT 1")).scalar() == 1
        finally:
            engine.dispose()


# ─────────────────────────────────────────────────────────────────
# connect() 嵌套 connect_args 格式（P1：MySQL charset 顶层 kwarg bug 回归保护）
#
# 历史 bug：MySQL 分支把 charset 放到顶层 connect_args["charset"]，经 **connect_args
# 展开后变成 create_engine(..., charset="utf8mb4")，SQLAlchemy 2.x 直接抛
# TypeError: Invalid argument(s) 'charset' sent to create_engine()。所有 DBAPI 级
# 参数（charset/timeout/check_same_thread/...）必须收纳到 connect_args["connect_args"]
# 子字典里。以下用 mock 捕获 create_engine 调用 kwargs 做断言，不依赖真实 DB 驱动。
# ─────────────────────────────────────────────────────────────────

from unittest.mock import MagicMock, patch  # noqa: E402 测试专用、与其他 import 风格一致


class TestConnectArgsNesting:
    """所有 DBAPI 级参数（charset/timeout/...）必须收纳到嵌套 connect_args，
    不能作为顶层 kwarg 传给 create_engine（否则 SQLAlchemy 2.x 抛 TypeError）。"""

    @staticmethod
    def _capture_create_engine_kwargs(cfg: dict) -> dict:
        """跳过 _check_driver + mock create_engine，返回捕获到的 kwargs。"""
        captured: dict = {}

        def fake_create(url, *args, **kwargs):
            captured.update(kwargs)
            m = MagicMock()
            # engine.connect() 上下文管理器需返回自身以支持 with engine.connect():
            m.connect.return_value.__enter__.return_value = None
            m.connect.return_value.__exit__.return_value = False
            return m

        with patch("_drivers._check_driver", lambda x: None), patch("_drivers.create_engine", side_effect=fake_create):
            connect(cfg)
        return captured

    def test_mysql_charset_nested_in_connect_args(self):
        """MySQL charset 必须出现在 connect_args 子字典里，而不是顶层 kwarg。"""
        cfg = {"db_type": "mysql", "server": "localhost", "database": "test", "user": "root", "password": "x"}
        kwargs = self._capture_create_engine_kwargs(cfg)
        # 顶层不应有 charset（否则 create_engine 抛 TypeError）
        assert "charset" not in kwargs, f"charset 误作为顶层 kwarg 传给 create_engine: {kwargs}"
        # charset 应该在嵌套 connect_args 字典里
        nested = kwargs.get("connect_args", {})
        assert nested.get("charset") == "utf8mb4"

    def test_mysql_custom_charset_nested(self):
        """用户指定 --charset 时也能透传到 DBAPI connect_args。"""
        cfg = {"db_type": "mysql", "server": "localhost", "database": "test", "user": "root", "password": "x", "charset": "latin1"}
        kwargs = self._capture_create_engine_kwargs(cfg)
        assert "charset" not in kwargs  # 顶层不应出现
        assert kwargs.get("connect_args", {}).get("charset") == "latin1"

    def test_mysql_timeout_goes_into_connect_args(self):
        """MySQL timeout（connect_timeout）也必须收纳到嵌套 connect_args。"""
        cfg = {"db_type": "mysql", "server": "localhost", "database": "test", "user": "root", "password": "x", "timeout": 30}
        kwargs = self._capture_create_engine_kwargs(cfg)
        assert "charset" not in kwargs
        nested = kwargs.get("connect_args", {})
        assert nested.get("connect_timeout") == 30
        assert nested.get("charset") == "utf8mb4"

    def test_sqlserver_timeout_nested(self):
        """SQL Server timeout/login_timeout 必须收纳到嵌套 connect_args。"""
        cfg = {"db_type": "sqlserver", "server": "localhost", "database": "test", "user": "sa", "password": "x", "timeout": 30}
        kwargs = self._capture_create_engine_kwargs(cfg)
        nested = kwargs.get("connect_args", {})
        assert nested.get("timeout") == 30
        assert nested.get("login_timeout") == 30

    def test_postgresql_timeout_nested(self):
        """PostgreSQL connect_timeout 必须收纳到嵌套 connect_args。"""
        cfg = {"db_type": "postgresql", "server": "localhost", "database": "test", "user": "pg", "password": "x", "timeout": 30}
        kwargs = self._capture_create_engine_kwargs(cfg)
        assert kwargs.get("connect_args", {}).get("connect_timeout") == 30


# ─────────────────────────────────────────────────────────────────
# _bind_params / _find_placeholder_positions（P0: 字面量占位符破坏）
# ─────────────────────────────────────────────────────────────────

from _drivers import _bind_params, _find_placeholder_positions


class TestFindPlaceholderPositions:
    def test_simple_question_marks(self):
        sql = "SELECT * FROM t WHERE a = ? AND b = ?"
        positions = _find_placeholder_positions(sql, "?")
        assert len(positions) == 2

    def test_skips_question_mark_in_string_literal(self):
        sql = "SELECT * FROM t WHERE a LIKE '%?%' AND b = ?"
        positions = _find_placeholder_positions(sql, "?")
        assert len(positions) == 1
        # The only real ? is at the end
        assert sql[positions[0]] == "?"

    def test_handles_doubled_quote_escape(self):
        sql = "SELECT * FROM t WHERE a = 'it''s ?' AND b = ?"
        positions = _find_placeholder_positions(sql, "?")
        assert len(positions) == 1

    def test_percent_s_in_string_literal(self):
        sql = "SELECT * FROM t WHERE a LIKE '100%s' AND b = %s"
        positions = _find_placeholder_positions(sql, "%s")
        assert len(positions) == 1

    def test_no_placeholders(self):
        sql = "SELECT * FROM t WHERE a = 'hello'"
        assert _find_placeholder_positions(sql, "?") == []

    def test_empty_sql(self):
        assert _find_placeholder_positions("", "?") == []


class TestBindParams:
    def test_basic_question_marks(self):
        sql, named = _bind_params("SELECT * FROM t WHERE a = ? AND b = ?", (1, 2))
        assert named == {"_p0": 1, "_p1": 2}
        assert ":_p0" in sql
        assert ":_p1" in sql

    def test_preserves_question_mark_in_string_literal(self):
        sql, named = _bind_params(
            "SELECT * FROM t WHERE a LIKE '%?%' AND b = ?",
            ("test",),
        )
        assert "%?%" in sql, "String literal content must not be modified"
        assert ":_p0" in sql
        assert named == {"_p0": "test"}

    def test_preserves_percent_s_in_string_literal(self):
        sql, named = _bind_params(
            "SELECT * FROM t WHERE a LIKE '100%s' AND b = %s",
            ("val",),
        )
        assert "100%s" in sql, "String literal content must not be modified"
        assert ":_p0" in sql

    def test_none_params(self):
        sql, named = _bind_params("SELECT 1", None)
        assert sql == "SELECT 1"
        assert named == {}

    def test_dict_params_passthrough(self):
        sql, named = _bind_params("SELECT :x", {"x": 42})
        assert sql == "SELECT :x"
        assert named == {"x": 42}

    def test_multiple_placeholders_with_literals(self):
        sql, named = _bind_params(
            "SELECT * FROM t WHERE a = ? AND b = '?' AND c = ? AND d = '?'",
            (1, 2),
        )
        assert named == {"_p0": 1, "_p1": 2}
        # Only the two unquoted ? should be replaced
        assert sql.count(":_p") == 2
        assert "'?'" in sql  # quoted ones preserved


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
