# 特殊功能代码模板

> 本文件由 SKILL.md Step 4 按需加载。仅在用户要求对应高级功能时读取；不要全量加载，按下表定位章节。

## 需求关键词 → 章节速查(优先用这张表)

> 用户提到下列关键词或要实现对应功能时,只读对应章节,不读全文件。

| 用户需求 / 关键词 | 章节 |
|------------------|------|
| "状态颜色" / "按状态变色" / "审批通过的行高亮" | §1 |
| "右键菜单" / "ContextMenuStrip" / "右键增删改" | §2(Upgrader) / §6(CRS) / §7(空数据保护) |
| "分页" / "下一页" / "每页 50 条" | §3 |
| "导出 Excel" / "导出" / "cmsExport" | §4（或见 `references/print-export.md`） |
| "深拷贝" / "DeepClone" / "编辑时不影响原数据" | §5 |
| "权限菜单" / "AddControlItemGroupConfig" / "按钮权限" | §6(CRS 专用) |
| "行号" / "序号列" / "CustomDrawRowIndicator" | §8 |
| "校验" / "必填" / "验证输入" / "保存前检查" | §9 / §16 |
| "拖拽" / "拖动节点" / "TreeList DragDrop" | §10（或见 `references/treelist-advanced.md`） |
| "多选下拉" / "GridLookUpEdit 勾选" / "GridCheckMarksSelection" | §11 |
| "等待窗体" / "WaitDialog" / "varlist_Dialog" | §12 |
| "报表" / "打印" / "ReportDesign" / "ShowReportView" | §13 |
| "CSS.DAL" / "DALBase<T>" / "CSS 子模式 ORM" | §14 |
| "日期列" / "下拉列" / "勾选列" / "RepositoryItem" | §15 / §1.4(designer-patterns) |
| "级联填充" / "CellValueChanging" / "选 A 自动填 B" | §16 |
| "下拉树" / "TreeListLookUpEdit" | §17 |
| "左右分栏" / "SplitContainer" / "DockPanel 浮动面板" | §18 / §1.2 §1.5(designer-patterns) |
| "多 Tab" / "标签页" / "基本信息+明细" / "XtraTabControl" | §19 / §1.6(designer-patterns) |
| "条件格式" / "StyleFormatCondition" / "RowCellStyle" | `references/gridview-advanced.md` |
| "汇总" / "统计" / "合计" / "Count/Sum" | `references/gridview-advanced.md` |
| "排序" / "多列排序" / "AllowSort" | `references/gridview-advanced.md` |
| "筛选" / "过滤" / "ActiveFilterString" | `references/gridview-advanced.md` |
| "TreeList 拖拽" / "节点移动" / "主从联动" | `references/treelist-advanced.md` |
| "编辑器配置" / "DateEdit" / "LookUpEdit" / "SpinEdit" | `references/editors-reference.md` |
| "Table Layout" / "网格布局" / "LayoutControl 分组" | `references/layout-advanced.md` |
| "打印" / "导出 Excel" / "ExportToXlsx" | `references/print-export.md` |
| "HTML 模板" / "TileView" / "CardView HTML" / "WinExplorer HTML" | §20 |
| "VGrid" / "垂直网格" / "属性面板" | §21 |
| "Accordion" / "手风琴" / "折叠菜单" | §22 |
| "DirectX" / "DirectXForm" / "硬件加速表单" | §23 |

## 章节索引(按编号)

| 功能 | 章节 |
|------|------|
| 状态颜色渲染 | §1 |
| 右键菜单 | §2 |
| 分页加载 | §3 |
| 导出 Excel | §4 |
| 深拷贝 | §5 |
| CRS 权限菜单 | §6 |
| GridControl 右键菜单空数据保护 | §7 |
| 行号显示 | §8 |
| 验证输入 | §9 |
| TreeList 拖拽 / 主从联动 / 展开菜单 | §10 |
| GridLookUpEdit 多选 | §11 |
| varlist_Dialog | §12 |
| 报表打印 | §13 |
| CSS 子模式 DALBase<T> | §14 |
| RepositoryItem 自定义编辑器 | §15 |
| Grid / TreeList 联动验证 | §16 |
| TreeListLookUpEdit 下拉树 | §17 |
| SplitContainer + DockPanel 布局 | §18 |
| XtraTabControl 多标签页 | §19 |
| HTML & CSS 模板（v21.2） | §20 |
| VGridControl 垂直网格 | §21 |
| Accordion Control 手风琴导航 | §22 |
| DirectX Form（v22.1） | §23 |

## 1. 状态颜色渲染

### TreeList 版本

```csharp
private void tlMain_CustomDrawNodeCell(object sender, CustomDrawNodeCellEventArgs e)
{
    if (e.Node == null) return;
    var view = tlMain.GetDataRecordByNode(e.Node) as TreeNodeView;
    if (view == null) return;

    if (view.Status == (int)OrderStatus.Submitted)
        e.Appearance.BackColor = Color.Pink;
    else if (view.Status == (int)OrderStatus.Approved)
        e.Appearance.BackColor = Color.LightGreen;
    else if (view.Status == (int)OrderStatus.Rejected)
        e.Appearance.BackColor = Color.Red;
}
```

