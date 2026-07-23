# 常见陷阱与修复

> 加载时机：生成/调试 DevExpress WinForms 应用时参考。按项目家族（Upgrader / CRS / EQUP / CSS）的已知坑位分类。

## 陷阱 1：RepositoryItem 未添加到 GridControl

**现象**：运行时列显示为空或编辑器不弹出。

```csharp
// ❌ 错误：RepositoryItem 未添加到 gc.RepositoryItems
var ri = new RepositoryItemComboBox();
gv.Columns["Status"].ColumnEdit = ri;  // 运行时抛异常或不显示

// ✅ 正确：先 Add 再绑定
var ri = new RepositoryItemComboBox();
gcMain.RepositoryItems.Add(ri);           // 关键：先 Add
gvMain.Columns["Status"].ColumnEdit = ri; // 再绑定
```

> Upgrader 项目见 `references/designer-patterns.md §1.4` 标准写法。

## 陷阱 2：LookAndFeel 未生效

**现象**：设置了 SkinName 但控件仍为默认样式。

**原因**：
- `SetSkinStyle` 在控件创建之后调用
- 缺少 `UserSkins.BonusSkins.Register()`（使用 BonusSkins 时）
- `Application.EnableVisualStyles()` 未调用

```csharp
// ✅ 正确顺序
[STAThread]
static void Main()
{
    Application.EnableVisualStyles();                    // 1. 启用
    UserSkins.BonusSkins.Register();                      // 2. 注册 BonusSkins
    SkinManager.EnableFormSkins();                        // 3. 启用表单皮肤
    UserLookAndFeel.Default.SetSkinStyle("Office 2019 Colorful"); // 4. 设置
    Application.Run(new FrmMain());
}
```

## 陷阱 3：GridControl DataSource 直接赋值 List<T> 后排序失效

**现象**：点击列头排序不生效。

```csharp
// ❌ 排序不生效
gcMain.DataSource = myList;  // List<T> 不支持排序

// ✅ 使用 BindingSource
BindingSource bs = new BindingSource { DataSource = myList };
gcMain.DataSource = bs;
// 此时点击列头自动排序生效
```

## 陷阱 4：TreeList ParentFieldName/KeyFieldName 未设置

**现象**：TreeList 显示为平面列表，不折叠。

```csharp
// ❌ 缺少关键配置
tlMain.DataSource = dataList;
// 显示为单层列表

// ✅ 正确配置
tlMain.DataSource = dataList;
tlMain.KeyFieldName = "ID";          // 主键字段
tlMain.ParentFieldName = "ParentID"; // 父级字段
tlMain.ExpandAll();                  // 展开所有节点（可选）
```

> 根节点的 ParentID 应为 `string.Empty`，确保能正确渲染顶层。

## 陷阱 5：XtraMessageBox.Show 参数类型错误

**现象**：编译错误或运行时异常。

```csharp
// ❌ 错误：MessageBoxIcon 不是 DevExpress 的枚举
XtraMessageBox.Show("文本", "标题", MessageBoxButtons.OK, MessageBoxIcon.Information);
// 编译器认为 MessageBoxIcon 是 WinForms 的

// ✅ 正确：使用 DevExpress 枚举
XtraMessageBox.Show("文本", "标题", MessageBoxButtons.OK, DevExpress.Utils.ToolTipIcon.Info);
```

## 陷阱 6：DateEdit 日期格式

**现象**：日期显示为空或格式不对。

```csharp
// ❌ 缺少 Mask 设置
dateEdit1.EditValue = DateTime.Now;
// 可能显示为空白或默认格式

// ✅ 正确配置
dateEdit1.Properties.Mask.EditMask = "yyyy-MM-dd";
dateEdit1.Properties.Mask.UseMaskAsDisplayFormat = true;
dateEdit1.Properties.VistaDisplayMode = DevExpress.Utils.DefaultBoolean.True; // 21.2 推荐
dateEdit1.Properties.VistaEditTime = DevExpress.Utils.DefaultBoolean.False;
```

## 陷阱 7：GridView 列宽在数据绑定后丢失

**现象**：自定义列宽在运行时恢复为默认值。

```csharp
// ✅ 用 BeginUpdate/EndUpdate 包裹
gcMain.BeginUpdate();
try
{
    gcMain.DataSource = data;
    gvMain.BestFitColumns();  // 自动计算最佳列宽
}
finally
{
    gcMain.EndUpdate();
}
```

## 陷阱 8：LayoutControl AutoSize 导致布局膨胀

**现象**：LayoutControl 内的控件超出窗体范围。

```csharp
// ❌ LayoutControl 默认 AutoSize = true，可能导致无限膨胀
this.layoutControl1.AutoSize = true;

// ✅ 设置为 false，让 Dock 控制大小
this.layoutControl1.AutoSize = false;
this.layoutControl1.Dock = DockStyle.Fill;
```

## 陷阱 9：GridStyle 在 InitializeComponent 中段调用

**现象**：GridStyle 抛出 NullRef 异常或布局不生效。

```csharp
// ❌ 在中间
this.gcMain = new GridControl();
this._gridStyle = new GridStyle("ASS", this, gcMain);  // ← 后置

// ✅ 在最前
this._gridStyle = new GridStyle("ASS", this, gcMain, gvMain);  // ← 必须在顶部
this.gcMain = new GridControl();
this.gvMain = new GridView();
```

> GridStyle 会 hook Form 事件，在控件实例化之前调用会报 NullRef。

## 陷阱 10：gvMain.GridControl 双向绑定漏写

**现象**：数据绑定后列表为空。

