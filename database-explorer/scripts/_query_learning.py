#!/usr/bin/env python3
"""SQL 查询学习模块 — 从执行过的 SQL 中提取结构化知识。

隐私原则：记录表名、列名、关联关系、非敏感枚举值（如状态、类型）等结构信息。
不记录敏感数据值（密码、手机号、身份证等），敏感列名匹配 _SENSITIVE_COLUMN_PATTERNS
的自动跳过。非敏感列的 WHERE 枚举值（如 status='pending'）会作为结构化知识记录。

存储格式：
    ~/.database-explorer/query_learned.yaml

    learned:
      table_frequency:   # 表访问频率
        orders: 47
        customers: 42
      associations:      # JOIN 共现（强关联）
        - [orders, customers]
        - [orders, order_items]
      column_enums:      # WHERE 条件中的枚举值
        orders.status: [pending, confirmed, shipped, cancelled]
        orders.payment_method: [wechat, alipay, bank_transfer]
      column_groups:     # 常用列组合
        orders: [order_id, customer_id, order_date, status, total_amount]
"""

import json
import logging
import os
import copy
import re
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# 默认存储路径（支持 DATABASE_EXPLORER_HOME 环境变量重定向，用于测试隔离）
_HOME_OVERRIDE = os.environ.get("DATABASE_EXPLORER_HOME")
_DEFAULT_LEARNED_PATH = Path(_HOME_OVERRIDE) if _HOME_OVERRIDE else Path.home() / ".database-explorer"
_DEFAULT_LEARNED_PATH = _DEFAULT_LEARNED_PATH / "query_learned.yaml"

# 质量门槛：表访问频率低于此值的 learned aliases 不参与评分（防止单次探索污染）
MIN_FREQ_FOR_SCORING = 2

# 隐私安全：不记录值的列名模式（密码、密钥、身份证、手机号等）
_SENSITIVE_COLUMN_PATTERNS = re.compile(
    r"(password|pwd|secret|token|key|phone|mobile|id_card|idcard|"
    r"identity|ssn|credit_card|bank_account|salt|hash|cert|cipher)",
    re.IGNORECASE,
)

# SQL 提取正则（轻量规则，不追求完整 parser）
_RE_TABLE = re.compile(
    r"\b(?:FROM|JOIN|INNER\s+JOIN|LEFT\s+JOIN|RIGHT\s+JOIN|"
    r"FULL\s+JOIN|CROSS\s+JOIN|UPDATE|INTO)\s+([A-Za-z_][\w.]*)",
    re.IGNORECASE,
)
_RE_COLUMNS_SELECT = re.compile(r"SELECT\s+(.+?)\s+FROM", re.IGNORECASE | re.DOTALL)
_RE_COLUMN_ALIAS = re.compile(r"(?:AS|alias)\s+(\w+)", re.IGNORECASE)
# WHERE col IN ('a', 'b', 'c') — multi-value enum extraction
_RE_WHERE_ENUM_IN = re.compile(
    r"(\w+)\s+IN\s*\(\s*((?:'[^']+'\s*,?\s*)+)\)",
    re.IGNORECASE,
)
_RE_WHERE_ENUM_SIMPLE = re.compile(r"(\w+)\s*=\s*'([^']+)'", re.IGNORECASE)


# ─── 隐私过滤 ────────────────────────────────────────────────────────────────


def _is_sensitive_column(col_name: str) -> bool:
    """判断列名是否可能包含敏感信息（密码、手机号等）。"""
    base = col_name.split(".")[-1].lower()
    return bool(_SENSITIVE_COLUMN_PATTERNS.search(base))


def _split_top_level_commas(s: str) -> list[str]:
    """按顶层逗号拆分，括号内的逗号不拆。

    用于 regex fallback 路径拆分 SELECT 列列表：
    "a, COUNT(x, y), c" → ["a", " COUNT(x, y)", " c"]。
    """
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(s):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append(s[start:i])
            start = i + 1
    parts.append(s[start:])
    return parts


# ─── SQL 结构提取 (sqlglot AST) ──────────────────────────────────────────────