### GridView 版本（RowCellStyle 事件，推荐）

```csharp
private void gvMain_RowCellStyle(object sender, RowCellStyleEventArgs e)
{
    var row = gvMain.GetRow(e.RowHandle) as OrderInfo;
    if (row == null) return;

    if (row.Status == 1)
        e.Appearance.BackColor = Color.Pink;
    else if (row.Status == 2)
        e.Appearance.BackColor = Color.LightGreen;
    else if (row.Status == 3)
        e.Appearance.BackColor = Color.Red;
}
```

## 2. 右键菜单（ContextMenuStrip）

### Deve-Upgrader 模式

菜单在 Designer.cs 中声明，通过 `MouseDown+MouseUp` 控制：

```csharp
// Designer.cs 中的菜单项声明
private System.Windows.Forms.ToolStripMenuItem cmsAdd;
private System.Windows.Forms.ToolStripMenuItem cmsUpdate;
private System.Windows.Forms.ToolStripMenuItem cmsDelete;
private System.Windows.Forms.ToolStripMenuItem cmsRefresh;
private System.Windows.Forms.ToolStripMenuItem cmsExport;

// 窗体代码中的事件处理
private GridHitInfo _ghi;

private void gv_MouseDown(object sender, MouseEventArgs e)
{
    _ghi = gv.CalcHitInfo(new Point(e.X, e.Y));
}

private void gv_MouseUp(object sender, MouseEventArgs e)
{
    if (!gv.MenuControl(sender, e, _ghi)) return;
    cmsDelete.Enabled = gv.GetRow(_ghi.RowHandle) as EntityX != null;
    cmsUpdate.Enabled = gv.GetRow(_ghi.RowHandle) as EntityX != null;
    cms.Show(gc, e.X, e.Y);
}
```

### Deve-CRS 模式

CRS 使用 `AddControlItemGroupConfig` 注册权限菜单，详见第 6 节。

## 3. 分页加载

```csharp
private int _pageSize = 50;
private int _pageIndex = 1;
private int _totalCount = 0;

private void LoadData()
{
    var result = _ser.GetPagedData(_pageSize, _pageIndex, BuildCondition());
    _totalCount = result.TotalCount;
    _view.DataList = result.DataList;
    UpdatePagerInfo();
}

private void btnPrev_Click(object sender, EventArgs e)
{
    if (_pageIndex > 1) { _pageIndex--; LoadData(); }
}

private void btnNext_Click(object sender, EventArgs e)
{
    int totalPages = (int)Math.Ceiling(_totalCount / (double)_pageSize);
    if (_pageIndex < totalPages) { _pageIndex++; LoadData(); }
}
```

## 4. 导出 Excel

### Deve-Upgrader

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

### Deve-CRS

```csharp
// ExportDefault 扩展方法（弹出保存对话框）
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

## 5. 深拷贝（DeepClone）

防止直接修改数据源中的对象，创建独立副本后编辑：

```csharp
using Jamtc.Common.Extend;

// 在编辑对话框中使用
var clonedEntity = Jamtc.Common.Extend.EntityExtend.DeepClone(originalEntity) as OrderInfo;
// 用户在对话框中修改 clonedEntity，确认后才同步回数据源
```

## 6. AddControlItemGroupConfig 权限菜单（仅 CRS）

在 `frm_Base` 子类构造函数中注册：

```csharp
// 右键菜单绑定到 GridControl
AddControlItemGroupConfig(new ControlItemGroupConfig("默认菜单", cms, gcProjectInfo));

// 右键菜单绑定到 TreeList
AddControlItemGroupConfig(new ControlItemGroupConfig("班组菜单", cms_WorkGroup, tl_WorkGroup));

// 按钮绑定
AddControlItemGroupConfig(new ControlItemGroupConfig("操作功能", btnRefresh));
AddControlItemGroupConfig(new ControlItemGroupConfig("操作功能", btnInsert));
AddControlItemGroupConfig(new ControlItemGroupConfig("操作功能", btnUpdate));
AddControlItemGroupConfig(new ControlItemGroupConfig("操作功能", btnDelete));
```

## 7. GridControl 右键菜单空数据保护

```csharp
// Deve-Upgrader 中 GridControl 的 MenuControlExceptDataSource 拓展
private void gv_MouseUp(object sender, MouseEventArgs e)
{
    if (!GridControlExtendMethods.MenuControlExceptDataSource(e, _ghi, gvMain))
        return;
    // 控制菜单项状态...
}

// Deve-CRS 中 GridControl 的自定义右键（不使用 AddControlItemGroupConfig 时）
private void gv_MouseUp(object sender, MouseEventArgs e)
{
    if (e.Button != MouseButtons.Right) return;
    var hitInfo = gv.CalcHitInfo(new Point(e.X, e.Y));
    if (hitInfo == null || hitInfo.InRowCell == false) return;

    var row = gv.GetRow(hitInfo.RowHandle) as EntityX;
    cmsUpdate.Enabled = row != null;
    cms.Show(gc, e.X, e.Y);
}
```

## 8. 行号显示

```csharp
private void gv_CustomDrawRowIndicator(object sender, RowIndicatorCustomDrawEventArgs e)
{
    if (e.RowHandle < 0) return;
    e.Info.DisplayText = (gv.GetVisibleIndex(e.RowHandle) + 1).ToString();
}
```

## 9. 验证输入

输入校验：按参照窗体的校验风格实现，常见为 `string.IsNullOrEmpty` 检查 + 消息提示。

## 10. TreeList 拖拽功能（完整模式）

### 标准拖放（节点类型验证 + DB 同步）

```csharp
private TreeListHitInfo _tlHitInfo;
private bool _dragInner = false;

