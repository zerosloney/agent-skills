# Designer InitializeComponent 片段库(实战沉淀)

> **目的**:把 failure-modes 案例 7「Designer 手写出错率极高」压到最低。
> 给 4 个项目家族 + 6 个常见控件场景提供**已验证可编译的 InitializeComponent 真实片段**,
> 直接复制后改 `{业务名}` / `{字段}` 占位符即可,不要再凭印象拼语法。
>
> **使用方式**:Step 4 生成 Designer 前,根据「基类家族 × 控件类型」交叉定位到对应片段,逐段拼接。
> **读取规则**:不要全量加载本文件;先看索引,只读目标家族/控件场景和 §5 通用坑位。

---

## 索引

> 按「家族 × 场景」交叉定位，只读目标章节。§5 通用坑位是所有家族的公共基线，必读。

| 家族 | 场景 | 章节 | 说明 |
|------|------|------|------|
| Deve-Upgrader | GridControl + GridView（CRUD 列表） | §1.1 | 主场景，含搜索区 + 分页 |
| Deve-Upgrader | TreeList（目录树 / 主从） | §1.2 | ParentFieldName / KeyFieldName |
| Deve-Upgrader | LayoutControl 表单（≤8 字段录入） | §1.3 | lciKeyword 绑定模式 |
| Deve-Upgrader | RepositoryItem 套件 | §1.4 | 日期/下拉/勾选/超链接编辑器 |
| Deve-Upgrader | SplitContainerControl / DockManager | §1.5 | 可折叠面板 |
| Deve-Upgrader | XtraTabControl（多 Tab） | §1.6 | Tab 页切换 + 动态加载 |
| Deve-CRS（主线） | 与 Upgrader 的 5 个关键差异 | §2 | 泛型基类 / 三层 IView / ORM / CRS GridStyle / 权限菜单 |
| Deve-CRS | Eqp 子模块变体 | §2 表 | ⚠️ Eqp 实际走 Upgrader 风格（非泛型），不要套 CRS 主线 |
| EQUP（CRS-Eq） | 与 CRS 的 3 个差异点 | §3 | 基类系 / GridStyle="EQP" / 命名空间 |
| CSS.WHXL.Extend | 与 Upgrader 的 4 个本地差异 | §4 | DBHelp 名 / 连接名 / 类名前缀 / 皮肤 |
| 所有家族 | 通用坑位预防 | §5 | 7 条 begin/end 配对 + resx 注册 + 控件命名 + AutoSize |
| 所有家族 | 选择指南 | §6 | 4 家族 × 6 场景快速决策树 |
| 所有家族 | 维护指南 | §7 | 新增片段时的格式规范 |

---

## §1 Deve-Upgrader(基类 = `frmBase`,GridStyle = `"ASS"` 主导)

> 适用项目:`CSS.WHXL.Extend` 系列、`Deve-Upgrader` 系列、`Jamtc.Common` 系列。
> 项目代号主导 `"ASS"`(`Program.cs` 中注册),GridStyle 构造见 §1.1。

> 📋 **GridStyle 多代号是 Upgrader 正常状态**(实测 2026-07,过滤注释后):
>
> | 代号 | 计数 | 主要分布 | 说明 |
> |------|------|---------|------|
> | `ASS` | 1291 | 散布全部目录 | 主代号,默认套用 |
> | `CSS` | 128 | ITPManagement(65) / QMS(13) / BasicConfigureLib(12) 等 | 子模块用,散布多目录 |
> | `SM` / `SMManagement` / `SMBOM` | 35 / 15 / 6 | **集中在 `SM.UI` 子目录** | 钢材/BOM 子模块专用 |
> | `Ass`(大小写变体) | ~45 | ITPManagement / BasicConfigureLib 散布 | ⚠️ 大小写敏感,与 `ASS` 不通用 |
>
> **判定规则**:
> - 目标模块所在子目录**只有一种代号** → 直接套该代号(如 SM.UI 全用 SM 系列)
> - 目标模块所在子目录**多代号混用**(如 ITPManagement: ASS 50 / CSS 65 / Ass 25) → **必须 Step 1 让用户选**,不默认
> - GridStyle 代号**大小写敏感**,`"Ass"` ≠ `"ASS"`,生成时严格按参照窗体原样

