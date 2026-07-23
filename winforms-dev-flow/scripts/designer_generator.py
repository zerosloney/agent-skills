#!/usr/bin/env python3
"""designer_generator.py — Designer 片段自动组合引擎 (P3)

解决的问题:
    Step 4 生成 Designer 时,Agent 需要根据「项目家族 × 场景 × 实体字段」
    拼装 InitializeComponent。设计器-patterns.md 有 713 行片段,
    本脚本根据参数自动组装成完整的 InitializeComponent() 草稿。

用法:
    # 生成 Upgrader + GridControl + 3 个字段的草稿
    python scripts/designer_generator.py generate \\
        --family upgrader --scenario grid \\
        --entity-name "PartsInfo" --form-name "Frm_PartsList" \\
        --fields "ID=Guid,Name=string,Status=int,CreateTime=DateTime"

    # CRS + TreeList 主从
    python scripts/designer_generator.py generate \\
        --family crs --scenario tree \\
        --entity-name "CategoryInfo" --form-name "frm_category" \\
        --fields "ID=Guid,Name=string,ParentID=Guid?"

    # 列出支持的家族和场景
    python scripts/designer_generator.py list-families
    python scripts/designer_generator.py list-scenarios
"""

import argparse
import sys
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ─── 枚举 ──────────────────────────────────────────────────────────────────

class Family(str, Enum):
    UPGRADER = "upgrader"
    CRS = "crs"
    EQUP = "equp"
    CSS = "css"


class Scenario(str, Enum):
    GRID = "grid"            # GridControl + GridView (CRUD 列表)
    TREE = "tree"            # TreeList (目录树 / 主从)
    LAYOUT = "layout"        # LayoutControl 表单 (≤8 字段)


class FieldType(str, Enum):
    GUID = "Guid"
    STRING = "string"
    INT = "int"
    DECIMAL = "decimal"
    DATETIME = "DateTime"
    BOOL = "bool"


# ─── 数据模型 ──────────────────────────────────────────────────────────────

@dataclass
class EntityField:
    """实体字段定义。"""
    name: str
    field_type: FieldType
    is_primary_key: bool = False
    caption: str = ""
    max_length: int = 50
    display_format: str = ""

    @property
    def control_type(self) -> str:
        if self.field_type == FieldType.GUID:
            return "hidden"  # 不展示
        elif self.field_type == FieldType.STRING:
            if self.max_length > 200:
                return "MemoEdit"
            return "TextEdit"
        elif self.field_type in (FieldType.INT, FieldType.DECIMAL):
            return "SpinEdit"
        elif self.field_type == FieldType.DATETIME:
            return "DateEdit"
        elif self.field_type == FieldType.BOOL:
            return "CheckEdit"
        return "TextEdit"

    @property
    def grid_column_type(self) -> str:
        if self.field_type == FieldType.GUID:
            return "hidden"
        elif self.field_type == FieldType.BOOL:
            return "CheckEdit"
        elif self.field_type in (FieldType.INT, FieldType.DECIMAL):
            return "numeric"
        elif self.field_type == FieldType.DATETIME:
            return "date"
        return "text"


@dataclass
class GenerationContext:
    """生成上下文，贯穿整个生成过程。"""
    family: Family
    scenario: Scenario
    entity_name: str
    form_name: str
    fields: list[EntityField]
    namespace_prefix: str = ""
    gridstyle_code: str = "ASS"
    base_class: str = "frmBase"
    is_generic: bool = False
    form_type: str = "list"  # list / detail / masterdetail


# ─── 家族配置 ──────────────────────────────────────────────────────────────

