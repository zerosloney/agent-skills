# 现代 C# 模式

## 文件范围命名空间和主构造函数

```csharp
namespace MyApp.Domain;

// 主构造函数 (C# 12)
public class ProductService(IProductRepository repository, ILogger<ProductService> logger)
{
    public async Task<Product?> GetByIdAsync(int id, CancellationToken ct = default)
    {
        logger.LogInformation("正在获取产品 {ProductId}", id);
        return await repository.GetByIdAsync(id, ct);
    }
}

// 带主构造函数的 Record
public record Product(int Id, string Name, decimal Price)
{
    public bool IsExpensive => Price > 100m;
}
```

## Record 类型和模式匹配

```csharp
// 不可变 Record
public record Customer(int Id, string Name, string Email);

// 带验证的 Record
public record OrderRequest(int ProductId, int Quantity)
{
    public OrderRequest : this(ProductId, Quantity)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(Quantity);
    }
}

// 用 Record 做模式匹配
public decimal CalculateDiscount(Customer customer, Order order) => customer switch
{
    { Id: > 1000 } => order.Total * 0.2m,          // 优质客户
    { Name: "VIP" } => order.Total * 0.3m,          // VIP
    _ when order.Total > 500 => order.Total * 0.1m, // 大额订单
    _ => 0m
};

// 列表模式 (C# 11+)
public string DescribeItems(int[] items) => items switch
{
    [] => "空",
    [var single] => $"单个项目: {single}",
    [var first, .., var last] => $"多个项目，从 {first} 到 {last}",
    _ => "未知"
};
```

## 可空引用类型

```csharp
#nullable enable

public class UserService
{
    // 非可空参数和返回类型
    public User CreateUser(string email, string name)
    {
        ArgumentNullException.ThrowIfNull(email);
        ArgumentNullException.ThrowIfNull(name);

        return new User { Email = email, Name = name };
    }

    // 可空返回类型
    public User? FindUserByEmail(string? email)
    {
        if (string.IsNullOrWhiteSpace(email))
            return null;

        return _repository.Find(email);
    }

    // required 修饰符 (C# 11)
    public class User
    {
        public required string Email { get; init; }
        public required string Name { get; init; }
        public string? PhoneNumber { get; init; } // 可选
    }
}

// 空包容运算符 (谨慎使用)
var user = FindUserById(id)!; // 仅确定时使用

// 空合并赋值
_cache ??= new Dictionary<string, object>();
```

## 现代集合模式

```csharp
// 集合表达式 (C# 12)
int[] numbers = [1, 2, 3, 4, 5];
List<string> names = ["Alice", "Bob", "Charlie"];

// 展开运算符
int[] moreNumbers = [..numbers, 6, 7, 8];
string[] allNames = [..names, "David"];

// 只读集合
public IReadOnlyList<Product> Products { get; } = [product1, product2];

// 用 Frozen 集合提升性能
using System.Collections.Frozen;

private static readonly FrozenDictionary<string, int> StatusCodes =
    new Dictionary<string, int>
    {
        ["Active"] = 1,
        ["Inactive"] = 2,
        ["Pending"] = 3
    }.ToFrozenDictionary();
```

## 表达式体成员

```csharp
public class Product
{
    private decimal _price;

    // 表达式体属性
    public decimal Price
    {
        get => _price;
        init => _price = value > 0 ? value : throw new ArgumentException();
    }

    // 表达式体方法
    public decimal GetPriceWithTax(decimal taxRate) => _price * (1 + taxRate);

    // 表达式体构造函数 (带验证)
    public Product(string name) => Name = !string.IsNullOrWhiteSpace(name)
        ? name
        : throw new ArgumentException(nameof(name));

    public required string Name { get; init; }
}
```

## 字符串插值和原始字符串

```csharp
// 原始字符串字面量 (C# 11)
var json = """
    {
        "name": "Product",
        "price": 99.99,
        "available": true
    }
    """;

// 插值原始字符串
var productJson = $$"""
    {
        "id": {{product.Id}},
        "name": "{{product.Name}}",
        "price": {{product.Price}}
    }
    """;

// UTF-8 字符串字面量
ReadOnlySpan<byte> utf8 = "Hello"u8;
```

## 全局 Using 指令

```csharp
// GlobalUsings.cs
global using System;
global using System.Collections.Generic;
global using System.Linq;
global using System.Threading;
global using System.Threading.Tasks;
global using Microsoft.Extensions.Logging;
global using Microsoft.Extensions.DependencyInjection;
```

## 源生成器 (准备)

```csharp
// 用分部类做源生成器
public partial class UserRepository
{
    // 生成器在此添加方法
}

// 示例: JsonSerializer 源生成
using System.Text.Json.Serialization;

[JsonSerializable(typeof(Product))]
[JsonSerializable(typeof(List<Product>))]
internal partial class AppJsonContext : JsonSerializerContext
{
}

// 使用
var json = JsonSerializer.Serialize(product, AppJsonContext.Default.Product);
```

## 用 Record 实现可区分联合

```csharp
// Result 模式基类 Record
public abstract record Result<T>
{
    public record Success(T Value) : Result<T>;
    public record Failure(string Error) : Result<T>;
}

// 使用
public Result<User> GetUser(int id) =>
    _repository.Find(id) is User user
        ? new Result<User>.Success(user)
        : new Result<User>.Failure("User not found");

// 对结果做模式匹配
var message = GetUser(id) switch
{
    Result<User>.Success(var user) => $"找到: {user.Name}",
    Result<User>.Failure(var error) => $"错误: {error}",
    _ => "未知"
};
```

## 快速参考

| 特性 | C# 版本 | 示例 |
|------|---------|------|
| 文件范围命名空间 | C# 10 | `namespace MyApp;` |
| 主构造函数 | C# 12 | `class Service(ILogger logger)` |
| required 成员 | C# 11 | `public required string Name { get; init; }` |
| 原始字符串字面量 | C# 11 | `var s = """ 多行 """;` |
| 列表模式 | C# 11 | `[1, 2, .., var last]` |
| 集合表达式 | C# 12 | `int[] x = [1, 2, 3];` |
| Init-only 属性 | C# 9 | `public string Name { get; init; }` |
| Record 类型 | C# 9 | `record Person(string Name);` |
