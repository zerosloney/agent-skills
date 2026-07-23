#!/usr/bin/env python3
"""incremental_designer.py — 增量编辑 Designer.cs 辅助工具 (P1)

解决的问题:
    Agent 给现有窗体加列/按钮时,需要精确计算 VisibleIndex、
    生成字段声明和初始化代码、插入到 Columns.AddRange 数组中。

用法:
    # 分析现有 Designer.cs 的列结构
    python scripts/incremental_designer.py analyze --designer "Frm_PartsList.Designer.cs"

    # 生成新增列的代码片段
    python scripts/incremental_designer.py add-column --designer "Frm_PartsList.Designer.cs" \\
        --name "CreateTime" --field "CreateTime" --type DateTime --visible-index last \\
        --format "yyyy-MM-dd HH:mm"

    # 生成新增按钮的代码片段
    python scripts/incremental_designer.py add-button --designer "Frm_PartsList.Designer.cs" \\
        --name "btnExport" --text "导出 Excel" --container lciBtnRow

    # 生成增量补丁（分析 → 生成全部）
    python scripts/incremental_designer.py patch --designer "Frm_PartsList.Designer.cs" \\
        --columns "CreateTime=DateTime,Remark=Text" \\
        --buttons "btnExport=导出 Excel"
"""

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


# ─── 数据类型 ──────────────────────────────────────────────────────────────

@dataclass
class GridColumnInfo:
    """从 Designer.cs 解析出的现有列信息。"""
    field_name: str          # FieldName 属性值
    caption: str             # Caption 属性值
    visible_index: int       # VisibleIndex 属性值
    visible: bool            # Visible 属性值
    display_format: str = "" # DisplayFormat.FormatString
    data_type: str = ""      # 推断的数据类型

@dataclass
class ButtonInfo:
    """从 Designer.cs 解析出的现有按钮信息。"""
    field_name: str
    text: str
    container: str = ""


# ─── 解析器 ───────────────────────────────────────────────────────────────

_COLUMN_FIELD_RE = re.compile(
    r"this\.(col\w+)\s*=\s*new\s+GridColumn\(\);"
)
_COLUMN_PROPS_RE = re.compile(
    r"this\.(col\w+)\.(?P<prop>[\w.]+\w)\s*=\s*(?P<value>[^;]+);"
)
_COLUMNS_ADD_RANGE_RE = re.compile(
    r"this\.gvMain\.Columns\.AddRange\(new\s+GridColumn\[\]\s*\{([^}]*)\}\)",
    re.DOTALL,
)
_BUTTON_FIELD_RE = re.compile(
    r"this\.(btn\w+)\s*=\s*new\s+SimpleButton\(\);"
)
_BUTTON_PROPS_RE = re.compile(
    r"this\.(btn\w+)\.(?P<prop>\w+)\s*=\s*(?P<value>[^;]+);"
)
_CONTAINER_ADD_RE = re.compile(
    r"this\.(\w+)\.(?:Controls\.)?Add(?:Control)?\(this\.(btn\w+)\)"
)


def _parse_string_value(raw: str) -> str:
    """从 `"xxx"` 或 `xxx` 提取字符串值。"""
    raw = raw.strip()
    if raw.startswith('"') and raw.endswith('"'):
        return raw[1:-1]
    return raw


