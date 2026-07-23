# Dimensions Coverage Matrix（6 维度规则覆盖矩阵）

> ⚠️ **执行口径（唯一真相）**：本文件描述各维度的**实际执行规则**，不以"规则定义"口径计数。Python 正则层已从 `run_review()` 移除；所有 C# 审查结论来自 Roslyn（AST/语义/项目级）+ `dotnet build`/`dotnet format` + NetAnalyzers。**规则数量以 `python scripts/count_rules.py` 为准**，当前快照为 175 条（AST `LEGACY_*` 153 条 + 语义 `SEM/EF/ASP/P/RCS` 22 条），另含项目级 + dotnet build/format + NetAnalyzers CAxxxx 动态注入。

> 加载时机：用户问"性能/可维护性/安全/最佳实践/架构哪条规则覆盖？"、评估技能成熟度、向用户证明覆盖度时。
> 数据来源：`scripts/csharp-ast-analyzer/Program.cs`（LEGACY_*）+ `scripts/csharp-semantic-analyzer/Program.cs`（SEM/EF/P/ASP）+ `scripts/csharp-project-analyzer/Program.cs`（ARCH/LAYER）+ `scripts/review/engine.py`（内联 S001/S002/S005/P021）+ dotnet build/format。

## 执行层速览

| 执行层 | 引擎 | 说明 |
|--------|------|------|
| **AST** | Roslyn `CSharpSyntaxWalker` | `LEGACY_*` 规则，153 条，语法级零误报 |
| **Semantic** | Roslyn `SemanticModel` | `SEM_*`/`EF*`/`ASP*`/`P*` 规则，14 条，类型/符号级 |
| **Project** | Roslyn 跨文件分析器 | `ARCH001`/`LAYER001`/`CS006` 等 |
| **Build** | `dotnet build` | CSxxxx 编译诊断 + NetAnalyzers CAxxxx（~500 条） |
| **Format** | `dotnet format` | IDE00xx 代码风格诊断 |
| **Style hint** | `run_review()` 内联 regex | S001/S002/S005（TODO/FIXME/commented-code） |
| **Perf hint** | `run_review()` 内联 regex | P021（byte[] → Span） |
| **Custom** | `.dotnet-review/rules.json` | 用户自定义规则 |
| **Duplicate** | 内部算法 | 重复代码检测（Layer 6） |

---

## 一、性能 (Performance)

**目标**：检测内存泄漏、不必要分配、CPU 浪费、装箱拆箱、低效集合等。

| 规则 | 来源 | severity | 检测点 |
|------|------|----------|--------|
| `LEGACY_P003_contains_in_loop` | AST | warning | 循环内 List.Contains |
| `LEGACY_P004_dictionary_in_loop` | AST | info | 循环内 Dict.ContainsKey |
| `LEGACY_reflection_in_loop` | AST | warning | 循环内反射 |
| `LEGACY_string_format_in_loop` | AST | warning | 循环内 string.Format |
| `LEGACY_ArrayList` | AST | info | 用 ArrayList（应用 List<T>） |
| `LEGACY_Hashtable` | AST | info | 用 Hashtable（应用 Dictionary） |
| `LEGACY_DataSet` | AST | info | 用 DataSet（应用 EF Core/Dapper） |
| `LEGACY_XmlDocument` | AST | info | 用 XmlDocument（应用 XDocument） |
| `LEGACY_P008_regex_not_cached` | AST | info | Regex 未缓存 |
| `LEGACY_GC_Collect` | AST | warning | 显式 GC.Collect() |
| `P021` | 内联 | info | byte[] 参数建议 Span<byte> |
| `EF001` | 语义 | warning | N+1 查询（CFG 控制流增强） |
| `EF004` | 语义 | info | 只读查询缺 AsNoTracking |
| `EF005` | 语义 | warning | async 方法内调用同步 SaveChanges()（应改 SaveChangesAsync） |
| `EF006` | 语义 | warning | DbContext 注册为 Singleton（跨请求共享会损坏 ChangeTracker） |
| `LEGACY_dynamic_local` | AST | info | `dynamic` 关键字（运行时绑定开销） |
| `CA18xx` | NetAnalyzers | — | 微软性能规则集（~30 条） |

**缺口**：ArrayPool/ObjectPool 推荐、stackalloc 检测、StringBuilder 容量预估。

---

## 二、可维护性 (Maintainability)

**目标**：检测复杂度、冗余、命名、抽象质量，让代码"易读易改"。

