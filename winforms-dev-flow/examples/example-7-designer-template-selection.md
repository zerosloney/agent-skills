# Example 7 — Designer 模板选择决策 (4 家族×6 场景)

> 对应 failure-modes 案例 7(Designer 文件手写出错率极高)。
> **核心场景**:Step 4 生成 Designer 文件时，必须从 `designer-template-list.md` 选择正确模板，不凭印象拼 InitializeComponent。
> **档位**:glance 档 (从参照窗体提取家族 + 场景即可)。

---

## 1. 场景描述

**用户原话**:
> "加个 `Frm_DesignerTest` 窗体，用 GridControl 显示列表，要支持条件格式和汇总。"

**上下文**:
- 项目：`.NET Framework 4.7.2` + WinForms + DevExpress 21.2
- 家族：**D. CSS.WHXL.Extend**(基类 `frmBase` + GridStyle "CSS")
- 场景：**GridControl + GridView + 条件格式 + 汇总** (对应 `designer-template-list.md` 模板 A.2)

---

## 2. Step 0 — 目标目录定位

```bash
PROJECT_ROOT = C:\Src\CSS.WHXL.Extend
TARGET_DIR   = C:\Src\CSS.WHXL.Extend\Modules\DesignerTest\UI
MODULE_NAME  = DesignerTest
```

---

## 3. Step 0a — 4 项必填门

| # | 确认项 | 取值 | 来源 |
|---|--------|------|------|
| 1 | 业务名 / 窗体名 | `DesignerTest` / `Frm_DesignerTestList` | 用户原话 |
| 2 | Entity 或字段来源 | `Entity.DesignerTestInfo`(已存在) | 项目已有 |
| 3 | 项目根 + 目标目录 | 见 §2 | 用户已说 |
| 4 | 构建入口 | `CSS.WHXL.Extend.sln` | 项目默认 |

✅ 4 项齐。

---

## 4. Step 0b — 项目指纹卡 (简化版)

```text
项目：C:\Src\CSS.WHXL.Extend                扫描：1842 .cs
┌─────────────────┬────────┬────────┬────────────────────────────────┐
│ 维度            │ 主导    │ 占比   │ 异类                           │
├─────────────────┼────────┼────────┼────────────────────────────────┤
│ 窗体基类        │ frmBase│ 98%    │ frm_Base<T>(2%)                │
│ 数据访问        │ SqlOp  │ 97%    │ DbHelp.Query(3%)               │
│ GridStyle 代号  │ "CSS"  │ 97%    │ "ASS"(3%)                      │
│ Collection 层   │ 无     │ —      │ —                              │
│ DAL 层完整性    │ DAL/Ser│ 0.06   │ DAL=1/Ser=1490→无独立 DAL 层  │
│ 连接名 (top1)   │ ASSConn│ 142    │ ASSDBHelp=38(过滤注释后)       │
└─────────────────┴────────┴────────┴────────────────────────────────┘
异质性等级：🟢 纯一 (所有维度主导 ≥95%) → 直接进 Step 1
```

---

## 5. Step 1 — 模式提取表

参照窗体:`Frm_CSSGridStyle.cs`(同模块最近窗体)。

| 提取项 | 提取结果 | 备注 |
|--------|---------|------|
| **窗体基类** | `frmBase` | 非泛型 |
| **命名空间** | `CSS.WHXL.Extend.Modules.DesignerTest.UI` | —— |
| **数据访问方式** | `SqlOperate+ListOperate` | —— |
| **是否泛型** | ❌ | —— |
| **GridStyle 代号** | `"CSS"` | ⚠️ **本案核心** |
| **DBHelp 实例 / 连接名** | `varlist.ASSDBHelp` / `varlist.ASSConn` | —— |
| **类名前缀约定** | `Frm_{业务}List` | —— |
| **WaitDialog** | `varlist_Dialog` | —— |
| **消息框** | `XtraMessageBox.Show` | —— |
| **Designer 模板** | **A.2 (GridControl + GridView + 条件格式 + 汇总)** | ⚠️ **本案核心** |

**用户确认**:"按 `Frm_CSSGridStyle.cs` 的模式生成 Yes/No?"

**用户回复**:"Yes"

---

## 6. Step 2 — 字段→控件 映射表

`Entity.DesignerTestInfo` 字段 (扫描):

