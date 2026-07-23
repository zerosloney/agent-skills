# 脏基线处理

脏基线 = loop-coding 启动前项目已有失败。

## 基线检查

1. 运行所有检查命令。
2. 对失败命令重跑一次；两次结果不同则标记为 `unreliable_commands`，不计入 ALL GREEN。
3. 写入 `.loop-state.json.baseline`。
4. 若存在预存失败，提取失败指纹并询问用户是否纳入本轮修复。

失败命令重跑策略：只重跑第一次失败的命令；第一次通过的命令不重跑。

## 用户确认

```text
⚠️ 脏基线检测
项目在本次任务前已有失败项：
{baseline_failures}

是否需要一并修复？
- 是：纳入 scope
- 否：仅关注新失败（推荐）
```

## 失败指纹

格式：

```text
[<check_name>] <file>:<line> - <错误类型> - <描述>
```

比较连续失败或回归时忽略行号，避免无意义漂移。

## 回归判定

- 干净基线：任何新失败都是回归。
- 脏基线：不在 `baseline_failures` 的失败是回归。
- `unreliable_commands` 只做参考，不参与 ALL GREEN。

详细停止行为见 `references/stop_conditions.md`。
