# Best Practices Catalog（DI / Async / Error Handling / Dispose）

> 加载时机：Code review 时给作者讲"为什么这是反模式"、生成修复方向、培训新人时。
> 数据来源：`scripts/csharp-ast-analyzer/Program.cs`（`LEGACY_*`）+ `scripts/csharp-semantic-analyzer/Program.cs`（`SEM_*`）+ `run_review()` 内联（S001/S002/S005）。
> 维护原则：反例必须来自真实 C# 项目常见模式，正例必须可编译运行。

---

## 一、依赖注入 (Dependency Injection)

### 1.1 服务不应直接 new

**反例**（直接 new 硬编码依赖；规则覆盖见 §七 矩阵）：

```csharp
public class OrderService
{
    private readonly EmailSender _emailer = new EmailSender();  // 硬编码依赖
    private readonly DbContext _db = new MyDbContext();          // 难测试

    public void PlaceOrder(Order o) {
        _db.Save(o);
        _emailer.Send(o.Customer.Email, "Order placed");
    }
}

// 单元测试：如何 mock EmailSender？如何替换 DbContext？
```

**正例**：

```csharp
public class OrderService
{
    private readonly IEmailSender _emailer;
    private readonly IOrderRepository _repo;

    public OrderService(IEmailSender emailer, IOrderRepository repo) {
        _emailer = emailer;
        _repo = repo;
    }

    public void PlaceOrder(Order o) {
        _repo.Save(o);
        _emailer.Send(o.Customer.Email, "Order placed");
    }
}

// 单元测试：注入 mock
var service = new OrderService(mockEmailer.Object, mockRepo.Object);
```

**为何重要**：
- 可测试性（mock 依赖）
- 配置灵活性（多环境切换）
- 生命周期管理（DI 容器统一 dispose）

### 1.2 静态服务（Service Locator 反模式）

**反例**（Service Locator 反模式；工具无静态信号，见人工 checklist）：

```csharp
public class ReportGenerator
{
    public void Generate() {
        // 运行时查找，破坏显式依赖
        var logger = ServiceLocator.Get<ILogger>();
        logger.Info("Starting report");
    }
}
```

**正例**：构造函数注入，ILogger 通过 DI 容器注册。

### 1.3 HttpClient 直接 new

**反例**（`LEGACY_HttpClient_New` httpclient-usage）：

```csharp
public class ApiClient
{
    public async Task<string> Get(string url) {
        using var client = new HttpClient();  // 每次新建、TCP 握手开销
        return await client.GetStringAsync(url);
    }
}
```

**正例**：

```csharp
public class ApiClient
{
    private readonly HttpClient _client;
    public ApiClient(HttpClient client) {
        _client = client;  // IHttpClientFactory 注入
    }
    public async Task<string> Get(string url) =>
        await _client.GetStringAsync(url);
}
```

**为何重要**：
- `new HttpClient()` 每次新建 socket（socket 耗尽风险）
- 不重用 `HttpMessageHandler` 导致 DNS 不更新
- 难以集中配置 timeout/headers/auth

### 1.4 依赖反转 (DIP)

**反例**（依赖具体类而非抽象；SOLID 启发式已移除，见 §七 注脚）：

```csharp
public class OrderService
{
    private readonly SqlOrderRepository _repo = new SqlOrderRepository();
    // 直接依赖具体类，无法换成 InMemoryOrderRepository 测试
}
```

**正例**：见 1.1 正例。

---

## 二、异步编程 (Async/Await)

### 2.1 async void 误用

**反例**（async-void 业务方法；实际规则 `LEGACY_async_void`）：

```csharp
public async void ProcessClick(object sender, EventArgs e)
{
    await DoWorkAsync();
    UpdateUi();  // 异常无法被 catch
}
```

**正例**（仅用于事件处理器，且内含 try/catch）：

```csharp
private async void ProcessClick(object sender, EventArgs e)
{
    try {
        await DoWorkAsync();
        UpdateUi();
    } catch (Exception ex) {
        _logger.LogError(ex, "Click handler failed");
    }
}

// 业务方法必须 async Task
public async Task ProcessAsync() { ... }
```

**检测规则**：`LEGACY_async_void`（业务方法）、`LEGACY_async_void_event`（事件处理器）、`LEGACY_async_void_lambda`（lambda）、`LEGACY_async_lambda_no_await`。

### 2.2 .Result / .Wait() 死锁

**反例**（`LEGACY_BP007_sync_wait` task-result-wait）：

```csharp
public string GetData()
{
    return GetDataAsync().Result;  // UI 线程死锁
}

// WPF/WinForms/ASP.NET classic 都会死锁（同步上下文 + Task.Wait）
```

**正例**：