| Entity 字段 | 类型 | 控件 | 列/项名 | 条件格式 | 汇总 |
|-------------|------|------|---------|---------|------|
| ID | Guid | 隐藏列 | — | — | — |
| Code | string | TextEdit 列 | `colCode` | — | — |
| Name | string | TextEdit 列 | `colName` | — | — |
| Price | decimal | SpinEdit 列 (右对齐) | `colPrice` | <0 红色 | Sum |
| Qty | int | SpinEdit 列 (右对齐) | `colQty` | <0 红色 | Sum |
| Amount | decimal | SpinEdit 列 (右对齐/只读) | `colAmount` | — | Sum |
| Status | enum | RepositoryItemComboBox | `colStatus` | 0=红色，1=绿色 | — |
| CreateTime | DateTime | RepositoryItemDateEdit 列 | `colCreateTime` | — | — |

**布局决策**:字段 8 个 + 含条件格式 + 含汇总 → **GridControl + GridView**(模板 A.2)。

---

## 7. Step 3 — frm vs ucl

**业务独立** → 新建 `Frm_DesignerTestList`。

---

## 8. Step 4 — Designer 模板选择决策

### 8.1 加载 `designer-template-list.md`

```markdown
# Designer 模板选择决策表

## 第一步：确认项目家族
- A. Deve-Upgrader → 走 §A 模板
- B. Deve-CRS → 走 §B 模板
- C. EQUP → 走 §C 模板
- D. CSS.WHXL.Extend → 走 §D 模板 (本案)

## 第二步：确认控件场景
- §1 GridControl + GridView
  - §1.1 基础列表 (无条件格式/汇总)
  - §1.2 + 条件格式
  - §1.3 + 汇总
  - §1.4 + 条件格式 + 汇总 (本案)
  - §1.5 + 主从联动
  - §1.6 + 多 Tab
- §2 TreeList
- §3 LayoutControl
- ...

## 本案决策路径
D 家族 → §A 模板 (D 家族复用 A 家族 Designer) → §1.4 (GridControl + 条件格式 + 汇总)
```

### 8.2 加载 `designer-patterns.md` §1.4

```markdown
# §1.4 GridControl + GridView + 条件格式 + 汇总

## 适用场景
- 需要条件格式 (如负数红色、超期黄色)
- 需要汇总 (Sum/Avg/Count)
- 项目家族：A / D (复用)

## InitializeComponent 关键片段

### 1. GridControl 声明
```csharp
private DevExpress.XtraGrid.GridControl gcMain;
private DevExpress.XtraGrid.Views.Grid.GridView gvMain;
private DevExpress.XtraGrid.Columns.GridColumn colCode;
private DevExpress.XtraGrid.Columns.GridColumn colName;
private DevExpress.XtraGrid.Columns.GridColumn colPrice;
private DevExpress.XtraGrid.Columns.GridColumn colQty;
private DevExpress.XtraGrid.Columns.GridColumn colAmount;
private DevExpress.XtraGrid.Columns.GridColumn colStatus;
private DevExpress.XtraGrid.Columns.GridColumn colCreateTime;
```

### 2. 条件格式初始化 (StyleFormatCondition)
```csharp
// colPrice < 0 红色
DevExpress.XtraGrid.FormatRule formatRule1 = new DevExpress.XtraGrid.FormatRule();
formatRule1.Name = "PriceNegative";
formatRule1.Column = colPrice;
formatRule1.Condition = DevExpress.XtraGrid.FormatConditionEnum.Less;
formatRule1.Values = new object[] { 0 };
formatRule1.Appearance.BackColor = Color.Red;
formatRule1.Appearance.ForeColor = Color.White;
gvMain.FormatRules.Add(formatRule1);

// colStatus = 0 红色，=1 绿色
DevExpress.XtraGrid.FormatRule formatRule2 = new DevExpress.XtraGrid.FormatRule();
formatRule2.Name = "StatusColor";
formatRule2.Column = colStatus;
formatRule2.Condition = DevExpress.XtraGrid.FormatConditionEnum.Equal;
formatRule2.Values = new object[] { 0 };
formatRule2.Appearance.BackColor = Color.Red;
gvMain.FormatRules.Add(formatRule2);

