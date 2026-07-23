"""Tests for designer_generator.py and incremental_designer.py."""
import sys
import textwrap
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from designer_generator import (
    GenerationContext,
    EntityField,
    FieldType,
    Family,
    Scenario,
    field_to_column_declaration,
    _generate_grid_scenario,
    _generate_layout_scenario,
    _generate_tree_scenario,
    _FAMILY_CONFIGS,
)
from incremental_designer import (
    GridColumnInfo,
    ButtonInfo,
    ColumnSpec,
    analyze_designer,
    generate_column_code,
    generate_button_code,
)


# ─── designer_generator tests ───────────────────────────────────────────────


class TestFieldToColumnDeclaration:
    def test_string_field(self):
        decl, init, ref = field_to_column_declaration(
            EntityField(name="Code", field_type=FieldType.STRING,
                        caption="编码", max_length=50), 0)
        assert decl == "private DevExpress.XtraGrid.Columns.GridColumn colCode;"
        assert ref == "this.colCode"
        assert "FieldName = \"Code\"" in init
        assert "Caption = \"编码\"" in init
        assert "Visible = true" in init
        assert "VisibleIndex = 0" in init

    def test_guid_field_is_hidden(self):
        decl, init, ref = field_to_column_declaration(
            EntityField(name="ID", field_type=FieldType.GUID,
                        caption="ID"), 0)
        assert "Visible = false" in init
        assert "VisibleIndex = -1" in init

    def test_datetime_field_has_format(self):
        decl, init, ref = field_to_column_declaration(
            EntityField(name="CreateTime", field_type=FieldType.DATETIME,
                        caption="创建时间", display_format="yyyy-MM-dd"), 0)
        assert "DisplayFormat.FormatString = \"yyyy-MM-dd\"" in init
        assert "FormatType.DateTime" in init

    def test_decimal_field_has_numeric_format(self):
        decl, init, ref = field_to_column_declaration(
            EntityField(name="Price", field_type=FieldType.DECIMAL,
                        caption="价格"), 1)
        assert "DisplayFormat.FormatString = \"N2\"" in init
        assert "FormatType.Numeric" in init
        assert "HorzAlignment.Far" in init
        assert "VisibleIndex = 1" in init

    def test_bool_field_has_check_edit(self):
        decl, init, ref = field_to_column_declaration(
            EntityField(name="IsActive", field_type=FieldType.BOOL,
                        caption="启用"), 2)
        assert "RepositoryItemCheckEdit" in init

    def test_long_string_has_memo_edit(self):
        decl, init, ref = field_to_column_declaration(
            EntityField(name="Remark", field_type=FieldType.STRING,
                        caption="备注", max_length=500), 3)
        assert "RepositoryItemMemoEdit" in init


class TestGenerateGridScenario:
    def _make_ctx(self, family=Family.UPGRADER, entity="Material"):
        return GenerationContext(
            family=family, scenario=Scenario.GRID,
            entity_name=entity, form_name=f"Frm_{entity}List",
            fields=[
                EntityField(name="Code", field_type=FieldType.STRING,
                            caption="编码", max_length=50),
                EntityField(name="Name", field_type=FieldType.STRING,
                            caption="名称", max_length=100),
            ],
        )

    def test_upgrader_grid_output(self):
        code = _generate_grid_scenario(self._make_ctx())
        assert "partial class Frm_MaterialList" in code
        assert "GridControl gcMain" in code
        assert "GridView   gvMain" in code
        assert "GridStyle" in code
        assert "colCode" in code
        assert "colName" in code

    def test_crs_grid_uses_generic_base(self):
        code = _generate_grid_scenario(
            self._make_ctx(family=Family.CRS, entity="Supplier"))
        assert "frm_Base<SupplierInfo>" in code

    def test_columns_inside_initialize_component(self):
        code = _generate_grid_scenario(self._make_ctx())
        ic_start = code.index("private void InitializeComponent()")
        # extract method body via brace counting
        depth = 0
        ic_end = ic_start
        for i, c in enumerate(code[ic_start:], ic_start):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    ic_end = i
                    break
        ic_section = code[ic_start:ic_end]
        assert "FieldName = \"Code\"" in ic_section
        assert "FieldName = \"Name\"" in ic_section

    def test_button_init_inside_initialize_component(self):
        code = _generate_grid_scenario(self._make_ctx())
        ic_start = code.index("private void InitializeComponent()")
        depth = 0
        ic_end = ic_start
        for i, c in enumerate(code[ic_start:], ic_start):
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    ic_end = i
                    break
        ic_section = code[ic_start:ic_end]
        assert "btnSearch = new" in ic_section
        assert "btnSearch_Click" in ic_section

    def test_autosize_false(self):
        code = _generate_grid_scenario(self._make_ctx())
        assert "AutoSize = false" in code

    def test_resume_layout_present(self):
        code = _generate_grid_scenario(self._make_ctx())
        assert "ResumeLayout(false)" in code