def analyze_designer(designer_path: str) -> dict:
    """解析 Designer.cs，提取列和按钮结构。

    参数可以是文件路径或原始文本内容（当 Path 不是有效文件时自动回退）。"""
    p = Path(designer_path)
    if p.exists() and p.is_file():
        text = p.read_text(encoding="utf-8", errors="replace")
    else:
        text = designer_path

    columns: dict[str, GridColumnInfo] = {}
    buttons: dict[str, ButtonInfo] = {}

    # 解析列字段声明
    for m in _COLUMN_FIELD_RE.finditer(text):
        col_name = m.group(1)
        columns[col_name] = GridColumnInfo(
            field_name="", caption="", visible_index=-1, visible=True,
        )

    # 解析列属性
    for m in _COLUMN_PROPS_RE.finditer(text):
        col_name = m.group(1)
        prop = m.group("prop")
        value = _parse_string_value(m.group("value"))
        if col_name not in columns:
            columns[col_name] = GridColumnInfo(
                field_name="", caption="", visible_index=-1, visible=True,
            )
        col = columns[col_name]
        if prop == "FieldName":
            col.field_name = value
        elif prop == "Caption":
            col.caption = value
        elif prop == "VisibleIndex":
            col.visible_index = int(value)
        elif prop == "Visible":
            col.visible = value.lower() != "false"
        elif prop == "DisplayFormat.FormatString":
            col.display_format = value

    # 推断数据类型（从 FormatString 猜测）
    for col in columns.values():
        fmt = col.display_format.lower()
        if "date" in fmt or "time" in fmt:
            col.data_type = "DateTime"
        elif "n" in fmt and "2" in fmt:
            col.data_type = "decimal"
        elif "n0" in fmt:
            col.data_type = "int"

    # 解析按钮
    for m in _BUTTON_FIELD_RE.finditer(text):
        btn_name = m.group(1)
        buttons[btn_name] = ButtonInfo(field_name=btn_name, text="")

    for m in _BUTTON_PROPS_RE.finditer(text):
        btn_name = m.group(1)
        prop = m.group("prop")
        value = _parse_string_value(m.group("value"))
        if btn_name not in buttons:
            buttons[btn_name] = ButtonInfo(field_name=btn_name, text="")
        if prop == "Text":
            buttons[btn_name].text = value

    # 解析按钮容器
    for m in _CONTAINER_ADD_RE.finditer(text):
        container_name = m.group(1)
        btn_name = m.group(2)
        if btn_name in buttons:
            buttons[btn_name].container = container_name

    # 找出 Columns.AddRange 中的当前列顺序
    add_range_match = _COLUMNS_ADD_RANGE_RE.search(text)
    add_range_order: list[str] = []
    if add_range_match:
        inner = add_range_match.group(1)
        for m in re.finditer(r"this\.(col\w+)", inner):
            add_range_order.append(m.group(1))

    return {
        "columns": {k: {
            "field_name": v.field_name,
            "caption": v.caption,
            "visible_index": v.visible_index,
            "visible": v.visible,
            "display_format": v.display_format,
            "data_type": v.data_type,
        } for k, v in columns.items()},
        "buttons": {k: {
            "text": v.text,
            "container": v.container,
        } for k, v in buttons.items()},
        "add_range_order": add_range_order,
        "max_visible_index": max(
            (c.visible_index for c in columns.values() if c.visible_index >= 0),
            default=-1,
        ),
    }


# ─── 列生成器 ──────────────────────────────────────────────────────────────

@dataclass
class ColumnSpec:
    """用户指定的新列规格。"""
    name: str              # 字段名（C# 属性名）
    caption: str           # 列头显示文本
    data_type: str         # string / int / decimal / DateTime / bool
    visible_index: str     # "last" 或数字字符串
    display_format: str = ""
    visible: bool = True


def generate_column_code(col: ColumnSpec, existing_max_index: int) -> dict:
    """生成新增列的完整 C# 代码片段。"""
    # 计算 VisibleIndex
    if col.visible_index.lower() == "last":
        vi = existing_max_index + 1
        vi_str = f"{vi}"
    else:
        vi = int(col.visible_index)
        vi_str = col.visible_index

    # 简化：取首字母大写
    field_name = "col" + col.name[0].upper() + col.name[1:]

    # 字段声明
    declaration = f"private DevExpress.XtraGrid.Columns.GridColumn {field_name};"

    # 初始化代码
    lines = [
        f"this.{field_name} = new DevExpress.XtraGrid.Columns.GridColumn();",
        f"this.{field_name}.Caption = \"{col.caption}\";",
        f"this.{field_name}.FieldName = \"{col.name}\";",
    ]

    # Guid 主键默认隐藏
    if col.data_type == "Guid":
        lines.append(f"this.{field_name}.Visible = false;")
        lines.append(f"this.{field_name}.VisibleIndex = -1;")
    else:
        lines.append(f"this.{field_name}.Visible = {(str(col.visible)).lower()};")
        lines.append(f"this.{field_name}.VisibleIndex = {vi_str};")

    # 类型特定配置
    if col.data_type == "DateTime" and col.display_format:
        lines.append(f"this.{field_name}.DisplayFormat.FormatString = \"{col.display_format}\";")
        lines.append(f"this.{field_name}.DisplayFormat.FormatType = DevExpress.Utils.FormatType.DateTime;")
    elif col.data_type in ("int", "decimal") and not col.display_format:
        lines.append(f"this.{field_name}.DisplayFormat.FormatString = \"N2\";")
        lines.append(f"this.{field_name}.DisplayFormat.FormatType = DevExpress.Utils.FormatType.Numeric;")
        lines.append(f"this.{field_name}.AppearanceCell.TextOptions.HAlignment = DevExpress.Utils.HorzAlignment.Far;")
    elif col.data_type == "bool":
        lines.append(f"this.{field_name}.ColumnEdit = new DevExpress.XtraEditors.Repository.RepositoryItemCheckEdit();")
        lines.append(f"this.{field_name}.DisplayFormat.FormatString = \"TRUE/FALSE\";")
    elif col.data_type == "string" and col.visible:
        # 默认 TextEdit，长文本用 MemoEdit
        pass  # 无需额外配置

    init_code = "\n".join(lines)

    # AddRange 追加项
    add_range_item = f"this.{field_name}"

    return {
        "field_name": field_name,
        "declaration": declaration,
        "init_code": init_code,
        "add_range_item": add_range_item,
        "visible_index": vi_str,
        "full_block": f"{declaration}\n\n{init_code}",
    }


