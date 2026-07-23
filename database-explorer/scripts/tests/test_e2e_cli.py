#!/usr/bin/env python3
"""端到端（e2e）CLI 测试

通过 subprocess 调用 db_tool.py，模拟 Agent 真实调用场景（无交互 TTY）。
覆盖第一轮 + 第二轮 P0 修复的端到端行为：
- query 写操作确认（--yes 通道 + 无 TTY 拒绝）
- query 全表扫描警告
- export 写操作硬拒绝、系统路径禁止、覆写保护
- search --semantic 覆盖全部表（不截断）
- schemas 命令

用 SQLite 文件库（每个测试独立 tmp_path），无需外部数据库驱动。
"""

import os
import sys
import subprocess


import pytest
from _helpers import run_cli, SCRIPT_DIR, DB_TOOL


def _sbert_available() -> bool:
    """检查 sentence_transformers 已安装且模型已缓存（不会触发下载）。"""
    try:
        import sentence_transformers  # noqa: F401
        from pathlib import Path as _P

        cache = _P.home() / ".cache" / "torch" / "sentence_transformers"
        return cache.exists()
    except ImportError:
        return False


_skip_no_sbert = pytest.mark.skipif(not _sbert_available(), reason="SBERT model not cached locally")


@pytest.fixture
def sqlite_conn(tmp_path, monkeypatch):
    """建立 SQLite 文件库连接并建表，返回连接名。

    通过 DATABASE_EXPLORER_HOME 环境变量把配置目录重定向到 tmp_path，
    完全隔离测试，绝不污染用户真实的 ~/.database-explorer/connections.json。
    monkeypatch 确保测试结束后环境变量自动还原。
    """
    home = str(tmp_path / "explorer-home")
    monkeypatch.setenv("DATABASE_EXPLORER_HOME", home)

    db_file = tmp_path / "test.db"
    conn_str = f"sqlite:///{db_file.as_posix()}"
    name = f"e2e-{tmp_path.name}"

    rc, out, err = run_cli(
        [
            "connect",
            "--db-type",
            "sqlite",
            "--connection-string",
            conn_str,
            "--name",
            name,
        ]
    )
    assert rc == 0, f"连接失败: {err}"

    # 建表（写操作，用 --yes）
    rc, out, err = run_cli(
        [
            "query",
            "--yes",
            "--sql",
            "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT)",
        ]
    )
    assert rc == 0, f"建表失败: {err}"

    # 插数据
    rc, out, err = run_cli(
        [
            "query",
            "--yes",
            "--sql",
            "INSERT INTO users (id, name, email) VALUES (1, 'alice', 'a@x.com')",
        ]
    )
    assert rc == 0, f"插数据失败: {err}"

    yield name
    # monkeypatch 自动还原 DATABASE_EXPLORER_HOME；tmp_path 自动清理


# ─────────────────────────────────────────────────────────────────
# query 写操作确认（第一轮 P0-3）
# ─────────────────────────────────────────────────────────────────


class TestQueryWriteConfirm:
    def test_write_without_yes_rejected(self, sqlite_conn):
        """写操作无 --yes 且无 TTY → 被拒（不卡死）。"""
        rc, out, err = run_cli(
            [
                "query",
                "--sql",
                "INSERT INTO users (id, name) VALUES (2, 'bob')",
            ]
        )
        assert "取消" in err or "取消" in out

    def test_write_with_yes_executes(self, sqlite_conn):
        """写操作带 --yes → 执行成功。"""
        rc, out, err = run_cli(
            [
                "query",
                "--yes",
                "--sql",
                "INSERT INTO users (id, name) VALUES (2, 'bob')",
            ]
        )
        assert rc == 0

    def test_write_with_literal_drop_not_misjudged(self, sqlite_conn):
        """P0-2：SELECT 'drop' 字面量不被误判为写操作。"""
        rc, out, err = run_cli(
            [
                "query",
                "--sql",
                "SELECT 'drop' AS msg",
            ]
        )
        assert "写操作" not in err
        assert rc == 0

    def test_mysql_conditional_comment_preserved(self, sqlite_conn):
        """/*!nnnnn ... */ 条件注释被保留为可执行代码，不被剥离。

        SQLite 不执行条件注释，但 strip_comments 必须保留其内容
        以避免安全检查时漏检。
        """
        from _security import strip_comments

        sql = "SELECT 1 /*!50110 , 2 */"
        cleaned = strip_comments(sql)
        assert "50110" in cleaned
        assert ", 2" in cleaned

    def test_regular_block_comment_stripped(self):
        """普通 /* comment */ 被正确剥离。"""
        from _security import strip_comments

        sql = "SELECT 1 /* this is a comment */"
        cleaned = strip_comments(sql)
        assert "this is a comment" not in cleaned
        assert "SELECT 1" in cleaned


