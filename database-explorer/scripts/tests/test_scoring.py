#!/usr/bin/env python3
"""_scoring.py 回归测试

覆盖：
- score_table 基础打分（表名、别名、列名匹配）
- score_table 无封顶（>1.0 区分度）
- score_table IDF 加权（高频列被降权）
- load_hot_tables 在 yaml 不可用时的降级行为
- load_hot_tables 通配符别名 + 权重别名
- invalidate_hot_tables_cache 清除缓存
"""

from pathlib import Path


import pytest
from _scoring import (
    score_table,
    load_hot_tables,
    invalidate_hot_tables_cache,
    _fnmatch_to_re,
    _idf_score,
    build_semantic_matches,
)


class TestFnmatchToRe:
    """_fnmatch_to_re 通配符转正则工具函数。"""

    def test_no_wildcard_returns_none(self):
        assert _fnmatch_to_re("exact") is None

    def test_asterisk_matches(self):
        pat = _fnmatch_to_re("sp_*")
        assert pat is not None
        assert pat.search("sp_getusers") is not None
        assert pat.search("sp_getorders") is not None
        assert pat.search("getusers") is None

    def test_question_matches_single(self):
        pat = _fnmatch_to_re("ord?r")
        assert pat is not None
        assert pat.search("order") is not None
        assert pat.search("ordxr") is not None
        assert pat.search("ordxx") is None

    def test_mixed_wildcards(self):
        pat = _fnmatch_to_re("*_get_?")
        assert pat is not None
        assert pat.search("table_get_a") is not None
        # ? matches single char; "ab" = 2 chars, ? matches 'a', 'b' not consumed → match
        assert pat.search("table_get_ab") is not None

    def test_regex_chars_escaped(self):
        # 列名含 () 等特殊字符不应导致 regex 报错
        pat = _fnmatch_to_re("fn(?)")
        assert pat is not None
        # 括号已转义，匹配 fn(?) 字面量
        assert pat.search("fn(?)") is not None


class TestIdfScore:
    """IDF 系数计算。"""

    def test_no_idf_returns_one(self):
        assert _idf_score(0, 10) == 1.0
        assert _idf_score(100, 0) == 1.0

    def test_high_freq_column_low_weight(self):
        # "ID" 出现在 99% 表中 → 系数接近最小值 0.05
        score = _idf_score(100, 99)
        assert 0.04 < score <= 0.05

    def test_medium_freq_column(self):
        # 出现在 50% 表中
        score = _idf_score(100, 50)
        assert 0.4 < score < 0.6

    def test_low_freq_column_full_weight(self):
        # 出现在 1% 表中 → 系数接近 1.0
        score = _idf_score(100, 1)
        assert score > 0.9


class TestScoreTableBasic:
    def test_exact_table_match(self):
        assert score_table("users", "users", []) == 1.0

    def test_word_segment_match(self):
        score = score_table("order", "order_items", [])
        assert score == 0.8

    def test_substring_match(self):
        score = score_table("user", "all_users_log", [])
        assert score == 0.6

    def test_no_match(self):
        assert score_table("xyz", "users", []) == 0.0

    def test_column_exact_match(self):
        # total_tables=0 → 无 IDF 降权
        score = score_table("email", "users", ["id", "name", "email"], total_tables=0)
        assert score == pytest.approx(0.2)

    def test_column_substring_match(self):
        score = score_table("mail", "users", ["id", "name", "email"], total_tables=0)
        assert score == pytest.approx(0.1)

    def test_column_cap_at_06(self):
        score = score_table("id", "users", ["id", "ID", "Id", "iD"], total_tables=0)
        # 4 exact matches (case-insensitive) * 0.2 = 0.8, capped at 0.6
        assert score == pytest.approx(0.6)


class TestScoreTableIdf:
    """IDF 加权：高频列（ID/Name/Status）在大量表中出现时降权。"""

    def test_id_very_common_deweighted(self):
        # "id" 在 100 张表中出现 → 高频降权
        # total_tables=100, column_idf={"id": 100}
        score = score_table("id", "my_special_table", ["id"], column_idf={"id": 100}, total_tables=100)
        # base 0.2 * idf≈0.05 → ≈0.01
        assert score < 0.05

    def test_unique_column_full_weight(self):
        # "custom_token" 只在 1 张表中出现 → 不降权
        score = score_table("token", "my_special_table", ["custom_token"], column_idf={"custom_token": 1}, total_tables=100)
        # base 0.1 * idf≈0.99 → ≈0.1
        assert score > 0.05

    def test_multiple_columns_idf(self):
        # 两列都有，但 id 高频降权，custom_col 稀有保权
        score = score_table("id", "t", ["id", "custom_col"], column_idf={"id": 100, "custom_col": 1}, total_tables=100)
        # id: 0.2*0.05=0.01, custom_col: 不匹配 0 → 仅 id 贡献 ≈0.01
        assert score < 0.05


