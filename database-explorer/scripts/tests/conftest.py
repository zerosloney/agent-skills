# -*- coding: utf-8 -*-
"""共享测试 fixture — 消除跨文件重复的样板代码

提供:
- sys.path 注入（自动，conftest 加载时执行）
- isolated_home fixture（DATABASE_EXPLORER_HOME 隔离）

路径常量与 run_cli 见 ``_helpers.py``。
"""

import sys

import pytest

# ═══════════════════════════════════════════════════════════════
#  路径设置（替代每个测试文件的 _SCRIPT_DIR + sys.path.insert）
# ═══════════════════════════════════════════════════════════════

from _helpers import SCRIPT_DIR  # noqa: E402 必须在 sys.path 设置之后

_SCRIPT_DIR = SCRIPT_DIR
sys.path.insert(0, str(SCRIPT_DIR))


# ═══════════════════════════════════════════════════════════════
#  共享 fixture
# ═══════════════════════════════════════════════════════════════


@pytest.fixture
def isolated_home(tmp_path, monkeypatch):
    """创建隔离的 DATABASE_EXPLORER_HOME 临时目录。

    每个测试函数独立的临时目录，避免测试间配置/缓存污染。

    注意：test_config.py 重新实现了同名 fixture（带 importlib.reload），
    因为 core.config 的 CONFIG_DIR 是模块级变量，env 改了需要 reload。
    本 fixture 不 reload，仅适用于运行时读 env 的代码。
    """
    home = tmp_path / "explorer-home"
    home.mkdir()
    monkeypatch.setenv("DATABASE_EXPLORER_HOME", str(home))
    return home
