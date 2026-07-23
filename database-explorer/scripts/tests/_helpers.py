# -*- coding: utf-8 -*-
"""测试共享常量与 helper — 替代从 conftest import 的反模式

pytest 推荐：conftest 只放 fixture / 共享钩子，普通 helper 函数和常量
放独立模块（`tests/_helpers.py`）。`from conftest import ...` 虽然在多数
pytest 配置下能 work，但依赖 conftest 被收集到 sys.path 的隐式顺序，
换 rootdir / 加 __init__.py / 改 collection 模式时容易 ImportError。

本模块提供:
- SCRIPT_DIR: scripts/ 目录绝对路径（启动子进程时用作 cwd 和 PYTHONPATH）
- DB_TOOL: scripts/db_tool.py 路径
- run_cli: subprocess 调用 db_tool.py 的统一封装
"""

import os
import subprocess
import sys
from pathlib import Path

# 父目录：tests/_helpers.py → tests/ → scripts/
SCRIPT_DIR = Path(__file__).resolve().parent.parent
DB_TOOL = SCRIPT_DIR / "db_tool.py"


def run_cli(args, stdin_data=None, env_extra=None, timeout: int = 60):
    """subprocess 调用 db_tool.py，返回 (returncode, stdout, stderr)。

    自动注入 PYTHONPATH 和可选的环境变量覆盖。
    """
    env = os.environ.copy()
    env["PYTHONPATH"] = str(SCRIPT_DIR)
    if env_extra:
        env.update(env_extra)
    result = subprocess.run(
        [sys.executable, str(DB_TOOL)] + [str(a) for a in args],
        input=stdin_data,
        capture_output=True,
        text=True,
        env=env,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr
