# 编辑器控件参考（XtraEditors）

> 加载时机：生成窗体时确定编辑器控件类型、精确配置、与 LayoutControl/GridView 集成方式。

## TextEdit（文本输入）

```csharp
TextEdit txtName = new TextEdit();
txtName.Name = "txtName";
txtName.Properties.MaxLength = 50;          // 限制输入长度
txtName.Properties.NullValuePrompt = "请输入";  // 占位提示
txtName.Properties.NullValuePromptShowForEmptyValue = true;
txtName.Size = new Size(200, 22);
```

## MemoEdit（多行文本）

```csharp
MemoEdit memo = new MemoEdit();
memo.Properties.MaxLength = 500;
memo.Properties.ScrollBars = ScrollBars.Both;
memo.Properties.WordWrap = true;
memo.Size = new Size(200, 80);
```

## DateEdit（日期选择）

```csharp
DateEdit deStart = new DateEdit();
deStart.Name = "deStart";
deStart.Properties.EditMask = "yyyy-MM-dd";
deStart.Properties.Mask.UseMaskAsDisplayFormat = true;
deStart.Properties.DisplayFormat.FormatString = "yyyy-MM-dd";
deStart.Properties.DisplayFormat.FormatType = DevExpress.Utils.FormatType.DateTime;
deStart.Properties.EditFormat.FormatString = "yyyy-MM-dd";
deStart.Properties.EditFormat.FormatType = DevExpress.Utils.FormatType.DateTime;
deStart.Properties.VistaDisplayMode = DevExpress.Utils.DefaultBoolean.True;  // 21.2 推荐
deStart.Properties.VistaEditTime = DevExpress.Utils.DefaultBoolean.False;
deStart.Properties.CalendarView = DevExpress.Utils.CalendarView.Classic;
deStart.Properties.ShowToday = true;
deStart.Properties.ShowClearButton = true;
deStart.Properties.Buttons.AddRange(new EditorButton[] { new EditorButton(ButtonPredefines.Combo) });
```

## SpinEdit（数值输入）

```csharp
SpinEdit spnQty = new SpinEdit();
spnQty.Properties.MinValue = 0;
spnQty.Properties.MaxValue = 999999;
spnQty.Properties.Increment = 1;
spnQty.Properties.DisplayFormat.FormatString = "N0";
spnQty.Properties.DisplayFormat.FormatType = DevExpress.Utils.FormatType.Numeric;
spnQty.EditValue = 0;
```

## CalcEdit（计算器输入）

```csharp
CalcEdit calcPrice = new CalcEdit();
calcPrice.Properties.Mask.EditMask = "c2";  // 货币格式
calcPrice.Properties.DisplayFormat.FormatString = "N2";
calcPrice.Properties.DisplayFormat.FormatType = DevExpress.Utils.FormatType.Numeric;
```

## ComboBoxEdit（下拉单选）

```csharp
ComboBoxEdit cboStatus = new ComboBoxEdit();
cboStatus.Properties.Items.AddRange(new object[] {
    "未提交", "已提交", "已审批", "已退回"
});
cboStatus.Properties.DropDownRows = 10;
cboStatus.Properties.TextEditStyle = DevExpress.Utils.TextEditStyles.DisableTextEditor;  // 只允许从列表选
```

## CheckedComboBoxEdit（多选下拉）

```csharp
CheckedComboBoxEdit ckcboStatus = new CheckedComboBoxEdit();
ckcboStatus.Properties.Items.AddRange(new CheckedListBoxItem[] {
    new CheckedListBoxItem(0, "未提交"),
    new CheckedListBoxItem(1, "已提交"),
    new CheckedListBoxItem(2, "已审批"),
    new CheckedListBoxItem(3, "已退回")
});

// 获取选中值
List<string> GetSelectedStatus(CheckedComboBoxEdit ck)
{
    var selected = new List<string>();
    foreach (CheckedListBoxItem item in ck.Properties.Items)
    {
        if (item.CheckState == CheckState.Checked)
            selected.Add(item.Value.ToString());
    }
    return selected;
}
```

## CheckEdit（复选框）

```csharp
CheckEdit chkEnabled = new CheckEdit();
chkEnabled.Properties.Caption = "启用";
chkEnabled.Properties.ValueChecked = true;
chkEnabled.Properties.ValueUnchecked = false;
chkEnabled.Properties.AllowGrayed = false;
chkEnabled.Checked = true;
```

## RadioGroup（单选组）

```csharp
RadioGroup rgType = new RadioGroup();
rgType.Properties.Items.AddRange(new object[] {
    new RadioGroupItem(0, "类型A"),
    new RadioGroupItem(1, "类型B"),
    new RadioGroupItem(2, "类型C")
});
rgType.Properties.Columns = 3;  // 3 列排列
rgType.EditValue = 0;  // 默认选中
```

## LookUpEdit（查找下拉）

```csharp
LookUpEdit lkuStatus = new LookUpEdit();
lkuStatus.Properties.DataSource = statusList;  // List<StatusInfo>
lkuStatus.Properties.ValueMember = "Value";
lkuStatus.Properties.DisplayMember = "Text";
lkuStatus.Properties.Columns.Add(new LookUpColumnInfo("Text", "状态"));
lkuStatus.Properties.NullText = "-- 请选择 --";
lkuStatus.Properties.ShowFooter = false;
lkuStatus.Properties.ShowHeader = false;
```

