---
name: dotnet-code-review
version: 0.4.1
description: |
  C#/.NET 代码审查，基于 Roslyn（AST + Semantic + Project）+ dotnet build/format + 离线 CVE 库。
  6 维度覆盖：安全（OWASP Top 10 / CWE 映射）、性能、可靠性、最佳实践、架构、测试。
  175 条自研规则（AST 153 + 语义 22）+ NetAnalyzers CAxxxx（~500 条）动态注入。
  两阶段 Triage→Verify 协议 + Agent 误报反馈闭环（.dotnet-review/agent-verdicts.json）+
  SARIF 输出（GitHub Code Scanning）+ 自动修复（9 条规则）。
  Agent 通过 subprocess 调用 scripts/review.py，用户不接触 CLI。
  触发：用户说"审查 C# 代码" / "代码 review" / "安全扫描" / "生产就绪检查" / "NuGet 包安全" 时。
agent_created: true
---

# .NET Code Review — Agent 指令集

## 核心原则

1. **用户看不到 CLI。** 用户用自然语言提审查需求，你在后台调 `review.py`，只返回结果报告。
2. **先跑 CLI 再报告。** 不要凭 SKILL.md 的规则文档手动审查代码——规则文档是参考，实际 findings 来自 Roslyn 分析器。
3. **格式优先 `--format compact --output-mode top --max-issues 10`**。先拿紧凑结果确认分数，需要细节时再补 `--format json`。
4. **读取 review_integrity。** 每次运行检查 `layers_skipped` / `cve_conclusion_valid` / `coverage_conclusion_valid`，在报告中说明边界。
5. **修复建议基于 CLI 结果 + 代码上下文生成。** 不是调用外部 LLM，而是当前模型基于 issue 列表 + 源码 ±3 行直接生成 diff。

脚本路径：`skill://dotnet-code-review/scripts/review.py`

---

## 0. 前置条件

### 0.1 .NET SDK 门禁

CLI 要求 .NET SDK ≥ 6.0。调用前先检查：

```bash
dotnet --version
```

- 失败 / < 6.0 → CLI 抛 `ToolMissingError`（exit 4），不返回任何 issues
- 告知用户安装 .NET SDK 6+（推荐 8.0 LTS）：https://dotnet.microsoft.com/download

### 0.2 C# 分析器预编译

三个 Roslyn 分析器已预编译（DLL 就绪），无需额外步骤：
- `scripts/csharp-ast-analyzer/` — AST 语法树级检测
- `scripts/csharp-semantic-analyzer/` — 语义模型级检测
- `scripts/csharp-project-analyzer/` — 跨文件项目级检测

---

## 1. 命令速查

### 1.1 场景速查表

| 用户意图 | 命令 | 说明 |
|---------|------|------|
| 审查整个项目 | `--target <目录> --format compact --output-mode top --max-issues 10` | 自动扫描全部 .cs，快速出分 |
| 审查指定文件 | `--files <path1.cs> [path2.cs ...] --format compact --output-mode top` | 指定文件，不扫描目录 |
| 审查 PR 变更 | `--diff HEAD --changed-only --format compact --output-mode top` | 仅报告变更行上的问题 |
| 审查并对比基线 | `--target . --baseline-report baseline.json --fail-on-introduced error --format json` | 先跑基线，再对比增量 |
| 完整生产级审查 | `--target . --quality-gate-score 85 --fail-on warning --cve-check --format json` | 安全 + 质量 + CVE |
| 只看摘要 | `--target . --format compact --output-mode summary` | 仅分数+统计，~50-100 token |
| 只看问题列表 | `--target . --format json --output-mode by-rule` | 按规则分组，跳过详细信息 |
| 预览文件列表 | `--target . --preview` | 列出将扫描的文件，不执行审查 |
| 输出 SARIF | `--target . --format sarif` | 用于 GitHub Code Scanning / Azure DevOps |
| 自动修复 | `--target . --fix-dry-run`（预览） / `--fix`（执行） | 9 条内置规则可自动修复 |
| 覆盖率检查 | `--coverage coverage.cobertura.xml --coverage-threshold 0.8` | 读 Cobertura 报告检查覆盖率 |
| 人工审查清单 | `--checklist` | 输出工具无法静态检测的维度清单 |