_FAMILY_CONFIGS = {
    Family.UPGRADER: {
        "namespace_prefix": "CSS.WHXL.Extend.UI",
        "gridstyle_code": "ASS",
        "base_class": "frmBase",
        "is_generic": False,
        "form_name_prefix": "Frm_",
        "form_name_suffix": "List",
        "gridstyle_call": 'new GridStyle("{gs}", this, gcMain, gvMain)',
        "view_interface": "I{entity}View",
        "presenter_class": "{entity}Presenter",
        "ser_class": "{entity}Ser",
    },
    Family.CRS: {
        "namespace_prefix": "CSS.{project}.UI",
        "gridstyle_code": "CRS",
        "base_class": "frm_Base<T>",
        "is_generic": True,
        "form_name_prefix": "frm_",
        "form_name_suffix": "",
        "gridstyle_call": 'new GridStyle("{gs}", this, gcMain, gvMain)',
        "view_interface": "I{entity}View",
        "presenter_class": "{entity}PresenterBase<T>",
        "ser_class": "{entity}SerBase<T>",
    },
    Family.EQUP: {
        "namespace_prefix": "Jamtc.Extend.CRS.Eqp.UI",
        "gridstyle_code": "EQP",
        "base_class": "Jamtc.Extend.CRS.Eqp.UI.frmBase",
        "is_generic": False,
        "form_name_prefix": "Frm_",
        "form_name_suffix": "List",
        "gridstyle_call": 'new GridStyle("{gs}", this, gcMain, gvMain)',
        "view_interface": "I{entity}View",
        "presenter_class": "{entity}Presenter",
        "ser_class": "{entity}Ser",
    },
    Family.CSS: {
        "namespace_prefix": "CSS.WHXL.Extend.UI",
        "gridstyle_code": "CSS",
        "base_class": "frmBase",
        "is_generic": False,
        "form_name_prefix": "Frm_",
        "form_name_suffix": "List",
        "gridstyle_call": 'new GridStyle("{gs}", this, gcMain, gvMain)',
        "view_interface": "I{entity}View",
        "presenter_class": "{entity}Presenter",
        "ser_class": "{entity}Ser",
    },
}


# ─── 字段 → 控件映射 ───────────────────────────────────────────────────────

def field_to_column_declaration(field: EntityField, index: int) -> tuple[str, str, str]:
    """返回 (字段声明, 初始化代码, AddRange 引用)。"""
    col_name = f"col{field.name[0].upper()}{field.name[1:]}"
    declaration = f"private DevExpress.XtraGrid.Columns.GridColumn {col_name};"

    init_lines = [
        f"this.{col_name} = new DevExpress.XtraGrid.Columns.GridColumn();",
        f"this.{col_name}.Caption = \"{field.caption or field.name}\";",
        f"this.{col_name}.FieldName = \"{field.name}\";",
    ]

    if field.field_type == FieldType.GUID:
        init_lines.append(f"this.{col_name}.Visible = false;")
        init_lines.append(f"this.{col_name}.VisibleIndex = -1;")
    else:
        init_lines.append(f"this.{col_name}.Visible = true;")
        init_lines.append(f"this.{col_name}.VisibleIndex = {index};")

    # 类型特定配置
    if field.field_type == FieldType.DATETIME:
        fmt = field.display_format or "yyyy-MM-dd HH:mm"
        init_lines.append(f"this.{col_name}.DisplayFormat.FormatString = \"{fmt}\";")
        init_lines.append(f"this.{col_name}.DisplayFormat.FormatType = DevExpress.Utils.FormatType.DateTime;")
    elif field.field_type in (FieldType.INT, FieldType.DECIMAL):
        fmt = field.display_format or "N2"
        init_lines.append(f"this.{col_name}.DisplayFormat.FormatString = \"{fmt}\";")
        init_lines.append(f"this.{col_name}.DisplayFormat.FormatType = DevExpress.Utils.FormatType.Numeric;")
        init_lines.append(f"this.{col_name}.AppearanceCell.TextOptions.HAlignment = DevExpress.Utils.HorzAlignment.Far;")
    elif field.field_type == FieldType.BOOL:
        init_lines.append(f"this.{col_name}.ColumnEdit = new DevExpress.XtraEditors.Repository.RepositoryItemCheckEdit();")
    elif field.field_type == FieldType.STRING and field.max_length > 200:
        init_lines.append(f"this.{col_name}.ColumnEdit = new DevExpress.XtraEditors.Repository.RepositoryItemMemoEdit();")

    return declaration, "\n".join(init_lines), f"this.{col_name}"


