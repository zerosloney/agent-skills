"""向量存储模块 — 为数据库 Schema 提供语义向量检索能力。
实现 L4 专家级能力：从词法匹配升级为语义空间检索。

降级策略（按检查顺序，任一不满足即降级为纯词法匹配）：
1. SBERT 库未安装 → 降级
2. 模型缓存目录不存在（首次使用需联网下载）→ 降级，避免静默触发下载阻塞
3. SentenceTransformer(...) 加载失败 → 降级

加载过程加了 thread-safety lock，避免多线程并发加载。

历史说明：早期实现 SBERT 不可用时回退到 128 维字符哈希向量，
但字符哈希对任意输入都返回正值，会污染 IDF 等精细词法权重（见 _scoring.py）。
v0.5.1 起改为降级到空结果，让上层 build_semantic_matches 自然回退到纯词法评分。
"""

import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)

# SBERT 模型缓存根目录（HuggingFace 默认 ~/.cache/torch/sentence_transformers）。
# 存在 → 离线可用；不存在 → 首次加载会触发联网下载，宁可直接降级避免阻塞。
_MODEL_CACHE_DIR = Path.home() / ".cache" / "torch" / "sentence_transformers"


def _model_cached_locally() -> bool:
    """模型是否已在本地缓存。返回 False 时 is_available 直接降级，不触发下载。

    跳过这层检查会让 SBERT 首次调用时尝试从 HuggingFace 下载（可能 10s-数分钟），
    阻塞 Agent 子进程。生产/CI 环境通常不会预缓存模型，因此必须先检查。
    """
    return _MODEL_CACHE_DIR.is_dir()


def _allow_network_download() -> bool:
    """是否允许在线下载模型。默认关闭（避免阻塞），可通过环境变量开启。

    设置 ``DATABASE_EXPLORER_ALLOW_SBERT_DOWNLOAD=1`` 允许首次联网下载。
    """
    return os.environ.get("DATABASE_EXPLORER_ALLOW_SBERT_DOWNLOAD", "").lower() in (
        "1",
        "true",
        "yes",
    )


# 延迟加载状态：
#   _HAS_SBERT = None  → 未尝试
#   _HAS_SBERT = True  → 已加载
#   _HAS_SBERT = False → 加载失败（库未装/模型不可用），已锁定降级
_HAS_SBERT: bool | None = None
_MODEL: Any = None
_MODEL_NAME = "all-MiniLM-L6-v2"

# 加载锁：避免多线程并发触发 SentenceTransformer 加载
_LOAD_LOCK = threading.Lock()

# 向量索引进程级缓存：同一 session 内多次语义搜索复用已编码的索引，
# 避免每次 search 都对全表调 SBERT encode（500 表 ≈ 5-25s → 缓存命中 <1ms）。
_INDEX_CACHE: dict[str, np.ndarray | None] | None = None
_INDEX_CACHE_KEY: str | None = None
_INDEX_CACHE_TIME: float = 0.0
_INDEX_CACHE_TTL: float = 300.0  # 秒，与语义索引缓存 TTL 对齐
# pipe 模式下多线程并发调 index_schema 时保护 _INDEX_CACHE 的写竞争
# （_LOAD_LOCK 只保护模型加载，不保护索引构建）
_INDEX_CACHE_LOCK = threading.Lock()


def is_available() -> bool:
    """SBERT 模型是否可用。惰性触发首次加载，失败后返回 False 并锁定。

    检查顺序（任一不满足直接降级，避免阻塞）：
    1. 库导入 + 模型缓存目录存在（或显式允许联网下载）
    2. SentenceTransformer 实例化成功

    在 Agent 子进程（单线程）下基本不会并发调用，但 pipe 模式 + 异步
    场景下不能保证。加锁确保只加载一次且失败结果被记录。
    """
    global _HAS_SBERT, _MODEL
    if _HAS_SBERT is True and _MODEL is not None:
        return True
    if _HAS_SBERT is False:
        return False
    # 快速失败：模型未缓存且不允许联网下载 → 直接降级
    if not _model_cached_locally() and not _allow_network_download():
        _HAS_SBERT = False
        _MODEL = None
        logger.info(
            "SBERT model not cached locally and network download is disabled "
            "(set DATABASE_EXPLORER_ALLOW_SBERT_DOWNLOAD=1 to allow). "
            "Semantic search falls back to lexical-only."
        )
        return False
    # 首次尝试加载
    with _LOAD_LOCK:
        if _HAS_SBERT is True:
            return True
        if _HAS_SBERT is False:
            return False
        try:
            from sentence_transformers import SentenceTransformer

            _MODEL = SentenceTransformer(_MODEL_NAME)
            _HAS_SBERT = True
            logger.info("SBERT model loaded: %s", _MODEL_NAME)
            return True
        except Exception as e:
            _HAS_SBERT = False
            _MODEL = None
            logger.info(
                "SBERT unavailable (%s). Semantic search falls back to lexical-only.",
                e,
            )
            return False


def reset_for_testing() -> None:
    """重置加载状态和索引缓存（仅测试用）。"""
    global _HAS_SBERT, _MODEL, _INDEX_CACHE, _INDEX_CACHE_KEY, _INDEX_CACHE_TIME
    _HAS_SBERT = None
    _MODEL = None
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE = None
        _INDEX_CACHE_KEY = None
        _INDEX_CACHE_TIME = 0.0


