# Build all Roslyn analyzers so engine.py can run them as DLLs (fast path)
# instead of `dotnet run` (which re-JITs on every call).
# Run from the skill root:  powershell -File scripts/build-analyzers.ps1
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$analyzers = @(
    "csharp-ast-analyzer",
    "csharp-semantic-analyzer",
    "csharp-project-analyzer"
)
foreach ($name in $analyzers) {
    $proj = Join-Path $root "$name\$name.csproj"
    Write-Host "Building $name..." -NoNewline
    & dotnet build $proj -c Debug --nologo -v q 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-Host " OK" -ForegroundColor Green
    } else {
        Write-Host " FAILED (exit $LASTEXITCODE)" -ForegroundColor Red
        exit $LASTEXITCODE
    }
}
Write-Host "All analyzers built. engine.py will use the DLL fast path." -ForegroundColor Green