private void tlMain_MouseDown(object sender, MouseEventArgs e)
{
    _tlHitInfo = tlMain.CalcHitInfo(new Point(e.X, e.Y));
}

private void tlMain_MouseMove(object sender, MouseEventArgs e)
{
    if (e.Button != MouseButtons.Left) return;
    if (tlMain.Selection.Count < 1) return;
    if (_tlHitInfo.HitInfoType != HitInfoType.Cell) return;

    // 验证：仅允许特定类型的节点拖动
    foreach (TreeListNode tn in tlMain.Selection)
    {
        var row = (tlMain.GetDataRecordByNode(tn) as DataRowView)?.Row;
        if (row["Type"].ToString() != "可拖动类型")
            return;
    }
    _dragInner = true;
    tlMain.DoDragDrop(tlMain.Selection, DragDropEffects.Move);
}

private void tlMain_DragEnter(object sender, DragEventArgs e)
{
    e.Effect = DragDropEffects.Move;
}

private void tlMain_DragDrop(object sender, DragEventArgs e)
{
    TreeListHitInfo HI = tlMain.CalcHitInfo(
        tlMain.PointToClient(new Point(e.X, e.Y)));
    TreeListNode targetNode = HI.Node;
    if (targetNode == null) return;

    foreach (TreeListNode tn in tlMain.Selection)
    {
        // 验证目标类型
        var targetRow = GetNodeRow(tlMain, targetNode);
        if (targetNode != tn.ParentNode
            && targetRow["Type"].ToString() != "禁止目标类型")
        {
            // 1. 更新数据库
            string sql = $"UPDATE TableName SET ParentID='{targetRow["ID"]}' WHERE ID='{GetNodeRow(tlMain,tn)["ID"]}'";
            _so.SqlExcuteNoQuery(sql, varlist.ASSConn);
            // 2. 移动节点
            tlMain.MoveNode(tn, targetNode);
        }
    }
}

// TreeList GetDataRecordByNode 辅助
private DataRow GetNodeRow(TreeList tl, TreeListNode node)
{
    return ((DataRowView)tl.GetDataRecordByNode(node)).Row;
}
```

### TreeList FocusedNodeChanged（主从联动）

```csharp
private void tlMain_FocusedNodeChanged(object sender, FocusedNodeChangedEventArgs e)
{
    // 排除筛选行
    if (e.Node is TreeListAutoFilterNode || e.Node == null) return;

    var row = GetNodeRow(tlMain, e.Node);
    string nodeType = row["NodeType"].ToString();
    string imageIndex = row["ImageIndex"].ToString();

    if (nodeType == "业务类型A" && imageIndex == ((int)ImageIndex.TypeA).ToString())
    {
        _presenter.LoadDetail(row["ID"].ToString());
    }
    else
    {
        gcDetail.DataSource = null;
    }
}
```

### TreeList 展开/收缩菜单

```csharp
// CSSTreeList 扩展方法，自动生成 "展开" | "收缩" | "全部展开" | "全部收缩" 四项菜单
tlMain.InitExpandAndCollapse(cms);
// 手动：tlMain.ExpandAll() / tlMain.CollapseAll()
```

## 11. GridLookUpEdit 多选

用于 GridLookUpEdit 的下拉列表多选场景。

> ⚠️ `GridCheckMarksSelection` 是**自定义包装类**（非 DevExpress 内置），多个博客有完整源码。其核心原理：给下拉 View 注入一列复选框 + 监听 `SelectionChanged`。如果项目已有该类直接用；没有则用下面的原生 API 写法。

### 方式一：原生 API（推荐）

```csharp
// 初始化
cboField.Properties.DataSource = dataSource;
cboField.Properties.ValueMember = "ID";
cboField.Properties.DisplayMember = "Name";
cboField.Properties.View.OptionsSelection.MultiSelect = true;
cboField.Properties.View.OptionsSelection.MultiSelectMode = MultiSelectMode.RowSelect;

// 监听选中变更
cboField.Properties.View.SelectedRowsChanged += (s, e) =>
{
    _selectedItems.Clear();
    foreach (int rowHandle in cboField.Properties.View.GetSelectedRows())
        _selectedItems.Add(cboField.Properties.View.GetRow(rowHandle));
};

// 自定义显示文本
cboField.CustomDisplayText += (sender, e) =>
{
    e.DisplayText = string.Join(", ", _selectedItems.Select(x => x.Name));
};
```

### 方式二：GridCheckMarksSelection（项目已有此类时用）

```csharp
private GridCheckMarksSelection _gridCheckMarksSA;

_gridCheckMarksSA = new GridCheckMarksSelection(cboField.Properties);
_gridCheckMarksSA.SelectionChanged += gridCheckMarks_SelectionChanged;
cboField.Properties.Tag = _gridCheckMarksSA;

