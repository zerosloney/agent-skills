#!/usr/bin/env python3
"""语义搜索评分工具 + hot_tables.yaml 别名加载。"""

import logging
import os
import re
from collections import deque
from pathlib import Path
from _vector_store import index_schema, search_semantic_vectors

logger = logging.getLogger(__name__)

# hot_tables.yaml 的进程内缓存，按配置路径隔离。
_HOT_TABLES_CACHE: dict[str, dict[str, dict]] = {}

# hot_tables.yaml 的查找路径（按优先级）
_SEARCH_PATHS = [
    Path(__file__).resolve().parent.parent / "references" / "hot_tables.yaml",  # scripts/../references/
]
SEMANTIC_PREVIEW_COLS = 30


def _fnmatch_to_re(pattern: str) -> re.Pattern | None:
    """将 fnmatch 风格的通配符模式（* ?）转为预编译正则。

    支持：
      *    → 任意字符序列
      ?    → 单个任意字符
      [abc] → 字符类（保留）
    对列名中有特殊 regex 字符（()-+.^$|{}[]\\）做转义，
    仅将 * ? [ 视为通配符原义处理（[, ] 字符类在列名中罕见）。

    若模式不含 * ? 则返回 None（走精确匹配）。
    """
    if "*" not in pattern and "?" not in pattern:
        return None
    escaped = re.escape(pattern)
    # re.escape 把 * ? 也转了，手动还原为通配符
    escaped = escaped.replace(r"\*", ".*").replace(r"\?", ".")
    return re.compile(escaped, re.IGNORECASE)


def load_hot_tables(config_path: str | Path | None = None) -> dict[str, dict]:
    """加载 hot_tables.yaml 别名配置，返回 {table_name: {aliases: [...], ...}} 字典。

    支持三种别名格式（向后兼容）：
      - 字符串:  "物料"          → 精确匹配，权重 1.0
      - 对象(权重):  {term: "物料", weight: 2.0}
      - 对象(组):    {term: "库存", group: "仓储"}
      - 对象(通配符): {term: "sp_*", weight: 1.5}  → * ? 预编译为正则

    带进程内缓存：首次调用读文件，后续直接返回。
    yaml 未安装或文件不存在时静默返回空字典。
    """
    paths_to_try = [Path(config_path)] if config_path else _SEARCH_PATHS
    cache_key = str(paths_to_try[0]) if len(paths_to_try) == 1 else "|".join(str(p) for p in paths_to_try)
    if cache_key in _HOT_TABLES_CACHE:
        return _HOT_TABLES_CACHE[cache_key]

    try:
        import yaml
    except ImportError:
        logger.debug("PyYAML not installed, hot_tables.yaml aliases disabled")
        _HOT_TABLES_CACHE[cache_key] = {}
        return _HOT_TABLES_CACHE[cache_key]

    for path in paths_to_try:
        if path.is_file():
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
                raw = data.get("hot_tables", {})
                # 预处理别名：标准化 + 预编译通配符
                processed: dict[str, dict] = {}
                for tname, tcfg in raw.items():
                    if isinstance(tcfg, dict):
                        aliases_raw = tcfg.get("aliases", [])
                        aliases_out: list[dict] = []
                        for al in aliases_raw:
                            if isinstance(al, dict):
                                # 对象格式：{term, weight?, group?}
                                term = al.get("term", "")
                                if not term:
                                    continue
                                entry: dict = {"term": term, "weight": al.get("weight", 1.0)}
                                if al.get("group"):
                                    entry["group"] = al["group"]
                                # 预编译通配符
                                pat = _fnmatch_to_re(term)
                                if pat:
                                    entry["_compiled"] = pat
                                aliases_out.append(entry)
                            elif isinstance(al, str):
                                # 字符串格式：预编译通配符，权重 1.0
                                entry: dict = {"term": al, "weight": 1.0}
                                pat = _fnmatch_to_re(al)
                                if pat:
                                    entry["_compiled"] = pat
                                aliases_out.append(entry)
                        processed[tname] = {**tcfg, "aliases": aliases_out}
                    else:
                        processed[tname] = tcfg
                _HOT_TABLES_CACHE[cache_key] = processed
                logger.debug(
                    "Loaded hot_tables.yaml from %s (%d tables, %d alias entries)",
                    path,
                    len(processed),
                    sum(len(v.get("aliases", [])) for v in processed.values()),
                )
                return processed
            except Exception:
                logger.debug("Failed to parse hot_tables.yaml at %s", path, exc_info=True)

    _HOT_TABLES_CACHE[cache_key] = {}
    return _HOT_TABLES_CACHE[cache_key]