### 1.2 Token 节约模式 / 输出格式选择

| 场景 | 命令组合 | token | 理由 |
|------|---------|-------|------|
| 快速评分/摘要 | `--format compact --output-mode summary` | ~50-100 | 最小 token，仅分数+统计 |
| 看最严重问题 | `--format compact --output-mode top --max-issues 10` | ~200-500 | 首次审查，先看 top 10 |
| 按规则分组 | `--format json --output-mode by-rule` | ~500-2000 | 省去重复 issue 详情 |
| 全部 issue 详情 | `--format json`（默认） | ~2000-10000 | 完整结构化数据，生成修复建议 |
| 上传 Code Scanning | `--format sarif` | — | GitHub/Azure DevOps 原生格式 |
| 截断消息长度 | `--max-message-length 80`（追加） | 追加节省 | 控制单条消息大小 |

### 1.3 质量门禁

| 参数 | 作用 |
|------|------|
| `--quality-gate-score <N>` | 总分 < N 时 exit 1。推荐：开发 70、测试 80、预生产 85、生产 90 |
| `--fail-on {error\|warning\|info\|none}` | 存在该级别及以上 issue 时 exit 非零（默认 error） |
| `--fail-on-introduced {error\|warning\|none}` | 仅 PR 新引入的问题触发（需 `--baseline-report`） |

### 1.4 Exit Code

| 码 | 含义 |
|----|------|
| 0 | 通过或无问题 |
| 1 | error 级别问题，或分数低于 `--quality-gate-score` |
| 2 | 仅 warning |
| 3 | 配置错误 |
| 4 | 工具缺失（.NET SDK） |
| 5 | 内部错误 |
| 6 | 用户输入错误 |
| 130 | 中断 |

---

## 2. Agent 决策规则

### 2.1 意图映射

| 用户输入 | Agent 行为 |
|---------|-----------|
| "审查这个项目 / 这个代码" | → `--target <项目目录> --format compact --output-mode top --max-issues 10` |
| "审查这个项目"（多 project 仓库）| 先 `--target . --preview` 列出 project，用户选一个后再 `--target <project_dir>` |
| "审查这几个文件" | → `--files <file1.cs> <file2.cs> --format compact --output-mode top` |
| "审查 PR / 变更" | → `--diff HEAD --changed-only --format compact --output-mode top` |
| "代码质量 / 质量评分" | → `--target . --format compact --output-mode summary` |
| "安全检查 / 安全漏洞" | → `--target . --format json --cve-check --quality-gate-score 85` |
| "生产就绪审查" | → `--target . --quality-gate-score 85 --fail-on warning --cve-check --format json --output-mode top --max-issues 20` |
| "帮我修复代码问题" | → `--target . --fix-dry-run --format json`（先预览），用户确认后 `--fix` |
| "和之前对比" | → 先跑基线 `--target . --format json > baseline.json`，再 `--baseline-report baseline.json --fail-on-introduced error --format json` |
| "NuGet 包安全" | → `--target . --cve-check --format json --output-mode summary` |
| "覆盖率" | → 需用户提供 `coverage.cobertura.xml` 路径，再加 `--coverage <path> --coverage-threshold 0.8` |
| "有什么审查不了的" | → `--checklist` |

### 2.2 两阶段审查协议（Triage → Verify）

工具对每条 issue 标注 triage 字段，Agent 据此决定是否需要深度分析：

| triage 值 | 含义 | Agent 行为 |
|-----------|------|------------|
| deterministic | Roslyn/编译器已确认，误报率极低 | **直接报告**，无需额外验证 |
| agent_verify | 高置信候选但需上下文判断 | **读取源码上下文**，按 verification_hints 判断 |
| agent_only | 工具无法静态检测 | Agent 自行分析（如业务逻辑合理性） |

#### Phase 1: Triage（~100-300 token）

```bash
review.py --target . --format compact --output-mode summary
```

