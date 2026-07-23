# 对话框模式参考（三种模式完整代码）

> 由 SKILL.md Step 生成对话框时按需加载。

## Deve-Upgrader 对话框 `dlg{业务名}.cs`

### 模式 A：`dlgBase`（手动 OK/Cancel）

```csharp
using System;
using System.Windows.Forms;
using DevExpress.XtraEditors;
using UICommon;  // dlgBase 在此命名空间

namespace MMLib
{
    public partial class dlg{业务名} : dlgBase
    {
        #region Private
        private {业务名}Presenter _presenter;
        private {实体类} _entity;
        private List<{实体类}> _lstContext;
        #endregion

        #region Constructor

        // 新增模式: entity 参数为 null
        public dlg{业务名}({业务名}Presenter presenter, List<{实体类}> lstContext)
        {
            InitializeComponent();
            _presenter = presenter;
            _lstContext = lstContext;
        }

        // 修改模式: entity 参数不为 null
        public dlg{业务名}({业务名}Presenter presenter, {实体类} entity)
        {
            InitializeComponent();
            _presenter = presenter;
            _entity = entity;
        }
        #endregion

        #region Events
        private void dlg{业务名}_Load(object sender, EventArgs e)
        {
            if (_entity == null)
                this.Text = "新增";
            else
            {
                this.Text = "修改";
                // 填充控件
                txtName.Text = _entity.Name;
                datCreateTime.EditValue = _entity.CreateTime;
            }
        }

        private void btnOk_Click(object sender, EventArgs e)
        {
            // 验证
            if (string.IsNullOrEmpty(txtName.Text))
            {
                XtraMessageBox.Show("名称不能为空", "提示");
                return;
            }

            if (_entity == null)  // 新增
            {
                var entity = new {实体类} { ID = Guid.NewGuid(), Name = txtName.Text };
                if (_presenter.AddItem(entity))
                    this.DialogResult = DialogResult.OK;
            }
            else  // 修改
            {
                // DeepClone 创建可编辑副本
                var cloned = Clone.DeepClone(_entity) as {实体类};
                cloned.Name = txtName.Text;
                if (_presenter.UpdateItem(cloned))
                {
                    // 写回原始对象
                    _entity.Name = cloned.Name;
                    this.DialogResult = DialogResult.OK;
                }
            }
        }

        private void btnCancel_Click(object sender, EventArgs e)
        {
            this.DialogResult = DialogResult.Cancel;
        }
        #endregion
    }
}
```

### 模式 B：`dlg_ModifyBase`（重写 `ok()`）

```csharp
using System;
using System.Collections.Generic;
using Jamtc.DevExpressExtend;  // dlg_ModifyBase
using Jamtc.Common.Lib;       // UICommonBase

namespace MMLib
{
    public partial class dlg{业务名} : dlg_ModifyBase
    {
        #region Private
        private List<{实体类}> _entities;
        #endregion

        #region Constructor
        public dlg{业务名}(List<{实体类}> entities)
        {
            InitializeComponent();
            _entities = entities;
        }
        #endregion

        #region Override
        /// <summary>
        /// 基类 ok() 钩子。返回 false 阻止关闭。
        /// </summary>
        protected override bool ok()
        {
            if (string.IsNullOrEmpty(glkuField.EditValue?.ToString()))
            {
                UICommonBase.ShowMessageBox(MessageType.Message, "必填项不可为空!");
                return false;
            }

            // 更新所有选定实体
            _entities.ForEach(a => {
                a.Property = glkuField.Text;
            });
            return base.ok();
        }
        #endregion
    }
}
```

## Deve-CRS 对话框 `dlg_{业务名}.cs`

CRS 对话框使用 `dlg_ModifyBase` 继承模式：

```csharp
using System;
using System.Data;
using Jamtc.DevExpressExtend;  // dlg_ModifyBase

namespace CRS.UI
{
    public partial class dlg_{业务名} : dlg_ModifyBase
    {
        #region Properties
        /// <summary>
        /// 选择的 ID（通过属性暴露给父窗体）
        /// </summary>
        public Guid SelectedID { get; private set; }
        public int SelectedValue { get; private set; }
        #endregion

        #region Constructor
        public dlg_{业务名}()
        {
            InitializeComponent();
        }
        #endregion

        #region Events
        private void dlg_{业务名}_Load(object sender, EventArgs e)
        {
            // 加载查找编辑数据源
            DataTable dt = new {业务名}DataSer().QueryData("TableName");
            gridLookUpEdit1.Properties.DataSource = dt;
        }
        #endregion

        #region Override
        protected override bool ok()
        {
            if (string.IsNullOrWhiteSpace(gridLookUpEdit1.EditValue?.ToString()))
            {
                return false;
            }
            SelectedID = Guid.Parse(gridLookUpEdit1.EditValue.ToString());
            DataRow dataRow = gridLookUpEdit1View.GetFocusedDataRow();
            SelectedValue = int.Parse(dataRow["Column"]?.ToString());
            return base.ok();
        }

        protected override bool cancel()
        {
            return base.cancel();
        }
        #endregion
    }
}
```

## CRS-EQUP 对话框 `dlg{业务名}.cs`

> CRS-EQUP 对话框与 Upgrader Pattern A 基本相同，差异：(1) 命名空间为 `Jamtc.Extend.CRS.Eqp`；(2) 使用 `UICommonBase.ShowMessageBox` 替代 `XtraMessageBox`；(3) 不使用 DeepClone，直接操作原始对象。完整代码参照 Upgrader Pattern A 做上述替换。

## 对话框基类总结

| 基类 | 来源命名空间 | OK 机制 | 使用项目 |
|------|-------------|---------|---------|
| `dlgBase` | `UICommon` / `Jamtc.Extend.CRS.Eqp.UI` | 手动 `btnOk_Click` + `this.DialogResult=OK` | Deve-Upgrader, EQUP |
| `dlg_ModifyBase` | `Jamtc.DevExpressExtend` | 重写 `override bool ok()` | Deve-CRS, 部分 Upgrader |
| `frm_GlobalizationBase` | `Jamtc.DevExpressExtend` | 同 `dlg_ModifyBase` | EQUP (dlgBase 的基类) |