```csharp
public async Task<string> GetDataAsync()
{
    return await GetDataAsync();
}
```

**async 全程**：从最外层 (Controller/MVVM) 一直 `await` 到底层。

### 2.3 ConfigureAwait 误用

**反例**（库代码缺 ConfigureAwait；⚠️ 工具无静态检测，需人工/代码评审确认）：

```csharp
// 库代码：会捕获调用方 SynchronizationContext，导致死锁/性能问题
public async Task<string> ReadAsync()
{
    using var stream = new FileStream(...);
    return await new StreamReader(stream).ReadToEndAsync();
    // 缺少 .ConfigureAwait(false)
}
```

**正例**：

```csharp
public async Task<string> ReadAsync()
{
    using var stream = new FileStream(...);
    return await new StreamReader(stream).ReadToEndAsync().ConfigureAwait(false);
}
```

**检测规则**：⚠️ 本工具未实现 ConfigureAwait 缺失检测（无可靠静态信号——需判断是否库代码）。建议团队在 `.editorconfig` 配 StyleCop SA1413 或人工 review。

### 2.4 缺 CancellationToken

**反例**（R014 cancellation-token）：

```csharp
public async Task<List<Order>> GetAllOrdersAsync()
{
    // 无法取消，客户端断开后仍继续工作
    var orders = await _repo.QueryAsync<Order>();
    return orders.ToList();
}
```

**正例**：

```csharp
public async Task<List<Order>> GetAllOrdersAsync(CancellationToken ct = default)
{
    var orders = await _repo.QueryAsync<Order>(ct);
    return orders.ToList();
}
```

### 2.5 async 无 await

**反例**（`LEGACY_async_lambda_no_await` async-await-mismatch）：

```csharp
public async Task<int> GetValueAsync()
{
    return 42;  // 标记 async 但无 await，徒增状态机开销
}
```

**正例**：

```csharp
public Task<int> GetValueAsync() => Task.FromResult(42);
// 或
public int GetValue() => 42;  // 不需要异步
```

### 2.6 Task.WhenAll 缺 await

**反例**（R016 task-whenall-without-await）：

```csharp
public async Task ProcessBatch()
{
    Task.WhenAll(items.Select(ProcessAsync));  // 缺 await！
    Log.Info("Done");  // 实际 ProcessAsync 还在跑
}
```

**正例**：

```csharp
public async Task ProcessBatch()
{
    await Task.WhenAll(items.Select(ProcessAsync));
    Log.Info("Done");
}
```

---

## 三、错误处理 (Error Handling)

### 3.1 空 catch

**反例**（`LEGACY_empty_catch` empty-catch）：

```csharp
try { RiskyOperation(); }
catch (Exception) { }  // 静默吞掉所有错误
```

**正例**：

```csharp
try { RiskyOperation(); }
catch (SpecificException ex) {
    _logger.LogError(ex, "Operation failed");
    throw;  // 或翻译为业务异常
}
```

### 3.2 捕获过于宽泛

**反例**（`LEGACY_catch_exception` catch-exception）：

```csharp
try { DoWork(); }
catch (Exception) { ... }  // 包含 OOM、ThreadAbort 等
```

**正例**：

```csharp
try { DoWork(); }
catch (IOException ex) { ... }
catch (JsonException ex) { ... }
```

### 3.3 catch 后只 log

**反例**（R003 exception-swallowed）：

```csharp
try { DoWork(); }
catch (Exception ex) {
    _logger.LogError(ex, "failed");
    // 没 throw、没返回错误状态、没恢复
    // 调用方不知道发生了错误
}
```

**正例**（选择其一）：
- `throw;`（让上层处理）
- 返回 `Result<T, Error>` 包装
- 设置状态标志

### 3.4 throw ex 丢失栈

**反例**（`LEGACY_throw_ex` throw-ex-rethrow；可 `--fix` 自动修复为 `throw;`）：

```csharp
try { DoWork(); }
catch (Exception ex) {
    throw ex;  // 栈从此处开始，原始栈丢失
}
```

**正例**：

```csharp
try { DoWork(); }
catch (Exception ex) {
    throw;  // 保留原始栈
}
// 或包装为新异常：
catch (Exception ex) {
    throw new MyBusinessException("Operation failed", ex);
}
```

### 3.5 NotImplementedException 残留

**反例**（`LEGACY_NotImplementedException` notimplemented；可 `--fix` 自动修复为 `NotSupportedException`）：

```csharp
public decimal CalculateDiscount(Customer c)
{
    // TODO: implement
    throw new NotImplementedException();  // 残留
}
```

**正例**：
- 实现方法
- 显式标记 abstract
- 抛 `NotSupportedException` 表达"不支持"语义

### 3.6 AggregateException 未展开

