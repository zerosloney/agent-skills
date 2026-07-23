# A0. --once

无循环语义时使用。只生成一次、检查一次，不自动重试。

## 流程

1. 输出：

```text
--once 模式：单次生成 + 单次检查，不进入多轮循环。如需迭代请说“反复到全绿”。
```

2. 初始化：

```bash
node scripts/loop_runner.js init <project_root> <task_brief> --once
```

`max_cycles=1`，`contract.confirmed_at` 自动写入，scope 默认 `["."]`。

3. 注入 builder，`fix_plan_in_progress = "无"`，除非已有单项计划。
4. 记录 builder：

```bash
node scripts/loop_runner.js record-builder .loop-state.json <modified_files_json>
```

5. 注入 checker。
6. ALL GREEN 输出完成摘要；FAILED 输出失败摘要和升级提示。

用户要求“继续修/直到通过”时，转完整循环并声明 Loop Contract。
