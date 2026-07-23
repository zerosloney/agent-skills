# DevExpress 控件使用规范

> 版本：DevExpress **21.2.x**，.NET Framework **4.7.2**。完整程序集清单见 `references/dev-21.2-reference.md`。

## 核心程序集

| 程序集 | 命名空间 | 用途 |
|--------|---------|------|
| `DevExpress.XtraEditors.v21.2.dll` | `DevExpress.XtraEditors` | 所有编辑器控件（TextEdit, DateEdit, ButtonEdit 等） |
| `DevExpress.XtraGrid.v21.2.dll` | `DevExpress.XtraGrid` | GridControl, GridView, BandedGridView |
| `DevExpress.XtraLayout.v21.2.dll` | `DevExpress.XtraLayout` | LayoutControl, LayoutControlGroup |
| `DevExpress.XtraBars.v21.2.dll` | `DevExpress.XtraBars` | BarManager, BarButtonItem |
| `DevExpress.XtraBars.Ribbon.v21.2.dll` | `DevExpress.XtraBars.Ribbon` | RibbonControl |
| `DevExpress.XtraTreeList.v21.2.dll` | `DevExpress.XtraTreeList` | TreeList |
| `DevExpress.XtraDialogs.v21.2.dll` | `DevExpress.XtraDialogs` | XtraMessageBox |
| `DevExpress.Utils.v21.2.dll` | `DevExpress.Utils` | LookAndFeel, FormatType, HorzAlignment |

> .NET Framework 项目只引用 `Bin\Framework\` 下的 DLL。

## 控件精确配置

### GridControl + GridView（数据列表）

#### 基础配置

```csharp
// 双向绑定必须都写
gcMain.Dock = DockStyle.Fill;
gcMain.MainView = gvMain;
gvMain.GridControl = gcMain;  // ← 关键：不写只 gvMain 在 gcMain 找不到

gvMain.OptionsView.ShowGroupPanel = false;
gvMain.OptionsView.ShowAutoFilterRow = true;
gvMain.OptionsView.ShowIndicator = false;
gvMain.OptionsView.ColumnAutoWidth = false;
gvMain.OptionsBehavior.Editable = false;
gvMain.OptionsBehavior.ReadOnly = true;
gvMain.OptionsSelection.EnableAppearanceFocusedCell = false;
gvMain.OptionsSelection.EnableAppearanceFocusedRow = true;
```

#### 列配置模板

```csharp
var col = new DevExpress.XtraGrid.Columns.GridColumn
{
    Caption = "列标题",
    FieldName = "FieldName",
    Name = "colFieldName",
    Visible = true,
    VisibleIndex = 0,
    Width = 100
};
col.AppearanceHeader.TextOptions.HAlignment = DevExpress.Utils.HorzAlignment.Center;
col.AppearanceCell.TextOptions.HAlignment = DevExpress.Utils.HorzAlignment.Center;
gvMain.Columns.Add(col);
```

> 状态颜色（RowCellStyle / CustomDrawNodeCell）代码见 `references/advanced-features.md` § 1。

### TreeList（目录树）

```csharp
tlMain.OptionsView.ShowAutoFilterRow = true;
tlMain.OptionsView.ShowIndicator = false;
tlMain.OptionsBehavior.Editable = false;
tlMain.OptionsBehavior.EnableFiltering = true;
tlMain.OptionsFilter.FilterMode = FilterMode.Extended;

