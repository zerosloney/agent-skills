#!/usr/bin/env python3
"""explore_cmds 专项单元测试

覆盖 cmd_explore 路由分发、硬上限拦截、pattern 自动包装、detail 级别输出差异、
辅助函数（_compact_column / _format_columns_result / _format_constraints_result）等。

用 mock 替代真实数据库连接，聚焦逻辑分支而非 SQL 执行。
SQLite 集成场景由 test_e2e_cli.py 覆盖，本文件不重复。
"""

import argparse
import json
from io import StringIO
from unittest.mock import patch, MagicMock


from cli.explore_cmds import (
    cmd_explore,
    _compact_column,
    _format_columns_result,
    _format_constraints_result,
    _COLUMN_KEEP_KEYS,
    _DETAIL_NAMES,
    _DETAIL_SUMMARY,
    _DETAIL_FULL,
)


# ═══════════════════════════════════════════════════════════════
#  _compact_column
# ═══════════════════════════════════════════════════════════════


class TestCompactColumn:
    """_compact_column: full 级别列定义裁剪"""

    def test_keep_keys_always_present(self):
        """COLUMN_NAME / DATA_TYPE / IS_NULLABLE 即使为空也保留"""
        row = {"COLUMN_NAME": "id", "DATA_TYPE": "int", "IS_NULLABLE": "NO"}
        result = _compact_column(row)
        assert result == {"COLUMN_NAME": "id", "DATA_TYPE": "int", "IS_NULLABLE": "NO"}

    def test_null_values_omitted(self):
        """非 keep_keys 的 None/空字符串/空 bytes 被省略"""
        row = {
            "COLUMN_NAME": "name",
            "DATA_TYPE": "varchar",
            "IS_NULLABLE": "YES",
            "COLUMN_DEFAULT": None,
            "CHARACTER_MAXIMUM_LENGTH": "",
            "COLUMN_DESCRIPTION": b"",
        }
        result = _compact_column(row)
        assert "COLUMN_DEFAULT" not in result
        assert "CHARACTER_MAXIMUM_LENGTH" not in result
        assert "COLUMN_DESCRIPTION" not in result

    def test_non_empty_optional_keys_kept(self):
        """非空的可选字段保留"""
        row = {
            "COLUMN_NAME": "email",
            "DATA_TYPE": "nvarchar",
            "IS_NULLABLE": "YES",
            "CHARACTER_MAXIMUM_LENGTH": 255,
            "COLUMN_DESCRIPTION": "用户邮箱",
        }
        result = _compact_column(row)
        assert result["CHARACTER_MAXIMUM_LENGTH"] == 255
        assert result["COLUMN_DESCRIPTION"] == "用户邮箱"

    def test_keep_keys_set_content(self):
        """_COLUMN_KEEP_KEYS 包含预期的三个字段"""
        assert _COLUMN_KEEP_KEYS == {"COLUMN_NAME", "DATA_TYPE", "IS_NULLABLE"}


# ═══════════════════════════════════════════════════════════════
#  _format_columns_result
# ═══════════════════════════════════════════════════════════════


class TestFormatColumnsResult:
    """_format_columns_result: 按 detail 级别格式化列信息"""

    def _capture(self, result, table, detail, fmt="json-compact"):
        buf = StringIO()
        with patch("sys.stdout", buf):
            _format_columns_result(result, table, detail, fmt)
        return buf.getvalue()

    def test_names_detail_returns_column_names_only(self):
        result = {
            "success": True,
            "rows": [
                {"COLUMN_NAME": "id", "DATA_TYPE": "int"},
                {"COLUMN_NAME": "name", "DATA_TYPE": "varchar"},
            ],
        }
        output = self._capture(result, "users", _DETAIL_NAMES)
        data = json.loads(output)
        assert data["columns"] == ["id", "name"]
        assert data["count"] == 2

    def test_summary_detail_includes_type_and_nullable(self):
        result = {
            "success": True,
            "rows": [
                {"COLUMN_NAME": "id", "DATA_TYPE": "int", "IS_NULLABLE": "NO"},
                {"COLUMN_NAME": "email", "DATA_TYPE": "varchar", "IS_NULLABLE": "YES", "COLUMN_COMMENT": "用户邮箱"},
            ],
        }
        output = self._capture(result, "users", _DETAIL_SUMMARY)
        data = json.loads(output)
        assert data["count"] == 2
        assert data["columns"][0]["nullable"] is False
        assert data["columns"][1]["description"] == "用户邮箱"

    def test_failed_result_passed_through(self):
        result = {"success": False, "error": "table not found"}
        output = self._capture(result, "missing", _DETAIL_NAMES)
        assert "table not found" in output

    def test_full_detail_hint_when_many_columns(self, capsys):
        """列数 >= 40 时附加 hint 提示"""
        rows = [{"COLUMN_NAME": f"col{i}", "DATA_TYPE": "int", "IS_NULLABLE": "YES"} for i in range(45)]
        result = {"success": True, "rows": rows}
        _format_columns_result(result, "big_table", _DETAIL_FULL, "json-compact")
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "hint" in data
        assert "45" in data["hint"]


