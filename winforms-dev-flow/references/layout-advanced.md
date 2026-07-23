# LayoutControl 高级布局

> 加载时机：需要复杂表单布局、Table Layout 模式、程序化动态布局时读取。

## 布局模式

### Regular 模式（默认）

```csharp
// 默认模式：控件按 AddItem 顺序垂直排列
layoutControlGroup.LayoutMode = LayoutMode.Regular;

// 添加控件
layoutControl1.AddItem("名称:", txtName);
layoutControl1.AddItem("编码:", txtCode);
layoutControl1.AddItem("状态:", cboStatus);
```

### Table Layout 模式（网格布局）

```csharp
// 启用 Table Layout
layoutControlGroup.LayoutMode = LayoutMode.Table;

// 定义行（自动 + 百分比）
layoutControlGroup.OptionsTableLayoutGroup.RowDefinitions.Clear();
layoutControlGroup.OptionsTableLayoutGroup.RowDefinitions.Add(new RowDefinition { SizeType = SizeType.AutoSize });  // 第1行：自动
layoutControlGroup.OptionsTableLayoutGroup.RowDefinitions.Add(new RowDefinition { SizeType = SizeType.Percent, Width = 50 });  // 第2行：50%
layoutControlGroup.OptionsTableLayoutGroup.RowDefinitions.Add(new RowDefinition { SizeType = SizeType.Percent, Width = 50 });  // 第3行：50%

// 定义列
layoutControlGroup.OptionsTableLayoutGroup.ColumnDefinitions.Clear();
layoutControlGroup.OptionsTableLayoutGroup.ColumnDefinitions.Add(new ColumnDefinition { SizeType = SizeType.AutoSize });  // Label 列
layoutControlGroup.OptionsTableLayoutGroup.ColumnDefinitions.Add(new ColumnDefinition { SizeType = SizeType.Percent, Width = 100 });  // 编辑列

// 添加控件到指定单元格
var item1 = layoutControlGroup.AddItem("名称:", txtName);
item1.LayoutMode = LayoutMode.Table;
BaseLayoutItem.SetRow(item1, 0);  // 第 0 行
BaseLayoutItem.SetColumn(item1, 0);  // Label 列
BaseLayoutItem.SetColumnSpan(item1, 2);  // 跨 2 列

var item2 = layoutControlGroup.AddItem("备注:", memoRemark);
item2.LayoutMode = LayoutMode.Table;
BaseLayoutItem.SetRow(item2, 1);
BaseLayoutItem.SetColumn(item2, 0);
BaseLayoutItem.SetColumnSpan(item2, 2);
```

### Flow Layout 模式

```csharp
// 控件按可用空间自动排列（类似 HTML flex）
layoutControlGroup.LayoutMode = LayoutMode.Flow;
```

## 分组（LayoutControlGroup）

### 基本分组

```csharp
// 创建组
LayoutControlGroup groupBasic = layoutControl1.Root.AddGroup();
groupBasic.Text = "基本信息";
groupBasic.LayoutMode = LayoutMode.Regular;

// 向组内添加控件
groupBasic.AddItem("名称:", txtName);
groupBasic.AddItem("编码:", txtCode);
```

### 嵌套组

```csharp
LayoutControlGroup groupParent = layoutControl1.Root.AddGroup();
groupParent.Text = "基本信息";

LayoutControlGroup groupChild = groupParent.AddGroup();
groupChild.Text = "联系信息";
groupChild.AddItem("电话:", txtPhone);
groupChild.AddItem("邮箱:", txtEmail);
```

### Tabbed Group（选项卡组）

