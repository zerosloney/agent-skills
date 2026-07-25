# Blazor 模式

## 组件基础

```razor
@* ProductList.razor *@
@page "/products"
@inject IProductService ProductService
@inject NavigationManager Navigation

<PageTitle>Products</PageTitle>

<h1>产品列表</h1>

@if (products is null)
{
    <p><em>加载中...</em></p>
}
else if (!products.Any())
{
    <p>未找到产品。</p>
}
else
{
    <div class="product-grid">
        @foreach (var product in products)
        {
            <ProductCard Product="@product" OnClick="@(() => ViewDetails(product.Id))" />
        }
    </div>
}

@code {
    private List<ProductDto>? products;

    protected override async Task OnInitializedAsync()
    {
        products = await ProductService.GetAllAsync();
    }

    private void ViewDetails(int id)
    {
        Navigation.NavigateTo($"/products/{id}");
    }
}
```

## 组件参数

```razor
@* ProductCard.razor *@
<div class="card" @onclick="HandleClick">
    <img src="@Product.ImageUrl" alt="@Product.Name" />
    <h3>@Product.Name</h3>
    <p class="price">@Product.Price.ToString("C")</p>

    @if (ShowDescription)
    {
        <p>@Product.Description</p>
    }

    <CascadingValue Value="@Product">
        @ChildContent
    </CascadingValue>
</div>

@code {
    [Parameter, EditorRequired]
    public ProductDto Product { get; set; } = null!;

    [Parameter]
    public bool ShowDescription { get; set; }

    [Parameter]
    public EventCallback<int> OnClick { get; set; }

    [Parameter]
    public RenderFragment? ChildContent { get; set; }

    private async Task HandleClick()
    {
        await OnClick.InvokeAsync(Product.Id);
    }
}
```

## 表单处理验证

```razor
@* ProductForm.razor *@
@using System.ComponentModel.DataAnnotations

<EditForm Model="@model" OnValidSubmit="@HandleValidSubmit">
    <DataAnnotationsValidator />
    <ValidationSummary />

    <div class="form-group">
        <label>名称：</label>
        <InputText @bind-Value="model.Name" class="form-control" />
        <ValidationMessage For="@(() => model.Name)" />
    </div>

    <div class="form-group">
        <label>价格：</label>
        <InputNumber @bind-Value="model.Price" class="form-control" />
        <ValidationMessage For="@(() => model.Price)" />
    </div>

    <div class="form-group">
        <label>分类：</label>
        <InputSelect @bind-Value="model.CategoryId" class="form-control">
            <option value="">选择分类...</option>
            @foreach (var category in categories)
            {
                <option value="@category.Id">@category.Name</option>
            }
        </InputSelect>
        <ValidationMessage For="@(() => model.CategoryId)" />
    </div>

    <button type="submit" class="btn btn-primary" disabled="@isSaving">
        @(isSaving ? "保存中..." : "保存")
    </button>
</EditForm>

@code {
    [Parameter]
    public int? ProductId { get; set; }

    [Parameter]
    public EventCallback<ProductDto> OnSaved { get; set; }

    private ProductFormModel model = new();
    private List<CategoryDto> categories = [];
    private bool isSaving;

    protected override async Task OnInitializedAsync()
    {
        categories = await CategoryService.GetAllAsync();

        if (ProductId.HasValue)
        {
            var product = await ProductService.GetByIdAsync(ProductId.Value);
            if (product is not null)
            {
                model = new ProductFormModel
                {
                    Name = product.Name,
                    Price = product.Price,
                    CategoryId = product.CategoryId
                };
            }
        }
    }

    private async Task HandleValidSubmit()
    {
        isSaving = true;
        try
        {
            var product = ProductId.HasValue
                ? await ProductService.UpdateAsync(ProductId.Value, model)
                : await ProductService.CreateAsync(model);

            await OnSaved.InvokeAsync(product);
        }
        finally
        {
            isSaving = false;
        }
    }

    private class ProductFormModel
    {
        [Required, StringLength(200)]
        public string Name { get; set; } = string.Empty;

        [Required, Range(0.01, 999999.99)]
        public decimal Price { get; set; }

        [Required]
        public int CategoryId { get; set; }
    }
}
```

