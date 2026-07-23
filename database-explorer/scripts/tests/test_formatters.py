#!/usr/bin/env python3
"""_formatters.py 回归测试：bytes 值序列化修复

覆盖：
- JSONEncoder 能处理 bytes（json/json-compact 不崩溃）
- _to_markdown 对 bytes 输出可读字符串而非 b'...'
- _to_csv 对 bytes 写出合法 CSV（不崩溃）
"""

import json as _json

import pytest
from _formatters import (
    JSONEncoder,
    format_result,
    _to_markdown,
    _to_csv,
    _sanitize_csv_value,
    _to_compact_json,
)


# ─────────────────────────────────────────────────────────────────
# bytes 辅助数据
# ─────────────────────────────────────────────────────────────────

BYTES_ROW = {"id": 1, "data": b"hello bytes", "blob": b"\x00\xff\x80"}
BYTES_RESULT = {
    "success": True,
    "columns": ["id", "data", "blob"],
    "rows": [BYTES_ROW],
}

TEXT_BYTES_ROW = {"id": 1, "text": "用户数据".encode("utf-8")}
TEXT_BYTES_RESULT = {
    "success": True,
    "columns": ["id", "text"],
    "rows": [TEXT_BYTES_ROW],
}


# ─────────────────────────────────────────────────────────────────
# JSONEncoder bytes 处理
# ─────────────────────────────────────────────────────────────────


class TestJSONEncoderBytes:
    def test_utf8_bytes_decoded(self):
        """UTF-8 可解码的 bytes 直接返回字符串。"""
        assert JSONEncoder().default(b"hello") == "hello"

    def test_non_utf8_bytes_fallback_hex(self):
        """非 UTF-8 bytes 回退到十六进制表示。"""
        val = bytes([0x00, 0xFF, 0x80])
        out = JSONEncoder().default(val)
        assert isinstance(out, str)
        assert out == val.hex()

    def test_chinese_utf8_bytes(self):
        """含中文的 UTF-8 bytes 正确解码。"""
        assert JSONEncoder().default("用户数据".encode("utf-8")) == "用户数据"

    def test_decimal_still_works(self):
        import decimal

        assert JSONEncoder().default(decimal.Decimal("3.14")) == 3.14

    def test_datetime_still_works(self):
        from datetime import datetime

        dt = datetime(2024, 1, 1, 12, 0, 0)
        assert JSONEncoder().default(dt) == dt.isoformat()


# ─────────────────────────────────────────────────────────────────
# format_result JSON 路径不崩溃
# ─────────────────────────────────────────────────────────────────


class TestFormatResultErrorByFmt:
    """错误分支按 fmt 分流（M2 修复回归）。

    Agent 在 json-compact 模式下期望结构化错误 {"e": "..."}，
    而非 Markdown 的 **错误**: ...（后者会让 pipe 模式 json.loads 失败）。
    """

    def test_error_json_compact_returns_structured_e(self):
        import json

        result = {"success": False, "error": "连接失败"}
        out = format_result(result, fmt="json-compact")
        data = json.loads(out)
        assert data == {"e": "连接失败"}

    def test_error_json_returns_success_false(self):
        import json

        result = {"success": False, "error": "连接失败"}
        out = format_result(result, fmt="json")
        data = json.loads(out)
        assert data == {"success": False, "error": "连接失败"}

    def test_error_table_returns_markdown(self):
        result = {"success": False, "error": "连接失败"}
        out = format_result(result, fmt="table")
        assert out == "**错误**: 连接失败"

    def test_error_missing_error_field_uses_default(self):
        import json

        out = format_result({"success": False}, fmt="json-compact")
        assert json.loads(out) == {"e": "未知错误"}


class TestFormatResultBytes:
    def test_json_format_with_bytes(self):
        out = format_result(dict(BYTES_RESULT), fmt="json")
        assert "hello bytes" in out
        assert "\\x00" not in out  # 不应出现 b'...' 字面量

    def test_json_compact_format_with_bytes(self):
        out = format_result(dict(BYTES_RESULT), fmt="json-compact")
        import json

        data = json.loads(out)
        assert data["c"] == ["id", "data", "blob"]
        cells = data["r"][0]
        assert cells[1] == "hello bytes"
        assert cells[2] == "00ff80"

    def test_json_compact_with_utf8_bytes(self):
        out = format_result(dict(TEXT_BYTES_RESULT), fmt="json-compact")
        import json

        data = json.loads(out)
        assert data["r"][0][1] == "用户数据"


# ─────────────────────────────────────────────────────────────────
# _to_markdown bytes 可读
# ─────────────────────────────────────────────────────────────────


class TestToMarkdownBytes:
    def test_markdown_non_journal(self):
        out = _to_markdown(dict(BYTES_RESULT))
        assert "hello bytes" in out
        assert "b'" not in out  # 不应出现 bytes 字面量

    def test_markdown_none_preserved_as_empty(self):
        result = {
            "success": True,
            "columns": ["id", "val"],
            "rows": [{"id": 1, "val": None}],
        }
        out = _to_markdown(result)
        assert "| 1 |  |" in out


# ─────────────────────────────────────────────────────────────────
# _to_csv bytes 合法
# ─────────────────────────────────────────────────────────────────