```csharp
// 创建选项卡组
TabbedControlGroup tabGroup = layoutControl1.Root.AddTabbedGroup();
tabGroup.Text = "";  // 不显示组标题

// 创建选项卡页
LayoutControlGroup tabBasic = tabGroup.AddTabPage();
tabBasic.Text = "基本信息";
tabBasic.AddItem("名称:", txtName);

LayoutControlGroup tabDetail = tabGroup.AddTabPage();
tabGroup.Text = "详细信息";
tabDetail.AddItem("备注:", memoRemark);

// 切换选项卡
tabGroup.SelectedTabPage = tabBasic;
```

## 分隔条（SplitterItem）

```csharp
// 在两组之间添加可拖拽分隔条
SplitterItem splitter = new SplitterItem();
splitter.ResetVisibilityToDefault();
layoutControl1.Root.AddItem(splitter);

// 设置分隔条位置
splitter.ItemSize = 200;  // 分隔条上方组的大小
splitter.ItemVisible = true;
```

## 空占位（EmptySpaceItem）

```csharp
// 添加空白间距
EmptySpaceItem empty = new EmptySpaceItem();
empty.Size = new Size(10, 10);
layoutControl1.Root.AddItem(empty);
```

## 运行时动态布局

```csharp
// 动态添加字段
private void AddFieldToLayout(string labelText, TextEdit edit, LayoutControlGroup targetGroup)
{
    var item = targetGroup.AddItem(labelText, edit);
    item.TextVisible = true;
    item.Size = new Size(300, 24);
}

// 动态移除字段
private void RemoveFieldFromLayout(LayoutControlItem item)
{
    layoutControl1.Root.RemoveItem(item);
    item.Control.Dispose();
    item.Dispose();
}
```

## 布局保存/恢复

```csharp
// 保存布局到 XML 字符串
string layoutXml = layoutControl1.SaveLayoutToXml();

// 从 XML 恢复
layoutControl1.RestoreLayoutFromXml(layoutXml);

// 保存到注册表
layoutControl1.SaveLayoutToRegistry("Software\\MyApp\\Layout");

// 从注册表恢复
layoutControl1.RestoreLayoutFromRegistry("Software\\MyApp\\Layout");
```

## 约束与尺寸

```csharp
// 设置控件最大/最小尺寸
layoutControlItem1.SizeConstraintsType = SizeConstraintsType.Custom;
layoutControlItem1.MaxSize = new Size(500, 24);
layoutControlItem1.MinSize = new Size(100, 24);

// 固定尺寸
layoutControlItem1.SizeConstraintsType = SizeConstraintsType.Default;
layoutControlItem1.Size = new Size(300, 24);

// 文本到控件的距离
layoutControl1.OptionsItemText.TextToControlDistance = 4;
```

## 可见性控制

```csharp
// 条件显示/隐藏字段
private void ToggleField(bool show)
{
    layoutControlItem1.Visibility = show 
        ? DevExpress.XtraLayout.Utils.LayoutVisibility.Always 
        : DevExpress.XtraLayout.Utils.LayoutVisibility.Never;
}

// 仅在设计时显示
layoutControlItem1.Visibility = DevExpress.XtraLayout.Utils.LayoutVisibility.OnlyInDesignTime;
```

## 常见布局结构

### 查询区 + 列表

```csharp
// LayoutControl 根
// ├─ lcgSearch (Group, Text="查询条件")
// │   ├─ lciKeyword (TextEdit)
// │   ├─ lciDateStart (DateEdit)
// │   └─ lciBtnSearch (SimpleButton) + lciBtnReset (SimpleButton)
// ├─ SplitterItem
// └─ lcgGrid (Group, Text="数据列表")
//     └─ lciGrid (GridControl)
```

### 标签页表单

```csharp
// LayoutControl 根
// ├─ TabbedControlGroup
// │   ├─ TabPage "基本信息"
// │   │   ├─ lciName (TextEdit)
// │   │   └─ lciCode (TextEdit)
// │   └─ TabPage "详细信息"
// │       ├─ lciRemark (MemoEdit)
// │       └─ lciStatus (ComboBoxEdit)
// └─ lciButtons (SimpleButton 保存/取消)
```