tlMain.DataSource = treeDataList;
tlMain.ParentFieldName = "ParentID";
tlMain.KeyFieldName = "ID";
tlMain.ExpandAll();
```

> 根节点的 ParentID 应为 `string.Empty`，确保能正确渲染顶层。

### 树形数据结构

```csharp
public class TreeNodeView
{
    public string ID { get; set; }
    public string ParentID { get; set; }  // 根节点 = string.Empty
    public string Name { get; set; }
    public int SortOrder { get; set; }
    public string Remark { get; set; }
}
```

### LayoutControl（布局容器）

#### 典型结构

```
LayoutControl (Dock = DockStyle.Fill)
├── Root (LayoutControlGroup)
│   ├── PanelControl (查询栏, Height = 35)
│   │   ├── LabelControl
│   │   ├── DateEdit / TextEdit / CheckedComboBoxEdit
│   │   └── SimpleButton (查询/清空)
│   ├── LayoutControlItem (TreeList)
│   ├── SplitterItem
│   └── LayoutControlItem (GridControl)
```

#### 关键属性

```csharp
this.layoutControl1.AutoSize = false;          // ← 21.2 必须设为 false
this.layoutControl1.Dock = DockStyle.Fill;
this.layoutControl1.OptionsItemText.TextToControlDistance = 4;
```

> LayoutControl 子控件必须用 `lcgMain.AddItem()` 添加，不能用 `lcMain.Controls.Add()`。

### DateEdit 标准配置

```csharp
dateEdit = new DateEdit
{
    Name = "dateStart",
    EditValue = null,
    Size = new Size(100, 20)
};
dateEdit.Properties.Buttons.AddRange(new EditorButton[] {
    new EditorButton(ButtonPredefines.Combo)
});
dateEdit.Properties.Mask.EditMask = "yyyy-MM-dd";
dateEdit.Properties.Mask.UseMaskAsDisplayFormat = true;
dateEdit.Properties.VistaDisplayMode = DevExpress.Utils.DefaultBoolean.True;  // 21.2 推荐
dateEdit.Properties.VistaEditTime = DevExpress.Utils.DefaultBoolean.False;
dateEdit.Properties.DisplayFormat.FormatString = "yyyy-MM-dd";
dateEdit.Properties.DisplayFormat.FormatType = DevExpress.Utils.FormatType.DateTime;
dateEdit.Properties.EditFormat.FormatString = "yyyy-MM-dd";
dateEdit.Properties.EditFormat.FormatType = DevExpress.Utils.FormatType.DateTime;
```

### CheckedComboBoxEdit（多选下拉）

```csharp
ckboStatus.Properties.Items.AddRange(new CheckedListBoxItem[] {
    new CheckedListBoxItem(0, "未提交"),
    new CheckedListBoxItem(1, "已提交"),
    new CheckedListBoxItem(2, "已审批"),
});

// 获取选中值
List<string> GetSelected(CheckedComboBoxEdit ckbo)
{
    var selected = new List<string>();
    foreach (CheckedListBoxItem item in ckbo.Properties.Items)
        if (item.CheckState == CheckState.Checked)
            selected.Add(item.Value.ToString());
    return selected;
}
```

## 项目家族特定配置

> 以下配置以参照窗体提取的项目家族为准。未列出家族时走 Deve-Upgrader 默认模式。

### Deve-Upgrader

```csharp
// GridStyle（21.2 可用，项目代号固定为 "ASS"）
new GridStyle("ASS", this, gcMain, gvMain);
new GridStyle("ASS", this, tlMain);       // TreeList 用单参数重载
```

### Deve-CRS

```csharp
// GridStyle（项目代号 "CRS" / "HKYL"）
new GridStyle("CRS", this, gcMain, gvMain);

// 权限菜单注册（仅 CRS）
AddControlItemGroupConfig(new ControlItemGroupConfig("默认菜单", cms, gcMain));
```

> CRS 的 `varlist` 类是纯工具类，不持 Conn 属性。代码中 `varlist.ASSConn` 的扫描命中**几乎全是注释残留**，非注释调用为 0。连接名必须扫描非注释代码或 `App.config` 确认。

### EQUP（CRS-Eq 子模块）

```csharp
// GridStyle 代号 "CRS"，但其余风格同 Upgrader（非泛型 frmBase + ListOperate）
// 消息框使用 XtraMessageBox（而非 UICommonBase.ShowMessageBox）
```

### CSS.WHXL.Extend

```csharp
// GridStyle 代号 "CSS"（本地代号）
new GridStyle("CSS", this, gcMain, gvMain);

// DBHelp 实例名：varlist.ASSDBHelp（自定义封装）
```

## 控件命名规范

> 命名规范权威来源：`references/three-tier-mvp.md`「控件命名」节（17 类控件命名格式 + 示例）。
> 本文件不再重复表格，有分歧以 three-tier-mvp.md 为准。
