# Commands Reference：命令参数百科

> **职责契约**：本文档是 database-explorer skill 的**唯一命令参数权威源**。
> 只包含：完整命令的参数规格（必填/可选/默认值/示例）+ 连接状态格式。
> 不包含：安全规则（→ SKILL.md §4）、错误处理（→ troubleshooting.md）、方言差异（→ SKILL.md §5）。
>
> Agent 使用路径：SKILL.md §2 确定用哪个命令 → 本文档查参数细节 → 执行。

## 连接管理

| 命令 | 用途 | 必填参数 | 常用可选参数 | 示例 |
|---|---|---|---|---|
| `connect` | 建立新连接 | `--db-type` | `--server` `--database` `--user` `--password` `--port` `--name` `--charset` `--timeout` `--connection-string` | `--db-type sqlserver --server localhost --database master --user sa --password pwd --name prod --timeout 30` |
| `connect` | 通过 URI 连接 | `--db-type` `--connection-string` | `--name` | `--db-type mysql --connection-string "mysql://root:pwd@localhost:3306/mydb"` |
| `list` | 列出所有连接 | — | `--format` | `--format json-compact` |
| `use` | 切换活动连接 | 位置参数 `name` | — | `prod` |
| `ping` | 测试连接 | — | `--name` | `[--name prod]` |

## 数据查询

| 命令 | 用途 | 必填参数 | 常用可选参数 | 示例 |
|---|---|---|---|---|
| `query` | 执行 SQL | `--sql` | `--max-rows` `--offset` `--format` `--yes` `--timeout` `--learn` | `--sql "SELECT ..." --max-rows 100 --format json-compact` |
| `query` | CSV 导出查询结果 | `--sql` | `--format csv` | `--sql "SELECT ..." --format csv > out.csv` |
| `query` | 学习模式 | `--sql` | `--learn` | `--sql "SELECT ... JOIN ..." --learn` |
| `explain` | 显示执行计划 | `--sql` | `--format` | `--sql "SELECT ..." --format json-compact` |
| `search` | 搜索表名（pattern） | — | `--pattern` `--schema` `--format` | `--pattern "%user%" --schema dbo` |
| `search` | 语义搜索 | — | `--semantic` `--limit` `--format` | `--semantic "订单" --limit 5` |
| `find` | 搜索列名 | `--pattern` | `--format` | `--pattern "%email%"` |
| `export` | 导出 CSV | `--sql` `--filepath` | `--encoding` `--yes` | `--sql "SELECT ..." --filepath out.csv` |
| `sample` | 随机采样 | `--table` | `--n` `--schema` | `--table users --n 5` |
| `profile` | 表统计分析 | `--table` | `--schema` `--format` | `--table users` |

## 结构探索

| 命令 | 用途 | 必填参数 | 常用可选参数 | 示例 |
|---|---|---|---|---|
| `explore` | 统一结构探索（Agent 首选） | — | `--object-type` `--detail` `--schema` `--table` `--pattern` `--semantic` `--format` | `--object-type table --detail names --format json-compact` |
| `schema` | 列出表/视图 | — | `--schema` `--detail` | `--schema dbo --detail` |
| `schemas` | 列出所有 schema | — | — | （无参数） |
| `columns` | 表列信息 | `--table` | `--schema` | `--table users --schema dbo` |
| `indexes` | 表索引信息 | `--table` | `--schema` | `--table users --schema dbo` |
| `foreign-keys` | 外键关系 | `--table` | `--schema` | `--table orders` |
| `constraints` | 约束信息 | `--table` | `--schema` | `--table users` |

## 代码生成

| 命令 | 用途 | 必填参数 | 常用可选参数 |
|---|---|---|---|
| `crud` | 生成 CRUD | `--table` | `--schema` |
| `script` | 建表脚本 | `--table` | `--schema` |

## 学习管理

学习数据由 `query --learn` 或语义搜索累积，存储于 `~/.database-explorer/query_learned.yaml`。

| 命令 | 用途 | 必填参数 | 常用可选参数 | 示例 |
|---|---|---|---|---|
| `learn` | 查看学习数据摘要 | — | — | `learn` 或 `learn show` |
| `learn clear` | 清除所有学习数据 | — | — | `learn clear` |
| `learn approve` | 将别名提升到 hot_tables.yaml | `--table` | — | `learn approve --table usr` |
| `learn delete` | 删除指定表的学习数据 | `--table` | — | `learn delete --table usr` |

## 会话管理

| 命令 | 用途 | 常用可选参数 | 示例 |
|---|---|---|---|
| `history` | 查看历史命令 | `--n` | `--n 20` |
| `repl` | 交互式 SQL | `--schema` `--max-rows` | `--schema dbo --max-rows 500` |

---

## `--yes` 确认标志

| 标志 | 跳过的确认 | 使用前提 |
|---|---|---|
| `query --yes` | 写操作确认 + 全表扫描确认 | **必须先在聊天层向用户说明并获得同意** |
| `export --yes` | 文件覆写确认 | **必须先在聊天层向用户说明并获得同意** |

> `--yes` 不会跳过 export 写操作拒绝、系统路径禁止这些**硬拦截**。
> 多语句含写操作仍需 `--yes`；export 仍限单条 SELECT。

---

## `--pipe` 常驻进程模式

| 用法 | 说明 |
|------|------|
| `db-tool --pipe` | 启动 JSON-RPC 常驻进程，从 stdin 读请求、stdout 写响应 |

语义缓存：pipe 模式下语义索引在进程内复用，二次 `search --semantic` 命中缓存（<1ms）。
适合 Agent 连续多轮探索同一数据库的场景，避免每次冷启动重建索引。
按 `Ctrl+C` 或关闭 stdin 退出。

---

## 连接状态

密码通过 **keyring** 库存储在操作系统密钥链中（Windows Credential Locker / macOS Keychain / Linux SecretService），配置文件中不保存明文密码。

### 连接字符串支持

- SQL Server: `Server=...;Database=...;User Id=...;Password=...;`
- MySQL URI: `mysql://user:pass@host:3306/dbname`
- PostgreSQL URI: `postgresql://user:pass@host:5432/dbname`
- SQLite: `sqlite:///path/to/file.db`