def field_to_layout_item(field: EntityField, idx: int) -> str:
    """生成 LayoutControl 表单项（Label + Editor）。"""
    ctrl_name = f"{field.control_type[0].lower()}{field.control_type[1:]}{field.name[0].upper()}{field.name[1:]}"
    label_name = f"lbc{field.name[0].upper()}{field.name[1:]}"

    lines = [
        f"private DevExpress.XtraEditors.{field.control_type} {ctrl_name};",
        f"private DevExpress.XtraEditors.LabelControl {label_name};",
        "",
        f"this.{label_name} = new DevExpress.XtraEditors.LabelControl();",
        f"this.{label_name}.Text = \"{field.caption or field.name}:\";",
        f"this.{label_name}.Name = \"{label_name}\";",
        f"this.{ctrl_name} = new DevExpress.XtraEditors.{field.control_type}();",
        f"this.{ctrl_name}.Name = \"{ctrl_name}\";",
    ]

    # 类型特定配置
    if field.field_type == FieldType.STRING:
        lines.append(f"this.{ctrl_name}.Properties.MaxLength = {field.max_length};")
    elif field.field_type in (FieldType.INT, FieldType.DECIMAL):
        lines.append(f"this.{ctrl_name}.Properties.DisplayFormat.FormatString = \"N2\";")
        if field.field_type == FieldType.DECIMAL:
            lines.append(f"this.{ctrl_name}.Properties.EditFormat.FormatString = \"N2\";")
    elif field.field_type == FieldType.DATETIME:
        fmt = field.display_format or "yyyy-MM-dd"
        lines.append(f"this.{ctrl_name}.Properties.Mask.EditMask = \"{fmt}\";")
        lines.append(f"this.{ctrl_name}.Properties.Mask.UseMaskAsDisplayFormat = true;")
        lines.append(f"this.{ctrl_name}.Properties.VistaDisplayMode = DevExpress.Utils.DefaultBoolean.True;")
    elif field.field_type == FieldType.BOOL:
        lines.append(f"this.{ctrl_name}.Properties.Caption = \"\";")
        lines.append(f"this.{ctrl_name}.Properties.ValueChecked = true;")
        lines.append(f"this.{ctrl_name}.Properties.ValueUnchecked = false;")
    elif field.field_type == FieldType.GUID:
        pass  # 不展示

    if field.field_type != FieldType.GUID:
        lines.append(f"this.lcgMain.AddItem(this.{label_name});")
        lines.append(f"this.lcgMain.AddItem(this.{ctrl_name});")

    return "\n".join(lines)


# ─── 场景生成器 ─────────────────────────────────────────────────────────────

