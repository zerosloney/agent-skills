# BandedGridView 完整模式

> 由 SKILL.md Step 2 使用 BandedGridView 时按需加载。

## Band 定义与列分配

```csharp
using DevExpress.XtraGrid.Views.BandedGrid;
using DevExpress.XtraGrid.Columns;

// 1. 创建 Band
GridBand bandBasic = new GridBand();
bandBasic.Caption = "基本信息";
bandBasic.Name = "bandBasic";
bandBasic.AppearanceHeader.TextOptions.HAlignment = DevExpress.Utils.HorzAlignment.Center;
bandBasic.AppearanceHeader.TextOptions.VAlignment = DevExpress.Utils.VertAlignment.Center;
bandBasic.AppearanceHeader.Options.UseTextOptions = true;
bandBasic.OptionsBand.FixedWidth = true;
bandBasic.Fixed = FixedStyle.Left;  // 固定左侧

// 2. 添加 Band 到视图
bgvMain.Bands.Clear();
bgvMain.Bands.Add(bandBasic);

// 3. 创建 BandedGridColumn 并分配给 Band
var colNO = new BandedGridColumn
{
    Caption = "单号",
    FieldName = "NO",
    Name = "colNO",
    Visible = true,
    VisibleIndex = 0,
    Width = 120
};
bandBasic.Columns.Add(colNO);  // 将列添加到 Band
bgvMain.Columns.Add(colNO);    // 列也需要添加到 Columns 集合

// 4. 多级 Band 示例
GridBand bandDetail = new GridBand();
bandDetail.Caption = "明细信息";
bandDetail.Name = "bandDetail";
bgvMain.Bands.Add(bandDetail);

// 子 Band（嵌套）
GridBand subBandA = new GridBand();
subBandA.Caption = "材料信息";
subBandA.Name = "subBandA";
bandDetail.Children.Add(subBandA);  // 嵌套 Band

// 子 Band 的列
var colMaterialName = new BandedGridColumn
{
    Caption = "材料名称",
    FieldName = "MaterialName",
    Name = "colMaterialName",
    Visible = true,
    VisibleIndex = 3,
    Width = 150
};
subBandA.Columns.Add(colMaterialName);
bgvMain.Columns.Add(colMaterialName);
```

## 完整表单示例

```csharp
public partial class frm{业务名} : frmBase, I{业务名}View
{
    private DevExpress.XtraGrid.GridControl gcMain;
    private BandedGridView bgvMain;
    private BandedGridHitInfo _ghi;

    public frm{业务名}()
    {
        InitializeComponent();
        new GridStyle("ASS", this, gcMain, bgvMain);  // BandedGridView 也支持
        InitBands();
        BindEvents();
    }

    private void InitBands()
    {
        // 创建 Bands
        var bandBase = CreateBand("基本信息", 0, 120);
        var bandFlow = CreateBand("流程信息", 120, 140);
        bgvMain.Bands.AddRange(new GridBand[] { bandBase, bandFlow });

        // 添加列到 Band
        AddColumn("colNO",      "单号",      "NO",         0, 100, bandBase);
        AddColumn("colShipNo",  "船号",      "ShipNo",     1, 80,  bandBase);
        AddColumn("colStatus",  "状态",      "StatusName", 2, 80,  bandFlow);
        AddColumn("colCreator", "创建人",    "Creator",    3, 80,  bandFlow);
        AddColumn("colDate",    "创建日期",  "CreateDate", 4, 100, bandFlow);
    }

    private BandedGridColumn AddColumn(string name, string caption, string field,
        int index, int width, GridBand band)
    {
        var col = new BandedGridColumn
        {
            Name = name,
            Caption = caption,
            FieldName = field,
            Visible = true,
            VisibleIndex = index,
            Width = width
        };
        col.AppearanceHeader.TextOptions.HAlignment = DevExpress.Utils.HorzAlignment.Center;
        band.Columns.Add(col);
        bgvMain.Columns.Add(col);
        return col;
    }

    private void BindEvents()
    {
        bgvMain.RowCellStyle += bgvMain_RowCellStyle;
        bgvMain.CustomDrawRowIndicator += bgv_CustomDrawRowIndicator;
        bgvMain.MouseDown += bgvMain_MouseDown;
        bgvMain.MouseUp += bgvMain_MouseUp;
    }

    // BandedGridView 右键菜单
    private void bgvMain_MouseDown(object sender, MouseEventArgs e)
    {
        _ghi = bgvMain.CalcHitInfo(new Point(e.X, e.Y));
    }

    private void bgvMain_MouseUp(object sender, MouseEventArgs e)
    {
        // 同 GridView，但使用 BandedGridHitInfo
        if (!bgvMain.MenuControl(sender, e, _ghi)) return;
        // 控制菜单项...
        cms.Show(gcMain, e.X, e.Y);
    }
}
```

## CSSBandedGridView 扩展

Deve-Upgrader 使用 `CSSBandedGridView`（继承 `GridBandViewExtend`），自动配置默认行为并提供导入导出：

```csharp
// CSSBandedGridView 默认行为（自动在构造函数配置）:
this.OptionsBehavior.EditorShowMode = EditorShowMode.Click;
this.OptionsBehavior.ReadOnly = true;
this.OptionsPrint.AutoWidth = false;
this.OptionsView.ColumnAutoWidth = false;
this.OptionsView.ShowAutoFilterRow = true;
this.OptionsView.ShowGroupPanel = false;
this.CustomDrawRowIndicator += 行号绘制;
this.RowCountChanged += 行号宽度自适应;

// CSSBandedGridView.MenuControl(BandedGridHitInfo) 方法:
// 检查 band 面板点击:
if (_ghi.InBandPanel) return false;
// 其他判断同 GridView.MenuControl
```

## BandedGridView vs GridView 差异

| 方面 | GridView | BandedGridView |
|------|----------|----------------|
| 视图类型 | `GridView` / `CSSGridView` | `BandedGridView` / `CSSBandedGridView` |
| 列类型 | `GridColumn` | `BandedGridColumn` |
| 多级表头 | 不支持 | 通过 Bands + band.Columns.Add(col) |
| 嵌套 Band | 不支持 | bandDetail.Children.Add(subBand) |
| HitTest | `GridHitInfo` | `BandedGridHitInfo`（多了 `InBandPanel`） |
| 数据绑定 | `gc.DataSource = dt` | 完全相同 |
| GridStyle | `new GridStyle("ASS", this, gc, gv)` | `new GridStyle("ASS", this, gc, bgv)` |
| 导出 | GridUI.ExportExcel(gc, name) | 完全相同 |
| 行号 | gv.CustomDrawRowIndicator | 完全相同 |
| 状态颜色 | gv.RowCellStyle | 完全相同 |