def generate_button_code(btn_name: str, text: str, container: str) -> dict:
    """生成新增按钮的 C# 代码片段。"""
    field_name = btn_name if btn_name.startswith("btn") else f"btn{btn_name}"

    declaration = f"private DevExpress.XtraEditors.SimpleButton {field_name};"

    init_lines = [
        f"this.{field_name} = new DevExpress.XtraEditors.SimpleButton();",
        f"this.{field_name}.Name = \"{field_name}\";",
        f"this.{field_name}.Text = \"{text}\";",
        f"this.{field_name}.Click += new EventHandler(this.{field_name}_Click);",
    ]
    init_code = "\n".join(init_lines)

    container_line = f"this.{container}.Add(this.{field_name});"

    return {
        "field_name": field_name,
        "declaration": declaration,
        "init_code": init_code,
        "container_line": container_line,
        "full_block": f"{declaration}\n\n{init_code}\n{container_line}",
    }


# ─── 主命令 ────────────────────────────────────────────────────────────────

def cmd_analyze(args: argparse.Namespace) -> int:
    result = analyze_designer(args.designer)
    cols = result["columns"]
    btns = result["buttons"]

    print(f"\n Designer: {args.designer}")
    print(f" Columns: {len(cols)} | Buttons: {len(btns)}")
    print(f" Max VisibleIndex: {result['max_visible_index']}")
    print(f" AddRange order: {' → '.join(result['add_range_order'])}")

    if cols:
        print(f"\n{'─'*50}")
        print(f"{'FieldName':<20} {'Caption':<15} {'VI':>4} {'Visible':<8} {'Format'}")
        print(f"{'─'*50}")
        for name, info in sorted(cols.items(), key=lambda x: x[1]["visible_index"]):
            print(f"{info['field_name']:<20} {info['caption']:<15} {info['visible_index']:>4} {str(info['visible']):<8} {info['display_format']}")

    if btns:
        print(f"\n{'─'*50}")
        print(f"{'Button':<15} {'Text':<15} {'Container'}")
        print(f"{'─'*50}")
        for name, info in sorted(btns.items()):
            print(f"{name:<15} {info['text']:<15} {info['container'] or '(none)'}")

    return 0


def _parse_column_spec(spec_str: str) -> ColumnSpec:
    """解析 `Name=type,caption,format` 格式。"""
    parts = spec_str.split("=")
    name = parts[0].strip()
    rest = parts[1].strip() if len(parts) > 1 else name

    type_parts = rest.split(",")
    data_type = type_parts[0].strip() if type_parts else "string"
    caption = type_parts[1].strip() if len(type_parts) > 1 else name
    display_format = type_parts[2].strip() if len(type_parts) > 2 else ""

    return ColumnSpec(
        name=name, caption=caption, data_type=data_type,
        visible_index="last", display_format=display_format,
    )


def cmd_add_column(args: argparse.Namespace) -> int:
    result = analyze_designer(args.designer)
    col = _parse_column_spec(args.column_spec)
    code = generate_column_code(col, result["max_visible_index"])

    print(f"\n{'='*60}")
    print(f"新增列: {col.name} (VisibleIndex = {code['visible_index']})")
    print(f"{'='*60}")
    print(code["full_block"])
    print(f"\nAddRange 追加项: {code['add_range_item']}")
    print(f"\n注意: 将 {code['add_range_item']} 追加到 gvMain.Columns.AddRange 的数组末尾")
    return 0


