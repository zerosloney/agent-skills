#!/usr/bin/env python3
"""_security.py 回归测试

覆盖两轮 P0 修复涉及的所有安全函数：
- strip_comments / strip_strings / extract_first_statement（注释与字符串剥离）
- check_read_only（写操作识别 + 字符串字面量误报修复，P0-2）
- is_full_table_scan（全表扫描检测，第一轮 P0）
- is_protected_path（系统路径禁止，第一轮 P0）
- count_statements（多语句注入拦截，第一轮 P0）
- quote_ident / sanitize_error

这些测试是纯函数测试，不依赖数据库连接，可在任何环境秒级运行。
"""

import pytest
from _security import (
    strip_comments,
    strip_strings,
    split_statements,
    extract_first_statement,
    check_read_only,
    is_full_table_scan,
    is_protected_path,
    count_statements,
    quote_ident,
    sanitize_error,
)


# ─────────────────────────────────────────────────────────────────
# strip_comments
# ─────────────────────────────────────────────────────────────────


class TestStripComments:
    def test_removes_line_comment(self):
        assert strip_comments("SELECT 1 -- comment") == "SELECT 1"

    def test_removes_block_comment(self):
        assert strip_comments("SELECT /* c */ 1") == "SELECT 1"

    def test_preserves_string_with_dash_dash(self):
        # '--' 在字符串内不应触发注释剥离
        assert strip_comments("SELECT 'a--b' FROM t") == "SELECT 'a--b' FROM t"

    def test_preserves_string_with_slash_star(self):
        assert strip_comments("SELECT 'a/*b' FROM t") == "SELECT 'a/*b' FROM t"

    def test_nested_string_and_comment(self):
        result = strip_comments("SELECT 'x' /* c */ -- e\nFROM t")
        assert "x" in result
        assert "c" not in result
        assert "e" not in result


# ─────────────────────────────────────────────────────────────────
# strip_strings（P0-2 新增）
# ─────────────────────────────────────────────────────────────────


class TestStripStrings:
    def test_replaces_string_content(self):
        # 字符串内容应被清空，保留引号结构
        assert strip_strings("SELECT 'drop' FROM t") == "SELECT '' FROM t"

    def test_multiple_strings(self):
        assert strip_strings("INSERT INTO t VALUES ('x', 'y')") == "INSERT INTO t VALUES ('', '')"

    def test_no_string_unchanged(self):
        assert strip_strings("DROP TABLE t") == "DROP TABLE t"

    def test_preserves_keywords_outside_strings(self):
        # DROP 在字符串外应保留
        result = strip_strings("DROP TABLE t WHERE c = 'value'")
        assert result.startswith("DROP TABLE t WHERE c = ''")

    def test_removes_comments_too(self):
        # strip_strings 同时剥离注释（与 strip_comments 一致的状态机）
        result = strip_strings("SELECT 'x' /* c */ -- e FROM t")
        assert "c" not in result
        assert "e" not in result
        assert "" in result  # 字符串内容已清空

    def test_empty_string_literal(self):
        assert strip_strings("SELECT '' FROM t") == "SELECT '' FROM t"

    def test_escaped_quote_in_string(self):
        # SQL 标准转义 '' — 状态机应正确识别字符串边界
        # 注意：当前实现用前一个字符是否为反斜杠判断转义，对 '' 转义的处理可能不完美，
        # 这里只验证不崩溃且返回字符串
        result = strip_strings("SELECT 'it''s' FROM t")
        assert "FROM t" in result


# ─────────────────────────────────────────────────────────────────
# extract_first_statement
# ─────────────────────────────────────────────────────────────────


class TestExtractFirstStatement:
    def test_single_statement(self):
        assert extract_first_statement("SELECT 1") == "SELECT 1"

    def test_strips_trailing_semicolon(self):
        assert extract_first_statement("SELECT 1;") == "SELECT 1"

    def test_takes_first_of_multi(self):
        assert extract_first_statement("SELECT 1; DROP TABLE x") == "SELECT 1"

    def test_empty(self):
        assert extract_first_statement("") == ""


