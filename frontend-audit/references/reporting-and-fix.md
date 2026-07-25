# reporting-and-fix

> **职责契约**：本文档是 frontend-audit 输出格式与报告生成的**唯一权威源**。
> 只包含：json-compact 字段表、markdown 段落结构、报告四段式模板、修复建议规则。
> 不包含：规则细节（→ rules-catalog.md）、评分公式（→ scoring-and-thresholds.md）。
>
> Agent 使用路径：生成给用户的最终报告时读。
> 数据来源：`scripts/audit/output.py`。

## json-compact 字段表

| 字段 | 类型 | 含义 |
|------|------|------|
| `score` | float | 总分（0–100） |
| `grade` | str | A/B/C/D/F |
| `issues` | `{error,warning,info}` | 按严重度计数 |
| `files` | int | 扫描的文件数 |
| `dimensions` | `{security,reliability,best-practice,arch,deps}` | 各维度分 |
| `findings` | list | finding 列表（**硬上限 50 条**） |
| `findings[].id` | str | 规则 ID（如 `SEC-REACT-001`） |
| `findings[].sev` | str | error/warning/info |
| `findings[].dim` | str | 维度 |
| `findings[].file` | str | 相对路径 |
| `findings[].line` | int | 行号 |
| `findings[].conf` | str | high/medium/low（置信度） |
| `findings[].triage` | str | deterministic/agent_verify/agent_only |
| `findings[].msg` | str | 问题描述（截断到 120 字符） |
| `findings[].fix` | str | 修复提示（截断到 80 字符） |
| `degradation_notices` | list[str] | 本次未检查的维度（**必须转达给用户**） |
| `triage` | `{deterministic,agent_verify,agent_only,total}` | triage 统计 |
| `deps` | obj | npm audit 摘要（packages + vulnerabilities 计数） |

## finding 排序

按 `(severity_rank, file, line)` 升序：error 在前，同 severity 按文件名、行号。这样最严重的问题总是出现在列表前面。

## 报告四段式模板

给用户的最终回复用四段式（参照 dotnet-code-review）：

### 1. Findings（问题列表）
```
- [error] src/UserProfile.tsx:6 - SEC-REACT-001 - dangerouslySetInnerHTML with non-literal __html
  证据: dangerouslySetInnerHTML={{__html: bio}}
```
- 严重度用方括号前缀：`[error]` / `[warning]` / `[info]`
- 每条带 `文件:行号 - 规则ID - 描述`
- `triage=agent_verify` 的项在末尾标注"需读代码确认"

### 2. Fix Suggestions（修复建议）
```
- [SEC-REACT-001] src/UserProfile.tsx:6
  用 DOMPurify.sanitize() 净化，或避免 dangerouslySetInnerHTML。
  ⚠️ AI 生成建议，应用前请人工验证。
```
- 来源：finding 的 `fix` 字段（来自规则的 `fix_hint`）
- **必须**带 ⚠️ 提示，因为修复建议是 AI 生成的

### 3. Degradation（本次未检查的维度）
```
- eslint/tsc skipped (--no-lint) → best-practice 维度结论不可信
- npm not found → deps 维度结论不可信
```
- 直接从 `degradation_notices` 转写
- **不可省略**——这是诚信要求，不能让用户误以为是完整审查

### 4. Summary（总结）
```
- Score: 83.0/100 (B)
- Severity: 4 error, 2 warning, 1 info
- Triage: 5 deterministic, 2 agent_verify
- 建议优先修: SEC-REACT-001, SEC-JS-001（error 级 security 问题）
```

## 修复建议规则（生成 fix 时的纪律）

1. **优先用规则的 fix_hint**：finding 的 `fix` 字段已经是规则作者写的，直接用，不要自己编。
2. **不要超出规则范围**：SEC-REACT-001 的 fix 只讲 XSS 净化，不要顺手建议重构组件。
3. **密钥泄露特殊处理**：SEC-SECRET-* 的 fix 必须强调"**立即轮换**"，不只是"移到环境变量"。
4. **agent_verify 不给确定结论**：这些 finding 标"待确认"，不要写成"已确认漏洞"。

## markdown 输出

`--format markdown` 给人看，结构：概览 → 评分详情 → 降级提示 → 依赖安全 → Triage → 问题列表。**token 消耗大，仅在用户明确要给人看的报告时用**。
