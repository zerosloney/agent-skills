# 报告输出与修复建议

本文档说明 `dotnet-code-review` 的输出格式、生产级质量门禁、AI 修复建议生成规则、降级与容错策略。Agent 调用 CLI 后产出报告时按本文件执行。

## 输出格式

| 组合 | 效果 |
|------|------|
| `--format compact --output-mode summary` | 最小 ~50-100 token，仅分数+统计 |
| `--format sarif` | SARIF 2.1.0，上传 GitHub Code Scanning / Azure DevOps 在 PR 内联展示 findings |
| `--output-mode summary` | 摘要，无 issues 列表 |
| `--output-mode by-rule` | 按规则分组 |
| `--output-mode top --max-issues 10` | 仅最严重 N 条 |
| `--max-message-length 80` | 截断消息 |
| `--format compact` | 紧凑 JSON（score/grade/severity counts） |

### 可信度字段

JSON 输出中每条 `issues[]` 都必须包含可信度元数据，Agent 报告结论时优先使用这些字段，而不是凭规则 ID 猜测可信度：

```json
{
  "confidence": "high",
  "evidence_type": "roslyn_ast",
  "verification": {
    "checker": "csharp-ast-analyzer",
    "layer": "ast",
    "deterministic": true,
    "requires_build": false
  },
  "limitations": []
}
```

`confidence` 取值口径：

| 来源 | 默认可信度 | 证据类型 |
|------|------------|----------|
| `ast` / `semantic` / `project` / `build` | high | Roslyn / compiler diagnostic |
| `format` / `coverage` / `nuget` / `duplicate` / `doc` / `style` | medium | tool output / supplied report / deterministic text scan |
| `custom` | low | user-defined regex rule |

每次运行还会输出 `review_integrity`，用于判断整份报告能否支撑“已审查/无问题/无漏洞”等结论：

```json
{
  "dotnet_sdk_checked": true,
  "dotnet_sdk_version": "8.0.100",
  "layers_requested": ["ast", "semantic", "build"],
  "layers_executed": ["ast", "semantic"],
  "layers_skipped": [{"layer": "build", "reason": "no .csproj/.sln found"}],
  "cve_conclusion_valid": false,
  "coverage_conclusion_valid": false
}
```

Agent 规则：当 `layers_skipped` 非空时，必须在 Summary 或 Open Questions / Assumptions 中说明检测边界；当 `cve_conclusion_valid=false` 时，不得报告“无已知漏洞”；当 `coverage_conclusion_valid=false` 时，不得报告“覆盖率达标”。

### NetAnalyzers (CAxxxx) 注入状态

build 层对 modern .NET 项目默认透传 `/p:EnableNETAnalyzers=true /p:AnalysisLevel=latest-recommended`，让 .NET SDK 内置的官方分析器（约 500 条 CAxxxx 规则）参与本次审查。`review_integrity.netanalyzers` 字段记录注入结果：

```json
{
  "injected_for_projects": 2,
  "skipped_projects": [
    {"csproj": "Legacy.csproj", "reason": ".NET Framework requires manual PackageReference"}
  ],
  "disabled_by_user": false
}
```

Agent 报告规则：

- 当 `injected_for_projects == 0` 且 `disabled_by_user == false` 时，**必须**在 Open Questions / Assumptions 中说明"build 层未启用 NetAnalyzers，微软官方 CAxxxx 规则集（约 500 条）未参与本次检测"。这种情况发生在：项目是 .NET Framework（无 SDK 内置 analyzer）、或所有项目都在 csproj 显式关闭了分析器。
- 当 `skipped_projects` 非空时，**应该**逐项目说明跳过原因（项目级配置 vs 框架限制）。
- `disabled_by_user == true` 时，说明用户主动 `--skip-netanalyzers`，CAxxxx 未参与检测属于用户选择。
- CAxxxx 规则归一化到评分维度：globalization→best-practice、design→best-practice、usage→reliability、maintainability→code-smell、portability→best-practice（详见 `scoring.py::CATEGORY_NORMALIZATION`）。

