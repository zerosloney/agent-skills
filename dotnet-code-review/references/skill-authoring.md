# SKILL 编写注记

本文件记录 `dotnet-code-review` 技能的设计取舍，供后续维护者参考。普通使用者无需阅读——SKILL.md 已包含全部调用所需信息。

## 设计原则

1. **SKILL.md 是轻量入口**：每次技能激活都会被模型完整读入。SKILL.md 应只包含"调用前必须知道的事"——环境门禁、调用入口、强制约束、安全边界。深度知识放 `references/`，按需加载。
2. **能做与不能做显式分离**：在 SKILL.md 列出工具**完全无检测能力**的维度，并要求 Agent **不得**对其给出通过/不通过结论。这是本技能区别于多数"代码审查 agent"的核心姿态。
3. **执行口径 vs 目录口径分离**：`scripts/review/rules.py` 中的 `AUTO_FIXES` 等是"自动修复映射"口径，**不是**实际执行规则数。实际执行规则数以 `python scripts/count_rules.py` 为准；当前快照为 175 条（AST 153 + 语义 22，另含项目级 + dotnet build/format 诊断）。

## 检测维度

### 有效维度（工具可产结论，共 6 类）

- **安全**：输入验证、输出编码、认证授权、敏感数据、依赖安全（CVE）、OWASP 映射。详见 `references/owasp-mapping.md`。
- **性能**：内存、异步、集合效率、反射/LINQ 成本、字符串、资源管理。详见 `references/performance-rules.md`。
- **可靠性**：异常处理（空 catch / throw ex / catch Exception）、并发原语（嵌套锁 / lock(this|typeof|string)）、任务异常丢失、空引用。
- **最佳实践**：SOLID 违反、设计模式误用、异步/并发/资源管理反模式、错误处理、依赖注入、IDE 格式诊断（dotnet format IDE 规则映射）。
- **架构**：跨层依赖违反、循环依赖、孤儿类型、架构违反（依赖倒置、层间隔离）、稳定抽象原则（SAP）、God Class 检测、模块边界。详见 `references/dimensions-coverage.md` § 五。
- **测试与质量**：单元测试覆盖（Cobertura）、空测试/无断言、可测性（`DateTime.Now`/静态 IO）、Mock 友好。

### 人工补充维度（工具无检测能力）

以下维度**完全无静态检测能力**，Agent **不得**在审查报告中对其给出通过/不通过结论。需人工 review 配合运行时 APM/运维工具确认。`python scripts/review.py --checklist` 可打印人工审查清单。

- **可观测性与监控**：结构化日志、指标收集、分布式跟踪、健康检查。
  → 需 Application Insights / OpenTelemetry / Serilog 等运行时工具确认。
- **部署与运维**：配置外部化、数据库迁移版本化、回滚策略、特性开关。
  → 需 CI/CD pipeline + 部署配置 + 运维流程人工确认。
- **日志脱敏**：LOG001 仅在代码层检测日志调用中疑似敏感命名的参数，**无法保证运行时不泄漏**，仍需人工 + 运行时日志采样确认。
- **传输/会话配置**：HTTPS 强制、TLS 1.2+、HSTS、Cookie Secure/HttpOnly/SameSite 属运行时配置，本工具仅能在代码层提示，实际生效需 IIS/Kestrel/反向代理配置确认。

## 安全类规则审查重点

- **关键 sink 覆盖度**：所有 SQL/命令/路径/LDAP/XPath/反序列化/XML 入口都有规则
- **加密合规**：禁用 MD5/SHA1/DES/RC4，使用 SHA-256+/AES-GCM
- **凭证管理**：禁止硬编码，强制使用 Secret Manager（Azure Key Vault / AWS Secrets Manager）
- **传输安全**：强制 HTTPS、TLS 1.2+、HSTS
- **会话安全**：Cookie Secure/HttpOnly/SameSite 必须显式设置
- **日志脱敏**：禁止记录密码、Token、信用卡号（LOG001 检测日志调用中疑似敏感命名的参数，运行时是否真正泄漏仍需人工确认）
- **企业 ORM SQL 拼接**：自研 ORM 的 `SelectData`/`ExecuteSql`/`SqlQuery` 方法使用字符串拼接/插值 → **LEGACY_SQL_Concat_In_Method (error)**
- **硬编码连接字符串**：源码中包含 `Data Source=...;Password=...` 或 `Server=...;User ID=...` 格式的凭据 → **LEGACY_Hardcoded_Connection_String (error)**

