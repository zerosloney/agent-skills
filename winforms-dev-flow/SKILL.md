---
name: winforms-dev-flow
description: |
  WinForm + DevExpress 业务窗体生成（.NET Framework 4.7.2）。

  **何时使用（按场景）**：
  - **创建**：user says "create a business form" / "generate form and bind data" / "create presenter/ser"；或描述 建列表窗体、主从结构、编辑弹窗、查询/新增/修改/删除 界面
  - **维护/扩展**：user says "加个列" / "加个导出按钮" / "改成泛型风格" / "换成 ORM"；或对既有窗体做增量编辑、架构迁移、ucl 抽取
  - **按风格生成**：user says "按 X 模块风格" / "跟 frmXXX 一样"，参照项目既有窗体模式生成
  - **故障修复**：生成的窗体编译/运行报错，如 `SqlOperate 找不到` / `GridStyle 未注册` / `DALBase<T> 编译失败` / `控件挤一起/Tab 乱` — 此时先查 `references/failure-modes.md` 顶部「症状→案例速查表」定位根因

  **不要用于**：简单对话框、纯 API 调用、无 DevExpress 的基础 WinForms。
---

# WinForm + DevExpress 业务窗体生成

## 核心理念

**先学后生成**：扫目标目录邻近窗体，按真实模式（基类/命名空间/数据访问）生成。无参照时让用户指定或参照 `three-tier-mvp.md`。

## Constraints（红线）

越界即停，停下来问用户。

1. **参照真实代码优先**：扫描兄弟/父级目录，提取最相似窗体模式。不臆造基类/命名空间/数据访问。
2. **Entity 先行**：Ser/DAL 前确认 `Entity.{实体类}` 存在；缺失问用户（新建/复用），不臆造字段。
3. **分层不可越级**：`View → Presenter → Ser →（DAL）`，禁 View 直调 Ser/DAL，禁 Presenter 直调 DAL。DAL 层按 Step 0b 检测结果决定是否生成（详见 Step 4）；项目无独立 DAL 层时 Ser 直接持有数据访问，不算越级。**新代码不生成 Collection 层**；发现既有 Collection 中间层时停下来提示用户确认，不擅自合并或删除。
4. **项目路径需确认**：写文件前明确项目根 + 目标目录；无法推断时问，不默认当前目录。
5. **不越界生成**：仅生成本窗体 6 类文件（frm/Designer/View/Presenter/Ser/DAL），不动 DB/迁移/其他模块。**DAL 层按项目实际结构决定**：参照窗体有独立 `*DAL.cs` 时生成，无时内联到 Ser（`three-tier-mvp.md` 无 DAL 层变体）。
6. **模式无法判定时询问**：扫不到同类窗体或邻近窗体结构不一致时，展示差异让用户选，不默认。
7. **模式必须在 Step 1 统一确认**：基类、数据访问、GridStyle 代号、DBHelp 连接名、命名空间、命名前缀都从参照窗体提取；无法判定则问用户。Designer 必加载 `designer-template-list.md`。

## 快速查找

> 按需加载，不要全量读。

| 需要查 | 加载 |
|--------|------|
| DevExpress 21.2 程序集清单、控件精确配置、字段→控件映射 | `references/dev-21.2-reference.md` |
| Skin/Theme 管理、21.2 皮肤名称表 | `references/skin-theme.md` |
| 常见陷阱（RepositoryItem、排序、DateEdit 格式等） | `references/common-pitfalls.md` |
| 控件使用规范、项目家族特定配置 | `references/devexpress-controls.md` |
| Designer 模板选择、InitializeComponent 片段库 | `references/designer-template-list.md` + `references/designer-patterns.md` |
| 三层架构 + 命名规范 | `references/three-tier-mvp.md` |
| 项目指纹扫描 | **权威**：`python scripts/scan_project.py --root "<项目根>"`（脚本为准，PowerShell 命令仅作降级）。**降级条件**：Python 不可用或脚本失败时，用 `references/project-fingerprint.md §0.2` 的 PowerShell glance 命令（与脚本同源，修改时需同步两处） |
| 失败案例排查 | `references/failure-modes.md` |
| Entity/字段缺失，需连库查 schema | **前置**：需在 WorkBuddy 连接器管理启用 `database-explorer` MCP。启用后：`mavis mcp call database-explorer query --sql "SELECT ..."`，连接串从项目 `App.config` 读。**MCP 未连接时 fallback**：让用户直接粘贴 `Entity.{实体类}` 字段定义或表 schema，不阻塞流程 |
| 增量编辑现有窗体（加列/加按钮/修改 Designer） | `scripts/incremental_designer.py`（VisibleIndex 自动计算 + 代码生成） |
| 全新窗体 InitializeComponent 草稿生成 | `scripts/designer_generator.py`（4 家族 × 3 场景模板引擎） |
| MSBuild 编译验证命令模板 | `references/msbuild-commands.md` |
| 生成后冒烟测试（5 项上下文无关 + 2 项上下文相关） | `python scripts/smoke_test.py --dir <生成目录>`（5 项）；加 `--reference <参照窗体.cs>` 启用 IView 契约 + GridStyle 代号一致性检查（共 7 项） |