def _parse_sql(sql: str):
    """Parse SQL with sqlglot, returning None on failure (graceful fallback)."""
    try:
        import sqlglot

        return sqlglot.parse_one(sql)
    except Exception:
        logger.debug("sqlglot failed to parse SQL, falling back to empty", exc_info=True)
        return None


def _get_cte_names(tree) -> set[str]:
    """Extract CTE alias names that should be excluded from real table list."""
    from sqlglot import exp

    return {cte.alias for cte in tree.find_all(exp.CTE) if cte.alias}


def extract_skeleton(sql: str) -> str | None:
    """将 SQL 简化为逻辑骨架（替换具体表名和列名为占位符）。
    例如: SELECT a, b FROM t1 WHERE c = 1 -> SELECT $COL, $COL FROM $TAB WHERE $COL = $VAL
    """
    try:
        import sqlglot
        from sqlglot import exp

        tree = sqlglot.parse_one(sql)
        if not tree:
            return None

        # 定义需要被泛化的节点类型
        def genericize(node):
            if isinstance(node, exp.Table):
                return exp.Identifier(this="$TAB", quoted=False)
            if isinstance(node, exp.Column):
                return exp.Identifier(this="$COL", quoted=False)
            if isinstance(node, (exp.Literal, exp.Number, exp.String)):
                return exp.Literal(this="$VAL")
            return node

        transformed = tree.transform(genericize)
        return transformed.sql()
    except Exception as e:
        logger.debug("Skeleton extraction failed: %s", e)
        return None


def extract_tables(sql: str) -> list[str]:
    """从 SQL 中提取所有真实表名（去重、保留顺序、排除 CTE 临时名）。

    使用 sqlglot AST 解析，支持 CTE、子查询、UNION 等复杂结构。
    解析失败时回退到 regex。
    """
    tree = _parse_sql(sql)
    if tree is not None:
        from sqlglot import exp

        cte_names = _get_cte_names(tree)
        tables: list[str] = []
        seen: set[str] = set()
        for t in tree.find_all(exp.Table):
            name = t.name
            if name and name not in seen and name not in cte_names:
                seen.add(name)
                tables.append(name)
        return tables
    # Fallback: regex
    tables = []
    seen = set()
    for m in _RE_TABLE.finditer(sql):
        name = m.group(1).strip().split(".")[-1]
        if name and name not in seen:
            seen.add(name)
            tables.append(name)
    return tables


def extract_columns(sql: str) -> list[str]:
    """从 SELECT 子句中提取列名（函数参数不拆分、子查询列不混入）。

    隐私过滤：跳过敏感列名。
    使用 sqlglot AST，只取顶层 SELECT 的列引用。
    """
    tree = _parse_sql(sql)
    if tree is not None:
        from sqlglot import exp

        cols: list[str] = []
        seen: set[str] = set()

        def _extract_from_expressions(expressions):
            """从 SELECT 的 expressions 列表中提取列名。"""
            for top_expr in expressions:
                for col in top_expr.find_all(exp.Column):
                    name = col.name
                    if not name or name in seen:
                        continue
                    if _is_sensitive_column(name):
                        continue
                    seen.add(name)
                    cols.append(name)

        # 只取顶层 SELECT 的列引用，排除 WHERE/JOIN/ORDER BY/子查询中的列
        top_expressions = tree.args.get("expressions", [])
        if top_expressions:
            _extract_from_expressions(top_expressions)
        else:
            # UNION/INTERSECT/EXCEPT 等集合操作：从每个分支 SELECT 提取
            for select_node in tree.find_all(exp.Select):
                _extract_from_expressions(select_node.args.get("expressions", []))
        return cols
    # Fallback: regex
    m = _RE_COLUMNS_SELECT.search(sql)
    if not m:
        return []
    cols = []
    seen = set()
    for part in _split_top_level_commas(m.group(1)):
        part = part.strip()
        if part == "*" or re.match(r"\w+\s*\(", part):
            continue
        col = part.split(".")[-1].strip()
        alias_m = _RE_COLUMN_ALIAS.search(part)
        if alias_m:
            col = alias_m.group(1)
        if col and col not in seen and not _is_sensitive_column(col):
            seen.add(col)
            cols.append(col)
    return cols


