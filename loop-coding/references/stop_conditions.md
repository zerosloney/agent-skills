# 停止条件

## 主条件

| # | 条件 | 行为 |
|---|---|---|
| 1 | ALL GREEN | 输出 success |
| 2 | 用户退出 | 输出 aborted_by_user |
| 3 | 轮次用尽 | 输出 incomplete |

ALL GREEN：所有可靠检查通过。脏基线下，任务范围失败消除且无新失败即可；`unreliable_commands` 只做参考。

## 辅助条件

触发后输出升级报告并等待用户决策：

| # | 条件 | schema 标识符 |
|---|---|---|
| 4 | 连续两轮相同失败 | `repeat_failure` |
| 5 | 回归 | `regression` |
| 6 | 连续两轮同一根因，无实质进展 | `no_progress` |
| 7 | 外部依赖/环境超出能力边界 | `capability_boundary` |
| 8 | `fix_plan.md` 全部 Done | `fix_plan_done` |

> 注意：`capability_boundary` 指环境/依赖能力受限，不是 `contract.scope` 范围越界——后者由 SCOPE_DRIFT 检测处理（回滚本轮，不走辅助升级）。

用户可选择继续、硬重启或放弃。超过预算继续时，必须明确确认突破轮次上限。

## 回归判定

- 干净基线 + 新失败 = 回归。
- 脏基线 + 新失败不在 `baseline_failures` = 回归。
- 脏基线失败减少 = 改善，允许继续。
- 脏基线失败增加 = 回归。

失败指纹格式：`[check] file:line - error_type - description`；比较时忽略行号漂移。

## 升级报告字段

`stopped_at_cycle`、`stop_reason`、`failed_items`、`attempted_fixes`、`why_loop_wont_help`、`recommendation`、`user_decision_required=true`。

## 上下文压缩

Cycle 3 起只保留最近 2 轮完整报告，早期轮次压成“解决了什么/仍失败什么”。当前残留失败必须完整传递。