### §1.1 GridControl + GridView(CRUD 列表)

**场景**:中部单表 Grid,Dock=Fill,可自定义列。

```csharp
namespace CSS.WHXL.Extend.UI.{模块}  // 命名空间占位
{
    partial class Frm_{业务名}List
    {
        private IContainer components;
        private GridStyle _gridStyle;

        private GridControl gcMain;
        private GridView   gvMain;
        private Panel      pnlBottom;

        private void InitializeComponent()
        {
            this.components = new Container();

            // ── 1. GridStyle(必须在 InitializeComponent 顶部)──
            this._gridStyle = new GridStyle("ASS", this, gcMain, gvMain);

            // ── 2. 实例化 ──
            this.gcMain   = new GridControl();
            this.gvMain   = new GridView();
            this.pnlBottom = new Panel();

            ((ISupportInitialize)(this.gcMain)).BeginInit();
            ((ISupportInitialize)(this.gvMain)).BeginInit();
            this.pnlBottom.SuspendLayout();
            this.SuspendLayout();

            // ── 3. gcMain 配置 ──
            this.gcMain.Dock = DockStyle.Fill;
            this.gcMain.Location = new Point(0, 48);
            this.gcMain.MainView = this.gvMain;
            this.gcMain.Name = "gcMain";
            this.gcMain.Size = new Size(984, 530);

            // ── 4. gvMain 配置(关键 4 选项)──
            this.gvMain.GridControl = this.gcMain;
            this.gvMain.Name = "gvMain";
            this.gvMain.OptionsBehavior.Editable = false;   // 整表只读
            this.gvMain.OptionsBehavior.ReadOnly = true;
            this.gvMain.OptionsView.ShowGroupPanel = false; // 不显示分组栏
            this.gvMain.OptionsView.ShowAutoFilterRow = true; // 列头筛选(推荐)

            // ── 5. pnlBottom ──
            this.pnlBottom.Dock = DockStyle.Bottom;
            this.pnlBottom.Location = new Point(0, 578);
            this.pnlBottom.Name = "pnlBottom";
            this.pnlBottom.Size = new Size(984, 48);

            // ── 6. Frm 装配 ──
            this.ClientSize = new Size(984, 626);
            this.Controls.Add(this.gcMain);
            this.Controls.Add(this.pnlBottom);   // Bottom 后添加(自动 Dock=Bottom)
            this.MinimumSize = new Size(720, 480);
            this.Name = "Frm_{业务名}List";
            this.Text = "{业务名}列表";
            this.StartPosition = FormStartPosition.CenterScreen;
            this.Load += new EventHandler(this.Frm_{业务名}List_Load);

            // ── 7. 解初始化(顺序:子 → 父)──
            ((ISupportInitialize)(this.gvMain)).EndInit();
            ((ISupportInitialize)(this.gcMain)).EndInit();
            this.pnlBottom.ResumeLayout(false);
            this.ResumeLayout(false);
        }
    }
}
```

**关键点**:
- GridStyle 必须在 `InitializeComponent` **顶部**调用,因为它会监听 Form events
- `gvMain.GridControl = this.gcMain` **双向绑定**(不写只 gvMain 在 gcMain 找不到)
- 4 个 `BeginInit/EndInit` 必须**严格配对**,缺一个会丢事件订阅

### §1.2 TreeList(目录树 / 主从左栏)