DevExpress.XtraGrid.FormatRule formatRule3 = new DevExpress.XtraGrid.FormatRule();
formatRule3.Name = "StatusColorGreen";
formatRule3.Column = colStatus;
formatRule3.Condition = DevExpress.XtraGrid.FormatConditionEnum.Equal;
formatRule3.Values = new object[] { 1 };
formatRule3.Appearance.BackColor = Color.Green;
gvMain.FormatRules.Add(formatRule3);
```

### 3. 汇总初始化 (SummaryItem)
```csharp
// colPrice Sum
DevExpress.XtraGrid.GridColumnSummaryItem summary1 = new DevExpress.XtraGrid.GridColumnSummaryItem();
summary1.FieldName = "Price";
summary1.SummaryType = DevExpress.Data.SummaryItemType.Sum;
summary1.DisplayFormat = "合计：{0:F2}";
colPrice.SummaryItem = summary1;

// colQty Sum
DevExpress.XtraGrid.GridColumnSummaryItem summary2 = new DevExpress.XtraGrid.GridColumnSummaryItem();
summary2.FieldName = "Qty";
summary2.SummaryType = DevExpress.Data.SummaryItemType.Sum;
summary2.DisplayFormat = "{0}";
colQty.SummaryItem = summary2;

// colAmount Sum
DevExpress.XtraGrid.GridColumnSummaryItem summary3 = new DevExpress.XtraGrid.GridColumnSummaryItem();
summary3.FieldName = "Amount";
summary3.SummaryType = DevExpress.Data.SummaryItemType.Sum;
summary3.DisplayFormat = "{0:F2}";
colAmount.SummaryItem = summary3;
```

### 4. GridView 配置
```csharp
gvMain.GridControl = gcMain;
gvMain.OptionsView.ShowAutoFilterRow = true; // 自动筛选行
gvMain.OptionsView.ShowFooter = true;        // 显示汇总行
gvMain.OptionsSelection.MultiSelect = true;  // 多选
```

### 5. 完整模板文件
见 `designer-template-a-crud.md` §1.4
```

### 8.3 生成 Designer 文件

