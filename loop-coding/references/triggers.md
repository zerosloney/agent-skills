# 触发方式

默认使用 `--once`；只有用户明确表达迭代意图才进入完整循环。

## 显式

| 指令 | 行为 |
|---|---|
| `/loop-coding <任务>` | 完整循环 |
| `/loop-coding --once <任务>` | 单次生成 + 单次检查 |
| `/loop-coding --hard-reset` | 硬重启 |
| `/loop-coding --hard-reset cycle N` | 回退到指定轮次 |

## 隐式循环

用户同时包含两类语义时触发：

- 反复类：反复、一直、迭代、多轮、循环、repeatedly、keep、loop。
- 终止类：直到通过、全绿、成功为止、until green、until it passes。

只有“修 bug / 加功能 / 测试失败”不触发循环，按 `--once`。

## 模糊处理

无法确定时选择 `--once`，并在失败报告中提示用户可说“反复到全绿”升级为完整循环。

## 循环内指令

- `停止` / `stop`: 退出循环。
- `硬重启` / `hard reset`: 进入恢复协议。
- `状态` / `status`: 输出当前循环状态。
