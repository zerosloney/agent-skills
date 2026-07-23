#!/usr/bin/env python3
"""数据库浏览器 - 统一 CLI 工具

支持 SQL Server / MySQL / PostgreSQL / SQLite 的连接、查询和结构探索。

子命令:
  连接: connect, list, use, ping
  查询: query, export
  探索: explore (统一，Agent 首选), schema, schemas, columns, indexes,
        foreign-keys, constraints, search, find
  分析: sample, profile
  生成: script, crud
  其他: history, repl

架构:
    db_tool.py (本文件) - 参数解析 + 命令调度
    cli/                   - 命令实现（连接管理/查询/结构探索/数据分析/代码生成/REPL）
    core/config.py         - 配置管理（统一入口）
    core/connection.py     - 连接获取
    _drivers.py            - 数据库驱动适配
    _security.py           - SQL 安全检查
    _formatters.py         - 输出格式化
    _keyring_security.py   - 密钥链密码管理
"""

__version__ = "0.6.0"

import argparse
import sys
from pathlib import Path

# 将脚本所在目录加入 path，以便导入同目录模块
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from _drivers import DRIVERS
from cli import (
    cmd_connect,
    cmd_list,
    cmd_use,
    cmd_ping,
    cmd_query,
    cmd_export,
    cmd_sample,
    cmd_profile,
    cmd_history,
    cmd_explain,
    cmd_script,
    cmd_crud,
    cmd_repl,
    cmd_explore,
    cmd_pipe,
    cmd_learn,
)


def _legacy_explore(object_type: str, detail: str = "names"):
    """返回一个包装函数，将旧版 CLI 子命令参数翻译为 cmd_explore 兼容的 Namespace。"""

    def wrapper(args):
        explore_args = argparse.Namespace(
            object_type=object_type,
            detail="full" if getattr(args, "detail", False) else detail,
            table=getattr(args, "table", None),
            schema=getattr(args, "schema", None),
            pattern=None,
            semantic=None,
            limit=10,
            format="table",
        )
        cmd_explore(explore_args)

    return wrapper


def _legacy_search(args: argparse.Namespace) -> None:
    """旧版 search 命令适配层：路由到 cmd_explore。

    --semantic → explore --semantic --level2=False（保持旧行为：无列数据展开）
    --pattern  → explore --object-type table --pattern（与 explore 行为一致）
    """
    fmt = getattr(args, "format", None) or "table"
    if getattr(args, "semantic", None):
        explore_args = argparse.Namespace(
            object_type="table",
            detail="names",
            table=None,
            schema=getattr(args, "schema", None),
            pattern=None,
            semantic=args.semantic,
            limit=getattr(args, "limit", 5) or 5,
            format=fmt,
            level2=False,  # 旧版 search --semantic 不展开列数据
        )
    else:
        explore_args = argparse.Namespace(
            object_type="table",
            detail="names",
            table=None,
            schema=getattr(args, "schema", None),
            pattern=getattr(args, "pattern", None),
            semantic=None,
            limit=5,
            format=fmt,
            level2=True,
        )
    cmd_explore(explore_args)


