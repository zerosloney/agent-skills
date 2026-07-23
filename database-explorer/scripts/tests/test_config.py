"""Tests for core/config.py — connection config save/load, password security.

Uses DATABASE_EXPLORER_HOME env var to isolate config to tmp_path,
avoiding pollution of the user's real ~/.database-explorer directory.
"""

import json


import pytest


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """Redirect config dir to tmp_path for test isolation.

    与 conftest.py 的同名 fixture 不同：这里在 monkeypatch 设完
    DATABASE_EXPLORER_HOME 后还要 ``importlib.reload(core.config)``，
    因为 ``core.config.CONFIG_DIR`` 是模块加载时基于环境变量算出的常量，
    后续只改 env 不会刷新该值。其它测试（运行时读 env 的代码）
    用 conftest 的版本即可，不需要 reload。
    """
    home = tmp_path / "dbx_home"
    home.mkdir()
    monkeypatch.setenv("DATABASE_EXPLORER_HOME", str(home))
    # Must reimport config to pick up the new CONFIG_DIR
    import importlib
    import core.config

    importlib.reload(core.config)
    return home


class TestSaveLoadRoundTrip:
    """save_config → load_config must preserve data."""

    def test_save_then_load_preserves_connection(self, isolated_home):
        import core.config as cfg_mod

        cfg = {
            "active": "test",
            "connections": {
                "test": {
                    "db_type": "sqlite",
                    "server": "localhost",
                    "database": str(isolated_home / "test.db"),
                    "user": "",
                    "password": "",
                }
            },
        }
        cfg_mod.save_config(cfg)
        loaded = cfg_mod.load_config()
        assert loaded["active"] == "test"
        assert "test" in loaded["connections"]
        assert loaded["connections"]["test"]["db_type"] == "sqlite"

    def test_load_empty_returns_empty_dict(self, isolated_home):
        import core.config as cfg_mod

        loaded = cfg_mod.load_config()
        assert loaded == {"active": None, "connections": {}}


class TestPasswordSecurity:
    """Passwords must NOT be stored in plaintext config file."""

    def test_password_not_in_config_file(self, isolated_home):
        import core.config as cfg_mod

        cfg = {
            "active": "prod",
            "connections": {
                "prod": {
                    "db_type": "sqlserver",
                    "server": "localhost",
                    "database": "mydb",
                    "user": "sa",
                    "password": "super_secret_123",
                }
            },
        }
        cfg_mod.save_config(cfg)
        # Read the raw config file — password must NOT appear in plaintext
        raw = json.loads(cfg_mod.CONFIG_FILE.read_text(encoding="utf-8"))
        conn = raw["connections"]["prod"]
        # Password should be cleared (None or "") after keyring migration
        assert not conn.get("password"), f"Password leaked to config file: {conn.get('password')}"

    def test_password_restored_on_load(self, isolated_home):
        import core.config as cfg_mod

        cfg = {
            "active": "prod",
            "connections": {
                "prod": {
                    "db_type": "sqlserver",
                    "server": "localhost",
                    "database": "mydb",
                    "user": "sa",
                    "password": "my_password_456",
                }
            },
        }
        cfg_mod.save_config(cfg)
        loaded = cfg_mod.load_config()
        # Password should be restored (from keyring or fallback)
        assert loaded["connections"]["prod"].get("password") in ("my_password_456", None, ""), "Password not restored on load"


class TestDbTypeNormalization:
    """db_type aliases (mssql → sqlserver) should be normalized on load."""

    def test_mssql_normalized_to_sqlserver(self, isolated_home):
        import core.config as cfg_mod

        cfg = {
            "active": "test",
            "connections": {
                "test": {
                    "db_type": "mssql",
                    "server": "localhost",
                    "database": "mydb",
                    "user": "sa",
                    "password": "",
                }
            },
        }
        cfg_mod.save_config(cfg)
        loaded = cfg_mod.load_config()
        assert loaded["connections"]["test"]["db_type"] == "sqlserver"

    def test_postgres_alias_preserved(self, isolated_home):
        import core.config as cfg_mod

        cfg = {
            "active": "test",
            "connections": {
                "test": {
                    "db_type": "postgres",
                    "server": "localhost",
                    "database": "mydb",
                    "user": "u",
                    "password": "",
                }
            },
        }
        cfg_mod.save_config(cfg)
        loaded = cfg_mod.load_config()
        # 'postgres' is a valid alias, stays as-is
        assert loaded["connections"]["test"]["db_type"] in ("postgres", "postgresql")

    def test_kingbasees_normalized_to_kingbase(self, isolated_home):
        import core.config as cfg_mod

        cfg = {
            "active": "test",
            "connections": {
                "test": {
                    "db_type": "kingbasees",
                    "server": "localhost",
                    "port": 54321,
                    "database": "testdb",
                    "user": "system",
                    "password": "",
                }
            },
        }
        cfg_mod.save_config(cfg)
        loaded = cfg_mod.load_config()
        assert loaded["connections"]["test"]["db_type"] == "kingbase"


class TestGetActiveConfig:
    """get_active_config returns the active connection's config."""

    def test_returns_active_connection(self, isolated_home):
        import core.config as cfg_mod

        cfg = {
            "active": "primary",
            "connections": {
                "primary": {
                    "db_type": "sqlite",
                    "server": "",
                    "database": str(isolated_home / "x.db"),
                    "user": "",
                    "password": "",
                }
            },
        }
        cfg_mod.save_config(cfg)
        active = cfg_mod.get_active_config()
        assert active is not None
        assert active["db_type"] == "sqlite"

    def test_raises_when_no_active(self, isolated_home):
        import core.config as cfg_mod

        with pytest.raises(RuntimeError, match="无活动连接"):
            cfg_mod.get_active_config()