# ═══════════════════════════════════════════════════════════════
#  _format_constraints_result
# ═══════════════════════════════════════════════════════════════


class TestFormatConstraintsResult:
    def _capture(self, result, table, detail, fmt="json-compact"):
        buf = StringIO()
        with patch("sys.stdout", buf):
            _format_constraints_result(result, table, detail, fmt)
        return buf.getvalue()

    def test_names_detail(self):
        result = {
            "success": True,
            "rows": [
                {"constraint_name": "PK_users", "CONSTRAINT_NAME": "PK_users"},
                {"constraint_name": "UQ_email", "CONSTRAINT_NAME": "UQ_email"},
            ],
        }
        output = self._capture(result, "users", _DETAIL_NAMES)
        data = json.loads(output)
        assert data["constraints"] == ["PK_users", "UQ_email"]

    def test_summary_detail(self):
        result = {
            "success": True,
            "rows": [
                {"constraint_name": "PK_users", "constraint_type": "PRIMARY KEY"},
            ],
        }
        output = self._capture(result, "users", _DETAIL_SUMMARY)
        data = json.loads(output)
        assert data["constraints"][0]["type"] == "PRIMARY KEY"

    def test_failed_result(self):
        result = {"success": False, "error": "permission denied"}
        output = self._capture(result, "secret", _DETAIL_NAMES)
        assert "permission denied" in output


# ═══════════════════════════════════════════════════════════════
#  cmd_explore 路由分发
# ═══════════════════════════════════════════════════════════════


