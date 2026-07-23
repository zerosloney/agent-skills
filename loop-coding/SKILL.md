---
name: loop-coding
description: 循环式 AI 编码：用 builder 修改、checker 验证，直到检查通过或触发停止条件。仅在编码、测试、修 bug、可验证功能开发、从零项目引导，或用户明确要求“循环/反复/直到通过”时使用；默认优先 --once 单轮模式。
---

# loop-coding

用最少轮次完成可验证的编码任务。主 agent 只做编排：先定义 Loop Contract，再按需调用 builder / checker / planner / explorer，并把跨轮状态写入文件。

## 默认选择

- 用户明确要求“循环、反复、直到通过”时，进入完整循环。
- 其他编码任务默认用 `/loop-coding --once <任务>`：生成一次、检查一次，失败则报告下一步，不自动重试。
- 纯探索、无检查命令、范围不清的任务，不启动循环；先澄清或做普通编码流程。

## 启动前必须确认 Loop Contract

任何代码改动前，先声明并等待用户明确确认：

```text
=== Loop Contract ===
TRIGGER : {触发信号}
TASK    : {一句话任务目标}
SCOPE   : {允许修改的文件/目录}
BUDGET  : {N} cycles max | 单轮 < 30 min
STOP    : ALL GREEN | 用户退出 | 轮次用尽 | 辅助条件升级
REPORT  : success / incomplete / aborted
====================
```

用户回复“开始 / ok / 确认”后，把契约写入 `.loop-state.json.contract`。如果用户修改字段，重新声明并再次等待确认。

细则读取：`references/loop_contract.md`、`templates/loop_contract.md`。

## 按需加载

启动时不要一次读完所有文档。按阶段只读相关文件：

- 触发判断：`references/triggers.md`
- 契约声明：`references/loop_contract.md`、`templates/loop_contract.md`
- 空项目引导：`references/bootstrap.md`
- 脏基线处理：`references/dirty_baseline.md`
- 中断恢复：`references/recovery.md`
- Cycle 示例：`references/example_cycle.md`
- 停止/升级判断：`references/stop_conditions.md`
- Git/TFS 快照与恢复：`references/vcs_abstraction.md`
- TFS 前置校验：`references/tfs_setup.md`
- 模型分级：`references/model_tiers.md`
- 基础设施异常：`references/infra_errors.md`

文件总索引见 `INDEX.md`。

## 执行流程

1. 识别触发方式，选择 `--once` 或完整循环。
2. 声明 Loop Contract 并等待确认。
3. 若项目为空，执行 Bootstrap：创建骨架、建立检查命令、生成种子测试、写入 `AGENTS.md`。
4. 跑基线检查；若已有失败，先向用户确认是否纳入修复范围。
5. TFS 项目先完成凭证、workspace 和签出确认；Git 项目跳过。
6. 每轮依次执行：记录快照 -> builder 修改 -> 记录快照 -> checker 运行检查 -> 记录 diff 和结果 -> 判断继续或停止。
7. 输出 success / incomplete / aborted 报告；辅助停止条件触发时输出升级报告并等待用户决策。

## 状态文件

- `.loop-state.json`：契约、baseline、cycles、registry、result。
- `fix_plan.md`：当前任务列表。
- `progress.md`：跨轮学习日志，只追加。
- `AGENTS.md`：项目局部约定和检查命令。

## 角色提示词

- `prompts/orchestrator.md`
- `prompts/bootstrap.md`
- `prompts/planner.md`
- `prompts/explorer.md`
- `prompts/builder.md`
- `prompts/checker.md`

## 红线

- 不弱化测试来通过。
- 不删除、跳过或隐藏失败检查。
- 不自动执行带破坏性的修复或提交。
- 不自动 `tf checkin`。
- 不删除既有 `progress.md` / `fix_plan.md` 的 Done 内容。
- 硬重启只能由用户主动触发；orchestrator 只能建议。
