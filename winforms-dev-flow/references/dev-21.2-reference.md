# DevExpress 21.2 精确实现参考

> 加载时机：生成窗体时确定控件选型、必设属性、Designer 代码结构、版本特定行为。
> 版本锁定：DevExpress **21.2.x**，.NET Framework **4.7.2**，程序集路径 `Bin\Framework\`。

## 核心程序集

> 以下为 DevExpress 21.2 与 .NET Framework 4.7.2 配套的**核心程序集**。.NET Framework 项目只引用 `Bin\Framework\` 下的 DLL，不混用 `Bin\NetCore\` 或 `Bin\Standard\`。

| 程序集 | 命名空间 | 主要控件 / 类 |
|--------|---------|-------------|
| `DevExpress.XtraEditors.v21.2.dll` | `DevExpress.XtraEditors` | TextEdit, ComboBoxEdit, DateEdit, CheckEdit, MemoEdit, ButtonEdit, SpinEdit, CalcEdit, LookUpEdit, GridLookUpEdit, TimeEdit, ImageComboBoxEdit, CheckedComboBoxEdit, SearchControl, SimpleButton, LabelControl, RepositoryItem 系列 |
| `DevExpress.XtraGrid.v21.2.dll` | `DevExpress.XtraGrid` | GridControl, GridView, BandedGridView, AdvBandedGridView, CardView, LayoutView |
| `DevExpress.XtraLayout.v21.2.dll` | `DevExpress.XtraLayout` | LayoutControl, LayoutControlGroup, LayoutControlItem, EmptySpaceItem, SplitterItem |
| `DevExpress.XtraBars.v21.2.dll` | `DevExpress.XtraBars` | BarManager, Bar, BarDockControl, BarSubItem, BarButtonItem |
| `DevExpress.XtraBars.Ribbon.v21.2.dll` | `DevExpress.XtraBars.Ribbon` | RibbonControl, RibbonPage, RibbonPageGroup, RibbonStatusBar |
| `DevExpress.XtraTreeList.v21.2.dll` | `DevExpress.XtraTreeList` | TreeList, TreeListColumn |
| `DevExpress.XtraPivotGrid.v21.2.dll` | `DevExpress.XtraPivotGrid` | PivotGridControl, PivotGridField |
| `DevExpress.XtraVerticalGrid.v21.2.dll` | `DevExpress.XtraVerticalGrid` | VGridControl, EditorRow |
| `DevExpress.XtraCharts.v21.2.dll` | `DevExpress.XtraCharts` | ChartControl, XYDiagram, Series |
| `DevExpress.XtraScheduler.v21.2.dll` | `DevExpress.XtraScheduler` | SchedulerControl, SchedulerStorage |
| `DevExpress.XtraReports.v21.2.dll` | `DevExpress.XtraReports` | XtraReport, DetailBand, XRLabel, XRTable |
| `DevExpress.XtraRichEdit.v21.2.dll` | `DevExpress.XtraRichEdit` | RichEditControl |
| `DevExpress.XtraSpreadsheet.v21.2.dll` | `DevExpress.XtraSpreadsheet` | SpreadsheetControl |
| `DevExpress.XtraSpellChecker.v21.2.dll` | `DevExpress.XtraSpellChecker` | SpellChecker |
| `DevExpress.XtraPrinting.v21.2.dll` | `DevExpress.XtraPrinting` | PrintableComponentLink, PrintingSystem |
| `DevExpress.XtraWizard.v21.2.dll` | `DevExpress.XtraWizard` | WizardControl, WizardPage |
| `DevExpress.XtraDiagram.v21.2.dll` | `DevExpress.XtraDiagram` | DiagramControl, DiagramShape, DiagramConnector |
| `DevExpress.XtraGantt.v21.2.dll` | `DevExpress.XtraGantt` | GanttControl |
| `DevExpress.XtraDialogs.v21.2.dll` | `DevExpress.XtraDialogs` | XtraMessageBox（替代 MessageBox） |
| `DevExpress.Utils.v21.2.dll` | `DevExpress.Utils` | LookAndFeel, SkinManager, ImageCollection, CalendarView, FormatType, HorzAlignment |
| `DevExpress.Data.v21.2.dll` | `DevExpress.Data` | BindingSource 辅助类、数据源适配 |
| `DevExpress.BonusSkins.v21.2.dll` | — | 额外皮肤（DevExpress Dark, Metropolis 等） |

### .csproj 引用示例

```xml
<ItemGroup>
  <Reference Include="DevExpress.XtraEditors.v21.2">
    <HintPath>$(DevExpressPath)\Bin\Framework\DevExpress.XtraEditors.v21.2.dll</HintPath>
  </Reference>
  <Reference Include="DevExpress.XtraGrid.v21.2">
    <HintPath>$(DevExpressPath)\Bin\Framework\DevExpress.XtraGrid.v21.2.dll</HintPath>
  </Reference>
  <Reference Include="DevExpress.XtraLayout.v21.2">
    <HintPath>$(DevExpressPath)\Bin\Framework\DevExpress.XtraLayout.v21.2.dll</HintPath>
  </Reference>
  <!-- 按需添加其他程序集 -->
