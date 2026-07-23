# Example 1 — PartsManagement 单表 CRUD(CSS.WHXL.Extend)

> 对应 failure-modes 案例 1(DBHelp 命名差异) + 案例 8(类名前缀约定)。
> **实战项目**:某制造业 ERP 子模块 `CSS.WHXL.Extend`。

---

## 1. 场景描述

**用户原话**:
> "在 `CSS.WHXL.Extend.Modules.Parts` 模块下加一个 `PartsManagement` 窗体,主表 `JDDR_MMA_PartsManagement`,字段就是表里那十几列,要支持查询/新增/修改/删除。"

**上下文**:
- 项目: `.NET Framework 4.7.2` + WinForms + DevExpress 21.2
- 架构: View → Presenter → Ser → DAL → Entity(Ser 直连 DAL,无 Collection 层)
- 已有基类: `frmBase`、`PartsPresenter`、`PartsSer`、`PartsDAL`、`Entity.PartInfo`(已存在但可能不全)

---

## 2. Step 0 — 目标目录定位

```bash
PROJECT_ROOT = C:\Src\CSS.WHXL.Extend
TARGET_DIR   = C:\Src\CSS.WHXL.Extend\Modules\Parts\UI
MODULE_NAME  = Parts
```

---

## 3. Step 0a — 4 项必填门

| # | 确认项 | 取值 | 来源 |
|---|--------|------|------|
| 1 | 业务名 / 窗体名 | `PartsManagement` / `Frm_PartsManagementList` | 用户原话 |
| 2 | Entity 或字段来源 | `Entity.PartInfo`(已存在,需 Step 1 检查字段完整性) | 项目已有 |
| 3 | 项目根 + 目标目录 | 见 §2 | 用户已说 |
| 4 | 构建入口 | `CSS.WHXL.Extend.sln`,Configuration=Debug,Platform=AnyCPU | 项目默认 |

✅ 4 项齐 → 进 Step 0b。

---

## 4. Step 0b — 项目指纹卡(自动跑)

> **命令**:跑 `references/project-fingerprint.md §0.2` 的 glance 档(6 查询,全部过滤注释 + 文件级去重)。命令权威以 §0.2 为准,此处不重复——避免与 §0.2 双份维护漂移。

### 指纹卡输出

| 维度 | 主导 | 占比 | 异类 |
|------|------|------|------|
| 窗体基类 | `frmBase` | **98%** | `frm_Base<T>`(2%) |
| 数据访问 | `SqlOperate+ListOperate` | **97%** | `DbHelp.Query<T>`(3%) |
| GridStyle | `"CSS"` | **97%** | `"ASS"`/`"CRS"`(3%) |
| DBHelp | `varlist.ASSDBHelp`(自定义) | 99% | — |
| Collection 层 | 已废弃 | 100% | — |
| 类名前缀 | `DAL_{业务}` / `Frm_{业务}List` / `DlgEdit_{业务}` | — | — |

**主家族**:**D. CSS.WHXL.Extend**(基类 frmBase + SqlOperate + GridStyle "CSS" + ASSDBHelp)

**异质性等级**:🟢 **纯一** — 主导达 98%,无须 ask_user,直接进 Step 1。

**命名规则扫描**:
```bash
$ ls {PROJECT_ROOT}/Modules/Parts/DAL/*.cs
DAL_Parts.cs
$ ls {PROJECT_ROOT}/Modules/Parts/UI/*.cs
Frm_PartsLookup.cs  # 已有
$ ls {PROJECT_ROOT}/Modules/Parts/BLL/*.cs
PartsSer.cs
```

→ 前缀约定:**DAL_** + `Frm_` + Ser/Presenter/DAL 无前缀(Base 链继承)。

---

## 5. Step 1 — 模式提取表

对照窗体:`Frm_PartsLookup.cs`(业务最相近的 Query 窗体)。

