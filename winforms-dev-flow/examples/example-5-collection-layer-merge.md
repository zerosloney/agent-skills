# Example 5 — Collection 层合并场景 (架构退化检测)

> 对应 failure-modes 案例 2 (Entity 不完整) + 案例 5 (泛型 vs 非泛型混用)。
> **核心场景**:Step 0b 检测到项目处于"有 Collection 层 → 无 Collection 层"的架构退化期，新代码不再生成 Collection 层。
> **档位**:deep 档 (因为涉及架构分层变更)。

---

## 1. 场景描述

**用户原话**:
> "老项目里有 Collection 层 (`Collection_Parts`)，但最近半年的新代码都不生了，直接把数据访问塞进 Ser。我想确认下新窗体要不要跟这个变化？"

**上下文**:
- 项目：`.NET Framework 4.7.2` + WinForms + DevExpress 21.2
- 架构过渡期：老模块 `View → Presenter → Ser → Collection → DAL → Entity`
- 新模块：`View → Presenter → Ser → DAL → Entity` (跳过 Collection)
- Step 0b 检测到 `collCount = 12` (老模块) vs `collCount = 0` (近 6 个月新模块)

---

## 2. Step 0 — 目标目录定位

```bash
PROJECT_ROOT = C:\Src\LegacyProject
TARGET_DIR   = C:\Src\LegacyProject\Modules\NewFeature\UI
MODULE_NAME  = NewFeature
```

---

## 3. Step 0a — 4 项必填门

| # | 确认项 | 取值 | 来源 |
|---|--------|------|------|
| 1 | 业务名 / 窗体名 | `NewFeature` / `Frm_NewFeatureList` | 用户原话 |
| 2 | Entity 或字段来源 | `Entity.NewFeatureInfo`(已存在) | 项目已有 |
| 3 | 项目根 + 目标目录 | 见 §2 | 用户已说 |
| 4 | 构建入口 | `LegacyProject.sln`, Configuration=Debug | 项目默认 |

✅ 4 项齐。

---

## 4. Step 0b — 项目指纹卡 (本案核心)

> **命令**:跑 `references/project-fingerprint.md §0.2` glance 档 + 升级到 deep 档 (因为 Collection 层存在性异质)。

### 4.1 glance 输出

```text
项目：C:\Src\LegacyProject                    扫描：2143 .cs
┌─────────────────┬────────┬────────┬────────────────────────────────┐
│ 维度            │ 主导    │ 占比   │ 异类                           │
├─────────────────┼────────┼────────┼────────────────────────────────┤
│ 窗体基类        │ frmBase│ 97%    │ frm_Base<T>(3%)                │
│ 数据访问        │ SqlOp  │ 94%    │ DbHelp.Query(6%)               │
│ GridStyle 代号  │ "ASS"  │ 96%    │ "CSS"(4%)                      │
│ Collection 层   │ 有     │ 12 个   │ 近 6 个月=0 个 ⚠️              │
│ DAL 层完整性    │ DAL/Ser│ 0.08   │ DAL=12/Ser=150→无独立 DAL 层⚠️ │
│ 连接名 (top1)   │ ASSConn│ 142    │ ASSDBHelp=38(过滤注释后)       │
└─────────────────┴────────┴────────┴────────────────────────────────┘
异质性等级：🟡 主导+少数 (Collection 层 12 个但近 6 个月=0) → 自动升级到 deep
```

### 4.2 deep 档补充探测

```powershell
# §1.5 历史演化 (最近 6 个月 commit)
git log --since="6 months ago" --pretty=format: --name-only --diff-filter=A -- "*Collection*.cs"
# 输出：0 个新增 Collection 文件

git log --since="6 months ago" --pretty=format: --name-only --diff-filter=A -- "*Ser.cs"
# 输出：47 个新增 Ser 文件，全部无 Collection 引用
```

### 指纹卡输出

