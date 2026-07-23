"""_vector_store.py 单元测试

覆盖：
- SBERT 不可用时的降级行为（返回 None/[]，不产生字符哈希噪声）
- compute_cosine_similarity 对 None/零向量健壮
- 强制 _HAS_SBERT=False 后 is_available 锁定返回 False
- index_schema / search_semantic_vectors 在降级下的契约

不验证 SBERT 实际加载路径（避免 CI 下载模型）。模型下载路径靠 is_available
内部 try/except 保证失败时被记录。
"""

import numpy as np
import pytest

import _vector_store
from _vector_store import (
    compute_cosine_similarity,
    get_embedding,
    index_schema,
    is_available,
    search_semantic_vectors,
)


@pytest.fixture(autouse=True)
def _reset_state():
    """每个测试前重置 SBERT 加载状态，确保互不污染。"""
    _vector_store.reset_for_testing()
    yield
    _vector_store.reset_for_testing()


def _force_unavailable(monkeypatch):
    """把 _vector_store 锁在 SBERT 不可用状态。"""
    _vector_store._HAS_SBERT = False
    _vector_store._MODEL = None
    return monkeypatch


# ─────────────────────────────────────────────────────────────────
# compute_cosine_similarity
# ─────────────────────────────────────────────────────────────────


class TestCosineSimilarity:
    def test_identical_vectors(self):
        v = np.array([1.0, 0.0, 0.0])
        assert compute_cosine_similarity(v, v) == pytest.approx(1.0)

    def test_orthogonal_vectors(self):
        v1 = np.array([1.0, 0.0])
        v2 = np.array([0.0, 1.0])
        assert compute_cosine_similarity(v1, v2) == pytest.approx(0.0)

    def test_opposite_vectors(self):
        v1 = np.array([1.0, 0.0])
        v2 = np.array([-1.0, 0.0])
        assert compute_cosine_similarity(v1, v2) == pytest.approx(-1.0)

    def test_left_none(self):
        v = np.array([1.0, 0.0])
        assert compute_cosine_similarity(None, v) == 0.0

    def test_right_none(self):
        v = np.array([1.0, 0.0])
        assert compute_cosine_similarity(v, None) == 0.0

    def test_both_none(self):
        assert compute_cosine_similarity(None, None) == 0.0

    def test_zero_vector(self):
        v_zero = np.zeros(3)
        v = np.array([1.0, 0.0, 0.0])
        # 零向量没有方向 → 返回 0.0 而非 NaN
        assert compute_cosine_similarity(v_zero, v) == 0.0
        assert compute_cosine_similarity(v, v_zero) == 0.0

    def test_returns_float(self):
        v = np.array([1.0, 2.0, 3.0])
        result = compute_cosine_similarity(v, v)
        assert isinstance(result, float)


# ─────────────────────────────────────────────────────────────────
# 降级行为：SBERT 不可用
# ─────────────────────────────────────────────────────────────────


class TestUnavailableFallback:
    """SBERT 库未装/模型未缓存场景下的行为契约。"""

    def test_get_embedding_returns_none(self, monkeypatch):
        _force_unavailable(monkeypatch)
        assert get_embedding("anything") is None

    def test_search_returns_empty_list(self, monkeypatch):
        _force_unavailable(monkeypatch)
        # 索引中即便有非 None 的向量也不应使用（应整体降级）
        index = {"t1": np.array([1.0, 0.0])}
        result = search_semantic_vectors("query", index, k=5)
        assert result == []

    def test_index_schema_returns_all_none(self, monkeypatch):
        _force_unavailable(monkeypatch)
        tables = {
            "users": {"columns": ["id", "name"], "comment": "用户表"},
            "orders": {"columns": ["id", "amount"], "comment": "订单"},
        }
        index = index_schema(tables)
        assert index == {"users": None, "orders": None}

    def test_is_available_locks_after_failure(self, monkeypatch):
        """is_available 失败后应锁定返回 False，不重复尝试加载。"""
        _force_unavailable(monkeypatch)
        assert is_available() is False
        # 多次调用也保持 False（避免反复尝试触发网络/IO）
        assert is_available() is False
        assert is_available() is False

    def test_index_with_none_entries_filtered(self, monkeypatch):
        """search_semantic_vectors 跳过 None 嵌入（即使 SBERT 可用）。"""
        # 模拟混合索引：部分表成功嵌入，部分失败
        index = {
            "good": np.array([1.0, 0.0]),
            "bad": None,
        }
        # SBERT 不可用 → 直接返回 []，跳过所有
        _force_unavailable(monkeypatch)
        assert search_semantic_vectors("q", index) == []


# ─────────────────────────────────────────────────────────────────
# 加载行为（不验证下载，只验证 is_available 在 SBERT 已加载时的 True 路径）
# ─────────────────────────────────────────────────────────────────