| 提取项 | 提取结果 | 备注 |
|--------|---------|------|
| **窗体基类** | `frmBase`(不带下划线) | ⚠️ `frm_Base<T>` 不是它,别混淆 |
| **窗体命名** | `Frm_{业务名}List` | 不是 `Frm{业务}List`,有下划线 |
| **命名空间** | `CSS.WHXL.Extend.Modules.Parts.UI` | 模块级 namespace |
| **`using` 引用** | `CSS.WHXL.Extend.Modules.Parts.BLL`、`.DAL`、`.Entity`、`CSS.WHXL.Extend.Common` | 跨模块 using |
| **数据访问方式** | `SqlOperate _so = new SqlOperate()` + `ListOperate _tolist = new ListOperate()` | 不是 ORM |
| **是否泛型** | ❌ 非泛型(Ser 直接继承基类,无 `<T>`) | 区别于 EQUP 的 `PartsSerBase<T>` |
| **GridStyle 代号** | `"CSS"` | ⚠️ 不是 `"ASS"` ——案例 1 的核心差异 |
| **DBHelp 实例 / 连接名** | `varlist.ASSDBHelp` / `varlist.ASSConn` | ⚠️ 案例 1 的核心差异:不是 `varlist.SqlOperate` |
| **类名前缀约定** | `DAL_Parts`(DAL 带前缀) / `Frm_Parts`(frm 带下划线)/ Ser/Presenter/Entity 无前缀 | ⚠️ 案例 8 的核心差异 |
| **WaitDialog** | `varlist_Dialog.SetWaitDialog(...)` / `varlist_Dialog.CloseWaitDialog()` | Upgrader 风格 |
| **消息框** | `XtraMessageBox.Show(msg, "提示", MessageBoxButtons.OK, MessageBoxIcon.Warning)` | 不是 `UICommonBase.ShowMessageBox` |
| **View 接口** | 单向 `set` 属性 + `Refresh*()` 方法 | 例:`List<PartInfo> DataList { set; }` |
| **绑定方式** | `gcMain.DataSource = value; gvMain.RefreshData();` | —— |
| **事件结构** | View 层 `try-catch` 弹 XtraMessageBox,Presenter 不处理异常 | 案例 6 的核心约定 |
| **Collection 中间层** | ❌ 无 | 流程:View → Presenter → Ser → DAL,跳过 Collection |

**用户确认**:"按 `Frm_PartsLookup.cs` 的模式生成 Yes/No?"

---

## 6. Step 2 — 字段→控件 映射表

`Entity.PartInfo` 字段(扫描):

| Entity 字段 | 类型 | 控件 | 列/项名 | 备注 |
|-------------|------|------|---------|------|
| ID | Guid | 隐藏列 | — | 主键 |
| Code | string | TextEdit 列 | `colCode` | 编码 |
| Name | string | TextEdit 列 | `colName` | 名称 |
| Category | enum | RepositoryItemComboBox | `colCategory` | 类别 |
| UnitPrice | decimal | SpinEdit 列(对齐右) | `colUnitPrice` | 单价 |
| StockQty | int | SpinEdit 列 | `colStockQty` | 库存 |
| Status | enum | RepositoryItemComboBox | `colStatus` | 状态 |
| CreateTime | DateTime | RepositoryItemDateEdit 列 | `colCreateTime` | 创建时间(yyyy-MM-dd) |
| Creator | string | TextEdit 列 | `colCreator` | 创建人 |
| Remark | string | MemoEdit 列 | `colRemark` | 备注 |

**布局决策**:字段 10 个 + 含枚举/日期/数值混合 → **GridControl + GridView**(按 §1.1 模板)。

---

## 7. Step 3 — frm vs ucl

**业务独立、需独立菜单入口** → 新建 `Frm_PartsManagementList`(不是 ucl)。

---

## 8. Step 4 — 三层生成产物

按 **数据流向**生成 6 类文件:

```
CSS.WHXL.Extend.Modules.Parts.UI/
├── Frm_PartsManagementList.cs              # View 主类
├── Frm_PartsManagementList.Designer.cs     # Designer
├── Frm_PartsManagementList.resx            # resx
└── IPartsManagementListView.cs             # View 接口(单向 set + Refresh*)

CSS.WHXL.Extend.Modules.Parts.BLL/
├── PartsManagementPresenter.cs            # Presenter
└── PartsManagementSer.cs                  # Ser(=BLL,直连 DAL)

CSS.WHXL.Extend.Modules.Parts.DAL/
└── DAL_PartsManagement.cs                 # DAL(用 varlist.ASSDBHelp+SqlOperate)

(已有,不动)
Entity/PartInfo.cs                         # 实体已存在
```

### 8.1 关键代码片段(DAL 重点)

```csharp
// DAL_PartsManagement.cs —— 数据访问
public class DAL_PartsManagement
{
    private readonly SqlOperate _so = new SqlOperate();
    private readonly ListOperate _tolist = new ListOperate();

    private const string CONN = "ASSConn"; // ← 案例 1 核心:不是 MainConn

    public List<PartInfo> Query(string keyword, int? category)
    {
        var sb = new StringBuilder();
        sb.Append("SELECT ID, Code, Name, Category, UnitPrice, StockQty, ");
        sb.Append("Status, CreateTime, Creator, Remark ");
        sb.Append("FROM JDDR_MMA_PartsManagement WHERE 1=1 ");

        var pars = new List<SqlParameter>();
        if (!string.IsNullOrEmpty(keyword))
        {
            sb.Append("AND (Code LIKE @kw OR Name LIKE @kw) ");
            pars.Add(new SqlParameter("@kw", "%" + keyword + "%"));
        }
        if (category.HasValue)
        {
            sb.Append("AND Category = @cat ");
            pars.Add(new SqlParameter("@cat", category.Value));
        }
        sb.Append("ORDER BY CreateTime DESC");

        var dt = _so.ReadDataToDataTable(sb.ToString(), CONN, pars.ToArray());
        return _tolist.FillModel<PartInfo>(dt);
    }

    public bool Insert(PartInfo e)
    {
        string sql = "INSERT INTO JDDR_MMA_PartsManagement (ID, Code, Name, ...) " +
                     "VALUES (@ID, @Code, @Name, ...)";
        var pars = new[] {
            new SqlParameter("@ID", e.ID),
            new SqlParameter("@Code", e.Code),
            // ... 其他
        };
        return _so.SqlExcuteNoQuery(sql, CONN, pars) > 0;
    }

    public bool Update(PartInfo e) { /* 同结构 */ }
    public bool Delete(Guid id) { /* 同结构 */ }
}
```

