#!/usr/bin/env python3
"""
cli.connection_cmds - 连接管理命令

实现 connect、list、use、ping 等连接管理相关的 CLI 命令。
"""

import argparse
import logging

logger = logging.getLogger(__name__)

from core.config import load_config, save_config, get_active_config
from _drivers import (
    connect as driver_connect,
    parse_connection_uri,
    DRIVERS,
    normalize_db_type,
)


def cmd_connect(args: argparse.Namespace) -> None:
    """建立数据库连接并保存配置"""
    cfg = load_config()

    # 解析连接参数
    if args.connection_string:
        parsed = parse_connection_uri(args.connection_string)
        if not parsed:
            raise RuntimeError("无法解析连接字符串")
        conn_cfg = parsed
        db_type = conn_cfg.get("db_type", "sqlserver")
    else:
        db_type = normalize_db_type(args.db_type or "sqlserver")
        driver_info = DRIVERS.get(db_type, {})

        conn_cfg = {
            "db_type": db_type,
            "server": args.server or "localhost",
            "database": args.database or ("master" if db_type == "sqlserver" else db_type),
            "user": args.user or driver_info.get("default_user", ""),
            "password": args.password or "",
        }
        if args.port:
            conn_cfg["port"] = args.port
        elif driver_info.get("default_port"):
            conn_cfg["port"] = driver_info["default_port"]
        if args.charset:
            conn_cfg["charset"] = args.charset
        conn_cfg["timeout"] = args.timeout

    # 验证必要参数
    if db_type != "sqlite" and not conn_cfg.get("user"):
        raise RuntimeError("必须提供用户名 (--user)")

    # 测试连接
    name = args.name or f"{db_type}@{conn_cfg.get('server', 'local')}"
    try:
        conn = driver_connect(conn_cfg)
        conn.dispose()
    except Exception as e:
        logger.debug("connect test failed: %s", e, exc_info=True)
        from _security import sanitize_error

        raise RuntimeError(f"连接失败 - {sanitize_error(e)}")

    # 保存配置
    cfg["connections"][name] = conn_cfg
    cfg["active"] = name
    try:
        save_config(cfg)
    except RuntimeError as e:
        raise RuntimeError(f"{e}\n连接测试成功但密码未能安全存储，请安装 keyring 后重新连接。") from e

    print(f"已连接: {name}")
    print(f"  类型: {conn_cfg.get('db_type')}")
    print(f"  服务器: {conn_cfg.get('server', 'N/A')}")
    print(f"  数据库: {conn_cfg.get('database')}")


def cmd_list(args: argparse.Namespace) -> None:
    """列出所有已保存的连接"""
    # repl_cmds.py 以空 Namespace() 调用本函数，这里兜底
    fmt = getattr(args, "format", "table")

    cfg = load_config()
    connections = cfg.get("connections", {})
    active = cfg.get("active")

    if not connections:
        print("无已保存的连接")
        return

    # 结构化数据，供各格式共用
    items = []
    for name, conn_cfg in connections.items():
        items.append(
            {
                "name": name,
                "active": name == active,
                "db_type": conn_cfg.get("db_type", "?"),
                "server": conn_cfg.get("server", "N/A"),
                "database": conn_cfg.get("database", "?"),
            }
        )

    if fmt == "json":
        import json

        print(json.dumps({"active": active, "connections": items}, ensure_ascii=False, indent=2))
        return

    if fmt == "json-compact":
        import json

        compact = {
            "active": active,
            "connections": [
                {
                    "name": it["name"],
                    "current": 1 if it["active"] else 0,
                    "type": it["db_type"],
                    "server": it["server"],
                    "database": it["database"],
                }
                for it in items
            ],
        }
        print(json.dumps(compact, ensure_ascii=False))
        return

    # table（默认，纯文本，给人读）
    for it in items:
        marker = " ← 当前" if it["active"] else ""
        print(f"- {it['name']}{marker}")
        print(f"    类型: {it['db_type']}")
        print(f"    服务器: {it['server']}")
        print(f"    数据库: {it['database']}")


def cmd_use(args: argparse.Namespace) -> None:
    """切换活动连接"""
    cfg = load_config()
    name = args.name

    if name not in cfg.get("connections", {}):
        available = ", ".join(cfg.get("connections", {}).keys()) or "无"
        raise RuntimeError(f"连接 '{name}' 不存在。可用连接: {available}")

    cfg["active"] = name
    save_config(cfg)
    conn_cfg = cfg["connections"][name]
    print(f"已切换到: {name} ({conn_cfg.get('db_type')} - {conn_cfg.get('server', 'local')}/{conn_cfg.get('database')})")


def cmd_ping(args: argparse.Namespace) -> None:
    """测试连接"""
    from sqlalchemy import text

    if args.name:
        cfg = load_config()
        if args.name not in cfg.get("connections", {}):
            raise RuntimeError(f"连接 '{args.name}' 不存在")
        conn_cfg = cfg["connections"][args.name]
    else:
        conn_cfg = get_active_config()

    try:
        conn = driver_connect(conn_cfg)
        with conn.connect() as connection:
            connection.execute(text("SELECT 1"))
        conn.dispose()
        name = conn_cfg.get("_name", args.name or "当前")
        print(f"连接正常: {name} ({conn_cfg.get('db_type')} - {conn_cfg.get('server', 'local')}/{conn_cfg.get('database')})")
    except Exception as e:
        logger.debug("ping failed: %s", e, exc_info=True)
        from _security import sanitize_error

        raise RuntimeError(f"连接失败: {sanitize_error(e)}")