## 级联值状态管理

```razor
@* App.razor *@
<CascadingAuthenticationState>
    <CascadingValue Value="@appState">
        <Router AppAssembly="@typeof(App).Assembly">
            <Found Context="routeData">
                <RouteView RouteData="@routeData" DefaultLayout="@typeof(MainLayout)" />
            </Found>
        </Router>
    </CascadingValue>
</CascadingAuthenticationState>

@code {
    private AppState appState = new();
}

// AppState.cs
public class AppState
{
    public event Action? OnChange;

    private int _cartItemCount;
    public int CartItemCount
    {
        get => _cartItemCount;
        set
        {
            if (_cartItemCount != value)
            {
                _cartItemCount = value;
                NotifyStateChanged();
            }
        }
    }

    private void NotifyStateChanged() => OnChange?.Invoke();
}

// 级联值
@code {
    [CascadingParameter]
    public AppState AppState { get; set; } = null!;

    protected override void OnInitialized()
    {
        AppState.OnChange += StateHasChanged;
    }

    public void Dispose()
    {
        AppState.OnChange -= StateHasChanged;
    }
}
```

## JavaScript 互操作

```razor
@inject IJSRuntime JS
@implements IAsyncDisposable

<div @ref="mapElement" style="height: 400px;"></div>

@code {
    private ElementReference mapElement;
    private IJSObjectReference? module;
    private IJSObjectReference? mapInstance;

    protected override async Task OnAfterRenderAsync(bool firstRender)
    {
        if (firstRender)
        {
            // 导入 JS 模块
            module = await JS.InvokeAsync<IJSObjectReference>(
                "import", "./js/mapComponent.js");

            // 初始化地图
            mapInstance = await module.InvokeAsync<IJSObjectReference>(
                "initializeMap", mapElement);
        }
    }

    public async Task SetLocationAsync(double lat, double lng)
    {
        if (mapInstance is not null)
        {
            await mapInstance.InvokeVoidAsync("setLocation", lat, lng);
        }
    }

    async ValueTask IAsyncDisposable.DisposeAsync()
    {
        if (mapInstance is not null)
            await mapInstance.DisposeAsync();

        if (module is not null)
            await module.DisposeAsync();
    }
}
```

```javascript
// wwwroot/js/mapComponent.js
export function initializeMap(element) {
    const map = new Map(element);
    return {
        setLocation: (lat, lng) => {
            map.setView([lat, lng], 13);
        }
    };
}
```

## 组件生命周期

```razor
@implements IDisposable

@code {
    protected override void OnInitialized()
    {
        // 组件初始化调用
        // 非异步初始化
    }

    protected override async Task OnInitializedAsync()
    {
        // 组件初始化调用
        // 异步初始化（API 调用）
        await LoadDataAsync();
    }

    protected override void OnParametersSet()
    {
        // 参数设置调用
        // 响应参数变化
    }

    protected override async Task OnParametersSetAsync()
    {
        // OnParametersSet 异步版本
        await ValidateParametersAsync();
    }

    protected override bool ShouldRender()
    {
        // 返回 false 阻止重渲染
        return true;
    }

    protected override void OnAfterRender(bool firstRender)
    {
        // 组件渲染后调用
        // firstRender 首次渲染 true
        if (firstRender)
        {
            // 一次性设置
        }
    }

    protected override async Task OnAfterRenderAsync(bool firstRender)
    {
        // 异步版本——JS 互操作
        if (firstRender)
        {
            await InitializeJavaScriptAsync();
        }
    }

    public void Dispose()
    {
        // 清理资源
        timer?.Dispose();
    }
}
```

## 认证

```razor
@* LoginDisplay.razor *@
<AuthorizeView>
    <Authorized>
        <span>你好，@context.User.Identity?.Name！</span>
        <button @onclick="LogOut">退出登录</button>
    </Authorized>
    <NotAuthorized>
        <a href="authentication/login">登录</a>
    </NotAuthorized>
</AuthorizeView>

@code {
    [Inject]
    private NavigationManager Navigation { get; set; } = null!;

    private void LogOut()
    {
        Navigation.NavigateTo("authentication/logout");
    }
}

@* 保护页面 *@
@page "/admin"
@attribute [Authorize(Roles = "Admin")]

<h1>管理面板</h1>

@* 按认证条件渲染 *@
<AuthorizeView Roles="Admin">
    <Authorized>
        <button>全部删除</button>
    </Authorized>
</AuthorizeView>
```