```csharp
namespace CSS.WHXL.Extend.UI.{模块}
{
    partial class Frm_{业务名}MasterDetail
    {
        private IContainer components;
        private GridStyle _gridStyle;

        private SplitContainerControl splitContainer1;
        private TreeList  tlMain;
        private GridControl gcDetail;
        private GridView   gvDetail;

        private void InitializeComponent()
        {
            this.components = new Container();

            // TreeList 用单参数 GridStyle 重载
            this._gridStyle = new GridStyle("ASS", this, tlMain);

            this.splitContainer1 = new SplitContainerControl();
            this.tlMain   = new TreeList();
            this.gcDetail = new GridControl();
            this.gvDetail = new GridView();

            ((ISupportInitialize)(this.splitContainer1)).BeginInit();
            ((ISupportInitialize)(this.tlMain)).BeginInit();
            ((ISupportInitialize)(this.gcDetail)).BeginInit();
            ((ISupportInitialize)(this.gvDetail)).BeginInit();
            this.SuspendLayout();

            // ── 切分容器 ──
            this.splitContainer1.Dock = DockStyle.Fill;
            this.splitContainer1.SplitterPosition = 300;  // 左 300px
            this.splitContainer1.Name = "splitContainer1";

            // ── 左:TreeList ──
            this.tlMain.Dock = DockStyle.Fill;
            this.tlMain.Name = "tlMain";
            this.tlMain.OptionsView.ShowAutoFilterRow = true;
            this.tlMain.OptionsView.ShowIndicator = false;
            this.tlMain.OptionsBehavior.Editable = false;
            this.tlMain.OptionsBehavior.EnableFiltering = true;
            this.tlMain.OptionsFilter.FilterMode = FilterMode.Extended;
            this.tlMain.ParentFieldName = "ParentID";  // 与 Entity 对齐
            this.tlMain.KeyFieldName = "ID";

            // ── 右:GridControl ──
            this.gcDetail.Dock = DockStyle.Fill;
            this.gcDetail.MainView = this.gvDetail;
            this.gcDetail.Name = "gcDetail";

            this.gvDetail.GridControl = this.gcDetail;
            this.gvDetail.Name = "gvDetail";
            this.gvDetail.OptionsBehavior.ReadOnly = true;
            this.gvDetail.OptionsView.ShowGroupPanel = false;

            // ── 装配 Panel1/Panel2 ──
            this.splitContainer1.Panel1.Controls.Add(this.tlMain);
            this.splitContainer1.Panel2.Controls.Add(this.gcDetail);

            this.ClientSize = new Size(1200, 700);
            this.Controls.Add(this.splitContainer1);

            this.Name = "Frm_{业务名}MasterDetail";
            this.Text = "{业务名}主从";
            this.StartPosition = FormStartPosition.CenterScreen;

            // ── 事件 ──
            this.tlMain.FocusedNodeChanged += new FocusedNodeChangedEventHandler(this.tlMain_FocusedNodeChanged);

            // ── 解初始化(子 → 父)──
            ((ISupportInitialize)(this.gvDetail)).EndInit();
            ((ISupportInitialize)(this.gcDetail)).EndInit();
            ((ISupportInitialize)(this.tlMain)).EndInit();
            ((ISupportInitialize)(this.splitContainer1)).EndInit();
            this.ResumeLayout(false);
        }
    }
}
```

**vs GridControl 注意**:
- TreeList 的 GridStyle 是**单参数重载**:`GridStyle(string, Form, TreeList)`
- 父/键字段名要**与 Entity 一致**(`ParentFieldName` / `KeyFieldName`)

**主从结构绑定规则**:
- `tlMain.FocusedNodeChanged` → 通知 Presenter 加载从表 → `gcSub.DataSource = list`
- 从表 GridControl 的查询 / 按钮复用 §1.1 的 pnlBottom 模式
- 右栏若需要 Header(pnlRightHeader),按 `Dock=Top` 先 Add、GridControl `Dock=Fill` 后 Add

### §1.3 LayoutControl 表单(单条记录,字段 ≤8)

