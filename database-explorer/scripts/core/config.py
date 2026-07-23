#!/usr/bin/env python3
"""
core.config - 连接配置管理模块

提供配置文件的加载、保存、连接管理功能。
支持密钥链安全存储，自动处理密码加密。

Type Definitions:
    ConnectionConfig: 完整的连接配置类型
    ConfigDict: 完整的配置字典类型

Public API:
    save_config: 保存配置
    load_config: 加载配置
    get_active_config: 获取活动连接配置
    CONFIG_DIR: 配置文件目录
    CONFIG_FILE: 配置文件路径
"""

import json
import logging
import os
from pathlib import Path
from typing import Optional, TypedDict, Dict

logger = logging.getLogger(__name__)

from _keyring_security import (
    save_password as _save_password,
    load_password as _load_password,
    _HAS_KEYRING,
)
from _drivers import normalize_db_type


# 配置路径
# 支持通过环境变量 DATABASE_EXPLORER_HOME 重定向配置目录，
# 用于测试隔离（e2e 测试设为 tmp_path，避免污染用户真实 connections.json）。
# 未设置时默认 ~/.database-explorer。
_HOME_OVERRIDE = os.environ.get("DATABASE_EXPLORER_HOME")
CONFIG_DIR: Path = Path(_HOME_OVERRIDE) if _HOME_OVERRIDE else Path.home() / ".database-explorer"
CONFIG_FILE: Path = CONFIG_DIR / "connections.json"


# ═══════════════════════════════════════════════════════════════
#  类型定义
# ═══════════════════════════════════════════════════════════════


class ConnectionConfig(TypedDict, total=False):
    """连接配置类型定义

    Attributes:
        db_type: 数据库类型 (sqlite/mysql/postgresql/sqlserver)
        server: 服务器地址
        database: 数据库名
        user: 用户名
        password: 密码（存储到密钥链后为 None）
        port: 端口
        timeout: 超时时间
        _keyring_ref: 是否使用密钥链
    """

    db_type: str
    server: str
    database: str
    user: str
    password: Optional[str]
    port: Optional[int]
    timeout: Optional[int]
    _keyring_ref: bool
    _name: str


class ConfigDict(TypedDict):
    """完整配置字典类型

    Attributes:
        active: 当前活动连接名
        connections: 所有连接配置字典
    """

    active: Optional[str]
    connections: Dict[str, ConnectionConfig]


# ═══════════════════════════════════════════════════════════════
#  密码处理辅助函数
# ═══════════════════════════════════════════════════════════════


def _save_connection_password(conn_name: str, conn_cfg: dict) -> None:
    """保存单个连接的密码到密钥链或配置文件

    如果系统支持密钥链（_HAS_KEYRING=True），
    密码将存储到系统密钥链，配置文件中只保留引用标记。

    Args:
        conn_name: 连接名称
        conn_cfg: 连接配置字典（原地修改 password 字段）

    Raises:
        RuntimeError: 密码无法安全存储（keyring 未安装或保存失败）
    """
    password: Optional[str] = conn_cfg.get("password")
    if not password:
        return

    # 使用密钥链存储密码
    try:
        saved: Optional[str] = _save_password(conn_name, password, use_keyring=_HAS_KEYRING)
    except RuntimeError:
        # keyring 不可用或保存失败 — 向上抛出，由调用方处理
        raise

    if saved:
        # 传统方式返回加密字符串
        conn_cfg["password"] = saved
    else:
        # 密钥链方式返回 None
        conn_cfg["password"] = None
        if _HAS_KEYRING:
            conn_cfg["_keyring_ref"] = True


def _load_config_file() -> Optional[dict]:
    """加载配置文件 JSON 内容

    Returns:
        配置字典，文件不存在或格式错误时返回 None
    """
    if not CONFIG_FILE.exists():
        return None
    try:
        return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _restore_connection_password(conn_name: str, conn_cfg: dict) -> None:
    """从密钥链或配置文件恢复单个连接的密码

    Args:
        conn_name: 连接名称
        conn_cfg: 连接配置字典（原地修改 password 字段）
    """
    # 尝试从密钥链或配置文件读取密码
    password: str = _load_password(conn_name, conn_cfg)
    if password:
        conn_cfg["password"] = password
    elif conn_cfg.get("_keyring_ref"):
        # 密钥链标记但密码为空，可能需要重新配置
        pass


# ═══════════════════════════════════════════════════════════════
#  文件操作辅助函数
# ═══════════════════════════════════════════════════════════════


