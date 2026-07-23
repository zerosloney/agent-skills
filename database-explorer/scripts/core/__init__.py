#!/usr/bin/env python3
"""
core - 核心功能模块

提供数据库管理器的核心功能：
- connection: 连接管理
- config: 配置管理
- security: 安全相关

Note: CLI 直接通过 _drivers.py / _security.py / _formatters.py 实现，
core/ 仅提供连接获取和配置管理的薄封装。
"""

from .connection import get_connection
from .config import (
    save_config,
    load_config,
    get_active_config,
    ConnectionConfig,
    ConfigDict,
    CONFIG_DIR,
    CONFIG_FILE,
)
from .config import HAS_KEYRING

__all__ = [
    # 连接
    "get_connection",
    # 配置
    "save_config",
    "load_config",
    "get_active_config",
    "ConnectionConfig",
    "ConfigDict",
    "CONFIG_DIR",
    "CONFIG_FILE",
    # 安全
    "HAS_KEYRING",
]
