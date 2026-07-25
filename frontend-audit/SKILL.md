---
name: frontend-audit
description: |
  JavaScript/TypeScript + React 前端代码审查 CLI，编排 eslint + tsc + npm audit + 自研 AST/正则语义规则。
  5 维度覆盖：安全（OWASP Top 10 / CWE 映射：XSS、eval、open-redirect、postMessage、硬编码密钥）、可靠性、最佳实践、架构、依赖（CVE）。
  13 条自研规则（SEC-REACT/SEC-JS/RELI-JS/SEC-SECRET）+ eslint/tsc 动态编排 + npm audit CVE。
  两阶段 Triage→Verify 协议 + json-compact 输出（token 友好）+ SARIF（GitHub Code Scanning）+ markdown 报告。
  Agent 通过 subprocess 调用 scripts/audit.py，用户不接触 CLI。
  触发：用户说"审查前端代码" / "JS 安全扫描" / "React review" / "前端依赖安全" / "XSS 检查" 时。
agent_created: true
version: 0.1.0
---

# frontend-audit — Agent 指令集

## 核心原则

1. **先跑 CLI 再报告**：所有结论必须来自 `audit.py` 的输出，不要凭直觉描述安全问题。
2. **默认 json-compact**：`--format json-compact` 是默认且唯一推荐的 token 高效格式；markdown 仅在用户要给人看时用。
3. **降级要明示**：eslint/tsc/npm 缺失时会输出 `degradation_notices`，必须在报告里显著告知"哪些维度本次未检查"。
4. **不重新发明 linting**：自研规则只覆盖 eslint 盲区（React XSS sink、数据流、密钥）；样式/最佳实践交给 eslint。

脚本路径：`skill://frontend-audit/scripts/audit.py`

---

## §0. 前置条件

| 组件 | 必须？ | 说明 |
|------|--------|------|
| Python ≥ 3.10 | ✅ 必须 | CLI 引擎运行环境 |
| tree-sitter（可选） | ⚠️ 可选 | 装了走精确 AST；不装自动降级为正则模式（见 §5） |
| Node.js + eslint + tsc | ⚠️ 可选 | 装了跑 lint/type 层；不装自动降级，只跑自研规则 |
| npm | ⚠️ 可选 | 装了跑 `npm audit` 查依赖 CVE；不装跳过依赖维度 |

**关键**：所有"可选"组件缺失都不会让 CLI 失败，只会进入降级模式并产生 `degradation_notices`。Agent 必须把这些 notice 转达给用户。

---

## §1. 命令速查

### 1.1 场景速查表

| 用户意图 | 命令 | 备注 |
|---------|------|------|
| 完整审查一个前端项目 | `scan --path <dir>` | 默认全维度 + json-compact |
| 只查安全问题（XSS/密钥） | `scan --path <dir> -d security --no-lint` | 最快，纯自研规则 |
| 只查依赖 CVE | `deps --path <dir>` | 等价于 `npm audit` 的结构化输出 |
| 列出所有规则 | `rules` | 看自研规则 ID / 维度 / CWE |
| PR 质量门禁 | `scan --path <dir> --threshold B` | 低于 B 级 exit 1 |
| 给人看的报告 | `scan --path <dir> --format markdown` | 仅展示用，token 大 |

### 1.2 Token 节约模式

**🚨 Token 节约硬规则（不可违反）：**

1. **format 永远 `json-compact`**（默认值，不要改成 json）。
2. **eslint 默认折叠为单条 summary**：除非用户明确要每条 lint 详情，**不要**加 `--include-lint`（实测一个中型项目 eslint 可输出几千条，会撑爆上下文）。
3. **聚焦维度优先**：用户只问安全时，用 `-d security --no-lint`，跳过 lint/deps 层。
4. **findings 已硬上限 50 条**（json-compact 自动截断），不要担心溢出。

### 1.3 Exit Code