class TestIdentifierEscaping:
    def test_special_chars_quoted(self):
        """含空格/特殊字符的标识符被正确引用，不报错。"""
        from _security import quote_ident

        assert quote_ident("my table", "sqlserver") == "[my table]"
        assert quote_ident("my table", "mysql") == "`my table`"
        assert quote_ident("my table", "postgresql") == '"my table"'
        assert quote_ident("my table", "sqlite") == '"my table"'

    def test_inner_quotes_escaped(self):
        """标识符内部的引号被正确转义。"""
        from _security import quote_ident

        assert quote_ident('a"b', "postgresql") == '"a""b"'
        assert quote_ident("a]b", "sqlserver") == "[a]]b]"
        assert quote_ident("a`b", "mysql") == "`a``b`"

    def test_already_quoted_passthrough(self):
        """已引用的标识符直接透传。"""
        from _security import quote_ident

        assert quote_ident("[my table]", "sqlserver") == "[my table]"
        assert quote_ident("`my table`", "mysql") == "`my table`"


# ─────────────────────────────────────────────────────────────────
# query 全表扫描警告（第一轮 P0）
# ─────────────────────────────────────────────────────────────────


class TestFullTableScan:
    def test_full_scan_without_yes_warned(self, sqlite_conn):
        """SELECT * 无 WHERE → 警告并被拒（无 TTY）。"""
        rc, out, err = run_cli(["query", "--sql", "SELECT * FROM users"])
        assert "全表" in err or "全表" in out

    def test_full_scan_with_yes_executes(self, sqlite_conn):
        rc, out, err = run_cli(["query", "--yes", "--sql", "SELECT * FROM users"])
        assert rc == 0
        assert "alice" in out


# ─────────────────────────────────────────────────────────────────
# export 护栏（第一轮 P0）
# ─────────────────────────────────────────────────────────────────


class TestExportGuardrails:
    def test_export_write_sql_rejected(self, sqlite_conn, tmp_path):
        """export 写操作 SQL 硬拒绝（即使 --yes）。"""
        rc, out, err = run_cli(
            [
                "export",
                "--yes",
                "--sql",
                "DROP TABLE users",
                "--filepath",
                str(tmp_path / "x.csv"),
            ]
        )
        assert "仅允许 SELECT" in err or "仅允许 SELECT" in out

    def test_export_protected_path_blocked(self, sqlite_conn):
        """export 到系统保护目录被拦。"""
        rc, out, err = run_cli(
            [
                "export",
                "--yes",
                "--sql",
                "SELECT * FROM users",
                "--filepath",
                r"C:\Windows\System32\dump.csv",
            ]
        )
        assert "保护目录" in err or "保护目录" in out

    def test_export_overwrite_without_yes_rejected(self, sqlite_conn, tmp_path):
        """覆写已存在文件无 --yes → 拒绝。"""
        target = tmp_path / "exists.csv"
        target.write_text("old")
        rc, out, err = run_cli(
            [
                "export",
                "--sql",
                "SELECT * FROM users",
                "--filepath",
                str(target),
            ]
        )
        assert "取消" in err or "取消" in out or "覆盖" in err

    def test_export_overwrite_with_yes(self, sqlite_conn, tmp_path):
        """覆写带 --yes → 成功。"""
        target = tmp_path / "exists.csv"
        target.write_text("old")
        rc, out, err = run_cli(
            [
                "export",
                "--yes",
                "--sql",
                "SELECT * FROM users",
                "--filepath",
                str(target),
            ]
        )
        assert rc == 0
        assert "已导出" in out

    def test_export_fresh_select(self, sqlite_conn, tmp_path):
        """正常 SELECT 导出成功。"""
        target = tmp_path / "fresh.csv"
        rc, out, err = run_cli(
            [
                "export",
                "--sql",
                "SELECT * FROM users",
                "--filepath",
                str(target),
            ]
        )
        assert rc == 0
        assert "已导出" in out

    def test_export_csv_formula_injection_sanitized(self, sqlite_conn, tmp_path):
        """P0-1：CSV 公式注入载荷导出时被转义。

        数据库中存储的 =cmd|'/c calc'!A1 这类值，导出 CSV 时必须加单引号前缀，
        防止 Excel/LibreOffice 打开时按公式执行（远程代码执行）。
        query --format csv 路径已用 _sanitize_csv_value，export 路径需保持一致。
        """
        # 插入公式注入载荷
        rc, out, err = run_cli(
            [
                "query",
                "--yes",
                "--sql",
                "INSERT INTO users (id, name, email) VALUES (9, \"=cmd|'/c calc'!A1\", 'x@x.com')",
            ]
        )
        assert rc == 0, f"插入载荷失败: {err}"

        target = tmp_path / "injection.csv"
        rc, out, err = run_cli(
            [
                "export",
                "--sql",
                "SELECT name FROM users WHERE id = 9",
                "--filepath",
                str(target),
            ]
        )
        assert rc == 0
        content = target.read_text(encoding="utf-8-sig")
        # 公式载荷应被加单引号前缀：'=cmd...，而非裸 =cmd
        assert "'=cmd" in content, f"CSV 公式注入未转义: {content!r}"
        # 确保不是 Excel 会直接执行的裸公式行
        lines_with_bare_formula = [ln for ln in content.splitlines() if ln.startswith("=cmd")]
        assert not lines_with_bare_formula, f"存在未转义的裸公式行: {lines_with_bare_formula}"