def _generate_grid_scenario(ctx: GenerationContext) -> str:
    """GridControl + GridView 场景。"""
    cfg = _FAMILY_CONFIGS[ctx.family]
    gs = ctx.gridstyle_code or cfg["gridstyle_code"]

    # 字段过滤：跳过 GUID 主键
    display_fields = [f for f in ctx.fields if f.field_type != FieldType.GUID]

    # 列声明 + 初始化（分离：字段声明在类体，初始化在 InitializeComponent）
    column_decls: list[str] = []
    column_inits: list[str] = []
    col_refs: list[str] = []
    for i, f in enumerate(display_fields):
        decl, init, ref = field_to_column_declaration(f, i)
        column_decls.append(decl)
        column_inits.append(init)
        col_refs.append(ref)

    add_range = "this.gvMain.Columns.AddRange(new DevExpress.XtraGrid.Columns.GridColumn[] {\n            " + ",\n            ".join(col_refs) + "\n        });"

    # 按钮区
    btn_search = """private DevExpress.XtraEditors.SimpleButton btnSearch;
private DevExpress.XtraEditors.SimpleButton btnReset;
private DevExpress.XtraEditors.SimpleButton btnAdd;
private DevExpress.XtraEditors.SimpleButton btnEdit;
private DevExpress.XtraEditors.SimpleButton btnDelete;
private DevExpress.XtraEditors.SimpleButton btnRefresh;"""

    btn_init = """this.btnSearch = new DevExpress.XtraEditors.SimpleButton();
this.btnSearch.Name = "btnSearch";
this.btnSearch.Text = "查询(&S)";
this.btnSearch.Click += new EventHandler(this.btnSearch_Click);

this.btnReset = new DevExpress.XtraEditors.SimpleButton();
this.btnReset.Name = "btnReset";
this.btnReset.Text = "重置(&R)";
this.btnReset.Click += new EventHandler(this.btnReset_Click);

this.btnAdd = new DevExpress.XtraEditors.SimpleButton();
this.btnAdd.Name = "btnAdd";
this.btnAdd.Text = "新增(&A)";
this.btnAdd.Click += new EventHandler(this.btnAdd_Click);

this.btnEdit = new DevExpress.XtraEditors.SimpleButton();
this.btnEdit.Name = "btnEdit";
this.btnEdit.Text = "修改(&E)";
this.btnEdit.Click += new EventHandler(this.btnEdit_Click);

this.btnDelete = new DevExpress.XtraEditors.SimpleButton();
this.btnDelete.Name = "btnDelete";
this.btnDelete.Text = "删除(&D)";
this.btnDelete.Click += new EventHandler(this.btnDelete_Click);

this.btnRefresh = new DevExpress.XtraEditors.SimpleButton();
this.btnRefresh.Name = "btnRefresh";
this.btnRefresh.Text = "刷新(&F)";
this.btnRefresh.Click += new EventHandler(this.btnRefresh_Click);"""

    btn_container = """this.lciBtnRow.Add(this.btnSearch);
this.lciBtnRow.Add(this.btnReset);
this.lciBtnRow.Add(this.btnAdd);
this.lciBtnRow.Add(this.btnEdit);
this.lciBtnRow.Add(this.btnDelete);
this.lciBtnRow.Add(this.btnRefresh);"""

    # 组装
    ns = cfg["namespace_prefix"]
    if ctx.namespace_prefix:
        ns = ctx.namespace_prefix

    form_class = ctx.form_name
    base = cfg["base_class"]
    if cfg["is_generic"]:
        base = base.replace("<T>", f"<{ctx.entity_name}Info>")

    code = f"""// ═══════════════════════════════════════════════════════════════
// 自动生成草稿 — 家族: {ctx.family.value} | 场景: {ctx.scenario.value}
// 实体: {ctx.entity_name} | 生成后请人工审查并替换占位符
// ═══════════════════════════════════════════════════════════════

namespace {ns}.{ctx.entity_name}
{{
    partial class {form_class} : {base}
    {{
        private IContainer components;
        private GridStyle _gridStyle;

        private GridControl gcMain;
        private GridView   gvMain;
        private DevExpress.XtraLayout.LayoutControl lcMain;
        private DevExpress.XtraLayout.LayoutControlGroup lcgMain;
        private DevExpress.XtraLayout.LayoutControlItem lciGrid;
        private DevExpress.XtraLayout.LayoutControlItem lciBtnRow;
        private Panel pnlSearch;

{chr(10).join('        ' + line for line in btn_search.split(chr(10)))}

{chr(10).join('        ' + line for line in column_decls)}

        private void InitializeComponent()
        {{
            this.components = new Container();

            // ── 1. GridStyle ──
            this._gridStyle = {cfg['gridstyle_call'].replace('{gs}', gs)};

            // ── 2. 实例化 ──
            this.gcMain   = new GridControl();
            this.gvMain   = new GridView();
            this.lcMain   = new DevExpress.XtraLayout.LayoutControl();
            this.lcgMain  = new DevExpress.XtraLayout.LayoutControlGroup();
            this.lciGrid  = new DevExpress.XtraLayout.LayoutControlItem();
            this.lciBtnRow = new DevExpress.XtraLayout.LayoutControlItem();
            this.pnlSearch = new Panel();

            ((ISupportInitialize)(this.gcMain)).BeginInit();
            ((ISupportInitialize)(this.gvMain)).BeginInit();
            this.lcMain.SuspendLayout();
            this.SuspendLayout();

            // ── 3. gcMain 配置 ──
            this.gcMain.Dock = DockStyle.Fill;
            this.gcMain.MainView = this.gvMain;
            this.gcMain.Name = "gcMain";

            // ── 4. gvMain 配置 ──
            this.gvMain.GridControl = this.gcMain;
            this.gvMain.Name = "gvMain";
            this.gvMain.OptionsBehavior.Editable = false;
            this.gvMain.OptionsBehavior.ReadOnly = true;
            this.gvMain.OptionsView.ShowGroupPanel = false;
            this.gvMain.OptionsView.ShowAutoFilterRow = true;

            // ── 5. 列定义 ──
            {add_range.replace(chr(10), chr(10) + '            ')}

            // ── 5b. 列初始化 ──
            {chr(10).join('            ' + line for line in ('\n'.join(column_inits)).split(chr(10)))}

            // ── 6. lcMain 布局 ──
            this.lcMain.Dock = DockStyle.Fill;
            this.lcMain.Name = "lcMain";
            this.lcMain.OptionsItemText.TextToControlDistance = 4;
            this.lcMain.AutoSize = false;  // ⚠️ 必须显式设为 false

            this.lcgMain.Name = "lcgMain";
            this.lcgMain.TextVisible = false;

            this.lciGrid.Control = this.gcMain;
            this.lciGrid.TextVisible = false;

            // ── 7. 搜索区 ──
            this.pnlSearch.Height = 48;
            this.pnlSearch.Dock = DockStyle.Top;
            this.pnlSearch.Name = "pnlSearch";

            this.lciBtnRow.Control = this.pnlSearch;
            this.lciBtnRow.TextVisible = false;

            // ── 8. 按钮 ──
{chr(10).join('            ' + line for line in btn_init.split(chr(10)))}

            // ── 9. 按钮容器 ──
{chr(10).join('            ' + line for line in btn_container.split(chr(10)))}

            // ── 10. Frm 装配 ──
            this.lcMain.Root = this.lcgMain;
            this.ClientSize = new Size(984, 626);
            this.Controls.Add(this.lcMain);
            this.Name = "{form_class}";
            this.Text = "{ctx.entity_name} 列表";
            this.StartPosition = FormStartPosition.CenterScreen;
            this.Load += new EventHandler(this.{form_class}_Load);

            // ── 11. 解初始化 ──
            ((ISupportInitialize)(this.gvMain)).EndInit();
            ((ISupportInitialize)(this.gcMain)).EndInit();
            this.lcMain.ResumeLayout(false);
            this.ResumeLayout(false);
        }}
    }}
}}"""
    return code


