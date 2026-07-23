# 模板 A：标准 CRUD 列表（最常用）

**布局**：顶部查询区（Anchor=Top,Dock=Top）→ 中部 GridControl（Dock=Fill）→ 底部按钮栏（Dock=Bottom）

**适用**：单表 CRUD、列表+筛选+新增/修改/删除

> 复制前先读 `designer-template-list.md` 的通用规则。

## A.cs（窗口主类）

```csharp
namespace {UI.Namespace}
{
    public partial class Frm_{业务名}List : {Step1.基类}, I{业务名}ListView
    {
        private {业务名}ListPresenter _presenter;

        public Frm_{业务名}List()
        {
            InitializeComponent();
            _presenter = new {业务名}ListPresenter(this);
        }

        private void Frm_{业务名}List_Load(object sender, EventArgs e)
        {
            UICommonBase.StartWaitForm("加载中...", this);
            try
            {
                _presenter.Select{业务名}List();
                ControlByStatus();
            }
            catch (Exception ex)
            {
                UICommonBase.ShowMessageBox(MessageType.Warming, ex.Message);
            }
            finally
            {
                UICommonBase.EndWaitForm();
            }
        }

        // ... IView 接口实现 + 事件处理 ...
    }
}
```

## A.Designer.cs — 主体复制 §1.1 + 追加查询区

> **InitializeComponent 主体权威版本见 `designer-patterns.md §1.1`**（已验证可编译，含正确的 `SuspendLayout/ResumeLayout` 对称、`BeginInit/EndInit` 子→父顺序、`components` 字段、`pnlBottom` 按钮栏）。
>
> 本模板只覆盖 §1.1 之上的**顶部查询区差异**：在 §1.1 的 InitializeComponent 基础上插入下面三块。

### ① 额外字段声明（加在 §1.1 字段列表里）

```csharp
private LayoutControl lcSearch;
private LayoutControlGroup lcgSearch;
private LayoutControlItem lciKeyword;          // 持 txtKeyword,label 由 item.Text 承担
private LayoutControlItem lciBtnSearch;        // 持 btnSearch
private LayoutControlItem lciBtnReset;         // 持 btnReset
private TextEdit txtKeyword;
private SimpleButton btnSearch;
private SimpleButton btnReset;
```

> ⚠️ DevExpress LayoutControl 里**每个 item 只能持一个 Control**，label 由 `LayoutControlItem.Text` 属性承担，**不要**新建独立 `LabelControl` 再赋给某个 item——那是上版本的根因 bug(双重赋值 / label 游离)。

### ② 查询区初始化(插在 §1.1 "2. 实例化" 之后、gcMain 实例化之前)

```csharp
this.lcSearch = new LayoutControl();
this.lcgSearch = new LayoutControlGroup();
this.lciKeyword = new LayoutControlItem();
this.lciBtnSearch = new LayoutControlItem();
this.lciBtnReset = new LayoutControlItem();
this.txtKeyword = new TextEdit();
this.btnSearch = new SimpleButton();
this.btnReset = new SimpleButton();

((ISupportInitialize)(this.lcSearch)).BeginInit();
this.lcSearch.SuspendLayout();

// 文字走 resx,这里只设 Name / Size 等非本地化属性(见 §"resx")
this.txtKeyword.Name = "txtKeyword";
this.txtKeyword.Properties.NullValuePrompt = "请输入编码或名称";   // NullValuePrompt 不算"初始可见文字",可硬编码
this.txtKeyword.Size = new Size(220, 22);

this.lciKeyword.Name = "lciKeyword";
this.lciKeyword.Control = this.txtKeyword;       // ← 单一 Control,label 由下面 lciKeyword.Text 承担
// this.lciKeyword.Text = "关键字：";            // 文字走 resx(见下),调试期可解除注释

this.btnSearch.Name = "btnSearch";
this.btnSearch.Size = new Size(75, 26);
this.lciBtnSearch.Name = "lciBtnSearch";
this.lciBtnSearch.Control = this.btnSearch;

this.btnReset.Name = "btnReset";
this.btnReset.Size = new Size(75, 26);
this.lciBtnReset.Name = "lciBtnReset";
this.lciBtnReset.Control = this.btnReset;

// 组装查询区容器
this.lcSearch.Dock = DockStyle.Top;
this.lcSearch.Location = new Point(0, 0);
this.lcSearch.Name = "lcSearch";
this.lcSearch.Size = new Size(984, 48);
this.lcSearch.TabIndex = 0;

this.lcgSearch.Name = "lcgSearch";
this.lcgSearch.TextVisible = false;
this.lcgSearch.AddItem(this.lciKeyword);
this.lcgSearch.AddItem(this.lciBtnSearch);
this.lcgSearch.AddItem(this.lciBtnReset);
this.lcSearch.Root = this.lcgSearch;
```

