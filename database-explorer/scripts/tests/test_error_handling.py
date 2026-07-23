"""Tests for error handling paths — network errors, bad engines, driver issues.

Uses unittest.mock to simulate failures without needing a real broken database.
"""

from unittest.mock import MagicMock, patch

import pytest


class TestExecuteQueryErrorRecovery:
    """execute_query must return error dict, not crash, on DB failures."""

    def test_connection_failure_returns_error(self):
        """Simulate engine.connect() raising a network error."""
        from _drivers import execute_query

        mock_engine = MagicMock()
        # Simulate network error on connect
        import sqlalchemy.exc

        mock_engine.connect.side_effect = sqlalchemy.exc.OperationalError("statement", {}, "Connection refused")

        result = execute_query(mock_engine, "SELECT 1")
        assert result["success"] is False
        assert "error" in result
        assert "Connection refused" in result["error"] or "refused" in result["error"].lower()

    def test_query_timeout_returns_error(self):
        """Simulate query execution raising a timeout."""
        from _drivers import execute_query

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        # Simulate timeout on execute
        mock_conn.execute.side_effect = Exception("Query timeout expired")

        result = execute_query(mock_engine, "SELECT * FROM huge_table")
        assert result["success"] is False
        assert "error" in result

    def test_invalid_sql_returns_error(self):
        """Simulate a syntax error in user SQL."""
        from _drivers import execute_query

        mock_engine = MagicMock()
        mock_conn = MagicMock()
        mock_engine.connect.return_value.__enter__ = MagicMock(return_value=mock_conn)
        mock_engine.connect.return_value.__exit__ = MagicMock(return_value=False)

        mock_conn.execute.side_effect = Exception("syntax error near 'SELEC'")

        result = execute_query(mock_engine, "SELEC * FROM x")
        assert result["success"] is False
        assert "error" in result


class TestSchemaExplorationGracefulFailure:
    """Schema exploration functions return empty (not crash) on failure."""

    def test_get_tables_handles_error(self):
        """get_tables returns [] when inspector fails (not crash)."""
        from _drivers import get_tables

        mock_engine = MagicMock()
        mock_engine.dialect.name = "sqlite"
        # Patch the local 'inspect' name in _drivers, not sqlalchemy.inspect
        with patch("_drivers.inspect", side_effect=Exception("permission denied")):
            result = get_tables(mock_engine)
            assert result == []

    def test_get_columns_handles_error(self):
        """get_columns returns [] when inspector fails."""
        from _drivers import get_columns

        mock_engine = MagicMock()
        mock_engine.dialect.name = "sqlite"
        with patch("_drivers.inspect", side_effect=Exception("table not found")):
            result = get_columns(mock_engine, "nonexistent_table")
            assert result == []


class TestConnectErrorMessages:
    """connect() should give helpful errors for common failures."""

    def test_unsupported_db_type_exits(self, capsys):
        """Unsupported db_type exits with helpful error."""
        from _drivers import _check_driver

        with pytest.raises(SystemExit):
            _check_driver("nonexistent_db_type_12345")
        captured = capsys.readouterr()
        assert "不支持" in captured.err or "unsupported" in captured.err.lower()

    def test_connect_bad_host_fails(self):
        """connect() to bad host raises OperationalError (mocked, no real network)."""
        from _drivers import connect
        import sqlalchemy.exc

        # mock create_engine 使 engine.connect() 抛 OperationalError，模拟不可达主机；
        # 同时跳过 _check_driver 的驱动安装校验（此处测的是连接失败，不是驱动缺失）。
        with patch("_drivers.create_engine") as mock_create, patch("_drivers._check_driver"):
            mock_engine = MagicMock()
            mock_engine.connect.side_effect = sqlalchemy.exc.OperationalError("statement", {}, "Connection refused")
            mock_create.return_value = mock_engine

            with pytest.raises(Exception):
                connect(
                    {
                        "db_type": "mysql",
                        "server": "nonexistent-host-12345.invalid",
                        "database": "testdb",
                        "user": "u",
                        "password": "p",
                        "port": 3306,
                    }
                )


class TestCorruptedFileRecovery:
    """Corrupted config/learned files should be handled gracefully."""

    def test_corrupted_learned_yaml_returns_empty(self, tmp_path):
        """Corrupted query_learned.yaml → load_learned_aliases returns {}."""
        bad_file = tmp_path / "query_learned.yaml"
        bad_file.write_text("{{{{not valid yaml: [[[", encoding="utf-8")

        from _query_learning import load_learned_aliases

        result = load_learned_aliases(path=str(bad_file))
        assert result == {}, f"Corrupted YAML should return empty, got: {result}"

    def test_empty_learned_yaml_returns_empty(self, tmp_path):
        """Empty query_learned.yaml → returns {}."""
        empty_file = tmp_path / "query_learned.yaml"
        empty_file.write_text("", encoding="utf-8")

        from _query_learning import load_learned_aliases

        result = load_learned_aliases(path=str(empty_file))
        assert result == {}
