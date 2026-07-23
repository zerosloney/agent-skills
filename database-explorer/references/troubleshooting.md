# Troubleshooting：错误处理与 Agent 行为

> **职责契约**：本文档是 database-explorer skill 的**唯一错误处理权威源**。
> 只包含：18 种错误的 Agent 决策表（追问/自动/放弃）+ 错误处理流程图 + 安全红线 + 场景示例。
> 不包含：命令参数（→ commands.md）、安全规则条目（→ SKILL.md §4，本文档只定义红线行为）。
>
> Agent 使用路径：脚本报错 → 查本文档决策表 → 执行对应行为 → 仍失败则追问用户。

> 供 AI Agent 加载使用。每个错误标注 Agent 应该"追问/重试/放弃"的具体行为。

## 错误处理决策表

| 错误 | Agent 行为 | 优先级 |
|------|------------|--------|
| 驱动未安装（如 `pymssql`/`pymysql`/`psycopg2`） | **追问用户**：推荐 `pip install <driver>`，用户确认后执行 | 高 |
| keyring 库未安装 | **追问用户**：推荐 `pip install keyring`，安装后重新连接 | 高 |
| 无活动连接 | **自动执行** `list` 检查已有连接；有则 `use <name>`，无则追问连接参数 | 高 |
| 连接失败（地址/端口/凭据错误） | **追问用户**：检查 server/port/user/password，不要猜测 | 高 |
| 写操作被拒绝（`check_read_only` 命中） | **追问用户**：明确告知是写操作需确认，用户同意后用 `--yes` 重试 | 高 |
| 全表扫描被拒绝（`is_full_table_scan` 命中） | **追问用户**：告知无 WHERE/LIMIT 的 SELECT * 可能很慢，用户同意后用 `--yes` 重试 | 中 |
| export 写操作被拒绝 | **告知用户**：export 仅允许 SELECT，请用 `query --yes` 执行写操作 | 高 |
| 导出路径被拒（`is_protected_path` 命中） | **追问用户**：目标在系统保护目录，请换非系统路径 | 高 |
| 导出覆写被拒（目标文件已存在且未确认） | **追问用户**：文件已存在是否覆盖，同意后用 `--yes` 重试 | 中 |
| subprocess 调用无 TTY 导致确认失败 | **告知用户/Agent**：改用 `--yes` 标志（须先在聊天层确认） | 高 |
| 表不存在 | **自动执行** `schema` 确认表名，或 `search` 搜索相似表名；多 schema 库先 `schemas` 确认是否在非默认 schema | 中 |
| 列名无效 | **自动执行** `columns --table` 确认列名 | 中 |
| 默认 schema（dbo/public）查询为空 | **自动执行** `schemas` 列出所有 schema，提示用户选择 `--schema <名>` | 中 |
| `search --semantic` 中文无结果 | **告知用户**：库内无 hot_tables 别名映射，建议用英文表名/列名关键词，或先 `search --pattern` 浏览表名 | 低 |
| SQL 注入风险检测 | **放弃执行**：建议用户用参数化查询或检查输入 | 高 |
| 查询结果为空 | **告知用户**：结果为空，建议放宽 WHERE 条件或检查数据 | 低 |
| 查询超时 | **建议优化**：缩小范围（加 WHERE/LIMIT），检查索引，或调大超时参数 | 中 |
| 驱动版本冲突 | **追问用户**：是否升级或降级驱动 | 中 |
| 权限不足（认证失败） | **追问用户**：检查用户名密码或数据库权限 | 高 |
| SSL/TLS 证书错误 | **告知用户**：需配置证书或添加 `--no-verify`（如支持） | 中 |
| 数据库不存在 | **追问用户**：确认数据库名，或提示创建 | 中 |
| REPL 模式下写操作 | **直接拒绝**：REPL 模式不允许写操作 | 高 |
| 多语句 SQL 含写操作 | **告知用户**：多语句逐条安全检查，含写操作需 `--yes`；或拆为多条命令分别执行 | 高 |
| 密码解密失败 / 旧版加密 | **告知用户**：密码可能使用废弃加密，建议重新执行 `connect` 命令 | 中 |
| 配置文件损坏（`connections.json` 解析失败） | **告知用户**：备份并重置配置文件 | 中 |

## 错误处理流程

```
Agent 收到 db_tool.py 错误输出
    │
    ├─ 是否在错误处理决策表中？
    │   ├─ 是 → 按表执行对应行为（追问/自动执行/放弃）
    │   └─ 否 → 默认追问用户，不做猜测
    │
    ├─ 是否可自动恢复？
    │   ├─ 是（无活动连接/表不存在/列名无效）→ 自动执行诊断命令
    │   └─ 否 → 追问用户
    │
    └─ 是否安全敏感？
        ├─ 是（写操作/注入风险）→ 拒绝并告知
        └─ 否 → 按表执行
```

## 安全红线（Agent 绝对不能做的事）

1. **不猜测连接信息**：缺 server/port/user/password 必须追问，不能用默认值填充
2. **不绕过写操作确认**：DROP/DELETE/TRUNCATE 必须经用户明确同意
3. **不暴露敏感信息**：错误信息中的密码/IP/路径已脱敏，Agent 不要尝试回显原始值
4. **不在 REPL 模式执行写操作**：REPL 模式写操作直接拒绝
5. **不修改密码存储文件**：除非用户明确要求重置
6. **多语句含写操作必须 `--yes`**：export 仍限单条 SELECT，query 的多语句含写操作需 `--yes`

## 常见错误恢复示例

### 场景 1：第一次连接 MySQL

```
用户：连接 MySQL 数据库
Agent：需要以下信息 → server, port(默认 3306), user, password, database
用户：192.168.1.100，root，pwd123，订单库
Agent：执行 connect --db-type mysql --server 192.168.1.100 --port 3306 --user root --password pwd123 --database 订单库
错误：驱动 'pymysql' 未安装
Agent：检测到缺少 pymysql 驱动，是否安装？执行 pip install pymysql ？(y/n)
用户：y
Agent：pip install pymysql，然后重试 connect
```

### 场景 2：表名拼写错误

```
用户：查一下 users 表的前 10 条
Agent：执行 query --sql "SELECT * FROM users LIMIT 10"
错误：表不存在
Agent：自动执行 schema 列出所有表，搜索相似表名（如 user/users/user_info）
Agent：未找到 'users'，是否想查 'user'？或请提供正确的表名
```

### 场景 3：写操作确认

```
用户：删除 users 表
Agent：⚠️ 危险操作：执行 DROP TABLE users 将永久删除该表及所有数据，不可恢复。
      确认执行吗？
用户：是
Agent：用户已确认，执行 query --sql "DROP TABLE users" --yes
```

> Agent 流程：识别到写操作 → 聊天层明确告知风险并询问 → 用户同意 → 调用时附 `--yes`。
> 若未获同意或未传 `--yes` 且无 TTY，脚本拒绝执行。

### 场景 4：列名拼写错误

```
用户：查 users 表的 emial 字段
Agent：执行 query --sql "SELECT emial FROM users"
错误：列名无效
Agent：自动执行 columns --table users 获取列名
Agent：未找到 'emial'，是否想查 'email'？
```
