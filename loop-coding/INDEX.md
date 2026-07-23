# loop-coding 文件索引

## 主文件

| 文件 | 说明 |
|---|---|
| `SKILL.md` | 技能入口：触发、默认模式、流程、红线 |
| `INDEX.md` | 本索引 |

## Prompts

| 文件 | 说明 |
|---|---|
| `prompts/orchestrator.md` | 编排入口和按需加载表 |
| `prompts/bootstrap.md` | 从零项目骨架 |
| `prompts/planner.md` | 生成 `fix_plan.md` |
| `prompts/explorer.md` | 顶层项目认知 JSON |
| `prompts/builder.md` | 单 item 修改与状态更新 |
| `prompts/checker.md` | 检查命令执行和自证 |
| `prompts/appendix/a0_once.md` | `--once` 单轮模式 |
| `prompts/appendix/a1-a3_loop_entry.md` | Contract、Bootstrap、基线 |
| `prompts/appendix/a4_execution.md` | 每轮执行、cross-check、SCOPE_DRIFT |
| `prompts/appendix/a5-a8_stop_dispatch.md` | 停止、分派、异常 |
| `prompts/schemas/*.json` | 角色输入 schema |

## Templates

| 文件 | 说明 |
|---|---|
| `templates/AGENTS.md` | 项目级 loop-coding 配置模板 |
| `templates/fix_plan.md` | fix_plan 模板 |
| `templates/progress.md` | progress 模板 |
| `templates/state.schema.json` | `.loop-state.json` JSON Schema |
| `templates/loop_contract.md` | Loop Contract 可填输出模板 |
| `templates/orchestrator_messages.md` | 常用用户消息模板 |
| `templates/tfs_config.example.json` | 旧版 TFS 配置兼容测试样例 |

## References

| 文件 | 说明 |
|---|---|
| `references/triggers.md` | `--once` vs 完整循环触发 |
| `references/loop_contract.md` | TRIGGER/TASK/SCOPE/BUDGET/STOP/REPORT |
| `references/example_cycle.md` | 最小完整 Cycle 示例 |
| `references/bootstrap.md` | 空项目引导 |
| `references/dirty_baseline.md` | 预存失败和不稳定检查命令 |
| `references/stop_conditions.md` | 主停止条件、辅助升级、回归 |
| `references/recovery.md` | 恢复和硬重启 |
| `references/vcs_abstraction.md` | Git/TFS/other 能力边界 |
| `references/tfs_setup.md` | TFS 登录和 workspace 前置条件 |
| `references/model_tiers.md` | 模型分派和角色模拟 |
| `references/infra_errors.md` | 超时、VCS、agent、资源异常 |

## Scripts

| 文件 | 说明 |
|---|---|
| `scripts/loop_state.js` | state 校验、stop、recover、scope-drift、cross-check |
| `scripts/vcs_git.js` | Git/TFS VCS 命令封装 |
| `scripts/loop_runner.js` | 状态机和检查执行 |

## Tests

| 文件 | 说明 |
|---|---|
| `tests/*.test.js` | runner、state、VCS、配置、cross-check、E2E 测试 |

## 使用

1. 读 `SKILL.md`。
2. 按阶段读取 `references/`、`prompts/`、`templates/` 的对应文件。
3. 验证技能：`python <skill-creator>/scripts/quick_validate.py .`
4. 验证运行时：`node tests/*.test.js`