class TestScoreTableWithAliases:
    def test_alias_exact_match(self):
        score = score_table("客户", "customers", ["id", "name"], aliases=["客户", "买家"])
        assert score == pytest.approx(1.0)

    def test_alias_substring_match(self):
        score = score_table("买", "customers", ["id"], aliases=["买家"])
        assert score == pytest.approx(0.6)

    def test_alias_no_match(self):
        score = score_table("xyz", "customers", [], aliases=["客户", "买家"])
        assert score == 0.0

    def test_alias_weighted(self):
        # 权重 2.0 的别名命中后分数加倍
        # "客户" as query exactly matches alias term "客户" → 1.0 * 2.0 = 2.0
        score = score_table("客户", "other_table", [], aliases=[{"term": "客户", "weight": 2.0}])
        assert score == pytest.approx(2.0)

    def test_alias_wildcard(self):
        # 通配符别名 sp_* 命中 sp_getusers
        # query="sp_getusers" 精确匹配 alias term "sp_*" 的模式
        score = score_table("sp_getusers", "routines", [], aliases=[{"term": "sp_*", "weight": 1.5}])
        # wildcard hits → score = 1.0 * 1.5 = 1.5
        assert score == pytest.approx(1.5)


class TestScoreTableNoCap:
    def test_score_can_exceed_one(self):
        score = score_table("users", "users", ["id", "name", "users"], total_tables=0)
        assert score > 1.0


class TestBuildSemanticMatches:
    """端到端：build_semantic_matches 内置 IDF 计算 + 传递。"""

    def test_idf_builtin_from_tables(self):
        # 两张表，一张含常见列 id，一张含稀有列 custom_token
        tables = {
            "common_table": {"columns": ["id", "name"]},
            "rare_table": {"columns": ["id", "custom_token"]},
        }
        result = build_semantic_matches("id", tables, {}, limit=5)
        rare_score = next((m["score"] for m in result["matches"] if m["name"] == "rare_table"), 0)
        # rare_table 中 "id" 更稀有（2/2 表时降权相同，这里主要看列名组合）
        # 注：列名 "id" 在两张表都出现，频率相同，所以分数差异来自稀有列贡献
        assert rare_score > 0

    def test_skipped_routines_hint(self):
        tables = {}
        result = build_semantic_matches("test", tables, {}, limit=5, skipped_routines=["sp_test"])
        assert "hint" in result
        # hint 说明有被覆盖的同名存储过程/函数
        assert "存储过程" in result["hint"]


class TestLoadHotTables:
    def test_returns_empty_when_yaml_missing(self):
        invalidate_hot_tables_cache()
        result = load_hot_tables(config_path="/nonexistent/path/hot_tables.yaml")
        assert result == {}

    def test_loads_real_file(self):
        invalidate_hot_tables_cache()
        yaml_path = Path(__file__).resolve().parent.parent.parent / "references" / "hot_tables.yaml"
        if yaml_path.is_file():
            result = load_hot_tables(config_path=str(yaml_path))
            assert "customers" in result
            assert "aliases" in result["customers"]

    def test_string_alias_normalized_to_dict(self):
        # 字符串别名在处理后转为 {"term": ..., "weight": 1.0} 格式
        invalidate_hot_tables_cache()
        yaml_path = Path(__file__).resolve().parent.parent.parent / "references" / "hot_tables.yaml"
        if yaml_path.is_file():
            result = load_hot_tables(config_path=str(yaml_path))
            aliases = result["customers"]["aliases"]
            # 字符串别名应转为 dict，含 weight
            for al in aliases:
                if isinstance(al, dict):
                    assert "term" in al
                    assert "weight" in al
                    break

    def test_cache_invalidation(self):
        invalidate_hot_tables_cache()
        load_hot_tables(config_path="/nonexistent/path.yaml")
        result = load_hot_tables(config_path="/nonexistent/path.yaml")
        assert result == {}
        invalidate_hot_tables_cache()
        result2 = load_hot_tables(config_path="/nonexistent/path.yaml")
        assert result2 == {}