</ItemGroup>
```

> 实际项目中通常通过 NuGet 离线包或项目级 `<Reference Include="DevExpress.*">` 统一引用，不逐 DLL 写 HintPath。

---

## 常用控件精确配置

### 数据展示

| 控件 | 程序集 | 用途 | 必设属性 |
|------|--------|------|----------|
| GridControl + GridView | XtraGrid | 数据列表 | `gc.Dock=Fill`; `gc.MainView=gv`; `gv.GridControl=gc`; `gv.OptionsBehavior.Editable=false`; `gv.OptionsView.ShowAutoFilterRow=true` |
| BandedGridView | XtraGrid | 分组列表 | 继承 GridView 配置 + `Bands` 分组 |
| TreeList | XtraTreeList | 层级数据 | `OptionsBehavior.Editable=false`; `ParentFieldName`/`KeyFieldName` |
| PivotGridControl | XtraPivotGrid | 透视分析 | `Fields` 定义行/列/数据区 |
| VGridControl | XtraVerticalGrid | 属性编辑器/属性面板 | `DataSource`; `Rows` 定义字段; `LayoutMode`（Records/Banded/MultiRecords/Tree）|
| AccordionControl | XtraBars | 折叠导航菜单 | `Elements` 树形结构; `ElementClick` 事件; 支持 HTML 模板 |
| DirectXForm | XtraEditors | DirectX 硬件加速表单 | 继承 `DevExpress.XtraEditors.DirectXForm`; `HtmlTemplate` 属性 |
| ChartControl | XtraCharts | 图表 | `Diagram` + `Series` + `DataSource` |
| SchedulerControl | XtraScheduler | 日历/日程 | `Storage` + `Views` |

### 数据编辑

| 控件 | 程序集 | 用途 | 必设属性 |
|------|--------|------|----------|
| TextEdit | XtraEditors | 单行文本 | `Properties.MaxLength` |
| MemoEdit | XtraEditors | 多行文本 | `Properties.MaxLength`; `Properties.ScrollBars` |
| DateEdit | XtraEditors | 日期选择 | `Properties.Mask.EditMask="yyyy-MM-dd"`; `Properties.Mask.UseMaskAsDisplayFormat=true` |
| TimeEdit | XtraEditors | 时间选择 | `Properties.Mask.EditMask="HH:mm:ss"` |
| SpinEdit | XtraEditors | 数值输入 | `Properties.MaxValue`/`MinValue` |
| CalcEdit | XtraEditors | 计算器式输入 | `Properties.Mask.EditMask` |
| ComboBoxEdit | XtraEditors | 下拉单选 | `Properties.Items.Add()` |
| CheckedComboBoxEdit | XtraEditors | 多选下拉 | `Properties.Items` |
| LookUpEdit | XtraEditors | 查找下拉 | `Properties.DataSource`/`ValueMember`/`DisplayMember` |
| GridLookUpEdit | XtraEditors | 表格式下拉 | `Properties.Buttons` + `Properties.PopupView` |
| CheckEdit | XtraEditors | 复选框 | `Properties.Caption` |
| RadioGroup | XtraEditors | 单选组 | `Properties.Items.Add()` |
| ImageComboBoxEdit | XtraEditors | 图文下拉 | `Properties.Items.AddImageComboItem()` |
| SearchControl | XtraEditors | 搜索框 | `Properties.Client` = 绑定的 GridControl |

### 容器

| 控件 | 程序集 | 用途 | 必设属性 |
|------|--------|------|----------|
| LayoutControl | XtraLayout | 根容器/表单布局 | `Dock=Fill`; `OptionsItemText.TextToControlDistance=4`; `AutoSize=false` |
| PanelControl | XtraEditors | 面板容器 | `Height` 或 `Dock` |
| GroupControl | XtraEditors | 分组容器 | `Text` = 分组标题 |
| TabControl | XtraEditors | 选项卡 | `TabPages` |
| WizardControl | XtraWizard | 向导 | `WizardPages` |

### 菜单/导航

| 控件 | 程序集 | 用途 | 必设属性 |
|------|--------|------|----------|
| BarManager | XtraBars | 工具栏 | `Bar` + `BarButtonItem` |
| RibbonControl | XtraBars.Ribbon | Ribbon 菜单 | `Pages` + `PageGroups` |
| NavBarControl | XtraNavBar | 旧式侧边导航（兼容） | `Groups` + `Items` |
| AccordionControl | XtraBars | 现代折叠导航（新项目首选） | `Elements`; `ElementClick`; HTML 模板; 支持 FluentDesignForm 集成 |

---

## 21.2 版本特定行为

### 1. Skin 名称体系

21.2 皮肤名称使用**全称**，不使用旧版简称。完整列表见 `references/skin-theme.md`。

**核心皮肤（无需 BonusSkins）**：

| 皮肤名称 | 说明 |
|----------|------|
| `"Office 2019 Colorful"` | Office 2019 彩色（默认推荐） |
| `"Office 2019 Dark Gray"` | Office 2019 深灰 |
| `"Office 2019 Black"` | Office 2019 黑色 |
| `"Office 2019 White"` | Office 2019 白色（v21.2 新增） |
| `"Office 2016 Colorful"` | Office 2016 彩色 |
| `"Office 2016 White"` | Office 2016 白色 |
| `"Visual Studio 2019 Blue"` | VS 2019 蓝色 |
| `"Visual Studio 2019 Dark"` | VS 2019 深色 |
| `"Visual Studio 2019 Light"` | VS 2019 浅色（v21.2 新增） |
| `"Basic"` | 基础无装饰风格 |

**BonusSkins 皮肤（需先 `UserSkins.BonusSkins.Register()`）**：

| 皮肤名称 | 说明 |
|----------|------|
| `"DevExpress Dark"` | DevExpress 深色主题 |
| `"DevExpress Light"` | DevExpress 浅色主题 |
| `"DevExpress Dark 2"` | DevExpress 深色 2（v21.2 新增） |
| `"Metropolis"` | Metro 风格 |
| `"Metropolis Dark"` | Metro 深色风格（v21.2 新增） |

### 2. GridControl.DataSource 绑定

21.2 支持 `BindingSource` / `List<T>` / `DataTable` 作为数据源。优先 `BindingSource` 以便排序筛选：

```csharp
BindingSource bs = new BindingSource { DataSource = myList };
gcMain.DataSource = bs;
// 此时点击列头自动排序生效
```

### 3. RepositoryItem 生命周期

21.2 中 RepositoryItem 必须在 GridControl 创建后初始化，**不能在设计期静态创建**。必须在 `InitializeComponent` 末尾或运行时通过 `gcMain.RepositoryItems.Add()` 添加。

### 4. LayoutControl AutoSize

21.2 LayoutControl 默认 `AutoSize = true`，可能导致布局膨胀。**必须显式设为 `false`**：

```csharp
this.layoutControl1.AutoSize = false;
this.layoutControl1.Dock = DockStyle.Fill;
```

### 5. LookAndFeel 继承链

21.2 LookAndFeel 三级继承：`UserLookAndFeel.Default` → 窗体 `LookAndFeel` → 控件 `LookAndFeel`。子级不设则继承父级。

### 6. VistaDisplayMode（DateEdit）

21.2 DateEdit 推荐启用 Vista 显示模式：

```csharp
dateEdit.Properties.VistaDisplayMode = DevExpress.Utils.DefaultBoolean.True;
dateEdit.Properties.VistaEditTime = DevExpress.Utils.DefaultBoolean.False;
```

### 7. XtraMessageBox 替代 MessageBox

21.2 使用 `XtraMessageBox.Show()` 替代 `MessageBox.Show()` 以保持皮肤一致性。注意参数使用 DevExpress 枚举：

```csharp
XtraMessageBox.Show("文本", "标题", MessageBoxButtons.OK, DevExpress.Utils.ToolTipIcon.Info);
```

---

## 字段 → 控件精确映射

| Entity 字段类型 | DevExpress 控件 | 列编辑器 | 备注 |
|---------------|----------------|---------|------|
| string (短, ≤50) | TextEdit | GridColumn + TextEdit | `Properties.MaxLength` 对齐 DB 列长度 |
| string (长, >50) | MemoEdit | RepositoryItemMemoEdit | 多行编辑，`Properties.ScrollBars` |
| int / decimal | SpinEdit | GridColumn + 数字格式 | `DisplayFormat.FormatString="N2"`; `HAlignment=Far` |
| DateTime | DateEdit | RepositoryItemDateEdit | `Properties.Mask.EditMask="yyyy-MM-dd"` |
| bool | CheckEdit | RepositoryItemCheckEdit | `ValueChecked="TRUE"`; `ValueUnchecked="FALSE"` |
| 枚举 | ComboBoxEdit | RepositoryItemComboBox | `Items.Add(KeyValuePair<int,string>)` |
| 外键 | GridLookUpEdit | RepositoryItemGridLookUpEdit | `ValueMember` + `DisplayMember` + `PopupView` |
| GUID 主键 | — | GridColumn (Visible=false) | 不展示 |

---

## 21.2 不兼容组合（防编译通过但运行时崩溃）

以下组合**编译无错，但 21.2 运行时会崩溃或行为异常**，生成时必须避免：

| 不兼容组合 | 后果 | 正确写法 |
|-----------|------|---------|
| RepositoryItem 未注册到 `gc.RepositoryItems` | `ArgumentException` 或控件不显示 | 创建后 `gc.RepositoryItems.Add(item)`，且只 Add 一次 |
| `DateEdit` 未设 `VistaDisplayMode` | 日期格式回退到系统默认，跨机器显示不一致 | `Properties.VistaDisplayMode = DefaultBoolean.True` |
| `LayoutControl.AutoSize = true`（默认值） | 布局随内容膨胀，窗体拉伸失控 | **必须显式 `AutoSize = false`** |
| GridColumn `Visible = true` 绑定 `Guid` 主键 | 列头显示 `00000000-0000-...` 无意义 | `Visible = false` |
| `SpinEdit` 未设 `MinValue/MaxValue` | 输入极端值导致 DB 溢出 | 对齐 DB 列范围设置 |
| `LookUpEdit` 未设 `DataSource` | 下拉空白 | 设置 `DataSource` + `ValueMember` + `DisplayMember` |
| `GridView.OptionsBehavior.Editable = true` 且无 `ShowingEditor` 守卫 | 用户可直接编辑不应改的列 | `Editable = false`；需行内编辑时加 `ShowingEditor` 判断 |
| `TreeList` 仅设 `KeyFieldName` 未设 `ParentFieldName` | 节点全部平铺，无层级 | 两者同时设置 |
| `BindingSource` 未设 `DataSource` 类型 | 数据绑定静默失败 | 先 `DataSource = typeof(Entity)` 或先赋值 `List<T>` |
| `XtraMessageBox.Show` 用 `MessageBoxButtons` 代替 `DevExpress.Utils.ToolTipIcon` | 皮肤不一致 | 第 4 参数用 `DevExpress.Utils.ToolTipIcon` 枚举 |
| `gcMain.DataSource = list` 无 `BindingSource` 中介 | 排序/筛选/导航按钮失效 | 优先 `BindingSource` 中介 |
| `FormClosing` 中 `e.Cancel = true` 但未提示原因 | 用户困惑 | Cancel 时同步弹 `XtraMessageBox` 说明原因 |
| `SqlOperate.SqlExcuteNoQuery` 返回值未检查 | DB 与内存脱节 | `> 0` 判断后再同步内存 |
| `ListOperate.FillModel<T>` 传入空 DataTable | `NullReferenceException` | DAL 方法加 `if (dt == null || dt.Rows.Count == 0) return new List<T>();` |

---

## 输出文件精确规范

> 路径以 Step 0 参照窗体同级目录为准。UTF-8 无 BOM。

| 文件 | 精确内容要求 |
|------|-------------|
| `frm{业务名}.cs` | 窗体逻辑：`partial class`，实现 `I{业务名}View`，构造函数 `InitializeComponent()` + `new Presenter(this)`，事件挂载，`Load` 事件调 `_presenter.LoadData()` |
| `frm{业务名}.Designer.cs` | `partial class`，`InitializeComponent()` 方法，控件声明（字段），实例化/配置/装配/解初始化，**所有初始可见文字走 resx** |
| `I{业务名}View.cs` | `interface`，属性只有 `{ set; }`，每个数据集一个 `set` 属性，`Refresh*()` 方法，`ShowMessage/ShowError` |
| `{业务名}Presenter.cs` | 协调器：构造注入 View，调 Ser 后通知 View 刷新，**不处理异常**（冒泡到 View） |
| `{业务名}Ser.cs` | BLL：`_lst{Entity}` 内存缓存 + 业务校验，直连 DAL，先改 DB 再同步内存 |
| `{业务名}DAL.cs` | 数据访问：`SqlOperate+ListOperate` 或 ORM，由参照窗体决定。无独立 DAL 层时不生成此文件 |

> **Designer.cs 不手改**：布局变更通过 Visual Studio Designer 完成，或整体替换 InitializeComponent。所有初始可见文字（按钮文本等）走 resx，不在 InitializeComponent 里硬编码 `.Text`。