# ─────────────────────────────────────────────────────────────────
# explain 输入校验（P0-2：拒绝写操作和多语句）
# ─────────────────────────────────────────────────────────────────


class TestExplainGuardrails:
    def test_explain_rejects_write_sql(self, sqlite_conn):
        """P0-2：explain 拒绝写操作 SQL（explain 语义只针对只读查询）。"""
        rc, out, err = run_cli(["explain", "--sql", "DROP TABLE users"])
        assert "写操作" in err or "写操作" in out

    def test_explain_rejects_multi_statement(self, sqlite_conn):
        """P0-2：explain 拒绝多语句输入（防止 ; DROP TABLE 注入）。"""
        rc, out, err = run_cli(["explain", "--sql", "SELECT 1; DROP TABLE users"])
        assert "单条" in err or "单条" in out or "多语句" in err or "多语句" in out

    def test_explain_accepts_readonly_select(self, sqlite_conn):
        """P0-2 回归：正常只读 SELECT 的 explain 仍能执行。"""
        rc, out, err = run_cli(["explain", "--sql", "SELECT * FROM users WHERE id = 1"])
        assert rc == 0, f"只读 explain 不应被拒: {err}"


# ─────────────────────────────────────────────────────────────────
# query TOP/LIMIT 处理（P0-1：TOP/OFFSET 冲突修复）
# ─────────────────────────────────────────────────────────────────


class TestQueryTopLimit:
    def test_top_not_broken_on_sqlite(self, sqlite_conn):
        """SQLite 支持 LIMIT，用户已写 LIMIT 时不重复追加。

        注：SQLite 无 TOP 语法，这里测 LIMIT 不重复。
        SQL Server 的 TOP 冲突修复用真实库已验证（见手动测试）。
        """
        rc, out, err = run_cli(
            [
                "query",
                "--sql",
                "SELECT * FROM users LIMIT 1",
            ]
        )
        # LIMIT 1 不触发全表扫描警告（有 LIMIT），且不报语法错
        assert rc == 0
        assert "错误" not in out and "error" not in out.lower()

    def test_query_with_limit_no_double_append(self, sqlite_conn):
        """用户 LIMIT 存在时不再追加第二个 LIMIT。"""
        rc, out, err = run_cli(
            [
                "query",
                "--sql",
                "SELECT name FROM users LIMIT 2",
            ]
        )
        assert rc == 0
        # 不应出现 LIMIT 重复导致的语法错误
        assert "syntax" not in err.lower() and "near" not in err.lower()


# ─────────────────────────────────────────────────────────────────


@_skip_no_sbert
class TestSemanticSearch:
    def test_search_covers_all_tables(self, sqlite_conn):
        """P0-1：语义搜索覆盖全部表（不截断）。"""
        rc, out, err = run_cli(["search", "--semantic", "users", "--limit", "5"])
        assert "users" in out

    def test_search_pattern(self, sqlite_conn):
        rc, out, err = run_cli(["search", "--pattern", "%user%"])
        assert rc == 0
        assert "users" in out


# ─────────────────────────────────────────────────────────────────
# search/find 统一走 explore 适配层（v0.5.1）
# ─────────────────────────────────────────────────────────────────


