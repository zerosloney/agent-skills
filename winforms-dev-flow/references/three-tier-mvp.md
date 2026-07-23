# 三层架构 + MVP 模式规范

本文档说明项目中使用的架构模式和 MVP 数据绑定规范。具体基类、命名空间、数据访问方式以 **Step 1 扫描到的真实窗体**为准；以下为常见结构的历史参考。

> **Collection 层已废弃**：Ser(BLL) 直连 DAL，不再经过 Collection 代理层。

## 统一三层架构（Ser 直连 DAL）

> 架构总览图见 SKILL.md「三层架构」章节。

> 数据访问方式（原始 SQL 还是 ORM）、是否使用泛型基类、基类名（`frmBase` vs `frm_Base`）等差异，均以 Step 1 扫描到的真实窗体为准。

### 变体：无独立 DAL 层（DAL/Ser < 0.1）

> **触发条件**：Step 0b glance 查询 5 输出 `dalRatio < 0.1`（实测 Deve-Upgrader 主仓 DAL=1/Ser=1490 命中此变体）。
> **判断依据**：项目里 `*DAL.cs` 文件远少于 `*Ser.cs`，说明数据访问（`SqlOperate` / `DbHelp.Query`）直接写在 Ser 里，**没有独立 DAL 层**。

此变体下：
- **不生成独立 `*DAL.cs` 文件**——避免给项目强加它没有的架构层
- Ser 直接持有 `SqlOperate _so` / `ListOperate _tolist` 字段，写操作流程不变（先改 DB，再同步 `_lst{Entity}`）
- SQL 字符串、连接名、`SqlOperate` 调用全部内联在 Ser 方法里
- 五层文件输出收缩为 4 类：`View / Presenter / Ser / Entity`（Designer 算 View 的配套）

```csharp
// Ser 直连数据访问示例（无 DAL 文件）
public class {业务名}Ser
{
    private List<{业务名}Info> _lst{业务名} = new List<{业务名}Info>();
    private SqlOperate _so = new SqlOperate();
    private ListOperate _tolist = new ListOperate();
    private const string CONN = "ASSConn";   // ← 以 Step 0b 扫描为准

    public List<{业务名}Info> SelectAll()
    {
        string sql = "SELECT * FROM {表名}";
        return _tolist.FillModel<{业务名}Info>(
                   _so.ReadDataToDataTable(sql, varlist.ASSConn));
    }

    public bool Insert({业务名}Info info)
    {
        string sql = $"INSERT INTO {表名} (...) VALUES (...)";
        if (_so.SqlExcuteNoQuery(sql, varlist.ASSConn) > 0)
        {
            _lst{业务名}.Add(info);   // 先改 DB 成功,再同步内存
            return true;
        }
        return false;
    }
}
```

> **注意**：Step 1 提取参照窗体时，若参照窗体本身就是「Ser 内联数据访问」写法（无对应 `*DAL.cs`），即使 `dalRatio ≥ 0.1` 也应走此变体——跟随参照窗体的真实结构优先。

## 角色定义

| 角色 | 直连（非泛型，常见于 Upgrader/EQUP） | 泛型（常见于 CRS） |
|------|--------------|----------|
| **View** | `frmBase, I{业务名}View` | `frm_Base, I{业务名}View<T>` |
| **Presenter** | `{业务名}Presenter` 非泛型 | `{业务名}PresenterBase<T>` + `{业务名}Presenter<T>` |
| **IView** | `List<T> DataList { set; }` | 泛型 `List<T> ListData { set; }` + 继承链 |
| **Ser (BLL)** | `{业务名}Ser` 内存缓存，直连 DAL | `{业务名}SerBase<T>` + `{业务名}Ser` ORM，直连 DAL |
| **DAL** | `DAL{业务名}` — `SqlOperate+ListOperate` | `DAL{业务名}Base<T>` — ORM |

## MVP 模式 — Deve-Upgrader（非泛型）

**核心规范摘要**：

- **View 接口**：属性只有 `{ set; }`，不提供 `get`；每个数据集对应一个 `set` 属性；`Refresh*()` 方法通知视图刷新
- **Presenter**：构造注入 View 接口，直接实例化 Ser（无 DI 容器）；每个方法调用 Ser → 检查 `bool` → 通知视图；不处理异常
- **Ser (BLL)**：持有内存数据缓存 `_lst{Entity}`，与数据库保持同步；直连 DAL，每个操作两步——先改 DB，成功后再同步内存；包含业务校验（如重复性检查）；异常返回 `false`，不向上抛出
- **DAL**：持有 `SqlOperate _so` + `ListOperate _tolist`；SELECT 用 `_tolist.FillModel<T>(_so.ReadDataToDataTable(sql, connName))`；INSERT/UPDATE/DELETE 用 `_so.SqlExcuteNoQuery(sql, connName) > 0`；批量删除用 `_so.ExecuteSqlTran(sqlList, connName)`；SQL 字符串拼接/插值，连接名通过 `varlist.*Conn` 引用

## MVP 模式 — Deve-CRS（泛型模式）

**核心规范摘要**：