// 选中项变更
private void gridCheckMarks_SelectionChanged(object sender, EventArgs e)
{
    _selectedItems.Clear();
    foreach (var item in _gridCheckMarksSA.Selection)
        _selectedItems.Add(item);
}
```

## 12. varlist_Dialog

varlist_Dialog 调用方式见各 UI 模板（`upgrader-ui.md` / `crs-ui.md`）。

## 13. 报表打印（ReportDesign）

通过 `Jamtc.ReportDesign.ReportDesignConfigSer.ShowReportView()` 调用：

```csharp
using Jamtc.ReportDesign;

// 有参数的报表
Dictionary<string, object> dicParams = new Dictionary<string, object>();
dicParams.Add("参数名", 参数值);
ReportDesignConfigSer.ShowReportView("报表编码", dicParams, dataSourceList);

// 无参数的报表
ReportDesignConfigSer.ShowReportView("报表编码", null, dataSourceList);

// XtraReport 对象方式
XtraReport report = new XtraReport_ReportName();
report.CreateDocument();
ReportDesignConfigSer.ShowReportView(report, false);
```

报表编码如 `"YQTDJ"`、`"GCXLD(ACL)ZBB"` 等由项目预定义。

## 14. CSS 子模式 DALBase<T>（Deve-Upgrader CSS 分支）

当目标使用 `CSS.DAL/` + `CSS.BLL/` 目录时，用 ORM 而非 SqlOperate：

```csharp
using CSS.DAL.Utils;

public class DAL{业务名} : DALBase<{实体类}>
{
    public List<{实体类}> QueryByProject(string id)
    {
        return DbHelp.Query<{实体类}>()
            .Where(n => n.ProjectInfoID == id)
            .ToList();
    }
}

// Ser 层
public class {业务名}Ser
{
    private DAL{业务名} _dal = new DAL{业务名}();
    public List<{实体类}> GetData(string id)
    {
        return _dal.QueryByProject(id);
    }
}
```

`DALBase<T>` 支持事务感知、多数据库切换（`DBConnectType`）、自动 Bulk 插入（>50 条）。

## 15. RepositoryItem 自定义编辑器

在 Designer 中声明 RepositoryItem，通过 `ColumnEdit` 绑定到列：

```csharp
// Designer 声明
this.repositoryItemDateEdit1 = new RepositoryItemDateEdit();
this.repositoryItemComboBox1 = new RepositoryItemComboBox();
this.repositoryItemHyperLinkEdit1 = new RepositoryItemHyperLinkEdit();
this.repositoryItemCheckEdit1 = new RepositoryItemCheckEdit();

// GridControl 注册（Designer）
this.gcMain.RepositoryItems.AddRange(new RepositoryItem[] {
    this.repositoryItemDateEdit1,
    this.repositoryItemHyperLinkEdit1
});

// 列绑定
bandedGridColumn24.ColumnEdit = this.repositoryItemHyperLinkEdit1;
colCreateDate.ColumnEdit = this.repositoryItemDateEdit1;

// RepositoryItemDateEdit 配置
this.repositoryItemDateEdit1.Buttons.AddRange(new EditorButton[] {
    new EditorButton(ButtonPredefines.Combo)
});
this.repositoryItemDateEdit1.Mask.EditMask = "yyyy-MM-dd";

// RepositoryItemCheckEdit 配置（布尔列）
repositoryItemCheckEdit1.ValueChecked = "TRUE";
repositoryItemCheckEdit1.ValueUnchecked = "FALSE";
repositoryItemCheckEdit1.AllowGrayed = false;
```

同一个 RepositoryItem 可绑定多个列（共享实例）。

## 16. Grid 联动验证（CellValueChanging + ValidatingEditor）

> 陷阱：`ShownEditor` 和 `EditValueChanging` 在某些场景会冲突，见 `references/common-pitfalls.md` § 15。

### 官方标准级联查找 API（两种方式）

#### 方式一：Grid 内嵌 LookUpEdit（ShownEditor 拦截）

适用于 GridView 内嵌的下拉列。官方文档源码（`docs.devexpress.com/WindowsForms/116018/`）：

```csharp
// 在 ShownEditor 事件中拦截，动态修改下拉数据源
private void gridView1_ShownEditor(object sender, EventArgs e)
{
    if (gridView1.FocusedColumn.FieldName == "ProductID")
    {
        var lookup = gridView1.ActiveEditor as LookUpEdit;
        if (lookup == null) return;

        // 取当前行的 CategoryID 作为过滤条件
        int categoryId = Convert.ToInt32(gridView1.GetFocusedRowCellValue("CategoryID"));
        lookup.Properties.DataSource = Product.GetProductsByCategory(categoryId);
    }
}
```

> 注意：此方式在每次进入编辑状态时重新过滤下拉数据。适合 Grid 内嵌的 RepositoryItemLookUpEdit 列。

#### 方式二：Standalone LookUpEdit（CascadingOwner 属性）

适用于表单上独立的两个 LookUpEdit 控件。官方文档源码：

```csharp
// 设置父级下拉
lookupCategory.Properties.DataSource = Category.Init();
lookupCategory.Properties.DisplayMember = "CategoryName";
lookupCategory.Properties.ValueMember = "CategoryID";

