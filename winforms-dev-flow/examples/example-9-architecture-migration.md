# Example 9：架构迁移（非泛型 → 泛型 / 无 DAL → 有 DAL）

> 场景：老项目从 Deve-Upgrader 风格迁移到 Deve-CRS 风格，或反过来。
> 这是比从零生成更高风险的操作——**迁移不是生成，是逐个文件改写**。
> 本示例覆盖两种最常见的迁移方向。

---

## 用户原话

> "这个模块要改成 CRS 风格，用泛型基类和 ORM"

---

## 迁移方向决策表

| 源 → 目标 | 难度 | 影响范围 | 建议 |
|-----------|------|---------|------|
| Upgrader（非泛型）→ CRS（泛型） | 🔴 高 | View + Presenter + Ser + DAL + Entity 全改 | 先跑 Step 0b 确认目标项目实际走哪种 CRS 变体 |
| Upgrader（无 DAL）→ Upgrader（有 DAL） | 🟡 中 | 新增 DAL 文件，Ser 改调用 | 参照窗体有 DAL 才走此方向 |
| CRS（泛型）→ Upgrader（非泛型） | 🔴 高 | 同上，反向操作 | 少见，通常是回退 |
| 无 Collection → 有 Collection | 🟡 中 | 新增 Collection 层 | 不推荐——Collection 已废弃 |

---

## 迁移流程（以 Upgrader → CRS 为例）

### Phase 1：确认目标模式（Step 0b）

```powershell
# 确认目标项目实际走哪种 CRS 变体
rg -n "frm_Base<|I\w+ViewBase" "C:\TargetProject" --type cs
```

输出判断：
- `frm_Base<T>` 命中 → CRS 主线风格（泛型 + ORM）
- 只命中 `frmBase` → 可能是 Eqp 变体（非泛型 + ListOperate，**不是** CRS 主线）

### Phase 2：Entity 迁移

**源（Upgrader）**：
```csharp
[Serializable]
[DBTableAttribute("PartsManagement")]
public class PartsInfo : DBUpdateObjectBase
{
    [DBColumnAttribute(IsPrimaryKey = true)]
    public Guid ID { get { return _ID; } set { AddRecordChange("ID", _ID, value); _ID = value; } }
    public string Name { get { return _Name; } set { AddRecordChange("Name", _Name, value); _Name = value; } }
}
```

**目标（CRS ORM）**：
```csharp
[Serializable]
[DBTableAttribute("PartsManagement")]
public class PartsInfo : DBUpdateObjectBase  // 基类不变
{
    [DBColumnAttribute(IsPrimaryKey = true)]
    public Guid ID { get { return _ID; } set { AddRecordChange("ID", _ID, value); _ID = value; } }
    
    // 字段定义不变——CRS 的 Entity 和 Upgrader 的 Entity 结构相同
    public string Name { get { return _Name; } set { AddRecordChange("Name", _Name, value); _Name = value; } }
}
```

> **Entity 通常不改**——CRS 和 Upgrader 的 Entity 结构一致，都是 `DBUpdateObjectBase` + `AddRecordChange` setter。只需确认 `DBTableAttribute` 和 `DBColumnAttribute` 存在。

### Phase 3：DAL 迁移（新增 CRS 风格 DAL）

**源（无 DAL，数据访问内联在 Ser）**：
```csharp
// PartsManagementSer.cs — 直接持有 SqlOperate
private SqlOperate _so = new SqlOperate();
private ListOperate _tolist = new ListOperate();
public List<PartsInfo> SelectAll()
{
    string sql = "SELECT * FROM PartsManagement";
    return _tolist.FillModel<PartsInfo>(_so.ReadDataToDataTable(sql, varlist.ASSConn));
}
```