def extract_associations(sql: str) -> list[tuple[str, str]]:
    """提取 SQL 中的表关联关系（FROM + JOIN 共现对）。

    返回 [(table_a, table_b), ...]，去重。
    """
    tables = extract_tables(sql)
    pairs: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for i in range(len(tables)):
        for j in range(i + 1, len(tables)):
            pair = (tables[i], tables[j])
            if pair not in seen:
                seen.add(pair)
                pairs.append(pair)
    return pairs


def extract_column_enums(sql: str) -> dict[str, list[str]]:
    """从 WHERE 条件中提取列名的枚举值（= 'val' 和 IN ('a', 'b')）。

    隐私过滤：跳过敏感列的枚举值。
    使用 sqlglot AST 精确识别 IN 和 = 表达式。

    Returns:
        {"orders.status": ["pending", "confirmed", ...], ...}
    """
    tree = _parse_sql(sql)
    if tree is not None:
        from sqlglot import exp

        enums: dict[str, list[str]] = {}
        # col IN ('a', 'b', 'c')
        for node in tree.find_all(exp.In):
            col_node = node.this
            if not isinstance(col_node, exp.Column):
                continue
            col = col_node.name
            if _is_sensitive_column(col):
                continue
            key = col.lower()
            if key not in enums:
                enums[key] = []
            for val_node in node.expressions:
                if isinstance(val_node, exp.Literal) and val_node.is_string:
                    val = val_node.this
                    if val not in enums[key]:
                        enums[key].append(val)
        # col = 'val'
        for node in tree.find_all(exp.EQ):
            left, right = node.this, node.expression
            if isinstance(left, exp.Column) and isinstance(right, exp.Literal) and right.is_string:
                col = left.name
                if _is_sensitive_column(col):
                    continue
                key = col.lower()
                if key not in enums:
                    enums[key] = []
                val = right.this
                if val not in enums[key]:
                    enums[key].append(val)
        return enums
    # Fallback: regex
    enums = {}
    for m in _RE_WHERE_ENUM_SIMPLE.finditer(sql):
        col = m.group(1).strip()
        val = m.group(2).strip()
        if _is_sensitive_column(col):
            continue
        key = col.lower()
        if key not in enums:
            enums[key] = []
        if val not in enums[key]:
            enums[key].append(val)
    for m in _RE_WHERE_ENUM_IN.finditer(sql):
        col = m.group(1).strip()
        if _is_sensitive_column(col):
            continue
        key = col.lower()
        if key not in enums:
            enums[key] = []
        for val_m in re.finditer(r"'([^']+)'", m.group(2)):
            val = val_m.group(1)
            if val not in enums[key]:
                enums[key].append(val)
    return enums


def extract_knowledge(sql: str) -> dict[str, Any]:
    """从一条 SQL 中提取全部结构化知识。"""
    tables = extract_tables(sql)
    cols = extract_columns(sql)
    assoc = extract_associations(sql)
    enums = extract_column_enums(sql)
    skel = extract_skeleton(sql)

    return {
        "tables": tables,
        "columns": cols,
        "associations": assoc,
        "column_enums": enums,
        "skeleton": skel,
    }


# ─── 知识持久化 ──────────────────────────────────────────────────────────────


def _default_learned() -> dict[str, Any]:
    return {
        "table_frequency": {},
        "associations": [],
        "column_enums": {},
        "column_groups": {},
        "table_metrics": {},
        "logic_patterns": {},
        "perf_metrics": {},  # {table: {avg_duration: 0.0, max_duration: 0.0, calls: 0}}
    }