## Exit Code

| 码 | 含义 |
|---|------|
| 0 | 通过或无问题 |
| 1 | error 级别问题，或分数低于 `--quality-gate-score` |
| 2 | 仅 warning |
| 3 | 配置错误 |
| 4 | 工具缺失 |
| 5 | 内部错误 |
| 6 | 用户输入错误 |
| 130 | 中断 |

## 生产级质量门禁

### 质量阈值建议

| 环境 | 质量门禁分数 | 失败级别 | 说明 |
|------|-------------|---------|------|
| **开发环境** | 70 | error | 基本质量检查 |
| **测试环境** | 80 | warning | 确保测试通过 |
| **预生产环境** | 85 | warning | 生产前最后检查 |
| **生产环境** | 90 | error | 最高质量标准 |

### 生产级审查组合

```bash
# 完整生产级审查（安全 + 质量 + 覆盖率 + CVE）
python scripts/review.py --target . \
  --quality-gate-score 85 \
  --fail-on warning \
  --cve-check \
  --coverage coverage.cobertura.xml \
  --coverage-threshold 0.8 \
  --format json \
  --output-mode detailed

# CI/CD 管道集成（紧凑输出）
python scripts/review.py --target . \
  --quality-gate-score 80 \
  --fail-on warning \
  --cve-check \
  --format compact \
  --output-mode summary

# PR 审查（增量 + 缓存）
python scripts/review.py --diff HEAD \
  --changed-only \
  --cache .review-cache \
  --quality-gate-score 80 \
  --fail-on warning \
  --cve-check
```

### 生产级审查决策树

```text
用户请求生产级审查？
├── 是 → 使用生产级质量门禁（85+ 分）
│   ├── 有覆盖率数据？→ 加 --coverage --coverage-threshold 0.8
│   ├── 需要 CVE 检查？→ 加 --cve-check --ensure-cve-db
│   ├── 是 PR 审查？→ 加 --diff HEAD --changed-only
│   └── 输出格式？→ --format json --output-mode detailed
└── 否 → 使用标准审查（70+ 分）
```

## 报告输出模板

最终回复采用 code-review 格式，先列 Findings，按 severity 从高到低排序，并引用文件和行号：

```text
Findings
- [error] path/to/File.cs:42 - <规则/问题名>
  <为什么这是问题；可能影响；必要时给出最小修复方向>
- [warning] path/to/Other.cs:18 - <规则/问题名>
  <说明>

Fix Suggestions
- [<规则ID>] path/to/File.cs:42
  上下文：
  ```csharp
  // +/- 3 行代码上下文
  ```
  ```diff
  - <原代码行>
  + <修复后代码>
  ```
  ⚠️ AI 生成，应用前请人工验证。

- [<规则ID>] path/to/Other.cs:18
  ...

Open Questions / Assumptions
- <目标框架、规则配置、CVE 数据库等不确定项>
- <review_integrity.layers_skipped 中的跳过层与原因>

Production Readiness Assessment
- Security Score: <安全分数/100>
- Performance Score: <性能分数/100>
- Maintainability Score: <可维护性分数/100>
- Test Coverage: <测试覆盖率百分比>
- CVE Status: <CVE 扫描状态>
- Evidence Boundary: <CVE/coverage 结论是否可信；哪些检测层跳过>
- Recommendation: <生产就绪建议：Ready/Conditional/Not Ready>

Summary
- Score/grade: <分数/等级>
- Scope: <diff/files/target/all>
- Command: <实际运行命令>
```

没有问题时明确写"未发现 error/warning 级别问题"，并说明仍然存在的检测边界（例如未启用语义分析、无 coverage、CVE 数据库离线）。

## AI 修复建议

审查结果返回后, Agent 应根据 issue 列表生成修复建议。**不是调用外部 LLM，而是当前模型基于结果 + 代码上下文直接生成**。

### 数据流

