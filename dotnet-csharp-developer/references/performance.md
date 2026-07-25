# 性能优化

## Span<T> 和 Memory<T>

```csharp
// 传统字符串操作（分配内存）
public string ProcessStringOld(string input)
{
    return input.Substring(0, 10).ToUpper();
}

// 用 Span<T>（零分配）
public string ProcessStringNew(ReadOnlySpan<char> input)
{
    Span<char> buffer = stackalloc char[10];
    input[..10].ToUpperInvariant(buffer);
    return new string(buffer);
}

// 用 Span<T> 解析
public int ParseNumber(ReadOnlySpan<char> text)
{
    return int.Parse(text);
}

// 小数组栈分配
public void ProcessSmallArray()
{
    Span<int> numbers = stackalloc int[10];
    for (int i = 0; i < numbers.Length; i++)
    {
        numbers[i] = i * 2;
    }
}

// 处理字节
public void ProcessBytes(ReadOnlySpan<byte> data)
{
// 直接内存访问，无分配
    for (int i = 0; i < data.Length; i++)
    {
        var byte = data[i];
// 处理字节
    }
}
```

## ArrayPool 缓冲区复用

```csharp
using System.Buffers;

public class BufferProcessor
{
    public async Task ProcessLargeDataAsync(Stream stream, CancellationToken ct)
    {
        // 从池租数组
        var buffer = ArrayPool<byte>.Shared.Rent(4096);

        try
        {
            int bytesRead;
            while ((bytesRead = await stream.ReadAsync(buffer, ct)) > 0)
            {
                // 处理 buffer[0..bytesRead]
                ProcessChunk(buffer.AsSpan(0, bytesRead));
            }
        }
        finally
        {
            // 归还到池
            ArrayPool<byte>.Shared.Return(buffer);
        }
    }

    private void ProcessChunk(ReadOnlySpan<byte> chunk)
    {
        // 处理逻辑
    }
}
```

## 异步最佳实践

```csharp
// 频繁同步路径用 ValueTask
public class CacheService
{
    private readonly Dictionary<string, string> _cache = new();

    public ValueTask<string?> GetAsync(string key)
    {
        // 已缓存，同步返回，无分配
        if (_cache.TryGetValue(key, out var value))
            return ValueTask.FromResult<string?>(value);

        // 否则走异步
        return LoadFromDatabaseAsync(key);
    }

    private async ValueTask<string?> LoadFromDatabaseAsync(string key)
    {
        var value = await _database.GetAsync(key);
        _cache[key] = value;
        return value;
    }
}

// 库代码用 ConfigureAwait(false)
public async Task<Data> GetDataAsync()
{
    var response = await _httpClient.GetAsync("api/data")
        .ConfigureAwait(false);
    return await response.Content.ReadFromJsonAsync<Data>()
        .ConfigureAwait(false);
}

// 避免 async void（事件处理程序除外）
public async void ButtonClick(object sender, EventArgs e) // 事件中可用
{
    try
    {
        await ProcessClickAsync();
    }
    catch (Exception ex)
    {
        _logger.LogError(ex, "处理点击时出错");
    }
}

// CancellationToken 支持
public async Task<List<Product>> GetProductsAsync(CancellationToken ct = default)
{
    return await _dbContext.Products
        .AsNoTracking()
        .ToListAsync(ct);
}

// 并行异步操作
public async Task<(User user, Orders orders, Profile profile)> GetUserDataAsync(int userId)
{
    var userTask = _userService.GetAsync(userId);
    var ordersTask = _orderService.GetByUserAsync(userId);
    var profileTask = _profileService.GetAsync(userId);

    await Task.WhenAll(userTask, ordersTask, profileTask);

    return (await userTask, await ordersTask, await profileTask);
}
```

## 对象池化