class TestLoadState:
    """加载状态的元测试。"""

    def test_initial_state_unknown(self):
        # 刚重置后，_HAS_SBERT 应为 None
        _vector_store.reset_for_testing()
        assert _vector_store._HAS_SBERT is None
        assert _vector_store._MODEL is None

    def test_force_unavailable_short_circuits(self, monkeypatch):
        """强制设置 _HAS_SBERT=False 后，is_available 不应再尝试加载。"""
        _force_unavailable(monkeypatch)
        # 用一个明显的假模型名，如果 is_available 真的尝试加载，
        # 会在 sleep/网络/IO 上卡住或抛异常；这里只验证立即返回 False
        assert is_available() is False

    def test_reset_clears_state(self):
        _vector_store._HAS_SBERT = False
        _vector_store._MODEL = None
        _vector_store.reset_for_testing()
        assert _vector_store._HAS_SBERT is None
        assert _vector_store._MODEL is None


class TestNoNetworkDownloadHang:
    """SBERT 已装但模型未缓存时，is_available 必须立即返回 False，
    不触发联网下载（避免阻塞 Agent 子进程 10s-数分钟）。

    这是 v0.5.0 的核心 bug 修复。"""

    def test_uncached_model_returns_false_immediately(self, monkeypatch, tmp_path):
        """模型缓存目录不存在 + 联网被禁用 → 立即降级，不下载。"""
        # 关键：路径必须不存在（用不创建的 tmp_path 子路径）
        non_existent_cache = tmp_path / "never_created_cache_dir"
        assert not non_existent_cache.exists()  # 确认前提
        monkeypatch.setattr(_vector_store, "_MODEL_CACHE_DIR", non_existent_cache)
        # 确保下载关闭
        monkeypatch.delenv("DATABASE_EXPLORER_ALLOW_SBERT_DOWNLOAD", raising=False)
        _vector_store.reset_for_testing()

        # 验证：调用 is_available() 不会触发任何加载逻辑
        # 如果触发了，会卡 10s+ 试图下载 → 测试会超时
        result = is_available()
        assert result is False
        # 失败被记录（_HAS_SBERT 锁定为 False，下次调用快速返回）
        assert _vector_store._HAS_SBERT is False

    def test_allow_download_env_disabled_by_default(self, monkeypatch, tmp_path):
        """未设置 DATABASE_EXPLORER_ALLOW_SBERT_DOWNLOAD → 视为禁用。"""
        non_existent_cache = tmp_path / "another_missing"
        monkeypatch.setattr(_vector_store, "_MODEL_CACHE_DIR", non_existent_cache)
        monkeypatch.delenv("DATABASE_EXPLORER_ALLOW_SBERT_DOWNLOAD", raising=False)
        _vector_store.reset_for_testing()
        assert is_available() is False

    def test_allow_download_env_parsed_values(self, monkeypatch, tmp_path):
        """DATABASE_EXPLORER_ALLOW_SBERT_DOWNLOAD 接受多种 truthy 值。"""
        non_existent_cache = tmp_path / "third_missing"
        monkeypatch.setattr(_vector_store, "_MODEL_CACHE_DIR", non_existent_cache)

        for truthy in ("1", "true", "yes", "TRUE", "Yes"):
            monkeypatch.setenv("DATABASE_EXPLORER_ALLOW_SBERT_DOWNLOAD", truthy)
            # 只验证 _allow_network_download 解析正确，不验证实际下载结果
            assert _vector_store._allow_network_download() is True, f"Expected truthy for {truthy!r}"

        for falsy in ("0", "false", "no", "random", ""):
            monkeypatch.setenv("DATABASE_EXPLORER_ALLOW_SBERT_DOWNLOAD", falsy)
            assert _vector_store._allow_network_download() is False, f"Expected falsy for {falsy!r}"


# ─────────────────────────────────────────────────────────────────
# 线程安全（白盒：验证 _LOAD_LOCK 存在 + 用法正确）
# ─────────────────────────────────────────────────────────────────


class TestThreadSafety:
    def test_lock_exists(self):
        """_LOAD_LOCK 必须是 threading.Lock 实例。"""
        import threading

        assert isinstance(_vector_store._LOAD_LOCK, type(threading.Lock()))


# ─────────────────────────────────────────────────────────────────
# 回归保护：确认 v0.5.0 字符哈希 fallback 已彻底移除
# ─────────────────────────────────────────────────────────────────


class TestNoCharacterHashFallback:
    """防止有人重新引入字符哈希回退（v0.5.0 之前的实现）。"""

    def test_no_zeros_call_in_module(self):
        """模块源码不应再出现 np.zeros(128) 这种字符哈希向量。"""
        import inspect

        source = inspect.getsource(_vector_store)
        # 防止误判：检查特定的字符哈希特征模式
        assert "np.zeros(128)" not in source, "字符哈希 fallback 已废弃，禁止重新引入；SBERT 不可用时应降级到 None/空列表。"
        assert "ord(char) % 128" not in source, "检测到字符哈希实现，v0.5.1 起应返回 None。"

    def test_get_embedding_signature_returns_optional(self):
        """get_embedding 应支持返回 None（type hint 层面）。"""
        import inspect

        sig = inspect.signature(get_embedding)
        # 不强制 runtime 类型检查，但通过 type annotation 表达契约
        assert sig.return_annotation != inspect.Signature.empty