**目标（新增 DAL + ORM）**：
```csharp
// PartsManagementDAL.cs — 新增
public class PartsManagementDal : DALBase<PartsInfo>
{
    public override List<PartsInfo> SelectAll()
    {
        return _dal.Query<PartsInfo>().ToList();
    }
    
    public override bool Insert(PartsInfo info)
    {
        return _dal.Insert(info) > 0;
    }
    
    public override bool Update(PartsInfo info)
    {
        return _dal.Update(info) > 0;
    }
    
    public override bool Delete(Guid id)
    {
        return _dal.Delete<PartsInfo>(id) > 0;
    }
}
```

```csharp
// PartsManagementSer.cs — 改调用 DAL
private PartsManagementDal _dal = new PartsManagementDal();
public List<PartsInfo> SelectAll() => _dal.SelectAll();
public bool Insert(PartsInfo info) => _dal.Insert(info);
```

### Phase 4：Presenter 迁移

**源（Upgrader 非泛型）**：
```csharp
public class PartsManagementPresenter
{
    private IPartsManagementView _view;
    private PartsManagementSer _ser = new PartsManagementSer();
    
    public PartsManagementPresenter(IPartsManagementView view)
    {
        _view = view;
    }
    
    public void LoadData()
    {
        _view.DataList = _ser.SelectAll();
    }
}
```

**目标（CRS 泛型）**：
```csharp
// 如果目标项目用三层继承链
public class PartsManagementPresenterBase : PresenterBase<PartsInfo>
{
    protected PartsManagementDal _dal = new PartsManagementDal();
}

public class PartsManagementPresenter : PartsManagementPresenterBase
{
    private IPartsManagementView _view;
    
    public PartsManagementPresenter(IPartsManagementView view) : base()
    {
        _view = view;
    }
    
    public override void LoadData()
    {
        _view.DataList = _dal.SelectAll();
    }
}
```

### Phase 5：View 接口迁移

**源（Upgrader）**：
```csharp
public interface IPartsManagementView
{
    List<PartsInfo> DataList { set; }
    void ShowMessage(string msg);
}
```

**目标（CRS 三层继承链）**：
```csharp
// IView 基类（如果项目有公共基类则复用，否则新建）
public interface IPartsManagementViewBase
{
    void ShowMessage(string msg);
    void ShowError(string msg);
}

// 泛型接口
public interface IPartsManagementView<T> : IPartsManagementViewBase
{
    List<T> DataList { set; }
}

// 闭泛型接口（窗体实际实现的）
public interface IPartsManagementView : IPartsManagementView<PartsInfo>
{
    // 不新增成员——继承链已覆盖
}
```

### Phase 6：窗体类声明迁移

**源（Upgrader）**：
```csharp
public partial class Frm_PartsList : frmBase, IPartsManagementView
```

**目标（CRS）**：
```csharp
public partial class frm_partsList : frm_Base<PartsInfo>, IPartsManagementView
```

> **注意**：CRS 窗体类名通常小写 + 带下划线（`frm_xxx`），与 Upgrader（`Frm_Xxx`）不同。

---

## 迁移验证清单

每迁移完一个文件，立即验证：

- [ ] 该文件独立编译通过（`MSBuild` 单文件编译）
- [ ] 调用链正确：View → Presenter → Ser → DAL（无越级）
- [ ] Entity setter 仍调 `AddRecordChange`
- [ ] 参照窗体风格一致（基类名、命名空间、GridStyle 代号）

## 迁移禁忌

| 禁止 | 原因 |
|------|------|
| 一次性改所有文件 | 出错时无法定位是哪个文件的改动导致的 |
| 混用两种风格（部分 Upgrader + 部分 CRS） | 案例 5 触发——编译错误 / 运行时类型转换失败 |
| 改 Entity 的 AddRecordChange 调用格式 | CRS 和 Upgrader 的 Entity 格式相同，改只会引入 bug |
| 删除原始 SQL 后才发现 ORM 查不到数据 | CRS ORM 的 `Query<T>()` 行为与原始 SQL 有差异（如 NULL 处理），先验证再删除 |