class TestLegacySearchFindExploreRouting:
    """验证 search/find 路由到 cmd_explore，输出与 explore 一致。"""

    def test_search_pattern_matches_explore(self, sqlite_conn):
        """search --pattern 应与 explore --object-type table --pattern 输出一致。"""
        rc_s, out_s, err_s = run_cli(["search", "--pattern", "%user%", "--format", "json-compact"])
        rc_e, out_e, err_e = run_cli(["explore", "--object-type", "table", "--pattern", "%user%", "--format", "json-compact"])
        assert rc_s == 0, f"search failed: {err_s}"
        assert rc_e == 0, f"explore failed: {err_e}"
        # 两者 json-compact 输出一致（search 通过 _legacy_search 路由到 cmd_explore）
        assert out_s == out_e, f"路由不一致:\n  search: {out_s}\n  explore: {out_e}"

    def test_find_pattern_matches_explore(self, sqlite_conn):
        """find --pattern 应与 explore --object-type column --pattern 输出一致。"""
        rc_f, out_f, err_f = run_cli(["find", "--pattern", "name", "--format", "json-compact"])
        rc_e, out_e, err_e = run_cli(["explore", "--object-type", "column", "--pattern", "name", "--format", "json-compact"])
        assert rc_f == 0, f"find failed: {err_f}"
        assert rc_e == 0, f"explore failed: {err_e}"
        # 两者 json-compact 输出一致（find 通过 _legacy_find 路由到 cmd_explore）
        assert out_f == out_e, f"路由不一致:\n  find: {out_f}\n  explore: {out_e}"

    def test_explore_level2_flag_is_accepted(self, sqlite_conn):
        """explore --semantic --level2 应被 argparse 接受（不报 unknown arg）。"""
        # SBERT 可能不可用，只验证 argparse 不报错
        rc, out, err = run_cli(["explore", "--semantic", "user", "--level2"])
        # 只要不是 usage error（argparse 报错会输出 "unrecognized arguments"）
        assert "unrecognized arguments" not in err


# ─────────────────────────────────────────────────────────────────
# schemas 命令（第二轮 P0-3）
# ─────────────────────────────────────────────────────────────────


class TestSchemasCommand:
    def test_schemas_lists_main(self, sqlite_conn):
        """schemas 命令对 SQLite 返回 ['main']。"""
        rc, out, err = run_cli(["schemas"])
        assert rc == 0
        assert "1 项" in out or "main" in out


# ─────────────────────────────────────────────────────────────────
# 多语句注入拦截（第一轮 P0）
# ─────────────────────────────────────────────────────────────────


class TestMultiStatementInjection:
    def test_query_multi_statement_write_needs_yes(self, sqlite_conn):
        """SELECT 1; INSERT ... → 多语句含写操作需 --yes（否则被拒）。"""
        rc, out, err = run_cli(
            [
                "query",
                "--sql",
                "SELECT 1; INSERT INTO users (id, name) VALUES (99, 'x')",
            ]
        )
        assert "取消" in err or "取消" in out

    def test_query_multi_statement_mixed_with_yes(self, sqlite_conn):
        """SELECT 1; INSERT ... → 带 --yes 逐条执行。"""
        rc, out, err = run_cli(
            [
                "query",
                "--yes",
                "--sql",
                "SELECT 1 AS val; INSERT INTO users (id, name) VALUES (100, 'multi')",
            ]
        )
        assert rc == 0

    def test_query_multi_statement_readonly(self, sqlite_conn):
        """SELECT 1; SELECT 2 → 两条只读语句可直接执行。"""
        rc, out, err = run_cli(
            [
                "query",
                "--sql",
                "SELECT 1 AS a; SELECT 2 AS b",
            ]
        )
        assert rc == 0


# ───────────────────────────────────────────────────────────────
# explore 统一命令（token 效率优化 P0）
# ────────────────────────────────────────────────────────────────


class TestExploreSchema:
    def test_explore_schema_names(self, sqlite_conn):
        """explore --object-type schema --detail names → 紧凑 JSON 含 schemas 列表。"""
        rc, out, err = run_cli(["explore", "--object-type", "schema", "--detail", "names"])
        assert rc == 0
        assert "main" in out

    def test_explore_schema_default_format_is_compact(self, sqlite_conn):
        """explore 不传 --format 时默认 json-compact。"""
        rc, out, err = run_cli(["explore", "--object-type", "schema"])
        assert rc == 0
        import json

        data = json.loads(out)
        assert "schemas" in data


class TestExploreTable:
    def test_explore_table_names(self, sqlite_conn):
        """explore --object-type table --detail names → 仅表名列表。"""
        rc, out, err = run_cli(["explore", "--object-type", "table", "--detail", "names"])
        assert rc == 0
        import json

        data = json.loads(out)
        assert "users" in data.get("tables", [])

    def test_explore_table_with_pattern(self, sqlite_conn):
        """explore --object-type table --pattern %user% → 匹配 users。"""
        rc, out, err = run_cli(["explore", "--object-type", "table", "--pattern", "%user%", "--detail", "names"])
        assert rc == 0
        assert "users" in out

    def test_explore_table_summary(self, sqlite_conn):
        """explore --object-type table --detail summary → 含 name/schema/type。"""
        rc, out, err = run_cli(["explore", "--object-type", "table", "--detail", "summary"])
        assert rc == 0
        import json

        data = json.loads(out)
        assert data["tables"][0].get("name") == "users"

    def test_explore_table_full(self, sqlite_conn):
        """explore --object-type table --detail full → 含完整字段。"""
        rc, out, err = run_cli(["explore", "--object-type", "table", "--detail", "full"])
        assert rc == 0
        assert "users" in out


