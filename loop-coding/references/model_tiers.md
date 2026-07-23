# 模型能力分级

用于决定是否分派 builder/checker/explorer 到较轻模型。`AGENTS.md loop_coding.model_map` 优先；用户确认的 `contract.budget.max_cycles` 优先于 Tier 默认值。

## Tier

| Tier | 匹配示例 | 默认策略 |
|---|---|---|
| T1 旗舰 | GPT-4o、Claude Sonnet/Opus、Gemini 2.5、DeepSeek R1/V3、Qwen Max | 完整预算；可处理复杂重构；全量回归 |
| T2 均衡 | GPT-4 Turbo、Claude Haiku、Gemini 1.5、DeepSeek Chat、Qwen Plus | 建议 ≤4 轮；避免大重构；优先增量检查 |
| T3 经济 | GPT-3.5、旧 DeepSeek/Qwen、Mixtral、LLaMA 2 | 建议 ≤3 轮；只做精确修复；核心检查 |
| T4 未知 | 未匹配 | 建议 ≤2 轮；每轮后询问；最小改动 |

若用户声明轮次超过 Tier 建议，提示一次并等待确认。

## 分派

| 当前模型 | builder | checker | explorer |
|---|---|---|---|
| T1 | T2 | T2 | T3 |
| T2 | T3 | T3 | T3 |
| T3/T4 | 当前模型 | 当前模型 | 当前模型 |

T3/T4、环境不支持子代理、或 `skip_dispatch: true` 时使用角色模拟。模拟模式下：

- 报告 `checker_mode: "simulated"`。
- checker 结论只信命令输出，不把自然语言判断当独立审查。
- 最终报告说明 checker 非物理隔离。