def _generate_layout_scenario(ctx: GenerationContext) -> str:
    """LayoutControl 表单场景（单条录入，≤8 字段）。"""
    cfg = _FAMILY_CONFIGS[ctx.family]
    ns = cfg["namespace_prefix"]
    if ctx.namespace_prefix:
        ns = ctx.namespace_prefix

    form_class = f"DlgEdit_{ctx.entity_name}"
    display_fields = [f for f in ctx.fields if f.field_type != FieldType.GUID][:8]

    field_blocks = []
    for f in display_fields:
        field_blocks.append(field_to_layout_item(f, len(field_blocks)))

    code = f"""// ═══════════════════════════════════════════════════════════════
// 自动生成草稿 — 家族: {ctx.family.value} | 场景: layout (表单录入)
// 实体: {ctx.entity_name} | 生成后请人工审查并替换占位符
// ═══════════════════════════════════════════════════════════════

namespace {ns}.{ctx.entity_name}
{{
    partial class {form_class}
    {{
        private IContainer components;

        private LayoutControl lcMain;
        private LayoutControlGroup lcgMain;
        private Panel pnlBottom;
        private SimpleButton btnSave;
        private SimpleButton btnCancel;

{chr(10).join('        ' + line for line in field_blocks)}

        private void InitializeComponent()
        {{
            this.components = new Container();

            this.lcMain     = new LayoutControl();
            this.lcgMain    = new LayoutControlGroup();
            this.pnlBottom  = new Panel();
            this.btnSave    = new SimpleButton();
            this.btnCancel  = new SimpleButton();

            ((ISupportInitialize)(this.lcMain)).BeginInit();
            this.lcMain.SuspendLayout();
            this.pnlBottom.SuspendLayout();
            this.SuspendLayout();

            // ── lcMain ──
            this.lcMain.Dock = DockStyle.Fill;
            this.lcMain.Name = "lcMain";
            this.lcMain.OptionsItemText.TextToControlDistance = 4;
            this.lcMain.AutoSize = false;  // ⚠️ 必须显式设为 false

            this.lcgMain.Name = "lcgMain";
            this.lcgMain.TextVisible = false;

            this.lcMain.Root = this.lcgMain;

            // ── pnlBottom ──
            this.pnlBottom.Dock = DockStyle.Bottom;
            this.pnlBottom.Height = 50;
            this.pnlBottom.Name = "pnlBottom";

            this.btnSave.Text = "保存(&S)";
            this.btnSave.Width = 75;
            this.btnSave.Anchor = AnchorStyles.Right;
            this.btnSave.Location = new Point(360, 11);

            this.btnCancel.Text = "取消(&C)";
            this.btnCancel.Width = 75;
            this.btnCancel.Anchor = AnchorStyles.Right;
            this.btnCancel.Location = new Point(450, 11);

            this.pnlBottom.Controls.Add(this.btnSave);
            this.pnlBottom.Controls.Add(this.btnCancel);

            // ── Frm 装配 ──
            this.ClientSize = new Size(540, 410);
            this.Controls.Add(this.lcMain);
            this.Controls.Add(this.pnlBottom);
            this.MinimumSize = new Size(420, 320);
            this.Name = "{form_class}";
            this.Text = "{{新增/修改}}{ctx.entity_name}";
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
        }}
    }}
}}"""
    return code