> ⚠️ **上一版的根因 bug**(已修)：旧版用 `lciBtnRow.AddControl(btnSearch, 0, 0)`——`LayoutControlItem` **没有** `AddControl` 方法(那是 `LayoutControlGroup` 的 API),编译会失败;且旧版把 btnSearch/btnReset 加进一个不存在的 item,**从未注册到任何容器**,控件悬浮。
>
> **正确做法**：每个按钮各自独占一个 `LayoutControlItem`(如 `lciBtnSearch` / `lciBtnReset`),再 `lcgSearch.AddItem(lciBtnSearch)` 把 item 加进 group。

### ③ 把查询区挂进 Form(§1.1 "6. Frm 装配" 处,在 gcMain 之前 Add)

```csharp
this.Controls.Add(this.gcMain);
this.Controls.Add(this.lcSearch);     // ← 新增:查询区 Dock=Top
this.Controls.Add(this.pnlBottom);    // §1.1 已有
```

> Dock 顺序：先 Add 的 `Fill`/`Bottom` 控件会被后 Add 的 `Top` 控件推到剩余空间——`Controls.Add` 顺序按 Top→Fill→Bottom 或 Bottom→Fill→Top 都行，WinForms Dock 布局引擎会按 Dock 值自动分配；只要三个都 Add 进去即可。

### ④ 解初始化(§1.1 "7. 解初始化" 处追加 lcSearch)

```csharp
((ISupportInitialize)(this.gvMain)).EndInit();   // §1.1 已有:子→父
((ISupportInitialize)(this.gcMain)).EndInit();   // §1.1 已有
((ISupportInitialize)(this.lcSearch)).EndInit(); // ← 新增
this.lcSearch.ResumeLayout(false);
this.pnlBottom.ResumeLayout(false);              // §1.1 已有
this.ResumeLayout(false);                         // §1.1 已有(对应 §1.1 顶部的 this.SuspendLayout)
```

## A.resx 关键节点（文字唯一定义处）

> §1.1 主体里所有可见文字（按钮文本等）都走 resx，**不要**在 InitializeComponent 里硬编码 `.Text = "..."`（违反 `designer-template-list.md`「❌ 控件初始文字硬编码」）。本查询区新增三项：

```xml
<data name="lciKeyword.Text" xml:space="preserve">
  <value>关键字：</value>
</data>
<data name="btnSearch.Text" xml:space="preserve">
  <value>查询(&amp;S)</value>
</data>
<data name="btnReset.Text" xml:space="preserve">
  <value>重置(&amp;R)</value>
</data>
<!-- 其他按钮、列头同理 -->
```

---

**单一权威说明**：本模板的 InitializeComponent 主体已 defer 到 `designer-patterns.md §1.1`，避免双份维护漂移。本文件只保留 §1.1 不覆盖的「顶部查询区差异」。改 §1.1 时本模板自动跟随；改查询区时只动本文件。