## 架构分层（统一）

```
View (frm / ucl)  →  Presenter (协调器)  →  Ser (BLL: 内存缓存 + 业务校验)  →  DAL  →  Entity
```

- **View**：frm/ucl，实现 `I{业务名}View`，构造注入 Presenter
- **Presenter**：协调器，调 Ser 后通知 View 刷新
- **Ser（=BLL）**：维护 `_lst{Entity}` 内存缓存 + 业务校验，**直连 DAL**
- **DAL**：数据访问层；方式（`SqlOperate+ListOperate` 或 ORM `Query<T>()`）**由参照窗体决定**
- **Entity**：setter 调 `AddRecordChange` 做变更追踪

> 基类/命名空间/泛型/数据访问均以 Step 1 真实窗体为准，技能不预设。

## Procedure

### Step 0. 定位目标目录

1. 确认目标目录（业务模块路径）
2. 扫描**同级 + 父级**目录窗体（`frm*.cs` / `*Presenter.cs` / `*Ser.cs` / `*DAL.cs` / `I*View.cs`）
3. 找 1–2 个最相似窗体作参照

### Step 0a. 最小输入门

> Step 0a 只确认任务输入与可写位置，不判定技术模式。基类、数据访问、GridStyle、DBHelp 等模式统一由 Step 1 从参照窗体提取。

| # | 确认项 | 选项/示例 | 获取方式 |
|---|--------|----------|----------|
|---|--------|----------|----------|
| 1 | **业务名 / 窗体名** | `PartsManagement` / `Frm_PartsList` | 用户描述或菜单/模块名 |
| 2 | **Entity 或字段来源** | `Entity.PartInfo` / 表名 / 字段清单 | 现有 Entity、DB schema、用户提供字段 |
| 3 | **项目根 + 目标目录** | `.sln` 所在目录 + 业务模块目录 | 用户指定；无法推断时问 |
| 4 | **构建入口** | `.sln` / `.csproj` + Configuration/Platform | 优先项目现有配置；多候选时问 |
| 5 | **数据库可连性** | 可连 / 不可连（连接串在 App.config） | 若 Entity/字段缺失且 App.config 有连接串，可用 `mavis mcp call database-explorer query --sql "SELECT ..."` 连库查 schema。**前置**：需先在 WorkBuddy 启用 `database-explorer` MCP（详见快速查找表）；MCP 未连接时让用户直接粘贴字段定义，不阻塞 |

缺少 1/2/3 时先问用户；**缺少 4（构建入口）时阻断，不进入 Step 1**。无法确认 `.sln` / `.csproj` 路径及 Configuration/Platform，Step 5b MSBuild 验证无法执行，交付物不可验证。

**Designer 强制门**：Step 4 前必加载 `references/dev-21.2-reference.md`「输出文件精确规范」节 + `designer-template-list.md` + `designer-patterns.md`，按选中模板复制，不凭印象拼 InitializeComponent。

### Step 0b. 项目指纹识别(防案例 5 同项目两套风格)

> **必跑**。**全项目扫描**(不只 1-2 个对照窗体),输出项目家族 + 异质性等级,作为 Step 1 的输入。
> **权威来源**：指纹扫描以 `python scripts/scan_project.py --root "<项目根>"` 为准，直接输出指纹卡。
> **降级路径**：Python 不可用或需调试时，用 `references/project-fingerprint.md §0.2` 的 PowerShell glance 命令（与脚本同源）。
> ⚠️ **修改指纹逻辑时必须同步改脚本和 PowerShell 命令两处**，避免漂移。
> 异质性等级 🟢 → 直接进 Step 1；🟡/🔴 → 按提示用户二选一。

