# Layer Capabilities（分层能力边界）

> 加载时机：判断某检测能力是否可达、判断某 issue 是否误报、判断 `--fix` 可修复清单、判断跨程序集/项目级分析能否生效。
> 数据来源：SKILL.md + `scripts/csharp-*-analyzer/` + `scripts/review/engine.py` + `auto_fix.py` + `run_review()` 内联代码。

## 一、分层总览

| Layer | 引擎 | 说明 | 依赖 |
|-------|------|------|------|
| **3 AST** | Roslyn `CSharpSyntaxWalker` | **高**（忽略注释/字符串，语法结构级） | .NET SDK ≥ 6.0 |
| **3b 语义** | Roslyn `SemanticModel` | **高**（类型/符号级） | .NET SDK ≥ 6.0 |
| **3c 项目级** | Roslyn 跨文件分析器 | 高（依赖循环 / god class / 孤儿类型） | .NET SDK ≥ 6.0 |
| **4 编译** | `dotnet build`（CS/CA 诊断 + NetAnalyzers） | 编译器级 | .NET SDK + csproj |
| **5 格式** | `dotnet format --verify-no-changes` | IDE 代码风格 | .NET SDK + csproj |
| **内联** | `run_review()` 内联（S001/S002/S005/P021） | 纯文本，零依赖 | 无 |
| **其他** | 重复代码 / XML 文档 / 自定义规则 | 零依赖 | 无 |

## 二、SDK 缺失行为（硬门禁，不可绕过）

- `dotnet --version` 失败 / < 6.0 → CLI 抛 `ToolMissingError`
- **exit code = 4**，`code = TOOL_MISSING`
- 输出 JSON 错误到 stderr（含 `install_url` / `recommended`）
- **不返回任何 issues**——禁止软降级
- 理由：返回「0 issues」会误导用户以为已过 Roslyn 审查

## 三、各层能力边界（误报/漏报判断）

### Layer 3（AST）
- 使用 Roslyn `CSharpSyntaxWalker`，忽略注释/字符串，语法结构级
- 合法业务场景（如 `==` 比较 string）仍可能误报
- ⚠️ 跨程序集符号解析受限于 `AdhocWorkspace`（无 MSBuild 全解决方案上下文）——项目内解析可靠

### Layer 3b（语义）
- `SemanticModel` 用于类型/符号解析，消除语法级 false positive（如 `var x = GetSomething()` 的类型推断）

### Layer 3c（项目级）
- **语义级依赖图**：基于 `SemanticModel` 类型解析，消除 `using` 导入导致的误报
- **God Class 检测**：基于 `ClassDeclarationSyntax.Members` 精确计数
- **孤儿类型检测**：识别定义后无任何引用的类型（潜在死代码）
- **循环依赖**：Tarjan SCC 算法，输出参与循环的文件列表
- **架构违反**：跨层依赖（LAYER001）+ SAP 失衡（ARCH002）

### Layer 4/5（编译/格式）—— 需 csproj
- 无 `.csproj`/`.sln` → Layer 4/5 跳过，不报错
- **NetAnalyzers（CAxxxx）注入**：build 层对 modern .NET（net6.0+）项目自动透传 `/p:EnableNETAnalyzers=true /p:AnalysisLevel=latest-recommended`，让 .NET SDK 内置的官方分析器（约 500 条 CAxxxx 规则）参与检测。**无需项目引用 PackageReference，不动用户 csproj**。legacy（.NET Framework）项目跳过（需 PackageReference，本次不支持）；csproj 中显式 `<EnableNETAnalyzers>false</EnableNETAnalyzers>` / `<AnalysisLevel>none</AnalysisLevel>` / `<AnalysisMode>None</AnalysisMode>` 的项目跳过（尊重项目配置——MSBuild 属性优先级规则下 `/p:` 会被覆盖，强行注入是无声 no-op）。注入结果记录在 `review_integrity.netanalyzers`：`injected_for_projects` / `skipped_projects[].reason` / `disabled_by_user`。可用 `--skip-netanalyzers` 关闭。
- **Layer 5 IDE 规则映射**：`dotnet format` 输出的 IDE 诊断通过 `_FORMAT_RULE_CATEGORIES` / `_FORMAT_RULE_SUGGESTIONS` 映射到审查维度：
  - **style**：IDE0055（格式）、IDE0005（冗余 using）
  - **performance**：IDE0057（foreach 参数）、IDE0059（不必要的参数赋值）
  - **naming**：IDE0060（未用参数）、IDE1006（命名风格）
  - **reliability**：IDE0039（局部函数提取）、IDE0052（未读私有成员）
  - 未知 IDE 规则默认归入 **style**，附带修复建议文本

