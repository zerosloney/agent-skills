# 基础设施异常

基础设施异常不是代码失败。不要把超时、VCS 错误、agent 崩溃、磁盘/网络问题当作业务 bug。

## 通用规则

- 同类异常最多重试 2 次（共 3 次尝试）。
- 仍失败则暂停循环并写入 `.loop-state.json.cycles[N].infra_errors`。
- 不吞异常；报告命令、对象、失败原因，避免记录密钥。

## Check 超时

默认阈值由 `scripts/loop_runner.js run-checks` 执行：

| 类型 | 默认 |
|---|---|
| test | 10 min |
| lint | 3 min |
| typecheck | 5 min |
| format | 2 min |
| other | 5 min |

处理：记录 `check_timeout` -> 重试该命令 -> 连续 3 次超时则暂停，提示用户检查死循环、外部服务或资源不足。

## VCS 失败

常见模式：

- `not a git repository`: VCS 检测错误。
- `lock file` / `locked`: 锁文件残留，可清理后重试。
- `CONFLICT`: 暂停，报告冲突文件。
- `permission denied` / `authentication failed` / `TF30063`: 暂停，要求用户处理凭证。

若 VCS 不可用，记录 `config.vcs_degraded: true`，关闭精确 SCOPE_DRIFT，仅在受限模式继续。

## Agent 崩溃

- builder 崩溃：若产生半成品改动，先 stash/shelve；下一轮恢复或重做同一 item。
- checker 崩溃：本轮不算 ALL GREEN，重试一次；仍失败则暂停。
- explorer 崩溃：记录 skipped，不阻塞循环。

## 资源/网络问题

- 磁盘满、内存不足、文件句柄耗尽：立即暂停，不重试。
- TFS 401/403/TF30063：提示用户重新 `tf login`。
- TFS 503：间隔 30 秒重试一次，仍失败则暂停。

## 多异常优先级

P0 资源问题 > P1 登录/网络 > P2 Agent 崩溃 > P3 Check 超时 > P4 VCS 降级。

同轮多异常时，按最高优先级决定是否暂停，并把所有异常写入 `infra_errors`。

## 记录格式

```json
{
  "type": "check_timeout",
  "command": "dotnet test",
  "elapsed_sec": 620,
  "timeout_sec": 600,
  "attempt": 1,
  "resolved": false
}
```
