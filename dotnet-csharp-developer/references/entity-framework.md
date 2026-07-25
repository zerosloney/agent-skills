# Entity Framework Core 模式

## DbContext 设置

```csharp
using Microsoft.EntityFrameworkCore;

public class AppDbContext(DbContextOptions<AppDbContext> options) : DbContext(options)
{
    public DbSet<Product> Products => Set<Product>();
    public DbSet<Category> Categories => Set<Category>();
    public DbSet<Order> Orders => Set<Order>();

    protected override void OnModelCreating(ModelBuilder modelBuilder)
    {
        base.OnModelCreating(modelBuilder);

        // 应用程序集配置
        modelBuilder.ApplyConfigurationsFromAssembly(typeof(AppDbContext).Assembly);

        // 全局查询过滤器
        modelBuilder.Entity<Product>()
            .HasQueryFilter(p => !p.IsDeleted);
    }
}

// 配置类（推荐）
public class ProductConfiguration : IEntityTypeConfiguration<Product>
{
    public void Configure(EntityTypeBuilder<Product> builder)
    {
        builder.ToTable("Products");

        builder.HasKey(p => p.Id);

        builder.Property(p => p.Name)
            .IsRequired()
            .HasMaxLength(200);

        builder.Property(p => p.Price)
            .HasPrecision(18, 2);

        builder.HasIndex(p => p.Sku)
            .IsUnique();

        // 关系配置
        builder.HasOne(p => p.Category)
            .WithMany(c => c.Products)
            .HasForeignKey(p => p.CategoryId)
            .OnDelete(DeleteBehavior.Restrict);
    }
}
```

## 实体模型

```csharp
// 基础实体
public abstract class BaseEntity
{
    public int Id { get; set; }
    public DateTime CreatedAt { get; set; }
    public DateTime? UpdatedAt { get; set; }
    public bool IsDeleted { get; set; }
}

// 产品实体
public class Product : BaseEntity
{
    public required string Name { get; set; }
    public required string Sku { get; set; }
    public decimal Price { get; set; }
    public string? Description { get; set; }

    // 导航属性
    public int CategoryId { get; set; }
    public Category Category { get; set; } = null!;

    public ICollection<OrderItem> OrderItems { get; set; } = [];
}

// 值对象（拥有类型）
public class Address
{
    public required string Street { get; init; }
    public required string City { get; init; }
    public required string Country { get; init; }
    public required string PostalCode { get; init; }
}

public class Order : BaseEntity
{
    public required string OrderNumber { get; set; }
    public Address ShippingAddress { get; set; } = null!;
}

// 拥有类型配置
builder.OwnsOne(o => o.ShippingAddress, address =>
{
    address.Property(a => a.Street).HasMaxLength(200);
    address.Property(a => a.City).HasMaxLength(100);
});
```

## 仓库模式

```csharp
public interface IRepository<T> where T : BaseEntity
{
    Task<T?> GetByIdAsync(int id, CancellationToken ct = default);
    Task<List<T>> GetAllAsync(CancellationToken ct = default);
    Task<T> AddAsync(T entity, CancellationToken ct = default);
    Task UpdateAsync(T entity, CancellationToken ct = default);
    Task DeleteAsync(int id, CancellationToken ct = default);
}

public class Repository<T>(AppDbContext context) : IRepository<T> where T : BaseEntity
{
    private readonly DbSet<T> _dbSet = context.Set<T>();

    public async Task<T?> GetByIdAsync(int id, CancellationToken ct = default)
    {
        return await _dbSet.FindAsync([id], cancellationToken: ct);
    }

    public async Task<List<T>> GetAllAsync(CancellationToken ct = default)
    {
        return await _dbSet.AsNoTracking().ToListAsync(ct);
    }

    public async Task<T> AddAsync(T entity, CancellationToken ct = default)
    {
        entity.CreatedAt = DateTime.UtcNow;
        await _dbSet.AddAsync(entity, ct);
        await context.SaveChangesAsync(ct);
        return entity;
    }

    public async Task UpdateAsync(T entity, CancellationToken ct = default)
    {
        entity.UpdatedAt = DateTime.UtcNow;
        _dbSet.Update(entity);
        await context.SaveChangesAsync(ct);
    }

    public async Task DeleteAsync(int id, CancellationToken ct = default)
    {
        var entity = await GetByIdAsync(id, ct);
        if (entity is not null)
        {
            entity.IsDeleted = true;
            await UpdateAsync(entity, ct);
        }
    }
}
```