class TestToCsvBytes:
    def test_csv_with_bytes(self):
        out = _to_csv(dict(BYTES_RESULT))
        assert "hello bytes" in out
        assert "b'" not in out

    def test_csv_with_binary_bytes(self):
        out = _to_csv(dict(BYTES_RESULT))
        assert "00ff80" in out


# ─────────────────────────────────────────────────────────────────
# CSV 公式注入防护（P0-1：cmd_export 与 query --format csv 共用此函数）
# ─────────────────────────────────────────────────────────────────


class TestSanitizeCsvValue:
    """CSV 公式注入防护：= / + / - / @ / \\t / \\r 开头的值加单引号前缀。

    防止 Excel/LibreOffice/Google Sheets 打开导出的 CSV 时把
    =cmd|'/c calc'!A1 这类值当作公式执行（远程代码执行）。
    """

    @pytest.mark.parametrize(
        "payload",
        [
            "=cmd|'/c calc'!A1",
            "+1+1",
            "-1+1",
            "@SUM(A1:A2)",
            "\t=cmd",
            "\rcmd",
        ],
    )
    def test_formula_prefix_gets_escaped(self, payload):
        sanitized = _sanitize_csv_value(payload)
        assert sanitized.startswith("'"), f"公式注入载荷未被转义: {payload!r}"
        assert sanitized[1:] == payload

    @pytest.mark.parametrize(
        "safe",
        [
            "normal text",
            "123",
            "",
            None,
            "name with = inside",  # = 不在开头
            "a+b",
        ],
    )
    def test_safe_values_untouched(self, safe):
        sanitized = _sanitize_csv_value(safe)
        assert sanitized == (str(safe) if safe is not None else "")

    def test_none_becomes_empty(self):
        assert _sanitize_csv_value(None) == ""

    def test_to_csv_sanitizes_bytes_formula(self):
        # 端到端：_to_csv 组合 _normalize + _sanitize_csv_value，
        # bytes 公式载荷应先解码再转义（cmd_export 与 query --format csv 共用此路径）
        result = {
            "success": True,
            "columns": ["payload"],
            "rows": [{"payload": b"=evil"}],
        }
        out = _to_csv(result)
        assert "'=evil" in out

    def test_to_csv_applies_sanitization(self):
        # 端到端：_to_csv 对含公式注入载荷的行输出转义后的 CSV
        result = {
            "success": True,
            "columns": ["formula"],
            "rows": [{"formula": "=cmd|'/c calc'!A1"}],
        }
        out = _to_csv(result)
        # CSV 行应为 ',=cmd...'（单引号前缀），而非裸 =cmd
        assert "'=cmd" in out


# ─────────────────────────────────────────────────────────────────
# 语义搜索 json-compact 紧凑格式（P1-6）
# ─────────────────────────────────────────────────────────────────


class TestSemanticCompactJson:
    """explore --semantic / search --semantic 的 json-compact 输出结构。

    _build_semantic_payload 返回 {success, query, matches, total_matched, returned, hint?}，
    之前落入 _to_compact_json 的 else 分支全量输出。修复后应输出紧凑结构
    {n: 命中数, r: [{n,s,c,k,...}], h?: hint}。
    """

    def test_semantic_payload_compact_structure(self):
        payload = {
            "success": True,
            "query": "LES",
            "matches": [
                {
                    "name": "LES_Order",
                    "score": 2.5,
                    "complete": True,
                    "columns": ["id", "name"],
                    "fk_targets": ["Customer"],
                    "via_fk": False,
                    "type": "TABLE",
                }
            ],
            "total_matched": 1,
            "returned": 1,
        }
        out = _to_compact_json(payload)
        parsed = _json.loads(out)
        # 紧凑结构键
        assert set(parsed.keys()) >= {"n", "r"}
        assert parsed["n"] == 1
        item = parsed["r"][0]
        assert item["n"] == "LES_Order"
        assert item["s"] == 2.5
        assert item["k"] is True
        assert item["c"] == ["id", "name"]
        assert item["f"] == ["Customer"]
        assert item["t"] == "TABLE"
        # via_fk=False 是默认值，不应输出（省 token）
        assert "v" not in item

    def test_semantic_payload_with_hint(self):
        payload = {
            "success": True,
            "query": "zzz",
            "matches": [],
            "total_matched": 0,
            "returned": 0,
            "hint": "语义搜索无匹配，可尝试字面兜底。",
        }
        parsed = _json.loads(_to_compact_json(payload))
        assert parsed["n"] == 0
        assert parsed["r"] == []
        assert parsed["h"] == "语义搜索无匹配，可尝试字面兜底。"

    def test_semantic_payload_via_fk_present(self):
        payload = {
            "success": True,
            "matches": [{"name": "T", "score": 1.0, "complete": False, "columns": [], "via_fk": True}],
            "total_matched": 1,
            "returned": 1,
        }
        parsed = _json.loads(_to_compact_json(payload))
        assert parsed["r"][0]["v"] is True

    def test_failed_search_returns_error_key(self):
        # 失败路径不受影响：仍走 {"e": error}
        parsed = _json.loads(_to_compact_json({"success": False, "error": "boom"}))
        assert parsed == {"e": "boom"}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