## 性能类审查重点

- **热路径识别**：用 dotnet-trace / PerfView 标记后再看 P0xx 报告
- **装箱检测**：值类型进入 object/ArrayList（P005 = error）
- **死锁风险**：.Result / .Wait() 必报（BP007 = error）
- **资源泄漏**：IDisposable 必须 using/await using（SEM004 = error）
- **异步完整链路**：从 controller 到 DB 全程 await，禁止 async void 业务方法

## 架构类审查重点

- **god class 检测**：方法/属性/字段数超阈值触发（项目级分析器，基于 `ClassDeclarationSyntax.Members` 精确计数）
- **循环依赖**：Tarjan SCC 算法检测跨文件/类型循环引用（项目级分析器，物化为 ARCH001）
- **孤儿类型**：识别定义后无任何引用的类型（潜在死代码，LAYER002）
- **稳定抽象原则（SAP）**：计算抽象度 + 不稳定性，标识"稳定抽象"类型（abstractness > 0.5 & instability < 0.5）
- **跨层依赖**：目录分层约定的跨层访问检查（LAYER001）
- **架构违反**：God Class 跨层、过度耦合等（ARCH002）
- **接口隔离**：避免大接口拆小（BP016 ISP）
- **SOLID 5 原则**：BP013/BP014/BP016/BP017/BP018/BP019 启发式支持（BP015 open-closed / BP020 prefer-interface 已删除：无可靠静态信号）
- **全局可变状态**：`public static` 可变字段在非配置类中 → **LEGACY_Global_Mutable_State (warning)**
- **WinForms 反模式**：`Application.DoEvents()` 重入风险 → **LEGACY_WinForms_DoEvents (warning)**；`Control.Invoke` 同步跨线程 → **LEGACY_WinForms_Invoke (info)**

## 6 维度覆盖度证明

本工具在 6 维度上提供分层规则覆盖。实际 C# 审查结论来自 **Roslyn（AST/语义/项目级）+ dotnet build/format**；规则数量以 `python scripts/count_rules.py` 为准，当前快照为 **175 条**（AST 153 + 语义 22）。

| 维度 | 当前执行层 | 详细映射 |
|------|------------|----------|
| 安全 (Security) | Roslyn AST/语义 + CVE | `references/dimensions-coverage.md` § 四 + `owasp-mapping.md` |
| 性能 (Performance) | Roslyn AST/语义 + build/format | `references/dimensions-coverage.md` § 一 |
| 可靠性 (Reliability) | Roslyn AST/语义 | `references/dimensions-coverage.md` § 五 |
| 最佳实践 (Best Practices) | Roslyn AST/语义 + build/format | `references/dimensions-coverage.md` § 五 |
| 架构 (Architecture) | Roslyn 项目级 + 语义 | `references/dimensions-coverage.md` § 六 + `layer-capabilities.md` |
| 测试与质量 (Testability) | Roslyn AST/语义 | `references/dimensions-coverage.md` § 三 |

## 诚实声明

