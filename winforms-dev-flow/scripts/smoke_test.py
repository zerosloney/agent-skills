#!/usr/bin/env python3
"""WinForms 生成后冒烟测试（Step 5b-pre）。

用法:
    python scripts/smoke_test.py --dir "C:/Project/UI/PartsManagement"
    python scripts/smoke_test.py --dir "./generated" --pattern "*.cs"
    python scripts/smoke_test.py --dir "./generated" --reference "C:/Project/UI/Frm_PartsLookup.cs"

检查项（共 5 项上下文无关 + 2 项上下文相关）:
    上下文无关（默认运行）:
    1. 无占位符残留: {业务名} / {实体类} / {表名}
    2. 无 TODO / // 待实现 / NotImplementedException
    3. partial class 类名一致（frmX.cs ↔ frmX.Designer.cs）
    4. 无空 catch 块（吞异常）
    5. 无重复事件订阅（同一事件出现 2+ 个 += handler）

    上下文相关（需 --reference <参照窗体.cs>）:
    6. IView 契约风格: 参照是 set-only 时, 生成文件不得有 { get; set; }
    7. GridStyle 第一参数: 参照用字面量代号时, 生成文件保持同一字面量

无 --reference 时仅跑 5 项上下文无关检查（向后兼容）。
"""

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

PLACEHOLDER_PATTERNS = [
    r"\{业务名\}",
    r"\{实体类\}",
    r"\{表名\}",
    r"\{连接名\}",
    r"\{字段名\}",
    r"\{GridStyle\}",
]

TODO_PATTERNS = [
    r"TODO",
    r"//\s*待实现",
    r"NotImplementedException",
]

PLACEHOLDER_RE = re.compile("|".join(PLACEHOLDER_PATTERNS))
TODO_RE = re.compile("|".join(TODO_PATTERNS))
PARTIAL_RE = re.compile(r"partial\s+class\s+(\w+)")
EMPTY_CATCH_RE = re.compile(r"catch\s*\([^)]*\)\s*\{\s*\}")
# 重复事件订阅: 统计每个事件名的 += 次数，>=2 即告警
EVENT_SUBSCRIBE_RE = re.compile(r'(\w+(?:Event|Changed)?)\s*\+=\s*(?:new\s+)?\w+EventHandler\(')


def check_file(filepath: Path) -> list[dict]:
    issues = []
    try:
        text = filepath.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [{"file": str(filepath), "check": "readable", "status": "FAIL", "detail": str(e)}]

    # 1. Placeholder check
    placeholders = PLACEHOLDER_RE.findall(text)
    if placeholders:
        issues.append({
            "file": str(filepath),
            "check": "no_placeholders",
            "status": "FAIL",
            "detail": f"Found {len(placeholders)} placeholder(s): {placeholders[:3]}",
        })

    # 2. TODO check
    todos = TODO_RE.findall(text)
    if todos:
        issues.append({
            "file": str(filepath),
            "check": "no_todos",
            "status": "FAIL",
            "detail": f"Found {len(todos)} TODO/marker(s): {todos[:3]}",
        })

    # 3. Partial class name consistency (Designer files only)
    if filepath.name.endswith(".Designer.cs"):
        partials = PARTIAL_RE.findall(text)
        if partials:
            expected = filepath.name.replace(".Designer.cs", "")
            actual = partials[0]
            if actual != expected:
                issues.append({
                    "file": str(filepath),
                    "check": "partial_class_match",
                    "status": "FAIL",
                    "detail": f"partial class '{actual}' != filename '{expected}'",
                })

    # 4. Empty catch block check (WARN, not FAIL — Upgrader style allows empty catch returning false)
    empty_catches = EMPTY_CATCH_RE.findall(text)
    if empty_catches:
        issues.append({
            "file": str(filepath),
            "check": "no_empty_catch",
            "status": "WARN",
            "detail": f"Found {len(empty_catches)} empty catch block(s)",
        })

    # 5. 重复事件订阅
    # 只在 .cs（非 Designer）文件中检测，Designer 的事件在 InitializeComponent 内正常
    if not filepath.name.endswith(".Designer.cs"):
        event_matches = EVENT_SUBSCRIBE_RE.findall(text)
        if event_matches:
            counts = defaultdict(int)
            for ev in event_matches:
                counts[ev] += 1
            dupes = {ev: cnt for ev, cnt in counts.items() if cnt >= 2}
            if dupes:
                dupe_detail = "; ".join(f"{ev} ({cnt}x)" for ev, cnt in dupes.items())
                issues.append({
                    "file": str(filepath),
                    "check": "no_duplicate_event_subscription",
                    "status": "FAIL",
                    "detail": f"Duplicate event subscriptions: {dupe_detail}",
                })

    return issues if issues else [{"file": str(filepath), "check": "all", "status": "PASS", "detail": ""}]


# IView 契约: set-only 属性 (参照是 set 契约时, 生成文件不应有 { get; set; })
IVIEW_GETSET_RE = re.compile(r"public\s+\w+\s+\w+\s*\{\s*get;\s*set;\s*\}")
# 参照窗体的方法式契约标记
METHOD_CONTRACT_RE = re.compile(r"(Set\w+\s*\(|ShowMessage\s*\(|ConfirmYesNo\s*\(|Refresh\w+\s*\()")
# GridStyle 字面量代号
GRIDSTYLE_LITERAL_RE = re.compile(r'new GridStyle\(\s*"([^"]+)"')