def invalidate_hot_tables_cache() -> None:
    """清除 hot_tables.yaml 缓存（pipe 模式下连接切换时调用）。"""
    _HOT_TABLES_CACHE.clear()


def invalidate_all_caches() -> None:
    """清除所有别名缓存（hot_tables + learned + vector index）。pipe 模式连接切换时调用。"""
    invalidate_hot_tables_cache()
    try:
        from _vector_store import invalidate_index_cache

        invalidate_index_cache()
    except ImportError:
        pass
    try:
        from _query_learning import invalidate_learned_cache

        invalidate_learned_cache()
    except ImportError:
        pass


def load_all_alias_sources(cfg: dict | None = None) -> dict[str, dict]:
    """加载全部别名源并合并（Layer 1 > Layer 2 > Layer 3）。

    合并顺序（优先级从高到低）:
        Layer 1: hot_tables.yaml (人工)
        Layer 2: learned_aliases.yaml (SQL 查询学习)
        Layer 3: query_learned.yaml 中的 column_groups 推导

    同一表名冲突时，人工条目的别名优先保留。

    Returns:
        {table_name: {"aliases": [...], "_source": "hot_tables"|"learned", ...}, ...}
    """
    # Layer 1: 人工维护
    hot_path = hot_tables_path_for_config(cfg) if cfg else None
    hot = load_hot_tables(hot_path)

    # Layer 2.5: SQL 查询学习
    try:
        from _query_learning import get_learned_aliases

        learned = get_learned_aliases()
    except ImportError:
        learned = {}

    # 合并：Layer 1 优先（人工 override）
    merged = {**learned, **hot}

    # 标记来源（用于调试）
    for tname in hot:
        if tname in merged:
            merged[tname]["_source"] = "hot_tables"
    for tname in learned:
        if tname in merged and "_source" not in merged[tname]:
            merged[tname]["_source"] = "learned"

    return merged


def hot_tables_path_for_config(cfg: dict) -> Path | None:
    """返回连接级 hot_tables 覆盖路径；未配置时返回 None 使用全局默认。"""
    explicit = cfg.get("hot_tables_path") or cfg.get("hot_tables")
    if explicit:
        return Path(explicit)
    conn_name = cfg.get("_name")
    if not conn_name:
        return None
    home = os.environ.get("DATABASE_EXPLORER_HOME")
    base = Path(home) if home else Path.home() / ".database-explorer"
    candidate = base / "hot_tables" / f"{conn_name}.yaml"
    return candidate if candidate.is_file() else None


def _match_name(query_lower: str, target_lower: str) -> float:
    """对单个名称做匹配打分，返回得分或 0.0。"""
    if query_lower == target_lower:
        return 1.0
    if query_lower in target_lower.split("_") or target_lower in query_lower.split("_"):
        return 0.8
    if query_lower in target_lower or target_lower in query_lower:
        return 0.6
    return 0.0


def _match_text(query_lower: str, target_lower: str) -> float:
    if not target_lower:
        return 0.0
    if query_lower == target_lower:
        return 1.0
    if query_lower in target_lower:
        return 0.8
    score = 0.0
    for word in query_lower.replace("_", " ").split():
        if len(word) >= 2 and word in target_lower:
            score += 0.2
    return min(score, 0.6)