```csharp
using Microsoft.Extensions.ObjectPool;

// 定义池化对象策略
public class StringBuilderPooledObjectPolicy : PooledObjectPolicy<StringBuilder>
{
    public override StringBuilder Create() => new StringBuilder();

    public override bool Return(StringBuilder obj)
    {
        obj.Clear();
        return obj.Capacity <= 4096; // 容量过大不池化
    }
}

// DI 中注册
builder.Services.AddSingleton<ObjectPoolProvider, DefaultObjectPoolProvider>();
builder.Services.AddSingleton(serviceProvider =>
{
    var provider = serviceProvider.GetRequiredService<ObjectPoolProvider>();
    return provider.Create(new StringBuilderPooledObjectPolicy());
});

// 使用
public class MessageFormatter(ObjectPool<StringBuilder> pool)
{
    public string FormatMessage(string template, params object[] args)
    {
        var builder = pool.Get();
        try
        {
            builder.AppendFormat(template, args);
            return builder.ToString();
        }
        finally
        {
            pool.Return(builder);
        }
    }
}
```

## 用 BenchmarkDotNet 做基准测试

```csharp
using BenchmarkDotNet.Attributes;
using BenchmarkDotNet.Running;

[MemoryDiagnoser]
[SimpleJob(warmupCount: 3, iterationCount: 5)]
public class StringBenchmarks
{
    private const string Input = "Hello, World!";

    [Benchmark(Baseline = true)]
    public string UsingSubstring()
    {
        return Input.Substring(0, 5).ToUpper();
    }

    [Benchmark]
    public string UsingSpan()
    {
        ReadOnlySpan<char> span = Input.AsSpan(0, 5);
        return span.ToString().ToUpper();
    }

    [Benchmark]
    public string UsingSpanWithStackAlloc()
    {
        ReadOnlySpan<char> input = Input;
        Span<char> buffer = stackalloc char[5];
        input[..5].ToUpperInvariant(buffer);
        return new string(buffer);
    }
}

// Program.cs
class Program
{
    static void Main(string[] args)
    {
        var summary = BenchmarkRunner.Run<StringBenchmarks>();
    }
}
```

## 集合性能

```csharp
// 用合适的集合类型
public class CollectionExamples
{
    // 快速查找：Dictionary 优于 List
    private readonly Dictionary<int, Product> _productsById = new();

    // HashSet 存唯一项
    private readonly HashSet<string> _processedIds = new();

    // 只读数据用 Frozen 集合（.NET 8）
    private static readonly FrozenDictionary<string, int> StatusCodes =
        new Dictionary<string, int>
        {
            ["Active"] = 1,
            ["Inactive"] = 0
        }.ToFrozenDictionary();

    // 已知数量时预分配
    public List<Product> CreateProducts(int count)
    {
        var products = new List<Product>(count); // 预分配
        for (int i = 0; i < count; i++)
        {
            products.Add(new Product { Id = i });
        }
        return products;
    }

    // 数组操作用 Span
    public int SumArray(int[] numbers)
    {
        return Sum(numbers.AsSpan());
    }

    private static int Sum(ReadOnlySpan<int> numbers)
    {
        int total = 0;
        foreach (var n in numbers)
            total += n;
        return total;
    }
}
```

## LINQ 优化

```csharp
public class LinqOptimizations
{
    // 避免多次枚举
    public void BadExample(IEnumerable<int> numbers)
    {
        if (numbers.Any())
        {
            var first = numbers.First(); // 再次枚举
            var count = numbers.Count(); // 再次枚举
        }
    }

    public void GoodExample(IEnumerable<int> numbers)
    {
        var list = numbers.ToList(); // 只枚举一次
        if (list.Count > 0)
        {
            var first = list[0];
            var count = list.Count;
        }
    }

    // 用合适的 LINQ 方法
    public bool HasActiveUsers(List<User> users)
    {
        return users.Any(u => u.IsActive); // 优于 Count() > 0
    }

    // 避免不必要的 ToList()
    public IEnumerable<Product> GetExpensiveProducts(IEnumerable<Product> products)
    {
        return products.Where(p => p.Price > 100); // 延迟执行
    }

    // 尽早用 Select 投影
    public List<string> GetProductNames(IEnumerable<Product> products)
    {
        return products
            .Where(p => p.IsActive)
            .Select(p => p.Name) // 尽早投影
            .ToList();
    }
}
```

## 响应缓存和压缩

```csharp
// Program.cs
builder.Services.AddResponseCaching();
builder.Services.AddResponseCompression(options =>
{
    options.EnableForHttps = true;
    options.Providers.Add<BrotliCompressionProvider>();
    options.Providers.Add<GzipCompressionProvider>();
});

app.UseResponseCompression();
app.UseResponseCaching();

// 带缓存的端点
app.MapGet("/api/products", async (ProductService service) =>
{
    var products = await service.GetAllAsync();
    return Results.Ok(products);
})
.CacheOutput(policy => policy.Expire(TimeSpan.FromMinutes(5)));
```