**反例**（`LEGACY_catch_AggregateException` aggregate-exception-handling）：

```csharp
try { Task.WaitAll(tasks); }
catch (AggregateException ae) {
    // 忘了 .Flatten() / .InnerExceptions
    Console.WriteLine(ae.Message);
}
```

**正例**：

```csharp
try { Task.WaitAll(tasks); }
catch (AggregateException ae) {
    foreach (var ex in ae.Flatten().InnerExceptions) {
        _logger.LogError(ex, "Task failed");
    }
}
```

---

## 四、Dispose 模式 (Resource Management)

### 4.1 IDisposable 未用 using

**反例**（`LEGACY_SEM004_idisposable_no_using` idisposable-not-disposed）：

```csharp
public void ReadFile()
{
    var stream = new FileStream("a.txt", FileMode.Open);
    var data = new byte[1024];
    stream.Read(data, 0, data.Length);
    // 异常或提前 return 时 stream 不会释放
}
```

**正例**：

```csharp
public void ReadFile()
{
    using var stream = new FileStream("a.txt", FileMode.Open);
    var data = new byte[1024];
    stream.Read(data, 0, data.Length);
}  // 离开作用域时 Dispose

// C# 8+ using 声明，作用域到方法结束
// 老代码用 using { } 块
```

### 4.2 派生类未调 base.Dispose

**反例**（AST 可检测，规则待新增 ID002）：

```csharp
public class MyResource : BaseResource
{
    private IntPtr _buffer;
    protected override void Dispose(bool disposing)
    {
        if (disposing) {
            // 释放托管资源
        }
        Marshal.FreeHGlobal(_buffer);
        // 忘了 base.Dispose(disposing) ！
    }
}
```

**正例**：

```csharp
protected override void Dispose(bool disposing)
{
    if (disposing) {
        // 释放托管资源
    }
    Marshal.FreeHGlobal(_buffer);
    base.Dispose(disposing);  // 必须
}
```

### 4.3 Equals 缺 GetHashCode（与 Dispose 同属"类完整性"）

**反例**（`LEGACY_equals_no_gethashcode` equals-no-gethashcode）：

```csharp
public class Money : IEquatable<Money>
{
    public decimal Amount { get; }
    public string Currency { get; }
    public bool Equals(Money other) => Amount == other.Amount && Currency == other.Currency;
    // 缺 GetHashCode override！
    // Dictionary<Money, T> 工作异常
}
```

**正例**：

```csharp
public class Money : IEquatable<Money>
{
    public decimal Amount { get; }
    public string Currency { get; }
    public bool Equals(Money other) => Amount == other.Amount && Currency == other.Currency;
    public override int GetHashCode() => HashCode.Combine(Amount, Currency);
}
```

---

## 五、EF Core 反模式

### 5.1 N+1 查询（EF001）

**反例**：

```csharp
// 外层枚举触发 lazy loading，每条记录再查一次导航属性
foreach (var order in orders) {
    var items = order.Items.ToList();  // N+1：orders.Count + 1 次查询
}
```

**正例**：

```csharp
// 一次性 Include 或投影
var orders = await ctx.Orders
    .Include(o => o.Items)
    .ToListAsync();
// 或
var data = await ctx.Orders
    .Select(o => new { o.Id, Items = o.Items.Count })
    .ToListAsync();
```

### 5.2 SaveChanges 未包事务（EF002）

**反例**：

```csharp
// 多步写入，部分失败时数据不一致
await ctx.Orders.Add(order);
await ctx.Products.Update(product);
await ctx.SaveChangesAsync();  // 没有事务包裹
```

**正例**：

```csharp
await using var tx = await ctx.Database.BeginTransactionAsync();
try {
    await ctx.Orders.Add(order);
    await ctx.Products.Update(product);
    await ctx.SaveChangesAsync();
    await tx.CommitAsync();
} catch {
    await tx.RollbackAsync();
    throw;
}
```

### 5.3 FromSqlRaw 拼接注入（EF003）

**反例**：

```csharp
// 字符串拼接 → SQL 注入
ctx.Database.ExecuteSqlRaw($"DELETE FROM Orders WHERE Id = {orderId}");
ctx.Database.FromSqlRaw($"SELECT * FROM Users WHERE Name = '{name}'");
```

**正例**：

```csharp
// 参数化查询
ctx.Database.ExecuteSqlInterpolated($"DELETE FROM Orders WHERE Id = {orderId}");
ctx.Database.FromSqlInterpolated($"SELECT * FROM Users WHERE Name = {name}");
// 或使用 {0} 占位符
ctx.Database.FromSqlRaw("SELECT * FROM Users WHERE Name = {0}", name);
```