| 规则 | 来源 | severity | 检测点 |
|------|------|----------|--------|
| `LEGACY_S003_excessive_region` | AST | info | 过度 region 嵌套 |
| `LEGACY_S004_magic_number` | AST | info | 魔法数字 |
| `LEGACY_null_assignment` | AST | warning | C# 8+ null 提前赋值 |
| `CS006` | 项目级 | warning | God Class（成员数超阈值） |
| `LAYER002` | 项目级 | info | 孤儿类型（无引用） |
| `ARCH002` | 项目级 | warning | 架构违反（SAP 失衡） |
| `LEGACY_single_letter_var` | AST | info | 非循环变量用单字母 |
| `LEGACY_N002_method_pascalcase` | AST | warning | 方法名非 PascalCase |
| `LEGACY_N003_private_field_camelcase` | AST | info | 私有字段非 camelCase |
| `LEGACY_N005_hungarian` | AST | info | 匈牙利命名 |
| `LEGACY_N011_interface_iprefix` | AST | warning | 接口无 I 前缀 |
| `CA170x` | NetAnalyzers | — | 微软命名规则集 |
| `CS0067` | 编译 | — | 未使用的字段 |

**缺口**：圈复杂度精确计算（当前 ±20%）、SOLID 启发式（Bp013-019 无可靠静态信号）。

---

## 三、可测试性 (Testability)

**目标**：检测妨碍单元测试的模式（DateTime.Now、static IO、共享状态）。

| 规则 | 来源 | severity | 检测点 |
|------|------|----------|--------|
| `LEGACY_T004_empty_test` | AST | warning | 空测试体 |
| `LEGACY_T006_async_void_test` | AST | error | 测试方法 async void |
| `LEGACY_test_shared_state` | AST | warning | 测试共享可变状态 |
| `SEM012` | 语义 | warning | 反射使用（难 mock） |
| `S005` | 内联 | info | 测试中的注释代码 |
| `CA2007` | NetAnalyzers | — | 异步方法命名 |

**缺口**：DateTime.Now 在生产代码（info 提示，需 IClock 注入）、Mock 框架推荐。

---

## 四、安全 (Security)

**目标**：检测 OWASP Top 10 及 CWE 关键 sink。

| 规则 | 来源 | severity | CWE |
|------|------|----------|-----|
| `LEGACY_SqlCommand_Concat` | AST | error | CWE-89 |
| `LEGACY_LDAP_Concat` | AST | error | CWE-90 |
| `LEGACY_DirectorySearcher_Concat` | AST | error | CWE-90 |
| `LEGACY_SqlMethods_Like` | AST | error | CWE-89 |
| `LEGACY_SEC002_process_injection` | AST | error | CWE-78 |
| `LEGACY_SEC003_xpath_injection` | AST | error | CWE-643 |
| `LEGACY_SEC004_path_traversal` | AST | error | CWE-22 |
| `LEGACY_SEC_hardcoded_secret` | AST | error | CWE-798 |
| `LEGACY_SEC_secret_format` | AST | error | CWE-798 |
| `LEGACY_SEC_secret_entropy` | AST | warning | CWE-321 |
| `LEGACY_TLS_cert_validation_disabled` | AST | error | CWE-295 |
| `LEGACY_BinaryFormatter` | AST | error | CWE-502 |
| `LEGACY_CSharpCodeProvider` | AST | error | CWE-95 |
| `LEGACY_WebClient` | AST | warning | — |
| `LEGACY_HttpClient_New` | AST | warning | — |
| `LEGACY_XmlDocument` | AST | warning | CWE-611 |
| `LEGACY_SHA_Password` | AST | warning | CWE-327 |
| `LEGACY_SH002_insecure_random` | AST | warning | CWE-330 |
| `LEGACY_SH005_weak_crypto` | AST | warning | CWE-327 |
| `SEC022` | 内联/NetAnalyzers | error | CWE-347 |
| `SEC023` | 内联/NetAnalyzers | error | CWE-942 |
| `ASP002` | 语义 | warning | CWE-915 |
| `CA21xx` | NetAnalyzers | — | 微软安全规则集（~50 条） |
| `CA53xx` | NetAnalyzers | — | 微软加密规则集 |

三层硬编码密钥检测：变量名（password/secret/token）+ 已知格式（AWS/GitHub/JWT/PEM）+ 高熵 fallback（Shannon ≥ 4.5）。

---

## 五、最佳实践 / 可靠性 (Best Practices / Reliability)

**目标**：检测 SOLID 违反、异步/并发反模式、错误处理、依赖注入。