def _type_alias_score(query_lower: str, data_type: str) -> float:
    dtype = data_type.lower()
    if not dtype:
        return 0.0
    aliases = {
        "date": ("date", "time", "日期", "时间"),
        "time": ("date", "time", "日期", "时间"),
        "datetime": ("date", "time", "日期", "时间"),
        "timestamp": ("date", "time", "日期", "时间"),
        "int": ("数量", "编号", "数字", "number", "count"),
        "decimal": ("金额", "价格", "数量", "number", "amount", "price"),
        "numeric": ("金额", "价格", "数量", "number", "amount", "price"),
        "varchar": ("名称", "文本", "备注", "name", "text"),
        "nvarchar": ("名称", "文本", "备注", "name", "text"),
        "text": ("名称", "文本", "备注", "name", "text"),
    }
    for type_key, terms in aliases.items():
        if type_key in dtype and any(term in query_lower for term in terms):
            return 0.05
    return 0.0


def _idf_score(idf_table: int, column_doc_freq: int) -> float:
    """计算列名 IDF 加权系数。

    使用经典的 IDF 公式：log(总表数 / 出现列数)
    列出现在越多表中，匹配时贡献越低（ID/Name/Status 这类万能列被降权）。
    无列频数据时返回 1.0（不降权）。

    Args:
        idf_table: 语义索引覆盖的总表数（用于归一化）
        column_doc_freq: 该列名出现在多少张表中
    """
    if idf_table <= 1 or column_doc_freq <= 0:
        return 1.0
    # 拉普拉斯平滑避免除零，同时让极高频列接近 0
    return max(0.05, 1.0 - (column_doc_freq / idf_table))


def score_table(
    query: str,
    table_name: str,
    columns: list[str],
    aliases: list[str] | None = None,
    table_comment: str = "",
    column_meta: dict[str, dict] | None = None,
    column_idf: dict[str, int] | None = None,
    total_tables: int = 0,
) -> float:
    """计算语义相关度分数。

    权重:
    - 表名精确匹配: +1.0
    - 别名精确/词组/子串匹配: +1.0 / +0.8 / +0.6（取最高）
    - 表名按词组（_ 分隔）匹配: +0.8
    - 表名子串匹配: +0.6
    - 列名精确匹配: +0.2/列
    - 列名子串匹配: +0.1/列（列名匹配合计上限 0.6）
    - 列注释/类型别名匹配: 额外加权（上限 1.0）
    - 列名 IDF 加权：高频率列（ID/Name 等）匹配分值衰减

    不封顶：允许高相关表得到 >1.0 的分数，保留排序区分度。
    """
    score = 0.0
    q = query.lower()

    # 表名匹配
    tn = table_name.lower()
    score += _match_name(q, tn)

    # 别名匹配（来自 hot_tables.yaml，已预处理含通配符 + 权重）
    if aliases:
        best_alias = 0.0
        for al in aliases:
            w = al.get("weight", 1.0) if isinstance(al, dict) else 1.0
            term = al.get("term", al) if isinstance(al, dict) else al
            a = term.lower()
            # 支持通配符：优先用预编译的 _compiled（load_hot_tables 已处理），
            # 未预编译时现场编译（测试直传 dict 时触发）
            pat = al.get("_compiled") if isinstance(al, dict) else None
            if pat:
                alias_score = 1.0 if pat.search(q) else 0.0
            elif isinstance(al, dict) and ("*" in term or "?" in term):
                pat = _fnmatch_to_re(term)
                alias_score = 1.0 if pat and pat.search(q) else 0.0
            else:
                alias_score = _match_name(q, a)
            if alias_score > best_alias:
                best_alias = alias_score * w
        score += best_alias

    # 表/列注释通常是业务语义最强信号，尤其中文业务库。
    score += 1.2 * _match_text(q, table_comment.lower())

    # 列名匹配（按词组分词）+ IDF 加权
    words = q.replace("_", " ").split()
    col_match = 0.0
    for word in words:
        for col in columns:
            cl = col.lower()
            base = 0.0
            if word == cl:
                base = 0.2
            elif word in cl and len(word) >= 2:
                base = 0.1
            if base > 0:
                idf = _idf_score(total_tables, column_idf.get(cl, 1) if column_idf else 0)
                col_match += base * idf
    score += min(col_match, 0.6)

    if column_meta:
        meta_match = 0.0
        for col, meta in column_meta.items():
            comment = str(meta.get("comment", "")).lower()
            col_lower = col.lower()
            idf = _idf_score(total_tables, column_idf.get(col_lower, 1) if column_idf else 0)
            meta_match += 0.4 * _match_text(q, comment) * idf
            meta_match += _type_alias_score(q, str(meta.get("type", ""))) * idf
        score += min(meta_match, 1.0)

    return score


