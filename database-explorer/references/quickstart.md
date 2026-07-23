# Quick Start：端到端轨迹 + 常用场景

> **职责契约：** 本文是 database-explorer skill 的**唯一端到端示例权威源**。
> 只包含：完整 Agent 决策轨迹（含 explore→看 complete→写 SQL→追问→交付）+ 常用场景命令片段。
> 不包含：命令参数规格（→ commands.md）、错误处理决策（→ troubleshooting.md）、安全规则（→ SKILL.md §4）。
>
> Agent 使用路径：SKILL.md §0 流程图定方向 → 本文看完整轨迹 → commands.md 查参数细节。

---

## 端到端轨迹 1：模糊业务需求 → 找表 → 查数据

> 用户只给了业务术语，没有表名。展示 semantic 搜索 → complete 标记判断 → query 的完整链路。

```
用户：帮我看看最近的订单情况， pending 状态的有多少

Agent 内部决策（用户看不到）：
  ① "订单"是业务术语，无精确表名 → 走 semantic
  ② "pending"暗示有状态列 → semantic 返回的 columns 预览里找 status 类列
  ③ 计数是只读 → 无需 --yes

Step 1: explore --semantic 订单 --format json-compact
─────────────────────────────────────────────────────
返回（已简化，字段缩写对照 SKILL.md §2.2: n=表名/总数 s=分值 c=列名 k=complete t=type v=via_fk）:
  {"n":3,"r":[
    {"n":"orders","s":1.0,"c":["order_id","customer_id","status","order_date","total_amount",...],"k":true},
    {"n":"order_items","s":0.72,"c":["order_id","product_id","quantity","unit_price"],"k":true},
    {"n":"order_logs","s":0.45,"c":["id","order_id","msg"],"k":true,"v":true}
  ]}

Agent 解读：
  - orders 表 s 最高 + status 列在 c 预览里 → 锁定 orders
  - k:true 且 status 列名已可见 → 跳过 column --detail full（省一次调用）

Step 2: query --sql "SELECT COUNT(*) AS pending_count FROM orders WHERE status = 'pending'" --format json-compact
─────────────────────────────────────────────────────
返回: {"c":["pending_count"],"r":[[142]],"t":1}

Agent 交付（用户看到）:
  pending 状态订单共 142 条。
```

**关键决策点：**
- Step 1 的 `k:true`（complete 标记）让 Agent 省掉了 Step 1.5（`explore --object-type column`）。若返回的是 `k:false` 且 `c` 里看不到 `status`，才需要补一次 `column --detail full`。
- 若 `explore --semantic 订单` 返回 `"n":0`（库内无别名映射），回退到 `explore --object-type table --pattern order --detail names`（§2.2 反模式对照）。

---

## 端到端轨迹 2：写操作确认 → 执行 → 验证

> 用户要改数据。展示 §3.3 写操作确认协议的完整落地——聊天层先说、用户同意、加 `--yes`、再验证。

```
用户：把 orders 表里 status 为 pending 超过 90 天的改成 cancelled

Agent（聊天层，先说明，不直接执行）:
  ⚠️ 将执行 UPDATE 操作：
     影响表：orders
     条件：status = 'pending' 且 order_date < '2026-04-17'
     变更：status → 'cancelled'
     这是写操作，不可自动回滚。
     是否确认执行？

用户：确认

Agent 内部决策：
  ① 用户已明确同意 → 可加 --yes
  ② 先 SELECT 确认影响范围（避免盲改），再 UPDATE
  ③ UPDATE 是写操作 → --yes

Step 1: query --sql "SELECT COUNT(*) AS cnt FROM orders WHERE status='pending' AND order_date < '2026-04-17'" --format json-compact
─────────────────────────────────────────────────────
返回: {"c":["cnt"],"r":[[23]],"t":1}  → 23 条将被影响

Step 2: query --sql "UPDATE orders SET status='cancelled' WHERE status='pending' AND order_date<'2026-04-17'" --yes --format json-compact
─────────────────────────────────────────────────────
返回: {"success": true, "columns": [], "rows": [], "total_rows": 0, "affected": 23, "duration": 0.05}
   (写操作无 c/r 结构，affected = 影响行数)

Step 3: query --sql "SELECT COUNT(*) AS cnt FROM orders WHERE status='pending'" --format json-compact
─────────────────────────────────────────────────────
返回: {"c":["cnt"],"r":[[119]],"t":1}  (原 142 - 23 = 119，验证一致)

Agent 交付:
  已更新 23 条订单为 cancelled。当前剩余 pending 订单 119 条（原 142 - 23 = 119，校验通过）。
```

**关键决策点：**
- Step 1 的 SELECT 不带 `--yes`（只读），Step 2 的 UPDATE 必须带 `--yes`（用户已确认）。
- 若用户没确认就执行 UPDATE，脚本会因无 TTY 直接拒绝（不卡死），Agent 会收到错误并追问——见 troubleshooting.md "写操作被拒绝"。
- 若 UPDATE 误用了 SELECT 语法想确认范围，可改用 `--learn` 顺带学习表关联（写入 query_learned.yaml）。

---

## 常用场景片段（单步速查）

### 场景 3：首次连接

```bash
# 建立连接（密码存入系统密钥链，配置文件零明文）
db_tool.py connect --db-type sqlserver --server 192.168.1.100 --database mydb --user sa --password xxx --name prod

# 验证连接
db_tool.py ping

# 查看已保存的连接
db_tool.py list --format json-compact
```

### 场景 4：数据采样 + 质量分析

```bash
# 随机采样 10 条（方言化采样语法由脚本自动处理，见 §5）
db_tool.py sample --table orders --n 10

# 表分析：行数 + 各列 NULL 占比
db_tool.py profile --table orders
```

### 场景 5：导出 CSV

```bash
# 仅 SELECT 可导出；覆写已存在文件需 --yes
db_tool.py export --sql "SELECT * FROM orders WHERE order_date > '2024-01-01'" --filepath orders.csv
```

### 场景 6：持久会话（pipe 模式）

```bash
# 启动常驻进程（避免每条命令重建连接，语义缓存跨请求复用）
db_tool.py --pipe

# 从 stdin 发送 JSON-RPC 请求：
{"jsonrpc":"2.0","id":1,"method":"explore","params":{"semantic":"客户"}}
{"jsonrpc":"2.0","id":2,"method":"query","params":{"sql":"SELECT * FROM customers LIMIT 5"}}
{"jsonrpc":"2.0","id":3,"method":"exit"}
```

> pipe 模式下语义索引缓存跨请求复用（二次查询 <1ms vs 首次 ~800ms）。