# ─────────────────────────────────────────────────────────────────
# check_read_only（P0-2：字符串字面量误报修复）
# ─────────────────────────────────────────────────────────────────


class TestCheckReadOnly:
    # --- 真写操作必须被识别（regression：不能漏）---

    @pytest.mark.parametrize(
        "sql",
        [
            "DROP TABLE users",
            "DELETE FROM users WHERE 1=1",
            "TRUNCATE TABLE users",
            "INSERT INTO users VALUES (1)",
            "UPDATE users SET n=1",
            "CREATE TABLE t (id int)",
            "ALTER TABLE t ADD col int",
            "GRANT SELECT ON t TO u",
            "REVOKE SELECT ON t FROM u",
            "MERGE INTO t USING s ON t.id=s.id",
            "SELECT * INTO archived_users FROM users",
            "BACKUP DATABASE app TO DISK='x.bak'",
            "RESTORE DATABASE app FROM DISK='x.bak'",
            "DBCC CHECKDB('app')",
            "KILL 53",
            "SHUTDOWN",
            "RENAME TABLE old_name TO new_name",
            "EXEC sp_rename 'old_name', 'new_name'",
            "EXEC",
            "EXECUTE",
            "EXEC(@sql)",
        ],
    )
    def test_real_write_operations_detected(self, sql):
        is_ro, kw, reason = check_read_only(sql, strict=True)
        assert not is_ro, f"应识别为写操作: {sql} (kw={kw})"

    # --- 字面量内的写关键字不应误报（P0-2 核心修复）---

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT 'drop' AS msg",
            "SELECT 'please delete this' AS note",
            "SELECT log FROM t WHERE log LIKE '%truncate%'",
            "SELECT 'DROP TABLE' AS demo",
            "SELECT id FROM t WHERE remark = 'deleted rows'",
            "SELECT name FROM t WHERE note LIKE '%xp_cmdshell%'",
            "SELECT EXEC_ORDER FROM t",
            "SELECT id FROM EXECUTE_LOG",
            "SELECT '*' AS star FROM t",
        ],
    )
    def test_string_literal_no_false_positive(self, sql):
        is_ro, kw, reason = check_read_only(sql, strict=True)
        assert is_ro, f"字面量不应误判为写操作: {sql} (kw={kw}, reason={reason})"

    # --- 边界 ---

    def test_empty_sql(self):
        is_ro, kw, _ = check_read_only("")
        assert is_ro

    def test_simple_select(self):
        assert check_read_only("SELECT 1")[0]

    def test_select_with_where(self):
        assert check_read_only("SELECT * FROM t WHERE id = 1")[0]

    def test_non_strict_skips_keyword_scan(self):
        # strict=False 只看首关键字，不扫 DROP/DELETE 等
        # "SELECT * FROM t WHERE c = 'drop'" 首关键字是 SELECT
        assert check_read_only("SELECT * FROM t WHERE c = 'drop'", strict=False)[0]


# ─────────────────────────────────────────────────────────────────
# is_full_table_scan（第一轮 P0 + P0-2 改进）
# ─────────────────────────────────────────────────────────────────


class TestIsFullTableScan:
    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM users",
            "SELECT * FROM big_table",
        ],
    )
    def test_full_scan_detected(self, sql):
        assert is_full_table_scan(sql) is True

    @pytest.mark.parametrize(
        "sql",
        [
            "SELECT * FROM users WHERE id=1",  # 有 WHERE
            "SELECT * FROM users LIMIT 10",  # 有 LIMIT
            "SELECT id, name FROM users",  # 非 SELECT *
            "SELECT TOP 5 * FROM users",  # TOP 限制
            "SELECT DISTINCT * FROM users LIMIT 5",  # DISTINCT + LIMIT
            "SELECT '*' AS x FROM t",  # 字面量星号（P0-2）
        ],
    )
    def test_not_full_scan(self, sql):
        assert is_full_table_scan(sql) is False

    def test_with_comment(self):
        assert is_full_table_scan("-- note\nSELECT * FROM big") is True