def _compute_column_idf(tables: dict) -> dict[str, int]:
    """列名 IDF 统计：统计每个列名在多少张表中出现。"""
    column_idf: dict[str, int] = {}
    for tname, info in tables.items():
        seen: set[str] = set()
        for col in info.get("columns", []):
            cl = col.lower()
            if cl not in seen:
                seen.add(cl)
                column_idf[cl] = column_idf.get(cl, 0) + 1
    return column_idf


def _compute_lexical_scores(query, tables, hot, column_idf, total_tables, limit, learned_metrics) -> tuple[dict[str, float], set[str]]:
    """词法匹配 + 向量语义融合 + 学习权重修正，返回 (direct_scores, lexical_hits)。"""
    direct_scores: dict[str, float] = {}
    # 词法真实命中的表集合（score_table > 0）。
    # FK 传递闭包的 via_fk 判断必须基于词法命中，而非 direct_scores——
    # 后者会因向量 fallback（字符哈希对任意输入返回正值）把所有表都算作"直接匹配"，
    # 导致 transitive_scores 永远为空、via_fk 永远不设。
    lexical_hits: set[str] = set()

    # 向量检索分支 (L4 Vector Space)
    vector_scores: dict[str, float] = {}
    schema_index = index_schema(tables)
    top_vecs = search_semantic_vectors(query, schema_index, k=limit * 2)
    for tname, v_score in top_vecs:
        vector_scores[tname] = v_score

    for table_name, info in tables.items():
        aliases = hot.get(table_name, {}).get("aliases", [])
        score = score_table(
            query,
            table_name,
            info.get("columns", []),
            aliases=aliases,
            table_comment=info.get("comment", ""),
            column_meta=info.get("column_meta", {}),
            column_idf=column_idf,
            total_tables=total_tables,
        )
        if score > 0:
            lexical_hits.add(table_name)

        # 融合向量分：词法已命中时以词法分为准（向量 fallback 的字符哈希
        # 对任意输入都返回正值，会覆盖 IDF 等精细词法权重）；
        # 词法未命中时向量分作为补充信号。
        v_score = vector_scores.get(table_name, 0.0)
        combined_score = score if score > 0 else v_score

        # L2 Feedback: 学习权重修正
        if learned_metrics and table_name in learned_metrics:
            m = learned_metrics[table_name]
            combined_score *= m.get("weight", 1.0)

        if combined_score > 0:
            direct_scores[table_name] = combined_score

    return direct_scores, lexical_hits


def _compute_fk_transitive(tables, lexical_hits, direct_scores) -> dict[str, float]:
    """FK 传递闭包打分：从词法命中的表出发沿 FK 图 BFS 传递分数。"""
    # 构建 FK 图：fk_out[t] = [被 t FK 引用的表], fk_in[t] = [FK 指向 t 的表]
    fk_out: dict[str, list[str]] = {t: [] for t in tables}
    fk_in: dict[str, list[str]] = {t: [] for t in tables}
    for tname, info in tables.items():
        for fk in info.get("fks", []):
            ref = fk.get("referred_table", "")
            if ref and ref in fk_out:
                fk_out[tname].append(ref)
                fk_in[ref].append(tname)

    # BFS：从每个词法命中的表出发，传递打分
    # hop_decay = 0.5^(hop-1)，hop=1 时 1.0，hop=2 时 0.5，hop=3 → 0.25
    # 起点限定为 lexical_hits（词法真实命中），避免向量 fallback 噪声让
    # 无关表也发起 FK 传递。传递目标同样基于 lexical_hits 判断"是否已是直接匹配"。
    transitive_scores: dict[str, float] = {}
    for tname in lexical_hits:
        score = direct_scores.get(tname, 0.0)
        visited: dict[str, int] = {tname: 0}
        queue: deque[str] = deque([tname])
        while queue:
            cur = queue.popleft()
            cur_hop = visited[cur]
            if cur_hop >= 3:
                continue  # 最多 3 跳
            next_hop = cur_hop + 1
            decay = 0.5 ** (next_hop - 1)  # hop=1 → 1.0，hop=2 时 0.5，hop=3 → 0.25
            # 扩展：正向（t FK 引用谁）+ 反向（谁 FK 引用 t）
            for nxt in fk_out.get(cur, []) + fk_in.get(cur, []):
                if nxt in visited:
                    continue
                visited[nxt] = next_hop
                if nxt not in lexical_hits:
                    transitive_scores[nxt] = max(transitive_scores.get(nxt, 0), score * decay)
                queue.append(nxt)

    return transitive_scores


