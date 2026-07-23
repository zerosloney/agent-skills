# A5-A8. 停止、分派、异常

## 停止判断

每轮结束按顺序：

1. ALL GREEN -> success。
2. 用户退出 -> aborted_by_user。
3. 轮次用尽 -> incomplete。
4. 辅助条件 -> incomplete，等待用户决策。
5. 否则下一轮。

报告字段见 `references/loop_contract.md`。

## 模型分派

先读项目 `AGENTS.md loop_coding.model_map`；没有则按 `references/model_tiers.md`。目标模型不可用时降级到当前会话模型。

## 异常

遇到 check 超时、VCS 失败、agent 崩溃、资源不足时加载 `references/infra_errors.md`。基础设施异常不当作代码失败。