class TestGenerateLayoutScenario:
    def test_layout_output(self):
        ctx = GenerationContext(
            family=Family.CSS, scenario=Scenario.LAYOUT,
            entity_name="Material", form_name="DlgEdit_Material",
            fields=[
                EntityField(name="Code", field_type=FieldType.STRING,
                            caption="编码", max_length=50),
                EntityField(name="Name", field_type=FieldType.STRING,
                            caption="名称", max_length=100),
            ],
        )
        code = _generate_layout_scenario(ctx)
        assert "partial class DlgEdit_Material" in code
        assert "LayoutControl lcMain" in code
        assert "textEditCode" in code
        assert "lbcCode" in code
        assert "AddItem" in code

    def test_max_8_fields(self):
        ctx = GenerationContext(
            family=Family.CSS, scenario=Scenario.LAYOUT,
            entity_name="Test", form_name="DlgEdit_Test",
            fields=[
                EntityField(name=f"F{i}", field_type=FieldType.STRING,
                            caption=f"字段{i}", max_length=50)
                for i in range(12)
            ],
        )
        code = _generate_layout_scenario(ctx)
        for i in range(8):
            assert f"F{i}" in code


class TestGenerateTreeScenario:
    def test_tree_output(self):
        ctx = GenerationContext(
            family=Family.EQUP, scenario=Scenario.TREE,
            entity_name="Equipment", form_name="Frm_EquipmentTree",
            fields=[
                EntityField(name="Name", field_type=FieldType.STRING,
                            caption="设备名称", max_length=100),
            ],
        )
        code = _generate_tree_scenario(ctx)
        assert "partial class Frm_EquipmentTree" in code
        assert "TreeList  tlMain" in code
        assert "GridControl gcDetail" in code
        assert "ParentFieldName" in code
        assert "KeyFieldName" in code


class TestFamilyConfigs:
    def test_all_families_have_configs(self):
        for fam in Family:
            assert fam in _FAMILY_CONFIGS

    def test_crs_is_generic(self):
        cfg = _FAMILY_CONFIGS[Family.CRS]
        assert cfg["is_generic"] is True
        assert "<T>" in cfg["base_class"]

    def test_upgrader_not_generic(self):
        cfg = _FAMILY_CONFIGS[Family.UPGRADER]
        assert cfg["is_generic"] is False


# ─── incremental_designer tests ─────────────────────────────────────────────


