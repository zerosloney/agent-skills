# GridView 高级功能

> 加载时机：需要 GridView 条件格式、汇总、排序、筛选、外观定制时读取。

## 条件格式（Conditional Formatting）

### RowCellStyle 事件（项目风格）

```csharp
private void gvMain_RowCellStyle(object sender, RowCellStyleEventArgs e)
{
    var row = gvMain.GetRow(e.RowHandle) as OrderInfo;
    if (row == null) return;

    if (row.Status == (int)OrderStatus.Submitted)
        e.Appearance.BackColor = Color.Pink;
    else if (row.Status == (int)OrderStatus.Approved)
        e.Appearance.BackColor = Color.LightGreen;
    else if (row.Status == (int)OrderStatus.Rejected)
        e.Appearance.BackColor = Color.Red;
}
```

### StyleFormatCondition（声明式，推荐）

```csharp
// 在 InitializeComponent 或 Load 中
var formatCondition = new DevExpress.XtraGrid.StyleFormatCondition();
formatCondition.Condition = FormatConditionEnum.Expression;
formatCondition.Expression = "[Status] == 1";  // 已提交
formatCondition.Appearance.BackColor = Color.Pink;
gvMain.FormatConditions.Add(formatCondition);

// 多条件示例
var cond2 = new DevExpress.XtraGrid.StyleFormatCondition();
cond2.Condition = FormatConditionEnum.Expression;
cond2.Expression = "[Status] == 2";  // 已审批
cond2.Appearance.BackColor = Color.LightGreen;
gvMain.FormatConditions.Add(cond2);
```

### 聚焦行外观

```csharp
// 选中行高亮（不显示聚焦单元格边框）
gvMain.OptionsSelection.EnableAppearanceFocusedCell = false;
gvMain.OptionsSelection.EnableAppearanceFocusedRow = true;
gvMain.Appearance.FocusedRow.BackColor = Color.FromArgb(255, 237, 206);  // Office 风格
gvMain.Appearance.FocusedRow.ForeColor = Color.Black;

// 多选行外观
gvMain.OptionsSelection.MultiSelect = true;
gvMain.OptionsSelection.MultiSelectMode = GridMultiSelectMode.RowSelect;
gvMain.Appearance.SelectedRow.BackColor = DXSkinColors.FillColors.Success;
gvMain.Appearance.SelectedRow.ForeColor = DXSkinColors.ForeColors.WindowText;
```

## 汇总（Summaries）

### 页脚汇总

```csharp
// 启用页脚
gvMain.OptionsView.ShowFooter = true;

// 总数汇总（SUM）
var colAmount = gvMain.Columns["Amount"];
if (colAmount != null)
{
    colAmount.SummaryItem.SummaryType = DevExpress.Data.SummaryItemType.Sum;
    colAmount.SummaryItem.DisplayFormat = "合计: {0:N2}";
}

// 计数汇总
var colID = gvMain.Columns["ID"];
if (colID != null)
{
    colID.SummaryItem.SummaryType = DevExpress.Data.SummaryItemType.Count;
    colID.SummaryItem.DisplayFormat = "共 {0} 条";
}

// 自定义汇总
gvMain.CustomSummaryCalculate += (s, e) =>
{
    if (e.SummaryProcess == CustomSummaryProcess.Finalize)
    {
        // 自定义计算逻辑
        e.TotalValue = ...;
    }
};
```

### 组汇总

```csharp
// 启用分组
gvMain.OptionsView.ShowGroupPanel = true;

// 组汇总
var groupSummary = new GridGroupSummaryItem();
groupSummary.SummaryType = DevExpress.Data.SummaryItemType.Sum;
groupSummary.FieldName = "Amount";
groupSummary.DisplayFormat = "组合计: {0:N2}";
gvMain.GroupSummary.Add(groupSummary);
```

## 排序（Sorting）

### 程序化排序

```csharp
// 单列排序
gvMain.SortInfo.Clear();
gvMain.SortInfo.Add(gvMain.Columns["CreateTime"], DevExpress.Data.ColumnSortOrder.Descending);

// 多列排序（Shift+点击）
gvMain.SortInfo.Add(gvMain.Columns["Status"], DevExpress.Data.ColumnSortOrder.Ascending);

// 清除排序
gvMain.SortInfo.Clear();
gvMain.ClearSorting();
```

### 排序控制

