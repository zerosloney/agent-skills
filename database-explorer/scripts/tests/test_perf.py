"""Performance regression tests — guard against slowdowns in hot paths.

Uses SQLite in-memory + the e2e CLI runner to measure real-world timing.
These are smoke-grade thresholds (not micro-benchmarks), designed to catch
order-of-magnitude regressions, not optimize to the millisecond.
"""

import time

import pytest


# SBERT 首次加载（all-MiniLM-L6-v2 约 103 层权重）耗时远超本文件的 2s 冷启动阈值。
# 该阈值是为 CI 干净环境（无 SBERT → 字符哈希 fallback，毫秒级）设计的回归护栏，
# 在装了 sentence-transformers 的开发机上必然超时，与产品性能无关。
# 用 find_spec 检测（不实际 import，避免收集阶段触发模型加载）。
import importlib.util
from _helpers import run_cli

_HAS_SBERT = importlib.util.find_spec("sentence_transformers") is not None
_skip_if_sbert = pytest.mark.skipif(
    _HAS_SBERT,
    reason="SBERT 首次加载耗时 >2s，本测试阈值仅针对无 SBERT 的 fallback 路径（CI 环境）",
)


@pytest.fixture
def sqlite_conn(tmp_path, monkeypatch):
    """Standard SQLite fixture with a small table."""
    home = str(tmp_path / "explorer-home")
    monkeypatch.setenv("DATABASE_EXPLORER_HOME", home)
    db_file = tmp_path / "test.db"
    conn_str = f"sqlite:///{db_file.as_posix()}"
    name = f"perf-{tmp_path.name}"
    run_cli(["connect", "--db-type", "sqlite", "--connection-string", conn_str, "--name", name])
    run_cli(["query", "--yes", "--sql", "CREATE TABLE orders (id INTEGER PRIMARY KEY, cust_name TEXT, status TEXT)"])
    for i in range(10):
        run_cli(["query", "--yes", "--sql", f"INSERT INTO orders (id, cust_name, status) VALUES ({i}, 'c{i}', 'pending')"])
    yield name


class TestSemanticSearchPerformance:
    """Semantic search should be fast even on cold start."""

    @_skip_if_sbert
    def test_semantic_search_under_2s(self, sqlite_conn):
        """Cold-start semantic search should complete in under 2 seconds."""
        t0 = time.perf_counter()
        rc, out, err = run_cli(
            [
                "search",
                "--semantic",
                "order",
                "--format",
                "json-compact",
            ]
        )
        elapsed = time.perf_counter() - t0
        assert rc == 0, f"search failed: {err}"
        assert elapsed < 2.0, f"Semantic search took {elapsed:.2f}s (threshold 2s)"


class TestJsonCompactEfficiency:
    """json-compact format should be smaller than table format."""

    def test_compact_smaller_than_table(self, sqlite_conn):
        """Compact output must be smaller than table output for the same query."""
        rc1, compact, _ = run_cli(
            [
                "query",
                "--yes",
                "--sql",
                "SELECT * FROM orders",
                "--format",
                "json-compact",
            ]
        )
        rc2, table, _ = run_cli(
            [
                "query",
                "--yes",
                "--sql",
                "SELECT * FROM orders",
                "--format",
                "table",
            ]
        )
        assert rc1 == 0 and rc2 == 0
        assert len(compact) < len(table), f"compact ({len(compact)} bytes) should be < table ({len(table)} bytes)"


class TestExploreSpeed:
    """explore command should return quickly for a small schema."""

    def test_explore_tables_under_3s(self, sqlite_conn):
        """explore --object-type table should complete quickly."""
        t0 = time.perf_counter()
        rc, out, err = run_cli(
            [
                "explore",
                "--object-type",
                "table",
                "--detail",
                "names",
                "--format",
                "json-compact",
            ]
        )
        elapsed = time.perf_counter() - t0
        assert rc == 0, f"explore failed: {err}"
        assert elapsed < 3.0, f"explore took {elapsed:.2f}s (threshold 3s)"