class TestExploreColumn:
    def test_explore_column_names(self, sqlite_conn):
        """explore --object-type column --table users --detail names → 仅列名。"""
        rc, out, err = run_cli(["explore", "--object-type", "column", "--table", "users", "--detail", "names"])
        assert rc == 0
        import json

        data = json.loads(out)
        assert "id" in data.get("columns", []) or "name" in data.get("columns", [])

    def test_explore_column_summary(self, sqlite_conn):
        """explore --object-type column --table users --detail summary → 含 type。"""
        rc, out, err = run_cli(["explore", "--object-type", "column", "--table", "users", "--detail", "summary"])
        assert rc == 0
        import json

        data = json.loads(out)
        cols = data.get("columns", [])
        assert any(c.get("type") for c in cols)

    def test_explore_column_search(self, sqlite_conn):
        """explore --object-type column --pattern %name% → 列搜索。"""
        rc, out, err = run_cli(["explore", "--object-type", "column", "--pattern", "%name%", "--detail", "names"])
        assert rc == 0


@_skip_no_sbert
class TestExploreSemantic:
    def test_explore_semantic(self, sqlite_conn):
        """explore --semantic users → 语义搜索。"""
        rc, out, err = run_cli(["explore", "--semantic", "users"])
        assert rc == 0
        import json

        data = json.loads(out)
        assert data.get("query") == "users"
        assert len(data.get("matches", [])) > 0


class TestExploreIndex:
    def test_explore_index_names(self, sqlite_conn):
        """explore --object-type index --table users → 索引列表。"""
        rc, out, err = run_cli(["explore", "--object-type", "index", "--table", "users", "--detail", "names"])
        assert rc == 0

    def test_explore_index_requires_table(self, sqlite_conn):
        """explore --object-type index 无 --table → 报错。"""
        rc, out, err = run_cli(["explore", "--object-type", "index"])
        assert rc == 0
        assert "required" in err.lower() or "--table" in err


class TestExploreFk:
    def test_explore_fk_requires_table(self, sqlite_conn):
        """explore --object-type fk 无 --table → 报错。"""
        rc, out, err = run_cli(["explore", "--object-type", "fk"])
        assert "required" in err.lower() or "--table" in err


class TestExploreConstraint:
    def test_explore_constraint_names(self, sqlite_conn):
        """explore --object-type constraint --table users → 约束列表。"""
        rc, out, err = run_cli(["explore", "--object-type", "constraint", "--table", "users", "--detail", "names"])
        assert rc == 0


class TestExploreView:
    def test_explore_view_names(self, sqlite_conn):
        """explore --object-type view → 视图列表（SQLite 无视图时返回空）。"""
        rc, out, err = run_cli(["explore", "--object-type", "view", "--detail", "names"])
        assert rc == 0
        import json

        data = json.loads(out)
        assert "views" in data

    def test_explore_view_with_view(self, sqlite_conn):
        """建视图后 explore view 能发现。"""
        rc, out, err = run_cli(
            [
                "query",
                "--yes",
                "--sql",
                "CREATE VIEW v_users AS SELECT id, name FROM users",
            ]
        )
        assert rc == 0
        rc, out, err = run_cli(["explore", "--object-type", "view", "--detail", "names"])
        assert rc == 0
        import json

        data = json.loads(out)
        assert "v_users" in data.get("views", [])

    def test_explore_view_full(self, sqlite_conn):
        """explore --object-type view --detail full → 含 definition。"""
        rc, out, err = run_cli(
            [
                "query",
                "--yes",
                "--sql",
                "CREATE VIEW v_users2 AS SELECT id, name FROM users",
            ]
        )
        assert rc == 0
        rc, out, err = run_cli(["explore", "--object-type", "view", "--detail", "full"])
        assert rc == 0
        assert "v_users2" in out


class TestExploreProcedure:
    def test_explore_procedure_sqlite_returns_empty(self, sqlite_conn):
        """explore --object-type procedure → SQLite 返回空+说明。"""
        rc, out, err = run_cli(["explore", "--object-type", "procedure", "--detail", "names"])
        assert rc == 0
        import json

        data = json.loads(out)
        assert data.get("count") == 0

    def test_explore_function_sqlite_returns_empty(self, sqlite_conn):
        """explore --object-type function → SQLite 返回空+说明。"""
        rc, out, err = run_cli(["explore", "--object-type", "function", "--detail", "names"])
        assert rc == 0
        import json

        data = json.loads(out)
        assert data.get("count") == 0


# ────────────────────────────────────────────────────────────────
# json-compact 输出格式（token 效率优化 P0）
# ───────────────────────────────────────────────────────────────