- 跨程序集 API 分析受 AdhocWorkspace 限制（无 MSBuild 全解决方案上下文）
- 运行时行为不可模拟（无 IAST 能力）
- 安全日志（A09）维度无规则（建议配合 SIEM 工具）
- AST/语义层并非零误报：规则基于语法/符号启发式，在合法业务场景（如 `==` 比较 string、缺 `StringComparison`、`new HttpClient()`）仍可能误报，需结合上下文判读
- **孤儿类型检测**：单文件项目中的类型若未被同项目其他文件引用即标记为孤儿——对单文件项目/脚本可能误报（确实只有单一入口类型），需人工判读
- **架构违反检测**：目录分层约定硬编码（如 `Controllers/` 不应直接依赖 `Data/`），不同项目架构约定不同，LAYER001/ARCH002 提示需结合项目实际分层结构确认
- 详细 CWE 映射见 `references/owasp-mapping.md`

## 关键能力边界（AdhocWorkspace）

- 跨程序集符号解析（如"调用了已废弃的外部 API"）受限于 `AdhocWorkspace`（无 MSBuild 全解决方案上下文）
- 这是当前能力上限，非 bug

## 分析架构（分层）

| Layer | 引擎 | 说明 |
|-------|------|------|
| **3 AST** | **Roslyn** `CSharpSyntaxWalker`（`csharp-ast-analyzer`） | 语法树级，`LEGACY_*` 规则，153 条，忽略注释/字符串 |
| **3b 语义** | **Roslyn** `SemanticModel`（`csharp-semantic-analyzer`） | 类型/符号级，`SEM_*`/`EF*`/`ASP*`/`P*`/`RCS*` 规则，22 条（8 SEM + 5 EF + 3 ASP + 1 P + 5 RCS） |
| **3c 项目级** | **Roslyn** 跨文件（`csharp-project-analyzer`） | 依赖循环 / 跨层违规 / god class |
| **4 编译** | `dotnet build` | CSxxxx 诊断 + NetAnalyzers CAxxxx（~500 条） |
| **5 格式** | `dotnet format` | IDE00xx 代码风格 |
| **Style hint** | `run_review()` 内联 | S001/S002/S005/P021 |
| **其他** | 重复代码 / XML 文档 / 自定义规则 | 零依赖 |

**判读要点**：

- Layer 3/3b/3c 基于 **Roslyn** 语法树/语义模型，精度高于正则。注意：这是手写的 CSharpSyntaxWalker 分析器，**并非 SonarLint/SonarQube**，规则数量与覆盖面远小于后者；对二者结论应交叉验证，不应将本工具视为等价替代。
- Layer 3/3b/3c 并非零误报（见上方"诚实声明"）。
- 自定义规则（`.dotnet-review/rules.json`）仍可由 `analyze_custom()` 执行；Python 内置正则规则已从 `run_review()` 移除。
- 无 .NET SDK 或版本 < 6.0 时 CLI **硬阻断**（exit code 4，TOOL_MISSING），不软降级、不返回 issues。

## 性能基准（`.benchmarks/`）

`.benchmarks/` 是**内部维护工具**，用于测量 `review.py` 在不同代码库规模下的耗时，不在 SKILL.md 引用（非用户调用入口）。

| 文件 | 用途 |
|------|------|
| `.benchmarks/benchmark_runner.py` | 主入口：对 fixtures 跑 review.py，记录耗时到 `results/*.json` |
| `.benchmarks/benchmark_gen.py` | 合成 C# 测试数据生成器（生成 fixtures） |
| `.benchmarks/README.md` | 详细说明（目录结构 / 运行方式 / 规模档位） |
| `.benchmarks/fixtures/` | 合成测试数据（`tiny`→`xlarge` 5 档），在 `.gitignore`（可重新生成） |
| `.benchmarks/results/` | 历史 JSON 结果，在 `.gitignore` |

**规模档位**：tiny（250 行）/ small（4K 行）/ medium（25K 行）/ large（50K 行）/ xlarge（100K 行）。

**运行**：`python .benchmarks/benchmark_runner.py`（需先 `python .benchmarks/benchmark_gen.py` 生成 fixtures）。

**为何不进 SKILL.md**：基准是维护者评估性能回归用的，不是用户审查代码的入口。普通使用者无需关心。