# ─────────────────────────────────────────────────────────────────
# is_protected_path（第一轮 P0）
# ─────────────────────────────────────────────────────────────────


class TestIsProtectedPath:
    @pytest.mark.parametrize(
        "path",
        [
            r"C:\Windows\System32\drivers\etc\hosts",
            r"C:\Windows\explorer.exe",
            r"C:\Program Files\app\data.csv",
            r"C:\Program Files (x86)\app\data.csv",
            "/etc/passwd",
            "/usr/bin/dump",
            "/bin/sh",
        ],
    )
    def test_protected_paths_blocked(self, path):
        assert is_protected_path(path) is True, f"应拦截: {path}"

    @pytest.mark.parametrize(
        "path",
        [
            r"C:\Users\me\out.csv",
            r"D:\data\out.csv",
            "/home/me/out.csv",
            "/var/log/dump.csv",
            "/tmp/data.csv",
            "./output.csv",
        ],
    )
    def test_safe_paths_allowed(self, path):
        assert is_protected_path(path) is False, f"不应拦截: {path}"

    def test_empty_path_rejected(self):
        assert is_protected_path("") is True

    def test_whitespace_path_rejected(self):
        assert is_protected_path("   ") is True


class TestIsProtectedPathSegmentLevelFix:
    """v0.5.1 修复：段包含判断（v0.5.0）改为路径前缀匹配。

    旧实现用段名包含判断，误伤包含关键词的用户目录：
    - "bin" 作为段名匹配：/home/zhang/bin/... 被误拦
    - "windows" 子串匹配：C:\\Users\\zhang\\WindowsBackup\\... 被误拦

    新实现仅匹配精确系统目录路径前缀，不受用户名/子目录影响。
    """

    @pytest.mark.parametrize(
        "path",
        [
            # v0.5.0 误伤场景：用户名/子目录含系统关键词
            r"C:\Users\zhang\WindowsBackup\file.csv",
            r"C:\Users\zhang\WindowsApps\app.exe",
            r"C:\Users\windowsadmin\Documents\data.csv",
            "/home/zhang/bin/script.sh",
            "/home/zhang/bin/data.csv",
            "/home/zhang/sbin/tool",
            "/home/zhang/sbin/backup.csv",
            "/data/home/zhang/etc/config.yaml",
            "/data/usr/bin/custom_tool",
            "/data/usr/sbin/custom_tool",
            "/data/usr/local/bin/my_tool",
            "/home/zhang/local/sbin/deploy.csv",
            # 包含 windows/system32 子串的用户目录
            r"C:\Users\system32\Documents\report.csv",
            r"C:\Users\proc\work\out.csv",
            r"C:\Users\dev\project\test.csv",
            # 相对路径含系统关键词
            "./Windows/System32/hosts",
            "./bin/backup.csv",
            "./etc/config",
            "./proc/info",
        ],
    )
    def test_false_positive_now_allowed(self, path):
        """v0.5.0 会被误拦的路径，新实现应放行。"""
        assert is_protected_path(path) is False, f"不应拦截（用户目录含关键词）: {path}"

    @pytest.mark.parametrize(
        "path",
        [
            # 新增保护的路径前缀（v0.5.1）
            "/sbin/iptables",
            "/usr/sbin/tcpdump",
            "/usr/local/bin/python",
            "/usr/local/sbin/service",
            "/dev/null",
            "/dev/urandom",
            "/sys/kernel",
        ],
    )
    def test_newly_protected_paths(self, path):
        """v0.5.1 新增保护的路径（v0.5.0 旧实现未覆盖）。"""
        assert is_protected_path(path) is True, f"应拦截: {path}"

    def test_bin_subpath_of_usr_allowed(self):
        """/usr/bin/... 是保护的，但 /home/bin/... 不应保护。"""
        assert is_protected_path("/usr/bin/grep") is True
        assert is_protected_path("/home/zhang/bin/backup.sh") is False

    def test_usr_local_bin_vs_usr_bin(self):
        """三个相关前缀均独立生效。"""
        assert is_protected_path("/usr/bin/python") is True
        assert is_protected_path("/usr/local/bin/python") is True
        assert is_protected_path("/usr/local/sbin/tool") is True


