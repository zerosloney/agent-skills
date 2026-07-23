# 恢复与硬重启

## 状态恢复

检测到 `.loop-state.json` 时：

1. `result` 存在 -> 汇报历史结果并退出。
2. 有 cycles 无 result -> 继续循环。
3. 最近 cycle 缺 `checker_report` -> 回退一轮重跑 checker。
4. 缺 baseline -> 重跑基线。
5. 校验当前 VCS 状态与 registry 快照是否一致。

VCS 不一致时：

| 状态 | 动作 |
|---|---|
| HEAD 不一致 + 本地修改 | 询问用户保留或丢弃 |
| HEAD 不一致 + 无本地修改 | 记录当前位置后回退到 registry 快照 |
| TFS 不一致 | 走签出确认，用户确认后 `tf undo` |

## 恢复消息

```text
⚠️ 检测到未完成的循环
当前：Cycle {N}
工作区被外部修改
选项：1. 保留  2. 丢弃
```

## 硬重启

只有用户可触发：`/loop-coding --hard-reset` 或“硬重启”。orchestrator 只能推荐。

推荐条件：连续相同失败、连续同根因、或升级报告说明继续循环无帮助。

执行：

1. 用户确认回退目标。
2. 读取 `registry[N].pre_checker.vcs_head`。
3. 回退前备份：Git `git stash push -u`；TFS `tf shelve`。
4. 回退：Git reset/restore；TFS 展示 pending changes，经用户确认后 `tf undo /recursive`。
5. `fix_plan.md` 当前项退回 Pending；Done 段不动。
6. 把失败尝试写入 `progress.md`。
7. 询问是否调整 prompt 后重跑。

## 审计记录

追加 `registry.hard_reset_events[]`，至少包含 cycle、回退前后 VCS 头、stash/shelveset、用户是否修改 prompt、timestamp。

## 红线

- 未经用户明确“硬重启”不得执行。
- reset/undo 前必须备份。
- 不删除 Done 段和既有 `progress.md`。
- TFS undo 必须先展示 pending changes 并确认。
