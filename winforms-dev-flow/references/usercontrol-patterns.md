# UserControl 可复用组件模式

> 由 SKILL.md Step 3（复用决策为 ucl 时）按需加载。
> 覆盖三种模式的 UserControl 设计规范。

## MMLib 模式（Deve-Upgrader）：属性 + 事件

用户控件继承 `XtraUserControl`，通过公开属性暴露数据，通过事件通知父窗体。

### 完整模板

```csharp
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Windows.Forms;
using DevExpress.XtraEditors;
using BLL;

namespace UICommon
{
    [ToolboxItem(true)]
    public partial class ucl{组件名} : XtraUserControl
    {
        #region 设计时属性

        [Browsable(true), Category("Custom"), Description("标签文本")]
        public string Label
        {
            get { return lbcLabel.Text; }
            set { lbcLabel.Text = value; }
        }

        [Browsable(true), Category("Custom"), Description("控件宽度")]
        public int GlueWidth
        {
            get { return glueMain.Width; }
            set { glueMain.Width = value; }
        }

        [Browsable(true), Category("Data"), Description("数据源类型")]
        public DataSourceType DatasourceType { get; set; }

        [Browsable(true), Category("Custom"), Description("是否必填")]
        public bool IsMustFillIn { get; set; }

        private bool _isEnabled = true;
        [Browsable(true), Category("Custom")]
        public new bool IsEnabled
        {
            get { return _isEnabled; }
            set { _isEnabled = glueMain.Enabled = value; }
        }

        #endregion

        #region 运行时属性（对父窗体暴露）

        [Browsable(false)]
        public List<{实体类}> DataSource { get; private set; }

        [Browsable(false)]
        public List<{实体类}> SelectedItems { get; set; }

        public bool HasSelection => SelectedItems != null && SelectedItems.Count > 0;

        #endregion

        #region 委托与事件

        public delegate void MyChangeEventHandler();
        public event MyChangeEventHandler TxtChanged;

        #endregion

        #region Constructor

        public ucl{组件名}()
        {
            InitializeComponent();
        }

        #endregion

        #region Events

        private void ucl{组件名}_Load(object sender, EventArgs e)
        {
            if (DesignMode) return;  // 设计时保护
            LoadData();
        }

        private void glueMain_EditValueChanged(object sender, EventArgs e)
        {
            SelectedItems = GetSelectedItems();
            TxtChanged?.Invoke();
        }

        #endregion

        #region Public Methods

        public void Clear()
        {
            glueMain.EditValue = null;
            SelectedItems?.Clear();
        }

        public void ClearDataSource()
        {
            glueMain.Properties.DataSource = null;
        }

        public void Reload()
        {
            Clear();
            LoadData();
        }

        #endregion

        #region Private Methods

        private void LoadData()
        {
            switch (DatasourceType)
            {
                case DataSourceType.All:
                    DataSource = new {实体名}Ser().GetAll();
                    break;
                case DataSourceType.Useable:
                    DataSource = new {实体名}Ser().GetUseable();
                    break;
                case DataSourceType.Custom:
                    break;  // 等待父窗体通过 DataSource 属性设置
            }
            glueMain.Properties.DataSource = DataSource;
            glueMain.Properties.ValueMember = "ID";
            glueMain.Properties.DisplayMember = "Name";
        }

        #endregion
    }
}
```

### 设计时属性规范

| 属性 | Category | 说明 |
|------|----------|------|
| `Label` | Custom | 标签文本 |
| `GlueWidth` | Custom | 查找编辑宽度 |
| `IsMustFillIn` | Custom | 必填标记（红色星号） |
| `IsEnabled` | Custom | 启用/禁用 |
| `DatasourceType` | Data | 数据源枚举（All/Useable/Custom） |

### 父窗体集成方式

```csharp
// 1. 设置数据源类型
uclCompany1.DatasourceType = uclCompany.CompanyType.Useable;

// 2. 订阅事件
uclCompany1.TxtChanged += (s, ev) => {
    // 处理选择变更
};

// 3. 读取选中数据
var companies = uclCompany1.SelectedItems;
```

---

## CRS 模式：IDetailView 接口

用户控件实现 `IDetailView`，通过 `DataSource` 属性 setter 接收外部数据。

