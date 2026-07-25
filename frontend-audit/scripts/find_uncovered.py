#!/usr/bin/env python3
"""
find_uncovered.py — 找没有测试断言的自研规则（防"死规则"回归）。

交叉 all_rules() 注册的规则 ID 与测试文件里出现的规则 ID，报告
没有任何测试引用的规则。这类规则是"注册了但不工作/没回归保护"的高危
信号——SEC-REACT-002 就是这样被发现为死规则的。

注意：本工具只检查"规则 ID 是否在测试里被断言"，不验证断言强度
（正/负例是否完整）。后者靠人工 review。

运行：python scripts/find_uncovered.py
退出码：0 = 全部规则都有测试引用；1 = 存在未覆盖规则。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from audit.rules import all_rules  # noqa: E402

# 测试文件：在这些文件里搜规则 ID 字面量。
TEST_FILES = [
    SKILL_ROOT / "tests" / "test_rules_security.py",
    SKILL_ROOT / "tests" / "test_e2e.py",
    SKILL_ROOT / "tests" / "test_engine.py",
]

# 规则 ID 形态：SEC-XXX-NNN / RELI-JS-NNN
RULE_ID_RE = re.compile(r'"((?:SEC|RELI)-[A-Z]+-[0-9]+)"')


def collect_tested_ids() -> set[str]:
    ids: set[str] = set()
    for tf in TEST_FILES:
        if not tf.exists():
            continue
        for m in RULE_ID_RE.finditer(tf.read_text(encoding="utf-8")):
            ids.add(m.group(1))
    return ids


def main() -> int:
    all_ids = {r.id for r in all_rules()}
    tested_ids = collect_tested_ids()

    uncovered = sorted(all_ids - tested_ids)
    extra_in_tests = sorted(tested_ids - all_ids)  # 测试引用了不存在的规则

    print("=" * 60)
    print("frontend-audit rule test coverage")
    print("=" * 60)
    print(f"Registered rules      : {len(all_ids)}")
    print(f"Referenced in tests   : {len(tested_ids & all_ids)}")
    print(f"Uncovered (no test)   : {len(uncovered)}")
    print()

    if uncovered:
        print("⚠️  Rules with NO test reference (death-rule risk):")
        for rid in uncovered:
            print(f"  - {rid}")
        print()
        print("These rules are registered but no test asserts them. Either add a")
        print("positive/negative test, or remove the rule from ruledefs/.")
    else:
        print("✅ All registered rules have at least one test reference.")

    if extra_in_tests:
        print()
        print("⚠️  Test references unknown rules (stale tests?):")
        for rid in extra_in_tests:
            print(f"  - {rid}")

    return 1 if uncovered else 0


if __name__ == "__main__":
    sys.exit(main())