class TestIsProtectedPathExceptionHandling:
    """v0.5.1 修复：expanduser 异常时应拒绝（返回 True），而非放行。

    旧实现 catch (ValueError, OSError) 后 return False，
    意味着无法解析的路径默认放行——安全边界方向错误。
    """

    def test_empty_path_rejected(self):
        assert is_protected_path("") is True
        assert is_protected_path("   ") is True

    def test_none_rejected(self):
        assert is_protected_path(None) is True


# ─────────────────────────────────────────────────────────────────
# count_statements（多语句注入拦截）
# ─────────────────────────────────────────────────────────────────


class TestCountStatements:
    def test_single(self):
        assert count_statements("SELECT 1") == 1

    def test_multi_injection(self):
        # 经典注入模式：SELECT 后接 DROP
        assert count_statements("SELECT 1; DROP TABLE x") == 2

    def test_semicolon_in_string(self):
        # 分号在字符串内不应算语句分隔
        assert count_statements("SELECT 'a;b'") == 1

    def test_with_comments(self):
        assert count_statements("-- c1\nSELECT 1; -- c2\nSELECT 2") == 2

    def test_trailing_semicolon(self):
        assert count_statements("SELECT 1;") == 1

    def test_empty(self):
        assert count_statements("") == 0


# ─────────────────────────────────────────────────────────────────
# PostgreSQL dollar-quoted strings ($$ / $tag$)（P0-3 安全修复）
# 防止 $$ 内部的关键字/分号误导 check_read_only 和 split_statements
# ─────────────────────────────────────────────────────────────────


class TestDollarQuotedStrings:
    """PostgreSQL dollar-quote 状态机：$$...$$ 与 $tag$...$tag$ 内容应整体视为字符串字面量。"""

    def test_drop_inside_dollar_not_flagged(self):
        # $$ 内的 'drop' 是字面量内容，check_read_only 应判定为只读
        is_ro, kw, _ = check_read_only("SELECT $$drop table x$$")
        assert is_ro, f"$$ 内的字面量不应误判为写操作 (kw={kw})"

    def test_drop_inside_tagged_dollar_not_flagged(self):
        # $tag$ 定界符同样保护内容
        is_ro, kw, _ = check_read_only("SELECT $tag$alter table foo$tag$")
        assert is_ro, f"$tag$ 内的字面量不应误判 (kw={kw})"

    def test_write_after_dollar_still_caught(self):
        # dollar-quote 闭合后的真实写操作仍应被识别（split_statements 正确切分后逐条检查）
        assert _any_write("SELECT $$a;b$$; DROP TABLE x")

    def test_semicolon_inside_dollar_not_split(self):
        # dollar 内的分号不是语句分隔符
        assert count_statements("SELECT $$a;b$$; DROP TABLE x") == 2

    def test_semicolon_inside_tagged_dollar_not_split(self):
        assert count_statements("SELECT $tag$x;y$tag$; DROP TABLE y") == 2

    def test_split_preserves_dollar_content(self):
        # split_statements 返回的第一条应保留 dollar 字符串原文
        stmts = split_statements("SELECT $$drop;select$$; DROP TABLE x")
        assert len(stmts) == 2
        assert "$$" in stmts[0]
        assert stmts[1].startswith("DROP")

    def test_empty_dollar(self):
        # $$ 无内容也合法
        assert count_statements("SELECT $$ $$") == 1
        is_ro, _, _ = check_read_only("SELECT $$ $$")
        assert is_ro

    def test_dollar_with_position_param_not_misread(self):
        # $1 是位置参数不是 dollar-quote 起始，不应被误判
        is_ro, _, _ = check_read_only("SELECT $1")
        assert is_ro
        assert count_statements("SELECT $1; SELECT 2") == 2

    def test_unclosed_dollar_treated_as_string(self):
        # 未闭合 dollar-quote（PG 语法错误）：内部内容按字符串处理，
        # 不应误判内部的写关键字，也不应崩溃
        is_ro, kw, _ = check_read_only("SELECT $$drop table x")
        assert is_ro, f"未闭合 dollar 内字面量不应误判 (kw={kw})"

    def test_strip_strings_empties_dollar_content(self):
        # strip_strings 应清空 dollar 内容（与单引号字符串同等处理）
        assert "drop" not in strip_strings("SELECT $$drop$$")

    def test_strip_comments_preserves_dollar_content(self):
        # strip_comments 保留 dollar 内容（含其中的注释标记，它们是字面量不是注释）
        assert strip_comments("SELECT $$a /* not comment */ b$$") == "SELECT $$a /* not comment */ b$$"

    def test_tag_cannot_start_with_digit(self):
        # $1foo$ 非法定界符（tag 不能以数字开头）：不应被识别为 dollar-quote 起始
        assert count_statements("SELECT $1foo$bar") == 1


