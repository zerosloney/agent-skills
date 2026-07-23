# Example 8：增量编辑（现有窗体加列/功能）

> 场景：现有 `Frm_PartsList` 需要新增一列「创建时间」和一个「导出 Excel」按钮。
> 这比从零生成更常见，skill 的默认流程是「全量生成」，增量编辑需要不同的操作策略。

---

## 用户原话

> "PartsManagement 列表加个创建时间列，再加个导出按钮"

---

## 决策：增量编辑 vs 全量生成

| 判断 | 结果 | 行动 |
|------|------|------|
| 窗体已存在且可编译 | ✅ 增量编辑 | 只动 2 个文件：`.Designer.cs` + `.cs` |
| 窗体结构需大改（换基类/换 GridStyle） | ❌ 全量生成 | 按 Step 0 重新生成 |

本场景走增量编辑。

---

## 操作步骤

### 1. 扫描现有窗体结构

```powershell
# 确认关键模式（不修改文件）
rg -n "partial class|GridView|GridStyle|SqlOperate|ListOperate" Frm_PartsList.cs Frm_PartsList.Designer.cs
```

提取：
- 基类：`frmBase`
- GridStyle：`"ASS"`
- 数据访问：`SqlOperate + ListOperate`
- 现有列数：5 列

### 2. 修改 Designer.cs（只加不改）

**原则**：增量编辑只 `Add` 新控件，不改已有控件的属性。

```csharp
// Frm_PartsList.Designer.cs — 只追加，不修改已有代码

// ① 新建列（追加到 gvMain.Columns 集合）
DevExpress.XtraGrid.Columns.GridColumn colCreateTime;
this.colCreateTime = new DevExpress.XtraGrid.Columns.GridColumn();
this.colCreateTime.Caption = "创建时间";
this.colCreateTime.FieldName = "CreateTime";
this.colCreateTime.Visible = true;
this.colCreateTime.VisibleIndex = 5;  // 排在最后
this.colCreateTime.DisplayFormat.FormatString = "yyyy-MM-dd HH:mm";
this.colCreateTime.DisplayFormat.FormatType = DevExpress.Utils.FormatType.DateTime;
this.gvMain.Columns.AddRange(new DevExpress.XtraGrid.Columns.GridColumn[] {
    // ... 已有列 ...,
    this.colCreateTime  // ← 追加到末尾
});

// ② 新建按钮（追加到 lciBtnRow 容器）
DevExpress.XtraEditors.SimpleButton btnExport;
this.btnExport = new DevExpress.XtraEditors.SimpleButton();
this.btnExport.Name = "btnExport";
this.btnExport.Text = "导出 Excel";
this.btnExport.Click += new System.EventHandler(this.btnExport_Click);
this.lciBtnRow.AddControl(this.btnExport);  // ← 追加到按钮行
```

> **关键**：不要改已有列的 `VisibleIndex`——增量加列只设新列的 `VisibleIndex`，不动其他列。

### 3. 修改窗体逻辑 .cs（只加不改）

```csharp
// Frm_PartsList.cs — 只追加新方法，不改已有方法

private void btnExport_Click(object sender, EventArgs e)
{
    var list = gcMain.DataSource as List<PartsInfo>;
    if (list == null || list.Count == 0)
    {
        XtraMessageBox.Show("无数据可导出", "提示");
        return;
    }

    using (SaveFileDialog sfd = new SaveFileDialog())
    {
        sfd.Filter = "Excel 文件|*.xlsx";
        sfd.FileName = $"Parts_{DateTime.Now:yyyyMMdd}.xlsx";
        if (sfd.ShowDialog() == DialogResult.OK)
        {
            gcMain.ExportToXlsx(sfd.FileName);
            XtraMessageBox.Show("导出完成", "提示");
        }
    }
}
```

> **不修改**：`_Load` 事件、`SelectData` 方法、`btnSearch_Click` 等已有方法。
> 创建时间列如果 Entity 已有 `CreateTime` 字段，Ser 层 SELECT 补上即可；若 Entity 没有，先确认字段存在再改。

### 4. Entity 确认（如果需要）

若 `PartsInfo` 没有 `CreateTime` 属性：

```csharp
// Entity.PartsInfo — 追加一个属性（参照现有属性的 setter 风格）
public DateTime CreateTime
{
    get { return _CreateTime; }
    set { AddRecordChange("CreateTime", _CreateTime, value); _CreateTime = value; }
}
private DateTime _CreateTime;
```

### 5. Ser 层 SQL 补列（如果需要）

```csharp
// PartsManagementSer.cs — 修改 SELECT，追加 CreateTime
string sql = "SELECT ID, Name, Spec, Status, SortSN, CreateTime FROM PartsManagement WHERE ...";
```

### 6. 冒烟测试 + 构建

```powershell
# 冒烟测试
python scripts/smoke_test.py --dir "C:\Project\UI\PartsManagement" --pattern "*.cs"

# 构建
& "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe" `
    "C:\Project\Project.sln" /p:Configuration=Debug /p:Platform="Any CPU" /m
```

---

## 增量编辑守则

| 规则 | 原因 |
|------|------|
| **只 Add，不改已有代码** | 避免破坏已有功能的副作用 |
| **新列 VisibleIndex 避开已有列** | 不动已有列的排序 |
| **新按钮 Append 到现有容器** | 不替换 lciBtnRow，只 AddControl |
| **Entity 追加属性参照现有风格** | setter 的 AddRecordChange 调用格式必须一致 |
| **Ser SQL 追加字段，不改 WHERE/ORDER BY** | 除非用户明确要求改查询逻辑 |
| **改完跑 smoke_test + MSBuild** | 增量改动同样需要验证 |

## 什么情况下不增量，要全量生成

| 触发条件 | 原因 |
|---------|------|
| 换基类（`frmBase` → `frm_Base<T>`） | 架构层变更，增量维护成本 > 全量 |
| 换 GridStyle 代号 | 影响所有列/皮肤初始化 |
| 换数据访问方式（SQL → ORM） | DAL/Ser 全改，不如重新生成 |
| 窗体布局重做（Grid → LayoutControl） | 控件体系变更 |
