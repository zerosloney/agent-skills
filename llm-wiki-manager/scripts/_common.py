"""
LLM Wiki Manager 公共工具模块

提供所有脚本共享的基础函数，消除跨脚本代码重复。

用法:
    from _common import get_wiki_root, WikiError, ErrorCode

    wiki_root = get_wiki_root()

    # 抛出错误
    raise WikiError(
        ErrorCode.CACHE_CORRUPTED,
        "缓存文件损坏",
        recovery_hint="运行: python scripts/wiki.py cache sync"
    )
"""

import hashlib
import os
import sys
from enum import Enum
from pathlib import Path
from typing import Optional


# ═══════════════════════════════════════════════════════════════════════
# 错误处理
# ═══════════════════════════════════════════════════════════════════════


class ErrorCode(Enum):
    """统一错误码"""

    # 环境错误 (1xx)
    WIKI_ROOT_NOT_SET = 101
    WIKI_ROOT_NOT_EXIST = 102
    INVALID_PATH = 103

    # 文件错误 (2xx)
    FILE_NOT_FOUND = 201
    FILE_CORRUPTED = 202
    FILE_PERMISSION_DENIED = 203
    ENCODING_ERROR = 204

    # 缓存错误 (3xx)
    CACHE_CORRUPTED = 301
    CACHE_MISSING = 302
    CACHE_INCONSISTENT = 303

    # 索引错误 (4xx)
    INDEX_CORRUPTED = 401
    INDEX_MISSING = 402
    INDEX_INCONSISTENT = 403
    CONCEPTS_INDEX_CORRUPTED = 404
    CONCEPTS_INDEX_MISSING = 405

    # 数据错误 (5xx)
    FRONTMATTER_INVALID = 501
    ENTITY_TYPE_INVALID = 502
    SOURCE_NOT_FOUND = 503
    CIRCULAR_REFERENCE = 504

    # 操作错误 (6xx)
    OPERATION_FAILED = 601
    VALIDATION_FAILED = 602
    COMPILATION_FAILED = 603
    SEARCH_FAILED = 604

    # 状态错误 (7xx)
    STATE_INCONSISTENT = 701
    CONCURRENT_MODIFICATION = 702


class WikiError(Exception):
    """Wiki 统一异常类

    用法:
        raise WikiError(
            ErrorCode.CACHE_CORRUPTED,
            "缓存文件损坏",
            recovery_hint="运行: python scripts/wiki.py cache sync",
            details={"file": cache_file}
        )
    """

    def __init__(
        self, code: ErrorCode, message: str, recovery_hint: Optional[str] = None, details: Optional[dict] = None
    ):
        self.code = code
        self.message = message
        self.recovery_hint = recovery_hint
        self.details = details or {}
        super().__init__(self.format_message())

    def format_message(self) -> str:
        """格式化错误信息"""
        lines = [
            f"❌ 错误 [{self.code.name}]: {self.message}",
        ]

        if self.details:
            lines.append(f"   详情: {self.details}")

        if self.recovery_hint:
            lines.append(f"   修复: {self.recovery_hint}")

        return "\n".join(lines)

    def exit(self, exit_code: int = 1):
        """打印错误信息并退出"""
        print(self.format_message(), file=sys.stderr)
        sys.exit(exit_code)


def handle_error(func):
    """错误处理装饰器

    用法:
        @handle_error
        def main():
            ...
    """

    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except WikiError as e:
            e.exit()
        except KeyboardInterrupt:
            print("\n⚠️  操作已取消", file=sys.stderr)
            sys.exit(130)
        except Exception as e:
            print(f"❌ 未预期的错误: {e}", file=sys.stderr)
            import traceback

            traceback.print_exc()
            sys.exit(1)

    return wrapper


# ═══════════════════════════════════════════════════════════════════════
# 路径和环境
# ═══════════════════════════════════════════════════════════════════════