def get_embedding(text: str) -> np.ndarray | None:
    """生成文本向量。SBERT 不可用时返回 None。

    返回 None 而非零向量：上层调用方可以据此跳过该文档，避免零向量
    与所有查询向量产生 undefined 的相似度（取决于实现）。
    """
    if not is_available():
        return None
    try:
        return _MODEL.encode(text)
    except Exception as e:
        logger.debug("get_embedding failed for %r: %s", text[:40], e)
        return None


def compute_cosine_similarity(v1: np.ndarray | None, v2: np.ndarray | None) -> float:
    """计算两个向量的余弦相似度。任一为 None 或零向量时返回 0.0。"""
    if v1 is None or v2 is None:
        return 0.0
    norm1 = float(np.linalg.norm(v1))
    norm2 = float(np.linalg.norm(v2))
    if norm1 == 0.0 or norm2 == 0.0:
        return 0.0
    return float(np.dot(v1, v2) / (norm1 * norm2))


def invalidate_index_cache() -> None:
    """清除向量索引缓存。连接切换或 schema 变更时调用。"""
    global _INDEX_CACHE, _INDEX_CACHE_KEY, _INDEX_CACHE_TIME
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE = None
        _INDEX_CACHE_KEY = None
        _INDEX_CACHE_TIME = 0.0


def _build_index_key(tables_data: dict[str, Any]) -> str:
    """从 tables_data 构建稳定的缓存 key。

    用 sorted 表名 + 列名 + comment 拼接后取 hash，保证相同 schema
    产生相同 key，不同 schema（增删表/列）一定 miss。
    """
    import hashlib

    parts: list[str] = []
    for tname in sorted(tables_data):
        info = tables_data[tname]
        cols = ",".join(sorted(info.get("columns", [])))
        comment = info.get("comment", "")
        parts.append(f"{tname}|{cols}|{comment}")
    raw = "\n".join(parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]


def index_schema(tables_data: dict[str, Any]) -> dict[str, np.ndarray | None]:
    """为数据库 Schema 构建向量索引（带进程级缓存）。

    SBERT 不可用时所有表都得到 None（而不是零向量），让
    :func:`search_semantic_vectors` 跳过这些表。

    缓存策略：
    - key = tables_data 内容哈希（表名 + 列名 + comment）
    - TTL = 300s，与语义索引缓存对齐
    - 同一 session 内多次语义搜索复用已编码索引（500 表 5-25s → <1ms）

    Args:
        tables_data: { table_name: { "columns": [...], "comment": "..." } }

    Returns:
        { table_name: np.ndarray | None }
    """
    global _INDEX_CACHE, _INDEX_CACHE_KEY, _INDEX_CACHE_TIME

    if not is_available():
        # 快速路径：SBERT 不可用时直接返回全 None map，无需缓存
        return {tname: None for tname in tables_data}

    # 缓存命中检查（持有锁避免读 - 写竞争）
    cache_key = _build_index_key(tables_data)
    now = time.monotonic()
    with _INDEX_CACHE_LOCK:
        if _INDEX_CACHE is not None and _INDEX_CACHE_KEY == cache_key and (now - _INDEX_CACHE_TIME) < _INDEX_CACHE_TTL:
            logger.debug("vector index cache hit (key=%s)", cache_key[:8])
            return _INDEX_CACHE

    # 缓存 miss：重建索引（不放锁，让多线程可并行编码；最后回写时加锁）
    logger.debug("vector index cache miss, rebuilding (key=%s, tables=%d)", cache_key[:8], len(tables_data))
    index: dict[str, np.ndarray | None] = {}
    for table_name, info in tables_data.items():
        cols = ", ".join(info.get("columns", []))
        comment = info.get("comment", "")
        doc = f"Table: {table_name}. Comment: {comment}. Columns: {cols}"
        index[table_name] = get_embedding(doc)

    # 写入缓存（加锁：N 个并发回写只保留最后赢家的结果；后续命中即可复用）
    with _INDEX_CACHE_LOCK:
        _INDEX_CACHE = index
        _INDEX_CACHE_KEY = cache_key
        _INDEX_CACHE_TIME = time.monotonic()
    return index


def search_semantic_vectors(
    query: str,
    index: dict[str, np.ndarray | None],
    k: int = 10,
) -> list[tuple[str, float]]:
    """在向量空间中检索最相似的表。

    降级行为：
    - SBERT 不可用时返回空列表（搜索结果完全由词法评分决定，调用方无需改）。
    - index 中嵌入为 None 的表被跳过。

    Args:
        query: 搜索关键词
        index: :func:`index_schema` 生成的索引
        k: 返回前 k 个

    Returns:
        按相似度降序的 (table_name, score) 列表；SBERT 不可用时返回 []
    """
    if not is_available():
        return []
    query_vec = get_embedding(query)
    if query_vec is None:
        return []
    scores: list[tuple[str, float]] = []
    for table_name, vec in index.items():
        if vec is None:
            continue
        sim = compute_cosine_similarity(query_vec, vec)
        if sim > 0:
            scores.append((table_name, sim))
    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:k]
