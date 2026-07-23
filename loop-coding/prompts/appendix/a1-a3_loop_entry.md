# A1-A3. 循环入口

## A1 Contract

输出 `templates/loop_contract.md` 的 6 字段，等待用户明确“开始 / ok / 确认”。scope 为空时不得接受确认。

用户修改字段 -> 更新 -> 重新声明 -> 再确认。

## A2 Bootstrap

触发：项目根不存在或无源文件。

加载 `references/bootstrap.md` 和 `prompts/bootstrap.md`，完成后写：

```json
{ "bootstrap": { "completed": true, "stack": "..." } }
```

## A3 基线

1. 运行所有检查命令。
2. 失败命令重跑一次验证稳定性。
3. 写 baseline。
4. 有预存失败 -> 加载 `references/dirty_baseline.md` 并询问是否纳入修复。
5. 检测到既有 `.loop-state.json` -> 加载 `references/recovery.md`。