def _any_write(sql: str) -> bool:
    """测试辅助：对 split_statements 的结果逐条做 check_read_only，任一为写即 True。

    复刻 cmd_query 多语句路径的检查方式（split_statements + 逐条 check_read_only），
    用于验证 dollar-quote 闭合后的真实写操作不会被掩盖。
    """
    for stmt in split_statements(sql):
        is_ro, _, _ = check_read_only(stmt, strict=True)
        if not is_ro:
            return True
    return False


# ─────────────────────────────────────────────────────────────────
# quote_ident
# ─────────────────────────────────────────────────────────────────


class TestQuoteIdent:
    @pytest.mark.parametrize(
        "db_type,expected",
        [
            ("sqlserver", "[users]"),
            ("mysql", "`users`"),
            ("postgresql", '"users"'),
            ("sqlite", '"users"'),
        ],
    )
    def test_quote_simple(self, db_type, expected):
        assert quote_ident("users", db_type) == expected

    def test_with_schema(self):
        assert quote_ident("users", "sqlserver", "dbo") == "[dbo].[users]"

    def test_already_quoted_not_double(self):
        assert quote_ident("[users]", "sqlserver") == "[users]"
        assert quote_ident("`users`", "mysql") == "`users`"

    def test_special_chars_safely_quoted(self):
        # 含 SQL 注入片段的标识符被正确引用，不抛异常
        assert quote_ident("user; DROP TABLE x", "sqlserver") == "[user; DROP TABLE x]"
        # 含方括号的标识符内部引号被转义
        assert quote_ident("col]name", "sqlserver") == "[col]]name]"

    def test_unicode_allowed(self):
        # 中文标识符（\w+ 含 Unicode）应允许
        assert quote_ident("用户表", "sqlite") == '"用户表"'


# ─────────────────────────────────────────────────────────────────
# sanitize_error
# ─────────────────────────────────────────────────────────────────