// 设置子级下拉，指定 CascadingOwner
lookupProduct.Properties.DataSource = Product.Init();
lookupProduct.Properties.DisplayMember = "Name";
lookupProduct.Properties.ValueMember = "ProductID";
lookupProduct.CascadingOwner = lookupCategory;  // ← 官方标准写法

// 父级变化时清空子级选择
private void lookupCategory_EditValueChanged(object sender, EventArgs e)
{
    lookupProduct.EditValue = null;
}
```

> `CascadingOwner` 是 DevExpress **21.1+** 内置属性，自动在父级值变化时过滤子级数据源。仅适用于 Standalone LookUpEdit 控件，不适用于 Grid 内嵌列。

### 旧版 CellValueChanging 方式（项目内仍可用）

选择下拉项后自动填充关联字段：

```csharp
private void gvDetail_CellValueChanging(object sender, CellValueChangedEventArgs e)
{
    var entity = gvDetail.GetRow(e.RowHandle) as EntityClass;
    if (entity == null) return;

    if (e.Column == colLookupField)
    {
        var lookupItem = _lookupList.FirstOrDefault(n => n.ID == (Guid)e.Value);
        if (lookupItem == null) return;

        entity.DpCName = lookupItem.DpCName;
        entity.WBSName = lookupItem.WBSName;
        entity.OrgID = lookupItem.OrgID;
        gvDetail.RefreshData();
    }
}
```

### TreeList 列校验（ValidatingEditor）

```csharp
private void tlMain_ValidatingEditor(object sender, BaseContainerValidateEditorEventArgs e)
{
    if (tlMain.FocusedColumn.FieldName == "UnitPrice")
    {
        if (string.IsNullOrWhiteSpace(Convert.ToString(e.Value)))
            e.Value = 0m;  // 空值默认 0
    }
}
```

### 保存前全量校验（ok() 方法中）

重写 `ok()` 方法，遍历明细列表做必填项/数值范围校验，失败时调用 `UICommonBase.ShowMessageBox(MessageType.Warming, "...")` 并返回 `false`。

## 17. TreeListLookUpEdit 下拉树

> 官方 API：`TreeListLookUpEdit.Properties.TreeList` 返回标准 `TreeList` 实例。**不是** `TreeListExtend`（那是项目自定义类）。

```csharp
// 声明
private TreeListLookUpEdit tllueDepartment;

// === Designer 初始化 ===
// TreeListLookUpEdit 自动创建内部 TreeList，访问 Properties.TreeList 操作列
this.tllueDepartment = new TreeListLookUpEdit();
this.tllueDepartment.Properties.Buttons.AddRange(new EditorButton[] {
    new EditorButton(ButtonPredefines.Combo)
});
this.tllueDepartment.Properties.DisplayMember = "Name";
this.tllueDepartment.Properties.ValueMember = "ID";
this.tllueDepartment.Properties.NullText = "";

// 内部 TreeList 列配置（通过 Properties.TreeList）
var tl = this.tllueDepartment.Properties.TreeList;
tl.Columns.Clear();
tl.Columns.Add(new TreeListColumn { Caption = "名称", FieldName = "Name", Visible = true });
tl.Columns.Add(new TreeListColumn { Caption = "编码", FieldName = "Code", Visible = false });
tl.KeyFieldName = "ID";
tl.ParentFieldName = "ParentID";
tl.OptionsView.ShowIndicator = false;
tl.OptionsView.ShowAutoFilterRow = true;
tl.OptionsFilter.FilterMode = FilterMode.EntireBranch; // 整支过滤

// === 运行时绑定 ===
tllueDepartment.Properties.DataSource = treeDataSource;
tllueDepartment.Properties.TreeList.ExpandAll();

// === 取值 ===
// 单选：tllueDepartment.EditValue 返回 ID
// 多选（带 CheckBox）：tl.Nodes遍历，手动判断 CheckState != CheckState.Unchecked

// === 自定义显示文本（多选时）===
tllueDepartment.Properties.CustomDisplayText += (sender, e) =>
{
    // 拼接已选节点名称
    e.DisplayText = GetCheckedNodeNames(tllueDepartment.Properties.TreeList);
};
```

## 18. SplitContainer + DockPanel 布局

### 标准 TreeList + Splitter + GridControl

```
LayoutControl (Dock.Fill)
├── splitContainerControl1 (Vertical)
│   Panel1: tlMain (TreeList)
│   Panel2: gcDetail (GridControl)
```

```csharp
// Designer
this.splitContainerControl1 = new SplitContainerControl();
this.splitContainerControl1.Dock = DockStyle.Fill;
this.splitContainerControl1.SplitterPosition = 300;
this.splitContainerControl1.Panel1.Controls.Add(this.tlMain);
this.splitContainerControl1.Panel2.Controls.Add(this.gcDetail);
```

### DockManager + DockPanel 右侧面板

```csharp
// Designer
this.dmDisplay = new DockManager(this.components);
this.dmDisplay.Form = this;

this.dpDisplay = new DockPanel();
this.dpDisplay.Dock = DockingStyle.Right;
this.dpDisplay.Options.FloatOnDblClick = false;
this.dpDisplay.Options.ShowCloseButton = false;
this.dpDisplay.Text = "预览面板";