| Code | 含义 | Agent 行为 |
|------|------|-----------|
| 0 | 通过（无 error 级问题，且通过 threshold 门禁） | 报告"无严重问题" |
| 1 | 有 error 级问题 / 未通过 threshold | 列出 error findings |
| 3 | 配置错误（argparse 拒绝、输入非法） | 检查命令参数 |
| 5 | 内部错误（未捕获 AuditError） | 报告 stderr，让用户看 |

**重要**：eslint/tsc/npm 缺失**不会**导致非零 exit——这些 tier 走降级，结果在 `degradation_notices` 里。不要等 "tool missing" 的 exit code，它不存在。

---

## §2. Agent 决策规则

### 2.1 意图映射

| 用户输入 | Agent 行为 |
|---------|-----------|
| "审查前端代码" / "review this" / "前端 review" | → `scan --path <dir>` |
| "有没有 XSS" / "安全吗" / "查漏洞" | → `scan --path <dir> -d security --no-lint`（最快聚焦） |
| "依赖有漏洞吗" / "npm audit" | → `deps --path <dir>` |
| "React 有没有问题" / "组件安全" | → `scan --path <dir> -d security,reliability` |
| "规则有哪些" / "SEC-REACT 是啥" | → `rules` |
| "PR 能不能合" / "达不达标" | → `scan --path <dir> --threshold B` |

### 2.2 Triage→Verify 协议

每条 finding 带 `triage` 字段，决定 Agent 怎么处理：

| triage | 含义 | Agent 行为 |
|--------|------|-----------|
| `deterministic` | 静态可证（如 `eval(x)` 非字面量） | **直接报告**，无需确认 |
| `agent_verify` | 需 Agent 确认（如 postMessage 缺 origin 检查——规则看不到接收方） | **读相关代码验证**后再下结论，无法验证时标"待确认" |
| `agent_only` | 启发式提示（如 SEC-SECRET-004 变量名猜密钥，已抑制 mock/test 前缀） | 调查后可 dismissed |

### 2.3 输出处理

`json-compact` 的结构（见 references/reporting-and-fix.md 详解）：

```json
{
  "score": 83.0, "grade": "B",
  "issues": {"error": 4, "warning": 2, "info": 1},
  "files": 1,
  "dimensions": {"security": 55, "reliability": 94, "best-practice": 100, "arch": 100, "deps": 100},
  "findings": [{"id": "SEC-REACT-001", "sev": "error", "dim": "security", "file": "src/UserProfile.tsx", "line": 6, "conf": "high", "triage": "deterministic", "msg": "...", "fix": "..."}],
  "degradation_notices": ["eslint/tsc skipped (--no-lint)."],
  "triage": {"deterministic": 5, "agent_verify": 2, "agent_only": 0, "total": 7},
  "deps": {"packages": 2, "vulnerabilities": {"critical": 0, "high": 0, "moderate": 0, "low": 0, "info": 0, "total": 0}, "npm_available": true}
}
```

---

## §3. 评分解读

5 维度加权（权重见 references/scoring-and-thresholds.md）：

| 维度 | 权重 | 说明 |
|------|------|------|
| security | 35% | 自研 SEC-* 规则（XSS/eval/open-redirect/secrets） |
| reliability | 20% | RELI-* 规则（异步未捕获、事件泄漏） |
| best-practice | 20% | eslint 折叠 + tsc 类型错误 |
| deps | 15% | npm audit CVE |
| arch | 10% | （预留，本版本无规则） |

每个 error 扣 10 分、warning 扣 5 分、info 扣 1 分（按维度独立计）。等级：A≥90 / B≥80 / C≥70 / D≥60 / F<60。

---

## §4. 报告生成模板

最终回复采用四段式格式（参照 dotnet-code-review）：

