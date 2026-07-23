#!/usr/bin/env python3
"""
core.history - 命令历史记录

统一 query 命令与 REPL 的历史写入,让 Agent 走 subprocess 调用 query 时
也能产生 history 记录(此前 history.txt 仅由 REPL 内部闭包写入,
导致 SKILL.md §2.4 的 history 命令在 Agent 路径下永远返回"无历史记录")。

存储: <CONFIG_DIR>/history.txt,追加写,超过 _MAX_HISTORY_LINES 行自动轮转。
"""

import logging
from pathlib import Path

from .config import CONFIG_DIR

logger = logging.getLogger(__name__)

_HISTORY_PATH: Path = CONFIG_DIR / "history.txt"
_MAX_HISTORY_LINES = 1000


def append_history(command: str) -> None:
    """追加一条命令到 history.txt 并按需轮转。

    Args:
        command: 完整命令原文(SQL 或命令行)。与 REPL 行为一致,不截断。
            history.txt 是用户私有文件(由 config 层 0o600 权限保障目录)。
    """
    if not command:
        return
    try:
        _HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(_HISTORY_PATH, "a", encoding="utf-8") as h:
            h.write(command + "\n")
        _rotate_history_if_needed()
    except Exception:
        logger.debug("failed to write history", exc_info=True)


def _rotate_history_if_needed() -> None:
    """超过 _MAX_HISTORY_LINES 行时保留最后 _MAX_HISTORY_LINES 行。"""
    try:
        with open(_HISTORY_PATH, "r", encoding="utf-8") as h:
            lines = h.readlines()
        if len(lines) > _MAX_HISTORY_LINES:
            with open(_HISTORY_PATH, "w", encoding="utf-8") as h:
                h.writelines(lines[-_MAX_HISTORY_LINES:])
    except Exception:
        logger.debug("history rotation failed (non-critical)", exc_info=True)


__all__ = ["append_history"]