### 8.2 关键代码片段(Ser 重点)

```csharp
public class PartsManagementSer
{
    private readonly DAL_PartsManagement _dal = new DAL_PartsManagement();
    private List<PartInfo> _lstPartInfo = new List<PartInfo>();

    public bool Load(string keyword, int? category)
    {
        try
        {
            _lstPartInfo = _dal.Query(keyword, category);
            return true;
        }
        catch (Exception ex)
        {
            // Ser 不弹窗,返回 false 让 View 层弹
            return false;
        }
    }

    public List<PartInfo> List { get { return _lstPartInfo; } }
    // ...
}
```

### 8.3 关键代码片段(Presenter)

```csharp
public class PartsManagementPresenter
{
    private readonly IPartsManagementListView _view;
    private readonly PartsManagementSer _ser = new PartsManagementSer();

    public PartsManagementPresenter(IPartsManagementListView view)
    {
        _view = view;
    }

    public void SelectPartsManagementList(string keyword, int? category)
    {
        if (_ser.Load(keyword, category))
        {
            _view.DataList = _ser.List;  // 单向 set
        }
    }
    // Add/Update/Delete 同模式
}
```

### 8.4 View 接口

```csharp
public interface IPartsManagementListView
{
    List<PartInfo> DataList { set; }   // 单向 set
    void RefreshDataSource();
    void ControlByStatus();
}
```

---

## 9. Step 5a — review-checklist 自审结果

> 完整 19 项对照过,这里只列关键几条。

- ✅ **A2.5** GridStyle 初始化代号 = `"CSS"`(与参照窗体一致)
- ✅ **A2.6** 消息框 = `XtraMessageBox.Show`(与 Frm_PartsLookup 一致)
- ✅ **A2.7** 异常处理:Presenter 不 try-catch(对照 Frm_PartsLookup)
- ✅ **B1.4** Ser 直连 DAL,无 Collection 层
- ✅ **B3.2** Ser 内存缓存 `_lstPartInfo` 在增删改后同步
- ✅ **C.3** Designer 从 `designer-patterns.md` §1.1 复制,固定字段替换
- ✅ **C.4** `.csproj` 已注册 3 件(.cs / .Designer.cs / .resx)

🔴 **A2.4** DBHelp = `varlist.ASSDBHelp`(确认无误,⚠️ 第一次生成曾错写成 `varlist.SqlOperate`,因为默认假设是 Upgrader 风格)

---

## 10. Step 5b — MSBuild 命令与结果

```powershell
$ cd C:\Src\CSS.WHXL.Extend
$ & "C:\Program Files (x86)\Microsoft Visual Studio\2022\BuildTools\MSBuild.exe" `
    .\CSS.WHXL.Extend.sln `
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

Time Elapsed 00:00:14.23
```

✅ 通过。

---

## 11. 失败点 + 沉淀

| 时间点 | 失败 | 修复 | 沉淀 |
|--------|------|------|------|
| Step 1 提取 | DBHelp 名错写为 `varlist.SqlOperate` | 从 `Frm_PartsLookup.cs` 全文 `rg "varlist\.[A-Za-z]+(DBHelp\|Conn)"`,找到 `varlist.ASSDBHelp` | **failure-modes 案例 1** |
| Step 1 提取 | GridStyle 代号错写为 `"ASS"` | `rg "new GridStyle\("` 在同窗体内找到 `"CSS"` | **failure-modes 案例 4** |
| Step 4 生成 | 文件名前缀错为 `DALPartsManagement`(无下划线) | 参照现有 `DAL_Parts.cs` 修正前缀 | **failure-modes 案例 8** |
| Step 4 生成 | Designer 手写错误导致 TabOrder 错乱 | 加载 `designer-patterns.md` §1.1 重新复制模板 | **failure-modes 案例 7** |

---

## 12. 本案例的可复用价值

1. **CSS.WHXL.Extend 项目家族指纹**——Step 0b 自动命令模板可直接复用
2. **`"CSS"` GridStyle + `varlist.ASSDBHelp` + `DAL_` 前缀**——三件套作为家族 D 的标配套
3. **layout 选择**:字段 10 + 含枚举 + 含日期 → `GridControl + GridView` 而非 `LayoutControl`(LayoutControl 适合表单录入 ≤8 字段)
4. **Designer 模板起点**:§1.1(GridControl + GridView)直接套用