| 维度 | 老模块 (1 年前) | 新模块 (近 6 个月) | 趋势 |
|------|----------------|-------------------|------|
| Collection 层 | 12 个 (`Collection_Parts` 等) | 0 个 | ❌ 已废弃 |
| Ser 层数据访问 | 直连 Collection | 直连 DAL | ✅ 简化 |
| DAL 层完整性 | 独立 DAL 文件 | Ser 内联数据访问 | ⚠️ 退化 |

**异质性等级**:🟡 **主导+少数** (新代码已不生成 Collection，但老代码仍有)

**架构决策**:
- **新代码跟随新模块** (不再生成 Collection 层)
- **老 Collection 层逐步废弃** (不主动删除，但新代码不引用)

---

## 5. Step 0b 的 ask_user 处置

**必须**用 `ask_user` 让用户确认架构变更：

```markdown
⚠️ Step 0b 检测到项目处于架构退化期。Collection 层使用情况：

- 老模块 (1 年前):12 个 Collection 类 (`Collection_Parts`, `Collection_Warehouse` 等)
- 新模块 (近 6 个月):0 个 Collection 类，Ser 直接持有数据访问
- 趋势：项目从 5 层 (View→Presenter→Ser→Collection→DAL) 退化为 4 层 (View→Presenter→Ser→DAL)

新窗体 Frm_NewFeatureList 怎么处理？请选：

A. 跟随新模块 (不再生成 Collection 层) ✅ 推荐
   → Ser 直接持有 `_lstNewFeatureInfo` + 数据访问
   → 适合 简化架构，减少中间层

B. 跟随老模块 (仍生成 `Collection_NewFeature`)
   → 保持与老代码一致
   → 适合 老模块维护期，需要风格完全统一

C. 自定义 (说明你的架构需求)
   → 适合 特殊场景

(选 A/B/C 或自定义)
```

**用户回复**:"走 A，跟新模块，不再生成 Collection"

---

## 6. Step 0b 用户确认后的指纹卡 v2

```markdown
## 项目指纹卡 (v2,Step 0b 终版)

主家族：架构退化期 (Collection 层已废弃)

新窗体架构:4 层 (View→Presenter→Ser→DAL)
- Ser 直接持有 `_lstNewFeatureInfo` 内存缓存
- Ser 直接持有 `SqlOperate`/`ListOperate` 数据访问
- 不生成 `Collection_NewFeature` 中间层

其他维度仍走主导:
- 窗体基类：frmBase (97%)
- 数据访问：SqlOperate+ListOperate (94%)
- GridStyle: "ASS" (96%)
- DBHelp: varlist.ASSDBHelp / varlist.ASSConn

类名前缀：Frm_{业务名}List(从父级扫描)
命名空间：LegacyProject.Modules.NewFeature.UI
```

---

## 7. Step 1 — 模式提取表

参照窗体 (选了"新模块"后，找近 6 个月的窗体):
```powershell
& rg -l -g "*.cs" "class Frm_" $projectRoot | Select-Object -First 5
UI/NewFeature/Frm_StockList.cs    # 同模块最近窗体 (3 个月前 commit)
UI/RecentModule/Frm_Recent1.cs
```

→ 用 `Frm_StockList.cs` 作参照。