def _generate_tree_scenario(ctx: GenerationContext) -> str:
    """TreeList 主从场景。"""
    cfg = _FAMILY_CONFIGS[ctx.family]
    gs = ctx.gridstyle_code or cfg["gridstyle_code"]
    ns = cfg["namespace_prefix"]
    if ctx.namespace_prefix:
        ns = ctx.namespace_prefix

    form_class = f"{ctx.form_name}MasterDetail"

    code = f"""// ═══════════════════════════════════════════════════════════════
// 自动生成草稿 — 家族: {ctx.family.value} | 场景: tree (TreeList 主从)
// 实体: {ctx.entity_name} | 生成后请人工审查并替换占位符
// ═══════════════════════════════════════════════════════════════

namespace {ns}.{ctx.entity_name}
{{
    partial class {form_class}
    {{
        private IContainer components;
        private GridStyle _gridStyle;

        private SplitContainerControl splitContainer1;
        private TreeList  tlMain;
        private GridControl gcDetail;
        private GridView   gvDetail;

        private void InitializeComponent()
        {{
            this.components = new Container();

            // TreeList 用单参数 GridStyle 重载
            this._gridStyle = {cfg['gridstyle_call'].replace('gcMain, gvMain', 'tlMain').replace('{gs}', gs)};

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
            this.splitContainer1.SplitterPosition = 300;
            this.splitContainer1.Name = "splitContainer1";

            // ── 左:TreeList ──
            this.tlMain.Dock = DockStyle.Fill;
            this.tlMain.Name = "tlMain";
            this.tlMain.OptionsView.ShowAutoFilterRow = true;
            this.tlMain.OptionsView.ShowIndicator = false;
            this.tlMain.OptionsBehavior.Editable = false;
            this.tlMain.OptionsBehavior.EnableFiltering = true;
            this.tlMain.OptionsFilter.FilterMode = FilterMode.Extended;
            this.tlMain.ParentFieldName = "ParentID";
            this.tlMain.KeyFieldName = "ID";

            // ── 右:GridControl ──
            this.gcDetail.Dock = DockStyle.Fill;
            this.gcDetail.MainView = this.gvDetail;
            this.gcDetail.Name = "gcDetail";

            this.gvDetail.GridControl = this.gcDetail;
            this.gvDetail.Name = "gvDetail";
            this.gvDetail.OptionsBehavior.ReadOnly = true;
            this.gvDetail.OptionsView.ShowGroupPanel = false;

            // ── 装配 ──
            this.splitContainer1.Panel1.Controls.Add(this.tlMain);
            this.splitContainer1.Panel2.Controls.Add(this.gcDetail);

            this.ClientSize = new Size(1200, 700);
            this.Controls.Add(this.splitContainer1);
            this.Name = "{form_class}";
            this.Text = "{ctx.entity_name} 主从";
            this.StartPosition = FormStartPosition.CenterScreen;

            // ── 事件 ──
            this.tlMain.FocusedNodeChanged += new FocusedNodeChangedEventHandler(this.tlMain_FocusedNodeChanged);

            // ── 解初始化 ──
            ((ISupportInitialize)(this.gvDetail)).EndInit();
            ((ISupportInitialize)(this.gcDetail)).EndInit();
            ((ISupportInitialize)(this.tlMain)).EndInit();
            ((ISupportInitialize)(this.splitContainer1)).EndInit();
            this.ResumeLayout(false);
        }}
    }}
}}"""
    return code


