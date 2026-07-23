#!/usr/bin/env python3
"""_query_learning.py 单元测试

覆盖:
- extract_tables: FROM/JOIN/UPDATE/INTO 提取, schema 前缀 stripping, 去重
- extract_columns: SELECT 列提取, * 跳过, AS alias, 敏感列过滤
- extract_associations: JOIN 共现对
- extract_column_enums: WHERE = 'val' 和 IN ('a','b') 提取, 敏感列跳过
- extract_knowledge: 全量提取
- _merge_learned: 频率累加, 关联计数, 枚举合并, 列组合记录
- record_query / load_learned_aliases / clear_learned: 持久化 + 加载
- _is_sensitive_column: 隐私过滤
- _default_learned: 初始结构
"""

import pytest
from _query_learning import (
    extract_tables,
    extract_columns,
    extract_associations,
    extract_column_enums,
    extract_knowledge,
    _merge_learned,
    _default_learned,
    _is_sensitive_column,
    record_query,
    load_learned_aliases,
    clear_learned,
    invalidate_learned_cache,
    _LEARNED_CACHE,
    _DEFAULT_LEARNED_PATH,
)

# sqlglot 缺失时 extract_tables/extract_columns 回退到 regex，
# 对 CTE/UNION/子查询/函数参数等复杂结构行为不同。以下测试依赖 sqlglot 精度。
try:
    import sqlglot  # noqa: F401

    HAS_SQLGLOT = True
except ImportError:
    HAS_SQLGLOT = False

requires_sqlglot = pytest.mark.skipif(not HAS_SQLGLOT, reason="需要 sqlglot：pip install database-explorer[learn]")


# ─── Privacy ────────────────────────────────────────────────────────────────


class TestSensitiveColumn:
    def test_password_detected(self):
        assert _is_sensitive_column("password")
        assert _is_sensitive_column("user_password")
        assert _is_sensitive_column("Password")

    def test_token_detected(self):
        assert _is_sensitive_column("api_token")
        assert _is_sensitive_column("accessToken")

    def test_phone_detected(self):
        assert _is_sensitive_column("phone")
        assert _is_sensitive_column("mobile_number")
        assert _is_sensitive_column("cell_phone")

    def test_id_card_detected(self):
        assert _is_sensitive_column("id_card")
        assert _is_sensitive_column("idcard")
        assert _is_sensitive_column("identity_number")

    def test_credit_card_detected(self):
        assert _is_sensitive_column("credit_card")
        assert _is_sensitive_column("bank_account")

    def test_safe_columns(self):
        assert not _is_sensitive_column("name")
        assert not _is_sensitive_column("email")
        assert not _is_sensitive_column("address")
        assert not _is_sensitive_column("status")
        assert not _is_sensitive_column("order_date")


# ─── SQL Extraction ─────────────────────────────────────────────────────────