this.dmDisplay.RootPanels.AddRange(new DockPanel[] { this.dpDisplay });
this.dockPanel1_Container.Controls.Add(this.previewControl);
```

## 19. XtraTabControl 多标签页

每个标签页包含独立的 TreeList 或 GridControl：

```csharp
// Designer
this.xtraTabControl1 = new XtraTabControl();
this.xtraTabPage1 = new XtraTabPage();  // Text = "船体"
this.xtraTabPage2 = new XtraTabPage();  // Text = "舾装"

this.xtraTabControl1.TabPages.AddRange(new XtraTabPage[] {
    this.xtraTabPage1, this.xtraTabPage2
});

// 每个 TabPage 承载独立控件
this.xtraTabPage1.Controls.Add(this.tlHullData);
this.xtraTabPage2.Controls.Add(this.tlOutfitData);

// 标签切换事件
this.xtraTabControl1.SelectedPageChanged += TabControl_SelectedPageChanged;

// 运行时检测当前标签
if (xtraTabControl1.SelectedTabPage.Text.Contains("船体"))
    LoadHullData();
```

### 分步加载模式（避免首屏卡顿）

```csharp
private void frm_Load(object sender, EventArgs e)
{
    xtraTabControl1.SelectedTabPage = xtraTabPage3;  // 先切到最后页
    LoadTab3Data();

    xtraTabControl1.SelectedTabPage = xtraTabPage2;  // 加载第二页
    LoadTab2Data();

    xtraTabControl1.SelectedTabPage = xtraTabPage1;  // 最后切回首屏
    LoadTab1Data();
}
```


## 20. HTML & CSS 模板（v21.2+ Grid 视图）

> 适用版本：DevExpress v21.2+。需引用 `DevExpress.XtraGrid.v21.2.dll`。以下源码整理自官方文档 `docs.devexpress.com/WindowsForms/119961/` 和官方博客（evget.com v21.2 新特性）。

HTML/CSS 模板让 Grid 的 TileView、CardView、WinExplorerView 支持 Web 风格的卡片渲染，无需 CustomDraw 手动绘制。

### 20.1 TileView HTML 磁贴模板

TileView 支持 `TileHtmlTemplate`（单一模板）或 `TileHtmlTemplates` 集合（多模板 + `QueryItemTemplate` 事件切换）。

```csharp
// 1. 声明模板（HTML + CSS）
string tileHtmlTemplate = @"
<div class='tile'>
  <div class='title'>${Name}</div>
  <div class='subtitle'>${Category}</div>
  <div class='price'>¥${Price}</div>
  <div class='badge'>${Status}</div>
</div>";

// 2. 分配给 TileView
tileView1.TileHtmlTemplate = tileHtmlTemplate;

// 3. 可选：多模板时处理切换事件
tileView1.QueryItemTemplate += (sender, e) =>
{
    var data = tileView1.GetRow(e.RowHandle) as Product;
    if (data == null) return;
    e.TemplateId = data.IsFeatured ? "featured" : "normal";
};