#### 两档命令一览

| 档位 | 触发 | 命令 | 输出 | Token 开销 |
|------|------|------|------|----------|
| **glance**(默认) | 所有任务第一步 | 6 个查询(基类 / 数据访问 / GridStyle / Collection / DAL 完整性 / 连接名),**全部过滤注释** | 迷你指纹卡(7 行) | ~700 token |
| **deep**(完整) | glance 输出 🟡/🔴 / 用户主动要求 / 关键词触发 | §1 全套 + git log | §4 完整指纹卡 | ~2000 token |

#### glance 命令

> **权威命令在 `references/project-fingerprint.md`**：§0.2 = `rg` 版（推荐，8s），§0.3 = Select-String 兜底版（`rg` 不可用时，递归扫描）。
> ⚠️ **必须用文件级去重 + `SkipComment` 过滤注释**，不要用简化版行级计数（`rg -l ... .Count`）——否则会把注释残留当真实调用（实测 `varlist.ASSConn` 误扫 311 次全是注释）。
> ⚠️ 修改指纹逻辑时必须同步改 `scripts/scan_project.py` 与 reference §0.2/§0.3 两处，避免漂移。

#### 输出与决策

**glance 输出**:迷你指纹卡(见 `project-fingerprint.md` §0.4)。

**决策流程**:
- 🟢 纯一(4 维度主导都 ≥95%):直接进 Step 1(用 glance 卡即可)
- 🟡 主导+少数(任一维度 75-95%):**自动升级到 deep**,补 §1.2-1.4
- 🔴 严重分裂(任一维度 <75% 或目标模块子目录 GridStyle ≥2 种代号):**自动升级到 deep**,走 ask_user a/b/c
  > 全项目级多代号 ≠ 🔴:子模块专用代号(如 `SM.UI` 全用 SM 系列)是正常状态,只要目标模块子目录代号单一就不升级。详见 `project-fingerprint.md §0.5`。
- 用户输入含"项目很乱"/"做个完整指纹"/"新模块上线"等关键词 → **直接 deep**(不跑 glance)

**忽略条件**:用户明确说"按 X 模块风格"(此时跳过,但仍建议跑一次 glance 存档指纹卡)。

**deep 档完整探测**:见 `project-fingerprint.md` §1(1.1-1.5 全套),输出 §4 完整指纹卡。
**deep 档 ask_user 模板**:见 `failure-modes.md` 案例 5 + `examples/example-4-gridstyle-multi-codes.md` §5。

### Step 1. 参照学习 + 项目级模式确认

读取 Step 0 找到的最相似窗体的源码，**显式提取并列出**以下要素（让用户确认）：

| 提取项 | 说明 |
|--------|------|
| 窗体基类 | `frmBase` / `frm_Base` / 其他（注意下划线差异） |
| 命名空间 | UI 层、BLL 层、DAL 层、Entity 层的命名空间 |
| `using` 引用 | DAL / Entity / Common 等关键引用 |
| 数据访问方式 | `SqlOperate`+`ListOperate` 原始 SQL / ORM `Query<T>()` |
| 是否泛型 | Presenter/Ser 是否有 `Base<T>` 泛型基类链 |
| GridStyle 代号 | `"ASS"` / `"CRS"` / 其他 |
| DBHelp 实例 / 连接名 | **不预设默认值**；必须扫描项目自己的非注释调用确认——优先从 Step 0b glance 扫描结果 `$connTop` 读取（已过滤注释的 top1）；若 glance 扫描结果为空或多个候选，用 `grep 'varlist\.[A-Za-z]+(Conn|DBHelp)'` 在项目源码中二次确认；连接串从 `App.config` 或 `varlist.*Conn` 属性读取 |
| 类名前缀约定 | `DALMM_` / `Frm_` / `DlgEdit_` 等 |
| WaitDialog | `varlist_Dialog` / `UICommonBase.StartWaitForm` |
| 消息框 | `XtraMessageBox.Show` / `UICommonBase.ShowMessageBox` |
| 事件结构 | `try-catch-finally` 包裹方式、异常提示风格 |
| View 接口风格 | **与参照窗体一致**：参照用单向 `set` 属性就用 `set` 属性；参照用方法式（`Set{X}(List<..>)` / `ShowMessage(..)` / `ConfirmYesNo(..)` / `Refresh{X}()`）+ get-only 输入属性就用方法式——**不要一刀切强制 set-only** |
| 绑定方式 | `gc.DataSource = value` 等 |

