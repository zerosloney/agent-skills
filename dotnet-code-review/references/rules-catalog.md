# Rules Catalog（规则目录）

> 加载时机：解读某条规则 ID、生成修复方向、判断规则是否在 AUTO_FIX / TEST_PROJECT_RELAXED_RULES / WIN_ONLY_API_RULES 列表中。
> 数据来源：`scripts/review/rules.py`（AUTO_FIXES / AST_RULE_META / RULE_TRIAGE）+ `scripts/review/engine.py`（内联 style/perf_hint）+ `scripts/csharp-ast-analyzer/Program.cs`（LEGACY_*）+ `scripts/csharp-semantic-analyzer/Program.cs`（SEM/EF/ASP/P）+ `scripts/csharp-project-analyzer/Program.cs`（ARCH/LAYER/CS006）。

## 执行口径（唯一真相）

Python 正则层（`analyze_builtin` / `analyze_complexity`）已从 `run_review()` 移除。**所有 C# 审查结论来自：**

| 执行层 | 来源 | 说明 |
|--------|------|------|
| **AST** | `csharp-ast-analyzer/Program.cs` | Roslyn `CSharpSyntaxWalker`，`LEGACY_*` 规则 |
| **Semantic** | `csharp-semantic-analyzer/Program.cs` | Roslyn `SemanticModel`，`SEM_*`/`EF*`/`ASP*`/`P*` 规则 |
| **Project** | `csharp-project-analyzer/Program.cs` | 跨文件分析，`ARCH001`/`LAYER001`/`CS006` 等 |
| **Build** | `dotnet build` | CSxxxx 编译诊断 + NetAnalyzers CAxxxx（约 500 条） |
| **Format** | `dotnet format` | IDE00xx 代码风格诊断 |
| **Custom** | `.dotnet-review/rules.json` | 用户自定义正则规则 |
| **Duplicate** | `detect_duplicates()` | 内部重复代码算法 |
| **Doc** | `check_xml_documentation()` | XML 文档检查 |
| **Style hint** | `run_review()` 内联 | S001/S002/S005（TODO/FIXME/commented-code） |
| **Perf hint** | `run_review()` 内联 | P021（byte[] → Span） |

**规则数量以 `python scripts/count_rules.py` 输出为准。**

## Severity 说明

| severity | 评分扣分 | 含义 |
|----------|---------|------|
| error | -10 | 阻断级（安全/可靠性/复杂度红线） |
| warning | -5 | 需修复 |
| info | -1 | 提示，仅列出不生成修复 |

---

## 一、AST 层规则（LEGACY_*，Roslyn CSharpSyntaxWalker 产出）

> 完整列表以 `scripts/csharp-ast-analyzer/Program.cs` 源码为准。典型条目：

| LEGACY ID | 概念 | severity |
|-----------|------|----------|
| LEGACY_async_void / async_void_event / async_void_lambda / async_void_test | async void 误用 | error/warning |
| LEGACY_BinaryFormatter / CSharpCodeProvider | 危险序列化 | error |
| LEGACY_SqlCommand_Concat / LDAP_Concat / SqlMethods_Like | SQL/LDAP 注入 | error |
| LEGACY_SEC_hardcoded_secret / _secret_format / _secret_entropy | 硬编码密钥三层检测 | error/warning |
| LEGACY_TLS_cert_validation_disabled | TLS 证书验证绕过 | error |
| LEGACY_SHA_Password | 密码用 SHA | warning |
| LEGACY_HttpClient_New / WebClient / ArrayList / Hashtable / DataSet | 过时/低效 API | info/warning |
| LEGACY_BP007_sync_wait / BP007b_getawaiter_getresult | 同步等异步 | warning |
| LEGACY_lock_this / lock_typeof / R005_nested_lock | 锁误用 | warning |
| LEGACY_empty_catch / catch_exception / throw_ex / catch_AggregateException | 异常处理 | warning/error |
| LEGACY_R016_task_whenall_not_awaited / R026_async_void_action / R027_fire_and_forget | 任务异常丢失 | error/warning |
| LEGACY_SEM006_struct_no_equalsequals / SEM007_captured_loop_variable / SEM008_class_no_equalsequals | 语义反模式 | warning |
| LEGACY_test_shared_state / T004_empty_test / T006_async_void_test | 测试问题 | warning/error |
| LEGACY_single_letter_var / N002_method_pascalcase / N011_interface_iprefix | 命名约定 | info/warning |
| LEGACY_GC_Collect | 显式 GC.Collect | warning |
| LEGACY_div_by_zero | 除零风险 | error |
| LEGACY_Console_Write / Thread_Sleep / NotImplementedException | 习惯问题 | info |
| LEGACY_WIN01_registry / WIN02_system_drawing / WIN03_event_log / WIN04_wmi | Windows-only API | warning |
| LEGACY_equals_no_gethashcode / SEM003_enum_no_none / SEM004_idisposable_no_using | 语义规则 | info/warning |
| LEGACY_ASP002_binding_sensitive / LEGACY_ASP003_antiforgery_skip / LEGACY_ASP004_developer_page / LEGACY_ASP005_no_https_redirect / LEGACY_ASP006_no_hsts | ASP.NET Core 安全规则 | warning/info |

## 二、语义层规则（SEM/EF/ASP/P\*，Roslyn SemanticModel 产出）

