#!/usr/bin/env python3
"""cli.safe.py 回归测试

覆盖第一轮 P0-3 的确认通道：
- confirm_danger：写操作的 --yes 确认通道 + 无 TTY 时 EOFError → False
- confirm_overwrite：文件覆写确认 + 不存在文件直接放行 + EOF 行为

关键场景：subprocess 调用（无交互 TTY）时，必须靠 --yes（confirmed=True）放行，
否则 input() 抛 EOFError → 返回 False → 操作被正确拒绝（不会卡死）。
"""

import io
import sys


import pytest
from cli.safe import confirm_danger, confirm_overwrite, is_read_only_sql


# ─────────────────────────────────────────────────────────────────
# 辅助：模拟无 stdin（subprocess 无 TTY 场景）
# ─────────────────────────────────────────────────────────────────


@pytest.fixture
def no_stdin(monkeypatch):
    """把 stdin 替换成空流，模拟 subprocess 无 TTY 调用。"""
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"")))


@pytest.fixture
def yes_stdin(monkeypatch):
    """stdin 输入 yes。"""
    monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"yes\n")))


# ─────────────────────────────────────────────────────────────────
# confirm_danger
# ─────────────────────────────────────────────────────────────────


class TestConfirmDanger:
    def test_readonly_always_allowed(self, no_stdin):
        # 只读 SQL 无论 confirmed 与否都放行
        assert confirm_danger("SELECT 1", confirmed=False) is True
        assert confirm_danger("SELECT 1", confirmed=True) is True

    def test_write_confirmed_yes(self, no_stdin):
        # 写操作 + --yes（confirmed=True）→ 放行（Agent subprocess 场景）
        assert confirm_danger("DROP TABLE x", confirmed=True) is True
        assert confirm_danger("DELETE FROM t", confirmed=True) is True

    def test_write_no_stdin_no_confirmed_rejected(self, no_stdin):
        # 写操作 + 无 stdin + 无 confirmed → EOFError → False（拒绝，不卡死）
        assert confirm_danger("DROP TABLE x", confirmed=False) is False

    def test_write_interactive_yes(self, yes_stdin):
        # 交互式输入 yes → 放行
        assert confirm_danger("DROP TABLE x", confirmed=False) is True

    def test_write_interactive_no(self, monkeypatch):
        # 交互式输入 no → 拒绝
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"no\n")))
        assert confirm_danger("DROP TABLE x", confirmed=False) is False

    def test_empty_sql_allowed(self, no_stdin):
        assert confirm_danger("", confirmed=False) is True


class TestIsReadOnlySql:
    def test_uses_main_security_scanner(self):
        assert is_read_only_sql("SELECT 'DROP TABLE users' AS msg") is True
        assert is_read_only_sql("SELECT * INTO archived_users FROM users") is False
        assert is_read_only_sql("BACKUP DATABASE app TO DISK='x.bak'") is False

    def test_checks_all_statements(self):
        assert is_read_only_sql("SELECT 1; DROP TABLE users") is False


# ─────────────────────────────────────────────────────────────────
# confirm_overwrite
# ─────────────────────────────────────────────────────────────────


class TestConfirmOverwrite:
    def test_nonexistent_file_allowed(self, no_stdin, tmp_path):
        # 文件不存在 → 无需确认直接放行
        target = tmp_path / "new.csv"
        assert confirm_overwrite(str(target), confirmed=False) is True

    def test_existing_confirmed_yes(self, no_stdin, tmp_path):
        # 已存在 + --yes → 放行
        target = tmp_path / "exists.csv"
        target.write_text("old")
        assert confirm_overwrite(str(target), confirmed=True) is True

    def test_existing_no_stdin_no_confirmed_rejected(self, no_stdin, tmp_path):
        # 已存在 + 无 stdin + 无 confirmed → 拒绝
        target = tmp_path / "exists.csv"
        target.write_text("old")
        assert confirm_overwrite(str(target), confirmed=False) is False

    def test_existing_interactive_yes(self, yes_stdin, tmp_path):
        target = tmp_path / "exists.csv"
        target.write_text("old")
        assert confirm_overwrite(str(target), confirmed=False) is True

    def test_existing_interactive_no(self, monkeypatch, tmp_path):
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(b"no\n")))
        target = tmp_path / "exists.csv"
        target.write_text("old")
        assert confirm_overwrite(str(target), confirmed=False) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