# ─── 字段解析 ──────────────────────────────────────────────────────────────

def _parse_field_spec(spec_str: str) -> EntityField:
    """解析 `FieldName=Type,caption,maxlen` 格式。"""
    parts = spec_str.split("=")
    name = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else "string"

    type_parts = rest.split(",")
    type_str = type_parts[0].strip().rstrip("?")
    is_optional = rest.strip().endswith("?")
    caption = type_parts[1].strip() if len(type_parts) > 1 else name
    max_length = int(type_parts[2].strip()) if len(type_parts) > 2 else 50

    ft = FieldType.STRING
    if type_str == "Guid": ft = FieldType.GUID
    elif type_str == "int": ft = FieldType.INT
    elif type_str == "decimal": ft = FieldType.DECIMAL
    elif type_str == "DateTime": ft = FieldType.DATETIME
    elif type_str == "bool": ft = FieldType.BOOL

    return EntityField(
        name=name, field_type=ft,
        is_primary_key=(name.lower() == "id" and ft == FieldType.GUID),
        caption=caption, max_length=max_length,
    )


def _build_context(args: argparse.Namespace) -> GenerationContext:
    """从命令行参数构建生成上下文。"""
    family = Family(args.family.lower())
    scenario = Scenario(args.scenario.lower())

    fields = []
    if args.fields:
        for spec in args.fields.split(","):
            spec = spec.strip()
            if spec:
                fields.append(_parse_field_spec(spec))

    cfg = _FAMILY_CONFIGS[family]
    return GenerationContext(
        family=family,
        scenario=scenario,
        entity_name=args.entity_name,
        form_name=args.form_name,
        fields=fields,
        namespace_prefix=args.namespace or cfg["namespace_prefix"],
        gridstyle_code=args.gridstyle or cfg["gridstyle_code"],
        base_class=cfg["base_class"],
        is_generic=cfg["is_generic"],
    )