**提取结果须以表格形式展示给用户确认**："从 `frmXXX.cs` 学到以下模式，是否按此生成？"

**兜底**：连接串查 `App.config`；DBHelp 名 grep `varlist\.[A-Za-z]+(DBHelp|Conn)`；GridStyle 查 `new GridStyle(...)` 第一参数。仍无法确认时把候选列出让用户选（NEED_CONTEXT）。

### Step 1b. 模式无法判定时

**必须询问**（不接受默认猜测）：
- 扫不到任何同类窗体
- 邻近窗体结构不一致（部分 SQL / 部分 ORM）

按真实代码差异列选项，不按"模式名"。无参照时让用户指定路径，或参照 `three-tier-mvp.md` 与用户逐项确认。

### Step 2. 数据驱动布局

1. 读 `Entity.{实体类}` 的字段定义
2. 按字段类型和数量决定布局：
   - 字段少（≤8）且为表单录入 → `LayoutControl` 表单
   - 字段多、列表展示 → `GridControl` + `GridView`
   - 有层级/分类字段 → `TreeList`（主） + `GridControl`（从）
3. 建立「字段 → 控件」映射表（展示给用户）：

| Entity 字段 | 类型 | 控件 | 列/项名 |
|-------------|------|------|---------|
| ID | Guid 主键 | 隐藏列 | — |
| Name | string | TextEdit 列 | 名称 |
| Status | 枚举 | RepositoryItemComboBox | 状态 |
| ... | ... | ... | ... |

> 控件选型参考见 `references/dev-21.2-reference.md`「字段→控件精确映射」节。

### Step 3. 复用决策（frm vs ucl）

判断新建独立窗体还是复用/抽取用户控件：

| 场景 | 决策 |
|------|------|
| 业务独立、需独立菜单/权限入口 | 新建 `frm` 窗体 |
| 会被多个窗体嵌入，或与主窗体主从联动 | 抽取 `ucl` UserControl |
| 项目已有可复用的同类 ucl | 引用现有 ucl，不重复生成 |

若决策为 ucl，加载 `references/usercontrol-patterns.md` 获取三种 UserControl 变体。

### Step 4. 三层生成 + 绑定

按学到的模式（Step 1）+ 字段映射（Step 2）+ 复用决策（Step 3）生成：

**生成顺序**（数据流向）：
1. **Entity 确认**：确认 `Entity.{实体类}` 字段完整（Step 2 已做）
2. **DAL 层（可选）**：仅当 Step 0b 查询 5 输出 `dalRatio ≥ 0.5` 或参照窗体有独立 `*DAL.cs` 时生成新 DAL；**若项目已有 DAL 层但无 Collection 中间层（典型如 CSS.*.Extend/WHXL：Ser 直接 `new DAL{Entity}()`），新窗体 Ser 复用既有 DAL 层，不新建 DAL、不内联 SqlOperate**；仅当项目既无 DAL 层也无 Collection 层时才走「无独立 DAL 层」变体——数据访问内联到 Ser
3. **Ser(BLL) 层**：内存缓存 `_lst{Entity}` + 业务校验；有 DAL 层时 Ser 持有并复用既有 DAL（`new DAL{Entity}()`），无 DAL、无 Collection 时才直接持有 `SqlOperate`/`DbHelp`
4. **Presenter**：协调器，调 Ser 后通知 View 刷新
5. **View 接口** `I{业务名}View`：**成员风格保持与参照窗体一致**——参照用单向 `set` 属性就用 `set` 属性；参照用方法式（`Set{X}(List<..>)` / `ShowMessage(..)` / `ConfirmYesNo(..)` / `Refresh{X}()`）+ get-only 输入属性时也用方法式，不强改为 set-only（实测 WHXL/CSS.*.Extend 全线方法式，CRS 全线 set 属性，二者都合法）
6. **窗体/Designer**：实现 View 接口，`_Load` 中创建 Presenter，绑定控件

> 代码严格遵循 Step 1 真实模式，不套静态模板。需架构/绑定规范时加载 `three-tier-mvp.md`。