def _legacy_find(args: argparse.Namespace) -> None:
    """旧版 find 命令适配层：路由到 cmd_explore --object-type column --pattern。"""
    explore_args = argparse.Namespace(
        object_type="column",
        detail="names",
        table=None,
        schema=None,
        pattern=getattr(args, "pattern", None),
        semantic=None,
        limit=5,
        format=getattr(args, "format", None) or "table",
        level2=True,
    )
    cmd_explore(explore_args)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="db_tool",
        description="数据库浏览器 - 支持 SQL Server / MySQL / PostgreSQL / SQLite",
    )
    parser.add_argument("--version", action="version", version=f"db_tool {__version__}")
    sub = parser.add_subparsers(dest="command", help="子命令")

    # connect
    p = sub.add_parser("connect", help="建立数据库连接")
    p.add_argument("--db-type", choices=list(DRIVERS.keys()), default="sqlserver", help="数据库类型")
    p.add_argument("--server", help="服务器地址")
    p.add_argument("--port", type=int, help="端口号")
    p.add_argument("--database", help="数据库名")
    p.add_argument("--user", help="用户名")
    p.add_argument("--password", help="密码")
    p.add_argument("--name", help="连接别名")
    p.add_argument("--charset", help="字符集")
    p.add_argument("--connection-string", help="完整连接字符串或 URI")
    p.add_argument("--timeout", type=int, default=30, help="查询超时（秒，默认30）")

    # list
    p = sub.add_parser("list", help="列出所有已保存连接")
    p.add_argument("--format", choices=["table", "json", "json-compact"], default="table", help="输出格式（默认 table，纯文本给人读）")

    # use
    p = sub.add_parser("use", help="切换活动连接")
    p.add_argument("name", help="连接名称")

    # ping
    p = sub.add_parser("ping", help="测试连接")
    p.add_argument("--name", help="指定连接名称（默认当前活动）")

    # explore (统一结构探索，Agent 首选)
    p = sub.add_parser("explore", help="统一结构探索（替代 schema/columns/indexes/fk/constraints/search/find）")
    p.add_argument(
        "--object-type",
        choices=["schema", "table", "view", "column", "index", "fk", "constraint", "procedure", "function"],
        default=None,
        help="对象类型（schema/table/view/column/index/fk/constraint/procedure/function）",
    )
    p.add_argument(
        "--detail",
        choices=["names", "summary", "full"],
        default="names",
        help="细节级别: names(仅名称，最省token) / summary(名称+元信息) / full(完整结构)",
    )
    p.add_argument("--schema", help="Schema 名称")
    p.add_argument("--table", help="表名（column/index/fk/constraint 必填）")
    p.add_argument("--pattern", default=None, help="搜索模式 (SQL LIKE %% 和 _)")
    p.add_argument("--semantic", help="语义搜索：自然语言查表（如'订单'、'用户'）")
    p.add_argument("--limit", type=int, default=5, help="语义搜索返回数量")
    p.add_argument(
        "--level2",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="语义搜索两级补全：explore --semantic 默认启用，用 --no-level2 关闭",
    )
    p.add_argument(
        "--format", choices=["json-compact", "json", "table"], default="json-compact", help="输出格式（Agent 默认 json-compact）"
    )

    # 旧版向后兼容子命令（重定向到 explore）
    p = sub.add_parser("schema", help="列出表/视图/存储过程（旧版，建议用 explore --object-type table）")
    p.add_argument("--schema", help="Schema 名称")
    p.add_argument("--detail", action="store_true", help="显示列详情")
    sub.add_parser("schemas", help="列出数据库所有 schema（旧版，建议用 explore --object-type schema）")
    p = sub.add_parser("columns", help="获取表的列信息（旧版，建议用 explore --object-type column）")
    p.add_argument("--table", required=True, help="表名")
    p.add_argument("--schema", help="Schema 名称")
    p = sub.add_parser("indexes", help="获取表的索引信息（旧版，建议用 explore --object-type index）")
    p.add_argument("--table", required=True, help="表名")
    p.add_argument("--schema", help="Schema 名称")
    p = sub.add_parser("foreign-keys", help="显示表的外键关系（旧版，建议用 explore --object-type fk）")
    p.add_argument("--table", required=True, help="表名")
    p.add_argument("--schema", help="Schema 名称")
    p = sub.add_parser("constraints", help="显示表的约束信息（旧版，建议用 explore --object-type constraint）")
    p.add_argument("--table", required=True, help="表名")
    p.add_argument("--schema", help="Schema 名称")

    # query
    p = sub.add_parser("query", help="执行 SQL 查询")
    p.add_argument("--sql", required=True, help="SQL 语句")
    p.add_argument("--max-rows", type=int, default=1000, help="最大返回行数")
    p.add_argument("--offset", type=int, default=0, help="分页偏移")
    p.add_argument("--format", choices=["table", "json", "json-compact", "csv"], default="table", help="输出格式")
    p.add_argument("--timeout", type=int, default=None, help="单次查询超时秒数")
    p.add_argument("--yes", "-y", action="store_true", help="非交互确认：跳过写操作/全表扫描确认（subprocess 调用需先在聊天层获用户同意）")
    p.add_argument("--learn", action="store_true", help="从本次 SQL 中学习表关联/列枚举等知识（写入 query_learned.yaml）")

    # explain
    p = sub.add_parser("explain", help="显示 SQL 查询执行计划")
    p.add_argument("--sql", required=True, help="要分析执行计划的 SQL 语句（仅 SELECT）")
    p.add_argument("--format", choices=["table", "json-compact", "json"], default="table", help="输出格式")

    # learn
    p = sub.add_parser("learn", help="管理学习数据")
    p.add_argument(
        "action",
        choices=["show", "clear", "approve", "delete"],
        nargs="?",
        default="show",
        help="show: 查看学习数据; clear: 清除; approve: 提升到 hot_tables.yaml; delete --table X: 删除指定表的学习数据",
    )
    p.add_argument("--table", help="approve/delete 指定表名")
    p = sub.add_parser("crud", help="生成 CRUD SQL 语句")
    p.add_argument("--table", required=True, help="表名")
    p.add_argument("--schema", help="Schema 名称")

    p = sub.add_parser("script", help="生成建表 DDL 脚本")
    p.add_argument("--table", required=True, help="表名")
    p.add_argument("--schema", help="Schema 名称")

    # export
    p = sub.add_parser("export", help="导出查询结果为 CSV")
    p.add_argument("--sql", required=True, help="SQL SELECT 查询")
    p.add_argument("--filepath", required=True, help="输出文件路径")
    p.add_argument("--encoding", default="utf-8-sig", help="文件编码")
    p.add_argument("--yes", "-y", action="store_true", help="非交互确认：跳过文件覆写确认（subprocess 调用需先在聊天层获用户同意）")

    # search（重定向到 _legacy_search → cmd_explore 统一适配层）
    p = sub.add_parser("search", help="搜索表名（旧版，建议用 explore）")
    p.add_argument("--pattern", default="%", help="搜索模式 (支持 SQL LIKE %% 和 _)")
    p.add_argument("--schema", help="Schema 名称")
    p.add_argument("--semantic", help="语义搜索：使用自然语言查找表（如'订单'、'用户'）")
    p.add_argument("--limit", type=int, default=5, help="语义搜索返回数量")
    p.add_argument("--format", choices=["json-compact", "json", "table"], default="table", help="输出格式")

    # find（重定向到 _legacy_find → cmd_explore 统一适配层）
    p = sub.add_parser("find", help="搜索列名（旧版，建议用 explore --object-type column）")
    p.add_argument("--pattern", default="%", help="搜索模式")
    p.add_argument("--format", choices=["json-compact", "json", "table"], default="table", help="输出格式")

    # sample
    p = sub.add_parser("sample", help="随机采样 N 条记录")
    p.add_argument("--table", required=True, help="表名")
    p.add_argument("--n", type=int, default=5, help="采样数量")
    p.add_argument("--schema", help="Schema 名称")

    # profile
    p = sub.add_parser("profile", help="表快速分析（行数 + 列为 NULL 占比）")
    p.add_argument("--table", required=True, help="表名")
    p.add_argument("--schema", help="Schema 名称")
    p.add_argument("--format", choices=["json-compact", "json", "table"], default="table", help="输出格式")

    # history
    p = sub.add_parser("history", help="查看历史命令记录")
    p.add_argument("--n", type=int, default=50, help="最近 N 条")

    # repl
    p = sub.add_parser("repl", help="进入交互式 SQL 命令行")
    p.add_argument("--schema", help="默认 Schema")
    p.add_argument("--max-rows", type=int, default=1000, help="最大返回行数")

    return parser


def main() -> None:
    # --pipe 模式：优先检测，不走子命令路由
    if "--pipe" in sys.argv:
        cmd_pipe(argparse.Namespace())
        return

    parser = build_parser()
    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    cmd_map = {
        "connect": cmd_connect,
        "list": cmd_list,
        "use": cmd_use,
        "ping": cmd_ping,
        "explore": cmd_explore,
        "query": cmd_query,
        "schema": _legacy_explore("table"),
        "schemas": _legacy_explore("schema"),
        "columns": _legacy_explore("column"),
        "indexes": _legacy_explore("index"),
        "foreign-keys": _legacy_explore("fk"),
        "constraints": _legacy_explore("constraint"),
        "script": cmd_script,
        "crud": cmd_crud,
        "export": cmd_export,
        "search": _legacy_search,
        "find": _legacy_find,
        "sample": cmd_sample,
        "profile": cmd_profile,
        "history": cmd_history,
        "explain": cmd_explain,
        "repl": cmd_repl,
        "learn": cmd_learn,
    }

    fn = cmd_map.get(args.command)
    if fn:
        try:
            fn(args)
        except (RuntimeError, ValueError, ImportError) as e:
            print(f"ERROR: {e}", file=sys.stderr)
            sys.exit(1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