# ─── 主命令 ────────────────────────────────────────────────────────────────

def cmd_generate(args: argparse.Namespace) -> int:
    ctx = _build_context(args)

    generators = {
        Scenario.GRID: _generate_grid_scenario,
        Scenario.LAYOUT: _generate_layout_scenario,
        Scenario.TREE: _generate_tree_scenario,
    }

    generator = generators.get(ctx.scenario)
    if not generator:
        print(f"场景 '{ctx.scenario.value}' 的生成器尚未实现", file=sys.stderr)
        print(f"当前支持: {', '.join(s.value for s in Scenario)}", file=sys.stderr)
        return 1

    code = generator(ctx)
    print(code)

    # 提示
    print(f"\n// ⚠️  以上为草稿，生成后必须人工审查：")
    print(f"//   1. 替换 {{新增/修改}} 等中文占位符")
    print(f"//   2. 确认 GridStyle 代号 '{ctx.gridstyle_code}' 正确")
    print(f"//   3. 确认命名空间 '{ctx.namespace_prefix}' 与项目一致")
    print(f"//   4. 确认字段映射（尤其枚举/外键字段）")
    print(f"//   5. 确认 BeginInit/EndInit 配对正确")
    return 0


def cmd_list_families(args: argparse.Namespace) -> int:
    print("\n支持的家族:")
    print(f"{'家族':<10} {'GridStyle':<8} {'基类':<20} {'泛型'}")
    print("─" * 50)
    for fam, cfg in _FAMILY_CONFIGS.items():
        print(f"{fam.value:<10} {cfg['gridstyle_code']:<8} {cfg['base_class']:<20} {cfg['is_generic']}")
    return 0


def cmd_list_scenarios(args: argparse.Namespace) -> int:
    print("\n支持的场景:")
    print(f"{'场景':<10} {'说明'}")
    print("─" * 50)
    descriptions = {
        Scenario.GRID: "GridControl + GridView (CRUD 列表)",
        Scenario.TREE: "TreeList (目录树 / 主从)",
        Scenario.LAYOUT: "LayoutControl 表单 (≤8 字段录入)",
    }
    for s in Scenario:
        print(f"{s.value:<10} {descriptions.get(s, '')}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Designer 片段自动组合引擎",
    )
    sub = parser.add_subparsers(dest="command")

    # generate
    p_gen = sub.add_parser("generate", help="生成 InitializeComponent 草稿")
    p_gen.add_argument("--family", required=True,
                       choices=[f.value for f in Family],
                       help="项目家族: upgrader / crs / equp / css")
    p_gen.add_argument("--scenario", required=True,
                       choices=[s.value for s in Scenario],
                       help="场景: grid / tree / layout")
    p_gen.add_argument("--entity-name", required=True, help="实体类名 (例: PartsInfo)")
    p_gen.add_argument("--form-name", required=True, help="窗体类名 (例: Frm_PartsList)")
    p_gen.add_argument("--fields", default="",
                       help="字段列表: Name1=type1,caption1,maxlen1,Name2=...")
    p_gen.add_argument("--namespace", default="", help="命名空间前缀 (覆盖家族默认)")
    p_gen.add_argument("--gridstyle", default="", help="GridStyle 代号 (覆盖家族默认)")

    # list-families
    sub.add_parser("list-families", help="列出支持的家族")

    # list-scenarios
    sub.add_parser("list-scenarios", help="列出支持的场景")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "generate": cmd_generate,
        "list-families": cmd_list_families,
        "list-scenarios": cmd_list_scenarios,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
