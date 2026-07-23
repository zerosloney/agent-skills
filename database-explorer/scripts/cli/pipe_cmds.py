#!/usr/bin/env python3
"""
cli.pipe_cmds - 常驻进程模式（JSON-RPC over stdin/stdout）

Agent 通过 subprocess 启动 `db_tool.py --pipe`，进程持续运行，
通过 stdin/stdout 交换 JSON-RPC 请求/响应，避免每次命令重启进程和重建连接。

协议：
  请求: {"jsonrpc":"2.0","id":1,"method":"<command>","params":{...}}
  响应: {"jsonrpc":"2.0","id":1,"result":{...}} 或 {"jsonrpc":"2.0","id":1,"error":{...}}

支持的方法: explore, query, sample, profile, crud, script, export, history,
            learn, connect, list, use, ping, schema, schemas, columns, indexes,
            foreign-keys, constraints, search, find

关闭: 发送 {"method":"exit"} 或关闭 stdin。
"""

import argparse
import json
import sys
import logging
from typing import Any

logger = logging.getLogger(__name__)

from _semantic_index import invalidate_semantic_cache
from _security import sanitize_error

from .explore_cmds import cmd_explore
from .query_cmds import cmd_query, cmd_export
from .data_cmds import cmd_sample, cmd_profile, cmd_search, cmd_find, cmd_history, cmd_explain
from .codegen_cmds import cmd_script, cmd_crud
from .learn_cmds import cmd_learn
from .connection_cmds import cmd_connect, cmd_list, cmd_use, cmd_ping


class _PipeCapture:
    """捕获 stdout 输出，替代 print 直写。"""

    def __init__(self) -> None:
        self._lines: list[str] = []

    def write(self, text: str) -> None:
        if text:
            self._lines.append(text)

    def get(self) -> str:
        return "".join(self._lines).rstrip("\n")

    def clear(self) -> None:
        self._lines.clear()


def _build_args(method: str, params: dict) -> argparse.Namespace:
    """从 JSON-RPC 参数构建 argparse.Namespace，补全缺失的默认值。

    各命令按自身需求补全默认参数，避免 pipe 模式因参数丢失导致意外行为。
    """
    ns = argparse.Namespace()
    for k, v in params.items():
        k_clean = k.replace("-", "_")
        setattr(ns, k_clean, v)

    # 通用默认值（所有命令共享）
    if not hasattr(ns, "format"):
        if method == "explore":
            setattr(ns, "format", "json-compact")
        elif method == "query":
            setattr(ns, "format", params.get("format", "json-compact"))
        else:
            setattr(ns, "format", params.get("format", "table"))
    if not hasattr(ns, "command"):
        setattr(ns, "command", method)

    # 按命令补全特定默认值
    _defaults: dict[str, dict] = {
        "explore": {"detail": "names", "limit": 5, "pattern": None, "schema": None, "table": None, "semantic": None, "object_type": None},
        "query": {"max_rows": 1000, "offset": 0, "timeout": None, "yes": False, "learn": False},
        "ping": {"name": None},
        "sample": {"n": 10, "schema": None},
        "profile": {"schema": None},
        "export": {"encoding": "utf-8-sig", "yes": False},
        "search": {"pattern": "%", "limit": 5, "schema": None},
        "find": {"pattern": "%"},
        "history": {"n": 50},
        "crud": {"schema": None},
        "script": {"schema": None},
        "learn": {"action": "show", "table": None},
    }
    for key, val in _defaults.get(method, {}).items():
        if not hasattr(ns, key):
            setattr(ns, key, val)

    return ns


_CMD_HANDLERS: dict[str, Any] = {
    "explore": cmd_explore,
    "query": cmd_query,
    "export": cmd_export,
    "sample": cmd_sample,
    "profile": cmd_profile,
    "search": cmd_search,
    "find": cmd_find,
    "history": cmd_history,
    "explain": cmd_explain,
    "script": cmd_script,
    "crud": cmd_crud,
    "learn": cmd_learn,
    "connect": cmd_connect,
    "list": cmd_list,
    "use": cmd_use,
    "ping": cmd_ping,
}


def cmd_pipe(args: argparse.Namespace) -> None:
    """常驻进程模式入口。"""
    _send({"jsonrpc": "2.0", "method": "ready", "params": {"pid": __import__("os").getpid()}})

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            _send_error(None, -32700, "Parse error")
            continue

        req_id = request.get("id")
        method = request.get("method", "")
        params = request.get("params", {})

        if method == "exit":
            _send_result(req_id, {"status": "exiting"})
            break

        handler = _CMD_HANDLERS.get(method)
        if not handler:
            _send_error(req_id, -32601, f"Method not found: {method}")
            continue

        try:
            cmd_args = _build_args(method, params)
            capture = _PipeCapture()
            old_stdout = sys.stdout
            sys.stdout = capture
            try:
                handler(cmd_args)
            finally:
                sys.stdout = old_stdout

            # 连接切换后清除语义缓存，确保下次搜索拿到最新 schema
            if method in ("connect", "use"):
                invalidate_semantic_cache()
                from _scoring import invalidate_hot_tables_cache

                invalidate_hot_tables_cache()

            output = capture.get()
            if output:
                try:
                    parsed = json.loads(output)
                    _send_result(req_id, parsed)
                except json.JSONDecodeError:
                    _send_result(req_id, {"output": output})
            else:
                _send_result(req_id, {"status": "ok"})

        except (RuntimeError, ValueError) as e:
            _send_error(req_id, -32000, str(e))
        except Exception as e:
            logger.debug("pipe handler error: %s", e, exc_info=True)
            _send_error(req_id, -32603, sanitize_error(e))


def _send(msg: dict) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _send_result(req_id: Any, result: dict) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _send_error(req_id: Any, code: int, message: str) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}})