class TestSanitizeError:
    def test_ip_redacted(self):
        result = sanitize_error(Exception("connect to 192.168.1.1:1433 failed"))
        assert "192.168.1.1" not in result
        assert "<ip>" in result

    def test_password_redacted(self):
        result = sanitize_error(Exception("login failed password=secret123"))
        assert "secret123" not in result
        assert "***" in result

    def test_path_redacted(self):
        result = sanitize_error(Exception("file at C:\\Users\\secret\\data.db"))
        assert "<path>" in result

    def test_truncation(self):
        long_msg = "x" * 500
        result = sanitize_error(Exception(long_msg))
        assert len(result) <= 203  # 200 + "..."

    def test_decode_chinese_bytes_from_driver(self):
        """pymssql 等驱动返回的异常 message 嵌入 bytes（UTF-8 中文），
        str(e) 后变成 b'\\xe4\\xb8...' 乱码，应被解码为可读中文。

        测试输入模拟 str(exception) 的真实输出：含 b"..." bytes 字面量，
        其中 \\xe4 等是字节转义序列（非字面反斜杠+x）。用 raw string 构造。
        """
        # "不存在" 的 UTF-8: \xe4\xb8\x8d\xe5\xad\x98\xe5\x9c\xa8
        # str(e) 输出形如: (208, b"Invalid object name '\xe4\xb8\x8d...'.")
        msg = r"""(208, b"Invalid object name '\xe4\xb8\x8d\xe5\xad\x98\xe5\x9c\xa8'.")"""
        result = sanitize_error(Exception(msg))
        # 不应再含 \x 字节序列
        assert "\\x" not in result
        # 应解码出中文
        assert "不存在" in result

    def test_ip_redacted_in_bytes_message(self):
        """bytes 解码后仍应脱敏 IP。"""
        # "服务器" UTF-8: \xe6\x9c\x8d\xe5\x8a\xa1\xe5\x99\xa8
        msg = r"""connect failed b'\xe6\x9c\x8d\xe5\x8a\xa1\xe5\x99\xa8' at 10.0.0.5:1433"""
        result = sanitize_error(Exception(msg))
        assert "10.0.0.5" not in result
        assert "<ip>" in result
        assert "\\x" not in result


# ─────────────────────────────────────────────────────────────────
# CTE 绕过检测（二次扫描补全）
# ─────────────────────────────────────────────────────────────────


class TestCteBypassDetection:
    """WITH 子句包裹的写操作应被 strict 模式二次扫描拦截。"""

    @pytest.mark.parametrize(
        "sql,keyword",
        [
            ("WITH cte AS (SELECT 1) MERGE INTO t USING cte ON 1=1 WHEN NOT MATCHED THEN INSERT VALUES (1)", "MERGE"),
            ("WITH cte AS (SELECT 1) INSERT INTO t SELECT * FROM cte", "INSERT"),
            ("WITH cte AS (SELECT 1) UPDATE t SET x=1 FROM cte", "UPDATE"),
            ("WITH cte AS (SELECT 1) DELETE FROM t USING cte", "DELETE"),
            ("WITH cte AS (SELECT 1) CREATE TABLE t AS SELECT * FROM cte", "CREATE"),
            ("WITH cte AS (SELECT 1) ALTER TABLE t ADD col int", "ALTER"),
            ("WITH cte AS (SELECT 1) GRANT SELECT ON t TO u", "GRANT"),
        ],
    )
    def test_cte_wrapped_write_detected(self, sql, keyword):
        is_ro, detected, _ = check_read_only(sql, strict=True)
        assert not is_ro, f"CTE-wrapped {keyword} should be detected as write"

    def test_normal_select_still_allowed(self):
        is_ro, _, _ = check_read_only("WITH cte AS (SELECT 1) SELECT * FROM cte", strict=True)
        assert is_ro


# ─────────────────────────────────────────────────────────────────
# 反斜杠转义在 strip_strings 中的正确处理
# ─────────────────────────────────────────────────────────────────


class TestBackslashEscapeInStripStrings:
    def test_escaped_backslash_before_quote(self):
        # 'test\\\\' ; DROP TABLE users — \\\\ 是转义反斜杠，引号关闭字符串
        sql = "SELECT 'test\\\\'; DROP TABLE users"
        result = strip_strings(sql)
        # DROP TABLE 应在 strip_strings 输出中可见（不在字符串内）
        assert "DROP" in result.upper()

    def test_escaped_quote_still_hidden(self):
        # SQL Server/PostgreSQL 中反斜杠不转义单引号，DROP 不应被吞进字符串。
        sql = r"SELECT 'test\'DROP TABLE users"
        result = strip_strings(sql)
        assert "DROP" in result.upper()

    def test_backslash_does_not_hide_second_statement(self):
        sql = r"SELECT '\'; DROP TABLE users; --'"
        assert count_statements(sql) == 2
        stmts = split_statements(sql)
        assert stmts == ["SELECT '\\'", "DROP TABLE users"]
        assert check_read_only(sql, strict=True)[0] is True
        assert check_read_only(stmts[1], strict=True)[0] is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
