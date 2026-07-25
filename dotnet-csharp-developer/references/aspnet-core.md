# ASP.NET Core 模式

## Minimal API 设置

```csharp
// Program.cs
using Microsoft.EntityFrameworkCore;

var builder = WebApplication.CreateBuilder(args);

// 注册服务
builder.Services.AddDbContext<AppDbContext>(options =>
    options.UseSqlServer(builder.Configuration.GetConnectionString("Default")));

builder.Services.AddScoped<IProductRepository, ProductRepository>();
builder.Services.AddScoped<ProductService>();

builder.Services.AddEndpointsApiExplorer();
builder.Services.AddSwaggerGen();

var app = builder.Build();

// 中间件
if (app.Environment.IsDevelopment())
{
    app.UseSwagger();
    app.UseSwaggerUI();
}

app.UseHttpsRedirection();
app.UseAuthentication();
app.UseAuthorization();

// 端点
app.MapProductEndpoints();

app.Run();
```

## Minimal API 端点和路由组

```csharp
public static class ProductEndpoints
{
    public static void MapProductEndpoints(this IEndpointRouteBuilder app)
    {
        var group = app.MapGroup("/api/products")
            .WithTags("Products")
            .RequireAuthorization();

        group.MapGet("/", GetAllProducts)
            .WithName("GetProducts")
            .Produces<List<ProductDto>>();

        group.MapGet("/{id:int}", GetProductById)
            .WithName("GetProduct")
            .Produces<ProductDto>()
            .Produces(404);

        group.MapPost("/", CreateProduct)
            .Produces<ProductDto>(201)
            .ProducesValidationProblem();

        group.MapPut("/{id:int}", UpdateProduct)
            .Produces(204)
            .Produces(404);

        group.MapDelete("/{id:int}", DeleteProduct)
            .Produces(204)
            .Produces(404);
    }

    private static async Task<IResult> GetAllProducts(
        ProductService service,
        CancellationToken ct)
    {
        var products = await service.GetAllAsync(ct);
        return Results.Ok(products);
    }

    private static async Task<IResult> GetProductById(
        int id,
        ProductService service,
        CancellationToken ct)
    {
        var product = await service.GetByIdAsync(id, ct);
        return product is not null
            ? Results.Ok(product)
            : Results.NotFound();
    }

    private static async Task<IResult> CreateProduct(
        CreateProductRequest request,
        ProductService service,
        CancellationToken ct)
    {
        var product = await service.CreateAsync(request, ct);
        return Results.CreatedAtRoute("GetProduct", new { id = product.Id }, product);
    }
}
```

## 端点过滤器

```csharp
// 验证过滤器
public class ValidationFilter<T> : IEndpointFilter where T : class
{
    public async ValueTask<object?> InvokeAsync(
        EndpointFilterInvocationContext context,
        EndpointFilterDelegate next)
    {
        var request = context.Arguments.OfType<T>().FirstOrDefault();
        if (request is null)
            return Results.BadRequest("无效请求");

        // FluentValidation 或自定义验证
        var validator = context.HttpContext.RequestServices
            .GetService<IValidator<T>>();

        if (validator is not null)
        {
            var result = await validator.ValidateAsync(request);
            if (!result.IsValid)
                return Results.ValidationProblem(result.ToDictionary());
        }

        return await next(context);
    }
}

// 使用
group.MapPost("/", CreateProduct)
    .AddEndpointFilter<ValidationFilter<CreateProductRequest>>();
```

## 依赖注入模式

```csharp
// 注册服务
public static class ServiceCollectionExtensions
{
    public static IServiceCollection AddApplicationServices(
        this IServiceCollection services)
    {
        // Transient：每次请求新实例
        services.AddTransient<IEmailService, EmailService>();

        // Scoped：每 HTTP 请求一个实例
        services.AddScoped<IProductRepository, ProductRepository>();
        services.AddScoped<ProductService>();

        // Singleton：应用生命周期一个实例
        services.AddSingleton<ICacheService, MemoryCacheService>();

        // 键化服务（C# 12，.NET 8）
        services.AddKeyedScoped<INotificationService, EmailNotificationService>("email");
        services.AddKeyedScoped<INotificationService, SmsNotificationService>("sms");

        return services;
    }
}

// 键化服务
public class NotificationController(
    [FromKeyedServices("email")] INotificationService emailService,
    [FromKeyedServices("sms")] INotificationService smsService)
{
    public async Task SendNotifications()
    {
        await emailService.SendAsync("Hello via email");
        await smsService.SendAsync("Hello via SMS");
    }
}
```

## Options 模式

```csharp
// appsettings.json
{
  "JwtSettings": {
    "Secret": "your-secret-key",
    "Issuer": "your-app",
    "Audience": "your-audience",
    "ExpiryMinutes": 60
  }
}

// Options 类
public class JwtSettings
{
    public required string Secret { get; init; }
    public required string Issuer { get; init; }
    public required string Audience { get; init; }
    public int ExpiryMinutes { get; init; }
}

// 注册
builder.Services.Configure<JwtSettings>(
    builder.Configuration.GetSection("JwtSettings"));

// 验证
builder.Services.AddOptions<JwtSettings>()
    .BindConfiguration("JwtSettings")
    .ValidateDataAnnotations()
    .ValidateOnStart();

// 使用
public class TokenService(IOptions<JwtSettings> options)
{
    private readonly JwtSettings _settings = options.Value;

    public string GenerateToken(User user)
    {
        // 用 _settings.Secret、_settings.Issuer 等
    }
}
```

