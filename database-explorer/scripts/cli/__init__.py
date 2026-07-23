#!/usr/bin/env python3
"""
cli - CLI 命令模块

提供命令行接口的命令实现。
所有命令逻辑由各子模块提供，db_tool.py 仅做参数解析和调度。
"""

# 连接管理命令
from .connection_cmds import (
    cmd_connect,
    cmd_list,
    cmd_use,
    cmd_ping,
)

# 查询命令
from .query_cmds import (
    cmd_query,
    cmd_export,
)


# 统一结构探索命令（Agent 首选）
from .explore_cmds import (
    cmd_explore,
)

# 数据分析命令
from .data_cmds import (
    cmd_sample,
    cmd_profile,
    cmd_search,
    cmd_find,
    cmd_history,
    cmd_explain,
)

# 代码生成命令
from .codegen_cmds import (
    cmd_script,
    cmd_crud,
)

# 交互式 REPL
from .repl_cmds import (
    cmd_repl,
)

# 常驻进程模式
from .pipe_cmds import (
    cmd_pipe,
)

# 安全工具
from .safe import (
    confirm_danger,
    is_read_only_sql,
)

# 学习数据管理命令
from .learn_cmds import (
    cmd_learn,
)

__all__ = [
    # 连接管理
    "cmd_connect",
    "cmd_list",
    "cmd_use",
    "cmd_ping",
    # 查询
    "cmd_query",
    "cmd_export",
    # 结构探索（统一，Agent 首选）
    "cmd_explore",
    # 数据分析
    "cmd_sample",
    "cmd_profile",
    "cmd_search",
    "cmd_find",
    "cmd_history",
    "cmd_explain",
    # 代码生成
    "cmd_script",
    "cmd_crud",
    # REPL
    "cmd_repl",
    # Pipe
    "cmd_pipe",
    # 学习
    "cmd_learn",
    # 安全工具
    "confirm_danger",
    "is_read_only_sql",
]