def _merge_learned(existing: dict[str, Any], new_knowledge: dict[str, Any], success: bool = True, duration: float = 0.0) -> dict[str, Any]:
    """将新提取的知识合并到已有 learned 数据中，并根据执行结果更新权重和性能画像。"""
    result = copy.deepcopy(existing)  # deep copy preserving all types
    learned = result.setdefault("learned", _default_learned())

    # 表访问频率
    freq = learned.setdefault("table_frequency", {})
    for t in new_knowledge["tables"]:
        freq[t] = freq.get(t, 0) + 1

    # 权重与指标更新 (L2 Feedback Loop)
    metrics = learned.setdefault("table_metrics", {})
    for t in new_knowledge["tables"]:
        m = metrics.setdefault(t, {"success_count": 0, "fail_count": 0, "weight": 1.0, "status": "active"})
        if success:
            m["success_count"] += 1
            m["weight"] = min(2.0, m["weight"] + 0.05)
            m["status"] = "active"
        else:
            m["fail_count"] += 1
            m["weight"] = max(0.1, m["weight"] - 0.2)
            m["status"] = "suspect"

    # 性能画像更新 (L5 Performance Learning)
    perf = learned.setdefault("perf_metrics", {})
    for t in new_knowledge["tables"]:
        p = perf.setdefault(t, {"avg_duration": 0.0, "max_duration": 0.0, "calls": 0})
        p["calls"] += 1
        # 移动平均更新
        p["avg_duration"] = (p["avg_duration"] * (p["calls"] - 1) + duration) / p["calls"]
        p["max_duration"] = max(p["max_duration"], duration)

    # 逻辑模式学习 (L3 Logic Patterns)
    if success and "skeleton" in new_knowledge:
        patterns = learned.setdefault("logic_patterns", {})
        skel = new_knowledge["skeleton"]
        if skel in patterns:
            patterns[skel]["count"] += 1
        else:
            patterns[skel] = {"skeleton": skel, "count": 1, "tables": new_knowledge["tables"], "first_seen": 0}

    # 关联关系（计数）
    assoc = learned.setdefault("associations", [])
    assoc_map: dict[str, int] = {}
    for pair in assoc:
        key = json.dumps(pair, ensure_ascii=False)
        assoc_map[key] = assoc_map.get(key, 0) + 1
    for pair in new_knowledge["associations"]:
        key = json.dumps(pair, ensure_ascii=False)
        assoc_map[key] = assoc_map.get(key, 0) + 1
    learned["associations"] = [json.loads(k) for k, _ in sorted(assoc_map.items(), key=lambda x: -x[1])]

    # 列枚举值（合并去重）
    col_enums = learned.setdefault("column_enums", {})
    for col, vals in new_knowledge["column_enums"].items():
        existing_vals = col_enums.get(col, [])
        for v in vals:
            if v not in existing_vals:
                existing_vals.append(v)
        col_enums[col] = existing_vals

    # 列组合
    col_groups = learned.setdefault("column_groups", {})
    tables_in_sql = new_knowledge["tables"]
    cols = new_knowledge["columns"]
    if tables_in_sql and cols:
        primary = tables_in_sql[0]
        existing_cols = col_groups.get(primary, [])
        for c in cols:
            if c not in existing_cols:
                existing_cols.append(c)
        col_groups[primary] = existing_cols

    return result


def load_learned_aliases(path: str | Path | None = None) -> dict[str, dict]:
    """加载 learned_aliases.yaml，返回 {table_name: {aliases: [...]}, ...} 格式。

    兼容 hot_tables.yaml 的别名格式，使 _scoring.py 可直接合并使用。

    Returns:
        {table_name: {"aliases": [...], "weight": float, ...}, ...}
    """
    p = Path(path) if path else _DEFAULT_LEARNED_PATH
    if not p.is_file():
        return {}

    try:
        text = p.read_text(encoding="utf-8")
        # Detect format by file extension, not file content
        if p.suffix == ".json":
            data = json.loads(text)
        else:
            data = {}
        # 尝试 YAML
        if not data:
            try:
                import yaml

                data = yaml.safe_load(text) or {}
            except ImportError:
                return {}
            except Exception:
                logger.debug("Failed to parse learned aliases at %s", p, exc_info=True)
                return {}
    except Exception:
        return {}

    learned = data.get("learned", {})

    # 从 column_enums 生成别名
    #   orders.status: [pending, confirmed, shipped] → 不生成别名（枚举值不是表名）
    #   但可以作为列语义补充

    # 从 table_frequency 生成别名：频率高的表，表名本身可以作为
    # "高频访问" 的信号传递给 _scoring.py

    # 从 column_groups 生成别名：列名中蕴含的表名信息
    # 质量门槛：只有访问频率 >= MIN_FREQ_FOR_SCORING 的表才生成别名参与评分
    result: dict[str, dict] = {}
    freq = learned.get("table_frequency", {})
    col_groups = learned.get("column_groups", {})

    for table_name, columns in col_groups.items():
        # 质量门槛：低频表不生成别名
        if freq.get(table_name, 0) < MIN_FREQ_FOR_SCORING:
            continue
        # 从列名提取可能的别名：如果列名包含表名的变体
        aliases: list[str] = []
        for col in columns:
            # 例如表名 orders，列名 order_date → 提取 "order" 作为别名候选
            stem = table_name.rstrip("s").rstrip("es")
            if stem and col.lower().startswith(stem.lower()) and col.lower() != table_name.lower():
                candidate = col.replace("_", " ").title()
                if candidate not in aliases:
                    aliases.append(candidate)
        if aliases:
            result[table_name] = {"aliases": aliases, "_source": "learned", "_weight": 0.5}

    # 高频表的表名直接作为"热门"标记（_scoring.py 可读取 _freq 字段）
    # 质量门槛：只有 freq >= MIN_FREQ_FOR_SCORING 的表才进入结果
    for table_name, count in freq.items():
        if count < MIN_FREQ_FOR_SCORING:
            continue
        if table_name in result:
            result[table_name]["_freq"] = count
        else:
            result[table_name] = {"_freq": count, "_source": "learned", "_weight": 0.5}

    return result