```csharp
// 禁止排序
gvMain.OptionsCustomization.AllowSort = false;

// 单列禁止排序
gvMain.Columns["ID"].OptionsColumn.AllowSort = false;

// 右键菜单排序控制
gvMain.PopupMenuShowing += (s, e) =>
{
    if (e.MenuType == GridMenuType.Column)
    {
        // 移除排序菜单项
        var sortItem = e.Menu.Items.FirstOrDefault(i => i.Caption.Contains("Sort"));
        if (sortItem != null) e.Menu.Items.Remove(sortItem);
    }
};
```

## 筛选（Filtering）

### 自动筛选行

```csharp
// 启用自动筛选行（Step 2 推荐配置）
gvMain.OptionsView.ShowAutoFilterRow = true;

// 程序化设置筛选
gvMain.SetAutoFilterValue(gvMain.Columns["Status"], 1);  // Status = 1
gvMain.GetAutoFilterValue(gvMain.Columns["Status"]);     // 获取当前筛选值

// 清除筛选
gvMain.ClearColumnsFilter();
```

### 高级筛选

```csharp
// 字符串筛选条件
gvMain.ActiveFilterString = "[OrderDate] Between (#01 JAN 1996#, #01 AUG 1996#) And [ShipCity] Is not null";

// CriteriaOperator（类型安全）
var expr1 = new BinaryOperator("ShipCity", "Aachen");
var expr2 = new BinaryOperator("OrderID", "10258");
gvMain.ActiveFilterCriteria = GroupOperator.Or(expr1, expr2);

// 列级筛选
colStatus.FilterInfo = new ColumnFilterInfo("[Status] = 1");
```

### 筛选面板

```csharp
// 筛选面板模式
gvMain.OptionsFilter.FilterMode = FilterMode.Extended;       // 扩展筛选
gvMain.OptionsFilter.FilterEditorMode = FilterEditorMode.Default;
gvMain.OptionsFilter.ShowAllValuesInFilterPopup = true;
```

## 行高与外观

### 行高控制

```csharp
// 固定行高（默认 -1 = 自适应）
gvMain.RowHeight = 24;

// 列头高度
gvMain.ColumnPanelRowHeight = 36;

// 组行高度
gvMain.GroupRowHeight = 28;

// 动态行高（按内容）
gvMain.OptionsView.RowAutoHeight = true;
gvMain.CalcRowHeight += (s, e) =>
{
    if (e.RowHandle >= 0)
        e.RowHeight = (int)gvMain.GetDataRow(e.RowHandle)["RowHeight"];
};
```

### 行列边框控制

```csharp
// 隐藏水平线
gvMain.OptionsView.ShowHorizontalLines = false;
// 隐藏垂直线
gvMain.OptionsView.ShowVerticalLines = false;
// 行分隔线高度
gvMain.RowSeparatorHeight = 0;
// 自定义分隔线颜色
gvMain.RowSeparatorColor = Color.LightGray;
```

### 外观优先级

```csharp
// 全局外观设置（通过 Appearance 属性）
gvMain.Appearance.EvenRow.BackColor = Color.WhiteSmoke;
gvMain.Appearance.OddRow.BackColor = Color.White;
gvMain.Appearance.HeaderPanel.TextOptions.HAlignment = HorzAlignment.Center;
gvMain.Appearance.Row.TextOptions.VAlignment = VertAlignment.Center;

// 列级别外观
colName.AppearanceCell.TextOptions.HAlignment = HorzAlignment.Near;
colAmount.AppearanceCell.TextOptions.HAlignment = HorzAlignment.Far;
colAmount.AppearanceCell.FormatString = "N2";

// 使用 DXSkinColors 保持皮肤一致性
gvMain.Appearance.FocusedCell.BackColor = DXSkinColors.FillColors.Warning;
gvMain.Appearance.FocusedRow.BackColor = DXSkinColors.FillColors.Primary;
```

## 单元格编辑（In-Place Editors）

### RepositoryItem 绑定流程

```csharp
// 1. 创建 RepositoryItem
var riDate = new RepositoryItemDateEdit();
riDate.Mask.EditMask = "yyyy-MM-dd";
riDate.DisplayFormat.FormatString = "yyyy-MM-dd";
riDate.DisplayFormat.FormatType = DevExpress.Utils.FormatType.DateTime;

// 2. 添加到 GridControl.RepositoryItems（必须先 Add）
gcMain.RepositoryItems.Add(riDate);

// 3. 绑定到列
colCreateDate.ColumnEdit = riDate;
```

### 常用 RepositoryItem 配置