```csharp
namespace CSS.WHXL.Extend.UI.{模块}
{
    partial class DlgEdit_{业务名}
    {
        private IContainer components;

        private LayoutControl    lcMain;
        private LayoutControlGroup lcgMain;
        private TextEdit         txtCode;
        private TextEdit         txtName;
        private LabelControl     lbcCode;
        private LabelControl     lbcName;
        private Panel            pnlBottom;
        private SimpleButton     btnSave;
        private SimpleButton     btnCancel;

        private void InitializeComponent()
        {
            this.components = new Container();

            this.lcMain     = new LayoutControl();
            this.lcgMain    = new LayoutControlGroup();
            this.txtCode    = new TextEdit();
            this.txtName    = new TextEdit();
            this.lbcCode    = new LabelControl();
            this.lbcName    = new LabelControl();
            this.pnlBottom  = new Panel();
            this.btnSave    = new SimpleButton();
            this.btnCancel  = new SimpleButton();

            ((ISupportInitialize)(this.lcMain)).BeginInit();
            this.lcMain.SuspendLayout();
            this.pnlBottom.SuspendLayout();
            this.SuspendLayout();

            // ── lcMain 根 ──
            this.lcMain.Dock = DockStyle.Fill;
            this.lcMain.Name = "lcMain";
            this.lcMain.Size = new Size(540, 360);

            // ── lcgMain 组 ──
            this.lcgMain.Name = "lcgMain";
            this.lcgMain.TextVisible = false;  // 隐藏 Group 标题

            // ── 字段对(Label + Edit) ──
            this.lbcCode.Text = "编码(&C):";
            this.lbcCode.Name = "lbcCode";
            this.txtCode.Name = "txtCode";
            this.txtCode.Properties.MaxLength = 50;
            this.lcgMain.AddItem(this.lbcCode);  // ← 关键:Label 必须 AddItem
            this.lcgMain.AddItem(this.txtCode);  // ←       Edit 也必须 AddItem

            this.lbcName.Text = "名称(&N):";
            this.lbcName.Name = "lbcName";
            this.txtName.Name = "txtName";
            this.lcgMain.AddItem(this.lbcName);
            this.lcgMain.AddItem(this.txtName);

            this.lcMain.Root = this.lcgMain;  // 必须挂 Root

            // ── pnlBottom ──
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

            // ── Frm 装配 ──
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

            this.btnSave.Click   += new EventHandler(this.btnSave_Click);
            this.btnCancel.Click += new EventHandler(this.btnCancel_Click);

            ((ISupportInitialize)(this.lcMain)).EndInit();
            this.lcMain.ResumeLayout(false);
            this.pnlBottom.ResumeLayout(false);
            this.ResumeLayout(false);
        }
    }
}
```

**LayoutControl 三大要点**:
1. LabelControl **必须** `lcgMain.AddItem(lbcControl)` 添加(不能 `lcMain.Controls.Add`)
2. Edit 也必须 AddItem(这两种用法等价于 LayoutControlItem 包裹)
3. 最后 **必须** `lcMain.Root = lcgMain`,否则不显示

### §1.4 RepositoryItem 套件

> RepositoryItem 让 GridView 列复用编辑器实例。**同一个 `repositoryItemXxx` 可绑给多列。**

#### §1.4.1 RepositoryItemDateEdit(日期列)

```csharp
// Designer 中
private RepositoryItemDateEdit repositoryItemDateEdit1;

// InitializeComponent 中:
this.repositoryItemDateEdit1 = new RepositoryItemDateEdit();

this.repositoryItemDateEdit1.Buttons.AddRange(new EditorButton[] {
    new EditorButton(ButtonPredefines.Combo)
});
this.repositoryItemDateEdit1.Mask.EditMask = "yyyy-MM-dd";
this.repositoryItemDateEdit1.DisplayFormat.FormatString = "yyyy-MM-dd";
this.repositoryItemDateEdit1.DisplayFormat.FormatType = FormatType.DateTime;
this.repositoryItemDateEdit1.EditFormat.FormatString = "yyyy-MM-dd";
this.repositoryItemDateEdit1.EditFormat.FormatType = FormatType.DateTime;
this.repositoryItemDateEdit1.Name = "repositoryItemDateEdit1";

// gcMain 注册(RepositoryItems 必须注册到 gcMain):
this.gcMain.RepositoryItems.AddRange(new RepositoryItem[] {
    this.repositoryItemDateEdit1
});

// 列绑定(运行时或 Designer):
colCreateDate.ColumnEdit = this.repositoryItemDateEdit1;
```

#### §1.4.2 RepositoryItemCheckEdit(布尔列)

```csharp
this.repositoryItemCheckEdit1 = new RepositoryItemCheckEdit();
this.repositoryItemCheckEdit1.ValueChecked = "TRUE";      // 注意:String,非 bool
this.repositoryItemCheckEdit1.ValueUnchecked = "FALSE";
this.repositoryItemCheckEdit1.AllowGrayed = false;        // 不允许三态
this.repositoryItemCheckEdit1.Name = "repositoryItemCheckEdit1";

// 列绑定后,GridView 显示真值为勾选,假值为不勾选
colEnabled.ColumnEdit = this.repositoryItemCheckEdit1;
```

#### §1.4.3 RepositoryItemComboBox(枚举/状态列)

