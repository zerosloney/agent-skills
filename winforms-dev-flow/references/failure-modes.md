# 失败模式案例库

> 实战中踩过的坑。共 8 例，覆盖 3 类失败原因：**默认假设错位** / **上下文获取受阻** / **输出偏离项目风格**。
>
> 每个案例给出：**场景 → 症状 → 根因 → 修复方案 → 预防措施**。
>
> 触发时机：任意 Step 卡顿时，**先用下面「症状→案例」速查表定位**。如不匹配，请补充新案例（修改本文件 + 同步 review-checklist.md）。

---

## 症状 → 案例 速查表(必看)

> **Agent 加载本文件的入口**:先看症状列,定位案例号,再翻对应章节。
> **每个 Step 的反向索引**:见 SKILL.md「Failure handling」节。

| # | 触发症状 / 关键词 | 案例号 | 根因分类 | 看哪个修复 |
|---|------------------|--------|---------|-----------|
| 1 | `未能找到类型或命名空间名 SqlOperate` / `运行连不上库` / `connName 未知` | **1** | 默认假设错位 | DBHelp 实例名 + 连接名提取 |
| 2 | `DALBase<T> 编译失败 T 参数不齐` / `Update 后字段丢失` | **2** | 上下文获取受阻 | Entity 字段完整性 3 选 1 |
| 3 | 拿不到 Entity / 字段清单 / 表 schema 不可读 | **3** | 上下文获取受阻 | 连 DB 查 schema / 让用户给清单 |
| 4 | `GridStyle [CSS] 未注册` / 列头颜色错乱 | **4** | 默认假设错位 | grep `new GridStyle(` 提取代号 |
| 5 | `无法转换泛型/非泛型` / 同项目两套基类 | **5** | 结构判定失败 | 强制二选一并全项目统一 |
| 6 | 用户看到两次弹窗 / 日志两条堆栈 | **6** | 输出偏离项目风格 | Presenter/Ser 不独立 try-catch |
| 7 | Designer 打开后控件挤一起 / Tab 跳乱 / resx 报错 | **7** | 输出偏离项目风格 | 强约束加载 designer-patterns.md |
| 8 | `DAL{业务名}` / `Frm_{业务}` 与项目其他模块不一致 | **8** | 默认假设错位 | Step 1 提取表加类名前缀行 |

### 按生成阶段反查(更精准)

| 生成阶段 | 必查案例 | 触发条件 |
|---------|---------|---------|
| Step 1(模式学习) | **1 / 4 / 5 / 8** | 扫不到 DBHelp / GridStyle 代号 / 是否泛型 / 前缀 |
| Step 2(数据驱动布局) | **3** | 没有 Entity、没有字段清单、表 schema 不可读 |
| Step 4(三层生成 + 绑定) | **2 / 6** | DAL/Ser 缺字段;Presenter/Ser 重复弹窗 |
| Step 4 后段(Designer) | **7** | Designer 打开错位、TabOrder 乱、resx 未注册 |
| 最终交付前 | **8** | 文件名/类名与项目不一致 |
| 5b-pre 冒烟 | **9** | 占位符残留 / TODO / partial class 名不一致 / 属性暴露 get |

### 关键词快速 grep(`grep -E` 模式)

```bash
# 编译报错时,先用这些 grep 定位
grep -E "SqlOperate|ListOperate|DBHelp" -r .       # → 案例 1
grep -E "GridStyle\(" -r .                          # → 案例 4
grep -E "frmBase|frm_Base" -r .                     # → 案例 5(基类风格)
grep -E "DAL[A-Z]|DALMM_|Frm_|DlgEdit_" -r .        # → 案例 8(命名)
```



---

## 案例 1：DBHelp 命名差异（默认假设错位）🔴

**场景**：扫描参照窗体看到 `SqlOperate + ListOperate` 调用，但项目实际用 `varlist.ASSDBHelp`。本次实战 `CSS.WHXL.Extend` 项目命中。

**症状**：
- 生成的 DAL 文件用了 `SqlOperate _so = new SqlOperate()` 这类代码
- 编译时报错「未能找到类型或命名空间名 `SqlOperate`」
- 即使编译通过，运行时连接字符串也错（用了错误的 connName）

**根因**：skill 默认模板假设 Upgrader / CRS 项目约定（用 `varlist.SqlOperate` / `varlist.ListOperate`），未识别 `CSS.WHXL.Extend` 用自定义 DBHelp（如 `varlist.ASSDBHelp`）。

**修复方案**：
1. 从参照窗体全文 `grep -E "varlist\.[A-Za-z]+(DBHelp|Conn)"`，确认实际 DBHelp 实例名
2. DAL 文件改用项目实际 DBHelp 实例名替换所有 `varlist.*`
3. SQL 连接名（connName）通过 `rg -oN 'varlist\.[A-Za-z]+(Conn|DBHelp)'` 找出候选,但**必须过滤注释**(`rg -nN ... | grep -vE '^\S+:\s*//|^\S+:\s*\*'`)再统计——否则会把从 Upgrader 复制过来的注释残留当成真实用法。实测 Upgrader 主导是 `varlist.ASSConn`(79%);**CRS 项目的 `varlist` 类是纯工具类不持 Conn 属性**,直接套 `ASSConn` 会编译错,必须扫描 CRS 自己的非注释调用确认