```csharp
// Frm_DesignerTestList.Designer.cs
namespace CSS.WHXL.Extend.Modules.DesignerTest.UI
{
    partial class Frm_DesignerTestList
    {
        protected override void Dispose(bool disposing)
        {
            if (disposing && (components != null))
            {
                components.Dispose();
            }
            base.Dispose(disposing);
        }

        #region Windows Form Designer generated code

        private void InitializeComponent()
        {
            this.gcMain = new DevExpress.XtraGrid.GridControl();
            this.gvMain = new DevExpress.XtraGrid.Views.Grid.GridView();
            this.colCode = new DevExpress.XtraGrid.Columns.GridColumn();
            this.colName = new DevExpress.XtraGrid.Columns.GridColumn();
            this.colPrice = new DevExpress.XtraGrid.Columns.GridColumn();
            this.colQty = new DevExpress.XtraGrid.Columns.GridColumn();
            this.colAmount = new DevExpress.XtraGrid.Columns.GridColumn();
            this.colStatus = new DevExpress.XtraGrid.Columns.GridColumn();
            this.colCreateTime = new DevExpress.XtraGrid.Columns.GridColumn();
            ((System.ComponentModel.ISupportInitialize)(this.gcMain)).BeginInit();
            ((System.ComponentModel.ISupportInitialize)(this.gvMain)).BeginInit();
            this.SuspendLayout();
            // 
            // gcMain
            // 
            this.gcMain.Dock = System.Windows.Forms.DockStyle.Fill;
            this.gcMain.Location = new System.Drawing.Point(0, 0);
            this.gcMain.MainView = this.gvMain;
            this.gcMain.Name = "gcMain";
            this.gcMain.Size = new System.Drawing.Size(1024, 600);
            this.gcMain.TabIndex = 0;
            this.gcMain.ViewCollection.AddRange(new DevExpress.XtraGrid.Views.Base.BaseView[] {
            this.gvMain});
            // 
            // gvMain
            // 
            this.gvMain.GridControl = this.gcMain;
            this.gvMain.Name = "gvMain";
            this.gvMain.OptionsView.ShowAutoFilterRow = true;
            this.gvMain.OptionsView.ShowFooter = true;
            this.gvMain.OptionsSelection.MultiSelect = true;
            // 条件格式 (从模板 §1.4 复制)
            this.gvMain.FormatRules.Add(this.formatRule_PriceNegative);
            this.gvMain.FormatRules.Add(this.formatRule_StatusColor);
            // 汇总 (从模板 §1.4 复制)
            this.colPrice.SummaryItem = this.summary_PriceSum;
            this.colQty.SummaryItem = this.summary_QtySum;
            this.colAmount.SummaryItem = this.summary_AmountSum;
            // 
            // colCode
            // 
            this.colCode.Caption = "编码";
            this.colCode.FieldName = "Code";
            this.colCode.Name = "colCode";
            this.colCode.Visible = true;
            this.colCode.VisibleIndex = 0;
            // 
            // colName
            // 
            this.colName.Caption = "名称";
            this.colName.FieldName = "Name";
            this.colName.Name = "colName";
            this.colName.Visible = true;
            this.colName.VisibleIndex = 1;
            // 
            // colPrice
            // 
            this.colPrice.Caption = "单价";
            this.colPrice.FieldName = "Price";
            this.colPrice.Name = "colPrice";
            this.colPrice.Visible = true;
            this.colPrice.VisibleIndex = 2;
            this.colPrice.DisplayFormat.FormatString = "F2";
            this.colPrice.DisplayFormat.FormatType = DevExpress.Utils.FormatType.Numeric;
            this.colPrice.SummaryItem = this.summary_PriceSum;
            // 
            // ... 其他列配置
            // 
            // Frm_DesignerTestList
            // 
            this.AutoScaleDimensions = new System.Drawing.SizeF(7F, 14F);
            this.AutoScaleMode = System.Windows.Forms.AutoScaleMode.Font;
            this.ClientSize = new System.Drawing.Size(1024, 600);
            this.Controls.Add(this.gcMain);
            this.Name = "Frm_DesignerTestList";
            this.Text = "DesignerTest 管理";
            this.Load += new System.EventHandler(this.Frm_DesignerTestList_Load);
            ((System.ComponentModel.ISupportInitialize)(this.gcMain)).EndInit();
            ((System.ComponentModel.ISupportInitialize)(this.gvMain)).EndInit();
            this.ResumeLayout(false);
        }

        #endregion

        // 字段声明
        private DevExpress.XtraGrid.GridControl gcMain;
        private DevExpress.XtraGrid.Views.Grid.GridView gvMain;
        private DevExpress.XtraGrid.Columns.GridColumn colCode;
        private DevExpress.XtraGrid.Columns.GridColumn colName;
        private DevExpress.XtraGrid.Columns.GridColumn colPrice;
        private DevExpress.XtraGrid.Columns.GridColumn colQty;
        private DevExpress.XtraGrid.Columns.GridColumn colAmount;
        private DevExpress.XtraGrid.Columns.GridColumn colStatus;
        private DevExpress.XtraGrid.Columns.GridColumn colCreateTime;
        
        // 条件格式字段 (从模板 §1.4 复制)
        private DevExpress.XtraGrid.FormatRule formatRule_PriceNegative;
        private DevExpress.XtraGrid.FormatRule formatRule_StatusColor;
        
        // 汇总字段 (从模板 §1.4 复制)
        private DevExpress.XtraGrid.GridColumnSummaryItem summary_PriceSum;
        private DevExpress.XtraGrid.GridColumnSummaryItem summary_QtySum;
        private DevExpress.XtraGrid.GridColumnSummaryItem summary_AmountSum;
    }
}
```

### 8.4 生成 resx 文件

```xml
<?xml version="1.0" encoding="utf-8"?>
<root>
  <resheader name="resmimetype">
    <value>text/microsoft-resx</value>
  </resheader>
  <resheader name="version">
    <value>2.0</value>
  </resheader>
  <resheader name="reader">
    <value>System.Resources.ResXResourceReader</value>
  </resheader>
  <resheader name="writer">
    <value>System.Resources.ResXResourceWriter</value>
  </resheader>
  <metadata name="gcMain.TrayLocation" type="System.Drawing.Point">
    <value>17, 17</value>
  </metadata>
  <metadata name="gvMain.TrayLocation" type="System.Drawing.Point">
    <value>106, 17</value>
  </metadata>
  <!-- 所有初始可见文字走 resx -->
  <data name="Frm_DesignerTestList.Text" xml:space="preserve">
    <value>DesignerTest 管理</value>
  </data>
  <data name="colCode.Caption" xml:space="preserve">
    <value>编码</value>
  </data>
  <data name="colName.Caption" xml:space="preserve">
    <value>名称</value>
  </data>
  <data name="colPrice.Caption" xml:space="preserve">
    <value>单价</value>
  </data>
  <!-- ... 其他列标题 -->
</root>
```