```csharp
this.repositoryItemComboBox1 = new RepositoryItemComboBox();
this.repositoryItemComboBox1.Items.AddRange(new object[] {
    new KeyValuePair<int, string>(0, "未提交"),
    new KeyValuePair<int, string>(1, "已提交"),
    new KeyValuePair<int, string>(2, "已审批")
});
this.repositoryItemComboBox1.Name = "repositoryItemComboBox1";

// 列绑定:
colStatus.ColumnEdit = this.repositoryItemComboBox1;
```

#### §1.4.4 RepositoryItemHyperLinkEdit(超链接列)

```csharp
this.repositoryItemHyperLinkEdit1 = new RepositoryItemHyperLinkEdit();
this.repositoryItemHyperLinkEdit1.Name = "repositoryItemHyperLinkEdit1";

// 列绑定后,事件触发可打开附件或跳转:
colAttachment.ColumnEdit = this.repositoryItemHyperLinkEdit1;
this.gvMain.ShowGridMenu += new ShowGridMenuEventHandler(this.gvMain_ShowGridMenu);
```

### §1.5 SplitContainerControl + DockManager

#### §1.5.1 左右切分(Splitter)

见 §1.2 主从片段(`SplitContainerControl` + `Panel1/Panel2.Controls.Add`)。

#### §1.5.2 DockManager(右侧悬浮面板)

```csharp
private DockManager dmDisplay;
private DockPanel   dpDisplay;

this.dmDisplay = new DockManager(this.components);
this.dmDisplay.Form = this;

this.dpDisplay = new DockPanel();
this.dpDisplay.Dock = DockingStyle.Right;
this.dpDisplay.Options.FloatOnDblClick = false;  // 双击不浮动
this.dpDisplay.Options.ShowCloseButton = false;  // 不显示关闭
this.dpDisplay.Text = "预览面板";
this.dpDisplay.Name = "dpDisplay";

this.dmDisplay.RootPanels.AddRange(new DockPanel[] { this.dpDisplay });

this.ClientSize = new Size(1200, 700);
this.Controls.Add(this.dpDisplay);   // 通常 Dock=Fill
this.Controls.Add(this.gcMain);      // 主区
```

**注意**:`DockManager(this.components)` 接受 IContainer,这是**资源释放**用的。
漏创建 components 会导致 Designer 关闭时 DockManager 不能释放。

### §1.6 XtraTabControl(多标签页)

```csharp
private XtraTabControl xtraTabControl1;
private XtraTabPage    xtraTabPage1;  // 第一个 Tab
private XtraTabPage    xtraTabPage2;  // 第二个 Tab

this.xtraTabControl1 = new XtraTabControl();
this.xtraTabPage1   = new XtraTabPage();
this.xtraTabPage2   = new XtraTabPage();

((ISupportInitialize)(this.xtraTabControl1)).BeginInit();
this.xtraTabControl1.SuspendLayout();

this.xtraTabControl1.Dock = DockStyle.Fill;
this.xtraTabControl1.Name = "xtraTabControl1";

this.xtraTabPage1.Name = "xtraTabPage1";
this.xtraTabPage1.Text = "基本信息";

this.xtraTabPage2.Name = "xtraTabPage2";
this.xtraTabPage2.Text = "明细信息";

this.xtraTabControl1.TabPages.AddRange(new XtraTabPage[] {
    this.xtraTabPage1, this.xtraTabPage2
});

this.xtraTabControl1.SelectedPageChanged += new TabPageChangedEventHandler(this.xtraTabControl1_SelectedPageChanged);

((ISupportInitialize)(this.xtraTabControl1)).EndInit();
this.xtraTabControl1.ResumeLayout(false);
this.ResumeLayout(false);
```

**TabPage 内部控件**:每个 `TabPage` 独立 `Dock=Fill` 装载 TreeList / GridControl,与单独窗体一致。

**多 Tab 绑定规则**:
- 每个 TabPage 内独立 GridControl / LayoutControl,独立绑定到 Presenter
- Tab 之间数据共享靠 Presenter 内的内存缓存,而非 View 层直接共享
- 常见场景:基础资料分「基本信息 / 扩展属性 / 审计日志」多页展示

---

## §2 Deve-CRS(GridStyle = `"CRS"`,基类/数据访问见下表)