**预防**：Step 1 必须从参照窗体提取并确认「数据库 DBHelp 实例 / 连接名」，无法判定时列候选让用户选。

---

## 案例 2：Entity 不完整或缺失（上下文获取受阻）🔴

**场景**：参照窗体里只用了一个轻量 DTO（如 `WarehouseLookup` 仅 ID/Code/Name 3 字段），完整 ORM Entity 不存在。本次实战 `JDDR_MMA_Warehouse_Data` 表命中。

**症状**：
- DAL 泛型 `DALBase<T>` 编译失败（T 参数不齐）
- 生成的 Entity 字段不全，列表显示缺列
- Ser 层内存缓存 `_lst{Entity}` 与数据库字段不一致，Update 丢失字段

**根因**：skill 假设 Entity 已就绪或按某种固定字段集生成，但项目里可能只有部分字段的 DTO。

**修复方案**（3 选 1，先问用户）：
- **A**：新建完整 Entity（所有字段 + ORM 风格 setter）
- **B**：用现有 DTO 扩展（保留轻量风格，但补足字段）
- **C**：走 DataTable 模式（不建 Entity，参照现有 `GetWarehouseLookup()`）

**预防**：
- Step 0a 必须确认「Entity 或字段来源」（已存在 / 缺字段 / 完全缺失）
- 完全缺失时，先用 `mavis mcp call database-explorer` 连库查 schema，列出字段后再生成

---

## 案例 3：表 schema 不可读（数据库连接缺失）🔴

**场景**：没有 `Entity.{实体类}`、没有完整表结构文档、用户只给了表名。本次实战命中。

**症状**：
- 「字段 → 控件」映射表无法列出（不知道字段名/类型/是否 NULL）
- 无法生成 Entity
- Step 2 数据驱动布局步骤卡死

**根因**：skill 自身没有 DB 读取能力，依赖用户提供字段清单或已有的 ORM Entity。

**修复方案**：
1. 用 `mavis mcp call database-explorer ...` 或直接加载 `database-explorer` MCP 技能
2. 连库查询：`SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_NAME = '...'`
3. 把查询结果整理成字段清单，再进入 Step 2 布局

**预防**：
- Step 0a 记录「数据库可连性」；不可连时必须从现有 Entity 或用户字段清单继续
- Step 2 启动前确认「字段清单是否已就绪」

---

## 案例 4：GridStyle 代号不匹配（默认假设错位）🔴

**场景**：项目代码里 `new GridStyle("CSS", ...)`，skill 默认假设 `"ASS"` 或 `"CRS"`。本次实战命中。

**症状**：
- GridControl 启动时异常「GridStyle [CSS] 未注册」或样式完全不对
- 列头颜色、行高、字体显示异常

**根因**：skill 没扫到真实代号，凭印象写了 `"ASS"`。

**修复方案**：
1. 在参照窗体内 `rg -n 'new GridStyle\('`(**过滤注释**),提取第一个参数
2. 同步检查项目 `App.config` / 注册代码里是否还有第二处注册（部分项目 GridStyle 在 `Program.cs` 启动注册）

**预防**：Step 1 必须从参照窗体提取并确认「GridStyle 代号」。

> 📋 **多代号是 Upgrader 正常状态**(实测 2026-07,详见 `designer-patterns.md` §1 表):
> - Upgrader 主仓有 6 种代号:`ASS`(1291) / `CSS`(128) / `SM`(35) / `SMManagement`(15) / `SMBOM`(6) / `Ass`(~45)
> - **子模块专用代号不算分裂**:`SM.UI` 子目录全用 SM 系列,目标模块在此目录就该用 SM,不是 ASS
> - **目标模块所在子目录内多代号混用**(如 ITPManagement: ASS 50 / CSS 65 / Ass 25)才是真分裂 → Step 1 让用户选
> - ⚠️ **大小写敏感**:`"Ass"` ≠ `"ASS"`,生成时严格按参照窗体原样

---

## 案例 5：泛型 vs 非泛型混用（结构判定失败）🟡

**场景**：项目内同时存在两种风格：
- `frmXxx : frmBase`（非泛型，Ser 直连 DAL）
- `frmYyy<T> : frm_Base<T>`（泛型，ORM `DALBase<T>`）

**症状**：
- 选错风格的窗体，Presenter/Ser 引用基类类型时混淆
- 编译报错「无法转换泛型/非泛型」

**根因**：skill 默认假设单一模式（要么非泛型 Upgrader、要么泛型 CRS）。

**修复方案**：
1. 以**选定参照窗体**为准
2. 新窗体必须**完全跟随参照**的范型（要么纯泛型要么纯非泛型）
3. 不要混用 `Base<T>` 和非泛型

**预防**：
- Step 1 提取表里明确记录「**是否泛型**」
- 生成时一致使用
- 如果同项目内确实存在两套风格——**强制让用户二选一并全项目统一**