class TestAnalyzeDesigner:
    def test_empty_string(self):
        result = analyze_designer("")
        assert result["columns"] == {}
        assert result["buttons"] == {}

    def test_nonexistent_path(self):
        result = analyze_designer("/nonexistent/path.cs")
        assert result["columns"] == {}

    def test_parse_columns(self):
        content = textwrap.dedent("""\
            partial class Frm_Test {
                private GridColumn colCode;
                private GridColumn colName;
                this.colCode = new GridColumn();
                this.colCode.FieldName = "Code";
                this.colCode.Visible = true;
                this.colCode.VisibleIndex = 0;
                this.colName.FieldName = "Name";
                this.colName.Visible = true;
                this.colName.VisibleIndex = 1;
                this.gvMain.Columns.AddRange(new GridColumn[] { this.colCode, this.colName });
            }
        """)
        result = analyze_designer(content)
        cols = result["columns"]
        assert cols["colCode"]["field_name"] == "Code"
        assert cols["colCode"]["visible_index"] == 0
        assert cols["colCode"]["visible"] is True
        assert cols["colName"]["field_name"] == "Name"
        assert cols["colName"]["visible_index"] == 1

    def test_parse_buttons(self):
        content = textwrap.dedent("""\
            partial class Frm_Test {
                private SimpleButton btnSearch;
                this.btnSearch = new SimpleButton();
                this.btnSearch.Name = "btnSearch";
                this.btnSearch.Text = "查询";
                this.pnlBottom.Controls.Add(this.btnSearch);
                this.lciBtnRow.Add(this.btnSearch);
            }
        """)
        result = analyze_designer(content)
        btns = result["buttons"]
        assert btns["btnSearch"]["text"] == "查询"
        # Both pnlBottom.Controls.Add and lciBtnRow.Add match; last write wins
        assert "lciBtnRow" in btns["btnSearch"]["container"]

    def test_hidden_guid_column(self):
        content = textwrap.dedent("""\
            partial class Frm_Test {
                this.colID = new GridColumn();
                this.colID.Visible = false;
                this.colID.VisibleIndex = -1;
            }
        """)
        result = analyze_designer(content)
        assert result["columns"]["colID"]["visible"] is False
        assert result["columns"]["colID"]["visible_index"] == -1

    def test_display_format_detected(self):
        content = textwrap.dedent("""\
            partial class Frm_Test {
                this.colPrice = new GridColumn();
                this.colPrice.DisplayFormat.FormatString = "N2";
                this.colPrice.VisibleIndex = 0;
            }
        """)
        result = analyze_designer(content)
        assert result["columns"]["colPrice"]["display_format"] == "N2"

    def test_addrange_parsing(self):
        content = textwrap.dedent("""\
            partial class Frm_Test {
                this.gvMain.Columns.AddRange(new GridColumn[] { this.colCode, this.colName });
            }
        """)
        result = analyze_designer(content)
        assert result["add_range_order"] == ["colCode", "colName"]


class TestGenerateColumnCode:
    def test_basic_column(self):
        spec = ColumnSpec(name="Status", caption="状态",
                          data_type="string", visible_index="2")
        result = generate_column_code(spec, existing_max_index=1)
        assert "colStatus" in result["declaration"]
        assert "Visible = true" in result["init_code"]
        assert "VisibleIndex = 2" in result["init_code"]
        assert "FieldName = \"Status\"" in result["init_code"]

    def test_guid_column_hidden(self):
        spec = ColumnSpec(name="ID", caption="ID", data_type="Guid",
                          visible_index="2")
        result = generate_column_code(spec, existing_max_index=1)
        assert "Visible = false" in result["init_code"]
        assert "VisibleIndex = -1" in result["init_code"]

    def test_datetime_format(self):
        spec = ColumnSpec(name="Date", caption="日期", data_type="DateTime",
                          visible_index="1", display_format="yyyy-MM-dd")
        result = generate_column_code(spec, existing_max_index=0)
        assert "DisplayFormat.FormatString = \"yyyy-MM-dd\"" in result["init_code"]

    def test_decimal_numeric_format(self):
        spec = ColumnSpec(name="Amt", caption="金额", data_type="decimal",
                          visible_index="3")
        result = generate_column_code(spec, existing_max_index=2)
        assert "DisplayFormat.FormatString = \"N2\"" in result["init_code"]

    def test_last_index_auto_calculated(self):
        spec = ColumnSpec(name="C", caption="C", data_type="string",
                          visible_index="last")
        result = generate_column_code(spec, existing_max_index=5)
        assert "VisibleIndex = 6" in result["init_code"]


class TestGenerateButtonCode:
    def test_basic_button(self):
        result = generate_button_code("btnApprove", "审批", "pnlBottom")
        assert "btnApprove" in result["declaration"]
        assert "Text = \"审批\"" in result["init_code"]
        assert "Click" in result["full_block"]

    def test_container_line(self):
        result = generate_button_code("btnExport", "导出", "pnlBottom")
        assert "pnlBottom.Add(this.btnExport)" in result["container_line"]
