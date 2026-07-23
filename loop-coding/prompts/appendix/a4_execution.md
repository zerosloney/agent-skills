# A4. 循环执行

每轮最多执行到 `contract.budget.max_cycles`。

## 阶段

1. Cycle start：记录 VCS 和本地变更指纹。
2. Builder：修改代码，更新 `fix_plan.md` / `progress.md`。
3. Pre-check：记录 `pre_checker` 快照。
4. Checker：运行检查。
5. Post-check：计算 `changedFilesSince(cycle_start)`，跑 SCOPE_DRIFT。
6. 判断：继续或停止。

特殊阶段：Cycle -1 bootstrap；Cycle 0 planner；Cycle 1a explorer（仅 planner 标记 recommended 时）。

## fix_plan 标记

- builder: 当前项 `[ ]` -> `[~]`。
- checker 通过后 orchestrator: `[~]` -> `[x]`，移入 Done。
- 仍失败：保持 `[~]`，下一轮继续。

## Cross-check

```bash
node scripts/loop_state.js cross-check .loop-state.json --fix-plan fix_plan.md --progress progress.md
```

ERROR 先修复再下一轮；WARN 可记录后继续。

## SCOPE_DRIFT

```bash
node scripts/loop_state.js scope-drift .loop-state.json '["file"]' --fix-plan fix_plan.md
```

要求：实际修改文件 ⊆ item.scope，且 item.scope ⊆ contract.scope。失败则回滚本轮。