### Layer 0（Legacy Framework Mapping）
- `_map_legacy_framework` maps `netstandard2.0` / `netcoreapp3.1` → `net8.0` for Roslyn analysis.
- This is an **approximation** — not a true upgrade simulation.
- Legacy projects using .NET 8-only APIs may produce **false negatives** (analyzer does not flag APIs that are absent in the target framework).
- .NET Framework (`net4x`) is **excluded** from this mapping entirely. Projects targeting `net48` or lower are analyzed as-is, with no legacy-to-modern mapping applied.

## 四、`--fix` 可修复规则（`AUTO_FIXES`）

**9 条内置规则**，自定义规则**永不**进入：

| 规则 | 行为 | 风险 |
|------|------|------|
| S001 | `// TODO` → `// TODO():` | 低 |
| S002 | `// FIXME` → `// REVIEW:` | 低 |
| S003 | 删 `#region/#endregion` | 中 |
| S005 | 删注释代码 | 中 |
| BP010 | `NotImplementedException` → `NotSupportedException` | 低 |
| BP011 | `throw ex;` → `throw;` | 低 |
| P010 | `x == ""` → `string.IsNullOrEmpty(x)` | 低 |
| S006 | `new String(` → `new string(` | 低 |
| R021 | `throw new Exception()` → `InvalidOperationException` | 低 |

### 安全约束
- **自定义规则不修复**：`AUTO_FIXES` key 仅上述 6 条；`.dotnet-review/rules.json` 规则即使含 fixable 字段也被忽略（防注入）
- **CS002 故意排除**：删未用参数需全调用方上下文
- **备份**：每文件单份 `.bak`（TRUE 原始内容，非中间态），可整文件回滚
- **批量门禁**：单次改 > 20 文件应先 `--fix-dry-run` 确认（SKILL.md 强制约束）

## 五、增量语义缓存（`--incremental-semantic`）

- 缓存目录：`<project>/.review-cache/semantic/`（或 `--semantic-cache-dir` 指定）
- 策略：按文件内容哈希增量，未变化文件复用 Compilation 对象
- 有效期：**24 小时**，过期自动重编译
- 首次运行仍全量编译

## 六、CVE 检查能力边界

- **离线数据库**：`scripts/review/cve-db/nuget-cve.json.gz`，由 `refresh_cve_db.py` 生成（gzip 压缩）
- **覆盖范围**：OSV NuGet 全量导出。affected 条目里**同时支持**显式 `versions` 列表与 `ECOSYSTEM` ranges（`introduced`/`fixed`）。ranges-only 的 advisory（如 `Microsoft.NetCore.App.Runtime.*`）通过 NuGet FlatContainer API 拉取全版本后按区间展开，避免静默漏报；FlatContainer 不可达时优雅降级（该包不展开，不阻塞 DB 构建）
- `db_present=false` → **未扫描**，非「安全」；禁止据此报无漏洞
- `--ensure-cve-db`：缺失时从 OSV.dev 下载（需联网）；失败仍 `db_present=false` + warning
- 数据源：OSV.dev（生成时点快照），**非实时**——新 CVE 可能未收录

## 七、API 兼容性（`--api-compat`）

- 需 `--diff`
- 检测 public API 破坏性变更（签名移除/变更）
- 依赖 git diff 获取前后版本

## 八、常见误报/漏报排查

| 现象 | 可能原因 | 处置 |
|------|---------|------|
| AST 未报某问题 | 跨程序集符号 / `AdhocWorkspace` 限制 | 标注能力边界，不强行下结论 |
| 合法业务代码被报 | AST 层上下文误报（如 `==` 比较 string） | 读源码上下文，按 `triage` 值判断 |
| CVE 报「无漏洞」但 `db_present=false` | 未实际扫描 | 必须声明未扫描 |
| .NET Framework 项目误报 ConfigureAwait | 框架误判 | 用 `--target-framework netframework-v4.8` 覆盖 |