class TestBuildSemanticMatchesWithStubTables:
    """Level-1 表级索引（无列数据）下的评分行为。"""

    def test_stub_table_scored_by_name_and_comment(self):
        # stub 表（_stub=True）无 columns，用表名+注释评分
        tables = {
            "order_main": {"comment": "订单主表，记录交易概要", "_stub": True},
            "order_items": {"comment": "订单明细", "_stub": True},
        }
        result = build_semantic_matches("订单", tables, {}, limit=5)
        names = [m["name"] for m in result["matches"]]
        # 表注释含"订单"的表应排名靠前
        assert "order_main" in names
        assert "order_items" in names

    def test_stub_table_complete_flag(self):
        # stub 表无列，complete=True（空列表不截断）
        tables = {
            "t": {"comment": "test", "_stub": True},
        }
        result = build_semantic_matches("test", tables, {}, limit=5)
        assert result["matches"][0]["complete"] is True
        assert result["matches"][0]["columns"] == []

    def test_mixed_stub_and_full_tables(self):
        # 混合索引：stub 表依赖注释，全量表依赖列名
        tables = {
            "order_detail": {
                "comment": "test",
                "columns": ["id", "order_id", "product_name"],
                "column_meta": {},
                "fks": [],
            },
            "misc": {
                "comment": "订单测试表",
                "_stub": True,
            },
        }
        result = build_semantic_matches("订单", tables, {}, limit=5)
        names = [m["name"] for m in result["matches"]]
        # misc 表注释含 "订单" → 命中
        assert "misc" in names
        # order_detail: 注释 "test" 不含"订单"，列名无"订单" → 不匹配
        assert "order_detail" not in names

    def test_idf_computed_only_from_tables_with_columns(self):
        # IDF = 1 - doc_freq/total_tables；id 在 2 张表中出现
        # 当 total_tables=2（仅含 users 和 orders，无 stub）时，IDF = 1-2/2 = 0 → floor 0.05
        # score = 0.2 * 0.05 = 0.01
        tables = {
            "users": {"columns": ["id", "name"], "column_meta": {}, "fks": [], "_stub": False},
            "orders": {"columns": ["id", "user_id"], "column_meta": {}, "fks": [], "_stub": False},
        }
        result = build_semantic_matches("id", tables, {}, limit=5)
        id_score = next((m["score"] for m in result["matches"] if m["name"] == "users"), 0)
        assert id_score < 0.05


class TestFkTransitiveClosure:
    """FK 传递闭包打分：直接匹配表的 FK 关联表也获得传递分。"""

    def test_direct_match_always_wins(self):
        # 直接匹配的分 ≥ 传递分（合并时取 max）
        tables = {
            "orders": {"columns": ["id"], "fks": [{"referred_table": "customers"}], "column_meta": {}, "comment": ""},
            "customers": {"columns": ["id"], "fks": [], "column_meta": {}, "comment": "dummy"},
        }
        result = build_semantic_matches("orders", tables, {}, limit=5)
        scores = {m["name"]: m["score"] for m in result["matches"]}
        # 直接匹配 orders = 1.0，传递 customers = 1.0（1-hop，无衰减）
        assert scores["orders"] >= scores["customers"]

    def test_via_fk_flag_set(self):
        # 仅有传递分的表标记 via_fk=True
        tables = {
            "orders": {"columns": ["id"], "fks": [{"referred_table": "customers"}], "column_meta": {}, "comment": ""},
            "customers": {"columns": ["id"], "fks": [], "column_meta": {}, "comment": ""},
        }
        result = build_semantic_matches("orders", tables, {}, limit=5)
        via_fk = [m["name"] for m in result["matches"] if m.get("via_fk")]
        assert "customers" in via_fk
        assert "orders" not in via_fk

    def test_two_hop_decay(self):
        # 2-hop 传递分 = direct_score * 0.5，3-hop = direct_score * 0.25
        tables = {
            "orders": {"columns": ["id"], "fks": [{"referred_table": "order_items"}], "column_meta": {}, "comment": ""},
            "order_items": {"columns": ["id"], "fks": [{"referred_table": "products"}], "column_meta": {}, "comment": ""},
            "products": {"columns": ["id"], "fks": [], "column_meta": {}, "comment": ""},
        }
        result = build_semantic_matches("orders", tables, {}, limit=5)
        scores = {m["name"]: m["score"] for m in result["matches"]}
        # orders 直接 1.0, order_items 1-hop 1.0, products 2-hop 0.5
        assert scores["orders"] == pytest.approx(1.0)
        assert scores["order_items"] == pytest.approx(1.0)
        assert scores["products"] == pytest.approx(0.5)

    def test_reverse_fk_boost(self):
        # 被直接匹配的表 FK 指向的表也获得传递分（反向关联）
        tables = {
            "orders": {"columns": ["id"], "fks": [{"referred_table": "customers"}], "column_meta": {}, "comment": ""},
            "customers": {"columns": ["id"], "fks": [], "column_meta": {}, "comment": ""},
        }
        result = build_semantic_matches("orders", tables, {}, limit=5)
        names = [m["name"] for m in result["matches"]]
        # customers 被 orders FK 引用（反向），应出现在结果中
        assert "customers" in names

    def test_no_loop_infinite_score(self):
        # 自环/重复 FK 不导致无限循环（visited 集合保护）
        tables = {
            "a": {"columns": ["id"], "fks": [{"referred_table": "b"}], "column_meta": {}, "comment": ""},
            "b": {"columns": ["id"], "fks": [{"referred_table": "a"}], "column_meta": {}, "comment": ""},
        }
        result = build_semantic_matches("a", tables, {}, limit=5)
        names = [m["name"] for m in result["matches"]]
        assert "a" in names
        assert "b" in names
        scores = {m["name"]: m["score"] for m in result["matches"]}
        # b 从 a 传递过来：hop=1 → 1.0；a 从 b 反向传递：hop=1 → 1.0
        # 两者都直接参与了打分，不会无限叠加
        assert scores["a"] == pytest.approx(1.0)
        assert scores["b"] == pytest.approx(1.0)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