def get_wiki_root() -> str:
    """获取 wiki 根目录：环境变量 WIKI_ROOT > .wiki_root 文件 > 平台默认 ~/wiki/"""
    # 1. 环境变量
    env = os.environ.get("WIKI_ROOT")
    if env:
        return env.replace("\\", "/")

    # 2. .wiki_root 文件
    wiki_root_file = Path(".wiki_root")
    if wiki_root_file.exists():
        try:
            return wiki_root_file.read_text(encoding="utf-8").strip()
        except Exception:
            pass

    # 3. 默认 ~/wiki
    return str(Path.home() / "wiki")


def ensure_wiki_root() -> Path:
    """确保 wiki_root 存在，返回 Path 对象"""
    wiki_root = Path(get_wiki_root())
    if not wiki_root.exists():
        raise WikiError(
            ErrorCode.WIKI_ROOT_NOT_EXIST,
            f"Wiki 根目录不存在: {wiki_root}",
            recovery_hint="运行: python scripts/wiki.py init",
        )
    return wiki_root


def resolve_path(relative_path: str) -> str:
    """解析相对于 wiki_root 的绝对路径"""
    wiki_root = get_wiki_root()
    return os.path.join(wiki_root, relative_path)


# ═══════════════════════════════════════════════════════════════════════
# 文件哈希
# ═══════════════════════════════════════════════════════════════════════


def body_for_hash(content: str) -> str:
    """提取 body（跳过 frontmatter），供 SHA256 哈希使用"""
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end > 0:
            return content[end + 5 :]
    return content


def file_hash(content: str, length: int = 16) -> str:
    """Body-only SHA256 哈希，返回前 length 位 hex"""
    return hashlib.sha256(body_for_hash(content).encode("utf-8")).hexdigest()[:length]


# ═══════════════════════════════════════════════════════════════════════
# 幂等性支持
# ═══════════════════════════════════════════════════════════════════════


class IdempotencyTracker:
    """幂等性追踪器

    用于记录已处理的项目，避免重复处理。

    用法:
        tracker = IdempotencyTracker("compile_post")

        for file in files:
            if tracker.is_processed(file):
                print(f"跳过已处理: {file}")
                continue

            # 处理文件
            process(file)

            # 标记为已处理
            tracker.mark_processed(file)
    """

    def __init__(self, operation_name: str):
        """初始化追踪器

        Args:
            operation_name: 操作名称（如 "compile_post", "detect_concepts"）
        """
        self.operation_name = operation_name
        wiki_root = Path(get_wiki_root())
        self.tracker_dir = wiki_root / ".cache" / "idempotency"
        self.tracker_dir.mkdir(parents=True, exist_ok=True)
        self.tracker_file = self.tracker_dir / f"{operation_name}.txt"
        self._processed = self._load()

    def _load(self) -> set:
        """加载已处理项目"""
        if not self.tracker_file.exists():
            return set()

        try:
            content = self.tracker_file.read_text(encoding="utf-8")
            return set(line.strip() for line in content.split("\n") if line.strip())
        except Exception:
            return set()

    def _save(self):
        """保存已处理项目"""
        try:
            self.tracker_file.write_text("\n".join(sorted(self._processed)), encoding="utf-8")
        except Exception as e:
            print(f"⚠️  警告: 无法保存幂等性追踪: {e}", file=sys.stderr)

    def is_processed(self, item: str) -> bool:
        """检查项目是否已处理"""
        return item in self._processed

    def mark_processed(self, item: str):
        """标记项目为已处理"""
        self._processed.add(item)
        self._save()

    def unmark(self, item: str):
        """取消标记（用于重新处理）"""
        self._processed.discard(item)
        self._save()

    def clear(self):
        """清空所有标记"""
        self._processed.clear()
        if self.tracker_file.exists():
            self.tracker_file.unlink()

    def get_processed_count(self) -> int:
        """获取已处理项目数量"""
        return len(self._processed)
