# Cycle 示例

场景：修复 Python 字符串工具库 bug，项目使用 pytest。

## Planner

```markdown
# Fix Plan

## In Progress
- [ ] BUG-001 reverse("") 应抛 ValueError (scope: src/strings.py, tests/test_strings.py)

## Pending (priority order)
- [ ] BUG-002 count_vowels 不兼容大写 (scope: src/strings.py, tests/test_strings.py)

## Done
（首轮为空）
```

## Builder

```text
改了什么：src/strings.py:42 reverse() 空字符串改为 raise ValueError
修改文件：src/strings.py
自测结果：pytest tests/test_strings.py::test_reverse_empty -v -> 1 passed
fix_plan.md：BUG-001 标记 [~]，等待 checker 验证
根因推导：症状 -> 空字符串分支返回 None -> 违反非法输入抛 ValueError 约定 -> 改为 raise
```

Builder 后当前项为 `[~]`，并向 `progress.md` 追加 Cycle 条目。

## Checker

```text
FAILED
- [pytest] tests/test_strings.py:22 - AssertionError - count_vowels("AEIOU") expected 5 got 0

    VCS 检测结果: Git — .git exists
    变更检查命令输出:
    （空 — 未修改任何文件）
    [SELF_VERIFIED] 未修改任何文件
```

## Orchestrator

- BUG-001 相关检查通过 -> `[~]` 改 `[x]`，移入 Done。
- BUG-002 移入 In Progress。
- 未 ALL GREEN 且未触发辅助条件 -> 继续 Cycle 2。

## SCOPE_DRIFT

```bash
node scripts/loop_state.js scope-drift .loop-state.json '["src/strings.py","src/lists.py"]' --fix-plan fix_plan.md
```

若 `src/lists.py` 不在当前 item scope，退出码 1，回滚本轮。