```csharp
public partial class UC_{组件名}View<TEntity> : UserControl, IDetailView
    where TEntity : EntityBase, new()
{
    private object _source;

    // IDetailView 核心属性
    public object DataSource
    {
        get { return _source; }
        set
        {
            _source = value;
            if (value == null) return;
            var entity = (value as List<object>)?[0] as TEntity;
            BindEntity(entity);
        }
    }

    public Control InternalControl => this;         // 或 xtraTabControl1
    public int DetailHeight => this.Height;

    private void BindEntity(TEntity entity)
    {
        textNO.Text = entity.NO;
        cboStatus.Text = entity.StatusName;
        dateCreate.EditValue = entity.CreateTime;
    }
}
```

### 父窗体集成方式

```csharp
// Designer 注入
customView1.InternalControlType = typeof(UC_ProjectInfoView<ProjectInfo>);
```

---

## EQUP 模式：委托事件 + 枚举数据源

```csharp
public partial class UserControl_{组件名} : UserControl
{
    #region Delegates
    public delegate void MyChangeEventHandler();
    public event MyChangeEventHandler TxtChanged;
    #endregion

    #region 设计时属性
    [Browsable(true), Category("Behavior")]
    public int DropDownWidth { get; set; }

    [Browsable(true), Category("Data")]
    public DataSourceEnum DataSourceType { get; set; }

    [Browsable(true), Category("Behavior")]
    public bool IsMultiSelect { get; set; }
    #endregion

    #region 运行时属性
    [Browsable(false)]
    public List<string> Value { get; private set; }

    [Browsable(false)]
    public override string Text => string.Join(", ", SelectedDisplayNames);
    #endregion

    #region Constructor
    public UserControl_{组件名}()
    {
        InitializeComponent();
    }
    #endregion

    #region Events
    private void UserControl_{组件名}_Load(object sender, EventArgs e)
    {
        if (!DesignMode)
        {
            LoadDataSource();

            if (IsMultiSelect)
            {
                cboField.Properties.View.OptionsSelection.MultiSelect = true;
                _gridCheckMarks = new GridCheckMarksSelection(cboField.Properties);
                _gridCheckMarks.SelectionChanged += GridCheckMarks_SelectionChanged;
                cboField.Properties.Tag = _gridCheckMarks;
            }
        }
    }

    private void GridCheckMarks_SelectionChanged(object sender, EventArgs e)
    {
        UpdateSelectedItems();
        TxtChanged?.Invoke();
    }

    private void cboField_CustomDisplayText(object sender, CustomDisplayTextEventArgs e)
    {
        e.DisplayText = string.Join(", ", SelectedDisplayNames);
    }
    #endregion

    #region Public Methods
    public void Clear()
    {
        cboField.EditValue = null;
        SelectedItems?.Clear();
    }

    public void SelectAll()
    {
        // 全选逻辑
    }

    public void SetSelected(List<{实体类}> items)
    {
        // 反选逻辑
    }
    #endregion

    #region Private Methods
    private void LoadDataSource()
    {
        switch (DataSourceType)
        {
            case DataSourceEnum.TypeA:
                _dataSource = new {业务名}Ser().GetTypeA();
                break;
            case DataSourceEnum.TypeB:
                _dataSource = new {业务名}Ser().GetTypeB();
                break;
        }
        cboField.Properties.DataSource = _dataSource;
    }
    #endregion
}
```

---

## 三种模式对比

| 特征 | MMLib | CRS | EQUP |
|------|-------|-----|------|
| 基类 | `XtraUserControl` | `UserControl + IDetailView` | `UserControl` |
| 数据暴露 | 公开属性 + 事件 | `DataSource` 属性 setter | 公开属性 + 委托事件 |
| 数据加载 | Load 事件中 BLL 查询 | 通过 DataSource 传入 | Load 事件中 BLL 查询 |
| 设计时属性 | Browsable/Category/Description | 少 | Browsable/Category/Description |
| 选择方式 | 单选为主 | 通用 | 单选 + GridCheckMarksSelection 多选 |
| 父窗体通信 | 属性赋值 + 事件订阅 | 属性赋值 | 属性赋值 + 事件订阅 |
| DesignMode 保护 | `if (DesignMode) return;` | 有 | `if (!DesignMode)` |