**⚠️ Presenter 事件退订规范（防内存泄漏）**：
若 Presenter 订阅了 View 的**任意事件**（`View.SomeEvent += ...`），无论事件名称是 `Load`/`Shown`/`FormClosing`/`FormClosed` 还是其他，均须完整退订：
- Presenter **必须**实现 `IDisposable`，在 `Dispose()` 中 unsubscribe 所有已订阅事件（`View.SomeEvent -= handler`）
- View 在 `FormClosing`/`FormClosed`/`Dispose` 中调用 `Presenter?.Dispose()`（**参照窗体有哪种就用哪种**，不必强求一种）
- **参照窗体检查**：若参照窗体调用了 `Presenter?.Dispose()`（或 `Presenter.Dispose()`），新代码跟随；若参照没有，则新代码**必须补上** `Presenter?.Dispose()` 调用，否则视为缺陷

### Step 5. 循环反馈（双层闭环）

```
┌─────────────────────── 内层：自审（自动）───────────────────────┐
│  5a  review-checklist 逐项过 (A设计/B绑定/C输出)                │
│   ↓                                                            │
│  5b-pre  smoke_test.py 5项 + 上下文相关2项 (对照参照窗体)       │
│   ↓                                                            │
│  5b  MSBuild 构建 (.sln 优先, 无则 .csproj)                    │
│   ↓                                                            │
│  5c  不通过 → 回对应 Step 修正 → 重审全部 checklist (防新问题)   │
└────────────────────────────────────────────────────────────────┘
                          ↓ 全过
┌─────────────────────── 外层：用户反馈 ─────────────────────────┐
│  5d  交付: 文件清单 + 关键决策 + 构建命令 + 未覆盖项             │
│   ↓                                                            │
│  5e  用户反馈 → 识别影响环节 → 回对应 Step 改 → 重跑 5a/5b       │
└────────────────────────────────────────────────────────────────┘
                          ↓
✅ 自审全过 + MSBuild 通过 + 用户确认  |  ⏸ 用户说「先这样」
```

#### 内层：自审（自动）

- **5a** 加载 `review-checklist.md`，逐项过 A 设计/B 绑定/C 输出
- **5b-pre 冒烟测试**（MSBuild 前的上下文无关快速检查，30 秒内完成，5 项）：
  - 无占位符残留（`{业务名}` / `{实体类}` / `{表名}` 等）
  - 无 `TODO` / `// 待实现` / `throw new NotImplementedException()`
  - `frmX.cs` 与 `frmX.Designer.cs` 的 `partial class` 类名一致
  - 无空 catch 块（吞异常）
  - 无重复事件订阅（同一事件 `+=` handler ≥2 次）
  - 以上 5 项可自动化：`python scripts/smoke_test.py --dir <生成目录>`
- **5b-pre 上下文相关自审**（对照 Step 1 参照窗体，**可自动化**）：
  - **自动化**：`python scripts/smoke_test.py --dir <生成目录> --reference <参照窗体.cs>` — 自动检查以下 2 项
  - `I{业务名}View.cs` 成员风格与参照窗体一致：**仅当参照本身是 set 属性契约时**才要求属性只有 `{ set; }`（无 `{ get; }`）；若参照是方法式契约（`Set{X}(..)` 等 + get-only 输入属性），则允许方法与 `{ get; }` 输入属性，不得据此判负
  - GridStyle 第一参数**保持与参照窗体一致**：参照窗体用字面量代号就保持字面量，参照用变量才用变量——**不要一刀切强制改为变量**。项目主导代号通常为字面量（实测 CRS 用 `"CRS"`、ASS/Upgrader 用 `"ASS"`，均与真实代码一致），此时保持 `new GridStyle("<项目代号>", this, gc, gv)` 原样；仅当同目录出现 ≥2 种代号（Step 0b 判定异质）时才考虑参数化。
- **5b** 用 MSBuild 构建 WinForms 项目：
  - 优先构建 Step 0a 确认的 `.sln`；没有 `.sln` 时构建目标 `.csproj`
  - 使用项目既有 Configuration/Platform；无法推断时问用户
  - Windows/.NET Framework 项目用 `MSBuild.exe`，不要用 `dotnet build` 代替
  - 构建失败时只修复本次生成/修改导致的错误；若是预先存在或环境缺依赖，交付时明确列出
  - **命令模板**：用 `vswhere.exe` 动态探测 MSBuild.exe 路径（覆盖 Community/Professional/Enterprise/BuildTools，注册表降级）再构建——完整可执行命令（探测 + `.sln`/`.csproj` 构建 + 失败诊断）见 `references/msbuild-commands.md`。
