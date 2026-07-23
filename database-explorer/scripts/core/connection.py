#!/usr/bin/env python3
"""
core.connection - 连接管理模块

提供数据库连接的获取和管理功能。

Public API:
    get_connection: 获取当前活动连接
    ConnectionConfig: 完整的连接配置类型
"""

from typing import Tuple
from sqlalchemy.engine import Engine

from _drivers import connect as _driver_connect
from .config import get_active_config, ConnectionConfig


def get_connection() -> Tuple[Engine, dict]:
    """获取当前活动连接和配置

    自动处理：
    - 活动连接配置加载
    - 密码从密钥链恢复
    - 数据库引擎创建

    Returns:
        (Engine, dict) 元组:
        - Engine: SQLAlchemy 数据库引擎
        - dict: 完整的连接配置字典

    Raises:
        RuntimeError: 无活动连接或密码加载失败

    Examples:
        >>> engine, cfg = get_connection()
        >>> cfg['_name']
        'prod'
        >>> result = engine.connect().execute("SELECT 1")
    """
    cfg: dict = get_active_config()
    conn: Engine = _driver_connect(cfg)
    return conn, cfg


__all__ = ["get_connection", "ConnectionConfig"]