### 5.4 只读查询缺 AsNoTracking（EF004）

**反例**：

```csharp
// 只读查询未加 AsNoTracking，EF 追踪实体造成额外开销
var allProducts = await ctx.Products.ToListAsync();
```

**正例**：

```csharp
var allProducts = await ctx.Products.AsNoTracking().ToListAsync();
```

---

## 六、IDE 格式诊断（dotnet format）

Layer 5 将 `dotnet format --verify-no-changes` 输出的 IDE 诊断映射到审查维度，便于在审查报告中统一归类。

| IDE 规则 | 维度 | 含义 | 修复建议 |
|---------|------|------|---------|
| IDE0055 | style | 格式不一致 | 运行 `dotnet format` 或配置 `.editorconfig` |
| IDE0005 | style | 冗余 using | 删未用 using |
| IDE0057 | performance | foreach 参数可替换为局部 | 用局部变量避免重复枚举 |
| IDE0059 | performance | 不必要的参数赋值 | 移除未使用的赋值 |
| IDE0060 | naming | 未使用参数 | 删或用 `_` 前缀 |
| IDE1006 | naming | 命名风格 | 统一 Pascal/camel 风格 |
| IDE0039 | reliability | 局部函数可提取 | 提取为私有方法提升可测性 |
| IDE0052 | reliability | 未读私有成员 | 删或用 `_` 前缀 |

> 未知 IDE 规则默认归入 **style** 维度，附带诊断消息原文作为修复建议。

---

## 七、最佳实践总览矩阵

> severity 以 `scripts/review/rules.py` + 分析器源码为准。下表只列**实际 emit** 的规则（`python scripts/count_rules.py` 核对）。

| 主题 | 实际 emit 的规则 | severity | 反模式 |
|------|-----------------|----------|--------|
| **DI / 依赖管理** | `LEGACY_HttpClient_New` | warning | `new HttpClient()` 每次新建（socket 耗尽）；用 IHttpClientFactory |
| **Async** | `LEGACY_async_void`, `LEGACY_async_void_event`, `LEGACY_async_void_lambda`, `LEGACY_BP007_sync_wait`, `LEGACY_BP007b_getawaiter_getresult`, `LEGACY_BP021_task_run_server`, `LEGACY_R014_cancellation_token`, `LEGACY_R016_task_whenall_not_awaited`, `LEGACY_R025_lock_await`, `LEGACY_async_lambda_no_await` | warning/error | async void、.Result/.Wait() 死锁、Task.WhenAll 未 await、lock 内 await |
| **Error** | `LEGACY_throw_ex` (error), `LEGACY_R021_broad_exception`, `LEGACY_empty_catch`, `LEGACY_catch_exception`, `LEGACY_R003_catch_swallow`, `LEGACY_catch_AggregateException`, `LEGACY_NotImplementedException` | error/warning | throw ex 丢栈、空 catch、catch(Exception) 过宽、吞异常 |
| **Dispose** | `LEGACY_SEM004_idisposable_no_using`, `LEGACY_R022_idisposable_field`, `LEGACY_equals_no_gethashcode` | warning | IDisposable 未 using、字段未 Dispose、Equals 缺 GetHashCode |
| **资源现代化** | `LEGACY_BP022_random_shared`, `LEGACY_BP023_system_text_json`, `LEGACY_BP024_datetime_modern`, `LEGACY_BP008_string_concat_loop` | best-practice | `new Random()`、Newtonsoft.Json、`DateTime.Now`、循环内字符串拼接 |

> **已移除的设计规则**：BP013/BP016/BP017（SOLID 启发式）、BP006/BP012/SEM010/R001/R020 等 62 条 SKIP 规则已在 commit `a526a92` 删除（启发式对 C# 误报率高，无可靠静态信号）。本表不再列出。本文档 §一/§二/§三 的反例代码保留作教学用途，但不再绑定这些 ID。

## 八、推荐配置

```yaml
# .editorconfig 配套（团队规范）—— 仅列实际 emit 的规则
dotnet_diagnostic.LEGACY_BP007_sync_wait.severity = warning  # .Result/.Wait() 死锁
dotnet_diagnostic.LEGACY_SEM004_idisposable_no_using.severity = warning  # IDisposable 未 using
dotnet_diagnostic.LEGACY_throw_ex.severity = error  # throw ex 丢栈
```

## 九、CI 集成建议

```bash
# PR 级别门禁
python scripts/review.py --target . \
    --quality-gate-score 80 \
    --fail-on error \
    --incremental-semantic
```

按 `--fail-on error` 阻断 critical 级（`LEGACY_throw_ex`、`LEGACY_R016_task_whenall_not_awaited`、`LEGACY_BP007_sync_wait` 等），warning 进入 review 讨论。