- **5c** 不通过项回到对应 Step 修正（A→Step 2/4，B→Step 4，C→补文件/替占位符，MSBuild→修编译错误）
- 修正后**重审全部 checklist**，避免引入新问题

#### 外层：用户反馈

- **5d** 自审 + MSBuild 通过后交付：文件清单 + 关键决策 + 构建命令 + 未覆盖项
- **5e** 用户反馈→识别影响环节→回对应 Step 改→重跑 5a/5b→再次交付

#### 终止

✅ 自审全过 + MSBuild 通过 + 用户确认；⏸ 用户说「先这样」。无轮数上限。

## 对话框 & Entity 模式

> 生成对话框或 Entity 属性时，加载 `dialog-patterns.md` + `three-tier-mvp.md`。

## References

> 按需加载，不要全量读。标准生成流程只需 **L1-core**（11 个核心文件，每次加载）+ **L1-conditional**（按场景触发，0–8 个文件）+ **L2**（高级手册，用户要求对应功能时才读）。

### L1-core — 核心必读（每个生成任务都要加载）

| 文件 | 用途 | 加载时机 |
|------|------|---------|
| `references/three-tier-mvp.md` | 三层架构 + 命名规范 + 无 DAL 层变体 | Step 1 / Step 4 |
| `references/project-fingerprint.md` | 项目指纹 + 异质性检测（含 glance/deep 两档完整命令） | Step 0b（每次必跑） |
| `references/designer-patterns.md` | 4 项目家族 × 6 控件场景的 InitializeComponent 片段库 | Step 4 必查 |
| `references/dev-21.2-reference.md` | DevExpress 21.2 精确实现：程序集清单、控件配置、字段→控件映射表、输出规范 | Step 4 必查 |
| `references/designer-template-list.md` | 模板选择决策表 | Step 4 必加载 |
| `references/msbuild-commands.md` | MSBuild.exe 命令模板、参数说明、常见失败诊断 | Step 5b 必查 |
| `references/failure-modes.md` | 症状→案例速查表 | 任意 Step 卡顿时先查顶部 |
| `references/review-checklist.md` | Step 5a 自审清单 | Step 5a |
| `scripts/smoke_test.py` | 生成后冒烟测试（5 项上下文无关 + 2 项上下文相关，`--reference` 启用） | Step 5b-pre |
| `scripts/incremental_designer.py` | 增量编辑：分析现有 Designer.cs + 生成加列/加按钮代码（VisibleIndex 自动计算） | Step 4 增量场景 |
| `scripts/designer_generator.py` | 全新窗体：4 家族 × 3 场景 InitializeComponent 草稿生成引擎 | Step 4 全新场景 |

### L1-conditional — 按场景加载（特定条件触发才读）

| 文件 | 触发条件 |
|------|---------|
| `references/designer-template-{a-crud|b-form}.md` | Step 4 选中了主从（a）或表单（b）模板时；多 Tab 场景直接走 `designer-patterns.md` §1.2/§1.6 |
| `references/dialog-patterns.md` | 用户说"生成对话框"时 |
| `references/usercontrol-patterns.md` | Step 3 决策为 ucl 时 |
| `references/banded-gridview.md` | Step 2 选用了 BandedGridView（分带网格）时 |
| `references/devexpress-controls.md` | 控件使用规范（GridControl/TreeList/LayoutControl 配置、命名规范）需要时 |
| `references/common-pitfalls.md` | 遇到 RepositoryItem/排序/DateEdit/GridStyle 调用顺序等已知坑时 |
| `references/skin-theme.md` | 用户说"改皮肤"/"换主题"时 |
| `references/decision-trees.md` | 需要可视化决策路径时 |

### L2 — 高级功能手册（按需加载，标准流程不读）

> ⚠️ **以下文件是高级功能手册，标准生成流程不需要加载。仅当用户主动要求对应功能时才读取。**
> 这些文件覆盖生成窗体之后的增强功能（条件格式、导出、拖拽、级联等），不是 MVP 生成的必需知识。