输出包含 triage_summary：
```json
{
  "score": 85, "grade": "B",
  "issues": {"error": 2, "warning": 5, "info": 8},
  "triage": {"deterministic": 10, "agent_verify": 5, "agent_only": 0, "total": 15}
}
```

**Agent 决策**：
- agent_verify == 0 → 直接出报告（所有问题已确认），结束
- agent_verify > 0 → 进入 Phase 2

#### Phase 2: Deep Analysis（按需，~500-2000 token）

```bash
review.py --target . --format json --output-mode top --max-issues 10 --context-bundles
```

- --context-bundles：为 agent_verify 类 issue 自动附带代码上下文（±5 行 + 所在方法/类名）
- 每条 agent_verify issue 附带 verification_hints，告诉 Agent 需要检查什么
- Agent 逐条分析，判断 true positive / false positive

#### Phase 3: Fix Suggestions（仅 error/warning）

修复建议规则详见 **§ 4.1**。核心约束：只修 error/warning、标 AI 生成、安全类加人工复核。

### 2.3 Agent 判定反馈闭环

Agent 确认某条 issue 为误报后，可写入 .dotnet-review/agent-verdicts.json：

```json
{
  "verdicts": [
    {
      "rule": "LEGACY_BP021_task_run_server",
      "file_pattern": "**/BackgroundJobs/**",
      "verdict": "false_positive",
      "reason": "Background job service, Task.Run is appropriate"
    }
  ]
}
```

后续审查自动抑制匹配的 issue，从分数中移除。suppressed_by_verdict 字段记录抑制数量。

### 2.4 审查流程

```
1. 确定审查范围（项目/文件/PR）
2. Phase 1: review.py --format compact --output-mode summary
3. 读取 triage_summary，判断是否需要 Phase 2
4. Phase 2（如需）: review.py --format json --context-bundles
5. 对 agent_verify 类 issue，按 verification_hints 读源码判断
6. 读取 review_integrity 确认检测边界
7. 生成修复建议 diff（仅 error/warning）
8. 输出四段式报告
```


### 2.5 输出格式选择

输出格式选择见 §1.2 Token 节约模式表（已合并场景/命令/token/理由四列）。

---

## 3. 输出处理

### 3.1 JSON 输出结构

```json
{
  "project_root": "E:/Git/CRSBackend",
  "framework_version": "net8.0",
  "framework_type": "modern",
  "files_scanned": 42,
  "total_issues": 15,
  "score": { "overall": 85.0, "grade": "B", "security": 90, "best_practice": 80, ... },
  "by_severity": { "error": 2, "warning": 5, "info": 8 },
  "technical_debt_minutes": 120,
  "cognitive_complexity": 45,
  "maintainability_index": 72.5,
  "issues": [
    {
      "file": "src/Services/OrderService.cs",
      "line": 42,
      "severity": "error",
      "category": "security",
      "rule": "SEC001",
      "message": "SQL injection: use parameterized query",
      "suggestion": "Use SqlParameter instead of string concatenation",
      "source": "ast",
      "confidence": "high",
      "evidence_type": "roslyn_ast",
      "triage": "deterministic",
      "verification_hints": []
    }
  ],
  "review_integrity": {
    "layers_executed": ["ast", "semantic", "build"],
    "layers_skipped": [],
    "cve_conclusion_valid": false,
    "coverage_conclusion_valid": false,
    "netanalyzers": {
      "injected_for_projects": 1,
      "skipped_projects": [],
      "disabled_by_user": false
    }
  }
}
```

### 3.2 Triage 与可信度解读

**Triage 分类**（每条 issue 的 triage 字段）：
- deterministic — Roslyn 语法树/编译器已确认，Agent 直接报告
- agent_verify — 高置信候选但需上下文判断，附带 verification_hints
- agent_only — 工具无法静态检测

**可信度**（每条 issue 的 confidence 字段）：