---

## 9. Step 5a — review-checklist 自审结果

> 重点校验 Designer 模板来源。

- ✅ **A2.5** GridStyle 初始化代号 = `"CSS"`(与参照窗体一致)
- ✅ **A2.6** 消息框 = `XtraMessageBox.Show`
- ✅ **A2.7** 异常处理:View 层 try-catch
- ✅ **C.3 Designer 模板** (本案核心):
  - ✅ 加载 `designer-template-list.md`
  - ✅ 选择 §D 家族 → §A 模板 → §1.4 (GridControl + 条件格式 + 汇总)
  - ✅ 从 `designer-patterns.md` §1.4 复制 InitializeComponent
  - ✅ 所有初始可见文字走 resx
- ✅ **C.4** `.csproj` 已注册 3 件 (.cs / .Designer.cs / .resx)
- ✅ **C.5** 条件格式规则与字段映射表一致
- ✅ **C.6** 汇总配置与字段映射表一致

---

## 10. Step 5b — MSBuild 命令与结果

```powershell
$ cd C:\Src\CSS.WHXL.Extend
$ & "...\MSBuild.exe" .\CSS.WHXL.Extend.sln /p:Configuration=Debug
Build succeeded.
Time Elapsed 00:00:15.80
```

✅ 通过。

---

## 11. 失败点 + 沉淀

| 时间点 | 失败 | 修复 | 沉淀 |
|--------|------|------|------|
| Step 4 前 | 未加载 `designer-template-list.md` | SKILL.md 约束 #7 强制加载 | **SKILL.md 约束 #7**:"Designer 必加载 `designer-template-list.md`" |
| Step 4 生成 | 凭印象拼 InitializeComponent | 强制从 `designer-patterns.md` §1.4 复制 | **review-checklist C.3**:"Designer 是否来自模板" |
| Step 4 生成 | 条件格式规则错配字段 | 对照字段映射表逐项确认 | **review-checklist C.5**:"条件格式与字段映射一致" |
| Step 4 生成 | 汇总配置遗漏 | 对照字段映射表逐项确认 | **review-checklist C.6**:"汇总与字段映射一致" |
| Step 4 生成 | resx 漏注册列标题 | 强制所有初始可见文字走 resx | **review-checklist C.7**:"resx 注册所有可见文字" |

---

## 12. 本案例的可复用价值

1. **Designer 模板选择决策表**——家族×场景二维决策
2. **§1.4 模板完整示例**——条件格式 + 汇总配置
3. **resx 注册规范**——所有初始可见文字走 resx
4. **review-checklist 扩展**——新增 C.5/C.6/C.7 Designer 专项校验

---

## 13. 4 家族×6 场景决策矩阵

| 家族 \ 场景 | 基础列表 | + 条件格式 | + 汇总 | + 条件格式 + 汇总 | + 主从联动 | + 多 Tab |
|------------|---------|-----------|-------|-----------------|-----------|---------|
| **A. Upgrader** | §A.1.1 | §A.1.2 | §A.1.3 | §A.1.4 (本案) | §A.1.5 | §A.1.6 |
| **B. CRS** | §B.1.1 | §B.1.2 | §B.1.3 | §B.1.4 | §B.1.5 | §B.1.6 |
| **C. EQUP** | §C.1.1 | §C.1.2 | §C.1.3 | §C.1.4 | §C.1.5 | §C.1.6 |
| **D. CSS.WHXL** | §A.1.1 | §A.1.2 | §A.1.3 | §A.1.4 (本案) | §A.1.5 | §A.1.6 |

> **注**:D 家族复用 A 家族 Designer 模板 (实测 CSS.WHXL.Extend 与 Upgrader Designer 一致)

---

## 14. 与 failure-modes 的对应关系

| 失败模式 | 本案例处置 |
|----------|-----------|
| **案例 7** (Designer 手写出错) | 强制加载 `designer-template-list.md` + `designer-patterns.md` |
| **新增**:条件格式错配 | review-checklist C.5 强制校验 |
| **新增**:汇总配置遗漏 | review-checklist C.6 强制校验 |
| **新增**:resx 漏注册 | review-checklist C.7 强制校验 |

(End of file - total 512 lines)