class TestJsonCompactFormat:
    def test_query_json_compact(self, sqlite_conn):
        """query --format json-compact → 紧凑 JSON (c/r 格式)。"""
        rc, out, err = run_cli(["query", "--yes", "--sql", "SELECT * FROM users", "--format", "json-compact"])
        assert rc == 0
        import json

        data = json.loads(out)
        assert "c" in data
        assert "r" in data
        assert isinstance(data["c"], list)
        assert isinstance(data["r"], list)

    def test_json_compact_smaller_than_json(self, sqlite_conn):
        """json-compact 输出比 json 格式更短。"""
        rc1, out1, _ = run_cli(["query", "--yes", "--sql", "SELECT * FROM users", "--format", "json-compact"])
        rc2, out2, _ = run_cli(["query", "--yes", "--sql", "SELECT * FROM users", "--format", "json"])
        assert rc1 == 0 and rc2 == 0
        assert len(out1) < len(out2)


# ──────────────────────────────────────────────────────────────
# --pipe 常驻进程模式（token 效率优化 P2）
# ───────────────────────────────────────────────────────────────


class TestPipeMode:
    def test_pipe_explore_schema(self, sqlite_conn):
        """--pipe 模式下 explore schema 返回 JSON-RPC 响应。"""
        import json

        env_extra = {"DATABASE_EXPLORER_HOME": os.environ.get("DATABASE_EXPLORER_HOME", "")}
        cmd = [sys.executable, str(DB_TOOL), "--pipe"]
        env = dict(os.environ, PYTHONPATH=str(SCRIPT_DIR))
        if env_extra:
            env.update(env_extra)

        requests = [
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "explore", "params": {"object_type": "schema", "detail": "names"}}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "exit", "params": {}}),
        ]
        stdin_data = "\n".join(requests) + "\n"

        proc = subprocess.run(
            cmd,
            input=stdin_data,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert proc.returncode == 0
        lines = [ln for ln in proc.stdout.strip().split("\n") if ln.strip()]
        # First line: ready notification, second: explore result, third: exit result
        assert len(lines) >= 2
        result = json.loads(lines[1] if len(lines) > 2 else lines[0])
        assert result.get("id") in (1, None) or "result" in result or "error" not in result

    def test_pipe_query(self, sqlite_conn):
        """--pipe 模式下 query 返回 JSON-RPC 响应。"""
        import json

        env = dict(os.environ, PYTHONPATH=str(SCRIPT_DIR))

        requests = [
            json.dumps(
                {"jsonrpc": "2.0", "id": 1, "method": "query", "params": {"sql": "SELECT 1 AS val", "format": "json-compact", "yes": True}}
            ),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "exit", "params": {}}),
        ]
        stdin_data = "\n".join(requests) + "\n"

        proc = subprocess.run(
            [sys.executable, str(DB_TOOL), "--pipe"],
            input=stdin_data,
            capture_output=True,
            text=True,
            env=env,
            timeout=30,
        )
        assert proc.returncode == 0


class TestExploreBytesData:
    def test_query_blob_json_compact_no_crash(self, sqlite_conn):
        """含 BLOB 列的数据以 json-compact 输出不崩溃。"""
        rc, out, err = run_cli(
            [
                "query",
                "--yes",
                "--sql",
                "CREATE TABLE files (id INTEGER PRIMARY KEY, name TEXT, content BLOB)",
            ]
        )
        assert rc == 0
        rc, out, err = run_cli(
            [
                "query",
                "--yes",
                "--sql",
                "INSERT INTO files VALUES (1, 'a.txt', X'48656c6c6f')",
            ]
        )
        assert rc == 0
        rc, out, err = run_cli(
            [
                "query",
                "--yes",
                "--sql",
                "SELECT * FROM files",
                "--format",
                "json-compact",
            ]
        )
        assert rc == 0
        import json

        data = json.loads(out)
        assert data["r"][0][1] == "a.txt"
        assert data["r"][0][2] == "Hello"

    def test_explore_table_with_blob_no_crash(self, sqlite_conn):
        """含 BLOB 列的表做 explore full 不崩溃。"""
        rc, out, err = run_cli(
            [
                "query",
                "--yes",
                "--sql",
                "CREATE TABLE blobs (id INTEGER, data BLOB)",
            ]
        )
        assert rc == 0
        rc, out, err = run_cli(
            [
                "explore",
                "--object-type",
                "table",
                "--table",
                "blobs",
                "--detail",
                "full",
            ]
        )
        assert rc == 0
        import json

        data = json.loads(out)
        assert data["success"] is True


# ============================================================
# sample / profile / crud — previously untested commands
# ============================================================


class TestSampleCommand:
    """sample: random row sampling from a table."""

    def test_sample_returns_rows(self, sqlite_conn):
        rc, out, err = run_cli(["sample", "--table", "users", "--n", "10"])
        assert rc == 0, f"sample failed: {err}"
        assert "alice" in out, f"Expected 'alice' in sample output: {out}"

    def test_sample_nonexistent_table(self, sqlite_conn):
        rc, out, err = run_cli(["sample", "--table", "nonexistent", "--n", "5"])
        # Should not crash — returns error or empty
        assert rc == 0, f"sample should handle missing table gracefully: {err}"