## 查询优化

```csharp
public class ProductRepository(AppDbContext context)
{
    // 只读查询用 AsNoTracking
    public async Task<List<ProductDto>> GetProductsAsync(CancellationToken ct = default)
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

    // 关联数据（贪婪加载）
    public async Task<Product?> GetProductWithCategoryAsync(int id, CancellationToken ct = default)
    {
        return await context.Products
            .Include(p => p.Category)
            .FirstOrDefaultAsync(p => p.Id == id, ct);
    }

    // 分割查询处理集合导航
    public async Task<Order?> GetOrderWithItemsAsync(int id, CancellationToken ct = default)
    {
        return await context.Orders
            .Include(o => o.OrderItems)
                .ThenInclude(oi => oi.Product)
            .AsSplitQuery() // 防笛卡尔爆炸
            .FirstOrDefaultAsync(o => o.Id == id, ct);
    }

    // 过滤包含（.NET 5+）
    public async Task<Category?> GetCategoryWithActiveProducts(
        int id,
        CancellationToken ct = default)
    {
        return await context.Categories
            .Include(c => c.Products.Where(p => p.Price > 0))
            .FirstOrDefaultAsync(c => c.Id == id, ct);
    }

    // 投影查询提升性能
    public async Task<List<ProductSummaryDto>> GetProductSummariesAsync(
        CancellationToken ct = default)
    {
        return await context.Products
            .Where(p => !p.IsDeleted)
            .Select(p => new ProductSummaryDto
            {
                Id = p.Id,
                Name = p.Name,
                Price = p.Price,
                CategoryName = p.Category.Name,
                OrderCount = p.OrderItems.Count
            })
            .ToListAsync(ct);
    }
}
```

## 编译查询

```csharp
// 编译查询定义为静态字段
private static readonly Func<AppDbContext, int, CancellationToken, Task<Product?>>
    GetProductByIdCompiled = EF.CompileAsyncQuery(
        (AppDbContext context, int id, CancellationToken ct) =>
            context.Products
                .Include(p => p.Category)
                .FirstOrDefault(p => p.Id == id));

public async Task<Product?> GetProductByIdOptimized(int id, CancellationToken ct = default)
{
    return await GetProductByIdCompiled(context, id, ct);
}
```

## 批量操作

```csharp
public class BulkProductRepository(AppDbContext context)
{
    // 批量插入
    public async Task AddRangeAsync(List<Product> products, CancellationToken ct = default)
    {
        await context.Products.AddRangeAsync(products, ct);
        await context.SaveChangesAsync(ct);
    }

    // ExecuteUpdate 批量更新（.NET 7+）
    public async Task IncreasePricesAsync(decimal percentage, CancellationToken ct = default)
    {
        await context.Products
            .Where(p => !p.IsDeleted)
            .ExecuteUpdateAsync(
                setters => setters.SetProperty(p => p.Price, p => p.Price * (1 + percentage)),
                ct);
    }

    // ExecuteDelete 批量删除（.NET 7+）
    public async Task DeleteDiscontinuedAsync(CancellationToken ct = default)
    {
        await context.Products
            .Where(p => p.IsDeleted)
            .ExecuteDeleteAsync(ct);
    }
}
```

## 事务