| 文件 | 触发条件 |
|------|---------|
| `references/advanced-features.md` | 用户要求以下任一：状态颜色/分页/右键菜单/TreeList 拖拽/级联填充/报表打印/多选下拉/等待窗体/HTML 模板/VGridControl/Accordion/DirectX Form 等 37 个高级特性（顶部有关键词索引表） |
| `references/gridview-advanced.md` | 用户要求 GridView 条件格式/汇总/排序/筛选/行高/外观时 |
| `references/treelist-advanced.md` | 用户要求 TreeList 节点操作/主从联动/拖拽/筛选时 |
| `references/editors-reference.md` | 需要 14 种编辑器（TextEdit/DateEdit/LookUpEdit 等）精确配置时 |
| `references/layout-advanced.md` | 用户要求 LayoutControl 三种布局/分组/保存恢复/可见性控制时 |
| `references/print-export.md` | 用户要求导出 Excel/CSV、打印预览时 |

## 文件输出 & Output contract

路径以 Step 0 参照窗体同级目录为准。UTF-8 无 BOM。文件数与拆分同参照窗体。新代码不生成 Collection；若参照结构已有 Collection 中间层，先提示用户确认。

### 输出文件精确规范

> 详细规范见 `references/dev-21.2-reference.md`「输出文件精确规范」节。
> Designer.cs 不手改——布局变更通过 Visual Studio Designer 完成，或整体替换 InitializeComponent。

## 不生成守卫

以下内容**不在生成范围内**，任何 Step 不得产出：

| 禁止生成 | 原因 |
|---------|------|
| **DB 迁移脚本** | 不动 DB/迁移/其他模块（Constraint #5） |
| **Entity 字段补全文件** | 字段缺失走 failure-modes 案例 2 三选一，不自动生成补丁 |
| **参照窗体的已有方法** | 只生成本窗体 6 类文件，不改/不扩展参照窗体 |
| **Collection 中间层** | 若项目已存在 Collection 层（典型如 CRS 的 `CRS.BLL.Collection` 命名空间，每个业务 Ser 持有 `{Entity}Collection` 实例并复用其查询/增删方法），新窗体 Ser **必须复用**该 Collection（`using CRS.BLL.Collection;` + 持有 `{Entity}Collection` 实例），不要内联 `SqlOperate` 或新建 DAL）；**若项目无 Collection 层但有 DAL 层（典型如 CSS.*.Extend/WHXL），Ser 复用既有 DAL 层（`new DAL{Entity}()`），不内联 SqlOperate**；仅当项目既无 Collection 也无 DAL 层时才走内联变体，且不擅自合并/删除既有 Collection |
| **项目级配置**（App.config / web.config 修改） | 不动项目配置文件 |
| **NuGet 包 / 程序集引用修改** | .csproj 引用由项目既有配置决定，不自动添加 |
| **测试项目 / 单元测试** | 当前 skill 只覆盖业务窗体生成 |
| **SQL 脚本 / 存储过程** | 数据访问 SQL 内联在 Ser/DAL 文件内，不生成独立 .sql 文件 |
| **文档 / README** | 不生成模块文档 |
| **其他窗体的修改** | 仅操作目标窗体文件，不动兄弟窗体 |

> **违反对策**：若生成过程中发现需要上述内容，停下来问用户，不自行推断。

## Failure handling

> 任意 Step 卡顿时，**先查 `references/failure-modes.md` 顶部「症状→案例 速查表」** 定位根因和修复方案。
> 下表是每个 Step 容易触发的失败案例快查。
> 编号体系:「案例 N」指 `references/failure-modes.md` 的案例编号;`examples/example-N-*.md` 是独立样例文件,两套编号无对应关系。

| Step | 易触发案例 | 看症状 |
|------|-----------|--------|
| **Step 1 模式学习** | 案例 1 / 4 / 5 / 8 | `SqlOperate` 找不到 / `GridStyle 未注册` / `无法转换泛型` / 类名风格不一致 |
| **Step 2 数据驱动布局** | 案例 3 | 没有 Entity、没有字段清单、表 schema 不可读 |
| **Step 4 三层生成 + 绑定** | 案例 2 / 6 | `DALBase<T> 编译失败` / 用户看到两次弹窗 |
| **Step 4 后段 Designer** | 案例 7 | Designer 打开错位 / TabOrder 乱 / resx 报错 |
| **最终交付前** | 案例 8 | 文件名/类名前缀与项目其他模块不一致 |
| **5b-pre 冒烟** | 案例 9 | 占位符残留 / TODO / partial class 名不一致 / IView 属性暴露 get |