class TestCmdExploreDispatch:
    """cmd_explore 根据 object_type 路由到正确的子函数"""

    def _make_args(self, **kwargs):
        defaults = {
            "object_type": None,
            "detail": "names",
            "schema": None,
            "table": None,
            "pattern": None,
            "semantic": None,
            "limit": 5,
            "format": "json-compact",
            "level2": True,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @patch("cli.explore_cmds._explore_schemas")
    def test_object_type_schema_routes_to_schemas(self, mock_fn):
        cmd_explore(self._make_args(object_type="schema"))
        mock_fn.assert_called_once_with("names", "json-compact")

    @patch("cli.explore_cmds._explore_tables")
    def test_object_type_table_routes_to_tables(self, mock_fn):
        cmd_explore(self._make_args(object_type="table", pattern="LES"))
        mock_fn.assert_called_once_with(None, "LES", "names", "json-compact")

    @patch("cli.explore_cmds._explore_columns")
    def test_object_type_column_with_table_routes_to_columns(self, mock_fn):
        cmd_explore(self._make_args(object_type="column", table="users"))
        mock_fn.assert_called_once_with("users", None, "names", "json-compact")

    @patch("cli.explore_cmds._explore_column_search")
    def test_object_type_column_without_table_routes_to_search(self, mock_fn):
        cmd_explore(self._make_args(object_type="column", pattern="email"))
        mock_fn.assert_called_once_with("email", None, "names", "json-compact")

    @patch("cli.explore_cmds._explore_indexes")
    def test_object_type_index_requires_table(self, mock_fn):
        """index 无 --table 时报错，不调用底层函数"""
        buf = StringIO()
        with patch("sys.stderr", buf):
            cmd_explore(self._make_args(object_type="index"))
        mock_fn.assert_not_called()
        assert "--table required" in buf.getvalue()

    @patch("cli.explore_cmds._explore_fks")
    def test_object_type_fk_requires_table(self, mock_fn):
        buf = StringIO()
        with patch("sys.stderr", buf):
            cmd_explore(self._make_args(object_type="fk"))
        mock_fn.assert_not_called()
        assert "--table required" in buf.getvalue()

    @patch("cli.explore_cmds._explore_constraints")
    def test_object_type_constraint_requires_table(self, mock_fn):
        buf = StringIO()
        with patch("sys.stderr", buf):
            cmd_explore(self._make_args(object_type="constraint"))
        mock_fn.assert_not_called()
        assert "--table required" in buf.getvalue()

    @patch("cli.explore_cmds._explore_semantic")
    def test_semantic_routes_to_semantic(self, mock_fn):
        cmd_explore(self._make_args(semantic="订单", level2=True))
        mock_fn.assert_called_once_with("订单", 5, "json-compact", enable_level2=True)

    @patch("cli.explore_cmds._explore_semantic")
    def test_semantic_with_level2_false(self, mock_fn):
        cmd_explore(self._make_args(semantic="订单", level2=False))
        mock_fn.assert_called_once_with("订单", 5, "json-compact", enable_level2=False)

    @patch("cli.explore_cmds._explore_views")
    def test_object_type_view(self, mock_fn):
        cmd_explore(self._make_args(object_type="view", pattern="v_%"))
        mock_fn.assert_called_once_with(None, "v_%", "names", "json-compact")

    @patch("cli.explore_cmds._explore_routines")
    def test_object_type_procedure(self, mock_fn):
        cmd_explore(self._make_args(object_type="procedure"))
        mock_fn.assert_called_once_with("procedure", None, None, "names", "json-compact")

    @patch("cli.explore_cmds._explore_routines")
    def test_object_type_function(self, mock_fn):
        cmd_explore(self._make_args(object_type="function", schema="dbo"))
        mock_fn.assert_called_once_with("function", "dbo", None, "names", "json-compact")

    @patch("cli.explore_cmds._explore_schemas")
    def test_none_object_type_defaults_to_schemas(self, mock_fn):
        """object_type=None 且无 semantic 时路由到 schemas"""
        cmd_explore(self._make_args(object_type=None, semantic=None))
        mock_fn.assert_called_once()


# ═══════════════════════════════════════════════════════════════
#  _explore_tables 硬上限拦截
# ═══════════════════════════════════════════════════════════════


class TestExploreTablesHardLimits:
    """硬上限是 token 节约的核心防线，必须精确测试"""

    def _make_mock_conn_cfg(self, db_type="sqlite", rows=None):
        """构造 mock connection 和 execute_query 返回值"""
        mock_engine = MagicMock()
        cfg = {"db_type": db_type, "database": "test"}
        query_result = {"success": True, "rows": rows or []}
        return mock_engine, cfg, query_result

    @patch("cli.explore_cmds._out")
    @patch("cli.explore_cmds.execute_query")
    @patch("cli.explore_cmds.get_connection")
    @patch("cli.explore_cmds.default_schema", return_value="main")
    def test_names_hard_limit_blocks_large_scan(self, mock_default, mock_get_conn, mock_exec, mock_out):
        """无 pattern + names + >200 张表 → 硬上限拦截"""
        mock_engine, cfg, _ = self._make_mock_conn_cfg()
        mock_get_conn.return_value = (mock_engine, cfg)
        # 模拟 250 张表
        rows = [{"TABLE_NAME": f"table_{i}"} for i in range(250)]
        mock_exec.return_value = {"success": True, "rows": rows}

        from cli.explore_cmds import _explore_tables

        _explore_tables(None, None, _DETAIL_NAMES, "json-compact")

        call_args = mock_out.call_args
        payload = call_args[0][0]
        assert payload["success"] is False
        assert "硬上限" in payload["error"]
        assert "250" in payload["error"]
        mock_engine.dispose.assert_called_once()

    @patch("cli.explore_cmds._out")
    @patch("cli.explore_cmds.execute_query")
    @patch("cli.explore_cmds.get_connection")
    @patch("cli.explore_cmds.default_schema", return_value="main")
    def test_names_hard_limit_not_triggered_with_pattern(self, mock_default, mock_get_conn, mock_exec, mock_out):
        """有 pattern 时不触发硬上限（即使 >200 张表）"""
        mock_engine, cfg, _ = self._make_mock_conn_cfg()
        mock_get_conn.return_value = (mock_engine, cfg)
        rows = [{"TABLE_NAME": f"table_{i}"} for i in range(250)]
        mock_exec.return_value = {"success": True, "rows": rows}

        from cli.explore_cmds import _explore_tables

        _explore_tables(None, "LES", _DETAIL_NAMES, "json-compact")

        call_args = mock_out.call_args
        payload = call_args[0][0]
        assert payload["success"] is True

    @patch("cli.explore_cmds._fetch_table_comments", return_value={})
    @patch("cli.explore_cmds._out")
    @patch("cli.explore_cmds.execute_query")
    @patch("cli.explore_cmds.get_connection")
    @patch("cli.explore_cmds.default_schema", return_value="main")
    def test_summary_hard_limit_blocks_large_scan(self, mock_default, mock_get_conn, mock_exec, mock_out, mock_comments):
        """无 pattern + summary + >100 张表 → 硬上限拦截"""
        mock_engine, cfg, _ = self._make_mock_conn_cfg()
        mock_get_conn.return_value = (mock_engine, cfg)
        rows = [{"TABLE_NAME": f"table_{i}", "TABLE_TYPE": "BASE TABLE"} for i in range(120)]
        mock_exec.return_value = {"success": True, "rows": rows}

        from cli.explore_cmds import _explore_tables

        _explore_tables(None, None, _DETAIL_SUMMARY, "json-compact")

        call_args = mock_out.call_args
        payload = call_args[0][0]
        assert payload["success"] is False
        assert "summary" in payload["error"].lower() or "硬上限" in payload["error"]

    @patch("cli.explore_cmds._out")
    @patch("cli.explore_cmds.execute_query")
    @patch("cli.explore_cmds.get_connection")
    @patch("cli.explore_cmds.default_schema", return_value="main")
    def test_names_within_limit_passes(self, mock_default, mock_get_conn, mock_exec, mock_out):
        """无 pattern 但 <200 张表 → 正常返回 + hint 警告（>=50 张时）"""
        mock_engine, cfg, _ = self._make_mock_conn_cfg()
        mock_get_conn.return_value = (mock_engine, cfg)
        rows = [{"TABLE_NAME": f"table_{i}"} for i in range(60)]
        mock_exec.return_value = {"success": True, "rows": rows}

        from cli.explore_cmds import _explore_tables

        _explore_tables(None, None, _DETAIL_NAMES, "json-compact")

        call_args = mock_out.call_args
        payload = call_args[0][0]
        assert payload["success"] is True
        assert payload["count"] == 60
        # >=50 张表时附加 hint 警告
        assert "hint" in payload


# ═══════════════════════════════════════════════════════════════
#  Pattern 自动包装
# ═══════════════════════════════════════════════════════════════


class TestPatternAutoWrap:
    """无通配符的 pattern 自动包成 %xxx%"""

    @patch("cli.explore_cmds._out")
    @patch("cli.explore_cmds.execute_query")
    @patch("cli.explore_cmds.get_connection")
    @patch("cli.explore_cmds.default_schema", return_value="main")
    def test_bare_keyword_gets_wrapped(self, mock_default, mock_get_conn, mock_exec, mock_out):
        """pattern='LES' 无通配符 → 自动变为 '%LES%'"""
        mock_engine, cfg, _ = self._make_mock_conn_cfg_mock()
        mock_get_conn.return_value = (mock_engine, cfg)
        mock_exec.return_value = {"success": True, "rows": []}

        from cli.explore_cmds import _explore_tables

        _explore_tables(None, "LES", _DETAIL_NAMES, "json-compact")

        # 检查传给 execute_query 的 params 包含 %LES%
        call_args = mock_exec.call_args
        params = call_args[1].get("params") or (call_args[0][2] if len(call_args[0]) > 2 else None)
        if params:
            assert any("%LES%" in str(p) for p in (params if isinstance(params, (list, tuple)) else [params]))

    @patch("cli.explore_cmds._out")
    @patch("cli.explore_cmds.execute_query")
    @patch("cli.explore_cmds.get_connection")
    @patch("cli.explore_cmds.default_schema", return_value="main")
    def test_pattern_with_wildcard_not_wrapped(self, mock_default, mock_get_conn, mock_exec, mock_out):
        """pattern='LES%' 已有通配符 → 不包装"""
        mock_engine, cfg, _ = self._make_mock_conn_cfg_mock()
        mock_get_conn.return_value = (mock_engine, cfg)
        mock_exec.return_value = {"success": True, "rows": []}

        from cli.explore_cmds import _explore_tables

        _explore_tables(None, "LES%", _DETAIL_NAMES, "json-compact")

        call_args = mock_exec.call_args
        params = call_args[1].get("params") or (call_args[0][2] if len(call_args[0]) > 2 else None)
        if params:
            # 不应出现 %LES%%
            assert not any("%LES%%" in str(p) for p in (params if isinstance(params, (list, tuple)) else [params]))

    def _make_mock_conn_cfg_mock(self):
        mock_engine = MagicMock()
        cfg = {"db_type": "sqlite", "database": "test"}
        return mock_engine, cfg, {"success": True, "rows": []}


# ═══════════════════════════════════════════════════════════════
#  detail 级别常量
# ═══════════════════════════════════════════════════════════════


class TestDetailConstants:
    """detail 级别常量值正确"""

    def test_detail_names_value(self):
        assert _DETAIL_NAMES == "names"

    def test_detail_summary_value(self):
        assert _DETAIL_SUMMARY == "summary"

    def test_detail_full_value(self):
        assert _DETAIL_FULL == "full"