def _build_result_items(tables, all_scores, transitive_scores, preview_cols, learned_metrics) -> list[dict]:
    """构建每张表的搜索结果字典，包含列信息、FK 元数据和学习状态标记。"""
    scored = []
    for table_name, score in all_scores.items():
        info = tables.get(table_name, {})
        all_cols = info.get("columns", [])
        item = {
            "name": table_name,
            "score": round(score, 2),
            "cols": len(all_cols),
            "complete": len(all_cols) <= preview_cols,
            "columns_truncated": len(all_cols) > preview_cols,
            "fk_count": len(info.get("fks", [])),
            "fk_targets": list({fk.get("referred_table", "") for fk in info.get("fks", []) if fk.get("referred_table")}),
            "columns": all_cols[:preview_cols],
        }
        if info.get("comment"):
            item["comment"] = info["comment"]
        if info.get("type"):
            item["type"] = info["type"]
        if table_name in transitive_scores:
            item["via_fk"] = True

        # L2 Feedback: 状态标记
        if learned_metrics and table_name in learned_metrics:
            m = learned_metrics[table_name]
            if m.get("status") == "suspect":
                item["status"] = "suspect"
                item["hint"] = "该表在历史查询中多次触发错误，请谨慎使用。"

        scored.append(item)
    return scored


def build_semantic_matches(
    query: str,
    tables: dict,
    hot: dict,
    limit: int,
    preview_cols: int = SEMANTIC_PREVIEW_COLS,
    skipped_routines: list[str] | None = None,
    learned_metrics: dict[str, dict] | None = None,
) -> dict:
    """按统一规则构建语义搜索结果。

    Args:
        skipped_routines: 与同名表冲突被跳过的存储过程/函数名列表。
                          存在时在结果中加 hint 提示用户可通过 object-type 查询。
    """
    total_tables = len(tables)

    # ── 列名 IDF 统计 ──
    column_idf = _compute_column_idf(tables)

    # ── 第一轮打分 (词法匹配 + 向量语义) ──
    direct_scores, lexical_hits = _compute_lexical_scores(
        query,
        tables,
        hot,
        column_idf,
        total_tables,
        limit,
        learned_metrics,
    )

    # ── FK 传递闭包打分 ──
    transitive_scores = _compute_fk_transitive(tables, lexical_hits, direct_scores)

    # ── 合并得分：直接分 vs 传递分，取较高者 ──
    all_scores: dict[str, float] = {t: direct_scores[t] for t in direct_scores}
    for t, s in transitive_scores.items():
        all_scores[t] = max(all_scores.get(t, 0), s)

    # ── 构建结果 ──
    scored = _build_result_items(tables, all_scores, transitive_scores, preview_cols, learned_metrics)
    # 按分数降序取前 limit 个作为最终返回结果
    top = sorted(scored, key=lambda x: -x["score"])[:limit]
    payload = {
        "success": True,
        "query": query,
        "matches": top,
        "total_matched": len(scored),
        "returned": len(top),
    }
    hints = []
    if not scored:
        hints.append(f"语义搜索无匹配，可尝试 search/explore --pattern %{query}% 做字面兜底。")
    if skipped_routines:
        hints.append(
            f"另有 {len(skipped_routines)} 个同名存储过程/函数被表搜索结果覆盖，"
            f"可用 explore --object-type procedure --pattern <名称> 或 "
            f"explore --object-type function --pattern <名称> 单独查询。"
        )
    if hints:
        payload["hint"] = "\n".join(hints)
    return payload