def record_query(sql: str, success: bool = True, duration: float = 0.0, path: str | Path | None = None) -> dict[str, Any]:
    """记录一条 SQL 查询到 learned 文件，并更新其成功/失败指标和性能画像。"""
    knowledge = extract_knowledge(sql)
    p = Path(path) if path else _DEFAULT_LEARNED_PATH

    existing: dict[str, Any] = {}
    if p.is_file():
        try:
            import yaml

            existing = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except Exception:
            existing = {}

    merged = _merge_learned(existing, knowledge, success, duration)

    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        import yaml

        p.write_text(yaml.dump(merged, allow_unicode=True, default_flow_style=False), encoding="utf-8")
    except Exception as e:
        logger.warning("Failed to write learned data to %s: %s", p, e)

    return merged


def clear_learned(path: str | Path | None = None) -> None:
    """清除所有学习数据。"""
    p = Path(path) if path else _DEFAULT_LEARNED_PATH
    if p.is_file():
        p.unlink()


def invalidate_learned_cache() -> None:
    """清除 learned 别名缓存（与 hot_tables 缓存联动）。"""
    _LEARNED_CACHE.clear()


def get_table_metrics(path: str | Path | None = None) -> dict[str, dict]:
    """从 learned 文件加载 table_metrics（含状态标记，如 suspect 表）。

    与 load_learned_aliases 共享同一条 learned 文件读取路径，避免 explore_cmds
    内联重复 yaml 加载（修复 TODO 代码债）。

    Args:
        path: 可选自定义路径（测试隔离用），默认 _DEFAULT_LEARNED_PATH

    Returns:
        {table_name: {"status": "suspect", ...}, ...}
        文件不存在或格式错误时返回空字典。
    """
    p = Path(path) if path else _DEFAULT_LEARNED_PATH
    if not p.is_file():
        return {}

    try:
        text = p.read_text(encoding="utf-8")
        if text.startswith("{"):
            data = json.loads(text)
        else:
            import yaml

            data = yaml.safe_load(text) or {}
    except Exception:
        logger.debug("Failed to load table_metrics from %s", p, exc_info=True)
        return {}

    metrics = (data.get("learned", {}) or {}).get("table_metrics", {}) if isinstance(data, dict) else {}
    return metrics if isinstance(metrics, dict) else {}


# ─── 进程内缓存 ──────────────────────────────────────────────────────────────

_LEARNED_CACHE: dict[str, dict] = {}


def get_learned_aliases(path: str | Path | None = None) -> dict[str, dict]:
    """带缓存的 learned 别名加载。"""
    p = Path(path) if path else _DEFAULT_LEARNED_PATH
    cache_key = str(p)
    if cache_key in _LEARNED_CACHE:
        return _LEARNED_CACHE[cache_key]

    result = load_learned_aliases(p)
    _LEARNED_CACHE[cache_key] = result
    return result
