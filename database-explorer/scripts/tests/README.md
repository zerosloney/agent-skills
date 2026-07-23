# 回归测试套件

database-explorer skill 的持久化测试，覆盖两轮 P0 修复的全部行为。

## 运行

```bash
# 全部测试（含 e2e subprocess 调用，较慢）
python -m pytest tests/ -q

# 仅单元测试（<1s，无需数据库）
python -m pytest tests/test_security.py tests/test_drivers.py tests/test_safe.py -q

# 仅 e2e（subprocess 模拟 Agent 调用，需 Python sqlite3）
python -m pytest tests/test_e2e_cli.py -v

# 单个测试类/方法
python -m pytest tests/test_security.py::TestCheckReadOnly -v
python -m pytest tests/test_security.py::TestCheckReadOnly::test_string_literal_no_false_positive -v
```

> **可选依赖**：`test_query_learning.py` 中 CTE/UNION/子查询相关测试需 `sqlglot`
> （未装时自动 skip）；`test_perf.py` 的语义索引测试在装了 SBERT 的环境 skip
> （避免模型加载拖慢 CI）。安装：`pip install database-explorer[learn]`。

## 测试文件

| 文件 | 覆盖 | 关联 P0 |
|------|------|---------|
| `test_security.py` | `_security.py` 全部纯函数：strip_strings/check_read_only/is_full_table_scan/is_protected_path/count_statements/quote_ident/sanitize_error | P0-1/P0-2/第一轮 |
| `test_drivers.py` | `_drivers.py`：default_schema/list_schemas/_engine_db_type/fetch_semantic_index（缓存+覆盖）、execute_query max_rows/timeout RESET、connect() SQLite 真实路径。用 SQLite 内存库做真实集成 | P0-1/P0-3 |
| `test_safe.py` | `cli/safe.py`：confirm_danger/confirm_overwrite 的 confirmed 通道与 EOF 行为 | 第一轮 P0-3 |
| `test_e2e_cli.py` | 端到端 subprocess：query 写确认/全表扫描、export 护栏、search 覆盖、schemas、多语句注入、explore 全 object-type、learn/explain/pipe | 全部 |
| `test_config.py` | `core/config.py`：save/load_config 往返、密码明文不落盘、db_type 别名归一化（mssql→sqlserver）、get_active_config | — |
| `test_error_handling.py` | `_drivers.py` 错误路径：execute_query 网络/超时/非法 SQL、get_tables/get_columns 权限降级、_check_driver 不支持类型、connect 不可达主机（mock）、corrupted YAML 恢复 | 第一轮 |
| `test_formatters.py` | `_formatters.py`：JSONEncoder bytes 处理（UTF-8/hex fallback）、format_result 的 json/json-compact/markdown/csv 路径含 bytes 不崩溃 | — |
| `test_keyring.py` | `_keyring_security.py`：save/load/delete_password 往返、check_security_level（keyring HIGH / 明文 INSECURE）、migrate_all_connections 旧版密码警告 | — |
| `test_pipe.py` | `--pipe` JSON-RPC 协议：connect/ping/explore 端到端、未知 method -32601、畸形 JSON -32700、explain 在 pipe 下正确 | — |
| `test_query_learning.py` | `_query_learning.py`：extract_tables/columns/associations/column_enums/knowledge（含 CTE/UNION/子查询，sqlglot 专属用 @skipif 守卫）、_merge_learned、record_query/clear_learned 持久化、隐私列过滤 | 第二轮 |
| `test_scoring.py` | `_scoring.py`：score_table 基础/IDF/别名打分、load_hot_tables 缓存失效、build_semantic_matches（stub 表、FK 传递闭包、2-hop 衰减、环路保护） | 第二轮 |
| `test_perf.py` | 性能回归护栏：语义搜索冷启动阈值（<2s，装 SBERT 的环境 skip）、json-compact vs table 体积对比、explore table 速度（<3s） | — |

## 设计原则

1. **零外部依赖**：单元测试纯函数；e2e 用 SQLite 文件库（Python 自带，无驱动），不连真实数据库
2. **隔离**：e2e 每个测试用独立 `tmp_path` 建库，不污染全局 `connections.json`
3. **真实调用路径**：e2e 通过 subprocess 调 `db_tool.py`，模拟 Agent 真实调用（无交互 TTY），验证 `--yes` 通道与无 TTY 时的拒绝行为
4. **回归保护**：每个 P0 修复都有对应测试——未来改代码若回退行为，测试会立即失败

## 当 P0 修复被回退时，哪些测试会红

| 回退的行为 | 失败的测试 |
|-----------|-----------|
| export 不再检查写操作 | `test_e2e_cli::TestExportGuardrails::test_export_write_sql_rejected` |
| check_read_only 恢复字面量误报 | `test_security::TestCheckReadOnly::test_string_literal_no_false_positive`（7 用例） |
| fetch_semantic_index 恢复 500 截断 | `test_drivers::TestFetchSemanticIndex::test_covers_all_tables` + e2e search |
| confirm_danger 不再支持 --yes | `test_safe::TestConfirmDanger::test_write_confirmed_yes` + e2e |
| is_protected_path 失效 | `test_security::TestIsProtectedPath::test_protected_paths_blocked`（7 用例） |
| default_schema 回退硬编码 | `test_drivers::TestDefaultSchema`（5 用例） |