## 错误边界

```razor
<ErrorBoundary>
    <ChildContent>
        <ProductList />
    </ChildContent>
    <ErrorContent Context="exception">
        <div class="alert alert-danger">
            <h4>发生错误</h4>
            <p>@exception.Message</p>
            <button @onclick="RecoverAsync">重试</button>
        </div>
    </ErrorContent>
</ErrorBoundary>

@code {
    private ErrorBoundary? errorBoundary;

    protected override void OnParametersSet()
    {
        errorBoundary?.Recover();
    }

    private async Task RecoverAsync()
    {
        errorBoundary?.Recover();
        await LoadDataAsync();
    }
}
```

## 大型列表虚拟化

```razor
@using Microsoft.AspNetCore.Components.Web.Virtualization

<Virtualize Items="@products" Context="product">
    <div class="product-item">
        <h3>@product.Name</h3>
        <p>@product.Price.ToString("C")</p>
    </div>
</Virtualize>

@* 或用 ItemsProvider 懒加载 *@
<Virtualize ItemsProvider="@LoadProducts" Context="product">
    <ItemContent>
        <ProductCard Product="@product" />
    </ItemContent>
    <Placeholder>
        <div class="loading-skeleton"></div>
    </Placeholder>
</Virtualize>

@code {
    private async ValueTask<ItemsProviderResult<ProductDto>> LoadProducts(
        ItemsProviderRequest request)
    {
        var products = await ProductService.GetPageAsync(
            request.StartIndex,
            request.Count);

        var totalCount = await ProductService.GetCountAsync();

        return new ItemsProviderResult<ProductDto>(products, totalCount);
    }
}
```

## SignalR 集成

```csharp
// Program.cs
builder.Services.AddScoped<NotificationService>();

// NotificationService.cs
public class NotificationService : IAsyncDisposable
{
    private HubConnection? _hubConnection;

    public async Task InitializeAsync(string hubUrl)
    {
        _hubConnection = new HubConnectionBuilder()
            .WithUrl(hubUrl)
            .WithAutomaticReconnect()
            .Build();

        _hubConnection.On<string>("ReceiveNotification", notification =>
        {
            OnNotificationReceived?.Invoke(notification);
        });

        await _hubConnection.StartAsync();
    }

    public event Action<string>? OnNotificationReceived;

    public async ValueTask DisposeAsync()
    {
        if (_hubConnection is not null)
            await _hubConnection.DisposeAsync();
    }
}
```

```razor
@inject NotificationService NotificationService
@implements IDisposable

@if (!string.IsNullOrEmpty(lastNotification))
{
    <div class="notification">@lastNotification</div>
}

@code {
    private string? lastNotification;

    protected override async Task OnInitializedAsync()
    {
        NotificationService.OnNotificationReceived += HandleNotification;
        await NotificationService.InitializeAsync("/notificationHub");
    }

    private void HandleNotification(string notification)
    {
        lastNotification = notification;
        StateHasChanged();
    }

    public void Dispose()
    {
        NotificationService.OnNotificationReceived -= HandleNotification;
    }
}
```

## 快速参考

| 特性 | 使用场景 | 说明 |
|------|----------|------|
| `@page` | 路由定义 | 支持多路由 |
| `@inject` | 依赖注入 | 或用 `[Inject]` 属性 |
| `@bind` | 双向绑定 | 组件用 `@bind-Value` |
| `[Parameter]` | 组件输入 | 必要时用 `[EditorRequired]` |
| `EventCallback` | 组件事件 | 类型安全回调 |
| `RenderFragment` | 子内容 | 灵活布局 |
| `CascadingValue` | 共享状态 | 自动传给子组件 |
| `AuthorizeView` | 条件认证 UI | 或用 `@attribute [Authorize]` |
| `ErrorBoundary` | 错误处理 | 捕获渲染异常 |
| `Virtualize` | 大型列表 | 性能优化 |