---

## 案例 6：异常处理风格不一致（输出偏离项目风格）🟡

**场景**：参照窗体在 View 层 try-catch，但生成的 Presenter 也加了 try-catch 包整段。

**症状**：
- 异常被截两次，原始堆栈丢失
- 用户看到两次弹窗（Ser 弹一次，View 弹一次）
- 日志混乱

**根因**：skill 没强调「异常只在一处处理」。

**修复方案**：
- Presenter **不处理异常**，全部冒泡到 View
- Ser 层**不处理异常**（除非业务校验要转换成 bool 返回值）
- View 层**统一 try-catch**，按参照窗体风格弹窗

**预防**：
- review-checklist B4 已加两项:「Presenter 不独立 try-catch」+「Ser 层不独立 try-catch 转 bool」(对应案例 6)
- review-checklist B4 同时校验 Upgrader vs CRS 的异常风格差异

---

## 案例 7：Designer 文件手写出错率极高（输出偏离项目风格）🔴

**场景**：必须自己拼 InitializeComponent，控件坐标/TabOrder 错位。

**症状**：
- 窗体打开后控件挤在一起
- Tab 顺序错乱（键盘 Tab 切换跳来跳去）
- 编译期「未注册资源」报错（resx 漏定义）
- Designer.cs 与 .resx 双向引用断链（修改 Designer 后 resx 没自动同步）

**根因**：Designer 模板极少沉淀，每次新窗体都从零写。

**修复方案**：
- **强约束：Step 4 生成 Designer 前必加载 `references/designer-template-list.md`**
- 按模板 A/B/C/D 之一复制，改名替换后填字段

**预防**：
- SKILL.md 约束 #7 已经强制 Designer 模板必加载
- review-checklist C.3 加一项：「Designer 是否来自 templates」（**否则报错**）

---

## 案例 8（新增）：命名约定与项目不符（小但常见）🟡

**场景**：skill 默认 `DAL{业务名}` / `{业务名}Ser` / `frm{业务名}`，但项目实际用 `DALMM_{业务名}` / `{业务名}Ser`（业务模块前缀）/ `Frm_{业务名}`（带下划线）。本次实战命中。

**症状**：
- 类名/文件名与项目其他模块不一致
- 后续 TFS 合并、命名空间搜索都受影响
- 同事 review 看着别扭

**根因**：skill 默认命名规则没考虑项目实际前缀约定。

**修复方案**：
1. 扫参照窗体：找现有命名规律（`DAL` + 业务前缀 + 名称）
2. 类名、文件名都用同一个 prefix
3. 同步检查命名空间（`CSS.WHXL.Extend.DAL.PartsManagement` 这种带业务模块名的）

**预防**：Step 1 提取表加一行「**类名前缀约定**」（如 `DALMM_` / `Frm_` / `DlgEdit_`）。

---
## 案例 9（新增）：占位符残留 + 结构不一致（输出偏离项目风格）🔴

**场景**：生成的文件里还留着 `{业务名}`、`{实体类}` 模板占位符，或 `partial class` 类名不匹配、`IView` 属性暴露 `get`。

**症状**：
- 编译报错：`{业务名}Presenter` 类型不存在（占位符未替换）
- 编译报错：partial class 类名不一致（`frmPart.Management` vs `frmPartsManagement`）
- 编译报错：接口属性有 `get` 导致 Presenter 调用方式不匹配

**根因**：生成后未做结构完整性校验。

**修复方案**：
1. `grep -c '{业务名}\|{实体类}\|{表名}' *.cs` — 计数应为 0
2. `grep -c 'TODO\|// 待实现\|NotImplementedException' *.cs` — 计数应为 0
3. 检查 `frmX.Designer.cs` 和 `frmX.cs` 的 `partial class frmX` 类名一致
4. 检查 `I{业务名}View` 接口属性只有 `{ set; }`

**预防**：Step 5b 前执行冒烟测试（5b-pre），见 SKILL.md Step 5。

---

## 通用预防清单

在任何 Step 卡顿时，自查这张表：

- [ ] Step 0a 最小输入是否完整（业务名 / Entity 或字段来源 / 项目根 + 目标目录 / 构建入口）
- [ ] Step 1 模式提取表是否填写完整（含基类 / 数据访问 / GridStyle / DBHelp / 命名前缀）
- [ ] Step 2 字段映射前是否已获取 Entity 字段或表 schema
- [ ] Step 3 frm/ucl 决策是否合理（业务独立 vs 复用）
- [ ] Step 4 Designer 是否加载了 `designer-template-list.md`
- [ ] Step 5a review-checklist 是否全过，Step 5b-pre 冒烟测试是否通过（无占位符/TODO/partial class 名不一致），Step 5b MSBuild 是否已执行并记录结果

## 如何往本文件加新案例

1. 在对应分类下追加
2. 同步更新 SKILL.md 的 constraints（如本案例触发了新红线）
3. 同步更新 `references/review-checklist.md` 的对应检查项
4. 在 git commit message 中标注 `failure-modes: add case N — <name>`