> 适用项目:`Deve-CRS` 主线、`HKYL` 子项目、`Jamtc.Extend.CRS.Eqp` 等子模块。
>
> ⚠️ **CRS 家族变体多,下表是「主线风格」参考——必须 Step 0b 扫描确认目标项目走哪种**,不要凭家族名套模式。

### CRS 家族已知变体(实测 2026-07)

| 子项目 | 窗体基类 | 数据访问 | GridStyle | 命名空间特征 |
|--------|---------|---------|-----------|------------|
| **Deve-CRS 主线**(历史参考) | `frm_Base<T>`(泛型) | ORM `DbHelp.Query<T>()` | `"CRS"` / `"HKYL"` | `CSS.{项目}.UI` |
| **Jamtc.Extend.CRS.Eqp**(实测) | `frmBase`(**非泛型**) | `ListOperate` + 少量 ORM | `"CRS"` 主 / `"ASS"` 少数 | `Jamtc.Extend.CRS.Eqp.UI` |

> **主线 vs Eqp 的关键差异**:Eqp 子模块**沿用 Upgrader 风格**(非泛型 frmBase + ListOperate),不是下表描述的泛型 + ORM。Step 0b 扫到 `frm_Base<T>` 计数为 0 → 走 Eqp 变体(等同于 §1 Upgrader 模式 + `"CRS"` 代号)。

### 与 §1 Upgrader 的 5 个关键差异(主线风格;Eqp 子模块见上表)

| # | 维度 | Deve-Upgrader(§1) | Deve-CRS 主线 |
|---|------|-------------------|----------|
| 1 | 窗体基类 | `frmBase`(非泛型) | `frm_Base<T>`(泛型) |
| 2 | View 接口 | `I{业务}View`(普通) | 三层继承链 `I{业务}ViewBase → I{业务}View<T> → I{业务}View`(闭泛型) |
| 3 | 数据访问 | 原始 SQL `SqlOperate+ListOperate` | ORM `_dal.Query<T>().Where(...)` |
| 4 | GridStyle 代号 | `"ASS"` | `"CRS"` / `"HKYL"` |
| 5 | 权限菜单 | 右键菜单手写 `cms.X.Show()` | `AddControlItemGroupConfig(ControlItemGroupConfig)` 注册 |

> ⚠️ **连接名陷阱**:CRS 的 `varlist` 类(如 `Jamtc.Extend.CRS.Eqp.Util.varlist`)是**纯工具类,不持 Conn 属性**。代码中 `varlist.ASSConn` 字符串扫描的命中**几乎全是注释残留**(从 Upgrader 复制后被注释掉的死代码),非注释调用为 0。**直接套用 `varlist.ASSConn` 会编译错**。CRS 的连接名必须扫描其非注释代码或 `App.config` 独立确认。

**基类差异的 Designer 体现**:
```csharp
// Upgrader
public partial class Frm_{业务名}List : frmBase, I{业务名}ListView { ... }

// CRS(泛型)
public partial class frm_{业务名} : frm_Base<{业务名}Info>, I{业务}ListView { ... }
```

注意 CRS 窗体**类名小写**(`frm_xxx`,带下划线),与 Upgrader(`Frm_Xxx`,无下划线)差异。
Designer 文件结构不变,**只是类声明行不同**。

### CRS 独有的 `AddControlItemGroupConfig`

```csharp
// 构造函数或 Form_Load 中
public frm_{业务名}()
{
    InitializeComponent();
    _gridStyle = new GridStyle("CRS", this, gcMain, gvMain);

    // ── 权限菜单注册(仅 CRS)──
    AddControlItemGroupConfig(new ControlItemGroupConfig("默认菜单", cms, gcMain));
    AddControlItemGroupConfig(new ControlItemGroupConfig("操作功能", btnSearch));
    AddControlItemGroupConfig(new ControlItemGroupConfig("操作功能", btnAdd));
    AddControlItemGroupConfig(new ControlItemGroupConfig("操作功能", btnEdit));
    AddControlItemGroupConfig(new ControlItemGroupConfig("操作功能", btnDelete));
}
```

**坑点**:`AddControlItemGroupConfig` 来自 `frm_Base` 基类,不是接口。漏注册 → 菜单不显示 / 按钮禁用状态不对。

---