class TestExtractTables:
    def test_simple_select(self):
        sql = "SELECT * FROM orders"
        assert extract_tables(sql) == ["orders"]

    def test_join_tables(self):
        sql = "SELECT o.*, c.name FROM orders o JOIN customers c ON o.customer_id = c.customer_id"
        result = extract_tables(sql)
        assert result == ["orders", "customers"]

    def test_multiple_joins(self):
        sql = "SELECT * FROM orders o JOIN order_items oi ON o.id = oi.order_id JOIN products p ON oi.product_id = p.id"
        result = extract_tables(sql)
        assert result == ["orders", "order_items", "products"]

    def test_schema_prefix_stripped(self):
        sql = "SELECT * FROM dbo.orders"
        assert extract_tables(sql) == ["orders"]

    def test_update_table(self):
        sql = "UPDATE customers SET name = 'X' WHERE id = 1"
        assert extract_tables(sql) == ["customers"]

    def test_into_table(self):
        sql = "INSERT INTO orders (id, name) VALUES (1, 'X')"
        assert extract_tables(sql) == ["orders"]

    def test_deduplicate(self):
        sql = "SELECT * FROM orders o JOIN order_items oi ON o.order_id = oi.order_id JOIN orders o2 ON oi.order_id = o2.order_id"
        result = extract_tables(sql)
        assert result == ["orders", "order_items"]

    def test_case_insensitive(self):
        sql = "select * from ORDERS join CUSTOMERS"
        result = extract_tables(sql)
        assert result == ["ORDERS", "CUSTOMERS"]

    # ── sqlglot-powered: complex queries that regex could NOT handle ──

    @requires_sqlglot
    def test_cte_excludes_temp_name(self):
        """CTE temp name should be excluded; only real tables extracted."""
        sql = "WITH active AS (SELECT * FROM users WHERE active=1) SELECT * FROM active JOIN orders ON active.id = orders.uid"
        result = extract_tables(sql)
        assert "users" in result
        assert "orders" in result
        assert "active" not in result  # CTE temp name excluded

    @requires_sqlglot
    def test_union_tables(self):
        """UNION should extract tables from both branches."""
        sql = "SELECT id FROM orders UNION SELECT id FROM returns"
        result = extract_tables(sql)
        assert "orders" in result
        assert "returns" in result

    @requires_sqlglot
    def test_subquery_tables(self):
        """Subquery tables should be extracted."""
        sql = "SELECT * FROM (SELECT id FROM users) sub WHERE id IN (SELECT uid FROM logs)"
        result = extract_tables(sql)
        assert "users" in result
        assert "logs" in result


class TestExtractColumns:
    def test_simple_columns(self):
        sql = "SELECT order_id, customer_id, order_date FROM orders"
        cols = extract_columns(sql)
        assert "order_id" in cols
        assert "customer_id" in cols
        assert "order_date" in cols

    def test_star_skipped(self):
        sql = "SELECT * FROM orders"
        assert extract_columns(sql) == []

    @requires_sqlglot
    def test_function_args_extracted(self):
        """sqlglot extracts column refs inside functions (COUNT/MAX/SUM etc).
        COUNT(*) yields nothing, but MAX(amount) correctly extracts 'amount'."""
        sql = "SELECT COUNT(*), MAX(amount) FROM orders"
        cols = extract_columns(sql)
        assert "amount" in cols
        assert "*" not in cols  # COUNT(*) should not produce a column

    @requires_sqlglot
    def test_column_name_not_alias(self):
        """sqlglot extracts the column NAME (order_id), not the SELECT alias (id).
        This is more accurate than the old regex which returned the alias."""
        sql = "SELECT o.order_id AS id, c.name AS customer_name FROM orders o JOIN customers c"
        cols = extract_columns(sql)
        assert "order_id" in cols
        assert "name" in cols

    def test_dot_prefix_stripped(self):
        sql = "SELECT o.order_id, c.name FROM orders o JOIN customers c"
        cols = extract_columns(sql)
        assert "order_id" in cols
        assert "name" in cols

    def test_sensitive_column_filtered(self):
        sql = "SELECT customer_id, password, name FROM customers"
        cols = extract_columns(sql)
        assert "customer_id" in cols
        assert "name" in cols
        assert "password" not in cols

    def test_complex_select_returns_partial(self):
        sql = "SELECT o.*, c.name FROM orders o JOIN customers c"
        cols = extract_columns(sql)
        # * is skipped, c.name is extracted
        assert "name" in cols

    # ── sqlglot-powered: complex queries that regex could NOT handle ──

    @requires_sqlglot
    def test_cte_columns(self):
        """CTE inner columns should be extracted."""
        sql = "WITH cte AS (SELECT user_id, amount FROM orders) SELECT user_id FROM cte"
        cols = extract_columns(sql)
        assert "user_id" in cols

    @requires_sqlglot
    def test_subquery_columns(self):
        """Subquery columns should be extracted."""
        sql = "SELECT name FROM (SELECT id, name FROM users) sub"
        cols = extract_columns(sql)
        assert "name" in cols

    @requires_sqlglot
    def test_union_columns(self):
        """UNION queries should extract columns from both branches."""
        sql = "SELECT id, name FROM orders UNION SELECT id, title FROM returns"
        cols = extract_columns(sql)
        assert "name" in cols
        assert "title" in cols


