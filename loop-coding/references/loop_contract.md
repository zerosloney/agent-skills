# Loop Contract

完整循环启动前必须向用户声明 6 个字段并等待明确确认。输出模板见 `templates/loop_contract.md`；无回应不视为接受。

用户确认后写入 `.loop-state.json.contract`；用户修改任一字段时，更新并重新确认。

## 字段规则

### TRIGGER

显式 `/loop-coding <任务>` 或隐式“反复/循环/迭代” + “直到通过/全绿/成功”。模糊时使用 `--once`。详见 `references/triggers.md`。

### TASK

从 TRIGGER 提炼 1-2 句话目标。去掉 `/loop-coding`、过程描述和检查细节；任务拆解放 `fix_plan.md`。

### SCOPE

循环总允许范围。优先级：

1. 用户显式 `--scope`
2. `fix_plan.md` 所有 item 的 `scope:`
3. `baseline_failures` 涉及文件
4. 用户中途追加并重新确认

Cycle 1、`--once` 和已确认契约必须有非空 scope。Bootstrap / Planner 草稿阶段可临时为空。

每轮 Post-check 跑：

```bash
node scripts/loop_state.js scope-drift .loop-state.json '<changed_files_json>' --fix-plan fix_plan.md
```

要求：实际修改文件 ⊆ item.scope，且 item.scope ⊆ contract.scope。失败则回滚本轮。

### BUDGET

默认 `max_cycles = 5`。用户显式 `--max-cycles N` 优先；单轮超过 30 min 暂停询问。预算耗尽触发升级报告。

### STOP

主条件：ALL GREEN、用户退出、轮次用尽。辅助条件：重复失败、回归、无实质进展、能力边界（`capability_boundary`）、fix_plan 全部 Done。详见 `references/stop_conditions.md`。

### REPORT

- `success`: cycles_used、fixed_items、final_check_status、artifacts、duration、follow_up_optional。
- `incomplete`: stopped_at_cycle、stop_reason、failed_items、attempted_fixes、why_loop_wont_help、recommendation、user_decision_required=true。
- `aborted_by_user`: stopped_at_cycle、state_path、resume_hint。

报告始终输出到对话，并写入 `.loop-state.json.result`。

## 反模式

- 未确认契约就进入 Cycle 1。
- 预算耗尽后自动续跑。
- 扩大 scope 不重新确认。
- 辅助条件触发后强行下一轮。
- 弱化测试、删除失败用例、隐藏失败检查。
