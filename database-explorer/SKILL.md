---
name: database-explorer
description: |
  数据库探索工具，支持 SQL Server/MySQL/PostgreSQL/KingbaseES(人大金仓)/SQLite 五种数据库的连接、查询、结构探索、CRUD 生成、CSV 导出。
  典型需求："连一下这个数据库" / "看看有哪些表" / "查一下XX表的数据" / "搜一下跟XX相关的表" / "导出XX查询结果" / "生成XX表的增删改查SQL"。
  安全机制：写操作（INSERT/UPDATE/DELETE/DROP/TRUNCATE）自动触发用户确认，密码通过 keyring 操作系统密钥链存储（Windows Credential Locker / macOS Keychain / Linux SecretService），多语句 SQL 注入自动拦截，错误信息自动脱敏。
  使用方式：Agent 通过 subprocess 调用 skill://database-explorer/scripts/db_tool.py 子命令，用户不直接接触 CLI。
agent_created: true
version: 0.6.0  # 对应 db_tool.__version__，升级前必读 CHANGELOG.md
---

# Database Explorer — Agent 指令集

## 0. 快速触发规则（优先级最高，先于读本文档）

用户说 **"连一下/连接/连上 <数据库名>"** 时，**不要读本文档剩余内容**，直接执行：

1. `python db_tool.py list --format json-compact` — 查 `~/.database-explorer/connections.json` 已有连接
2. 找到匹配 → `python db_tool.py use <name>`
3. 未找到 → 追问用户 server/db/user/pwd，然后 `python db_tool.py connect ...`
4. **禁止**搜索项目文件（grep/glob 找连接字符串）

---

## 核心原则

1. **优先用 `explore` 命令**：一个命令覆盖所有结构探索，比碎片命令省 60% 调用轮次。

（schema-first 铁律见 §0，token 节约硬规则见 §2.2。）

脚本路径：`skill://database-explorer/scripts/db_tool.py`

---
## 1. 安装

**权威安装方式（包含全部硬依赖 + 可选加速，见 §7 requirements.txt）：**
```bash
pip install -r "skill://database-explorer/requirements.txt"
```

**或逐条按需安装：**

```bash
pip install keyring            # 必须（密码管理）
pip install sqlalchemy         # 必须（数据库抽象层核心，SQLAlchemy 2.0+）
pip install numpy              # 必须（语义搜索向量运算，顶层 import 不可缺）
pip install pyyaml             # 必须（hot_tables.yaml 别名 + --learn 查询学习存储）
pip install pymssql            # SQL Server
pip install pymysql            # MySQL
pip install psycopg2-binary    # PostgreSQL / KingbaseES(人大金仓)
pip install sqlglot            # 推荐（查询学习的 SQL 解析引擎）
# SQLite 无需额外驱动
```

**环境变量：**

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `DATABASE_EXPLORER_HOME` | `~/.database-explorer/` | 配置/缓存根目录。连接信息（`connections.json`）、学习数据（`query_learned.yaml`）、语义缓存（`cache/`）均存放于此。测试时可设为临时目录实现隔离。 |
| `DATABASE_EXPLORER_ALLOW_SBERT_DOWNLOAD` | 禁止（需显式 `=1`） | 设为 `1` 允许联网下载 SBERT 模型。默认禁止，未缓存时直接降级为纯词法匹配，避免 Agent 子进程阻塞数分钟。 |

---
## 2. 命令速查

### 2.1 连接管理

| 用户意图 | 命令 |
|---------|------|
| 连接数据库 | `connect --db-type <type> --server <host> --database <db> --user <u> --password <p> [--name <alias>]` |
| 连接(URI) | `connect --db-type <type> --connection-string <uri> [--name <alias>]` |
| 列出/切换/测试 | `list [--format json-compact\|json\|table]` / `use <name>` / `ping [--name <n>]` |