1. 运行 `python scripts/review.py --format json` 获取结果
2. 从 `result["issues"]` 取 top 15 条（按 severity 排序，error > warning > info）
3. 对每条 issue：
   a. 读取 `issue["file"]` 文件中 `issue["line"]` 的上下文（行号 ±3 行）
   b. 基于 `issue["message"]` + `issue["suggestion"]` + 代码上下文，生成具体修复 diff
4. 按模板格式输出

### 生成规则（强制）

| # | 规则 | 说明 |
|---|------|------|
| 1 | **只处理 error/warning** | info 级只列不修。严重度从 result.issues[].severity 判断 |
| 2 | **标记 AI 生成** | 每条建议必须附带 "⚠️ AI generated — verify before applying" |
| 3 | **安全类 (SEC) 额外警告** | 安全类修复生成后，须额外加一句 "Manual security review required" |
| 4 | **复杂修只给方向** | 涉及跨文件改动或需要重构的（如 CS006 god class），不生成完整 diff，只给 1-2 句重构思路，加 "Requires manual refactoring" |
| 5 | **Token 预算控制** | 大项目（issues > 30）最多生成 top 10 条 error + warning 的修复建议 |
| 6 | **零语义保证** | 生成的修复建议未经编译器验证，禁止声称"已通过编译"或"无风险" |
| 7 | **不可覆盖自动修复** | 当 `--fix` 已执行（`fix_result` 非空）时，对于已修复的 issue 跳过 AI 建议，避免重复 |
| 8 | **生产级修复优先级** | 安全类问题（SEC/SH）必须优先修复，其次是性能问题（P），最后是代码风格（S/N） |

### 建议（SHOULD）

- 修复 diff 优先展示最小修改：不要重排整个方法，只改问题行
- 如果从 issue 的 suggestion 字段已可明确推断修复方向（如 `"Use parameterized queries"`），优先按该方向生成
- 对高频重复规则（如同文件中出现 5 次 SEC001），只生成第一个和最后一个的完整 diff，中间的简要描述即可
- 对于生产级审查，建议提供修复后的代码示例，而不仅仅是修复方向

### 输出位置

Fix Suggestions 放在 Findings 之后、Open Questions 之前，形成完整报告四段式：

```
Findings
Fix Suggestions    ← 修复建议段
Open Questions / Assumptions
Production Readiness Assessment  ← 生产就绪评估段
Summary
```

## 降级与容错

| 场景 | 行为 |
|------|------|
| 无 .NET SDK（缺失或 < 6.0） | **CLI 硬阻断**（exit code 4 + TOOL_MISSING + 安装指引），不返回任何 issues |
| 无 csproj | 框架感知降级为 unknown，全部规则生效；Agent 应主动询问并用 `--target-framework` 覆盖 |
| `--target-framework` 显式传入 | 覆盖 csproj 自动检测结果 |
| 无 OCR | ocr-bridge 自动回退为纯 dotnet-code-review（也可 `--skip-ocr`） |
| 无 CVE 数据库 | `--cve-check` 返回 `db_present=false` 且带 `warning`；`vulnerabilities` 为空表示"未扫描"而非"安全"，禁止据此报无漏洞 |
| CVE 数据库过期 | `--cve-check` 返回 `db_present=true` 但 `db_age_days > 14`（或 `null`）且带 `warning`；"无漏洞"可能漏报近期漏洞，禁止据此时报可信 clean |
| 工具缺失 | 按 `--fail-on` 处理，不中断其他分析 |
| 覆盖率文件缺失 | 跳过覆盖率检查，不报错，但在 Summary 中说明 |
| 抑制文件 `.dotnet-review/suppress.json` 存在 | 匹配的 issue 从 score/输出移除，`suppressed_by_config` 字段记录抑制计数 |
| 增量语义分析（`--incremental-semantic`） | 复用未变文件的语法树；结果含 `semantic_cache_stats`（hit_rate/compilation_reused）供回归观测 |

## PR diff-aware 门禁（`--baseline-report`）