def cmd_add_button(args: argparse.Namespace) -> int:
    result = analyze_designer(args.designer)
    btn_name = args.button_spec.split("=")[0].strip() if "=" in args.button_spec else args.button_spec
    text = args.button_spec.split("=")[1].strip() if "=" in args.button_spec else args.button_spec
    container = args.container or "pnlBottom"

    code = generate_button_code(btn_name, text, container)

    print(f"\n{'='*60}")
    print(f"新增按钮: {btn_name} (容器: {container})")
    print(f"{'='*60}")
    print(code["full_block"])
    return 0


def cmd_patch(args: argparse.Namespace) -> int:
    result = analyze_designer(args.designer)

    # 解析列规格
    new_columns = []
    if args.columns:
        for spec_str in args.columns.split(","):
            spec_str = spec_str.strip()
            if spec_str:
                new_columns.append(_parse_column_spec(spec_str))

    # 解析按钮规格
    new_buttons = []
    if args.buttons:
        for spec_str in args.buttons.split(","):
            spec_str = spec_str.strip()
            if spec_str:
                name = spec_str.split("=")[0].strip()
                text = spec_str.split("=")[1].strip() if "=" in spec_str else name
                new_buttons.append((name, text))

    print(f"\n{'='*60}")
    print(f"增量补丁: {args.designer}")
    print(f"新增列: {len(new_columns)} | 新增按钮: {len(new_buttons)}")
    print(f"当前 Max VisibleIndex: {result['max_visible_index']}")
    print(f"{'='*60}")

    # 生成列代码
    for col in new_columns:
        code = generate_column_code(col, result["max_visible_index"])
        result["max_visible_index"] = int(code["visible_index"])  # 递增
        print(f"\n// ── 列: {col.name} ──")
        print(code["full_block"])
        print(f"// AddRange 追加: {code['add_range_item']}")

    # 生成按钮代码
    container = args.container or "lciBtnRow"
    for btn_name, text in new_buttons:
        code = generate_button_code(btn_name, text, container)
        print(f"\n// ── 按钮: {btn_name} ──")
        print(code["full_block"])

    print(f"\n{'='*60}")
    print("操作步骤:")
    print(f"  1. 将上方列代码追加到 Designer.cs 的字段声明区")
    print(f"  2. 将列初始化代码追加到 InitializeComponent 的 gcMain/gvMain 配置区")
    print(f"  3. 将 AddRange 追加项加入 gvMain.Columns.AddRange 数组")
    print(f"  4. 将按钮代码追加到按钮区并 Add 到 lciBtnRow")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="增量编辑 Designer.cs 辅助工具",
    )
    sub = parser.add_subparsers(dest="command")

    # analyze
    p_analyze = sub.add_parser("analyze", help="解析现有 Designer.cs 的列/按钮结构")
    p_analyze.add_argument("--designer", required=True, help="Designer.cs 文件路径")

    # add-column
    p_col = sub.add_parser("add-column", help="生成新增列的代码片段")
    p_col.add_argument("--designer", required=True, help="Designer.cs 文件路径")
    p_col.add_argument("--column-spec", required=True,
                       help="列规格: Name=type,caption,format (例: CreateTime=DateTime,创建时间,yyyy-MM-dd)")
    p_col.add_argument("--visible-index", default="last",
                       help="VisibleIndex: last(追加) 或具体数字")

    # add-button
    p_btn = sub.add_parser("add-button", help="生成新增按钮的代码片段")
    p_btn.add_argument("--designer", required=True, help="Designer.cs 文件路径")
    p_btn.add_argument("--button-spec", required=True,
                       help="按钮规格: Name=显示文本 (例: btnExport=导出 Excel)")
    p_btn.add_argument("--container", default="lciBtnRow",
                       help="按钮容器: lciBtnRow / pnlBottom")

    # patch (组合)
    p_patch = sub.add_parser("patch", help="分析 + 生成全部增量代码（推荐）")
    p_patch.add_argument("--designer", required=True, help="Designer.cs 文件路径")
    p_patch.add_argument("--columns", default="",
                        help="列规格列表: Name1=type1,caption1,Name2=type2,caption2")
    p_patch.add_argument("--buttons", default="",
                        help="按钮规格列表: btnName1=文本1,btnName2=文本2")
    p_patch.add_argument("--container", default="lciBtnRow",
                        help="按钮容器: lciBtnRow / pnlBottom")

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "analyze": cmd_analyze,
        "add-column": cmd_add_column,
        "add-button": cmd_add_button,
        "patch": cmd_patch,
    }
    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