**连接流程（严格遵守）：**
1. 先 `list` 查 `~/.database-explorer/connections.json` 已有连接
2. 名称匹配 → `use <name>`
3. 不匹配 → 追问用户 server/db/user/pwd，再 `connect`
4. **绝对禁止**搜索项目文件（grep/glob/read 找连接字符串）

**`--db-type` 可选值：** `sqlserver` / `mysql` / `postgresql` / `kingbase` / `sqlite`。`mssql` 作为 `sqlserver` 的别名，`kingbasees` 作为 `kingbase` 的别名，均自动归一化。

### 2.2 结构探索 — `explore`（Agent 首选）

**一个命令覆盖所有结构探索（schema/table/view/column/index/fk/constraint/procedure/function）+ 独立的 `--semantic` 语义搜索。**

```
explore --object-type <type> --detail <level> [--schema <s>] [--table <t>] [--pattern <p>] [--semantic <q>] [--format <fmt>]
```

> `--semantic` 优先于 `--object-type`：同时传且 object-type 为 table 或缺省时走语义搜索；object-type 为其他值（column/index/fk 等）时 `--semantic` 被忽略。**建议分开调用**，不要组合。
>
> `--level2` 默认启用（`explore --semantic` 自动两级补全）。Agent 不需要显式传；仅在需要关闭时用 `--no-level2`。`search --semantic` 适配层自动关闭（仅表名+注释匹配）。

| object-type | 必填参数 | 说明 |
|-------------|---------|------|
| schema | — | 列出所有 schema |
| table | — | 列表/搜索表 |
| view | — | 视图列表/搜索 |
| column | --table（指定表时） | 列详情或列搜索 |
| index | --table | 索引信息 |
| fk | --table | 外键关系 |
| constraint | --table | 约束信息 |
| procedure | — | 存储过程（SQLite 不支持，返回空） |
| function | — | 自定义函数（SQLite 不支持，返回空） |

**语义搜索（独立于 `--object-type`，不要组合使用）：**

`explore --semantic "<关键词>" [--limit <n>]` 触发语义匹配，**不要**同时传 `--object-type`（若组合，object-type 非 table 时 `--semantic` 会被静默忽略）。返回结果自带 `columns` 列名预览和 `complete` 标记（见下方"Token 节约硬规则"第 2 条）。

输出结构（json-compact）：`{"n":总命中数, "r":[{"n":表名, "s":分值, "c":[列名], "k":complete标记, "t"?:类型, "f"?:[fk], "v"?:via_fk}], "h"?:提示}`。`k:true` → 列名已全量返回，禁止再查 column；`k:false` → 需写 SQL 时才补 full。

**detail 级别（渐进式披露，控制 token 消耗）：**

| 级别 | 返回内容 | 何时用 |
|------|---------|--------|
| names | 仅名称列表 | 浏览、找表（**默认，最省 token**） |
| summary | 名称 + 元信息（类型/nullable/行数等） | 选择相似表 |
| full | **对 table/view**：仅返回 system view 行（TABLE_SCHEMA/NAME/TYPE），**不是列定义**。<br>**对 column/index/fk/constraint**：返回完整定义 | 写 SQL 前对**单张**目标表用 `--object-type column --table X --detail full` |

**format（Agent 必须用 json-compact）：**

| 格式 | 说明 | token 效率 |
|------|------|-----------|
| json-compact | `{"c":[...],"r":[[...],...]}` | **最高（Agent 默认）** |
| json | 标准 JSON | 中 |
| table | Markdown 表格 | 低（人阅读用） |

> ⚠️ **`--format` 仅 `explore`/`query`/`search`/`find`/`list`/`profile` 支持。** `sample`/`crud`/`history`/`ping`/`use`/`connect` 固定纯文本/Markdown 输出，不加 `--format` 参数（会报 `unrecognized arguments`）。

**🚨 Token 节约硬规则（不可违反）：**

1. **探索阶段一律 `--detail names`**。只有即将写 SQL、且已锁定**单张**目标表时，才对该表单次 `--detail full`。绝不对多表批量 full。
2. **列名搜索优先复用语义预览**。`explore --semantic` 返回每表带 `columns` 列名预览和 `complete` 标记：
   - `complete: true` → 该表列名已全量返回，**禁止**再 `explore --object-type column`。
   - `complete: false` → 仅当确实需要该表完整列定义时才补 full。