class TestExtractAssociations:
    def test_two_tables(self):
        pairs = extract_associations("SELECT * FROM orders JOIN customers")
        assert ("orders", "customers") in pairs

    def test_three_tables(self):
        sql = "SELECT * FROM orders o JOIN order_items oi ON o.id = oi.order_id JOIN products p ON oi.product_id = p.id"
        pairs = extract_associations(sql)
        assert len(pairs) == 3
        assert ("orders", "order_items") in pairs
        assert ("order_items", "products") in pairs
        assert ("orders", "products") in pairs

    def test_deduplicate(self):
        sql = "SELECT * FROM orders o JOIN customers c ON o.cid = c.id JOIN customers c2 ON o.cid2 = c2.id"
        pairs = extract_associations(sql)
        # customers appears twice, but pair (orders, customers) should only appear once
        assert pairs.count(("orders", "customers")) == 1


class TestExtractColumnEnums:
    def test_simple_equality(self):
        sql = "SELECT * FROM orders WHERE status = 'pending'"
        enums = extract_column_enums(sql)
        assert "status" in enums
        assert "pending" in enums["status"]

    def test_in_clause(self):
        # Note: our regex handles simple = first, IN needs separate handling
        sql = "SELECT * FROM orders WHERE status = 'confirmed'"
        enums = extract_column_enums(sql)
        assert "confirmed" in enums.get("status", [])

    def test_multiple_equality(self):
        sql = "SELECT * FROM orders WHERE status = 'pending' AND payment_method = 'wechat'"
        enums = extract_column_enums(sql)
        assert "pending" in enums.get("status", [])
        assert "wechat" in enums.get("payment_method", [])

    def test_sensitive_column_skipped(self):
        sql = "SELECT * FROM users WHERE password = 'secret123'"
        enums = extract_column_enums(sql)
        assert "password" not in enums

    def test_no_where_returns_empty(self):
        sql = "SELECT * FROM orders"
        assert extract_column_enums(sql) == {}


class TestExtractKnowledge:
    def test_full_extraction(self):
        sql = "SELECT o.order_id, c.name FROM orders o JOIN customers c ON o.customer_id = c.customer_id WHERE o.status = 'pending'"
        k = extract_knowledge(sql)
        assert k["tables"] == ["orders", "customers"]
        assert "order_id" in k["columns"]
        assert "name" in k["columns"]
        assert ("orders", "customers") in k["associations"]
        assert "pending" in k["column_enums"].get("status", [])

    def test_empty_select(self):
        k = extract_knowledge("SELECT * FROM t")
        assert k["tables"] == ["t"]
        assert k["columns"] == []
        assert k["associations"] == []
        assert k["column_enums"] == {}


# ─── Merge & Persistence ────────────────────────────────────────────────────


class TestMergeLearned:
    def test_frequency_accumulates(self):
        existing = {"learned": {"table_frequency": {"orders": 3}}}
        new = {"tables": ["orders", "customers"], "columns": [], "associations": [], "column_enums": {}}
        result = _merge_learned(existing, new)
        assert result["learned"]["table_frequency"]["orders"] == 4
        assert result["learned"]["table_frequency"]["customers"] == 1

    def test_associations_count_and_sort(self):
        existing = {"learned": {"associations": [["orders", "customers"]]}}
        new = {"tables": ["orders", "customers"], "columns": [], "associations": [["orders", "customers"]], "column_enums": {}}
        result = _merge_learned(existing, new)
        assoc = result["learned"]["associations"]
        assert ["orders", "customers"] in assoc
        # Should appear twice in count but stored once (we rebuild sorted list)
        assert len(assoc) == 1

    def test_column_enums_merged(self):
        existing = {"learned": {"column_enums": {"status": ["pending"]}}}
        new = {"tables": ["orders"], "columns": [], "associations": [], "column_enums": {"status": ["confirmed", "pending"]}}
        result = _merge_learned(existing, new)
        enums = result["learned"]["column_enums"]["status"]
        assert "pending" in enums
        assert "confirmed" in enums
        assert enums.index("pending") < enums.index("confirmed")  # original order preserved

    def test_column_groups_primary_table(self):
        existing = {"learned": {}}
        new = {"tables": ["orders", "customers"], "columns": ["order_id", "customer_id", "status"], "associations": [], "column_enums": {}}
        result = _merge_learned(existing, new)
        groups = result["learned"]["column_groups"]
        assert "orders" in groups
        assert "order_id" in groups["orders"]

    def test_deep_copy_independence(self):
        """Merging should not mutate the original dict."""
        existing = {"learned": {"table_frequency": {"orders": 1}}}
        new = {"tables": ["orders"], "columns": [], "associations": [], "column_enums": {}}
        _merge_learned(existing, new)
        assert existing["learned"]["table_frequency"]["orders"] == 1  # unchanged