> 完整列表以 `scripts/csharp-semantic-analyzer/Program.cs` 源码为准。
> 注：`ASP001` 仅由语义分析器（第 3b 层）实现。`ASP002`/`ASP003` 在 AST 层（`LEGACY_ASP002`/`ASP003`）和语义层（`ASP002`/`ASP003`）都 emit。`ASP004`/`ASP005`/`ASP006` 仅 AST 层。

**ASP002/003 双层 emit 的详细语义**（为何部分去重、部分保留）：

| 规则 | AST 层抓什么（位置） | 语义层抓什么（位置） | 去重？ |
|------|---------------------|---------------------|--------|
| **ASP002** | class 级 `[Bind]`/`[BindProperties]` + 类上的敏感属性名（mass-assignment 风险）—— 报 **class** 位置 | param 级 `[Bind(Include="Password")]` 的 attribute 参数（binding-include 风险）—— 报 **parameter** 位置 | **不去重**（不同位置、不同漏洞，两层互补） |
| **ASP003** | `[IgnoreAntiforgeryToken]` 语法名匹配 —— 报 **attribute** 位置 | 同一 attribute，用 SemanticModel 解析符号（处理命名空间限定/别名）—— 报 **attribute** 位置 | **理论可去重但当前不去**（同位置真重复；`suppress_ast_semantic_overlap` 只处理 `SEM_OUTREF_NULL_SAFE`，未扩展到 ASP003） |

> **ASP003 去重留作未来改进**：语义层比 AST 更精确（符号解析能处理 `[Microsoft.AspNetCore.Mvc.IgnoreAntiforgeryToken]` 全名形式，AST 的字符串匹配会漏检别名）。当前两层都报，Agent 按 `agent_verify` triage 人工判读（同一 attribute 出现两条 ASP003 时只取语义层那条即可）。
> **ASP002 不去重是有意的**：两层抓的是 mass-assignment 漏洞的两个不同入口（class 级默认绑定 vs param 级显式 Include 列表），都应保留。

| 规则 | 概念 | severity |
|------|------|----------|
| SEM_OUTREF_NULL_SAFE | out/ref 参数 null 赋值（C# 语言惯用法） | deterministic 抑制 |
| SEM_TYPE_GETTYPE_CONCAT / SEM_TYPE_GETTYPE_USERINPUT | 符号级类型注入 | warning |
| EF001 | N+1 查询（CFG 控制流分析） | warning |
| EF002 | SaveChangesAsync 无事务 | warning |
| EF003 | FromSqlRaw 拼接 | error |
| EF004 | 只读查询缺 AsNoTracking | info |
| ASP001 | Controller 缺 [Authorize] | agent_verify | Semantic (3b) |
| ASP002 | Bind 含敏感字段 | agent_verify | Semantic (3b) |
| ASP003 | IgnoreAntiforgeryToken 跳过 | agent_verify | Semantic (3b) |

## 三、项目级规则（ARCH/LAYER/CS006，Roslyn 跨文件分析器产出）

| 规则 | 概念 | severity |
|------|------|----------|
| LAYER001 | 跨层依赖违反（目录分层约定） | warning |
| ARCH001 | 循环依赖（Tarjan SCC） | warning |
| ARCH002 | 架构违反（SAP 失衡） | warning |
| ARCH003 | 未调用的 public 方法 | info |
| ARCH004 | 接口无实现类 | warning |
| CS006 | God Class（成员数超阈值） | warning |
| LAYER002 | 孤儿类型（无引用） | info |

## 四、AUTO_FIXES（`rules.py`，`--fix` 时执行）

| 规则 | 修复行为 | 风险 |
|------|---------|------|
| S001 | `// TODO` → `// TODO():` 插入空 owner 占位 | 低 |
| S002 | `// FIXME` → `// REVIEW: needs an issue link` | 低 |
| S003 | 删除 `#region...#endregion` 块 | 中 |
| S005 | 删除注释掉的代码行 | 中 |
| BP010 | `throw new NotImplementedException()` → `NotSupportedException` | 低 |
| P010 | `x == ""` → `string.IsNullOrEmpty(x)` | 低 |
| BP011 | `throw ex;` → `throw;`（保留栈） | 低 |
| S006 | `new String(` → `new string(` | 低 |
| R021 | `throw new Exception()` → `InvalidOperationException` | 低 |

> CS002 故意排除——删除未用参数需理解全部调用方，正则无法安全完成。
> **自定义规则永不进入 AUTO_FIX**。`RULE_ID_ALIASES`（`rules.py`）处理 LEGACY_* → 正则 ID 的别名映射。

## 五、框架过滤规则

| 集合 | 规则 | 说明 |
|------|------|------|
| `TEST_PROJECT_RELAXED_RULES` | `BP001` `BP010` `LEGACY_Console_Write` `LEGACY_NotImplementedException` | 测试项目降级（Console/NotImplemented 可接受） |
| `WIN_ONLY_API_RULES` | `LEGACY_WIN01_registry` `WIN02_system_drawing` `WIN03_event_log` `WIN04_wmi` | 跨平台项目中 Windows-only API 才告警 |

## 六、Triage 分类（`rules.py`）

| triage 值 | 含义 |
|-----------|------|
| **deterministic** | Roslyn 已确认，零误报，直接报告 |
| **agent_verify** | 高置信候选，需读取源码上下文判断（verification_hints 见 `rules.py` `RULE_VERIFICATION_HINTS`） |
| **agent_only** | 工具无法检测，Agent 自行分析 |