## §3 EQUP(基类 = `Jamtc.Extend.CRS.Eqp.UI` 系,GridStyle = `"EQP"`)

> 适用项目:`CRS-Equipment` 子模块、`Jamtc.Extend.CRS.Eqp` 框架。
> 与 CRS 差异:基础类名 **多 `Eqp.` 前缀**,且 **`Deve-CRS` 等价风格**(使用 dlgBase/upgrader UI 模式)。

### 3 个差异点

| # | 维度 | Deve-CRS | EQUP |
|---|------|----------|------|
| 1 | 命名空间 | `CSS.{项目}.UI` | `Jamtc.Extend.CRS.Eqp.UI` |
| 2 | 对话框基类 | `dlg_ModifyBase` + 重写 `ok()` | `dlgBase` + 手动 OK/Cancel |
| 3 | 消息提示 | `UICommonBase.ShowMessageBox(MessageType.Message, ...)` | `XtraMessageBox.Show(..., MessageBoxButtons.OK, MessageBoxIcon.Warning)` |

**对话框差异完整示例**(对应 `dialog-patterns.md` 案例 3):

```csharp
// EQUP 版本(dlgBase,手动 Ok/Cancel)
public partial class dlg{业务名} : dlgBase
{
    public dlg{业务名}()
    {
        InitializeComponent();
    }

    private void btnOk_Click(object sender, EventArgs e)
    {
        if (string.IsNullOrEmpty(txtName.Text))
        {
            XtraMessageBox.Show("名称不能为空", "提示",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);  // ← EQUP: XtraMessageBox
            return;
        }
        // ... 业务逻辑(直接操作原始对象,不使用 DeepClone)
        this.DialogResult = DialogResult.OK;
    }
}
```

---

## §4 CSS.WHXL.Extend(基类 = `frmBase`,GridStyle = `"CSS"`)

> 适用项目:`CSS.WHXL.Extend` 主线、`JDDR_MMA_*` 表对应的所有模块。
> **与 Deve-Upgrader (§1) 同源**(基类/数据访问风格相同),但有 4 个**本地差异**。

### 4 个差异

| # | 维度 | Deve-Upgrader(§1) | CSS.WHXL.Extend |
|---|------|-------------------|------------------|
| 1 | DBHelp 实例名 | `varlist.SqlOperate` / `varlist.ListOperate` | `varlist.ASSDBHelp`(自定义封装) |
| 2 | 连接名 | 实测 Upgrader 主导 `varlist.ASSConn`(79%);**CRS 不套用**——CRS 的 `varlist` 是纯工具类不持 Conn,套用会编译错 | 子项目/老模块可能有 `varlist.MainConn` / `varlist.PPMSConn` 等,**以 Step 0b 扫描结果为准(注意过滤注释)** |
| 3 | GridStyle 代号 | `"ASS"` | `"CSS"`(本地代号) |
| 4 | Collection 层 | 直连 DAL | **仍保留 Collection 中间层**(deprecated,新代码不生成) |

**Designer 体现**:GridStyle 字符串从 `"ASS"` 换为 `"CSS"`。

```csharp
this._gridStyle = new GridStyle("CSS", this, gcMain, gvMain);  // ← 只是字符串差异
```

**DAL 文件连接名**:
```csharp
// Deve-Upgrader 主导(实测 79%)
string connName = varlist.ASSConn;   // 以 Step 0b 扫描为准
_so.SqlExcuteNoQuery(sql, connName);

// ⚠️ CRS 子项目不套用此默认——CRS 的 varlist 类是纯工具类,不持 Conn 属性
//    CRS 连接名必须 Step 0b 扫描非注释代码确认(常见为直接字符串字面量)
// 其他子模块:varlist.PPMSConn / varlist.SystemMainDBHelp / varlist.MainConn 等
```

---

## §5 通用坑位预防清单

> 这一节是 7 条最容易踩的 InitializeComponent 错误。生成后必查。

### ❌ 错误 1:`BeginInit` / `EndInit` 不配对

```csharp
((ISupportInitialize)(this.gcMain)).BeginInit();  // ← 写了 Begin
((ISupportInitialize)(this.gcMain)).EndInit();    // ← 漏了 End → 事件丢
```

**正确**:Begin / End **严格 1:1**。先 Begin 所有需要初始化的,后 End 所有(子→父顺序)。
漏 End 常见症状:GridView 数据不显示、CellValueChanged 不触发。