通用兜底：
- **Entity 不存在**：问用户(对应案例 2)
- **扫不到参照窗体**：让用户给路径;若无则按 `three-tier-mvp.md` 确认(对应案例 3)
- **邻近窗体结构不一致**：展示差异让用户选(对应案例 5)
- **DAL 方法不确定**：参考项目现有 DAL 文件
- **布局复杂**：先用简单 GridControl，逐步加复杂度
- **SQL 异常**：Ser 层 catch 后按参照窗体消息框风格展示(对应案例 6)

## Fallback strategies

> 每个标签都对应 `references/failure-modes.md` 一个具体案例,触发时加载。

- **NEED_CONTEXT（模式判定失败）**→ 对应 **案例 5**:扫不到同类窗体或邻近结构不一致时，把真实代码差异列出让用户选
- **NEED_REFERENCE（无参照）**→ 对应 **案例 3**:让用户给路径;若不能则按 `three-tier-mvp.md` 逐项确认，不臆造
- **NEED_DBHELP（DBHelp/连接名未知）**→ 对应 **案例 1**:扫不到 DBHelp 实例名或连接名时，让用户从候选列中选
- **STUCK（未知控件）**→ 对应 **案例 7**:降级为 `GridControl` + 单列 `GridView`;告知「最小化布局,列配置后续补」,并加载 `designer-patterns.md` §5 通用坑位
- **NEED_ENTITY（字段不明）**→ 对应 **案例 2**:不臆造,让用户提供 `Entity.{实体类}` 字段定义;或连 DB 查 schema(案例 3)

## Examples

遇到类似任务前,按场景或症状只读一个最接近的样例;遇到 Step 卡顿,先查 `references/failure-modes.md` 顶部「症状→案例 速查表」。
> 编号体系:`example-N` 指本目录 `examples/` 下的样例文件;「案例 N」指 `failure-modes.md` 的案例号,两套编号无对应关系。

| 用户原话 / 症状关键词 | 场景 | 读取 |
|----------------------|------|------|
| "加个 XX 列表窗体" / `SqlOperate 找不到` / `varlist.ASSDBHelp` / 类名前缀不一致 | CSS.WHXL.Extend 单表 CRUD / DBHelp 命名差异 / 前缀约定 | `examples/example-1-partsmanagement-crud.md` |
| "Entity 字段不全" / `DALBase<T> 编译失败` / 仅 DTO / Update 丢字段 | Entity 不完整,需补字段决策(A/B/C 三选) | `examples/example-2-warehouse-entity-incomplete.md` |
| "没有 Entity" / "表结构不知道" / DB 连不上 / schema 不可读 | 无 Entity、无表文档、DB 不可达 | `examples/example-3-schema-unknown-db-unreachable.md` |
| "项目代号乱" / `GridStyle [X] 未注册` / 同项目多代号 / Step 0b 异质性 🔴 | GridStyle 多值共存,子目录级判定 | `examples/example-4-gridstyle-multi-codes.md` |
| "要不要生成 Collection 层" / 既有 Collection 中间层 / 架构分层变了 | Collection 层架构退化检测,新代码是否跳过 | `examples/example-5-collection-layer-merge.md` |
| "异常写哪层" / try-catch 风格不一致 / 弹两次框 | Upgrader vs CRS 异常处理风格提取(案例 6) | `examples/example-6-exception-handling-style.md` |
| "Designer 打开错位" / TabOrder 乱 / InitializeComponent 手写 | Designer 模板选择(4 家族×6 场景,案例 7) | `examples/example-7-designer-template-selection.md` |
| "加个创建时间列" / "加个导出按钮" / 现有窗体功能扩展 | 增量编辑：只 Add 不改已有代码 | `examples/example-8-incremental-edit.md` + `scripts/incremental_designer.py` |
| "改成泛型风格" / "换成 ORM" / 架构迁移 | Upgrader→CRS / 无DAL→有DAL 逐步迁移 | `examples/example-9-architecture-migration.md` |
| "多个窗体共用搜索区" / 抽出公共控件 | ucl 抽取：变体 A/B/C 选择 | `examples/example-10-ucl-extraction.md` |
