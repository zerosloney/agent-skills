# troubleshooting

> **职责契约**：本文档是 frontend-audit 错误处理与故障排查的**扩展决策表**。
> 只包含：错误现象 → 根因 → Agent 行为 → 用户提示。
> 不包含：SKILL.md §6 已覆盖的速查项（本文是扩展版）。
>
> Agent 使用路径：遇到非预期输出 / exit code 异常时读。
> 数据来源：`scripts/audit/errors.py` + 实测。

## Exit Code 决策表

| exit | 含义 | 典型原因 | Agent 行为 |
|------|------|----------|-----------|
| 0 | 通过 | 无 error，达 threshold | 报告"无严重问题" |
| 1 | 有问题 | 有 error finding 或未达 threshold | 列 error findings |
| 3 | 配置错误 | argparse 拒绝参数 | 检查命令，重试 |
| 4 | 工具缺失 | （本版本不会主动抛，linters/deps 走降级而非抛错） | 理论存在，实际罕见 |
| 5 | 内部错误 | Python 异常 | 报告 stderr 全文给用户 |

## 常见现象 → 排查

### 现象：scan 返回 0 findings，但项目明显有问题

**根因**：大概率 lint/deps 层全跳过了。
**排查**：检查 `degradation_notices`：
- 有 `eslint not found` → 装不了 eslint 时，至少 security/reliability 自研规则该有输出；若连这都没有，检查文件扩展名是否在 `.js/.jsx/.ts/.tsx/.mjs/.cjs/.vue/.svelte` 内。
- 有 `package.json not found` → 路径错了，不是前端项目根目录。

### 现象：Windows 上 `npm found on PATH but not executable`

**根因**：`shutil.which("npm")` 返回了无扩展名的 shell wrapper，Windows `CreateProcess` 无法直接执行。
**修复**：`_resolve_npm()` 已优先找 `npm.cmd`。若仍失败，让用户：
1. 确认 Node.js 装在标准路径；
2. 或直接用 `npx npm audit` 手动跑，把 JSON 贴给 Agent 分析。

### 现象：eslint 输出几千条，撑爆上下文

**根因**：用户加了 `--include-lint`。
**修复**：去掉 `--include-lint`，eslint 会折叠成单条 `ESLINT-SUMMARY`。需要详情时用 `--format json` 输出到文件，让用户自己看。

### 现象：tree-sitter 装了但 AST 规则还是正则行为

**根因**：本版本所有规则的检测逻辑写在 `visitors.py` 的正则层；tree-sitter parser 已初始化（`tree_sitter_available()` 返回 True），但**规则尚未迁移到 AST visitor**。这是有意的 MVP 取舍。
**升级路径**：在 `visitors.py` 增加 `_scan_with_tree_sitter()`，用 AST 节点匹配替代正则，提升跨行/复杂表达式的准确率。

### 现象：fixture 测试失败

**根因**：规则正则变了，或 fixture 代码改了。
**排查**：
```bash
cd frontend-audit
python -m pytest tests/test_e2e.py -v
python -m pytest tests/test_rules_security.py -v
```
若 `test_detects_all_seed_findings` 失败，对照 `scripts/fixtures/react-demo/src/UserProfile.tsx` 与 `test_rules_security.py` 的预期 ID 列表。

### 现象：SEC-SECRET-004 误报很多

**根因**（已大幅缓解）：旧版变量名启发式正则有非贪婪 bug，对 `mockApiKey` 误报、对真实 `apiKey` 漏报。H5 修复后：变量名扁平化匹配 credential 词，且 `mock`/`fake`/`dummy`/`test`/`example`/`sample`/`fixture` 前缀被抑制，triage 降为 `agent_only`（Agent 调查后可 dismissed）。
**仍可能的残余误报**：非 mock 前缀但实际是配置项的变量（如 `secretMode = "enabled"`）。这类由 `agent_only` triage 兜底，Agent 读代码后 dismiss。

## 降级模式可信度矩阵

| 模式 | security | reliability | best-practice | deps |
|------|:--------:|:-----------:|:-------------:|:----:|
| 全量（eslint+tsc+npm 都在） | ✅ | ✅ | ✅ | ✅ |
| 缺 eslint/tsc | ✅ | ✅ | ❌ | ✅ |
| 缺 npm | ✅ | ✅ | ✅ | ❌ |
| 缺 tree-sitter（正则降级） | ⚠️ 可能漏报 | ⚠️ 可能漏报 | — | — |
| 全缺（纯自研规则） | ✅ | ✅ | ❌ | ❌ |

✅ = 结论可信 | ❌ = 不可信（必须明示） | ⚠️ = 部分可信（标注限制）
