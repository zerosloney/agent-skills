"""结果格式化 - Markdown 表格、JSON、CSV 输出"""

import csv
import io
import json
from datetime import datetime
from uuid import UUID
from decimal import Decimal
from typing import Any


class JSONEncoder(json.JSONEncoder):
    """数据库结果的 JSON 编码器，支持 Decimal / datetime / bytes / UUID"""

    def default(self, obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return float(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, bytes):
            try:
                return obj.decode("utf-8")
            except UnicodeDecodeError:
                return obj.hex()
        if isinstance(obj, UUID):
            return str(obj)
        return super().default(obj)


def format_result(result: dict, fmt: str = "table", title: str = "") -> str:
    """格式化查询结果。

    Args:
        result: 查询结果字典 {"success": bool, "columns": [...], "rows": [...]}
        fmt: 输出格式 (table/json/json-compact/csv)
        title: 可选标题

    Returns:
        格式化后的字符串
    """
    if not result.get("success"):
        err = result.get("error", "未知错误")
        if fmt == "json-compact":
            return json.dumps({"e": err}, ensure_ascii=False)
        if fmt == "json":
            return json.dumps({"success": False, "error": err}, ensure_ascii=False, cls=JSONEncoder)
        return f"**错误**: {err}"

    if fmt == "json":
        return json.dumps(result, ensure_ascii=False, cls=JSONEncoder, indent=2)

    if fmt == "json-compact":
        return _to_compact_json(result)

    if fmt == "csv":
        return _to_csv(result)

    return _to_markdown(result, title)


def _normalize(v: Any) -> Any:
    """将数据库结果中的 bytes / UUID 值转换为可读字符串。"""
    if isinstance(v, bytes):
        try:
            return v.decode("utf-8")
        except UnicodeDecodeError:
            return v.hex()
    if isinstance(v, UUID):
        return str(v)
    return v


def _sanitize_csv_value(v: Any) -> str:
    """防止 CSV 公式注入：对 =/+/-/@/\\t/\\r 开头的值加单引号前缀。"""
    s = str(v) if v is not None else ""
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def _escape_md_cell(v: Any) -> str:
    """转义 Markdown 表格单元格中的管道符和换行符，防止破坏表格结构。"""
    s = str(v) if v is not None else ""
    s = s.replace("|", "\\|")
    s = s.replace("\n", " ")
    s = s.replace("\r", "")
    return s


def _to_markdown(result: dict, title: str = "") -> str:
    """将结果转换为 Markdown 格式"""
    lines = []
    if title:
        lines.append(f"## {title}")

    # 错误
    if not result.get("success"):
        return f"**错误**: {result.get('error', '未知错误')}"

    # 表格结果（rows 是列表，非 None）
    if "columns" in result and isinstance(result.get("rows"), list) and result["columns"]:
        cols = result["columns"]
        rows = result["rows"] or []

        if result.get("total_rows"):
            info = f"返回 {result.get('displayed', len(rows))} 行"
            if result["total_rows"] != result.get("displayed", len(rows)):
                info += f"（共 {result['total_rows']} 行）"
            lines.append(info)
        if result.get("truncated"):
            lines.append("> 结果已截断")

        sep = "| " + " | ".join(["---"] * len(cols)) + " |"
        lines.append("| " + " | ".join(str(c) for c in cols) + " |")
        lines.append(sep)
        for row in rows:
            vals = []
            for c in cols:
                v = row.get(c)
                if v is None:
                    vals.append("")
                else:
                    vals.append(_escape_md_cell(_normalize(v)))
            lines.append("| " + " | ".join(vals) + " |")
        return "\n".join(lines)

    # 搜索结果（表/列列表）
    if result.get("result_type") == "search_tables" and isinstance(result.get("tables"), list):
        items = result["tables"]
        lines.append(f"共 {result.get('count', len(items))} 个表匹配 `{result.get('pattern', '')}`")
        for t in items:
            schema = t.get("TABLE_SCHEMA", "")
            name = t.get("TABLE_NAME", "")
            typ = t.get("TABLE_TYPE", "")
            prefix = f"{schema}." if schema else ""
            lines.append(f"- {prefix}{name}  ({typ})")
        return "\n".join(lines)

    if result.get("result_type") == "search_columns" and isinstance(result.get("columns"), list):
        items = result["columns"]
        lines.append(f"共 {result.get('count', len(items))} 个列匹配 `{result.get('pattern', '')}`")
        for c in items:
            schema = c.get("TABLE_SCHEMA", "")
            table = c.get("TABLE_NAME", "")
            col = c.get("COLUMN_NAME", "")
            dtype = c.get("DATA_TYPE", "")
            prefix = f"{schema}.{table}." if schema else f"{table}."
            lines.append(f"- {prefix}{col}  ({dtype})")
        return "\n".join(lines)

    # 键值对
    for k, v in result.items():
        if k == "success":
            continue
        lines.append(_render_kv(v, k))
    return "\n".join(lines) if lines else ""


def _to_csv(result: dict) -> str:
    """将结果转换为 CSV 格式"""
    cols = result.get("columns", [])
    rows = result.get("rows", [])
    if not cols or not rows:
        return ""
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow({c: _sanitize_csv_value(_normalize(row.get(c, ""))) for c in cols})
    return buf.getvalue()


def _to_compact_json(result: dict) -> str:
    """将结果转换为紧凑 JSON（Agent 模式，最小化 token）。

    格式: {"c":["col1","col2"],"r":[["v1","v2"],...]}
    - c: 列名数组
    - r: 行值数组（每行是值数组，按列序排列）
    - 额外字段: t=total_rows, k=truncated, n=count
    """
    if not result.get("success"):
        return json.dumps({"e": result.get("error", "unknown")}, ensure_ascii=False)

    compact: dict[str, Any] = {}

    if "columns" in result and isinstance(result.get("rows"), list) and result["columns"]:
        cols = result["columns"]
        rows = result["rows"] or []
        compact["c"] = cols
        compact["r"] = [[row.get(c) for c in cols] for row in rows]
        if result.get("total_rows") is not None:
            compact["t"] = result["total_rows"]
        if result.get("truncated"):
            compact["k"] = True
    elif result.get("result_type") == "search_tables" and isinstance(result.get("tables"), list):
        items = result["tables"]
        compact["n"] = result.get("count", len(items))
        compact["r"] = [{"s": t.get("TABLE_SCHEMA", ""), "t": t.get("TABLE_NAME", ""), "y": t.get("TABLE_TYPE", "")} for t in items]
    elif result.get("result_type") == "search_columns" and isinstance(result.get("columns"), list):
        items = result["columns"]
        compact["n"] = result.get("count", len(items))
        compact["r"] = [
            {"s": c.get("TABLE_SCHEMA", ""), "t": c.get("TABLE_NAME", ""), "c": c.get("COLUMN_NAME", ""), "d": c.get("DATA_TYPE", "")}
            for c in items
        ]
    elif isinstance(result.get("matches"), list):
        # 语义搜索载荷（explore --semantic / search --semantic）。
        # _build_semantic_payload 返回 {matches, total_matched, returned, hint?}，
        # 字段缩写沿用现有 compact 风格：n=表名 s=分值 c=列名预览 k=complete 标记
        # t=type f=fk_targets v=via_fk。Agent 据 k 决定是否补查 column --detail full。
        items = result["matches"]
        compact["n"] = result.get("total_matched", len(items))
        rows_out = []
        for m in items:
            item = {
                "n": m.get("name"),
                "s": m.get("score"),
                "c": m.get("columns", []),
                "k": m.get("complete"),
            }
            # 以下为可选字段，仅在存在且非默认值时输出，省 token
            if m.get("type"):
                item["t"] = m.get("type")
            fk = m.get("fk_targets") or []
            if fk:
                item["f"] = fk
            if m.get("via_fk"):
                item["v"] = True
            if m.get("status"):
                item["st"] = m.get("status")
            rows_out.append(item)
        compact["r"] = rows_out
        if result.get("hint"):
            compact["h"] = result["hint"]
    else:
        return json.dumps(result, ensure_ascii=False, cls=JSONEncoder)

    return json.dumps(compact, ensure_ascii=False, cls=JSONEncoder)


def _render_kv(v: object, k: str) -> str:
    if isinstance(v, dict):
        return f"- **{k}**: {json.dumps(v, ensure_ascii=False, cls=JSONEncoder)}"
    if isinstance(v, list):
        return f"- **{k}**: {len(v)} 项"
    if isinstance(v, bool):
        return f"- **{k}**: {'是' if v else '否'}"
    return f"- **{k}**: {v}"