- **View 接口**三层继承链：`I{业务}ViewBase`（基础方法）→ `I{业务}View<T>`（泛型数据属性）→ `I{业务}View`（关闭泛型）
- **Presenter**：所有方法 `virtual`，子类可覆写；两个构造重载（带 View / 不带 View）；方法模式 `_ser.DoSomething() → _view?.RefreshDataSource()`；泛型约束 `where T : class, IEntityInterface`
- **Ser (BLL)**：通过 `Set{Entity}Dal(dal)` 注入具体 DAL（子类构造函数调用）；使用 ORM `_dal.Query<T>()` / `Insert` / `Update` / `Delete`，不写原始 SQL
- **DAL**：泛型基类 `DAL{业务}Base<T>`，提供 ORM 方法

## 数据绑定与错误处理

> 控件配置详见 `references/devexpress-controls.md`。

**核心规范摘要**：

- 窗体 `set` 属性中直接 `gridControl.DataSource = value` + `RefreshDataSource()`
- 删除/保存等操作在 View 层 `try-catch`，配合等待窗体（Upgrader: `varlist_Dialog`，CRS: `UICommonBase`）
- Presenter 不处理异常，异常冒泡到 View 层统一 `XtraMessageBox.Show`

## 命名规范

> 文件命名规则见 SKILL.md「文件输出」章节。

### 控件命名

| 控件类型 | 命名格式 | 示例 |
|----------|----------|------|
| GridControl | `gc{名称}` | `gcPBType`, `gcProjectInfo` |
| GridView | `gv{名称}` | `gvPBType`, `gvProjectInfo` |
| TreeList | `tl{名称}` | `tlMain`, `tl_WorkGroup` |
| LayoutControl | `lc{名称}` | `lcMain`, `lcSearch` |
| LayoutControlGroup | `lcg{名称}` | `lcgSearch`, `lcgGrid` |
| DateEdit | `dat{名称}` 或 `de_{名称}` | `datStart`, `de_Start` |
| TextEdit | `txt{名称}` | `txtKeyword`, `txtSearch` |
| SpinEdit | `spn{名称}` | `spnSortSN` |
| CheckEdit | `chk{名称}` | `chkEnabled` |
| CheckedComboBoxEdit | `ckcbo{名称}` | `ckcboStatus` |
| SimpleButton | `btn{名称}` | `btnSearch`, `btnSave` |
| LabelControl | `lbc{名称}` | `lbcSubmit`, `lbcKeyword` |
| ContextMenuStrip | `cms` 或 `cms{名称}` | `cms`, `cms_WorkGroup` |
| GridLookUpEdit | `glku{名称}` 或 `gle_{名称}` | `glkuOffice` |
| RepositoryItemLookUpEdit | `rlkue{名称}` | `rlkueStatus` |

> 本表为命名规范权威来源。`designer-template-list.md` 与 `devexpress-controls.md` 的命名约定均引用本表,有分歧以本表为准。

### 私有字段命名

```csharp
private List<EntityClass> _lstEntity = new List<EntityClass>();
private EntityClass _currentEntity;
private GridHitInfo _ghi;  // 鼠标点击信息
```

## 状态管理

### 枚举定义模式

枚举通常定义在 Entity 或独立 Enums 文件中，窗体通过 `using` 引用。值从 0 开始，与数据库 `int` 列对应。

```csharp
public enum OrderStatus
{
    NotSubmitted = 0,   // 未提交
    Submitted = 1,      // 已提交
    Approved = 2,       // 已审批
    NotApproved = 3,    // 已退回
    Closed = 4          // 已关闭
}
```

### 权限按钮控制

```csharp
private void ControlByStatus()
{
    var order = gvMain.GetFocusedRow() as OrderInfo;
    if (order == null) return;

    btnSubmit.Enabled   = order.Status == 0 || order.Status == 3;
    btnApprove.Enabled  = order.Status == 1;
    btnReject.Enabled   = order.Status == 1;
    btnClose.Enabled    = order.Status == 2;
}
```

**典型初始化流程**：`Form_Load` → `_presenter.Select*()` → `ControlByStatus()` → 用户操作 → `_presenter.Add/Delete/Update()` → 刷新 → `ControlByStatus()`

## 跨模式共通规则

1. **Presenter 不处理异常**——异常冒泡到 View 层 `try-catch` 统一展示
2. **Ser = BLL**——业务校验 + 内存缓存管理，不依赖 DI 容器
3. **先改 DB，再同步内存**——所有写操作先调用 DAL，成功后才更新 `_lst{Entity}`
4. **View 接口单向数据流**——属性只有 `set`，Presenter 通过 Ser 获取数据后赋值给 View
5. **基类 / 命名空间以真实窗体为准**——Step 1 扫描结果优先于本文档的默认值
6. **删除前确认**——`XtraMessageBox.Show("是否删除？", "提示", OKCancel) == Cancel` 时 return
7. **操作等待窗体**——长时间操作包裹在 `SetTitleAndCaption / CloseWaitDialog`（Upgrader）或 `StartWaitForm / EndWaitForm`（CRS）中

## Entity 属性模式模板

```csharp
[Serializable]
[DBTableAttribute("TableName")]
public class EntityName : DBUpdateObjectBase
{
    [DBColumnAttribute(IsPrimaryKey = true)]
    public Guid ID
    {
        get { return _ID; }
        set { AddRecordChange("ID", _ID, value); _ID = value; }
    }

    public string PropertyName
    {
        get { return _PropertyName; }
        set { AddRecordChange("PropertyName", _PropertyName, value); _PropertyName = value; }
    }
}
```

**关键**：`AddRecordChange("PropertyName", oldValue, newValue)` 在每个 setter 中调用，用于变更追踪。参照窗体的 Entity 若如此则遵循。