## 数据库查询优化

```csharp
public class OptimizedQueries(AppDbContext context)
{
    // 只读查询用 AsNoTracking
    public async Task<List<ProductDto>> GetProductsAsync(CancellationToken ct)
    {
        return await context.Products
            .AsNoTracking()
            .Select(p => new ProductDto
            {
                Id = p.Id,
                Name = p.Name,
                Price = p.Price
            })
            .ToListAsync(ct);
    }

    // 用 Include 避免 N+1 查询
    public async Task<List<Order>> GetOrdersWithItemsAsync(CancellationToken ct)
    {
        return await context.Orders
            .Include(o => o.OrderItems)
                .ThenInclude(oi => oi.Product)
            .AsNoTracking()
            .ToListAsync(ct);
    }

    // 重复查询用编译查询
    private static readonly Func<AppDbContext, int, Task<Product?>> GetProductById =
        EF.CompileAsyncQuery((AppDbContext ctx, int id) =>
            ctx.Products.FirstOrDefault(p => p.Id == id));

    public Task<Product?> GetProductOptimizedAsync(int id)
    {
        return GetProductById(context, id);
    }

    // 分页
    public async Task<PagedResult<ProductDto>> GetPagedAsync(
        int page,
        int pageSize,
        CancellationToken ct)
    {
        var query = context.Products.AsNoTracking();

        var total = await query.CountAsync(ct);

        var items = await query
            .OrderBy(p => p.Name)
            .Skip((page - 1) * pageSize)
            .Take(pageSize)
            .Select(p => new ProductDto
            {
                Id = p.Id,
                Name = p.Name,
                Price = p.Price
            })
            .ToListAsync(ct);

        return new PagedResult<ProductDto>(items, total, page, pageSize);
    }
}
```

## 源生成器和 AOT

```csharp
// 为 Native AOT 准备
using System.Text.Json.Serialization;

[JsonSerializable(typeof(ProductDto))]
[JsonSerializable(typeof(List<ProductDto>))]
internal partial class AppJsonSerializerContext : JsonSerializerContext
{
}

// API 中使用
app.MapGet("/api/products", async (ProductService service) =>
{
    var products = await service.GetAllAsync();
    return Results.Json(products, AppJsonSerializerContext.Default.ListProductDto);
});

// AOT 的 .csproj 配置
<PropertyGroup>
    <PublishAot>true</PublishAot>
    <InvariantGlobalization>true</InvariantGlobalization>
    <JsonSerializerIsReflectionEnabledByDefault>false</JsonSerializerIsReflectionEnabledByDefault>
</PropertyGroup>
```

## 内存分析提示

```csharp
// 避免值类型装箱
public void AvoidBoxing()
{
    // 不好：装箱
    object obj = 42;

    // 好：用泛型
    void Print<T>(T value) => Console.WriteLine(value);
    Print(42); // 无装箱
}

// 小且不可变数据用结构体
public readonly struct Point(int x, int y)
{
    public int X { get; } = x;
    public int Y { get; } = y;
}

// 避免循环中拼接字符串
public string BuildString(List<string> items)
{
    var builder = new StringBuilder();
    foreach (var item in items)
    {
        builder.Append(item);
    }
    return builder.ToString();
}
```

## 快速参考

| 优化方式 | 场景 | 优势 |
|----------|------|------|
| `Span<T>` | 数组/字符串操作 | 零分配 |
| `ArrayPool<T>` | 临时缓冲区 | 减 GC 压力 |
| `ValueTask<T>` | 频繁同步路径 | 更少分配 |
| `ConfigureAwait(false)` | 库代码 | 避免上下文捕获 |
| Frozen 集合 | 静态只读数据 | 更快查找 |
| `AsNoTracking()` | 只读查询 | 更好 EF 性能 |
| 对象池化 | 重量级对象 | 复用实例 |
| 响应缓存 | 静态响应 | 减服务器负载 |
| Native AOT | 启动时间关键 | 更快冷启动 |