| 提取项 | 提取结果 | 备注 |
|--------|---------|------|
| **窗体基类** | `frmBase` | 非泛型 |
| **窗体命名** | `Frm_{业务名}List` | 有下划线 |
| **命名空间** | `LegacyProject.Modules.NewFeature.UI` | 模块级 namespace |
| **`using` 引用** | `LegacyProject.Modules.NewFeature.BLL`、`.Entity` | 无 `.Collection` |
| **数据访问方式** | `SqlOperate _so = new SqlOperate()` + `ListOperate _tolist = new ListOperate()` | Ser 直连 |
| **是否泛型** | ❌ 非泛型 | —— |
| **GridStyle 代号** | `"ASS"` | 与 glance 一致 |
| **DBHelp 实例 / 连接名** | `varlist.ASSDBHelp` / `varlist.ASSConn` | 过滤注释后确认 |
| **类名前缀约定** | `Frm_{业务}List`(带下划线) / Ser 无前缀 | —— |
| **WaitDialog** | `varlist_Dialog.SetWaitDialog(...)` | Upgrader 风格 |
| **消息框** | `XtraMessageBox.Show(...)` | 不是 `UICommonBase.ShowMessageBox` |
| **Collection 层** | ❌ 无 | Ser 直连 DAL |
| **Ser 内存缓存** | `_lstNewFeatureInfo = new List<NewFeatureInfo>()` | Ser 持有 |

**用户确认**:"按 `Frm_StockList.cs` 的模式生成 Yes/No?"

---

## 8. Step 2 — 字段→控件 映射表

`Entity.NewFeatureInfo` 字段 (扫描):

| Entity 字段 | 类型 | 控件 | 列/项名 | 备注 |
|-------------|------|------|---------|------|
| ID | Guid | 隐藏列 | — | 主键 |
| Code | string | TextEdit 列 | `colCode` | 编码 |
| Name | string | TextEdit 列 | `colName` | 名称 |
| Spec | string | TextEdit 列 | `colSpec` | 规格 |
| UnitPrice | decimal | SpinEdit 列 (对齐右) | `colUnitPrice` | 单价 |
| Qty | int | SpinEdit 列 | `colQty` | 数量 |
| Amount | decimal | SpinEdit 列 (只读) | `colAmount` | 金额 (=UnitPrice*Qty) |
| Status | enum | RepositoryItemComboBox | `colStatus` | 状态 |
| CreateTime | DateTime | RepositoryItemDateEdit 列 | `colCreateTime` | 创建时间 (yyyy-MM-dd) |

**布局决策**:字段 9 个 + 含枚举/日期/数值混合 → **GridControl + GridView**(按 §1.1 模板)。

---

## 9. Step 3 — frm vs ucl

**业务独立、需独立菜单入口** → 新建 `Frm_NewFeatureList`(不是 ucl)。

---

## 10. Step 4 — 三层生成产物 (无 Collection 层变体)

按 **数据流向**生成 6 类文件 (注意 Ser 层直连 DAL):

```
LegacyProject.Modules.NewFeature.UI/
├── Frm_NewFeatureList.cs              # View 主类
├── Frm_NewFeatureList.Designer.cs     # Designer
├── Frm_NewFeatureList.resx            # resx
└── INewFeatureListView.cs             # View 接口 (单向 set + Refresh*)

LegacyProject.Modules.NewFeature.BLL/
├── NewFeaturePresenter.cs             # Presenter
└── NewFeatureSer.cs                   # Ser(=BLL,直连 DAL,无 Collection)
    # ← 关键差异：Ser 直接持有 SqlOperate 和 ListOperate

(已有，不动)
Entity/NewFeatureInfo.cs               # 实体已存在
```

### 10.1 关键代码片段 (Ser 重点 — 无 Collection 变体)