## GridLookUpEdit（表格式下拉）

```csharp
GridLookUpEdit glkuPart = new GridLookUpEdit();
glkuPart.Properties.DataSource = partList;
glkuPart.Properties.ValueMember = "ID";
glkuPart.Properties.DisplayMember = "Name";
glkuPart.Properties.NullText = "-- 请选择 --";

// 配置弹出视图
glkuPart.Properties.PopupView.Columns["ID"].Visible = false;
glkuPart.Properties.PopupView.Columns["Name"].Caption = "零件名称";
glkuPart.Properties.PopupView.Columns["Code"].Caption = "编码";
glkuPart.Properties.PopupView.BestFitColumns();
glkuPart.Properties.PopupFormMinSize = new Size(400, 300);
```

## ImageComboBoxEdit（图文下拉）

```csharp
ImageComboBoxEdit imgCbo = new ImageComboBoxEdit();
imgCbo.Properties.Items.AddImageComboItem("待处理", 0, imageList1.Images[0]);
imgCbo.Properties.Items.AddImageComboItem("处理中", 1, imageList1.Images[1]);
imgCbo.Properties.Items.AddImageComboItem("已完成", 2, imageList1.Images[2]);
```

## ButtonEdit（带按钮的文本框）

```csharp
ButtonEdit btnEdit = new ButtonEdit();
btnEdit.Properties.Buttons.AddRange(new EditorButton[] {
    new EditorButton(ButtonPredefines.Ellipsis),  // "..." 按钮
    new EditorButton(ButtonPredefines.Clear)       // 清除按钮
});
btnEdit.ButtonClick += (s, e) =>
{
    if (e.Button.Kind == ButtonPredefines.Ellipsis)
    {
        // 打开选择对话框
        OpenSelectDialog();
    }
};
```

## SearchControl（搜索框）

```csharp
SearchControl search = new SearchControl();
search.Properties.Client = gcMain;  // 绑定到 GridControl
search.Properties.ShowSearchButton = true;
search.Properties.ShowClearButton = true;
search.Dock = DockStyle.Top;
```

## TimeEdit（时间选择）

```csharp
TimeEdit teStart = new TimeEdit();
teStart.Properties.Mask.EditMask = "HH:mm:ss";
teStart.Properties.Mask.UseMaskAsDisplayFormat = true;
teStart.Properties.DisplayFormat.FormatString = "HH:mm:ss";
teStart.Properties.DisplayFormat.FormatType = DevExpress.Utils.FormatType.DateTime;
```

## 编辑器与 LayoutControl 集成

```csharp
// TextEdit + LayoutControlItem
TextEdit txtName = new TextEdit();
txtName.Properties.MaxLength = 50;
LayoutControlItem item = layoutControl1.AddItem("名称:", txtName);
item.TextVisible = true;

// DateEdit + LayoutControlItem
DateEdit deStart = new DateEdit();
deStart.Properties.Mask.EditMask = "yyyy-MM-dd";
LayoutControlItem itemDate = layoutControl1.AddItem("开始日期:", deStart);

// ComboBoxEdit + LayoutControlItem
ComboBoxEdit cboStatus = new ComboBoxEdit();
cboStatus.Properties.Items.AddRange(new object[] { "启用", "禁用" });
LayoutControlItem itemStatus = layoutControl1.AddItem("状态:", cboStatus);
```

## 编辑器与 GridView 集成（RepositoryItem）

```csharp
// RepositoryItem 绑定流程（必读）
// 1. 创建 RepositoryItem
RepositoryItemDateEdit riDate = new RepositoryItemDateEdit();
riDate.Mask.EditMask = "yyyy-MM-dd";

// 2. 添加到 GridControl.RepositoryItems（必须先 Add）
gcMain.RepositoryItems.Add(riDate);

// 3. 绑定到列
gvMain.Columns["CreateDate"].ColumnEdit = riDate;
```

## 字段→编辑器映射速查

| Entity 字段类型 | 编辑器控件 | RepositoryItem | 备注 |
|---------------|-----------|---------------|------|
| string (短, ≤50) | TextEdit | — | `Properties.MaxLength` 对齐 DB 列长度 |
| string (长, >50) | MemoEdit | RepositoryItemMemoEdit | `Properties.ScrollBars` |
| int | SpinEdit | RepositoryItemSpinEdit | `Properties.MaxValue`/`MinValue` |
| decimal | CalcEdit / SpinEdit | RepositoryItemSpinEdit | `DisplayFormat.FormatString="N2"` |
| DateTime | DateEdit | RepositoryItemDateEdit | `Mask.EditMask="yyyy-MM-dd"` |
| TimeSpan | TimeEdit | RepositoryItemTimeEdit | `Mask.EditMask="HH:mm:ss"` |
| bool | CheckEdit | RepositoryItemCheckEdit | `ValueChecked=true; ValueUnchecked=false` |
| 枚举 | ComboBoxEdit | RepositoryItemComboBox | `Items.Add()` |
| 多选 | CheckedComboBoxEdit | RepositoryItemCheckedComboBoxEdit | 遍历 `Properties.Items` 获取选中值 |
| 外键 | LookUpEdit / GridLookUpEdit | RepositoryItemLookUpEdit | `ValueMember` + `DisplayMember` |