| 规则 | 来源 | severity | 检测点 |
|------|------|----------|--------|
| `LEGACY_async_void` | AST | warning | async void（非事件处理器） |
| `LEGACY_async_void_event` | AST | warning | 事件处理器 async void |
| `LEGACY_async_void_lambda` | AST | warning | lambda async void |
| `LEGACY_BP007_sync_wait` | AST | warning | .Result/.Wait() 死锁 |
| `LEGACY_BP007b_getawaiter_getresult` | AST | warning | GetAwaiter().GetResult() 死锁 |
| `LEGACY_BP021_task_run_server` | AST | info | Task.Run 服务端饥饿 |
| `LEGACY_throw_ex` | AST | error | throw ex 丢栈 |
| `LEGACY_empty_catch` | AST | warning | 空 catch 块 |
| `LEGACY_catch_exception` | AST | warning | catch(Exception) 过宽 |
| `LEGACY_catch_AggregateException` | AST | info | 异常展开 |
| `LEGACY_R016_task_whenall_not_awaited` | AST | error | WhenAll 未 await |
| `LEGACY_R026_async_void_action` | AST | warning | async void lambda 丢异常 |
| `LEGACY_R027_fire_and_forget_discard` | AST | warning | fire-and-forget 丢异常 |
| `LEGACY_lock_this` | AST | warning | lock(this) |
| `LEGACY_lock_typeof` | AST | warning | lock(typeof(T)) |
| `LEGACY_R005_nested_lock` | AST | warning | 嵌套 lock 死锁 |
| `LEGACY_Console_Write` | AST | info | 生产代码 Console |
| `LEGACY_Thread_Sleep` | AST | warning | Thread.Sleep |
| `LEGACY_NotImplementedException` | AST | info | NotImplementedException 残留 |
| `LEGACY_Thread_New` | AST | warning | new Thread() |
| `LEGACY_Thread.Abort` | AST | error | Thread.Abort 已废弃 |
| `LEGACY_HttpContext.Current` | AST | warning | ASP.NET Core 不可用 |
| `LEGACY_div_by_zero` | AST | error | 除零风险 |
| `LEGACY_equals_no_gethashcode` | AST | warning | Equals 未配 GetHashCode |
| `LEGACY_SEM006_struct_no_equalsequals` | AST | warning | struct 缺 operator== |
| `LEGACY_SEM007_captured_loop_variable` | AST | warning | 闭包捕获循环变量 |
| `LEGACY_SEM008_class_no_equalsequals` | AST | warning | class 缺 operator== |
| `LEGACY_SEM003_enum_no_none` | AST | info | 枚举缺 None=0 |
| `LEGACY_SEM004_idisposable_no_using` | AST | warning | IDisposable 未 using |
| `SEM001` | 语义 | warning | 访问 Nullable<T>.Value 前未检查 HasValue |
| `SEM002` | 语义 | warning | LINQ First()/Single() 无空集合保护 |
| `SEM009` | 语义 | info | 可空引用类型解引用前未判空 |
| `SEM013` | 语义 | info | 泛型参数过度约束（限制复用） |
| `SEM015` | 语义 | warning | IDisposable Dispose() 未释放字段 |
| `SEM016` | 语义 | info | struct 包含可变字段（值类型副本语义） |
| `EF006` | 语义 | warning | DbContext 注册为 Singleton（跨请求共享会损坏 ChangeTracker） |
| `RCS0013` | 语义 | info | 集合 3+ 次 Add() 调用可换集合初始化器语法 |
| `RCS0018` | 语义 | info | string.Format 可换字符串插值 |
| `RCS0045` | 语义 | info | if(x==null) 可用 ?? 操作符 |
| `RCS0052` | 语义 | info | 冗余的 base() 调用 |
| `RCS0096` | 语义 | info | nameof(typeof(X)) 可换语言关键字 |
| `LEGACY_ContinueWith` | AST | info | ContinueWith 而非 await |
| `LEGACY_R018_opc_not_rethrow` | AST | info | OperationCanceledException 不 rethrow |
| `LEGACY_R019_switch_no_default` | AST | info | switch 缺 default |
| `LEGACY_R021_broad_exception` | AST | warning | throw Exception() 过宽 |
| `LEGACY_R022_idisposable_field` | AST | warning | IDisposable 字段未 Dispose |
| `LEGACY_R023_method_too_long` | AST | warning | 方法超长 |
| `LEGACY_R024_too_many_params` | AST | warning | 参数过多 |
| `LEGACY_R025_lock_await` | AST | warning | lock 内 await |
| `LEGACY_AppDomain.CreateDomain` | AST | warning | 已废弃 |
| `LEGACY_WinForms_DoEvents` | AST | warning | DoEvents 重入 |
| `LEGACY_WinForms_Invoke` | AST | info | Control.Invoke 同步跨线程 |
| `LEGACY_WIN01_registry` | AST | warning | Windows-only API（跨平台） |
| `LEGACY_WIN02_system_drawing` | AST | warning | System.Drawing 已废弃 |
| `LEGACY_WIN03_event_log` | AST | warning | EventLog Windows-only |
| `LEGACY_WIN04_wmi` | AST | warning | WMI Windows-only |
| `ASP001` | 语义 | agent_verify | Controller 缺 [Authorize]（仅语义层） |
| `ASP002` / `ASP003` | AST + 语义 | agent_verify | Bind 含敏感字段 / IgnoreAntiforgeryToken（双层 emit，见下方说明） |
| `LEGACY_ASP004_developer_page` | AST | warning | UseDeveloperExceptionPage 未加环境守卫 |
| `LEGACY_ASP005_no_https_redirect` | AST | info | 缺 app.UseHttpsRedirection() |
| `LEGACY_ASP006_no_hsts` | AST | info | 缺 app.UseHsts()（生产环境） |
| `SEM_OUTREF_NULL_SAFE` | 语义 | 抑制 | out/ref 参数 null（C# 惯用法） |
| `CA22xx` | NetAnalyzers | — | 微软可靠性规则集 |
| `CA10xx/CA17xx` | NetAnalyzers | — | 微软设计规则集 |
| `CA20xx` | NetAnalyzers | — | Dispose 规则 |