3. **列表搜索必带 `--pattern`**。`--object-type table` 不带 pattern 在大库会 dump 上千张表。
   - 实测 whxl 库 2788 张表：仅 names 列表就 **~28,000 token**。
   - 脚本采用**两级安全阀**：DB 查询层 `SCHEMA_SCAN_LIMIT=5000` 防止 SQL 返回过多行；Agent 输出层对 `pattern=="%" and names` 额外加 **200 张硬上限**（直接拒绝而非返回巨型列表）。
   - pattern 不含 `%`/`_` 时脚本自动按子串匹配，直接写 `--pattern LES` 即可。
4. **format 永远 `json-compact`**（见上方 format 表），禁止 table 格式。
5. **响应中带 `hint` 字段时按提示行动**（如建议加 pattern 或改用 semantic）。

### 🚫 反模式示例（实测对比，whxl 库 + 关键词 LES）

| 写法 | token | 倍数 | 评价 |
|------|------:|-----:|------|
| `explore --object-type table`（无 pattern） | **~28,000** | 213× | ❌ 黑洞；names 模式 >200 张脚本会直接拒绝 |
| 对 10 张 LES 表**逐个** `column --detail full` | ~11,500 | 87× | ❌ 黑洞；多表批量 full |
| 单张大表 `column --detail full`（92 列） | ~4,000 | — | ⚠️ 锁定单张后再用 |
| `explore --semantic LES` | ~400 | 3× | ✅ **首选**：自带列名预览 + complete 标记 |
| `explore --object-type table --pattern LES --detail names` | ~130 | 1× | ✅ 已知前缀时最省 |

### 2.3 数据操作

| 用户意图 | 命令 | 备注 |
|---------|------|------|
| 执行 SQL | `query --sql "<SQL>" [--format json-compact|table|csv] [--yes] [--timeout <sec>] [--learn]` | 写操作/全表扫描需 `--yes`；`--learn` 从 SQL 中学习表关联和列语义；`--format csv` 直接打印 CSV 文本 |
| 采样数据 | `sample --table <t> --n 10` | 优先用 sample，不用手写 SELECT * |
| 统计分析 | `profile --table <t>` | 行数 + NULL 占比 |
| 导出 CSV | `export --sql "<SQL>" --filepath <路径>` | 仅 SELECT；覆写需 `--yes` |
| 生成 CRUD | `crud --table <t>` | INSERT/SELECT/UPDATE/DELETE SQL |
| DDL 脚本 | `script --table <t>` | 建表语句 |

### 2.4 其他

| 命令 | 说明 |
|------|------|
| `history --n 20` | 查看历史命令 |
| `repl` | 交互式 SQL（Agent 不可调用） |
| `explain --sql "<SQL>"` | 查看 SQL 查询执行计划（MySQL: EXPLAIN / PG: EXPLAIN / SQLite: EXPLAIN QUERY PLAN / SQL Server: SET SHOWPLAN_TEXT ON）。**仅接受单条只读 SELECT**，写操作和多语句会被拒绝 |
| `learn show` | 查看学习数据摘要（别名、频率、关联） |
| `learn clear` | 清除所有学习数据 |
| `learn approve --table <表名>` | 将学习别名提升到 hot_tables.yaml（人工确认后永久生效） |

**`query --learn` 模式**：Agent 执行 SQL 时加 `--learn` 标志，自动从 SQL 中提取表名、列名、JOIN 关联、WHERE 枚举值等结构化知识，写入 `~/.database-explorer/query_learned.yaml`。隐私保护：只记录结构信息，不记录实际数据值。

---
## 3. Agent 决策规则

### 3.1 意图映射