### ❌ 错误 2:`SuspendLayout` / `ResumeLayout` 不配对

```csharp
this.lcMain.SuspendLayout();  // ← 写了
this.lcMain.ResumeLayout(false);  // ← 参数 `false` = 不强制重新布局
```

**正确**:`SuspendLayout → ... → ResumeLayout(false)` 配对。
**结尾**必须 `this.ResumeLayout(false)`,这是 Form 根。

### ❌ 错误 3:`gvMain.GridControl = this.gcMain` 漏写

只写 `this.gcMain.MainView = this.gvMain`,**不写** `this.gvMain.GridControl = this.gcMain`。
**两个都要写**(互相绑定)。DevExpress 双向要求。

### ❌ 错误 4:LayoutControl 不挂 Root

```csharp
this.lcgMain.Name = "lcgMain";
// ... 漏了这一行
this.lcMain.Root = this.lcgMain;   // ← 必须挂,否则不显示
```

### ❌ 错误 5:LayoutControl 子控件用 `Controls.Add` 而非 `lcgMain.AddItem`

```csharp
this.lcMain.Controls.Add(this.txtCode);  // ❌ 不显示
this.lcgMain.AddItem(this.txtCode);      // ✅ 显示
```

### ❌ 错误 6:GridStyle 在 InitializeComponent 中段调用

```csharp
// ❌ 在中间
this.gcMain = new GridControl();
this._gridStyle = new GridStyle("ASS", this, gcMain);  // ← 后置
this.gvMain = new GridView();

// ✅ 在最前
this._gridStyle = new GridStyle("ASS", this, gcMain, gvMain);  // ← 必须在顶部
this.gcMain = new GridControl();
this.gvMain = new GridView();
```

GridStyle 会 hook Form 事件,在实例化前调用会报 NullRef。

### ❌ 错误 7:`.csproj` 缺注册(Designer 文件编译不到)

```xml
<Compile Include="Frm_{业务名}List.cs">
  <SubType>Form</SubType>
</Compile>
<Compile Include="Frm_{业务名}List.Designer.cs">
  <DependentUpon>Frm_{业务名}List.cs</DependentUpon>
</Compile>
<EmbeddedResource Include="Frm_{业务名}List.resx">
  <DependentUpon>Frm_{业务名}List.cs</DependentUpon>
</EmbeddedResource>
```

漏注册任何一个 → 编译报错「未找到类 Frm_xxx」或「resx 未包含」。

---

## §6 选择指南(快速决策)

**问**:这次要生成什么样的 Designer?

| 问题 | 答案 → 章节 |
|------|------------|
| 单表 CRUD 列表(查询 + 列表 + 按钮) | §1.1 + §1.4(RepositoryItem) |
| 左树 + 右列表(主从联动) | §1.2(TreeList + SplitContainer) |
| 单条记录的编辑对话框 | §1.3(LayoutControl) |
| 含多 Tab(基本 + 明细) | §1.6 + §1.1(每个 Tab 独立) |
| 主从结构(分类树 + 下属列表) | §1.2(已含主从绑定规则) |
| 业务分组多视图(多 Tab 切换) | §1.6(已含多 Tab 绑定规则) |
| 右侧 DockPanel 浮动预览 | §1.5.2(DockManager) |
| 项目是 Deve-CRS 主线(泛型) | 全 §1 + §2 主线差异点 |
| 项目是 CRS.Eqp 子模块(非泛型) | 全 §1 + §2 Eqp 变体(GridStyle="CRS",其余同 Upgrader) |
| 项目是 EQUP | 全 §1 + §3 差异点 |
| 项目是 CSS.WHXL.Extend | 全 §1 + §4 差异点(GridStyle="CSS") |

---

## §7 维护指南

新增 designer 模式时:
1. 实战验证完整可编译(用 `references/designer-template-{a\|b}.md` 风格生成,或本文件 §1 对应场景,然后 MSBuild 通过)
2. 在 §0 索引表加一行
3. 给本文件加 GitHub 风格的 commit:
   ```
   feat(designer-patterns): 新增 XxxControl 场景
   ```
4. 同步在 `failure-modes.md` 补充对应"踩坑→沉淀"案例
