#!/usr/bin/env python3
"""
count_rules.py — frontend-audit 规则数统计（文档漂移校验）。

这是"frontend-audit 实际有多少条自研规则"的单一权威源，用于校验
SKILL.md / references/*.md 里声称的规则数不漂移。

运行：python scripts/count_rules.py
退出码：0 = 与 SKILL.md 声明一致；1 = 漂移（需更新文档或代码）。

数据来源：直接 import audit.rules.all_rules()（比 grep 源码更可靠）。
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from audit.rules import all_rules  # noqa: E402

# SKILL.md / references/rules-catalog.md 里声明的规则总数。
# 改动规则集时同步更新这里与文档；count_rules.py 会在不一致时 exit 1。
DECLARED_TOTAL = 13


def main() -> int:
    rules = all_rules()
    total = len(rules)

    by_dim = Counter(r.dimension for r in rules)
    by_triage = Counter(r.triage for r in rules)
    by_sev = Counter(r.severity for r in rules)

    print("=" * 60)
    print("frontend-audit rule counts (computed from ruledefs/)")
    print("=" * 60)
    print(f"Total self-authored rules : {total}")
    print(f"SKILL.md declares         : {DECLARED_TOTAL}")
    print()
    print("By dimension:")
    for dim in ("security", "reliability", "best-practice", "arch"):
        print(f"  {dim:16s}: {by_dim.get(dim, 0)}")
    print("By triage:")
    for t in ("deterministic", "agent_verify", "agent_only"):
        print(f"  {t:16s}: {by_triage.get(t, 0)}")
    print("By severity:")
    for s in ("error", "warning", "info"):
        print(f"  {s:16s}: {by_sev.get(s, 0)}")
    print()
    print("-" * 60)
    print("Rule IDs:", ", ".join(sorted(r.id for r in rules)))

    if total != DECLARED_TOTAL:
        print()
        print(f"DRIFT: code has {total} rules but SKILL.md declares {DECLARED_TOTAL}.")
        print("Update SKILL.md / references/rules-catalog.md OR DECLARED_TOTAL in this script.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