| 用户输入 | Agent 行为 |
|---------|-----------|
| "查" + SQL 语句 | → `query --format json-compact` |
| "查" + 关键词（无 SQL） | → `explore --semantic <关键词>`（**首选，自带列名预览**） |
| "找和XX相关的表" / "哪些表和XX有关" | → `explore --semantic <XX>`（**不要先 explore --object-type table**） |
| "看" + 表名 | → `explore --object-type column --table <表> --detail names` |
| "看" + "结构"/"所有表" | → 先 `explore --semantic <领域关键词>`；用户明确要求"所有表"时才 `--object-type table --pattern %` |
| "有哪些 schema" | → `explore --object-type schema --detail names` |
| "连接"/"连一下"/"连上" + 数据库名 | → 先 `list` 查已有连接；匹配则 `use`，否则追问用户（**禁止搜项目文件**） |
| 无活动连接 | → 自动 `list`；有则 `use`，无则追问 |
| "查一下XX表" | → `sample --table XX --n 10` |
| "导出" / "下载" | → `export --sql --filepath`（追问数据来源） |
| "切换" + 连接名 | → `use <name>` |
| "建表脚本" / "DDL" | → `script --table <t>` |
| "查询计划" / "执行计划" / "explain" + SQL | → `explain --sql "<SQL>"` |
| "数据质量" / "表分析" | → `profile --table <t>` |
| "抽样" / "样本" | → `sample --table <t> --n 10` |

### 3.2 探索→查询工作流

见 §0 决策流程图。关键点：`explore --semantic` 返回的 `complete` 标记决定是否需补查列定义——`true` 跳过 `column --detail full`，`false` 且需写 SQL 时仅对目标表单次补 full。

### 3.3 写操作确认协议

Agent 通过 subprocess 执行，**没有交互 TTY**，写操作/全表扫描走「聊天层 + `--yes`」协议：
1. 识别到写操作（INSERT/UPDATE/DELETE/DROP 等）或全表 SELECT *
2. **向用户说明**影响范围；用户同意后调用时附 `--yes`
3. 未传 `--yes` 且无 TTY → 脚本直接拒绝

### 3.4 语义搜索

**返回结果解读：**
- 结果按综合得分排序（表名/别名匹配 > 列名匹配 > FK 关联表），含 `via_fk` 标记区分外键传递关联的表
- `columns` 列名预览 + `complete` 标记：`true` 表示列名已全量返回，`false` 表示需要补查
- 高频列（ID/Name/Status）自动降权，稀有列保持完整权重

**hot_tables.yaml 别名配置：** `{term: "VIP客户", weight: 2.0}`（加权别名）或 `{term: "sp_*", weight: 1.5}`（通配符别名）

> ⚠️ **存储过程/函数（routines）**：SQL Server / MySQL / PostgreSQL / KingbaseES 均支持（SQLite 无存储过程概念）。

---
## 4. 安全边界

1. **写操作必须确认**：INSERT/UPDATE/DELETE/DROP/TRUNCATE/MERGE/CREATE/ALTER/EXEC/GRANT/REVOKE 触发 `--yes` 确认
2. **export 仅允许只读 SELECT**：检测到写操作关键字**直接拒绝**（不止确认）
3. **错误信息脱敏**：自动替换 IP/路径/密码为 `<ip>`/`<path>`/`pwd=***`
4. **密码安全**：keyring 存入操作系统密钥链，配置文件零明文
5. **多语句逐条安全检查**：`SELECT 1; INSERT ...` 逐条做安全检查，含写操作需 `--yes`；export 仍限单条
6. **SQL 注入防护**：quote_ident 方言化引用 + xp_cmdshell 检测 + MySQL 条件注释保留 + PostgreSQL dollar-quote（`$$...$$` / `$tag$...$tag$`）识别，防止字面量内的关键字/分号误导写操作检测与多语句拆分
7. **全表扫描拦截**：SELECT * 无 WHERE/LIMIT 需 `--yes`
8. **导出路径保护**：禁止系统目录，覆写需确认
9. **查询超时**：`--timeout <sec>` 单次查询执行超时（PostgreSQL/MySQL/SQL Server）