| 来源 | 默认可信度 | 说明 |
|------|-----------|------|
| `ast` / `semantic` / `project` / `build` | high | Roslyn 语法树/编译器诊断，零误报 |
| `format` / `coverage` / `nuget` / `duplicate` / `doc` | medium | 工具输出或确定性文本扫描 |
| `custom` | low | 用户自定义正则规则 |

### 3.3 评分解读

总分 = Σ(各类别分数 × 权重)，0-100。

| 等级 | 分数 | 含义 |
|------|------|------|
| A | ≥ 90 | 优秀，可生产就绪 |
| B | ≥ 80 | 良好，少量警告 |
| C | ≥ 70 | 及格，需关注 |
| D | ≥ 60 | 差，需改进 |
| F | < 60 | 不合格，必须修复 |

| 类别 | 权重 | 每条 error 扣分 |
|------|------|----------------|
| security | 20% | 10 |
| best-practice | 20% | 10 |
| semantic | 10% | 10 |
| complexity | 10% | 10 |
| code-smell | 10% | 10 |
| style | 5% | 10 |
| test | 5% | 10 |
| performance | 5% | 10 |
| naming | 5% | 10 |
| reliability | 5% | 10 |
| security-hotspot | 5% | 10 |

---

## 4. 报告生成模板

最终回复采用四段式格式：

```text
Findings
- [error] path/to/File.cs:42 - SEC001 - SQL injection
  SQL 注入风险：使用字符串拼接构造 SQL 查询，攻击者可通过输入注入恶意 SQL。
  修复方向：使用参数化查询（SqlParameter）。

- [warning] path/to/Other.cs:18 - DI1001 - 构造函数参数过多
  5 个参数，超过推荐的 4 个上限。考虑拆分职责。

Fix Suggestions
- [SEC001] path/to/File.cs:42
  上下文：
  ```csharp
  var sql = "SELECT * FROM Users WHERE Name = '" + input + "'";
  var cmd = new SqlCommand(sql, conn);
  ```
  ```diff
  - var sql = "SELECT * FROM Users WHERE Name = '" + input + "'";
  - var cmd = new SqlCommand(sql, conn);
  + var cmd = new SqlCommand("SELECT * FROM Users WHERE Name = @name", conn);
  + cmd.Parameters.AddWithValue("@name", input);
  ```
  ⚠️ AI 生成，应用前请人工验证。

Open Questions / Assumptions
- 目标框架：net8.0（自动检测）
- build 层已执行，NetAnalyzers 已注入（约 500 条 CAxxxx 规则参与检测）
- CVE 检查未启用（无 --cve-check），不报告"无漏洞"
- 覆盖率数据未提供

Summary
- Score: 85.0/100 (B)
- Severity: 2 error, 5 warning, 8 info
- Technical Debt: ~120 分钟
- Scope: 42 files in E:/Git/CRSBackend
- Command: review.py --target E:/Git/CRSBackend --format json --quality-gate-score 80
```

### 4.1 修复建议生成规则

| # | 规则 | 说明 |
|---|------|------|
| 1 | **只处理 error/warning** | info 级只列不修 |
| 2 | **标记 AI 生成** | 每条建议附带 "⚠️ AI generated — verify before applying" |
| 3 | **安全类 (SEC) 额外警告** | 加 "Manual security review required" |
| 4 | **复杂修只给方向** | 跨文件/重构类，给 1-2 句思路，加 "Requires manual refactoring" |
| 5 | **Token 预算控制** | issues > 30 时最多生成 top 10 条 error + warning 的修复建议 |
| 6 | **零语义保证** | 禁止声称"已通过编译"或"无风险" |
| 7 | **不可覆盖自动修复** | `fix_result` 非空时，已修复的 issue 跳过 AI 建议 |
| 8 | **安全优先** | 安全类问题优先修复，其次性能，最后代码风格 |

---

## 5. 边界处理

### 5.1 review_integrity 检查清单

每次解析 JSON 结果后，必须检查 `review_integrity`：

```json
{
  "layers_executed": ["ast", "semantic"],
  "layers_skipped": [{"layer": "build", "reason": "no .csproj/.sln found"}],
  "cve_conclusion_valid": false,
  "coverage_conclusion_valid": false
}
```