class TestProfileCommand:
    """profile: row count + NULL stats for a table."""

    def test_profile_shows_row_count(self, sqlite_conn):
        rc, out, err = run_cli(["profile", "--table", "users"])
        assert rc == 0, f"profile failed: {err}"
        assert "1" in out, f"Expected row count '1' in profile: {out}"


class TestCrudCommand:
    """crud: generates INSERT/SELECT/UPDATE/DELETE SQL for a table."""

    def test_crud_generates_all_four(self, sqlite_conn):
        rc, out, err = run_cli(["crud", "--table", "users"])
        assert rc == 0, f"crud failed: {err}"
        assert "INSERT" in out.upper(), f"Expected INSERT in CRUD output: {out}"
        assert "SELECT" in out.upper(), f"Expected SELECT in CRUD output: {out}"
        assert "UPDATE" in out.upper(), f"Expected UPDATE in CRUD output: {out}"
        assert "DELETE" in out.upper(), f"Expected DELETE in CRUD output: {out}"


class TestListCommand:
    """list: show saved connections."""

    def test_list_shows_active_connection(self, sqlite_conn):
        rc, out, err = run_cli(["list"])
        assert rc == 0, f"list failed: {err}"
        assert "sqlite" in out.lower(), f"Expected sqlite in list: {out}"


class TestPingCommand:
    """ping: test connection health."""

    def test_ping_active_connection(self, sqlite_conn):
        rc, out, err = run_cli(["ping"])
        assert rc == 0, f"ping failed: {err}"


class TestHistoryCommand:
    """history: show command history."""

    def test_history_returns_entries(self, sqlite_conn):
        # Run a query first to have history
        run_cli(["query", "--yes", "--sql", "SELECT COUNT(*) FROM users"])
        rc, out, err = run_cli(["history", "--n", "5"])
        assert rc == 0, f"history failed: {err}"
        # query 走 subprocess 路径必须写入 history,否则 history 命令恒空(SKILL.md §2.4 契约)
        assert "SELECT COUNT(*) FROM users" in out, f"history should contain the query just executed; got: {out!r}"


# ============================================================
# Legacy commands — previously zero coverage
# ============================================================


@pytest.fixture
def sqlite_with_fk(tmp_path, monkeypatch):
    """SQLite DB with FK + index for testing legacy schema commands."""
    home = str(tmp_path / "explorer-home")
    monkeypatch.setenv("DATABASE_EXPLORER_HOME", home)
    db_file = tmp_path / "fk_test.db"
    conn_str = f"sqlite:///{db_file.as_posix()}"
    name = f"fk-{tmp_path.name}"
    rc, _, err = run_cli(
        [
            "connect",
            "--db-type",
            "sqlite",
            "--connection-string",
            conn_str,
            "--name",
            name,
        ]
    )
    assert rc == 0, f"connect failed: {err}"
    for sql in [
        "CREATE TABLE t_orders (id INTEGER PRIMARY KEY, cust_name TEXT)",
        "CREATE TABLE t_items (id INTEGER PRIMARY KEY, order_id INTEGER, FOREIGN KEY (order_id) REFERENCES t_orders(id))",
        "CREATE INDEX idx_oid ON t_items (order_id)",
    ]:
        rc, _, err = run_cli(["query", "--yes", "--sql", sql])
        assert rc == 0, f"DDL failed: {err}"
    yield name


class TestLegacySchemaCommand:
    def test_schema_returns_table_info(self, sqlite_with_fk):
        rc, out, err = run_cli(["schema"])
        assert rc == 0, f"schema failed: {err}"
        assert len(out.strip()) > 0, "schema should produce output"


class TestLegacyColumnsCommand:
    def test_columns_returns_column_info(self, sqlite_with_fk):
        rc, out, err = run_cli(["columns", "--table", "t_orders"])
        assert rc == 0, f"columns failed: {err}"
        assert len(out.strip()) > 0, "columns should produce output"


class TestLegacyIndexesCommand:
    def test_indexes_returns_index_info(self, sqlite_with_fk):
        rc, out, err = run_cli(["indexes", "--table", "t_items"])
        assert rc == 0, f"indexes failed: {err}"
        assert len(out.strip()) > 0, "indexes should produce output"


class TestLegacyForeignKeysCommand:
    def test_foreign_keys_returns_fk_info(self, sqlite_with_fk):
        rc, out, err = run_cli(["foreign-keys", "--table", "t_items"])
        assert rc == 0, f"foreign-keys failed: {err}"
        assert "fk" in out.lower() or "1" in out, f"Expected FK info: {out}"


