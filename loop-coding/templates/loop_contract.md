# Loop Contract 模板

Cycle 1 前填充并输出；用户必须明确“开始 / ok / 确认”。字段规则见 `references/loop_contract.md`，持久化结构见 `templates/state.schema.json`。

```text
=== Loop Contract ===
TRIGGER : {触发信号原文}
TASK    : {一句话任务目标}
SCOPE   :
         - {file_or_dir}
BUDGET  : {N} cycles max | 单轮 < 30 min
STOP    : ALL GREEN | 用户退出 | 轮次用尽 | 辅助条件升级
REPORT  : success / incomplete / aborted，写入 .loop-state.json.result
START_AT: {ISO8601}
CONFIRMED_AT: (用户确认后补填)
CONFIRM : 回复 "开始" / "ok" / "确认" 接受，或提出修改
====================
```
