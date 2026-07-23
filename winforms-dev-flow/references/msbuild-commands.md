# MSBuild 命令参考（.NET Framework WinForms）

> 加载时机：Step 5b MSBuild 构建。
> 目标运行时：.NET Framework 4.7.2，DevExpress 21.2。

---

## 查找 MSBuild.exe

> **推荐**：`vswhere` 动态探测，覆盖 Community / Professional / Enterprise / BuildTools 全部 VS 2022 版本。
> `vswhere` 不可用时降级注册表查询；两者都失败则抛错并提示安装 Build Tools。

### 动态探测（推荐，覆盖所有 VS 2022 版本）

```powershell
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
$msbuild = & $vswhere -latest -requires Microsoft.Component.MSBuild `
    -find "MSBuild\**\Bin\MSBuild.exe" 2>$null | Select-Object -First 1
if (-not $msbuild) {
    # 降级：注册表查询（兼容 "2022" 与 "17.0" 两种键名）
    $vs7 = Get-ItemProperty "HKLM:\SOFTWARE\Microsoft\VisualStudio\SxS\VS7" -ErrorAction SilentlyContinue
    $vsRoot = $vs7."2022"
    if (-not $vsRoot) { $vsRoot = $vs7."17.0" }
    if ($vsRoot) { $msbuild = Join-Path $vsRoot "MSBuild\Current\Bin\MSBuild.exe" }
}
if (-not $msbuild -or -not (Test-Path $msbuild)) {
    throw "未找到 MSBuild.exe。请安装 Visual Studio 2022（含 'MSBuild v17' 组件）或 Build Tools。下载：https://visualstudio.microsoft.com/downloads/#build-tools-for-visual-studio-2022"
}
```

### 硬编码路径（vswhere/注册表都失败时手动指定）

```powershell
$msbuild = "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe"
# 或 Professional / Enterprise / BuildTools（替换 edition 子目录）
```

---

## 构建命令

### .sln 构建（首选）

```powershell
& $msbuild "C:\Path\To\Project.sln" `
    /p:Configuration=Debug `
    /p:Platform="Any CPU" `
    /m /v:m /nr:false
```

### 单个 .csproj（无 .sln 时）

```powershell
& $msbuild "C:\Path\To\Project.csproj" `
    /p:Configuration=Debug `
    /p:Platform="Any CPU" `
    /tv:4.7.2 `
    /p:TargetFrameworkVersion="v4.7.2" `
    /m /v:m /nr:false
```

### 关键参数说明

| 参数 | 说明 |
|------|------|
| `/p:Configuration=Debug` | 构建配置；Release 时改为 Release |
| `/p:Platform="Any CPU"` | 平台名称含空格，必须引号包裹 |
| `/tv:4.7.2` |  ToolsVersion，匹配目标框架 |
| `/p:TargetFrameworkVersion="v4.7.2"` | 显式声明目标框架 |
| `/m` | 并行构建，加速 |
| `/v:m` | 详细程度 minimal（有错误时输出足够信息） |
| `/nr:false` | 允许节点复用（分布式构建，单机无影响但避免警告） |
| `/fl` | 生成 .binlog 文件，供 VS 打开排查（构建失败时加） |
| `/p:WarningLevel=0` | **不要用**—— suppression 会掩盖真实问题 |
| `/p:ContinueOnError=true` | **不要用**——错误不中断，MSBuild 失去验证意义 |

---

## 常见失败模式

### 1. "MSBuild.exe 找不到"

```powershell
# 检查是否已安装
Test-Path "C:\Program Files\Microsoft Visual Studio\2022\Community\MSBuild\Current\Bin\MSBuild.exe"

# 或使用 vswhere
$vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
& $vswhere -latest -requires Microsoft.Component.MSBuild -find "MSBuild\Current\Bin\MSBuild.exe"
```

### 2. "Platform 名称无效"

`Any CPU` 含空格，**必须引号包裹**。常见错误：

```powershell
# ❌ 错误：Platform 值未引号包裹
/p:Platform=Any CPU    # 只取到 "Any"

# ✅ 正确
/p:Platform="Any CPU"
```

### 3. "目标框架版本不匹配"

.csproj 中 `<TargetFrameworkVersion>v4.7.2</TargetFrameworkVersion>` 与 `/tv` 不一致时可能跳过部分引用检查。确保两者一致。

### 4. "DevExpress DLL 找不到"

```powershell
# 检查 HintPath
Select-String -Path "*.csproj" -Pattern "DevExpress" | Select-Object -First 5

# 若路径不存在，列出实际 DevExpress 安装位置
Get-ChildItem "C:\Program Files (x86)\DevExpress*" -Directory | Select-Object FullName
```

### 5. 构建通过但运行时报错

- 确认 `Copy Local = true`（DevExpress 程序集是否随 exe 部署）
- 确认 `app.config` 中 `DevExpress.XtraEditors.Controls.CustomEditor` 注册
- 确认皮肤名称在 `references/skin-theme.md` 列表内（v21.2 全称）

---

## 快速诊断脚本

```powershell
param(
    [string]$SlnPath,
    [string]$Config = "Debug",
    [string]$Platform = "Any CPU"
)

$vswhere = "C:\Program Files (x86)\Microsoft Visual Studio\Installer\vswhere.exe"
$msbuild = & $vswhere -latest -requires Microsoft.Component.MSBuild -find "MSBuild\Current\Bin\MSBuild.exe" -nologo

if (-not $msbuild) {
    Write-Error "MSBuild not found. Install Visual Studio Build Tools."
    exit 1
}

Write-Host "MSBuild: $msbuild"
Write-Host "Building: $SlnPath ($Config | $Platform)"

& $msbuild $SlnPath `
    /p:Configuration=$Config `
    /p:Platform="$Platform" `
    /tv:4.7.2 `
    /m /v:m /nr:false `
    /fl `
    /p:WarningLevel=3

if ($LASTEXITCODE -eq 0) {
    Write-Host "BUILD PASSED" -ForegroundColor Green
} else {
    Write-Host "BUILD FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
    Write-Host "Check .binlog with VS or msbuild /fl"
}