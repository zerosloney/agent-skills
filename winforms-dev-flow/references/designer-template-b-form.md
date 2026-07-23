# 模板 B：单条记录编辑表单

**布局**：整个窗体一个 LayoutControl（字段 ≤8 一字排开，>8 上下两栏）+ 底部按钮栏

**适用**：新增 / 修改弹窗（`DlgEdit_{业务名}.cs`）

> 复制前先读 `designer-template-list.md` 的通用规则。

## B.Designer.cs

```csharp
namespace {UI.Namespace}
{
    partial class DlgEdit_{业务名}
    {
        private void InitializeComponent()
        {
            this.lcMain = new LayoutControl();
            this.lcgMain = new LayoutControlGroup();
            this.txtCode = new TextEdit();
            this.txtName = new TextEdit();
            this.lbcCode = new LabelControl();
            this.lbcName = new LabelControl();
            this.pnlBottom = new Panel();
            this.btnSave = new SimpleButton();
            this.btnCancel = new SimpleButton();

            ((ISupportInitialize)(this.lcMain)).BeginInit();
            this.lcMain.SuspendLayout();
            this.pnlBottom.SuspendLayout();

            //
            // lcMain
            //
            this.lcMain.Dock = DockStyle.Fill;
            this.lcMain.Name = "lcMain";
            this.lcMain.Size = new Size(540, 360);

            this.lcgMain.Name = "lcgMain";
            this.lcgMain.TextVisible = false;

            // 字段行（示例：Code + Name）
            this.txtCode.Properties.MaxLength = 50;
            this.lcgMain.AddItem(this.txtCode);
            // ... 其他字段同理

            //
            // pnlBottom
            //
            this.pnlBottom.Dock = DockStyle.Bottom;
            this.pnlBottom.Size = new Size(540, 50);
            this.btnSave.Text = "保存(&S)";
            this.btnSave.Size = new Size(75, 28);
            this.btnSave.Anchor = AnchorStyles.Right;
            this.btnSave.Location = new Point(360, 11);
            this.btnCancel.Text = "取消(&C)";
            this.btnCancel.Size = new Size(75, 28);
            this.btnCancel.Anchor = AnchorStyles.Right;
            this.btnCancel.Location = new Point(450, 11);
            this.pnlBottom.Controls.Add(this.btnSave);
            this.pnlBottom.Controls.Add(this.btnCancel);

            this.ClientSize = new Size(540, 410);
            this.Controls.Add(this.lcMain);
            this.Controls.Add(this.pnlBottom);
            this.MinimumSize = new Size(420, 320);
            this.Name = "DlgEdit_{业务名}";
            this.Text = "{新增/修改}{业务名}";
            this.StartPosition = FormStartPosition.CenterParent;
            this.FormBorderStyle = FormBorderStyle.FixedDialog;
            this.MaximizeBox = false;
            this.MinimizeBox = false;

            ((ISupportInitialize)(this.lcMain)).EndInit();
            this.lcMain.ResumeLayout(false);
            this.pnlBottom.ResumeLayout(false);
            this.ResumeLayout(false);
        }
    }
}
```

## B.cs（新增 / 修改判定）

```csharp
public partial class DlgEdit_{业务名} : {Step1.基类}
{
    private readonly {业务名}Info _info;        // null = 新增
    private readonly {业务名}Ser _ser;           // 构造函数注入

    public DlgEdit_{业务名}({业务名}Ser ser, {业务名}Info info = null)
    {
        InitializeComponent();
        _ser = ser ?? throw new ArgumentNullException(nameof(ser));
        _info = info;
        if (_info != null)
        {
            this.Text = "修改" + this.Text;
            txtCode.Text = _info.Code;
            txtCode.Properties.ReadOnly = true;   // 修改时 Code 不允许改
            // ... 绑定其他字段
        }
        else
        {
            this.Text = "新增" + this.Text;
        }
    }
}
```