```csharp
public class OrderService(AppDbContext context)
{
    public async Task<Order> CreateOrderAsync(CreateOrderDto dto, CancellationToken ct = default)
    {
        using var transaction = await context.Database.BeginTransactionAsync(ct);

        try
        {
            var order = new Order
            {
                OrderNumber = GenerateOrderNumber(),
                CreatedAt = DateTime.UtcNow
            };

            await context.Orders.AddAsync(order, ct);
            await context.SaveChangesAsync(ct);

            // 更新库存
            foreach (var item in dto.Items)
            {
                var product = await context.Products.FindAsync([item.ProductId], ct);
                if (product is null)
                    throw new InvalidOperationException($"产品 {item.ProductId} 未找到");

                product.Stock -= item.Quantity;
            }

            await context.SaveChangesAsync(ct);
            await transaction.CommitAsync(ct);

            return order;
        }
        catch
        {
            await transaction.RollbackAsync(ct);
            throw;
        }
    }
}
```

## 迁移

```bash
# 添加迁移
dotnet ef migrations add InitialCreate

# 更新数据库
dotnet ef database update

# 生成 SQL 脚本
dotnet ef migrations script

# 移除上次迁移（未应用时）
dotnet ef migrations remove

# 回滚到指定迁移
dotnet ef database update PreviousMigrationName
```

```csharp
// 编程应用迁移
public static async Task ApplyMigrationsAsync(IServiceProvider services)
{
    using var scope = services.CreateScope();
    var context = scope.ServiceProvider.GetRequiredService<AppDbContext>();
    await context.Database.MigrateAsync();
}
```

## 变更跟踪优化

```csharp
// 只读操作禁用变更跟踪
context.ChangeTracker.QueryTrackingBehavior = QueryTrackingBehavior.NoTracking;

// 附加实体更新，无需加载
public async Task UpdateProductPriceAsync(int id, decimal newPrice, CancellationToken ct = default)
{
    var product = new Product { Id = id };
    context.Products.Attach(product);
    product.Price = newPrice;
    context.Entry(product).Property(p => p.Price).IsModified = true;
    await context.SaveChangesAsync(ct);
}
```

## 拦截器（.NET 6+）

```csharp
public class AuditInterceptor : SaveChangesInterceptor
{
    public override ValueTask<InterceptionResult<int>> SavingChangesAsync(
        DbContextEventData eventData,
        InterceptionResult<int> result,
        CancellationToken ct = default)
    {
        if (eventData.Context is null)
            return base.SavingChangesAsync(eventData, result, ct);

        var entries = eventData.Context.ChangeTracker.Entries<BaseEntity>();

        foreach (var entry in entries)
        {
            if (entry.State == EntityState.Added)
                entry.Entity.CreatedAt = DateTime.UtcNow;
            else if (entry.State == EntityState.Modified)
                entry.Entity.UpdatedAt = DateTime.UtcNow;
        }

        return base.SavingChangesAsync(eventData, result, ct);
    }
}

// 注册拦截器
builder.Services.AddDbContext<AppDbContext>((sp, options) =>
{
    options.UseSqlServer(connectionString)
        .AddInterceptors(new AuditInterceptor());
});
```

## 快速参考

| 操作 | 方法 | 说明 |
|------|------|------|
| 只读查询 | `.AsNoTracking()` | 更好性能 |
| 贪婪加载 | `.Include()` | 加载关联数据 |
| 过滤包含 | `.Include(x => x.Items.Where(...))` | .NET 5+ |
| 分割查询 | `.AsSplitQuery()` | 避免笛卡尔爆炸 |
| 批量更新 | `.ExecuteUpdateAsync()` | .NET 7+ |
| 批量删除 | `.ExecuteDeleteAsync()` | .NET 7+ |
| 编译查询 | `EF.CompileAsyncQuery()` | 可复用查询 |
| 软删除 | 查询过滤器 | `HasQueryFilter()` |