---
## 5. 方言差异

`query` 自动追加分页和 ORDER BY，**Agent 不要手动拼接分页语法**。Agent 关心的是标识符引用差异（写 SQL 时手动引用列/表名用）：

| 数据库 | 标识符引用 | 分页 |
|--------|-----------|------|
| SQL Server | `[name]` | OFFSET/FETCH（自动） |
| MySQL | `` `name` `` | LIMIT/OFFSET（自动） |
| PostgreSQL | `"name"` | LIMIT/OFFSET（自动） |
| KingbaseES | `"name"` | LIMIT/OFFSET（自动） |
| SQLite | `"name"` | LIMIT/OFFSET（自动） |

> 随机采样、建表脚本、系统视图查询等方言差异的完整 SQL 参考，见 `references/schema_queries.md`。

---
## 6. 故障排查

| 错误 | Agent 行为 |
|------|-----------|
| 驱动未安装 | 追问用户：`pip install <driver>` |
| 无活动连接 | 自动 `list`；有则 `use`，无则追问 |
| 连接失败 | 追问：检查 server/port/user/password |
| 写操作被拒 | 追问：用户同意后用 `--yes` 重试 |
| 全表扫描被拒 | 追问：用户同意后用 `--yes` 重试 |
| 表不存在 | 自动 `explore --object-type table` 确认 |
| 列名无效 | 自动 `explore --object-type column --table X` 确认 |
| 多语句含写操作 | 告知：需 `--yes` 确认，或拆为多条命令 |
| 密码解密失败 | 告知：重新 `connect` |

完整错误处理见 `references/troubleshooting.md`。

---
## 7. 参考文件

| 文件 | 何时看 |
|------|--------|
| `references/quickstart.md` | **端到端示例**（2 个完整 Agent 决策轨迹 + 常用场景片段），首次使用先看 |
| `references/commands.md` | 命令参数百科（必填/可选/默认值） |
| `references/troubleshooting.md` | 错误处理决策表（追问/自动/放弃） |
| `references/hot_tables.yaml` | 语义搜索别名配置 |
| `references/schema_queries.md` | 自定义结构查询 |
| `CHANGELOG.md` | 版本演进与破坏性变更（升级前必读） |
| `requirements.txt` | 依赖清单（安装权威源，见 §1） |
| `scripts/tests/` | 测试套件（改动后跑 `pytest scripts/tests/`） |

---
## 8. 常驻进程模式（`--pipe`）

`python db_tool.py --pipe` 启动 JSON-RPC 常驻进程，避免每次命令重启进程和重建连接。Agent 通过 stdin 发送 JSON-RPC 请求，stdout 接收响应。`explore` 和 `query` 在 pipe 模式下自动使用 `json-compact` 格式。语义搜索缓存跨请求复用（同进程二次查询 <1ms vs 首次 ~800ms）。方法名同子命令名，`exit` 关闭。

**请求格式：** `{"jsonrpc":"2.0","id":<n>,"method":"<command>","params":{...}}`，`params` 字段名同子命令的 `--flag`（连字符转下划线，如 `max-rows` → `max_rows`）。

**写操作确认（遵循 §3.3）：** pipe 模式无 TTY，写操作/全表 SELECT * 默认被拒，用户在聊天层同意后在 params 附 `"yes":true`。示例：`{"jsonrpc":"2.0","id":2,"method":"query","params":{"sql":"DROP TABLE old_logs","yes":true}}`。未传 `yes:true` → `{"error":{"code":-32000,"message":"用户取消执行"}}`。export 覆写已存在文件同样走 `params.yes`。

**错误响应：** 失败时返回 `{"jsonrpc":"2.0","id":<n>,"error":{"code":<int>,"message":"<脱敏后的错误>"}}`（code -32700 解析错误 / -32601 方法不存在 / -32603 内部错误 / -32000 业务错误）。错误消息已脱敏（IP/路径/密码 → `<ip>`/`<path>`/`pwd=***`）。