```csharp
// ❌ 只写一边
this.gcMain.MainView = this.gvMain;
// 漏了 gvMain.GridControl = this.gcMain;

// ✅ 双向都要写
this.gcMain.MainView = this.gvMain;
this.gvMain.GridControl = this.gcMain;
```

## 陷阱 11：LayoutControl 子控件用 Controls.Add

**现象**：控件不显示。

```csharp
// ❌ LayoutControl 的子控件必须用 AddItem
this.lcMain.Controls.Add(this.txtCode);  // 不显示

// ✅ 用 AddItem
this.lcgMain.AddItem(this.txtCode);      // 显示
```

## 陷阱 12：多线程更新 UI 控件

**现象**：跨线程操作异常。

```csharp
// ✅ 使用 Invoke
this.Invoke((Action)(() => {
    _view.BindData(data);
}));
```

## 陷阱 13：高 DPI 模糊

> ⚠️ `Application.SetHighDpiMode(...)` 是 **.NET Core 3+ / .NET 5+** API，**.NET Framework 4.7.2 不存在**。
> .NET Framework 项目通过 **app.manifest** 声明 DPI 感知（VS 新建项目时默认已包含此 manifest）。

**app.manifest（项目根目录，Build Action = None / Copy if newer）：**

```xml
<?xml version="1.0" encoding="utf-8"?>
<assembly manifestVersion="1.0" xmlns="urn:schemas-microsoft-com:asm.v1">
  <application xmlns="urn:schemas-microsoft-com:asm.v3">
    <windowsSettings>
      <dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true/pm</dpiAware>
      <!-- true/pm = Per Monitor V2 感知（Win10 1703+ 生效，旧系统回退为 System 感知） -->
    </windowsSettings>
  </application>
</assembly>
```

**Program.cs（.NET Framework 写法）：**

```csharp
Application.EnableVisualStyles();
Application.SetCompatibleTextRenderingDefault(false);
```

**窗体设置：**

```csharp
this.AutoScaleMode = AutoScaleMode.Dpi;
this.AutoScaleDimensions = new SizeF(96F, 96F);
```

## 陷阱 14：.csproj 漏注册 Designer 文件

**现象**：编译报错「未找到类 Frm_xxx」。

```xml
<!-- 三件套必须都有 -->
<Compile Include="Frm_XXX.cs">
  <SubType>Form</SubType>
</Compile>
<Compile Include="Frm_XXX.Designer.cs">
  <DependentUpon>Frm_XXX.cs</DependentUpon>
</Compile>
<EmbeddedResource Include="Frm_XXX.resx">
  <DependentUpon>Frm_XXX.cs</DependentUpon>
</EmbeddedResource>
```

## 陷阱 15：ShowingEditor 条件禁用编辑

**现象**：特定条件下某列不可编辑，但编辑器仍然弹出。

**场景**：如 A 列值="作废"时，B 列应禁止编辑。

```csharp
private void gvMain_ShowingEditor(object sender, CancelEventArgs e)
{
    var view = sender as GridView;
    var row = view.GetRow(view.FocusedRowHandle) as OrderInfo;
    if (row == null) return;

    // 当"作废"状态时，禁用编辑
    if (view.FocusedColumn.FieldName == "Amount")
    {
        if (row.Status == 3) // 作废
        {
            e.Cancel = true;
            return;
        }
    }
}
```

> 挂载事件：`gvMain.ShowingEditor += gvMain_ShowingEditor;`

## 陷阱 16：ColumnPositionChanged 列拖拽监听

**现象**：需要知道用户何时手动调整了列顺序，以便持久化布局。

```csharp
private void gvMain_ColumnPositionChanged(object sender, EventArgs e)
{
    var col = sender as GridColumn;
    // col.VisibleIndex = 当前列位置
    // col.FieldName = 当前列字段名
    // 配合序列化保存列宽/顺序
}
```

> 官方文档（慧都网）：`ColumnView.ColumnPositionChanged` 事件可获取被移动列的标题和当前索引，用于状态栏显示或布局保存。

## 陷阱 17：EditFormPrepared 自定义编辑表单外观

**现象**：GridView 内嵌编辑表单（EditForm）的背景色、控件样式需与状态联动。

```csharp
private void gvMain_EditFormPrepared(object sender, EditFormPreparedEventArgs e)
{
    var view = sender as GridView;
    foreach (GridColumn c in view.VisibleColumns)
    {
        // 将行样式同步到 EditForm 控件背景色
        e.BindableControls[c].BackColor = GetRowBackColor(view, e.RowHandle);
    }
}

// 状态颜色逻辑（与 RowCellStyle 保持一致）
private Color GetRowBackColor(GridView view, int rowHandle)
{
    var row = view.GetRow(rowHandle) as OrderInfo;
    if (row == null) return Color.Empty;
    if (row.Status == 1) return Color.Pink;
    if (row.Status == 2) return Color.LightGreen;
    return Color.Empty;
}
```

> 官方文档（CSDN）：`EditFormPrepared` 事件在编辑表单创建后触发，`e.BindableControls[col]` 可获取每列对应的编辑器实例，从而修改 BackColor / ForeColor / Enabled 等属性。

## 调试技巧

| 技巧 | 命令/代码 |
|------|----------|
| 查看当前皮肤 | `UserLookAndFeel.Default.SkinName` |
| 列出所有已注册皮肤 | `DevExpress.Skins.SkinManager.Default.Skins` |
| Grid 列信息 | `gvMain.Columns.Count` + 循环检查 `col.FieldName` |
| RepositoryItem 列表 | `gcMain.RepositoryItems.Count` + 循环检查 |
| 控件实际 LookAndFeel | `control.LookAndFeel.SkinName` |