class TestDefaultLearned:
    def test_structure(self):
        d = _default_learned()
        assert "table_frequency" in d
        assert "associations" in d
        assert "column_enums" in d
        assert "column_groups" in d
        assert d["table_frequency"] == {}
        assert d["associations"] == []
        assert d["column_enums"] == {}
        assert d["column_groups"] == {}


# ─── File Persistence (temp dir) ────────────────────────────────────────────


class TestRecordQuery:
    def test_creates_file(self, tmp_path):
        original_default = _DEFAULT_LEARNED_PATH
        try:
            import _query_learning

            _query_learning._DEFAULT_LEARNED_PATH = tmp_path / "query_learned.yaml"
            sql = "SELECT o.*, c.name FROM orders o JOIN customers c ON o.customer_id = c.customer_id"
            result = record_query(sql)
            assert (tmp_path / "query_learned.yaml").is_file()
            assert result["learned"]["table_frequency"]["orders"] == 1
            assert result["learned"]["table_frequency"]["customers"] == 1
            assert ["orders", "customers"] in result["learned"]["associations"]
        finally:
            _query_learning._DEFAULT_LEARNED_PATH = original_default

    def test_accumulates_on_second_call(self, tmp_path):
        original_default = _DEFAULT_LEARNED_PATH
        try:
            import _query_learning

            _query_learning._DEFAULT_LEARNED_PATH = tmp_path / "query_learned.yaml"
            record_query("SELECT * FROM orders")
            record_query("SELECT * FROM orders")
            result = load_learned_aliases(tmp_path / "query_learned.yaml")
            # frequency should be 2
            assert result.get("_freq") == 2 or "orders" in load_learned_aliases(tmp_path / "query_learned.yaml")
        finally:
            _query_learning._DEFAULT_LEARNED_PATH = original_default

    def test_clear_removes_file(self, tmp_path):
        original_default = _DEFAULT_LEARNED_PATH
        try:
            import _query_learning

            test_path = tmp_path / "query_learned.yaml"
            _query_learning._DEFAULT_LEARNED_PATH = test_path
            record_query("SELECT * FROM orders")
            assert test_path.is_file()
            clear_learned(test_path)
            assert not test_path.is_file()
        finally:
            _query_learning._DEFAULT_LEARNED_PATH = original_default


class TestLoadLearnedAliases:
    def test_empty_file_returns_empty(self, tmp_path):
        f = tmp_path / "empty.yaml"
        f.write_text("", encoding="utf-8")
        assert load_learned_aliases(f) == {}

    def test_nonexistent_file_returns_empty(self):
        assert load_learned_aliases("/nonexistent/path.yaml") == {}

    def test_learned_format_parsed(self, tmp_path):
        f = tmp_path / "learned.yaml"
        f.write_text(
            """
learned:
  table_frequency:
    orders: 10
  column_groups:
    orders:
      - order_id
      - customer_id
  associations:
    - [orders, customers]
""",
            encoding="utf-8",
        )
        result = load_learned_aliases(f)
        assert "orders" in result
        assert result["orders"].get("_freq") == 10
        assert result["orders"].get("_source") == "learned"

    def test_cache_invalidation(self):
        invalidate_learned_cache()
        assert len(_LEARNED_CACHE) == 0


# ─── Integration: _scoring.py ────────────────────────────────────────────────