def check_view_contract(generated_dir: Path, reference_file: Path) -> list[dict]:
    """对照参照窗体检查 IView 契约风格 + GridStyle 第一参数一致性（检查项 6-7）。

    需 --reference <参照窗体.cs> 参数。无参数时跳过（保持向后兼容）。

    检查项:
        6. IView 契约风格: 参照是 set-only 属性契约时, 生成文件不得有 { get; set; }
           （参照是方法式契约时跳过此检查，方法式允许 { get; } 输入属性）
        7. GridStyle 第一参数: 参照用字面量代号时, 生成文件保持同一字面量
    """
    issues = []
    try:
        ref_text = reference_file.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [{"file": str(reference_file), "check": "reference_readable",
                 "status": "FAIL", "detail": str(e)}]

    # 检测参照窗体的契约风格
    ref_set_only = bool(re.search(r"public\s+\w+\s+\w+\s*\{\s*set;\s*\}", ref_text))
    ref_method_style = bool(METHOD_CONTRACT_RE.search(ref_text))

    # 提取参照的 GridStyle 代号
    ref_grid_match = GRIDSTYLE_LITERAL_RE.search(ref_text)
    ref_grid_code = ref_grid_match.group(1) if ref_grid_match else None

    # 扫描生成目录中的 View 相关文件（I*View.cs 和 *View*.cs）
    view_files = list(generated_dir.rglob("I*View*.cs")) + list(generated_dir.rglob("*View*.cs"))
    # 去重（同一路径可能被两个 glob 匹配）
    seen = set()
    view_files = [f for f in view_files if not (str(f) in seen or seen.add(str(f)))]

    for f in view_files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue

        # 检查 6: IView 契约风格（仅当参照是 set-only 契约时）
        if ref_set_only and not ref_method_style:
            bad_props = IVIEW_GETSET_RE.findall(text)
            if bad_props:
                issues.append({
                    "file": str(f),
                    "check": "iview_contract",
                    "status": "FAIL",
                    "detail": f"Reference uses set-only contract, but found {len(bad_props)} {{ get; set; }} prop(s): {bad_props[:3]}",
                })

        # 检查 7: GridStyle 第一参数一致性
        if ref_grid_code:
            gen_grid_match = GRIDSTYLE_LITERAL_RE.search(text)
            if gen_grid_match and gen_grid_match.group(1) != ref_grid_code:
                issues.append({
                    "file": str(f),
                    "check": "gridstyle_code",
                    "status": "FAIL",
                    "detail": f"Reference uses '{ref_grid_code}', generated uses '{gen_grid_match.group(1)}'",
                })

    return issues


def main() -> int:
    parser = argparse.ArgumentParser(
        description="WinForms generation smoke test (5 context-free + 2 context-aware checks, Step 5b-pre)"
    )
    parser.add_argument("--dir", required=True,
                        help="Directory containing generated .cs files")
    parser.add_argument("--pattern", default="*.cs",
                        help="File glob pattern (default: *.cs)")
    parser.add_argument("--reference", type=Path, default=None,
                        help="Reference form .cs file; enables 2 context-aware checks "
                             "(IView contract style + GridStyle code consistency)")
    args = parser.parse_args()

    root = Path(args.dir)
    if not root.is_dir():
        print(f"ERROR: {args.dir} is not a directory", file=sys.stderr)
        return 1

    files = sorted(root.rglob(args.pattern))
    if not files:
        print(f"No files matching {args.pattern} in {args.dir}")
        return 0

    all_issues = []
    for f in files:
        issues = check_file(f)
        all_issues.extend(issues)

    # 上下文相关检查（需 --reference）
    if args.reference:
        if not args.reference.is_file():
            print(f"ERROR: reference file not found: {args.reference}", file=sys.stderr)
            return 1
        contract_issues = check_view_contract(root, args.reference)
        all_issues.extend(contract_issues)

    failures = [i for i in all_issues if i["status"] == "FAIL"]
    warnings = [i for i in all_issues if i["status"] == "WARN"]
    passes = [i for i in all_issues if i["status"] == "PASS"]

    from collections import Counter
    check_summary = Counter(i["check"] for i in all_issues)

    mode = "5 ctx-free + 2 ctx-aware" if args.reference else "5 context-free"
    print(f"\n{'='*60}")
    print(f"Smoke Test: {root} ({len(files)} files, {mode})")
    if args.reference:
        print(f"Reference: {args.reference}")
    print(f"{'='*60}")
    print(f"Checks: {dict(check_summary)}")
    print(f"Result: {len(passes)} pass, {len(warnings)} warn, {len(failures)} fail")

    if failures:
        print(f"\n{'─'*60}")
        print("FAILURES:")
        for issue in failures:
            print(f"  [{issue['check']}] {issue['file']}")
            if issue["detail"]:
                print(f"    -> {issue['detail']}")

    if warnings:
        print(f"\n{'─'*60}")
        print("WARNINGS:")
        for issue in warnings:
            print(f"  [{issue['check']}] {issue['file']}")
            if issue["detail"]:
                print(f"    -> {issue['detail']}")

    if not failures and not warnings:
        print("\nAll checks passed.")

    print(f"{'='*60}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
