#!/usr/bin/env python3
"""
find_uncovered.py — 规则覆盖率审计工具

对目标代码库运行代码审查，提取所有触发的规则 ID，与规则目录对比，
报告从未触发过的规则（可能是误报规则、或代码库特殊性导致永不触发）。

运行方式:
  python find_uncovered.py <目标目录>          # 扫描全量
  python find_uncovered.py <目标目录> --diff   # 仅扫描 git diff

输出:
  - 总规则数 / 已覆盖数 / 未覆盖数
  - 按 family 分组的未覆盖规则列表（含 category 和 suggestion）
  - --verbose 时显示已覆盖规则

依赖:
  - review.py 入口（python -m review）
  - rules.py 规则目录
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

# ── Resolve skill root ─────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SKILL_ROOT / "scripts"))

from review.rules import AST_RULE_META  # noqa: E402  (sys.path bootstrap above)

# ── Regex: extract rule IDs from analyzer source ──────────────────────

AST_ADD_RE = re.compile(
    r'\b(?:Add|CheckPascalCase)\(\s*(?:\w+\.\w+,\s*)?'
    r'"(?P<id>LEGACY_[A-Za-z0-9_]+)"'
)
SEM_ADD_RE = re.compile(
    r'\bAdd\(\s*diagnostics,\s*[^,]+,\s*[^,]+,\s*'
    r'"(?P<id>(?:SEM|USELESS|EF|ASP|P)\d{2,4})"'
)

AST_CS = SKILL_ROOT / "scripts" / "csharp-ast-analyzer" / "Program.cs"
SEM_CS = SKILL_ROOT / "scripts" / "csharp-semantic-analyzer" / "Program.cs"


def extract_all_rules() -> set[str]:
    """从源码提取所有注册的规则 ID。"""
    rules: set[str] = set()
    if AST_CS.exists():
        text = AST_CS.read_text(encoding="utf-8", errors="ignore")
        rules.update(AST_ADD_RE.findall(text))
    if SEM_CS.exists():
        text = SEM_CS.read_text(encoding="utf-8", errors="ignore")
        rules.update(SEM_ADD_RE.findall(text))
    return rules


# ── Run review, extract fired rule IDs ────────────────────────────────

def run_review_get_rules(target: str, use_diff: bool) -> list[str]:
    """
    运行 review 并从标准输出中提取触发的规则 ID。
    使用 compact JSON 格式（包含 top_rules），提取所有出现的规则 ID。
    返回规则 ID 列表（可能有重复）。
    """
    cmd = [
        sys.executable,
        str(SKILL_ROOT / "scripts" / "review.py"),
        "--format", "compact",
        "--output-mode", "by-rule",
        "--max-issues", "99999",
    ]
    if use_diff:
        cmd += ["--diff", "HEAD"]
        cmd += ["--target", target]
    else:
        cmd += ["--all", target]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        print("⚠️  review 超时（5min），无法提取规则覆盖率", file=sys.stderr)
        return []
    except FileNotFoundError:
        print("⚠️  找不到 review.py，请确认 skill 根目录正确", file=sys.stderr)
        return []

    fired_rules: list[str] = []

    # review.py 输出包含 ANSI 颜色代码（stderr）和 JSON（stdout）。
    # 找第一个 '{' 截取 JSON 主体。
    raw = result.stdout
    first_brace = raw.find("{")
    if first_brace < 0:
        print("⚠️  review 输出中没有 JSON", file=sys.stderr)
        return fired_rules

    json_text = raw[first_brace:]
    try:
        obj = json.loads(json_text)
    except json.JSONDecodeError as e:
        print(f"⚠️  无法解析 review JSON: {e}", file=sys.stderr)
        return fired_rules

    # top_rules 包含每个规则的聚合统计
    top_rules = obj.get("top_rules", [])
    fired_rules = [entry["rule"] for entry in top_rules if entry.get("rule")]

    return fired_rules


# ── Rule family grouping ──────────────────────────────────────────────

FAMILIES = [
    ("LEGACY_", "Legacy (AST)"),
    ("SEM", "Semantic"),
    ("USELESS", "Dead Code"),
    ("EF", "EF Core"),
    ("ASP", "ASP.NET"),
    ("P0", "Performance"),
    ("P", "Performance"),
    ("R0", "Reliability"),
    ("R", "Reliability"),
    ("N0", "Naming"),
    ("N", "Naming"),
    ("T0", "Test"),
    ("T", "Test"),
    ("S", "Style"),
    ("SEC", "Security"),
    ("SH", "Security Hotspot"),
    ("WIN", "Windows API"),
    ("LOG", "Logging"),
    ("SQL", "SQL"),
    ("ARCH", "Architecture"),
    ("DI", "DI/IoC"),
    ("CS", "Compiler"),
    ("WHITESPACE", "Whitespace"),
]

FAMILY_LABELS: dict[str, str] = {prefix: label for prefix, label in FAMILIES}


def family_of(rule_id: str) -> str:
    for prefix, label in FAMILIES:
        if rule_id.startswith(prefix):
            return label
    return "Other"


# ── Print helpers ─────────────────────────────────────────────────────

def divider(char="─", width=72):
    print(char * width)


def rule_info(rule_id: str) -> tuple[str, str]:
    """返回 (category, suggestion) 从规则目录，未找到则为 (?)。"""
    meta = AST_RULE_META.get(rule_id, {})
    return meta.get("category", "?"), meta.get("suggestion", "（无 suggestion）")


def print_report(
    all_rules: set[str],
    fired_set: set[str],
    fired_rules_list: list[str],
    verbose: bool,
):
    uncovered = all_rules - fired_set

    total = len(all_rules)
    covered = len(fired_set)
    not_covered = len(uncovered)

    print()
    divider("═")
    print("  规则覆盖率审计报告")
    divider("═")
    print(f"  目标目录 : {'git diff' if '--diff' in sys.argv else '(全量)'}")
    print(f"  总规则数 : {total}")
    print(f"  已覆盖   : {covered}  ({covered/total*100:.1f}%)")
    print(f"  未覆盖   : {not_covered}  ({not_covered/total*100:.1f}%)")
    divider()

    if verbose and fired_set:
        print(f"\n  ✅ 已覆盖规则 ({covered}):")
        by_family: Counter = Counter(family_of(r) for r in sorted(fired_set))
        for fam, cnt in by_family.most_common():
            rules_in_fam = sorted(r for r in fired_set if family_of(r) == fam)
            print(f"\n    [{fam}] ×{cnt}")
            for r in rules_in_fam[:20]:  # 限制每组显示数量
                cat, _ = rule_info(r)
                print(f"      {r:<45} {cat}")
            if len(rules_in_fam) > 20:
                print(f"      ... 另有 {len(rules_in_fam)-20} 条")

    if not covered:
        print("\n  ⚠️  未运行 review 或未检测到 issues（all_rules 可能来自源码提取）")

    if not uncovered:
        print("\n  🎉 所有规则均已覆盖！")
        return

    print(f"\n  ❌ 未覆盖规则 ({not_covered}):")
    by_family: Counter = Counter(family_of(r) for r in sorted(uncovered))
    for fam, cnt in by_family.most_common():
        rules_in_fam = sorted(r for r in uncovered if family_of(r) == fam)
        print(f"\n    [{fam}] ×{cnt}")
        for r in rules_in_fam:
            cat, suggestion = rule_info(r)
            print(f"      {r:<45} {cat}")
            if suggestion and suggestion != "（无 suggestion）":
                print(f"        → {suggestion[:80]}{'...' if len(suggestion) > 80 else ''}")

    print()
    # 热力图：每条规则触发次数
    if fired_rules_list:
        print("  📊 规则触发热力图（Top 15）:")
        by_count = Counter(fired_rules_list).most_common(15)
        max_count = by_count[0][1]
        for rule_id, count in by_count:
            bar = "█" * int(count / max_count * 30)
            print(f"    {rule_id:<45} {count:>4}  {bar}")
    print()


# ── Main ──────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(
        description="审计代码审查规则覆盖率——报告在目标代码库中从未触发的规则"
    )
    parser.add_argument(
        "target",
        nargs="?",
        default=".",
        help="目标目录（默认: 当前目录）",
    )
    parser.add_argument(
        "--diff",
        action="store_true",
        help="仅扫描 git diff HEAD 的变更文件（而非全量扫描）",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="显示已覆盖规则",
    )
    parser.add_argument(
        "--no-run",
        action="store_true",
        help="不运行 review，仅从源码提取规则目录",
    )
    args = parser.parse_args()

    # 1. 提取全量规则
    all_rules = extract_all_rules()
    if not all_rules:
        print("❌ 无法从源码提取任何规则，检查 csharp-ast-analyzer / csharp-semantic-analyzer 是否存在")
        return 1

    print(f"✅ 从源码提取到 {len(all_rules)} 条规则")

    if args.no_run:
        return 0

    # 2. 运行 review 并提取触发的规则
    fired_list = run_review_get_rules(args.target, args.diff)
    fired_set = set(fired_list)

    # 3. 输出报告
    print_report(all_rules, fired_set, fired_list, args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