## 自定义中间件

```csharp
// 中间件类
public class RequestLoggingMiddleware(RequestDelegate next, ILogger<RequestLoggingMiddleware> logger)
{
    public async Task InvokeAsync(HttpContext context)
    {
        var start = DateTime.UtcNow;

        try
        {
            await next(context);
        }
        finally
        {
            var elapsed = DateTime.UtcNow - start;
            logger.LogInformation(
                "请求 {Method} {Path} 在 {Elapsed}ms 内完成，状态码 {StatusCode}",
                context.Request.Method,
                context.Request.Path,
                elapsed.TotalMilliseconds,
                context.Response.StatusCode);
        }
    }
}

// 扩展方法
public static class MiddlewareExtensions
{
    public static IApplicationBuilder UseRequestLogging(this IApplicationBuilder app)
    {
        return app.UseMiddleware<RequestLoggingMiddleware>();
    }
}

// Program.cs
app.UseRequestLogging();
```

## 认证和授权

```csharp
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.IdentityModel.Tokens;
using System.Text;

// JWT 认证
builder.Services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
    .AddJwtBearer(options =>
    {
        var jwtSettings = builder.Configuration.GetSection("JwtSettings").Get<JwtSettings>()!;

        options.TokenValidationParameters = new TokenValidationParameters
        {
            ValidateIssuer = true,
            ValidateAudience = true,
            ValidateLifetime = true,
            ValidateIssuerSigningKey = true,
            ValidIssuer = jwtSettings.Issuer,
            ValidAudience = jwtSettings.Audience,
            IssuerSigningKey = new SymmetricSecurityKey(
                Encoding.UTF8.GetBytes(jwtSettings.Secret))
        };
    });

// 策略授权
builder.Services.AddAuthorization(options =>
{
    options.AddPolicy("AdminOnly", policy =>
        policy.RequireRole("Admin"));

    options.AddPolicy("RequireEmailVerified", policy =>
        policy.RequireClaim("email_verified", "true"));
});

// 端点
app.MapGet("/admin", () => "仅管理员可见")
    .RequireAuthorization("AdminOnly");
```

## 异常处理

```csharp
// 全局异常处理（.NET 8）
app.UseExceptionHandler(exceptionHandlerApp =>
{
    exceptionHandlerApp.Run(async context =>
    {
        var exceptionHandler = context.Features.Get<IExceptionHandlerFeature>();
        var exception = exceptionHandler?.Error;

        var logger = context.RequestServices.GetRequiredService<ILogger<Program>>();
        logger.LogError(exception, "未处理异常");

        var problemDetails = new ProblemDetails
        {
            Status = StatusCodes.Status500InternalServerError,
            Title = "错误",
            Detail = context.RequestServices.GetRequiredService<IHostEnvironment>()
                .IsDevelopment() ? exception?.Message : "请联系支持"
        };

        context.Response.StatusCode = StatusCodes.Status500InternalServerError;
        await context.Response.WriteAsJsonAsync(problemDetails);
    });
});
```

## 输出缓存（.NET 8）

```csharp
// 启用输出缓存
builder.Services.AddOutputCache(options =>
{
    options.AddBasePolicy(builder => builder.Expire(TimeSpan.FromSeconds(10)));

    options.AddPolicy("Products", builder => builder
        .Expire(TimeSpan.FromMinutes(5))
        .SetVaryByQuery("category", "page"));
});

app.UseOutputCache();

// 应用到端点
app.MapGet("/api/products", GetProducts)
    .CacheOutput("Products");
```

## 速率限制（.NET 7+）

```csharp
using System.Threading.RateLimiting;

builder.Services.AddRateLimiter(options =>
{
    options.GlobalLimiter = PartitionedRateLimiter.Create<HttpContext, string>(context =>
        RateLimitPartition.GetFixedWindowLimiter(
            partitionKey: context.User.Identity?.Name ?? context.Request.Headers.Host.ToString(),
            factory: partition => new FixedWindowRateLimiterOptions
            {
                AutoReplenishment = true,
                PermitLimit = 100,
                QueueLimit = 0,
                Window = TimeSpan.FromMinutes(1)
            }));
});

app.UseRateLimiter();
```

## 健康检查

```csharp
builder.Services.AddHealthChecks()
    .AddDbContextCheck<AppDbContext>()
    .AddUrlGroup(new Uri("https://api.example.com/health"), "外部 API");

app.MapHealthChecks("/health");
```

## 快速参考

| 模式 | 使用场景 | 生命周期 |
|------|----------|----------|
| Minimal API | 简单端点 | - |
| 路由组 | 组织端点 | - |
| 端点过滤器 | 验证、日志 | - |
| Scoped 服务 | 每请求状态 | HTTP 请求 |
| Singleton 服务 | 共享状态 | 应用程序 |
| Transient 服务 | 无状态操作 | 每次注入 |
| Options 模式 | 配置管理 | - |
| 输出缓存 | 性能优化 | 可配置 |
| 速率限制 | API 保护 | 每分区 |