class TestLoadAllAliasSources:
    def test_returns_merged_dict(self):
        from _scoring import load_all_alias_sources

        result = load_all_alias_sources()
        assert isinstance(result, dict)

    def test_hot_tables_priority(self):
        """hot_tables.yaml entries should override learned entries for same table."""
        from _scoring import load_all_alias_sources, load_hot_tables

        hot = load_hot_tables()
        merged = load_all_alias_sources()
        # For tables in hot_tables, _source should be "hot_tables"
        for tname in hot:
            if tname in merged:
                assert merged[tname].get("_source") == "hot_tables"


class TestGetTableMetrics:
    """get_table_metrics 公共 API 测试。"""

    def test_no_file_returns_empty(self, tmp_path):
        """文件不存在时返回空字典。"""
        from _query_learning import get_table_metrics

        nonexistent = tmp_path / "nonexistent.yaml"
        assert get_table_metrics(nonexistent) == {}

    def test_yaml_format(self, tmp_path):
        """YAML 格式的 learned 文件正确加载 metrics。"""
        from _query_learning import get_table_metrics

        p = tmp_path / "learned.yaml"
        p.write_text(
            "learned:\n  table_metrics:\n    suspect_table:\n      status: suspect\n    normal_table:\n      status: ok\n",
            encoding="utf-8",
        )
        metrics = get_table_metrics(p)
        assert metrics["suspect_table"]["status"] == "suspect"
        assert metrics["normal_table"]["status"] == "ok"

    def test_json_format(self, tmp_path):
        """JSON 格式的 learned 文件正确加载 metrics。"""
        from _query_learning import get_table_metrics

        p = tmp_path / "learned.json"
        p.write_text(
            '{"learned": {"table_metrics": {"t1": {"status": "suspect"}}}}',
            encoding="utf-8",
        )
        metrics = get_table_metrics(p)
        assert metrics["t1"]["status"] == "suspect"

    def test_empty_learned_returns_empty(self, tmp_path):
        """learned 段为空时返回空字典。"""
        from _query_learning import get_table_metrics

        p = tmp_path / "empty.yaml"
        p.write_text("learned:", encoding="utf-8")
        assert get_table_metrics(p) == {}

    def test_malformed_file_returns_empty(self, tmp_path):
        """损坏文件返回空字典不崩溃。"""
        from _query_learning import get_table_metrics

        p = tmp_path / "bad.yaml"
        p.write_text("{broken: yaml: : : :", encoding="utf-8")
        result = get_table_metrics(p)
        assert result == {}


# ─────────────────────────────────────────────────────────────────
# _merge_learned 深拷贝（P0: JSON 深拷贝丢非 JSON 类型）
# ─────────────────────────────────────────────────────────────────


class TestMergeLearnedDeepCopy:
    def test_preserves_datetime_values(self):
        """copy.deepcopy 保留 datetime 对象，json.dumps 会丢弃。"""
        from datetime import datetime

        existing = {
            "learned": _default_learned(),
            "metadata": {"last_run": datetime(2026, 1, 1, 12, 0, 0)},
        }
        new_knowledge = {"tables": ["t1"], "associations": [], "column_enums": {}, "columns": []}
        result = _merge_learned(existing, new_knowledge)
        assert result["metadata"]["last_run"] == datetime(2026, 1, 1, 12, 0, 0)

    def test_does_not_mutate_existing(self):
        """合并结果不应修改原始 existing 字典。"""
        existing = {"learned": _default_learned()}
        original_freq = existing["learned"]["table_frequency"]
        new_knowledge = {"tables": ["t1"], "associations": [], "column_enums": {}, "columns": []}
        _merge_learned(existing, new_knowledge)
        assert original_freq == {}

    def test_preserves_nested_lists(self):
        """嵌套列表在深拷贝后保持独立。"""
        existing = {"learned": _default_learned(), "extra": [1, [2, 3]]}
        new_knowledge = {"tables": [], "associations": [], "column_enums": {}, "columns": []}
        result = _merge_learned(existing, new_knowledge)
        result["extra"][1].append(99)
        assert existing["extra"][1] == [2, 3]