| 条件 | Agent 行为 |
|------|-----------|
| `layers_skipped` 非空 | 在 Open Questions 中说明哪个层跳过及原因 |
| `cve_conclusion_valid == false` | **不得**报告"无已知漏洞" |
| `coverage_conclusion_valid == false` | **不得**报告"覆盖率达标" |
| `netanalyzers.injected_for_projects == 0` 且 `disabled_by_user == false` | 说明"CAxxxx 规则集（约 500 条）未参与检测" |
| `semantic_degraded == true` | 说明"语义分析层降级，SEM_* 规则不可靠" |

### 5.2 降级场景

| 场景 | 行为 |
|------|------|
| 无 .NET SDK | CLI 硬阻断（exit 4），告知用户安装 |
| 无 csproj | build/format 层跳过，Agent 应主动询问目标框架，用 `--target-framework` 覆盖 |
| 无 CVE 数据库 | `--cve-check` 返回 `db_present=false`，标记"未扫描"而非"安全" |
| 覆盖率文件缺失 | 跳过覆盖率检查，Summary 中说明 |
| 指定文件模式 (`--files`) | build/format 层自动跳过（无 csproj），这是 AST 级审查，非完整审查 |

### 5.3 没有问题时

当 `total_issues == 0` 或只有 info 级别问题时：

- 明确写"未发现 error/warning 级别问题"
- 说明检测边界（如未启用语义分析、无 coverage、CVE 数据库离线）
- 不要写"代码完美"——说明哪些层没跑

---

## 6. 故障排查

| 错误 | Agent 行为 |
|------|-----------|
| "ToolMissingError: .NET SDK ≥ 6.0 is required" | 告知用户安装 .NET SDK |
| 无 csproj 文件 | 用 `--target-framework` 手动指定框架 |
| `--cve-check` 返回 `db_present=false` | 标记未扫描，问用户是否要 `--ensure-cve-db` 联网下载 |
| build 失败 | 检查项目是否可编译，告知用户 |
| 扫描结果为空 | 确认目标目录有 .cs 文件 |
| 评分低于预期 | 按类别逐项分析，指出占比最高的扣分类别 |

---

## 7. references/ 索引

按需加载——Agent 在用户问到对应主题时才读这些文件。

| 主题 | 文件 | 何时加载 |
| --- | --- | --- |
| 规则总数真相 | `python scripts/count_rules.py` | 用户问"多少条规则"或评审成熟度 |
| 安全 / OWASP / CWE 映射 | `references/owasp-mapping.md` | 用户问 OWASP 覆盖度、SEC\*/SH\* 解释 |
| 6 维度规则矩阵 | `references/dimensions-coverage.md` | 解释某维度为何漏报 / 与 SonarLint 对比 |
| 层能力边界 | `references/layer-capabilities.md` | 用户问 AdhocWorkspace 限制 / AST 误报场景 |
| 性能规则 | `references/performance-rules.md` | 报告 P0xx 系列 / 解释热路径识别 |
| 修复模板 | `references/reporting-and-fix.md` | 生成 fix 段落时 |
| 评分口径 | `references/scoring-and-thresholds.md` | 解释 grade 边界、扣分公式 |
| BP 目录 | `references/best-practices-catalog.md` | 报告 BP\* 系列 |
| 规则目录 | `references/rules-catalog.md` | 查任意 ID 含义 |
| 设计取舍 | `references/skill-authoring.md` | 维护者 / 评审者 |

---

## 8. 测试状态

`tests/test_dimensions_coverage.py` / `tests/test_owasp_mapping.py` / `tests/test_count_rules.py` 三个 audit 测试持续断言本文件 + references/\*.md 不与活的分析层 drift。

最近一次全套结果：**10 passed / 0 failed**（2026-07-17）。详见 `changelogs/`。

---

*基于 Microsoft 官方编码约定 + SonarQube C# 规则集 + 社区最佳实践整理*
*适用于 .NET Framework 4.7.2+ 和 .NET Core 3.1+*
*CLI 工具：scripts/review.py（基于 Roslyn 分析引擎）*