// 4. 可选：响应 HTML 元素点击事件（交互元素）
tileView1.ElementMouseClick += (s, e) =>
{
    if (e.ElementId == "btnDetails")
        ShowProductDetail(e.RowHandle);
};
```

> CSS 示例（支持阴影、圆角等 Web 效果）：
> ```css
> .tile { width: 200px; background: white; border-radius: 8px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); padding: 12px; }
> .title { font-weight: bold; font-size: 14px; margin-bottom: 4px; }
> .price { color: #e74c3c; font-size: 16px; font-weight: bold; }
> .badge { background: #3498db; color: white; border-radius: 4px; padding: 2px 6px; font-size: 11px; }
> ```

### 20.2 CardView 命名占位符（替代索引占位符）

v21.2 新增：CardCaptionFormat 支持字段名替代列索引 `{0}`、`{1}`。

```csharp
// 旧写法（v21.1 及之前，按列索引引用）
cardView1.CardCaptionFormat = "Record # {0}, {1}";

// v21.2+ 新写法（用字段名，更稳定）
cardView1.CardCaptionFormat = "Record # {0}, {Name}";

// RecordHeaderFormat 同理
cardView1.RecordHeaderFormat = "{0} - {EmployeeName}";
```

### 20.3 WinExplorerView HTML 模板

WinExplorerView（文件浏览器视图）支持 `HtmlTemplates` 集合 + `QueryItemTemplate` 事件：

```csharp
// 每个视图样式（大图标/图块/详细信息）可单独设置模板
winExplorerView1.Style = WinExplorerViewStyle.Tile;
winExplorerView1.StyleOptions.HtmlTemplate = tileHtmlTemplate;  // 大图标模板
winExplorerView1.StyleOptions = WinExplorerViewStyleOptions.Large; // 切到大图标

// 动态模板
winExplorerView1.HtmlTemplates.Add(new HtmlTemplate { Id = "custom", Content = myTemplate });
winExplorerView1.QueryItemTemplate += (s, e) =>
{
    var item = winExplorerView1.GetRow(e.RowHandle) as MyItem;
    e.TemplateId = item.IsHighlighted ? "custom" : null;  // null = 使用默认
};
```

### 20.4 数据绑定语法

模板中引用数据字段用 `${FieldName}` 占位符（区分大小写）：

```html
<input class="input" name="emailEdit" value='${Email}'/>
<div class="text">${FullName} ({Ticker}) 涨跌 ${Direction} ${Percentage}%。当前价格 ${Price}.</div>
```

> 绑定枚举值：`${Direction}` 配合 `AlertControl.BeforeFormShow` 事件中 `e.HtmlPopup.DataContext = myDataObject`。

### 20.5 CustomDraw~/DrawHTML() 降级方案

并非所有控件都原生支持 HTML 模板，但所有 `CustomDraw~` 事件都带 `DrawHtml()` 方法：

```csharp
// 在 CustomDrawEmptyForeground 中绘制 HTML 背景（ListBox 等空状态）
private void listBox_CustomDrawEmptyForeground(object sender, CustomDrawEventArgs e)
{
    var htmlTemplate = new HtmlTemplate(myHtml, myCss);
    var ctx = new DxHtmlPainterContext();
    e.DrawHtml(htmlTemplate, ctx);
}

// 处理鼠标悬停/点击（需额外绑定 MouseMove/MouseDown）
listBox.MouseMove += (s, e) =>
{
    if (listBox.ItemCount == 0)
    {
        ctx.OnMouseMove(e);
        listBox.Cursor = ctx.GetCursor(e.Location);
        listBox.Invalidate();
    }
};
```

### 20.6 已知限制（官方明确）

- **不要**创建超过 2 层嵌套的 flex 布局（性能问题）
- **不要**使用 CSS 动画（不支持）
- **不要**在 HTML 元素上直接修改逻辑 → 改用 `ElementId` + 事件处理
- **不要**直接拿外部 HTML/CSS 来用（可能包含不支持的标签/属性）
- **不要**在 `CustomDraw~` 事件中修改 HTML 元素结构

## 21. VGridControl（垂直网格）

> 程序集：`DevExpress.XtraVerticalGrid.v21.2.dll`，命名空间：`DevExpress.XtraVerticalGrid`。

VGridControl 将数据旋转 90° 显示（记录为列，字段为行），适合属性面板式编辑或单条记录详情展示。官方文档：`docs.devexpress.com/WindowsForms/116578/`。

### 21.1 四种布局模式

```csharp
VGridControl vGrid = new VGridControl();
vGrid.Dock = DockStyle.Fill;

// 1. 单记录布局（默认，PropertyGrid 风格）
vGrid.LayoutMode = DevExpress.XtraVerticalGrid.LayoutMode.Records;
// 每条记录一行，字段垂直排列

// 2. 分带布局（Banded）
vGrid.LayoutMode = DevExpress.XtraVerticalGrid.LayoutMode.Banded;
// 一个记录跨多列显示

// 3. 多记录布局（反向网格）
vGrid.LayoutMode = DevExpress.XtraVerticalGrid.LayoutMode.MultiRecords;
// 多个记录从左到右排列

// 4. 树形模式（分组可折叠）
vGrid.LayoutMode = DevExpress.XtraVerticalGrid.LayoutMode.Tree;
// 行可持有子行，展开/折叠

// 分组类别（Category Rows）
VGridCategoryRow categoryRow = new VGridCategoryRow("基本信息");
categoryRow.Expanded = true;
vGrid.Rows.Add(categoryRow);

// 添加字段行
VGridTextRow rowName = new VGridTextRow { Name = "Name", Caption = "姓名", Properties = { Value = "张三" } };
VGridTextRow rowAge = new VGridTextRow { Name = "Age", Caption = "年龄" };
vGrid.Rows.AddRange(new VGridRow[] { rowName, rowAge });
```

### 21.2 绑定 DataSource

```csharp
// 绑定 DataTable 或 List<T>
vGrid.DataSource = myDataTable;  // 每行 = DataTable 列

// 或绑定单条记录对象
vGrid.DataSource = new List<MyEntity> { currentEntity };
vGrid.RecordWidth = 300;  // 每条记录的宽度
```

### 21.3 排序和过滤（v21.1+）

```csharp
// v21.1 起支持行标题右键排序
vGrid.OptionsBehavior.AllowSort = true;  // 默认 true，设为 false 禁用

// 列过滤
vGrid.ActiveFilterString = "[Status] = 'Active'";
```

### 21.4 与 GridControl 的核心区别

| 特性 | GridControl | VGridControl |
|------|------------|-------------|
| 数据方向 | 行=记录，列=字段 | 行=字段，列=记录 |
| 适合场景 | 数据列表、主从表 | 属性面板、详情编辑 |
| 主从支持 | 内置 Detail View | 不支持 |
| 编辑方式 | 单元格编辑器 | 行级编辑器 |

## 22. Accordion Control（手风琴导航）

> 程序集：`DevExpress.XtraBars.v21.2.dll`，命名空间：`DevExpress.XtraBars`。

AccordionControl 是垂直折叠面板，适合做左侧导航菜单，支持多级嵌套、图标、HTML 模板。官方文档：`docs.devexpress.com/WindowsForms/116002/`。

### 22.1 基本结构

```csharp
// 在 Form 上放 AccordionControl
accordionControl1.Dock = DockStyle.Left;
accordionControl1.Width = 250;

// 根级别组
AccordionControlElement groupMain = new AccordionControlElement();
groupMain.Text = "主导航";
groupMain.Expanded = true;
accordionControl1.Elements.Add(groupMain);

// 子元素
AccordionControlElement item1 = new AccordionControlElement();
item1.Text = "首页";
item1.Style = ElementStyle.Item;  // Item = 可点击行
item1.Name = "nav_home";
groupMain.Elements.Add(item1);

AccordionControlElement item2 = new AccordionControlElement();
item2.Text = "数据管理";
item2.Style = ElementStyle.Group;  // Group = 可折叠组
groupMain.Elements.Add(item2);

// 嵌套子项
AccordionControlElement subItem = new AccordionControlElement();
subItem.Text = "用户列表";
subItem.Name = "nav_user_list";
item2.Elements.Add(subItem);
```

### 22.2 点击事件

```csharp
accordionControl1.ElementClick += (s, e) =>
{
    var element = e.Element;
    if (element.Name == "nav_home")
        ShowHomePage();
    else if (element.Name == "nav_user_list")
        ShowUserList();
};
```

### 22.3 AccordionControl 支持 HTML 模板

Accordion 各部分（项目、页脚、组、页眉面板等）均支持 HTML 模板：

```csharp
// 为 Accordion 组设置 HTML 模板
accordionControl1.HtmlTemplates.Add(new HtmlTemplate
{
    Id = "customGroup",
    Content = "<div class='group-title'>${Text}</div>"
});
// 在设计器或代码中关联模板 ID
```

### 22.4 与 NavBarControl 的区别

| 特性 | NavBarControl | AccordionControl |
|------|--------------|-----------------|
| 视觉风格 | Outlook 2007 风格 | 现代扁平折叠面板 |
| 嵌套层级 | 有限 | 支持更深层级 |
| HTML 模板 | 不支持 | 支持 |
| 皮肤支持 | 传统皮肤 | 新版矢量皮肤 |
| 推荐场景 | 旧项目兼容 | 新项目首选 |

## 23. DirectX Form（v22.1+）

> 适用版本：DevExpress v22.1+。需要 `DevExpress.XtraEditors.v22.1.dll` 及以上。

DirectX Form 为所有子控件启用 DirectX 硬件加速，并支持在表单框架上应用 HTML/CSS 模板。官方博客（evget.com v22.1 新特性）：

### 23.1 启用 DirectX 渲染

```csharp
// 方式一：项目全局设置（Program.cs）
DevExpress.XtraEditors.WindowsFormsSettings.ForceDirectXPaint = DefaultBoolean.True;

// 方式二：单个 Form 继承 DirectXForm（v22.1+）
public partial class MyDirectXForm : DevExpress.XtraEditors.DirectXForm
{
    // 所有子控件自动启用 DirectX 渲染
}

// 方式三：Fluent Design Form（自带 DirectX + Acrylic 效果）
public partial class MyFluentForm : DevExpress.XtraEditors.FluentDesignForm
{
    // 侧边半透明亚克力效果 + DirectX
}
```

### 23.2 DirectX Form HTML 模板

DirectX Form 接受 HTML 模板来自定义标题栏和框架：

```csharp
// 默认模板结构（标准窗口元素，无需 CSS 即可工作）
string defaultTemplate = @"
<dx-form-frame id='frame'>
  <dx-form-titlebar id='titlebar'>
    <dx-form-icon id='icon'></dx-form-icon>
    <dx-form-text id='text'></dx-form-text>
    <dx-form-minimizebutton id='minimizebutton'></dx-form-minimizebutton>
    <dx-form-maximizebutton id='maximizebutton'></dx-form-maximizebutton>
    <dx-form-closebutton id='closebutton'></dx-form-closebutton>
  </dx-form-titlebar>
  <dx-form-content id='content'></dx-form-content>
</dx-form-frame>";

// 最小自定义模板（无标准按钮样式）
string minimalTemplate = @"
<div id='frame' class='frame'>
  <div id='content'></div>
</div>
<style>.frame { height: 100%; }</style>";

// 最简有效模板（必须有 frame 和 content 元素 ID）
string bareMinTemplate = @"
<div id='frame' class='frame'>
  <div id='content'></div>
</div>
<style>.frame { height: 100%; background: #f5f5f5; }</style>";

// 赋值
this.HtmlTemplate = bareMinTemplate;
```

### 23.3 DirectX Form vs 标准 XtraForm

| 特性 | XtraForm | DirectXForm |
|------|---------|-------------|
| DirectX 渲染 | 需要全局开关 | 表单级启用 |
| Ribbon/Gallery DirectX | 不支持 | 支持 |
| HTML 标题栏模板 | 不支持 | 支持 |
| 调整大小动画 | 标准 | 流畅动画 |
| SimpleButton DirectX | 不支持 | 支持（表单内） |

### 23.4 已知不支持的控件

以下控件放在 DirectX Form 上**不会**使用 DirectX 渲染（即使放在支持 DirectX 的表单上）：电子表格（SpreadsheetControl）等。放置后它们会以标准 GDI+ 渲染。