```csharp
// NewFeatureSer.cs —— 无 Collection 层变体
public class NewFeatureSer
{
    // ← 关键差异：Ser 直接持有数据访问，不通过 Collection
    private readonly SqlOperate _so = new SqlOperate();
    private readonly ListOperate _tolist = new ListOperate();
    
    // 内存缓存
    private List<NewFeatureInfo> _lstNewFeatureInfo = new List<NewFeatureInfo>();

    private const string CONN = "ASSConn"; // ← 与 Step 1 提取一致

    public bool Load(string keyword, decimal? minPrice)
    {
        try
        {
            var sb = new StringBuilder();
            sb.Append("SELECT ID, Code, Name, Spec, UnitPrice, Qty, Amount, Status, CreateTime ");
            sb.Append("FROM T_NewFeature WHERE 1=1 ");

            var pars = new List<SqlParameter>();
            if (!string.IsNullOrEmpty(keyword))
            {
                sb.Append("AND (Code LIKE @kw OR Name LIKE @kw) ");
                pars.Add(new SqlParameter("@kw", "%" + keyword + "%"));
            }
            if (minPrice.HasValue)
            {
                sb.Append("AND UnitPrice >= @minPrice ");
                pars.Add(new SqlParameter("@minPrice", minPrice.Value));
            }
            sb.Append("ORDER BY CreateTime DESC");

            var dt = _so.ReadDataToDataTable(sb.ToString(), CONN, pars.ToArray());
            _lstNewFeatureInfo = _tolist.FillModel<NewFeatureInfo>(dt);
            return true;
        }
        catch (Exception ex)
        {
            // Ser 不弹窗，返回 false 让 View 层弹
            return false;
        }
    }

    public bool Add(NewFeatureInfo e)
    {
        try
        {
            string sql = "INSERT INTO T_NewFeature (ID, Code, Name, Spec, UnitPrice, Qty, Amount, Status, CreateTime) " +
                         "VALUES (@ID, @Code, @Name, @Spec, @UnitPrice, @Qty, @Amount, @Status, @CreateTime)";
            var pars = new[] {
                new SqlParameter("@ID", e.ID),
                new SqlParameter("@Code", e.Code),
                new SqlParameter("@Name", e.Name),
                // ... 其他
            };
            
            if (_so.SqlExcuteNoQuery(sql, CONN, pars) > 0)
            {
                // 先改 DB 再同步内存
                _lstNewFeatureInfo.Add(e);
                return true;
            }
            return false;
        }
        catch
        {
            return false;
        }
    }

    public bool Update(NewFeatureInfo e) { /* 同结构：先改 DB 再同步内存 */ }
    public bool Delete(Guid id) { /* 同结构：先改 DB 再同步内存 */ }

    public List<NewFeatureInfo> List { get { return _lstNewFeatureInfo; } }
}
```

### 10.2 关键代码片段 (Presenter)

```csharp
// NewFeaturePresenter.cs —— 协调器 (与有 Collection 层一致)
public class NewFeaturePresenter
{
    private readonly INewFeatureListView _view;
    private readonly NewFeatureSer _ser = new NewFeatureSer(); // ← 直连 Ser

    public NewFeaturePresenter(INewFeatureListView view)
    {
        _view = view;
    }

    public void SelectNewFeatureList(string keyword, decimal? minPrice)
    {
        if (_ser.Load(keyword, minPrice))
        {
            _view.DataList = _ser.List;  // 单向 set
        }
    }
    // Add/Update/Delete 同模式
}
```

### 10.3 View 接口

```csharp
// INewFeatureListView.cs
public interface INewFeatureListView
{
    List<NewFeatureInfo> DataList { set; }   // 单向 set
    void RefreshDataSource();
    void ControlByStatus();
}
```

---

## 11. Step 5a — review-checklist 自审结果

> 完整 19 项对照过，这里只列关键几条 (特别是 Collection 层相关)。

- ✅ **A2.5** GridStyle 初始化代号 = `"ASS"`(与参照窗体一致)
- ✅ **A2.6** 消息框 = `XtraMessageBox.Show`(与 Frm_StockList 一致)
- ✅ **A2.7** 异常处理:Presenter 不 try-catch(对照 Frm_StockList)
- ✅ **B1.4** Ser 直连数据访问 (无 Collection 层，与 Step 0b 决策一致)
- ✅ **B3.2** Ser 内存缓存 `_lstNewFeatureInfo` 在增删改后同步
- ✅ **B3.3** Ser 持有 `SqlOperate`/`ListOperate` 实例 (无 Collection 层变体)
- ✅ **C.3** Designer 从 `designer-patterns.md` §1.1 复制，固定字段替换
- ✅ **C.4** `.csproj` 已注册 3 件 (.cs / .Designer.cs / .resx)

