# Example 10：UserControl 抽取（从现有窗体提取可复用控件）

> 场景：多个窗体都需要同一个「搜索区 + 结果列表」组合，把它抽取成 `ucl`。
> Step 3 的 ucl 决策场景：业务组件被多个窗体嵌入，或需要与主窗体主从联动。

---

## 用户原话

> "PartsManagement 和 WarehouseManagement 都有相同的搜索和列表，做个公共控件"

---

## 决策：是否该抽 ucl

| 判断 | 结果 |
|------|------|
| 3 个以上窗体用相同的「搜索 + 列表」布局 | ✅ 抽 ucl |
| 只有 2 个窗体用，且布局几乎一样 | ✅ 可以抽，但评估维护成本 |
| 布局差异大（列不同、按钮不同） | ❌ 先抽公共部分（搜索区），列表部分各自保留 |
| 仅 1 个窗体用 | ❌ 不抽，等第二个需求出现再考虑 |

---

## ucl 三种变体

| 变体 | 适用场景 | 加载时机 |
|------|---------|---------|
| **A：纯 UI 壳** | 只封装布局和控件，数据由宿主窗体提供 | 最常见，宿主调 Ser → 赋值给 ucl |
| **B：带Presenter** | ucl 自带轻量 Presenter 管理自己的数据加载 | ucl 内部数据逻辑独立于宿主 |
| **C：主从联动** | ucl 作为从表，主表选中行触发 ucl 刷新 | 需事件通信 |

> 变体选择见 `references/usercontrol-patterns.md`。本示例走最常见的 **变体 A（纯 UI 壳）**。

---

## 操作步骤

### 1. 分析共用部分

从 `Frm_PartsList` 提取共用组件：

```
共用部分：
  - lcSearch（LayoutControl 搜索区）
    - txtKeyword（搜索关键词）
    - datStart / datEnd（日期范围）
    - btnSearch / btnReset
  - gcMain（GridControl 列表区）
    - gvMain（GridView）

差异化部分（各自保留）：
  - 列定义（Parts vs Warehouse 列不同）
  - 业务按钮（导出/审核等）
  - Ser 层逻辑
```

### 2. 创建 ucl 文件

**文件清单**（3 个文件）：

| 文件 | 说明 |
|------|------|
| `uclSearchList.cs` | UserControl 逻辑 |
| `uclSearchList.Designer.cs` | 布局 + 控件声明 |
| `uclSearchList.resx` | 可见文字 |

### 3. ucl 设计（变体 A：纯 UI 壳）

```csharp
// uclSearchList.cs
public partial class uclSearchList : UserControl
{
    public uclSearchList()
    {
        InitializeComponent();
    }
    
    // ── 搜索区事件（宿主订阅） ──
    public event EventHandler SearchClicked;
    public event EventHandler ResetClicked;
    
    // ── 数据绑定（宿主提供数据源） ──
    public object DataSource
    {
        get { return gcMain.DataSource; }
        set { gcMain.DataSource = value; }
    }
    
    // ── GridView 访问（宿主需要操作列时） ──
    public DevExpress.XtraGrid.Views.Grid.GridView View => gvMain;
    public DevExpress.XtraGrid.GridControl Grid => gcMain;
    
    // ── 搜索参数读取（宿主读取后自行查询） ──
    public string Keyword => txtKeyword.Text.Trim();
    public DateTime? StartDate => datStart.EditValue as DateTime?;
    public DateTime? EndDate => datEnd.EditValue as DateTime?;
    
    // ── 清空搜索 ──
    public void ClearSearch()
    {
        txtKeyword.Text = "";
        datStart.EditValue = null;
        datEnd.EditValue = null;
    }
}
```

### 4. 宿主窗体集成

```csharp
// Frm_PartsList.cs — 引用 ucl
public partial class Frm_PartsList : frmBase, IPartsManagementView
{
    public Frm_PartsList()
    {
        InitializeComponent();
        // 把宿主 Panel 替换为 ucl
        uclSearchList1 = new UCL.SearchList.uclSearchList();
        this.pnlContainer.Controls.Add(uclSearchList1);
        uclSearchList1.Dock = DockStyle.Fill;
        
        // 订阅搜索事件
        uclSearchList1.SearchClicked += (s, e) => LoadData();
        uclSearchList1.ResetClicked += (s, e) => { ClearSearch(); LoadData(); };
    }
    
    private void LoadData()
    {
        // 从 ucl 读取搜索参数
        string keyword = uclSearchList1.Keyword;
        DateTime? start = uclSearchList1.StartDate;
        // 调 Ser 查询...
        var list = _ser.SelectByCondition(keyword, start, end);
        uclSearchList1.DataSource = list;
    }
}
```

### 5. Designer 注意事项

| 规则 | 原因 |
|------|------|
| ucl 自身不设 `GridStyle` | GridStyle 是窗体级概念，由宿主设置 |
| ucl 不直接调 Ser | 变体 A 是纯 UI 壳，数据由宿主注入 |
| ucl 的 `gcMain` 不设 `DataSource` | 由宿主通过 `DataSource` 属性设置 |
| ucl 的 `Name` 属性用宿主实例名 | `uclSearchList1`，设计器自动编号 |

---

## 三种变体对比

| | 变体 A（纯 UI） | 变体 B（带 Presenter） | 变体 C（主从联动） |
|--|---------------|---------------------|-----------------|
| **数据逻辑在哪** | 宿主窗体 | ucl 内部 Presenter | 宿主触发 ucl 刷新 |
| **适用场景** | 布局复用 | ucl 数据逻辑独立 | 主从表 |
| **耦合度** | 低 | 中 | 中 |
| **代码量** | 最少 | 中等 | 中等 |

> 详细代码见 `references/usercontrol-patterns.md`。

---

## 什么时候不该抽 ucl

| 场景 | 原因 |
|------|------|
| 两个窗体列定义完全不同 | 共用的只是"搜索区"，列表部分各自保留 |
| 业务逻辑差异大 | ucl 会变成意大利面条式条件分支 |
| 只有一个窗体用 | YAGNI——等第二个需求出现再抽 |
| 宿主窗体已用 Panel 嵌入其他复杂控件 | 替换成本高，风险大 |