```csharp
// RepositoryItemCheckEdit（布尔列）
var riCheck = new RepositoryItemCheckEdit();
riCheck.ValueChecked = true;
riCheck.ValueUnchecked = false;
riCheck.AllowGrayed = false;
gcMain.RepositoryItems.Add(riCheck);
colEnabled.ColumnEdit = riCheck;

// RepositoryItemComboBox（枚举列）
var riCombo = new RepositoryItemComboBox();
riCombo.Items.AddRange(new object[] {
    new KeyValuePair<int, string>(0, "未提交"),
    new KeyValuePair<int, string>(1, "已提交"),
    new KeyValuePair<int, string>(2, "已审批")
});
gcMain.RepositoryItems.Add(riCombo);
colStatus.ColumnEdit = riCombo;

// RepositoryItemSpinEdit（数值列）
var riSpin = new RepositoryItemSpinEdit();
riSpin.MinValue = 0;
riSpin.MaxValue = 999999;
riSpin.Mask.EditMask = "N2";
gcMain.RepositoryItems.Add(riSpin);
colPrice.ColumnEdit = riSpin;

// RepositoryItemMemoEdit（长文本列）
var riMemo = new RepositoryItemMemoEdit();
riMemo.ScrollBars = ScrollBars.Both;
gcMain.RepositoryItems.Add(riMemo);
colRemark.ColumnEdit = riMemo;
```

## 行号显示

```csharp
// 自定义绘制行号
gvMain.CustomDrawRowIndicator += (s, e) =>
{
    if (e.RowHandle < 0) return;  // 跳过分组行
    e.Info.DisplayText = (gvMain.GetVisibleIndex(e.RowHandle) + 1).ToString();
    e.Painter.DrawObject(e.Info);
    e.Handled = true;
};

// 调整行号列宽度
gvMain.IndicatorWidth = 40;
```

## 性能优化

### 大数据量优化

```csharp
// 1. 关闭不必要的视觉元素
gvMain.OptionsView.ShowGroupPanel = false;
gvMain.OptionsView.ShowIndicator = false;
gvMain.OptionsView.ShowHorizontalLines = false;
gvMain.OptionsView.ShowVerticalLines = false;

// 2. 使用 BeginUpdate/EndUpdate 包裹批量操作
gcMain.BeginUpdate();
try
{
    gcMain.DataSource = largeData;
    gvMain.BestFitColumns();
}
finally
{
    gcMain.EndUpdate();
}

// 3. 虚拟模式（超大数据集 > 10万行）
gvMain.VirtualMode = true;
gvMain.OptionsView.ShowAutoFilterRow = false;
// 需实现 CustomUnboundColumnData 事件处理

// 4. 延迟列生成
gcMain.DataSource = data;
gvMain.PopulateColumns();  // 显式调用，避免重复生成
```

## 打印（Print）

```csharp
// 基础打印
gvMain.Print();

// 带选项打印
var ps = new DevExpress.XtraPrinting.PrintingSystem();
var link = new DevExpress.XtraPrinting.PrintableComponentLink(ps);
link.Component = gcMain;
link.CreateDocument();
ps.PreviewFormEx.Show();
```

## 导出 Excel

```csharp
// 项目风格（Upgrader）
private void ExportExcel()
{
    _gridUI.ExportExcel(gcMain, "导出文件名");
}

// 原生 API
private void ExportExcelNative()
{
    var dialog = new SaveFileDialog();
    dialog.Filter = "Excel (*.xlsx)|*.xlsx|Excel (*.xls)|*.xls";
    if (dialog.ShowDialog() == DialogResult.OK)
    {
        gcMain.ExportToXlsx(dialog.FileName);
        // 或
        gcMain.ExportToXls(dialog.FileName);
        gcMain.ExportToCsv(dialog.FileName);
    }
}
```

## 常用事件速查

| 事件 | 用途 |
|------|------|
| `RowStyle` | 行外观定制（整行） |
| `RowCellStyle` | 单元格外观定制（按条件变色） |
| `CustomDrawRowIndicator` | 行号自定义绘制 |
| `FocusedRowChanged` | 焦点行切换（替代 CellClick） |
| `DoubleClick` | 双击行（打开编辑） |
| `PopupMenuShowing` | 右键菜单控制 |
| `ShowGridMenu` | Grid 右键菜单 |
| `CellValueChanged` | 单元格值变更后 |
| `ValidatingEditor` | 编辑器值验证 |
| `CustomSummaryCalculate` | 自定义汇总计算 |
| `CalcRowHeight` | 动态行高 |
| `KeyDown` | 键盘事件（Delete 删除、Enter 确认） |