def _write_config_file(cfg: dict) -> None:
    """写入配置文件到磁盘（原子写入）

    先写到同目录临时文件，设置权限后原子重命名为目标文件。
    消除崩溃损坏风险和权限暴露窗口。

    Args:
        cfg: 要保存的配置字典
    """
    # 确保父目录存在
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

    content = json.dumps(cfg, ensure_ascii=False, indent=2)
    tmp_file = CONFIG_FILE.with_suffix(".tmp")

    # 写入临时文件
    tmp_file.write_text(content, encoding="utf-8")

    # Unix: 在临时文件上设置权限（rename 后权限跟随）
    if os.name == "posix":
        try:
            os.chmod(tmp_file, 0o600)
        except OSError:
            logger.warning("无法设置配置文件权限为 600: %s", tmp_file, exc_info=True)

    # 原子重命名：POSIX 用 os.replace（保证原子），Windows 用 os.replace（NTFS 上原子）
    os.replace(tmp_file, CONFIG_FILE)


# ═══════════════════════════════════════════════════════════════
#  公共 API
# ═══════════════════════════════════════════════════════════════


def save_config(cfg: dict) -> None:
    """保存连接配置（使用密钥链存储密码）

    自动处理密码安全：
    - 优先使用系统密钥链存储
    - 清理配置文件中的明文密码
    - 配置文件权限保护

    Args:
        cfg: 完整的配置字典，包含 active 和 connections

    Examples:
        >>> cfg = {
        ...     "active": "prod",
        ...     "connections": {
        ...         "prod": {
        ...             "db_type": "sqlserver",
        ...             "server": "localhost",
        ...             "database": "mydb",
        ...             "user": "sa",
        ...             "password": "secret"
        ...         }
        ...     }
        ... }
        >>> save_config(cfg)
    """
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    # 处理所有连接的密码存储
    for name, conn_cfg in cfg.get("connections", {}).items():
        try:
            _save_connection_password(name, conn_cfg)
        except RuntimeError as e:
            # 密码无法安全存储 — 向上抛出，由 CLI 层向用户报告
            raise RuntimeError(f"连接 '{name}' 的密码无法安全存储：{e}") from e

    # 写入配置文件
    _write_config_file(cfg)


def load_config() -> dict:
    """加载连接配置（从密钥链或配置文件读取密码）

    自动恢复密码：
    - 从系统密钥链读取（如果标记了 _keyring_ref）
    - 从配置文件中恢复（兼容旧格式）
    - 支持自动迁移旧密码到密钥链

    Returns:
        配置字典，包含:
        - active: 当前活动连接名
        - connections: 所有连接配置字典

    Examples:
        >>> cfg = load_config()
        >>> cfg['active']
        'prod'
        >>> cfg['connections']['prod']['password']
        'secret'
    """
    raw = _load_config_file()
    if raw is None:
        return {"active": None, "connections": {}}

    # 恢复所有连接的密码，并归一化 db_type 别名（如 mssql → sqlserver）
    conns = raw.get("connections", {})
    for name, conn_cfg in conns.items():
        _restore_connection_password(name, conn_cfg)
        if "db_type" in conn_cfg:
            conn_cfg["db_type"] = normalize_db_type(conn_cfg["db_type"])

    raw["connections"] = conns
    return raw


def get_active_config() -> dict:
    """获取当前活动连接的配置（确保密码已加载）

    强制从密钥链加载密码（如果连接标记了 _keyring_ref）。

    Returns:
        活动连接的配置字典，包含 _name 字段标识连接名

    Raises:
        RuntimeError: 无活动连接
        RuntimeError: 密钥链密码无法加载
    """
    cfg = load_config()
    name: Optional[str] = cfg.get("active")
    if not name or name not in cfg.get("connections", {}):
        raise RuntimeError("ERROR: 无活动连接，请先使用 connect 命令建立连接")

    conn_cfg = cfg["connections"][name]

    # 确保密码已加载（处理密钥链）
    if not conn_cfg.get("password") and conn_cfg.get("_keyring_ref"):
        password: str = _load_password(name, conn_cfg)
        if password:
            conn_cfg["password"] = password
        else:
            raise RuntimeError(f"ERROR: 无法从密钥链读取 '{name}' 的密码")

    return {**conn_cfg, "_name": name}


# ═══════════════════════════════════════════════════════════════
#  向后兼容性别名
# ═══════════════════════════════════════════════════════════════

# 为旧代码提供向后兼容
HAS_KEYRING: bool = _HAS_KEYRING


__all__ = [
    "ConnectionConfig",
    "ConfigDict",
    "save_config",
    "load_config",
    "get_active_config",
    "CONFIG_DIR",
    "CONFIG_FILE",
    "HAS_KEYRING",
]