**ASP002/003 双层 emit 说明**（为何两条都在表里、不去重）：

- **ASP002 不去重（有意）**：AST 抓 class 级 `[Bind]`/`[BindProperties]` + 类上的敏感属性（mass-assignment），语义层抓 param 级 `[Bind(Include="Password")]` 的参数（binding-include）。**不同位置、不同漏洞入口**，两层互补，都应保留。
- **ASP003 理论可去重但当前不去**：AST 和语义层都指向同一 `[IgnoreAntiforgeryToken]` attribute 位置（真重复）。语义层用 SemanticModel 解析符号更精确（能处理命名空间限定/别名），但 `suppress_ast_semantic_overlap` 只扩展到了 `SEM_OUTREF_NULL_SAFE`，未覆盖 ASP003。留作未来改进；当前 Agent 按 `agent_verify` triage 人工判读（同 attribute 出现两条 ASP003 时取语义层那条）。

详见 `references/rules-catalog.md` §二 注脚。

---

## 六、架构 (Architecture)

**目标**：检测跨层依赖违反、循环依赖、死代码、架构违反。

| 规则 | 来源 | severity | 检测点 |
|------|------|----------|--------|
| `LAYER001` | 项目级 | warning | 跨层依赖违反（目录分层） |
| `ARCH001` | 项目级 | warning | 循环依赖（Tarjan SCC） |
| `ARCH002` | 项目级 | warning | 架构违反（SAP 失衡） |
| `ARCH003` | 项目级 | info | 未调用的 public 方法 |
| `ARCH004` | 项目级 | warning | 接口无实现类 |
| `LAYER002` | 项目级 | info | 孤儿类型（无引用） |
| `CS006` | 项目级 | warning | God Class（成员数超阈值） |

**缺口**：跨程序集分析（AdhocWorkspace 限制）、NuGet 依赖图解析。

---

## 覆盖度声明

- **OWASP Top 10**：见 `references/owasp-mapping.md`，现有 SEC/LEGACY_*/EF*/ASP* 规则覆盖 A01-A10。
- **CWE 关键 sink**：CWE-22/78/79/89/90/95/259/295/327/330/347/470/502/601/611/614/643/798/918/942/915。
- **可量化指标**：error -10、warning -5、info -1，可通过 `scoring-and-thresholds.md` 调整权重。

## 已知缺口（透明声明）

1. **跨程序集 API 分析**：受 `AdhocWorkspace` 限制，不进行全解决方案 MSBuild 解析。
2. **运行时行为**：纯静态分析，不模拟执行。
3. **EF/ASP/SEM 规则**：`EF001` 已升级为 CFG 增强，`EF002/EF004/EF005/EF006/ASP001-003/SEM001/SEM002/SEM009/SEM013/SEM015/SEM016` 均为 `agent_verify` 或 `deterministic`，仍有上下文误报风险。
4. **可观测性维度**：无规则（日志/指标/跟踪需运行时 APM 工具）。
5. **C# 12+ 新特性**：collection expressions、primary constructors 滥用等规则未覆盖。