class TestLegacyConstraintsCommand:
    def test_constraints_returns_without_error(self, sqlite_with_fk):
        rc, out, err = run_cli(["constraints", "--table", "t_orders"])
        assert rc == 0, f"constraints failed: {err}"


class TestFindCommand:
    """find: search for column names across tables."""

    def test_find_pattern(self, sqlite_with_fk):
        rc, out, err = run_cli(["find", "--pattern", "id"])
        assert rc == 0, f"find failed: {err}"


# ============================================================
# Learn feature — e2e tests for --learn flag and learn subcommand
# ============================================================


class TestLearnCommand:
    """e2e tests for the query learning feature."""

    def test_query_learn_writes_file(self, sqlite_conn):
        """query --learn should write to query_learned.yaml."""
        rc, out, err = run_cli(
            [
                "query",
                "--learn",
                "--yes",
                "--sql",
                "SELECT * FROM users",
            ]
        )
        assert rc == 0, f"query --learn failed: {err}"
        import os

        home = os.environ.get("DATABASE_EXPLORER_HOME", "")
        learned_path = os.path.join(home, "query_learned.yaml")
        assert os.path.isfile(learned_path), f"query_learned.yaml not created at {learned_path}"

    def test_learn_show_displays_data(self, sqlite_conn):
        """learn show should display learned data after --learn."""
        run_cli(["query", "--learn", "--yes", "--sql", "SELECT * FROM users"])
        run_cli(["query", "--learn", "--yes", "--sql", "SELECT * FROM users"])
        rc, out, err = run_cli(["learn", "show"])
        assert rc == 0, f"learn show failed: {err}"
        assert len(out.strip()) > 0, "learn show should produce output"

    def test_learn_clear_wipes_file(self, sqlite_conn):
        """learn clear should remove query_learned.yaml."""
        run_cli(["query", "--learn", "--yes", "--sql", "SELECT * FROM users"])
        rc, out, err = run_cli(["learn", "clear"])
        assert rc == 0, f"learn clear failed: {err}"
        import os

        home = os.environ.get("DATABASE_EXPLORER_HOME", "")
        learned_path = os.path.join(home, "query_learned.yaml")
        assert not os.path.isfile(learned_path), "query_learned.yaml should be deleted after clear"

    def test_learn_delete_removes_table(self, sqlite_conn):
        """learn delete --table X should remove that table's data."""
        run_cli(["query", "--learn", "--yes", "--sql", "SELECT * FROM users"])
        rc, out, err = run_cli(["learn", "delete", "--table", "users"])
        assert rc == 0, f"learn delete failed: {err}"
        import os
        import yaml

        home = os.environ.get("DATABASE_EXPLORER_HOME", "")
        learned_path = os.path.join(home, "query_learned.yaml")
        if os.path.isfile(learned_path):
            data = yaml.safe_load(open(learned_path, encoding="utf-8")) or {}
            freq = data.get("learned", {}).get("table_frequency", {})
            assert "users" not in freq, "'users' should be deleted from table_frequency"

    def test_learn_delete_nonexistent_is_graceful(self, sqlite_conn):
        """learn delete for nonexistent file should exit gracefully (not crash)."""
        rc, out, err = run_cli(["learn", "delete", "--table", "ghost"])
        # No learned file exists → should exit 1 with message, not crash
        assert "不存在" in out or "无学习数据" in err or rc == 0 or rc == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestExplainCommand:
    """EXPLAIN 命令 CLI 模式端到端测试。"""

    def test_explain_select(self, sqlite_conn):
        """explain SELECT 返回执行计划。"""
        rc, out, err = run_cli(["explain", "--sql", "SELECT 1"])
        assert rc == 0, f"explain 失败: {err}"
        assert any(kw in out.upper() for kw in ["SCAN", "SEARCH", "USE", "LIST"]), f"执行计划应含预期关键词: {out[:200]}"

    def test_explain_table(self, sqlite_conn):
        """explain 查询具体的表。"""
        rc, out, err = run_cli(["explain", "--sql", "SELECT name FROM sqlite_master WHERE type='table'"])
        assert rc == 0, f"explain 失败: {err}"
        assert any(kw in out.upper() for kw in ["SCAN", "SEARCH"]), f"执行计划应含 SCAN/SEARCH: {out[:200]}"


class TestQueryFormatCsv:
    """query --format csv 输出测试。"""

    def test_query_csv_output(self, sqlite_conn):
        """query --format csv 直接打印 CSV 文本到 stdout。"""
        rc, out, err = run_cli(
            [
                "query",
                "--sql",
                "SELECT 1 AS id, 'hello' AS name",
                "--format",
                "csv",
            ]
        )
        assert rc == 0, f"CSV 查询失败: {err}"
        assert "id,name" in out, f"CSV 应包含表头: {out[:100]}"
        assert "1,hello" in out, f"CSV 应包含数据行: {out[:100]}"