🔴 **A2.4** DBHelp = `varlist.ASSDBHelp`(确认无误，⚠️ 第一次生成曾错写成 `varlist.SqlOperate`，因为默认假设是 Upgrader 风格)

---

## 12. Step 5b — MSBuild 命令与结果

```powershell
$ cd C:\Src\LegacyProject
$ & "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild.exe" `
    .\LegacyProject.sln `
    /p:Configuration=Debug `
    /p:Platform="Any CPU" `
    /v:minimal `
    /nologo
```

**输出**:
```
Build succeeded.
    0 Warning(s)
    0 Error(s)

Time Elapsed 00:00:16.45
```

✅ 通过。

---

## 13. 失败点 + 沉淀

| 时间点 | 失败 | 修复 | 沉淀 |
|--------|------|------|------|
| Step 0b | 检测到 Collection 层 12 个但近 6 个月=0 | 升级到 deep 档，跑 git log 确认趋势 | **新增案例**:架构退化检测 |
| Step 0b ask_user | 用户不确定选 A 还是 B | 给出推荐 A(简化架构) 并说明理由 | **ask_user 模板** 新增"架构退化"场景 |
| Step 1 提取 | Ser 层代码模板错用有 Collection 层变体 | 从 `Frm_StockList.cs` 确认 Ser 直连数据访问 | **failure-modes 新增**:"Ser 层架构变体错配" |
| Step 4 生成 | Ser 层漏写 `SqlOperate`/`ListOperate` 实例化 | review-checklist B3.3 强制校验 | **review-checklist 新增**:"Ser 直连数据访问时必持有 SqlOperate/ListOperate" |

---

## 14. 本案例的可复用价值

1. **架构退化检测**——Step 0b 不仅检测异质性，还检测架构演化趋势
2. **git log 验证**——用 `--since="6 months ago"` 确认最近实践
3. **ask_user 架构选项**——A(跟新)/B(跟老)/C(自定义) 三选一模板
4. **Ser 直连变体**——无 Collection 层时 Ser 的代码模板
5. **review-checklist 扩展**——新增"架构变体一致性"校验项

---

## 15. 与 failure-modes 的对应关系

| 失败模式 | 本案例处置 |
|----------|-----------|
| **案例 2** (Entity 不完整) | Step 2 前确认 Entity 字段完整性 |
| **案例 5** (泛型 vs 非泛型) | Step 0b 检测架构分层异质性 |
| **新增**:架构退化 | Step 0b 检测 Collection 层使用趋势 |

---

## 16. 如何扩展到其他架构退化场景

本案例的检测逻辑可扩展到：

| 架构维度 | 检测命令 | 退化信号 |
|----------|---------|---------|
| Collection 层 | `git log --since="6 months ago" -- "*Collection*.cs"` | 近 6 个月=0 个新增 |
| 独立 DAL 层 | `dalRatio = dalCount / serCount` | dalRatio < 0.1 |
| 泛型基类 | `rg -g "*.cs" "class.*frm_Base<"` | 近 6 个月使用率下降 |
| ORM 迁移 | `rg -g "*.cs" "DbHelp\.Query<"` | 新代码不再使用 ORM |

**通用检测模板**:
```powershell
# 1. 统计老代码 (全量)
$oldCount = @(rg -g "*.cs" "PATTERN" $projectRoot).Count

# 2. 统计新代码 (近 6 个月)
$newCount = @(git log --since="6 months ago" --pretty=format: --name-only --diff-filter=A -- "*.cs" | rg "PATTERN").Count

# 3. 判定退化
if ($oldCount -gt 10 -and $newCount -eq 0) {
    Write-Host "🔴 检测到架构退化：PATTERN 已废弃"
    # 触发 ask_user
}
```

(End of file - total 412 lines)
