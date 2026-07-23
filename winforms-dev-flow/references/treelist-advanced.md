# TreeList 高级功能

> 加载时机：需要 TreeList 节点操作、列定制、条件格式、拖拽、展开菜单时读取。

## 节点基础操作

### 获取节点数据

```csharp
// 获取当前选中节点对应的数据
private TreeNodeView GetCurrentNode()
{
    if (tlMain.FocusedNode == null) return null;
    return tlMain.GetDataRecordByNode(tlMain.FocusedNode) as TreeNodeView;
}

// 遍历所有节点
private void IterateAllNodes()
{
    foreach (TreeListNode node in tlMain.Nodes)
    {
        ProcessNode(node);
    }
}

private void ProcessNode(TreeListNode node)
{
    var data = tlMain.GetDataRecordByNode(node) as TreeNodeView;
    // 处理数据...

    // 递归子节点
    foreach (TreeListNode child in node.Nodes)
    {
        ProcessNode(child);
    }
}
```

### 节点操作

```csharp
// 展开/收缩
tlMain.ExpandAll();
tlMain.CollapseAll();
tlMain.FocusedNode.Expand();  // 展开当前节点

// 选中节点
tlMain.FocusedNode = targetNode;
tlMain.MakeNodeVisible(targetNode);  // 确保节点可见

// 添加节点（非绑定模式）
TreeListNode newNode = tlMain.AppendNode(
    new object[] { "新节点名称", "备注" },
    parentNode  // null = 根节点
);
newNode["ID"] = Guid.NewGuid().ToString();

// 删除节点
tlMain.DeleteNode(tlMain.FocusedNode);

// 移动节点
tlMain.MoveNode(nodeToMove, targetParentNode);
```

## 列配置

### 动态列生成

```csharp
private void SetupTreeColumns()
{
    tlMain.Columns.Clear();

    var colName = new TreeListColumn
    {
        Caption = "名称",
        FieldName = "Name",
        Name = "colName",
        Visible = true,
        VisibleIndex = 0,
        Width = 200
    };
    colName.AppearanceCell.TextOptions.HAlignment = HorzAlignment.Near;
    tlMain.Columns.Add(colName);

    var colRemark = new TreeListColumn
    {
        Caption = "备注",
        FieldName = "Remark",
        Name = "colRemark",
        Visible = true,
        VisibleIndex = 1,
        Width = 300
    };
    tlMain.Columns.Add(colRemark);
}
```

### 列属性

```csharp
// 设置列可见性
tlMain.Columns["Remark"].Visible = false;
tlMain.Columns["Name"].VisibleIndex = 0;

// 列宽
tlMain.Columns["Name"].Width = 200;
tlMain.BestFitColumns();  // 自动计算最佳列宽

// 列排序
tlMain.Columns["SortOrder"].SortOrder = DevExpress.Data.ColumnSortOrder.Ascending;
```

## 条件格式（CustomDrawNodeCell）

### 节点颜色

```csharp
private void tlMain_CustomDrawNodeCell(object sender, CustomDrawNodeCellEventArgs e)
{
    if (e.Node == null) return;
    var view = tlMain.GetDataRecordByNode(e.Node) as TreeNodeView;
    if (view == null) return;

    if (view.Status == (int)NodeStatus.Active)
        e.Appearance.BackColor = Color.LightGreen;
    else if (view.Status == (int)NodeStatus.Inactive)
        e.Appearance.BackColor = Color.LightGray;
    else if (view.Status == (int)NodeStatus.Locked)
        e.Appearance.BackColor = Color.Pink;
}
```

### 节点图标

```csharp
// 在列中使用 ImageComboBox 或自定义绘制
private void tlMain_CustomDrawNodeCell(object sender, CustomDrawNodeCellEventArgs e)
{
    if (e.Column.FieldName == "Name" && e.Node.HasChildren)
    {
        // 有子节点的加粗显示
        e.Appearance.Font = new Font(e.Appearance.Font, FontStyle.Bold);
    }
}
```

## 主从联动（FocusedNodeChanged）

### 标准联动

```csharp
private void tlMain_FocusedNodeChanged(object sender, FocusedNodeChangedEventArgs e)
{
    // 排除筛选行
    if (e.Node is TreeListAutoFilterNode || e.Node == null) return;

    var view = tlMain.GetDataRecordByNode(e.Node) as TreeNodeView;
    if (view == null) return;

    _presenter.LoadDetail(view.ID);
}
```

