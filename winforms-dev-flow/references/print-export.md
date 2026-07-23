# 打印与导出

> 加载时机：需要 GridControl / TreeList 打印或导出 Excel/CSV/PDF 时读取。

## GridControl 导出

### Excel（XLSX/XLS）

```csharp
// 导出 XLSX（推荐，.NET Framework 4.7.2 支持）
private void ExportToXlsx()
{
    SaveFileDialog dialog = new SaveFileDialog();
    dialog.Filter = "Excel 工作簿 (*.xlsx)|*.xlsx";
    dialog.FileName = "导出_" + DateTime.Now.ToString("yyyyMMddHHmmss");
    if (dialog.ShowDialog() == DialogResult.OK)
    {
        gcMain.ExportToXlsx(dialog.FileName);
        XtraMessageBox.Show("导出成功", "提示",
            MessageBoxButtons.OK, DevExpress.Utils.ToolTipIcon.Info);
    }
}

// 导出 XLS（旧格式）
private void ExportToXls()
{
    gcMain.ExportToXls("export.xls");
}

// 导出 CSV
private void ExportToCsv()
{
    gcMain.ExportToCsv("export.csv", new DevExpress.XtraPrinting.CsvExportOptions {
        Separator = ","
    });
}
```

### 导出选项

```csharp
// 自定义导出选项
var options = new DevExpress.XtraPrinting.XlsxExportOptions();
options.ExportMode = DevExpress.XtraPrinting.XlsxExportMode.SingleFile;  // 或 WYSIWYG
options.SheetName = "数据列表";
options.ShowGridLines = true;
options.TextExportMode = DevExpress.XtraPrinting.TextExportMode.Value;
gcMain.ExportToXlsx("export.xlsx", options);
```

### 项目风格导出（Upgrader）

```csharp
private GridUI _gridUI = new GridUI();

private void cmsExport_Click(object sender, EventArgs e)
{
    _gridUI.ExportExcel(gcMain, "导出文件名");
}

// TreeList 导出
private TreeListUI _tlUI = new TreeListUI();
_tlUI.ExportExcel(tlMain);
```

### CRS 风格导出

```csharp
private void cmsExport_Click(object sender, EventArgs e)
{
    gcMain.ExportDefault("导出文件名");
}

// TreeList 导出
private void cmsTreeExport_Click(object sender, EventArgs e)
{
    tlMain.ExportDefault("导出文件名");
}
```

## GridControl 打印

### 基础打印

```csharp
// 直接打印（默认打印机）
gvMain.Print();
```

### 带预览的打印

```csharp
private void PrintWithPreview()
{
    DevExpress.XtraPrinting.PrintingSystem ps = new DevExpress.XtraPrinting.PrintingSystem();
    DevExpress.XtraPrinting.PrintableComponentLink link = new DevExpress.XtraPrinting.PrintableComponentLink(ps);
    link.Component = gcMain;
    link.Landscape = true;  // 横向打印
    link.PaperKind = System.Drawing.Printing.PaperKind.A4;
    link.Margins = new System.Drawing.Printing.Margins(50, 50, 50, 50);

    // 页眉/页脚
    link.CreateDetailHeaderArea += (s, e) =>
    {
        e.HeaderAreaItems.Clear();
        e.HeaderAreaItems.Add(new DevExpress.XtraPrinting.PageInfoBrick {
            PageInfo = DevExpress.XtraPrinting.PageInfo.DateTime,
            Format = "导出时间: {0:yyyy-MM-dd HH:mm}",
            Alignment = DevExpress.XtraPrinting.BrickAlignment.Far
        });
    };

    link.CreateDocument();
    ps.PreviewFormEx.Show();  // 显示预览窗口
}
```

## TreeList 导出

```csharp
// 导出 Excel
private void ExportTreeList()
{
    SaveFileDialog dialog = new SaveFileDialog();
    dialog.Filter = "Excel 工作簿 (*.xlsx)|*.xlsx";
    if (dialog.ShowDialog() == DialogResult.OK)
    {
        tlMain.ExportToXlsx(dialog.FileName);
    }
}

// 导出 CSV
private void ExportTreeListCsv()
{
    tlMain.ExportToCsv("treelist.csv");
}
```

## 右键菜单导出

```csharp
// 在 GridControl 右键菜单中添加导出项
private void SetupExportMenu(ContextMenuStrip cms)
{
    ToolStripMenuItem exportItem = new ToolStripMenuItem("导出 Excel");
    exportItem.Click += (s, e) => ExportToXlsx();
    cms.Items.Add(exportItem);
}
```

## 性能注意事项

```csharp
// 大数据量导出前先 BeginUpdate
gcMain.BeginUpdate();
try
{
    // 导出操作
    gcMain.ExportToXlsx("export.xlsx");
}
finally
{
    gcMain.EndUpdate();
}
```