```
Findings
- [error] src/X.tsx:6 - SEC-REACT-001 - dangerouslySetInnerHTML with non-literal __html
  证据: dangerouslySetInnerHTML={{__html: bio}}
  ⚠️ triage=agent_verify 的项需读代码确认后再下结论

Fix Suggestions
- [SEC-REACT-001] src/X.tsx:6
  用 DOMPurify.sanitize() 净化，或避免 dangerouslySetInnerHTML。
  ⚠️ AI 生成建议，应用前请人工验证。

Degradation（本次未检查的维度）
- eslint/tsc skipped (--no-lint) → best-practice 维度结论不可信
- npm not found → deps 维度结论不可信

Summary
- Score: 83.0/100 (B)
- Severity: 4 error, 2 warning, 1 info
- Triage: 5 deterministic, 2 agent_verify
```

---

## §5. 边界处理 / 降级

`degradation_notices` 出现时，对应维度的结论**不可信**，必须明示：

| Notice | 含义 | 降级后可信的维度 |
|--------|------|-----------------|
| `eslint not found` | 未跑 lint | security / reliability（自研规则仍跑） |
| `tsc not found` | 未跑类型检查 | 同上 |
| `npm not found` | 未跑依赖 CVE | 除 deps 外都可信 |
| `eslint/tsc skipped (--no-lint)` | 用户主动跳过 | 同 eslint not found |
| `package.json not found` | 不是前端项目 | 全部维度（提示用户路径错误） |
| tree-sitter 未装 | 自动用正则模式 | 全部维度可信，但 `intentional-simple`：正则不跟踪数据流，跨行/复杂表达式可能漏报 |

**正则降级的已知限制**（`intentional-simple`）：
- 不跟踪跨行数据流，所以"参数是否来自用户输入"只能用"是否字面量"近似。
- 多行 JSX 表达式可能漏报。
- 升级路径：装 `tree-sitter` + `tree-sitter-javascript` + `tree-sitter-typescript`（见 requirements.txt）即自动启用精确 AST。

---

## §6. 故障排查

| 错误 | Agent 行为 |
|------|-----------|
| `degradation_notices` 含 "eslint/tsc not found" | **告知用户**：缺 Node/eslint，建议 `npm i -D eslint typescript`；自研规则仍可用（注意：这不影响 exit code，scan 仍可能返回 0/1） |
| `CONFIG_ERROR` (exit 3) | **追问用户**：检查命令参数 |
| `npm found on PATH but not executable` (Windows) | **告知用户**：用 npm.cmd 或重装 Node.js |
| scan 输出 0 findings 但项目明显有问题 | **检查 degradation_notices**：很可能 lint/deps 全跳过了 |
| fixture 测试失败 | 跑 `python -m pytest tests/ -v` 看详情 |

---

## §7. 参考文件索引

| 文件 | 何时看 |
|------|--------|
| `references/rules-catalog.md` | 看每条自研规则的完整描述 / CWE / 修复建议 |
| `references/scoring-and-thresholds.md` | 调 threshold、理解评分权重 |
| `references/reporting-and-fix.md` | 输出字段详解 + 报告模板规则 |
| `references/troubleshooting.md` | 错误处理决策表（扩展版） |
| `tests/README.md` | 测试运行方式 + 覆盖表 |
| `scripts/count_rules.py` | 维护：统计规则数，校验文档"13 条"声明不漂移 |
| `scripts/find_uncovered.py` | 维护：找没有测试引用的规则（防死规则回归） |

**加载原则**：SKILL.md 已包含 90% 场景的决策信息。references/ 仅在用户问具体规则细节、评分公式、或排障时按需读，**不要预读**。

---

## §8. 测试状态

```
105 passed in 2.5s
```

覆盖：自研规则正/负例、评分模型、triage 回填、4 种输出格式、linters 编排（mock）、端到端 CLI（fixtures/react-demo）。

运行：`python -m pytest tests/ -v`（在 frontend-audit/ 目录下）。