### 节点类型判断联动

```csharp
private void tlMain_FocusedNodeChanged(object sender, FocusedNodeChangedEventArgs e)
{
    if (e.Node is TreeListAutoFilterNode || e.Node == null) return;

    var row = GetNodeRow(tlMain, e.Node);
    string nodeType = row["NodeType"].ToString();

    if (nodeType == "业务类型A")
    {
        _presenter.LoadDetail(row["ID"].ToString());
    }
    else if (nodeType == "业务类型B")
    {
        _presenter.LoadOtherDetail(row["ID"].ToString());
    }
    else
    {
        gcDetail.DataSource = null;
    }
}

private DataRow GetNodeRow(TreeList tl, TreeListNode node)
{
    return ((DataRowView)tl.GetDataRecordByNode(node)).Row;
}
```

## 拖拽功能

### 标准拖放

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
        var row = (tlMain.GetDataRecordByNode(tn) as TreeNodeView);
        if (row == null || row.CanDrag == false)
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
        var targetRow = tlMain.GetDataRecordByNode(targetNode) as TreeNodeView;
        if (targetRow == null || targetRow.CanAcceptDrop == false)
            continue;

        // 不允许拖到自己
        if (targetNode == tn) continue;

        // 1. 更新数据库
        string sql = $"UPDATE TableName SET ParentID='{targetRow.ID}' WHERE ID='{GetNodeId(tn)}'";
        _so.SqlExcuteNoQuery(sql, varlist.ASSConn);

        // 2. 移动节点
        tlMain.MoveNode(tn, targetNode);
    }
}

private string GetNodeId(TreeListNode node)
{
    var data = tlMain.GetDataRecordByNode(node) as TreeNodeView;
    return data?.ID ?? string.Empty;
}
```

## 展开/收缩菜单

```csharp
// CSSTreeList 扩展方法（项目已有），或手动实现：
private void InitExpandMenu(ContextMenuStrip cms)
{
    var expandItem = new ToolStripMenuItem("展开");
    expandItem.Click += (s, e) => tlMain.ExpandAll();
    cms.Items.Add(expandItem);

    var collapseItem = new ToolStripMenuItem("收缩");
    collapseItem.Click += (s, e) => tlMain.CollapseAll();
    cms.Items.Add(collapseItem);
}
```

## 筛选

```csharp
// 启用筛选
tlMain.OptionsView.ShowAutoFilterRow = true;
tlMain.OptionsBehavior.EnableFiltering = true;
tlMain.OptionsFilter.FilterMode = FilterMode.Extended;

// 筛选模式
tlMain.OptionsFilter.FilterMode = FilterMode.Extended;       // 扩展筛选（推荐）
tlMain.OptionsFilter.FilterEditorMode = FilterEditorMode.Default;
```

## 外观定制

```csharp
// 树线显示
tlMain.OptionsView.ShowTreeLines = true;

// 指示器
tlMain.OptionsView.ShowIndicator = false;

// 可编辑
tlMain.OptionsBehavior.Editable = false;
tlMain.OptionsBehavior.AutoFocusNewNode = false;

// 预览区域（显示大文本）
tlMain.OptionsView.ShowPreview = true;
tlMain.PreviewFieldName = "Remark";  // 显示 Remark 字段作为预览
```

## TreeList + RepositoryItem

```csharp
// 进度条列
RepositoryItemProgressBar riProgress = new RepositoryItemProgressBar();
riProgress.Minimum = 0;
riProgress.Maximum = 100;
tlMain.RepositoryItems.Add(riProgress);
tlMain.Columns["Progress"].ColumnEdit = riProgress;

// 图片列
RepositoryItemPictureEdit riPicture = new RepositoryItemPictureEdit();
tlMain.RepositoryItems.Add(riPicture);
tlMain.Columns["Image"].ColumnEdit = riPicture;
```

## 性能注意事项

```csharp
// 大数据量时用 BeginUpdate/EndUpdate
tlMain.BeginUpdate();
try
{
    tlMain.DataSource = largeTreeData;
    tlMain.KeyFieldName = "ID";
    tlMain.ParentFieldName = "ParentID";
    tlMain.ExpandAll();
}
finally
{
    tlMain.EndUpdate();
}

// 避免频繁刷新
// ❌ 每次节点变更都刷新
// ✅ 批量操作后用 EndUpdate 一次性刷新
```