PR 审查的核心问题是"这次变更是让代码变好还是变坏"。`--baseline-report` 接收一份基线 JSON 报告（main 分支跑出的 `--format json` 输出），将当前 run 的问题分类为：

| 分类 | 定义 | 输出 |
|------|------|------|
| `introduced` | 当前有、基线无 | 独立列表 + `introduced_score` |
| `fixed` | 基线有、当前无 | 独立列表（不影响分数） |
| `unchanged_count` | 两边都有（含行号漂移容忍） | 仅计数 |
| `severity_changed` | 同位置但 severity 变化 | 列表（含 baseline→current severity） |

### 工作流

```bash
# 1. main 分支跑基线（CI 或本地）
python scripts/review.py --target . --format json --output baseline.json

# 2. PR 分支对比基线
python scripts/review.py --target . --format json \
    --baseline-report baseline.json \
    --fail-on-introduced error    # 仅新引入的 error 阻断 PR
```

### 匹配键与行号漂移

匹配基于 `(rule, normalize_review_path(file), line)` 三元组。**故意不含 message**（文案漂移不应影响匹配）。同 `(rule, file)` 且行号差异 ≤ 5 行视为同一问题漂移（`LINE_PROXIMITY=5`，见 `diff_baseline.py`）——PR 插入/删除几行会让后续问题的行号整体偏移，精确匹配会误报大量 introduced+fixed 对。

### 双分数

- `score`（顶层，不变）：全量问题的分数——保持现有 `--quality-gate-score` 门禁语义
- `introduced_score`（新增）：仅 introduced 子集的分数——PR 引入问题的净影响

两个门禁独立：`--quality-gate-score` 看全量，`--fail-on-introduced` 看增量。两者取最严（max）。

### 抑制交互

基线对比在 suppressions **之后**运行（`engine.py`）。语义：抑制 = 视同不存在。若某问题在基线存在、当前被抑制 → 计入 `fixed`。这是有意为之——保证"抑制从分数移除"的现有契约不变。

### 退出码

`--fail-on-introduced` 与 `--fail-on` 独立计算，取更严者：
- `--fail-on-introduced error`：introduced 含 error → exit 1
- `--fail-on-introduced warning`：introduced 含 warning+ → exit 2
- 无 `--baseline-report` 时，`--fail-on-introduced` 无效（无 introduced 数据）

## CI/CD 集成

```yaml
# GitHub Actions 示例
name: Code Review
on: [push, pull_request]
jobs:
  review:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3
      - name: Setup .NET
        uses: actions/setup-dotnet@v3
        with:
          dotnet-version: '8.0.x'
      - name: Setup Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'
      - name: Install dependencies
        run: pip install -e .
      - name: Run code review
        run: |
          python scripts/review.py --target . \
            --quality-gate-score 85 \
            --fail-on warning \
            --cve-check \
            --coverage coverage.cobertura.xml \
            --format json \
            --output-mode summary
```

## 生产环境部署检查清单

> ⚠️ 标注 **[工具]** 的项可由本技能产出结论；标注 **[人工]** 的项本工具无检测能力，Agent 不得在报告中给出通过/不通过结论，只能提示"需人工/运行时工具确认"。

- [工具] 安全审查通过（无 error 级别安全问题）
- [工具] CVE 扫描完成（无已知高危漏洞）
- [工具] 测试覆盖率达标（≥ 80%，需 `--coverage`）
- [工具] 性能审查通过（无严重性能问题）
- [工具] 代码质量达标（质量门禁分数 ≥ 85）
- [工具] 依赖项安全（无已知漏洞，CVE 扫描结果）
- [人工] 配置管理正确（敏感信息外部化）
- [人工] 日志记录完整（关键操作有日志，结构化日志）
- [人工] 监控指标齐全（关键业务指标，APM 工具确认）
- [人工] 分布式跟踪就绪（OpenTelemetry / APM）
- [人工] 回滚策略就绪（支持快速回滚）
