"""Tests for _keyring_security.py — password save/load/delete/migrate.

Uses a unique connection name per test (with cleanup) to avoid polluting
the real OS keyring. If keyring is not installed, tests are skipped.
"""

import pytest


# Skip entire module if keyring is not installed
try:
    import keyring  # noqa: F401

    _HAS_KEYRING = True
except ImportError:
    _HAS_KEYRING = False

pytestmark = pytest.mark.skipif(not _HAS_KEYRING, reason="keyring not installed")


@pytest.fixture
def conn_name():
    """Unique connection name, cleaned up after test."""
    import uuid

    name = f"test-{uuid.uuid4().hex[:8]}"
    yield name
    # Cleanup: delete password if it exists
    try:
        from _keyring_security import delete_password

        delete_password(name, use_keyring=True)
    except Exception:
        pass


class TestSaveLoadRoundTrip:
    """save_password → load_password must preserve the password."""

    def test_save_then_load(self, conn_name):
        from _keyring_security import save_password, load_password

        save_password(conn_name, "secret123", use_keyring=True)
        cfg = {"password": None, "_keyring_ref": True}
        loaded = load_password(conn_name, cfg)
        assert loaded == "secret123"

    def test_load_nonexistent_returns_empty(self, conn_name):
        from _keyring_security import load_password

        cfg = {"password": None, "_keyring_ref": True}
        result = load_password(conn_name, cfg)
        assert result == ""  # empty string, not None

    def test_delete_after_save(self, conn_name):
        from _keyring_security import save_password, delete_password, load_password

        save_password(conn_name, "pwd", use_keyring=True)
        assert delete_password(conn_name, use_keyring=True) is True
        # After delete, load should return empty
        cfg = {"password": None, "_keyring_ref": True}
        assert load_password(conn_name, cfg) == ""

    def test_delete_nonexistent_returns_false(self, conn_name):
        from _keyring_security import delete_password

        # Deleting a non-existent password should not crash
        result = delete_password(conn_name, use_keyring=True)
        assert isinstance(result, bool)


class TestCheckSecurityLevel:
    """check_security_level reports whether password is securely stored."""

    def test_keyring_stored_is_secure(self, conn_name):
        from _keyring_security import save_password, check_security_level

        save_password(conn_name, "secret", use_keyring=True)
        cfg = {"password": None, "_keyring_ref": True}
        info = check_security_level(cfg)
        assert info["secure"] is True
        assert info["level"] == "HIGH"

    def test_plaintext_password_is_insecure(self):
        from _keyring_security import check_security_level

        cfg = {"password": "plain_secret", "_keyring_ref": False}
        info = check_security_level(cfg)
        assert info["secure"] is False

    def test_no_password_is_neutral(self):
        from _keyring_security import check_security_level

        cfg = {"password": None, "_keyring_ref": False}
        info = check_security_level(cfg)
        # No password at all — not insecure, just empty
        assert "level" in info


class TestSaveFallback:
    """save_password behavior with use_keyring=False."""

    def test_save_without_keyring_returns_none(self, conn_name):
        """use_keyring=False returns None (password not stored anywhere)."""
        from _keyring_security import save_password

        result = save_password(conn_name, "fallback_pwd", use_keyring=False)
        assert result is None


class TestMigrateConnections:
    """migrate_all_connections behavior — legacy encrypted passwords can't be decrypted."""

    def test_migrate_legacy_password_warns(self, conn_name, capsys):
        """Legacy encrypted passwords trigger warning, can't auto-migrate."""
        from _keyring_security import migrate_all_connections

        config = {
            "active": conn_name,
            "connections": {
                conn_name: {
                    "db_type": "sqlite",
                    "server": "",
                    "database": "/tmp/x.db",
                    "user": "",
                    "password": "legacy_encrypted_blob",
                    "_keyring_ref": False,
                }
            },
        }
        migrate_all_connections(config)
        captured = capsys.readouterr()
        assert "旧版" in captured.out or "重新执行" in captured.out
