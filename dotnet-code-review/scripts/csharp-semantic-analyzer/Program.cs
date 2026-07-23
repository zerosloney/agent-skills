/// C# Semantic Analyzer — 基于 Roslyn SemanticModel 的语义分析
/// 使用 AdhocWorkspace + CSharpCompilation（仅需 Microsoft.CodeAnalysis 4.5.0）
///
/// 支持增量编译：通过 --incremental 和 --cache-dir 参数复用 Compilation 对象
///
/// 输入: --files <.cs1.cs> <.cs2.cs> ... [--incremental] [--cache-dir <path>]
/// 输出: JSON 格式诊断列表

using System.Security.Cryptography;
using System.Text.Json;
using System.Collections.Generic;
using System.Text.Json.Serialization;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Text;

// ── 命令行参数解析 ──
var parsedArgs = ParseArguments(args);

var files = parsedArgs.Files.Where(File.Exists).ToArray();

// ── Solution-aware cross-project reference resolution ──
string? slnPath = parsedArgs.SolutionPath;
if (slnPath == null && parsedArgs.SolutionFull && files.Length > 0)
{
    var firstDir = Path.GetDirectoryName(Path.GetFullPath(files[0]));
    if (firstDir != null) slnPath = SolutionHelper.FindSolution(firstDir);
}
if (slnPath != null && File.Exists(slnPath))
{
    var solutionProjects = SolutionHelper.ParseSolution(slnPath);
    var depGraph = SolutionHelper.BuildDependencyGraph(solutionProjects);
    var matchedCsprojs = SolutionHelper.FindCsprojForFiles(files, solutionProjects);
    foreach (var csproj in matchedCsprojs)
    {
        var depDlls = SolutionHelper.ResolveTransitiveDeps(csproj, depGraph, solutionProjects, "net6.0");
        foreach (var dll in depDlls)
        {
            if (!parsedArgs.References.Contains(dll, StringComparer.OrdinalIgnoreCase))
                parsedArgs.References.Add(dll);
        }
    }
    if (parsedArgs.SolutionFull)
    {
        var allFiles = SolutionHelper.CollectAllSourceFiles(solutionProjects);
        files = allFiles.Where(File.Exists).ToArray();
        Console.Error.WriteLine($"[SOLUTION] Expanded to {files.Length} files from {solutionProjects.Count} projects");
    }
}

if (files.Length == 0)
{
    Console.Error.WriteLine("{\"error\": \"No valid .cs files provided\"}");
    return 1;
}

var incremental = parsedArgs.Incremental;
var cacheDir = parsedArgs.CacheDir;
var diagnostics = new List<SemanticDiagnostic>();
int CompilationErrorCount = 0;

try
{
    await AnalyzeFilesAsync(files, diagnostics, incremental, cacheDir);
}
catch (Exception ex)
{
    diagnostics.Add(new SemanticDiagnostic
    {
        File = files.FirstOrDefault() ?? "",
        Line = 1,
        Severity = "warning",
        Code = "INTERNAL_ERROR",
        Message = "Semantic analysis failed: " + ex.Message
    });
}

// Cache statistics (collected into static fields by AnalyzeFilesAsync).
var totalFiles = files.Length;
var cacheHits = IncrementalStats.CacheHits;
var cacheMisses = IncrementalStats.CacheMisses;
var cacheHitRate = totalFiles > 0
    ? Math.Round((double)cacheHits / totalFiles, 3)
    : 0;

var output = new
{
    tool = "csharp-semantic-analyzer",
    incremental_used = incremental && cacheDir != null,
    files_scanned = files.Intersect(diagnostics.Select(d => d.File)).Count(),
    compilation_error_count = CompilationErrorCount,
    cache_stats = new
    {
        total_files = totalFiles,
        cache_hits = cacheHits,
        cache_misses = cacheMisses,
        hit_rate = cacheHitRate,
        compilation_reused = IncrementalStats.CompilationReused,
    },
    diagnostics
};

// Category and suggestion fields are now populated per-diagnostic by the
// SemanticDiagnostic record (Category + Suggestion), so the Python engine
// layer no longer needs a hardcoded fallback for SEM_* rules.
Console.WriteLine(JsonSerializer.Serialize(output, new JsonSerializerOptions
{
    WriteIndented = false,
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
}));

return 0;

// ============================================================
// 增量编译核心逻辑
// ============================================================

/// <summary>
/// 使用增量编译进行语义分析
/// </summary>
async Task AnalyzeFilesAsync(string[] filePaths, List<SemanticDiagnostic> diagnostics,
    bool incremental, string? cacheDir)
{
    var validFiles = filePaths.Where(File.Exists).ToArray();
    if (validFiles.Length == 0) return;

    // ── 增量模式：尝试复用缓存的 Compilation ──
    CompilationCache? cache = null;
    if (incremental && cacheDir != null)
    {
        cache = await LoadCacheAsync(cacheDir);
    }

    using var workspace = new AdhocWorkspace();

    var projectInfo = ProjectInfo.Create(
        ProjectId.CreateNewId(),
        VersionStamp.Create(),
        "VirtualProject",
        "VirtualAssembly",
        LanguageNames.CSharp,
        compilationOptions: new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary)
    );

    var project = workspace.AddProject(projectInfo);

    // ── 计算文件哈希，检测变化 ──
    var fileHashes = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
    var changedFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    var unchangedFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    foreach (var file in validFiles)
    {
        var hash = await ComputeFileHashAsync(file);
        fileHashes[file] = hash;

        if (cache != null && cache.FileHashes.TryGetValue(file, out var cachedHash))
        {
            if (cachedHash == hash)
            {
                unchangedFiles.Add(file);
                continue;
            }
        }
        changedFiles.Add(file);
    }

    // ── 加载语法树（增量模式下只重新解析变化的文件）──
    var syntaxTrees = new Dictionary<string, SyntaxTree>(StringComparer.OrdinalIgnoreCase);
    var syntaxTreeList = new List<SyntaxTree>();

    foreach (var file in validFiles)
    {
        SyntaxTree tree;

        if (incremental && cache != null && unchangedFiles.Contains(file) &&
            cache.SyntaxTrees.TryGetValue(file, out var cachedTree))
        {
            // 复用缓存的语法树
            tree = cachedTree;
            IncrementalStats.CacheHits++;
        }
        else
        {
            // 重新解析
            var code = await File.ReadAllTextAsync(file);
            tree = CSharpSyntaxTree.ParseText(code, new CSharpParseOptions(LanguageVersion.Latest), path: file);
            IncrementalStats.CacheMisses++;
        }

        syntaxTrees[file] = tree;
        syntaxTreeList.Add(tree);
    }

    // ── 构建或复用 Compilation ──
    Compilation? compilation;

    if (incremental && cache != null && cache.Compilation != null &&
        changedFiles.Count == 0)
    {
        // 所有文件未变化，完全复用缓存的 Compilation
        compilation = cache.Compilation;
        IncrementalStats.CompilationReused = true;
    }
    else if (incremental && cache != null && cache.Compilation != null &&
             changedFiles.Count > 0 && changedFiles.Count < validFiles.Length)
    {
        // 部分文件变化，增量更新 Compilation
        compilation = await UpdateCompilationAsync(
            cache.Compilation, syntaxTrees, changedFiles, unchangedFiles);
    }
    else
    {
        // 全量构建 - 直接使用 CSharpCompilation
        var references = new List<MetadataReference>
        {
            MetadataReference.CreateFromFile(typeof(object).Assembly.Location),
            MetadataReference.CreateFromFile(typeof(Console).Assembly.Location),
        };

        // Add System.Linq / System.Collections / System.Runtime references so
        // LINQ extension methods (Where/Select/ToList/etc.) and collection
        // types (IEnumerable<T> / List<T>) are resolvable. Without these,
        // local var types declared via `var x = list.Where(...)` come back
        // empty and cross-statement data flow analysis cannot type locals.
        var trustedAssemblies = ((string?)AppContext.GetData("TRUSTED_PLATFORM_ASSEMBLIES")) ?? "";
        foreach (var asmPath in trustedAssemblies.Split(Path.PathSeparator))
        {
            var name = Path.GetFileNameWithoutExtension(asmPath);
            if (name is "System.Linq" or "System.Collections" or "System.Runtime" or
                       "netstandard" or "System.Core" or "System.Console" or "System.Linq.Expressions")
            {
                if (File.Exists(asmPath))
                    references.Add(MetadataReference.CreateFromFile(asmPath));
            }
        }

        // Add explicit reference DLLs from --references argument
        foreach (var refPath in parsedArgs.References)
        {
            if (File.Exists(refPath))
                references.Add(MetadataReference.CreateFromFile(refPath));
        }

        compilation = CSharpCompilation.Create(
            "VirtualAssembly",
            syntaxTrees: syntaxTreeList,
            references: references,
            options: new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary)
        );
    }

    if (compilation == null) return;

    var compDiags = compilation.GetDiagnostics().Where(d => d.Severity == DiagnosticSeverity.Error).ToList();
    CompilationErrorCount = compDiags.Count;
    foreach (var d in compDiags.Take(5))
    {
        Console.Error.WriteLine($"[DBG-COMP-ERR] {d}");
    }

    // ── 构建类型 -> 文件 映射（全项目）──
    var allTypes = new Dictionary<string, (INamedTypeSymbol type, string file)>(StringComparer.OrdinalIgnoreCase);

    foreach (var (file, tree) in syntaxTrees)
    {
        var model = compilation.GetSemanticModel(tree);
        var root = tree.GetRoot();
        CollectNamedTypes(model, root, file, allTypes);
    }

    // ── 遍历每个文件进行语义分析 ──
    foreach (var (filePath, tree) in syntaxTrees)
    {
        var semanticModel = compilation.GetSemanticModel(tree);
        AnalyzeNullable(semanticModel, tree, filePath, diagnostics);
        AnalyzeTypeGetType(semanticModel, tree, filePath, allTypes, diagnostics);
        AnalyzeBoxing(semanticModel, tree, filePath, diagnostics);
        AnalyzeStringConcatInLoop(semanticModel, tree, filePath, diagnostics);
        AnalyzeSealedOverride(semanticModel, tree, filePath, diagnostics);
        AnalyzeInterfaceImplementation(semanticModel, tree, filePath, compilation, allTypes, diagnostics);
        AnalyzeEfRules(semanticModel, tree, filePath, diagnostics);
        AnalyzeLinqMultipleEnumeration(semanticModel, tree, filePath, diagnostics);
        AnalyzeDisposePattern(semanticModel, tree, filePath, diagnostics);
        AnalyzeMutableStruct(semanticModel, tree, filePath, diagnostics);
        AnalyzeSemanticHints(semanticModel, tree, filePath, diagnostics);
        AnalyzeTaint(semanticModel, tree, filePath, diagnostics);
        AnalyzeCancellationToken(semanticModel, tree, filePath, diagnostics);
        AnalyzeOutRefNullAssignment(semanticModel, tree, filePath, diagnostics);
        AnalyzeAspNetRules(semanticModel, tree, filePath, allTypes, diagnostics);
AnalyzeRedundantBaseConstructorCall(semanticModel, tree, filePath, diagnostics);
        AnalyzeRedundantNameofType(semanticModel, tree, filePath, diagnostics);
        AnalyzeUseStringInterpolation(semanticModel, tree, filePath, diagnostics);
        AnalyzeUseCollectionInitializer(semanticModel, tree, filePath, diagnostics);
        AnalyzeUseCoalesceExpression(semanticModel, tree, filePath, diagnostics);
    }

    // 分析未使用的私有成员（跨文件）
    AnalyzeUnusedPrivateMembers(compilation, syntaxTrees, diagnostics);

    // ── 保存缓存 ──
    if (incremental && cacheDir != null)
    {
        await SaveCacheAsync(cacheDir, compilation, syntaxTrees, fileHashes);
    }
}

/// <summary>
/// 增量更新 Compilation - 只替换变化的语法树
/// </summary>
async Task<Compilation> UpdateCompilationAsync(
    Compilation existingCompilation,
    Dictionary<string, SyntaxTree> syntaxTrees,
    HashSet<string> changedFiles,
    HashSet<string> unchangedFiles)
{
    var csharpCompilation = existingCompilation as CSharpCompilation;
    if (csharpCompilation == null)
    {
        return existingCompilation;
    }

    // 获取现有的语法树
    var existingTrees = csharpCompilation.SyntaxTrees.ToDictionary(
        t => t.FilePath ?? "",
        t => t,
        StringComparer.OrdinalIgnoreCase);

    // 替换变化的语法树
    var newTrees = new List<SyntaxTree>();

    foreach (var (file, tree) in syntaxTrees)
    {
        if (changedFiles.Contains(file) || !existingTrees.ContainsKey(file))
        {
            newTrees.Add(tree);
        }
        else
        {
            newTrees.Add(existingTrees[file]);
        }
    }

    // 重建 Compilation
    var newCompilation = csharpCompilation.RemoveAllSyntaxTrees();

    foreach (var tree in newTrees)
    {
        newCompilation = newCompilation.AddSyntaxTrees(tree);
    }

    return newCompilation;
}

// ============================================================
// 缓存管理
// ============================================================

async Task<CompilationCache?> LoadCacheAsync(string cacheDir)
{
    try
    {
        var cachePath = Path.Combine(cacheDir, "semantic-cache.json");
        if (!File.Exists(cachePath))
            return null;

        var json = await File.ReadAllTextAsync(cachePath);
        var cacheData = JsonSerializer.Deserialize<CacheData>(json);

        if (cacheData == null)
            return null;

        // 检查缓存是否过期（24小时）
        if (DateTime.UtcNow - cacheData.Timestamp > TimeSpan.FromHours(24))
            return null;

        // 加载语法树
        var syntaxTrees = new Dictionary<string, SyntaxTree>(StringComparer.OrdinalIgnoreCase);
        foreach (var entry in cacheData.SyntaxTreePaths)
        {
            if (File.Exists(entry.Value))
            {
                var code = await File.ReadAllTextAsync(entry.Value);
                var tree = CSharpSyntaxTree.ParseText(code, path: entry.Key);
                syntaxTrees[entry.Key] = tree;
            }
        }

        return new CompilationCache
        {
            Compilation = null,
            SyntaxTrees = syntaxTrees,
            FileHashes = cacheData.FileHashes,
            Timestamp = cacheData.Timestamp
        };
    }
    catch
    {
        return null;
    }
}

async Task SaveCacheAsync(string cacheDir, Compilation compilation,
    Dictionary<string, SyntaxTree> syntaxTrees, Dictionary<string, string> fileHashes)
{
    try
    {
        Directory.CreateDirectory(cacheDir);

        var treePaths = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var (file, tree) in syntaxTrees)
        {
            var treePath = Path.Combine(cacheDir, $"tree_{Path.GetFileName(file)}.cs");
            await File.WriteAllTextAsync(treePath, tree.ToString());
            treePaths[file] = treePath;
        }

        var cacheData = new CacheData
        {
            FileHashes = fileHashes,
            SyntaxTreePaths = treePaths,
            Timestamp = DateTime.UtcNow
        };

        var cachePath = Path.Combine(cacheDir, "semantic-cache.json");
        var json = JsonSerializer.Serialize(cacheData, new JsonSerializerOptions
        {
            WriteIndented = true,
            PropertyNamingPolicy = JsonNamingPolicy.CamelCase
        });
        await File.WriteAllTextAsync(cachePath, json);
    }
    catch (Exception ex)
    {
        Console.Error.WriteLine($"Warning: Failed to save cache: {ex.Message}");
    }
}

// ============================================================
// 文件哈希计算
// ============================================================

async Task<string> ComputeFileHashAsync(string filePath)
{
    using var sha256 = SHA256.Create();
    using var stream = File.OpenRead(filePath);
    var hashBytes = await sha256.ComputeHashAsync(stream);
    return Convert.ToHexString(hashBytes).ToLowerInvariant();
}

// ============================================================
// 命令行参数解析
// ============================================================

ParsedArgs ParseArguments(string[] args)
{
    var result = new ParsedArgs();
    var i = 0;

    while (i < args.Length)
    {
        var arg = args[i];

        if (arg == "--incremental")
        {
            result = result with { Incremental = true };
            i++;
        }
        else if (arg == "--cache-dir" && i + 1 < args.Length)
        {
            result = result with { CacheDir = args[i + 1] };
            i += 2;
        }
        else if (arg == "--references")
        {
            i++;
            while (i < args.Length && !args[i].StartsWith("--"))
            {
                if (File.Exists(args[i]))
                    result.References.Add(args[i]);
                i++;
            }
        }
        else if (arg == "--files")
        {
            i++;
            while (i < args.Length && !args[i].StartsWith("--"))
            {
                result.Files.Add(args[i]);
                i++;
            }
        }
        else if (arg == "--file-list" && i + 1 < args.Length)
        {
            i++;
            var listPath = args[i];
            if (File.Exists(listPath))
            {
                foreach (var line in File.ReadAllLines(listPath))
                {
                    var trimmed = line.Trim();
                    if (trimmed.Length > 0 && File.Exists(trimmed))
                        result.Files.Add(trimmed);
                }
            }
            i++;
        }
        else if (arg == "--references-file" && i + 1 < args.Length)
        {
            i++;
            var listPath = args[i];
            if (File.Exists(listPath))
            {
                foreach (var line in File.ReadAllLines(listPath))
                {
                    var trimmed = line.Trim();
                    if (trimmed.Length > 0 && File.Exists(trimmed))
                        result.References.Add(trimmed);
                }
            }
            i++;
        }
        else if (arg == "--solution" && i + 1 < args.Length)
        {
            i++;
            var slnPath = args[i];
            if (slnPath.Equals("full", StringComparison.OrdinalIgnoreCase))
            {
                // --solution full: auto-discover and include all files
                result = result with { SolutionFull = true };
                // The actual .sln path will be discovered when we have the files
            }
            else
            {
                result = result with { SolutionPath = slnPath };
            }
            i++;
        }
        else if (!arg.StartsWith("--"))
        {
            result.Files.Add(arg);
            i++;
        }
        else
        {
            i++;
        }
    }

    return result;
}

// ============================================================
// 原有分析方法（保持不变）
// ============================================================

void AnalyzeUnusedPrivateMembers(Compilation compilation,
    Dictionary<string, SyntaxTree> syntaxTrees,
    List<SemanticDiagnostic> diagnostics)
{
    var referencedNames = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    foreach (var (file, tree) in syntaxTrees)
    {
        foreach (var id in tree.GetRoot().DescendantNodes().OfType<IdentifierNameSyntax>())
        {
            referencedNames.Add(id.Identifier.Text);
        }
    }

    foreach (var (file, tree) in syntaxTrees)
    {
        var semanticModel = compilation.GetSemanticModel(tree);
        var root = tree.GetRoot();

        foreach (var node in root.DescendantNodes())
        {
            ISymbol? memberSymbol = null;
            string memberName = "";
            SyntaxKind memberKind = node.Kind();

            if (node is FieldDeclarationSyntax fld)
            {
                if (!fld.Modifiers.Any(m => m.Kind() == SyntaxKind.PrivateKeyword)) continue;
                foreach (var vf in fld.Declaration.Variables)
                {
                    memberSymbol = semanticModel.GetDeclaredSymbol(vf);
                    memberName = vf.Identifier.Text;
                }
            }
            else if (node is MethodDeclarationSyntax mth)
            {
                if (!mth.Modifiers.Any(m => m.Kind() == SyntaxKind.PrivateKeyword)) continue;
                memberSymbol = semanticModel.GetDeclaredSymbol(mth);
                memberName = mth.Identifier.Text;
            }
            else if (node is PropertyDeclarationSyntax prop)
            {
                if (!prop.Modifiers.Any(m => m.Kind() == SyntaxKind.PrivateKeyword)) continue;
                memberSymbol = semanticModel.GetDeclaredSymbol(prop);
                memberName = prop.Identifier.Text;
            }
            else if (node is EventDeclarationSyntax evt)
            {
                if (!evt.Modifiers.Any(m => m.Kind() == SyntaxKind.PrivateKeyword)) continue;
                memberSymbol = semanticModel.GetDeclaredSymbol(evt);
                memberName = evt.Identifier.Text;
            }

            if (memberSymbol == null || string.IsNullOrEmpty(memberName)) continue;

            var refsInTree = tree.GetRoot()
                .DescendantNodes()
                .OfType<IdentifierNameSyntax>()
                .Where(id => id.Identifier.Text == memberName)
                .ToList();

            var nonDeclRefs = refsInTree.Count;

            if (memberKind == SyntaxKind.FieldDeclaration)
            {
                var assignments = tree.GetRoot()
                    .DescendantNodes()
                    .OfType<AssignmentExpressionSyntax>()
                    .Where(a => a.Left.ToString() == memberName)
                    .ToList();
                nonDeclRefs -= assignments.Count;
            }

            if (nonDeclRefs <= 1)
            {
                var loc = node.GetLocation();
                var kindStr = memberKind switch
                {
                    SyntaxKind.FieldDeclaration => "私有字段",
                    SyntaxKind.MethodDeclaration => "私有方法",
                    SyntaxKind.PropertyDeclaration => "私有属性",
                    SyntaxKind.EventDeclaration => "私有事件",
                    _ => "私有成员"
                };
                Add(diagnostics, file, loc,
                    "SEM_UNUSED_PRIVATE", "info",
                    $"{kindStr} {memberName} 在当前文件内未被使用",
                    $"如果不需要可移除，否则添加对外暴露的调用");
            }
        }
    }
}

void CollectNamedTypes(SemanticModel model, SyntaxNode root, string file,
    Dictionary<string, (INamedTypeSymbol, string)> allTypes)
{
    foreach (var node in root.DescendantNodes())
    {
        ISymbol? sym = null;
        if (node.Kind() == SyntaxKind.ClassDeclaration)
            sym = model.GetDeclaredSymbol((ClassDeclarationSyntax)node);
        else if (node.Kind() == SyntaxKind.InterfaceDeclaration)
            sym = model.GetDeclaredSymbol((InterfaceDeclarationSyntax)node);
        else if (node.Kind() == SyntaxKind.StructDeclaration)
            sym = model.GetDeclaredSymbol((StructDeclarationSyntax)node);
        else if (node.Kind() == SyntaxKind.EnumDeclaration)
            sym = model.GetDeclaredSymbol((EnumDeclarationSyntax)node);

        if (sym is INamedTypeSymbol namedType &&
            namedType.TypeKind != TypeKind.Error &&
            namedType.Name != "<Module>")
        {
            var key = namedType.ToDisplayString(SymbolDisplayFormat.FullyQualifiedFormat);
            if (!allTypes.ContainsKey(key))
                allTypes[key] = (namedType, file);
        }
    }
}

void AnalyzeNullable(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, List<SemanticDiagnostic> diagnostics)
{
    foreach (var node in syntaxTree.GetRoot().DescendantNodes())
    {
        if (node.Kind() == SyntaxKind.NullableType)
        {
            var nullableType = (NullableTypeSyntax)node;
            if (nullableType.Parent.Kind() == SyntaxKind.VariableDeclarator)
            {
                var declarator = (VariableDeclaratorSyntax)nullableType.Parent;
                if (declarator.Initializer?.Value.Kind() == SyntaxKind.NullLiteralExpression)
                {
                    var innerType = nullableType.ElementType.ToString();
                    Add(diagnostics, filePath, declarator.GetLocation(),
                        "SEM_NULLABLE_NULL_INIT", "warning",
                        "Nullable 引用类型 " + innerType + "? 初始化为 null，访问前需判空",
                        "使用 null 合并 ?? 或空条件运算符 ?.");
                }
            }
        }

        if (node is PostfixUnaryExpressionSyntax bang &&
            bang.OperatorToken.Kind() == SyntaxKind.ExclamationToken &&
            bang.Parent.Kind() == SyntaxKind.SimpleMemberAccessExpression)
        {
            var info = semanticModel.GetTypeInfo(bang);
            if (info.Type != null && !info.Type.IsValueType)
            {
                Add(diagnostics, filePath, bang.GetLocation(),
                    "SEM_NULLFORGIVING", "warning",
                    "对引用类型 " + info.Type.Name + " 使用 ! 压制警告，可能掩盖 NullReferenceException",
                    "在访问成员前进行 null 检查");
            }
        }

        if (node.Kind() == SyntaxKind.CoalesceExpression)
        {
            var coalescing = (BinaryExpressionSyntax)node;
            if (coalescing.Right.Kind() == SyntaxKind.SimpleMemberAccessExpression)
            {
                var leftType = semanticModel.GetTypeInfo(coalescing.Left).Type;
                if (leftType != null && !leftType.IsValueType)
                {
                    Add(diagnostics, filePath, coalescing.GetLocation(),
                        "SEM_COALESCE_NULL", "warning",
                        "?? 左侧 " + leftType.Name + " 可能为 null，右侧直接访问成员可能仍为空",
                        "在右侧也使用空条件运算符 (?.)");
                }
            }
        }
    }
}

void AnalyzeTypeGetType(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, Dictionary<string, (INamedTypeSymbol, string)> allTypes,
    List<SemanticDiagnostic> diagnostics)
{
    foreach (var node in syntaxTree.GetRoot().DescendantNodes())
    {
        if (node.Kind() == SyntaxKind.InvocationExpression)
        {
            var invoke = (InvocationExpressionSyntax)node;
            if (invoke.Expression.Kind() == SyntaxKind.SimpleMemberAccessExpression)
            {
                var member = (MemberAccessExpressionSyntax)invoke.Expression;
                if (member.Name.Identifier.Text == "GetType" &&
                    member.Expression.Kind() == SyntaxKind.IdentifierName)
                {
                    var id = (IdentifierNameSyntax)member.Expression;
                    if (id.Identifier.Text == "Type" && invoke.ArgumentList.Arguments.Count > 0)
                    {
                        var arg = invoke.ArgumentList.Arguments[0].Expression;

                        if (arg.Kind() == SyntaxKind.AddExpression)
                        {
                            Add(diagnostics, filePath, invoke.GetLocation(),
                                "SEM_TYPE_GETTYPE_CONCAT", "warning",
                                "Type.GetType 使用字符串拼接，存在类型解析注入风险",
                                "验证类型名称或使用白名单");
                        }

                        var methodSym = semanticModel.GetEnclosingSymbol(node.SpanStart) as IMethodSymbol;
                        if (methodSym != null)
                        {
                            var argStr = arg.ToString();
                            var paramNames = methodSym.Parameters.Select(p => p.Name).ToArray();
                            if (paramNames.Any(p => argStr.Contains(p, StringComparison.OrdinalIgnoreCase)))
                            {
                                Add(diagnostics, filePath, invoke.GetLocation(),
                                    "SEM_TYPE_GETTYPE_USERINPUT", "warning",
                                    "Type.GetType 接收参数 '" + argStr + "'，可能存在用户输入注入",
                                    "使用白名单验证类型名称");
                            }
                        }
                    }
                }
            }
        }
    }
}

void AnalyzeBoxing(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, List<SemanticDiagnostic> diagnostics)
{
    foreach (var node in syntaxTree.GetRoot().DescendantNodes())
    {
        if (node.Kind() == SyntaxKind.CastExpression)
        {
            var cast = (CastExpressionSyntax)node;
            if (cast.Type.Kind() == SyntaxKind.PredefinedType)
            {
                var predefined = (PredefinedTypeSyntax)cast.Type;
                if (predefined.Keyword.Kind() == SyntaxKind.ObjectKeyword)
                {
                    var exprType = semanticModel.GetTypeInfo(cast.Expression).Type;
                    if (exprType != null && exprType.IsValueType && exprType.SpecialType != SpecialType.System_Void)
                    {
                        Add(diagnostics, filePath, cast.GetLocation(),
                            "SEM_BOXING", "info",
                            "将值类型 " + exprType.Name + " 装箱为 object，产生堆分配",
                            "避免不必要的装箱或使用泛型重载");
                    }
                }
            }
        }
    }
}

void AnalyzeStringConcatInLoop(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, List<SemanticDiagnostic> diagnostics)
{
    // BP008: string += inside a loop produces O(n²) allocations; recommend
    // StringBuilder. The AST analyzer (no SemanticModel) only catches cases
    // where the RHS *looks* like a string (literal/interpolation/.ToString()).
    // It misses `s += i` (int operand) because it cannot infer that the LHS `s`
    // is typed `string`. This semantic check closes that gap by resolving the
    // declared type of the left operand via GetTypeInfo.
    foreach (var node in syntaxTree.GetRoot().DescendantNodes())
    {
        if (node.Kind() != SyntaxKind.AddAssignmentExpression) continue;
        var assign = (AssignmentExpressionSyntax)node;
        if (!IsInsideLoop(assign)) continue;

        // Resolve the compile-time type of the left operand (e.g. `s` in `s += i`).
        var leftType = semanticModel.GetTypeInfo(assign.Left).Type;
        if (leftType == null) continue;
        if (leftType.SpecialType != SpecialType.System_String) continue;

        Add(diagnostics, filePath, assign.GetLocation(),
            "LEGACY_BP008_string_concat_loop", "warning",
            "循环内字符串 += 触发 O(n²) 内存分配，推荐 StringBuilder",
            "使用 StringBuilder.Append 或 string.Create/Span 替代循环拼接");
    }
}

static bool IsInsideLoop(SyntaxNode node)
{
    return node.Ancestors().Any(a => a is ForEachStatementSyntax
                                     || a is ForStatementSyntax
                                     || a is WhileStatementSyntax
                                     || a is DoStatementSyntax);
}

void AnalyzeSealedOverride(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, List<SemanticDiagnostic> diagnostics)
{
    foreach (var node in syntaxTree.GetRoot().DescendantNodes())
    {
        if (node.Kind() == SyntaxKind.MethodDeclaration)
        {
            var method = (MethodDeclarationSyntax)node;
            var hasSealed = method.Modifiers.Any(m => m.Kind() == SyntaxKind.SealedKeyword);
            var hasOverride = method.Modifiers.Any(m => m.Kind() == SyntaxKind.OverrideKeyword);

            if (hasSealed && hasOverride)
            {
                var methodSym = semanticModel.GetDeclaredSymbol(method);
                if (methodSym?.OverriddenMethod != null)
                {
                    Add(diagnostics, filePath, method.GetLocation(),
                        "SEM_SEALED_OVERRIDE", "info",
                        "sealed override 方法 '" + methodSym.Name + "' 阻止进一步覆盖",
                        "如不需要防止覆盖，可移除 sealed");
                }
            }
        }

        if (node.Kind() == SyntaxKind.ClassDeclaration)
        {
            var cls = (ClassDeclarationSyntax)node;
            var hasSealed = cls.Modifiers.Any(m => m.Kind() == SyntaxKind.SealedKeyword);
            if (hasSealed && cls.BaseList?.Types.Count > 0)
            {
                Add(diagnostics, filePath, cls.GetLocation(),
                    "SEM_SEALED_CLASS_INHERITANCE", "warning",
                    "sealed class " + cls.Identifier.Text + " 不可被继承，BaseList 是多余的",
                    "移除 sealed class 的 BaseList 或移除 sealed");
            }
        }
    }
}

void AnalyzeInterfaceImplementation(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, Compilation compilation,
    Dictionary<string, (INamedTypeSymbol, string)> allTypes,
    List<SemanticDiagnostic> diagnostics)
{
    foreach (var node in syntaxTree.GetRoot().DescendantNodes())
    {
        if (node.Kind() == SyntaxKind.ClassDeclaration)
        {
            var classDecl = (ClassDeclarationSyntax)node;
            if (classDecl.BaseList == null) continue;

            var classSym = semanticModel.GetDeclaredSymbol(classDecl) as INamedTypeSymbol;
            if (classSym == null) continue;

            foreach (var baseType in classDecl.BaseList.Types)
            {
                var typeInfo = semanticModel.GetTypeInfo(baseType.Type);
                if (typeInfo.Type is INamedTypeSymbol iface && iface.TypeKind == TypeKind.Interface)
                {
                    var ifaceMembers = iface.GetMembers().OfType<IMethodSymbol>().ToList();
                    var classMembers = classSym.GetMembers().OfType<IMethodSymbol>().ToList();

                    foreach (var ifaceMember in ifaceMembers)
                    {
                        var impl = classMembers.FirstOrDefault(m =>
                            m.Name == ifaceMember.Name &&
                            m.Arity == ifaceMember.Arity &&
                            m.Parameters.Length == ifaceMember.Parameters.Length);

                        if (impl == null)
                        {
                            Add(diagnostics, filePath, baseType.GetLocation(),
                                "SEM_MISSING_INTERFACE_IMPL", "error",
                                "类 " + classSym.Name + " 实现接口 " + iface.Name + " 但未提供 " + ifaceMember.Name + " 方法",
                                "实现 " + iface.Name + "." + ifaceMember.Name);
                        }
                    }
                }
            }
        }
    }
}

void Add(List<SemanticDiagnostic> diagnostics, string file, Location location,
    string code, string severity, string message, string suggestion = "", string category = "")
{
    if (location == null) return;
    var lineSpan = location.GetLineSpan();
    diagnostics.Add(new SemanticDiagnostic
    {
        File = file,
        Line = lineSpan.StartLinePosition.Line + 1,
        Severity = severity,
        Code = code,
        Message = message,
        Suggestion = suggestion,
        Category = category
    });
}

void AnalyzeOutRefNullAssignment(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, List<SemanticDiagnostic> diagnostics)
{
    var root = syntaxTree.GetRoot();
    foreach (var method in root.DescendantNodes().OfType<BaseMethodDeclarationSyntax>())
    {
        if (method.Body == null) continue;
        foreach (var assign in method.Body.DescendantNodes().OfType<AssignmentExpressionSyntax>())
        {
            if (!assign.IsKind(SyntaxKind.SimpleAssignmentExpression)) continue;
            if (!assign.Right.IsKind(SyntaxKind.NullLiteralExpression)) continue;
            if (assign.Left is not IdentifierNameSyntax id) continue;
            var sym = semanticModel.GetSymbolInfo(id).Symbol;
            if (sym is IParameterSymbol p &&
                (p.RefKind == RefKind.Out || p.RefKind == RefKind.Ref))
            {
                Add(diagnostics, filePath, id.GetLocation(),
                    "SEM_OUTREF_NULL_SAFE", "info",
                    $"out/ref parameter '{p.Name}' assigned null — C# mandated idiom, not a defect.",
                    suggestion: "No action required", category: "reliability");
            }
        }
    }
}


// ============================================================
// CancellationToken propagation (ASYNC1004)
// ============================================================
void AnalyzeCancellationToken(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, List<SemanticDiagnostic> diagnostics)
{
    var root = syntaxTree.GetRoot();

    foreach (var method in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
    {
        // Skip non-async methods
        if (!method.Modifiers.Any(SyntaxKind.AsyncKeyword)) continue;
        // Skip methods with no body (abstract, extern, partial)
        if (method.Body == null) continue;
        // Skip event handlers (void return)
        if (method.ReturnType is PredefinedTypeSyntax pts && pts.Keyword.IsKind(SyntaxKind.VoidKeyword)) continue;

        // Check if method has await in body
        bool hasAwait = method.Body.DescendantNodes().OfType<AwaitExpressionSyntax>().Any();
        if (!hasAwait) continue;

        // Check if method already has CancellationToken parameter
        bool hasCt = method.ParameterList.Parameters
            .Any(p => p.Type != null &&
                (p.Type.ToString().EndsWith("CancellationToken") ||
                 p.Type.ToString().EndsWith("CancellationToken?")));
        if (hasCt) continue;

        // Check return type is Task/ValueTask (using SemanticModel)
        var returnTypeInfo = semanticModel.GetTypeInfo(method.ReturnType);
        var returnType = returnTypeInfo.Type;
        if (returnType == null) continue;

        var fullName = returnType.ToDisplayString();
        if (fullName == "System.Threading.Tasks.Task" ||
            fullName.StartsWith("System.Threading.Tasks.Task<") ||
            fullName == "System.Threading.Tasks.ValueTask" ||
            fullName.StartsWith("System.Threading.Tasks.ValueTask<"))
        {
            Add(diagnostics, filePath, method.Identifier.GetLocation(),
                "SEM_CANCELLATION_TOKEN", "warning",
                "async 方法缺少 CancellationToken 参数，客户端断开后请求无法取消",
                "添加 CancellationToken ct = default 参数，并传递给内部 async 调用");
        }
    }
}


// ============================================================
// EF Core rules (Layer 3b — Semantic Analyzer)
// ============================================================

void AnalyzeEfRules(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, List<SemanticDiagnostic> diagnostics)
{
    var root = syntaxTree.GetRoot();

    var efTerminalMethods = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "ToList", "ToListAsync", "FirstOrDefault", "FirstOrDefaultAsync",
        "SingleOrDefault", "SingleOrDefaultAsync", "Count", "CountAsync",
        "Any", "AnyAsync", "ToArray", "ToArrayAsync",
        "Find", "FindAsync"
    };

    var efQueryMethods = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "Where", "Find", "First", "Single", "OrderBy", "OrderByDescending",
        "Take", "Skip", "Select", "Include", "ThenInclude"
    };
    foreach (var invoke in root.DescendantNodes().OfType<InvocationExpressionSyntax>())
    {
        if (invoke.Expression is MemberAccessExpressionSyntax scMa &&
            (scMa.Name.Identifier.Text == "SaveChanges" || scMa.Name.Identifier.Text == "SaveChangesAsync"))
        {
            if (!IsDbContextMemberAccess(scMa, semanticModel)) continue;

            // Check if this call is inside a using statement with BeginTransaction
            if (!IsInsideTransactionUsing(invoke))
            {
                Add(diagnostics, filePath, invoke.GetLocation(),
                    "EF002", "warning",
                    "SaveChanges 未在显式事务中执行，部分失败时可能产生数据不一致",
                    "使用 using(var tx = ctx.Database.BeginTransaction()) { ... ctx.SaveChanges(); tx.Commit(); }");
            }

            // EF005: synchronous SaveChanges() inside an async method.
            // The async method already pays the state-machine cost; calling the
            // blocking SaveChanges() defeats it and risks thread-pool starvation
            // on the database I/O path. Only fires for the sync overload whose
            // name is exactly "SaveChanges" (no "Async" suffix).
            if (scMa.Name.Identifier.Text == "SaveChanges")
            {
                var enclosing = invoke.Ancestors().OfType<MethodDeclarationSyntax>().FirstOrDefault();
                if (enclosing != null &&
                    enclosing.Modifiers.Any(SyntaxKind.AsyncKeyword))
                {
                    Add(diagnostics, filePath, invoke.GetLocation(),
                        "EF005", "warning",
                        "async 方法内调用同步 SaveChanges()——阻塞线程池且浪费 async 状态机，应改用 SaveChangesAsync()",
                        "将 ctx.SaveChanges() 改为 await ctx.SaveChangesAsync()");
                }
            }
        }
    }

    // EF004: Read-only query missing AsNoTracking
    foreach (var invoke in root.DescendantNodes().OfType<InvocationExpressionSyntax>())
    {
        if (invoke.Expression is MemberAccessExpressionSyntax terminalMa)
        {
            string terminal = terminalMa.Name.Identifier.Text;
            // Terminal methods that materialize results (no further chaining)
            if (!efTerminalMethods.Contains(terminal)) continue;

            // Check if AsNoTracking appears anywhere in the same statement
            var statement = invoke.Ancestors().OfType<StatementSyntax>().FirstOrDefault();
            if (statement != null && statement.DescendantNodes()
                .OfType<MemberAccessExpressionSyntax>()
                .Any(ma => ma.Name.Identifier.Text == "AsNoTracking"))
            {
                continue; // explicitly no-tracking, no issue
            }

            // Heuristic: if the statement also contains Where/Find/Single/First/OrderBy,
            // it's likely a read-only query
            if (statement != null && statement.DescendantNodes()
                .OfType<MemberAccessExpressionSyntax>()
                .Any(ma => efQueryMethods.Contains(ma.Name.Identifier.Text)))
            {
                Add(diagnostics, filePath, invoke.GetLocation(),
                    "EF004", "info",
                    $"只读查询使用 {terminal}() 未加 AsNoTracking()，EF Core 会 unnecessarily 跟踪实体状态",
                    $"在查询链末尾添加 .AsNoTracking() 提升性能");
            }
        }
    }

    // EF006: DbContext registered as Singleton — thread-safety hazard.
    // A Singleton DbContext shared across concurrent requests corrupts its
    // internal change tracker and identity map. We only flag the explicit
    // `contextLifetime: ServiceLifetime.Singleton` named-argument form, which
    // is unambiguous. Positional ServiceLifetime arguments are skipped (we
    // cannot distinguish contextLifetime from optionsLifetime positionally).
    foreach (var invoke in root.DescendantNodes().OfType<InvocationExpressionSyntax>())
    {
        if (invoke.Expression is not MemberAccessExpressionSyntax dcMa) continue;
        if (dcMa.Name.Identifier.Text != "AddDbContext") continue;

        foreach (var arg in invoke.ArgumentList.Arguments)
        {
            // Match named argument: `contextLifetime: ServiceLifetime.Singleton`
            // or `contextLifetime: ServiceLifetime.Scoped` (Scoped is also wrong
            // for DbContext in most architectures, but we only flag Singleton
            // — the objectively broken case — to minimize false positives).
            if (arg.NameColon?.Name.Identifier.Text != "contextLifetime") continue;
            var argText = arg.ToString();
            if (argText.Contains("Singleton"))
            {
                Add(diagnostics, filePath, invoke.GetLocation(),
                    "EF006", "warning",
                    "DbContext 注册为 Singleton——跨并发请求共享同一实例会损坏 ChangeTracker/IdentityMap（DbContext 非线程安全）",
                    "使用默认的 Scoped 生命周期：services.AddDbContext<AppDbContext>(opt => opt.UseSqlServer(conn));");
                break; // one EF006 per AddDbContext call
            }
        }
    }

    // EF001: N+1 query — Include + terminal method inside a loop
    // Heuristic: if a loop body contains a DbSet access with .Include() that
    // ends in a terminal method (ToList, FirstOrDefault, etc.), each iteration
    // likely triggers a separate query.
    foreach (var loop in root.DescendantNodes().OfType<StatementSyntax>()
        .Where(s => s is ForEachStatementSyntax or ForStatementSyntax or WhileStatementSyntax or DoStatementSyntax))
    {
        var loopBody = loop is ForEachStatementSyntax fes ? fes.Statement :
                       loop is ForStatementSyntax fs ? fs.Statement :
                       loop is WhileStatementSyntax ws ? ws.Statement :
                       ((DoStatementSyntax)loop).Statement;
        if (loopBody == null) continue;

        foreach (var invoke in loopBody.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            if (invoke.Expression is not MemberAccessExpressionSyntax terminalMa) continue;
            string terminal = terminalMa.Name.Identifier.Text;
            if (!efTerminalMethods.Contains(terminal)) continue;

            // Check if the chain contains Include/ThenInclude by walking the
            // receiver expression: .FirstOrDefault(.Include(u => x).Where(...))
            // has Include inside an InvocationExpressionSyntax, not just MemberAccess.
            bool hasInclude = ChainContainsMethod(terminalMa, "Include") ||
                              ChainContainsMethod(terminalMa, "ThenInclude");
            if (!hasInclude) continue;

            Add(diagnostics, filePath, invoke.GetLocation(),
                "EF001", "warning",
                "循环内执行带 Include 的查询（" + terminal + "()），可能触发 N+1 查询问题",
                "将 Include 查询移出循环，或使用 .Select() 投影 + 批量预加载");
        }
    }

    // EF001 (CFG variant): generic N+1 — any DbSet query inside a loop body
    // (no Include required). This catches the common N+1 pattern where a
    // foreach over a materialized list triggers per-iteration DbSet lookups.
    // Uses Roslyn ControlFlowAnalysis to (a) confirm the loop body is reachable
    // (not a dead branch) and (b) leverage Roslyn's CFG for receiver resolution
    // across nested scopes. Falls back to syntax-only walk for unreachable code.
    AnalyzeEfNPlus1WithCfg(semanticModel, root, filePath, efTerminalMethods, diagnostics);
}

void AnalyzeEfNPlus1WithCfg(SemanticModel semanticModel, SyntaxNode root, string filePath,
    HashSet<string> efTerminalMethods, List<SemanticDiagnostic> diagnostics)
{
    foreach (var loop in root.DescendantNodes().OfType<StatementSyntax>()
        .Where(s => s is ForEachStatementSyntax or ForStatementSyntax or WhileStatementSyntax or DoStatementSyntax))
    {
        var loopBody = loop is ForEachStatementSyntax fes ? fes.Statement :
                       loop is ForStatementSyntax fs ? fs.Statement :
                       loop is WhileStatementSyntax ws ? ws.Statement :
                       ((DoStatementSyntax)loop).Statement;
        if (loopBody == null) continue;

        // CFG check: confirm the loop body is reachable. If the loop is inside
        // a block the CFG considers unreachable (e.g. after an unconditional
        // return/throw), skip to avoid false positives.
        var cfg = semanticModel.AnalyzeControlFlow(loop);
        if (cfg.StartPointIsReachable == false) continue;

        foreach (var invoke in loopBody.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            if (invoke.Expression is not MemberAccessExpressionSyntax terminalMa) continue;
            string terminal = terminalMa.Name.Identifier.Text;
            if (!efTerminalMethods.Contains(terminal)) continue;

            // Receiver must resolve to a DbSet<T>-typed expression.
            // We accept both:
            //   (a) a direct DbSet property access (ctx.Users)
            //   (b) a chain rooted at a DbSet (ctx.Orders.Where(...).ToList())
            if (!IsDbSetReceiver(terminalMa.Expression, semanticModel)) continue;

            // Skip if the chain already has Include/ThenInclude — that case is
            // handled by the heuristic above with a more specific message.
            if (ChainContainsMethod(terminalMa, "Include") ||
                ChainContainsMethod(terminalMa, "ThenInclude"))
                continue;

            Add(diagnostics, filePath, invoke.GetLocation(),
                "EF001", "warning",
                "循环内执行 DbSet 查询（" + terminal + "()），可能触发 N+1 查询问题",
                "将查询移出循环，或使用 .Include() / .Select() 投影 + 批量预加载");
        }
    }
}

/// <summary>
/// Returns true if <paramref name="expr"/> is a DbSet&lt;T&gt;-typed expression,
/// or is a query chain rooted at one.
///
/// Strategy: walk DOWN through any nested wrapping (MemberAccess/Invocation/
/// Parenthesized) until we find an expression whose semantic type is a
/// DbSet-or-IQueryable. We do this by checking each layer's type — for
/// `ctx.Orders.Where(...).ToList()` we test: receiver of terminalMa is
/// `ctx.Orders.Where(...).ToList()` (a call) → unwrap to the method chain
/// → check the type of the outermost receiver, which should be
/// `DbSet<Order>` (or `IQueryable<Order>`).
///
/// In practice: the OUTERMOST receiver in the chain (the part before the
/// first LINQ method like .Where/.Select/.ToList) is the DbSet access.
/// </summary>
static bool IsDbSetReceiver(ExpressionSyntax expr, SemanticModel semanticModel)
{
    // Walk down through any invocation/member-access/parenthesized wrappers
    // and test each layer's type. The first layer that resolves to a
    // DbSet-or-IQueryable is the chain root.
    ExpressionSyntax current = expr;
    ExpressionSyntax lastResolved = expr;
    int safety = 0;
    while (safety++ < 20)
    {
        // Unwrap invocation
        if (current is InvocationExpressionSyntax inv)
        {
            // Check type of the whole invocation result first (e.g. ToList() returns List<T>)
            var invType = semanticModel.GetTypeInfo(current).Type;
            if (invType != null && IsDbSetType(invType)) return true;
            // Then unwrap to the method chain root
            if (inv.Expression is MemberAccessExpressionSyntax invMa)
            {
                current = invMa.Expression;
                continue;
            }
            break;
        }
        // Unwrap parenthesized
        if (current is ParenthesizedExpressionSyntax paren)
        {
            current = paren.Expression;
            continue;
        }
        // For member access, check type of the access itself — `ctx.Orders`
        // has type `DbSet<Order>` even though `ctx` does not.
        if (current is MemberAccessExpressionSyntax ma)
        {
            var maType = semanticModel.GetTypeInfo(current).Type;
            if (maType != null && IsDbSetType(maType)) return true;
            // Not a DbSet, keep unwrapping to the left
            current = ma.Expression;
            continue;
        }
        // Identifier or other terminal: type is the identifier's type
        var idType = semanticModel.GetTypeInfo(current).Type;
        if (idType != null && IsDbSetType(idType)) return true;
        break;
    }

    // Final fallback: syntactic check on the outermost text.
    return LooksLikeDbSetAccessor(lastResolved.ToString());
}

static bool IsDbSetType(ITypeSymbol type)
{
    if (type.Name == "DbSet") return true;
    for (var current = type; current != null; current = current.BaseType)
    {
        if (current.Name == "DbSet") return true;
        if (current.OriginalDefinition?.Name == "DbSet`1") return true;
    }
    // Also accept IQueryable<T> as a strong indicator the chain is EF/LINQ.
    for (var current = type; current != null; current = current.BaseType)
    {
        if (current.Name == "IQueryable") return true;
        if (current.OriginalDefinition?.Name == "IQueryable`1") return true;
    }
    return false;
}

static bool LooksLikeDbSetAccessor(string text)
{
    // Heuristic for when type info is missing (e.g. unrelated assemblies):
    // require a two-segment accessor like "ctx.Users" / "_context.Orders".
    if (string.IsNullOrEmpty(text)) return false;
    if (text.Contains('(') || text.Contains('[')) return false;
    var parts = text.Split('.');
    if (parts.Length != 2) return false;
    var ctxName = parts[0];
    var propName = parts[1];
    return (ctxName is "ctx" or "db" or "context" or "_context")
        && !string.IsNullOrEmpty(propName)
        && char.IsUpper(propName[0]);
}

// ============================================================
// LINQ multiple-enumeration (P009) — cross-statement data flow
// ============================================================

void AnalyzeLinqMultipleEnumeration(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, List<SemanticDiagnostic> diagnostics)
{
    var root = syntaxTree.GetRoot();

    // Per-method analysis: the unit of "scope" for multi-enumeration is a
    // method body, since that's where local variables are introduced and
    // consumed.
    foreach (var method in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
    {
        if (method.Body == null) continue;
        AnalyzeLinqMultipleEnumerationInMethod(semanticModel, method, filePath, diagnostics);
    }

    // Property getters / expression-bodied properties also hold local state.
    foreach (var prop in root.DescendantNodes().OfType<PropertyDeclarationSyntax>())
    {
        if (prop.ExpressionBody != null)
        {
            // Expression-bodied property: scan the single expression.
            AnalyzeLinqMultipleEnumerationInExpression(semanticModel, prop.ExpressionBody.Expression, filePath, diagnostics);
        }
    }
}

void AnalyzeLinqMultipleEnumerationInMethod(SemanticModel semanticModel,
    MethodDeclarationSyntax method, string filePath, List<SemanticDiagnostic> diagnostics)
{
    var body = method.Body!;
    var dataFlow = semanticModel.AnalyzeDataFlow(body);
    if (!dataFlow.Succeeded) return;

    // Collect candidate local variables: ILocalSymbols whose type is a
    // deferred LINQ type (IEnumerable<T> / IQueryable<T> etc.).
    // DataFlowAnalysis doesn't expose a flat "all locals" list, so we walk
    // the body looking for VariableDeclaratorSyntax and resolve each to its
    // declared symbol.
    var candidates = new List<ILocalSymbol>();
    foreach (var decl in body.DescendantNodes().OfType<VariableDeclaratorSyntax>())
    {
        var local = semanticModel.GetDeclaredSymbol(decl) as ILocalSymbol;
        if (local == null) continue;
        if (local.Type == null) continue;
        if (!IsLikelyEnumerableType(local.Type)) continue;
        candidates.Add(local);
    }

    // Map: local symbol -> list of consumption statements (line of consumption).
    var consumptions = new Dictionary<ISymbol, List<Location>>(SymbolEqualityComparer.Default);
    foreach (var local in candidates)
    {
        consumptions[local] = new List<Location>();
    }

    // Walk all consumer points in the body.
    foreach (var node in body.DescendantNodes())
    {
        // Case 1: foreach (var x in <expr>) — the <expr> is a consumer.
        if (node is ForEachStatementSyntax fes)
        {
            var sym = semanticModel.GetSymbolInfo(fes.Expression).Symbol;
            // Sometimes it's an IMethodSymbol (GetEnumerator) — get the receiver
            // local from the InvocationExpression instead.
            if (sym is ILocalSymbol || sym is IParameterSymbol || sym is IFieldSymbol || sym is IPropertySymbol)
            {
                AddConsumption(consumptions, sym, fes.Expression.GetLocation());
            }
            else
            {
                // The expression is itself a method call (e.g. `GetX().Where(...)`).
                // Trace back to the local in the chain.
                var rootLocal = GetRootLocalSymbol(fes.Expression, semanticModel);
                if (rootLocal != null)
                {
                    AddConsumption(consumptions, rootLocal, fes.Expression.GetLocation());
                }
            }
        }

        // Case 2: invocation with the variable as receiver.
        if (node is InvocationExpressionSyntax inv &&
            inv.Expression is MemberAccessExpressionSyntax ma)
        {
            var sym = semanticModel.GetSymbolInfo(ma.Expression).Symbol;
            if (sym is ILocalSymbol || sym is IParameterSymbol || sym is IFieldSymbol || sym is IPropertySymbol)
            {
                AddConsumption(consumptions, sym, inv.GetLocation());
            }
        }
    }

    // Report locals with 2+ consumption points.
    foreach (var (sym, locs) in consumptions)
    {
        if (locs.Count < 2) continue;

        // Skip if the variable is a parameter (function inputs may legitimately
        // be enumerated multiple times by callees).
        if (sym is IParameterSymbol) continue;

        // Resolve the display type.
        ITypeSymbol? type = sym switch
        {
            ILocalSymbol l => l.Type,
            IParameterSymbol p => p.Type,
            IFieldSymbol f => f.Type,
            IPropertySymbol pr => pr.Type,
            _ => null
        };
        var typeName = type?.ToDisplayString(SymbolDisplayFormat.MinimallyQualifiedFormat) ?? "IEnumerable";

        // Find the declaration location for the "first consumption" point.
        var firstLoc = locs[0];
        Add(diagnostics, filePath, firstLoc,
            "P009", "warning",
            $"变量 '{sym.Name}' (类型 {typeName}) 被多次枚举，"
            + "每次都会重新执行 LINQ 查询",
            "使用 .ToList()/.ToArray() 物化一次，或在方法签名中接受 IReadOnlyList<T> / IList<T>");
    }
}

void AnalyzeLinqMultipleEnumerationInExpression(SemanticModel semanticModel,
    ExpressionSyntax expr, string filePath, List<SemanticDiagnostic> diagnostics)
{
    // For expression-bodied members, we only check one level deep — not worth
    // building full data flow for a single expression. Just look for inline
    // `var x = y.Where(...); ... x.Count(); ... x.ToList();` patterns.
    // Since the expression body has no statements, multi-enumeration is
    // usually across the body itself, which we don't track here. Skipping.
    _ = expr;
}

/// <summary>Record a consumption of <paramref name="sym"/> at <paramref name="loc"/>.</summary>
static void AddConsumption(Dictionary<ISymbol, List<Location>> consumptions, ISymbol sym, Location loc)
{
    if (!consumptions.TryGetValue(sym, out var list))
    {
        // Symbol may be a parameter or field that we didn't pre-register.
        // We don't report those (parameters are callees' responsibility).
        return;
    }
    list.Add(loc);
}

/// <summary>
/// Walk left through MemberAccess/Invocation chains to find a local symbol
/// reference (the "root" of the chain). Returns null if the chain doesn't
/// resolve to a local.
/// </summary>
static ISymbol? GetRootLocalSymbol(ExpressionSyntax expr, SemanticModel semanticModel)
{
    ExpressionSyntax current = expr;
    int safety = 0;
    while (safety++ < 20)
    {
        if (current is InvocationExpressionSyntax inv)
        {
            if (inv.Expression is MemberAccessExpressionSyntax invMa)
            {
                current = invMa.Expression;
                continue;
            }
            break;
        }
        if (current is MemberAccessExpressionSyntax ma)
        {
            current = ma.Expression;
            continue;
        }
        if (current is ParenthesizedExpressionSyntax paren)
        {
            current = paren.Expression;
            continue;
        }
        break;
    }
    var sym = semanticModel.GetSymbolInfo(current).Symbol;
    return sym is ILocalSymbol ? sym : null;
}

static bool IsLikelyEnumerableType(ITypeSymbol type)
{
    // Materialized collection types — safe to enumerate multiple times.
    // Skip these to avoid false positives on List<T>/T[]/Dictionary<,>.
    if (type.TypeKind == TypeKind.Array) return false;
    var defName = type.OriginalDefinition?.Name ?? type.Name;
    if (defName.StartsWith("List", StringComparison.Ordinal) ||
        defName.StartsWith("Dictionary", StringComparison.Ordinal) ||
        defName.StartsWith("HashSet", StringComparison.Ordinal) ||
        defName.StartsWith("IReadOnlyList", StringComparison.Ordinal) ||
        defName.StartsWith("IReadOnlyCollection", StringComparison.Ordinal) ||
        defName.StartsWith("IReadOnlyDictionary", StringComparison.Ordinal) ||
        defName.StartsWith("Collection", StringComparison.Ordinal) ||
        defName.StartsWith("KeyValuePair", StringComparison.Ordinal) ||
        defName == "String")
    {
        return false;
    }

    // Accept IEnumerable / IEnumerable<T> / IQueryable / IQueryable<T> and
    // derived (including user-defined LINQ projections).
    for (var current = type; current != null; current = current.BaseType)
    {
        var name = current.OriginalDefinition?.Name ?? current.Name;
        if (name == "IEnumerable" || name == "IEnumerable`1" ||
            name == "IQueryable" || name == "IQueryable`1" ||
            name == "IOrderedEnumerable`1" || name == "IOrderedQueryable`1")
        {
            return true;
        }
    }
    return false;
}

/// <summary>Walk the member-access chain from a terminal method to check if an ancestor method is Include/ThenInclude.</summary>
static bool ChainContainsMethod(MemberAccessExpressionSyntax terminalMa, string methodName)
{
    var expr = terminalMa.Expression;
    int depth = 0;
    while (expr is MemberAccessExpressionSyntax ma && depth < 20)
    {
        if (ma.Name.Identifier.Text == methodName) return true;
        expr = ma.Expression;
        depth++;
    }
    // Also check invocation expressions in the chain (e.g. Include(u => x) is
    // an InvocationExpressionSyntax wrapping a MemberAccessExpressionSyntax).
    if (expr is InvocationExpressionSyntax inv && inv.Expression is MemberAccessExpressionSyntax invMa)
    {
        if (invMa.Name.Identifier.Text == methodName) return true;
        // Continue walking from invMa.Expression
        var innerExpr = invMa.Expression;
        int innerDepth = 0;
        while (innerExpr is MemberAccessExpressionSyntax innerMa && innerDepth < 20)
        {
            if (innerMa.Name.Identifier.Text == methodName) return true;
            innerExpr = innerMa.Expression;
            innerDepth++;
        }
    }
    return false;
}

/// <summary>Check if a SaveChanges member access is on a DbContext-like variable.</summary>
static bool IsDbContextMemberAccess(MemberAccessExpressionSyntax ma, SemanticModel semanticModel)
{
    var receiverType = semanticModel.GetTypeInfo(ma.Expression).Type;
    if (receiverType != null)
        return IsDbContextType(receiverType);

    var symbol = semanticModel.GetSymbolInfo(ma.Expression).Symbol;
    if (symbol is ILocalSymbol local && local.Type != null)
        return IsDbContextType(local.Type);
    if (symbol is IParameterSymbol parameter && parameter.Type != null)
        return IsDbContextType(parameter.Type);
    if (symbol is IFieldSymbol field && field.Type != null)
        return IsDbContextType(field.Type);
    if (symbol is IPropertySymbol property && property.Type != null)
        return IsDbContextType(property.Type);

    if (ma.Expression is IdentifierNameSyntax id)
    {
        var receiverName = id.Identifier.Text;
        return receiverName is "ctx" or "db" or "context" or "_context";
    }

    return false;
}

static bool IsDbContextType(ITypeSymbol type)
{
    for (var current = type; current != null; current = current.BaseType)
    {
        if (current.Name == "DbContext" ||
            current.ToDisplayString().EndsWith(".DbContext", StringComparison.Ordinal))
            return true;
    }
    return false;
}

/// <summary>Check if a node is inside a using statement whose expression contains BeginTransaction.</summary>
static bool IsInsideTransactionUsing(SyntaxNode node)
{
    foreach (var ancestor in node.Ancestors())
    {
        if (ancestor is UsingStatementSyntax usingStmt)
        {
            // Check if the using expression references BeginTransaction
            if (usingStmt.Expression != null &&
                usingStmt.Expression.ToString().Contains("BeginTransaction",
                    StringComparison.Ordinal))
            {
                return true;
            }
            // Also check if the using declaration (C# 8+ using var) has BeginTransaction
            if (usingStmt.Declaration != null &&
                usingStmt.Declaration.Variables.Any(v =>
                    v.Initializer?.Value.ToString().Contains("BeginTransaction",
                        StringComparison.Ordinal) == true))
            {
                return true;
            }
        }
    }
    return false;
}

void AnalyzeDisposePattern(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, List<SemanticDiagnostic> diagnostics)
{
    // SEM015: class implements IDisposable but Dispose() does not call
    // Dispose() on owned IDisposable fields. Heuristic: check if any field
    // type implements IDisposable and the Dispose method body does not
    // reference that field name.
    foreach (var cls in syntaxTree.GetRoot().DescendantNodes().OfType<ClassDeclarationSyntax>())
    {
        var clsSym = semanticModel.GetDeclaredSymbol(cls) as INamedTypeSymbol;
        if (clsSym == null) continue;

        // Only check classes that implement IDisposable
        var disposableInterface = clsSym.AllInterfaces.FirstOrDefault(i =>
            i.Name == "IDisposable");
        if (disposableInterface == null) continue;

        // Find the Dispose method
        var disposeMethod = clsSym.GetMembers().OfType<IMethodSymbol>()
            .FirstOrDefault(m => m.Name == "Dispose");
        if (disposeMethod == null) continue;

        // Find all IDisposable fields
        var disposableFields = new List<IFieldSymbol>();
        foreach (var member in clsSym.GetMembers())
        {
            if (member is IFieldSymbol field && field.Type.AllInterfaces.Any(i => i.Name == "IDisposable"))
            {
                disposableFields.Add(field);
            }
        }
        if (disposableFields.Count == 0) continue;

        // Check if Dispose body references each disposable field
        foreach (var field in disposableFields)
        {
            // Get the syntax of the Dispose method
            var disposeSyntax = cls.Members.OfType<MethodDeclarationSyntax>()
                .FirstOrDefault(m => m.Identifier.Text == "Dispose");
            if (disposeSyntax == null) continue;

            bool fieldReferenced = disposeSyntax.DescendantNodes()
                .OfType<IdentifierNameSyntax>()
                .Any(id => id.Identifier.Text == field.Name);

            if (!fieldReferenced)
            {
                Add(diagnostics, filePath, disposeSyntax.GetLocation(),
                    "SEM015", "warning",
                    $"IDisposable 类 '{clsSym.Name}' 的 Dispose() 未释放字段 '{field.Name}' ({field.Type.Name})",
                    "在 Dispose() 中调用 field.Dispose() 或使用 using 声明");
            }
        }
    }
}

void AnalyzeMutableStruct(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, List<SemanticDiagnostic> diagnostics)
{
    // SEM016: mutable struct (contains non-readonly fields) — value type
    // semantics mean mutations affect copies, not the original, leading to
    // subtle bugs. Detected by checking for non-readonly fields in structs
    // that have any setter or non-constructor assignment.
    foreach (var st in syntaxTree.GetRoot().DescendantNodes().OfType<StructDeclarationSyntax>())
    {
        var stSym = semanticModel.GetDeclaredSymbol(st) as INamedTypeSymbol;
        if (stSym == null) continue;

        // Find non-readonly fields
        var mutableFields = stSym.GetMembers().OfType<IFieldSymbol>()
            .Where(f => !f.IsReadOnly && !f.IsStatic)
            .ToList();
        if (mutableFields.Count == 0) continue;

        // Find property setters that mutate fields
        var hasSetters = stSym.GetMembers().OfType<IPropertySymbol>()
            .Any(p => p.SetMethod != null && p.SetMethod.DeclaredAccessibility != Accessibility.Private);

        if (hasSetters || mutableFields.Count > 0)
        {
            var fieldNames = string.Join(", ", mutableFields.Select(f => f.Name));
            Add(diagnostics, filePath, st.GetLocation(),
                "SEM016", "info",
                $"struct '{stSym.Name}' 包含可变字段 [{fieldNames}]，值类型副本语义可能导致意外行为",
                "考虑将 struct 设为 readonly，或改为 class");
        }
    }
}

/// <summary>
/// SEM009/011/012/013/015 — syntax-level semantic hints (no type query needed).
/// </summary>
void AnalyzeSemanticHints(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, List<SemanticDiagnostic> diagnostics)
{
    var root = syntaxTree.GetRoot();

    // SEM012: reflection usage — typeof / GetMethod / GetProperty / Assembly.GetTypes
    foreach (var inv in root.DescendantNodes().OfType<InvocationExpressionSyntax>())
    {
        var exprText = inv.Expression.ToString();
        if (exprText.Contains("GetMethod") || exprText.Contains("GetProperty") ||
            exprText.Contains("GetField") || exprText.Contains("Assembly.GetTypes") ||
            exprText.Contains("CreateInstance"))
        {
            Add(diagnostics, filePath, inv.GetLocation(),
                "SEM012", "info",
                "反射调用 " + exprText + "，性能较差且失去类型安全",
                "考虑用泛型、接口或委托替代反射");
        }
    }
    // typeof(...) is a TypeOfExpressionSyntax, not an InvocationExpressionSyntax
    foreach (var tof in root.DescendantNodes().OfType<TypeOfExpressionSyntax>())
    {
        Add(diagnostics, filePath, tof.GetLocation(),
            "SEM012", "info",
            "typeof(" + tof.Type + ") 反射获取类型信息，频繁调用性能较差",
            "考虑用泛型约束或 is/as 模式匹配替代");
    }

    // SEM013: generic constraint with 3+ constraints
    foreach (var clause in root.DescendantNodes().OfType<TypeParameterConstraintClauseSyntax>())
    {
        if (clause.Constraints.Count >= 3)
        {
            Add(diagnostics, filePath, clause.GetLocation(),
                "SEM013", "info",
                $"泛型参数有 {clause.Constraints.Count} 个约束，过度约束会限制复用性",
                "确认每个约束都是必要的");
        }
    }

    // SEM015: out parameter in method signature
    foreach (var method in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
    {
        foreach (var param in method.ParameterList.Parameters)
        {
            if (param.Modifiers.Any(SyntaxKind.OutKeyword))
            {
                Add(diagnostics, filePath, param.GetLocation(),
                    "SEM015", "info",
                    $"方法 {method.Identifier.Text} 使用 out 参数 {param.Identifier.Text}，降低可读性",
                    "考虑用返回值或元组替代 out 参数");
                break; // one report per method
            }
        }
    }

    // SEM011: LINQ deferred execution — .Where(...) not materialized
    // Detect: `expr.Where(lambda)` whose result is assigned/returned but never
    // followed by ToList/ToArray/ToDictionary/First/Single/etc.
    foreach (var inv in root.DescendantNodes().OfType<InvocationExpressionSyntax>())
    {
        if (inv.Expression is MemberAccessExpressionSyntax whereMa &&
            whereMa.Name.Identifier.Text == "Where")
        {
            // Check if the parent chain ends at ToList/ToArray/etc (materialized)
            bool isMaterialized = false;
            var parent = inv.Parent;
            if (parent is MemberAccessExpressionSyntax pma &&
                pma.Name.Identifier.Text is "ToList" or "ToArray" or "ToDictionary" or
                    "ToHashSet" or "ToLookup" or "First" or "FirstOrDefault" or
                    "Single" or "SingleOrDefault" or "Any" or "Count" or "LongCount" or
                    "Sum" or "Max" or "Min" or "Aggregate")
            {
                isMaterialized = true;
            }
            if (!isMaterialized)
            {
                Add(diagnostics, filePath, inv.GetLocation(),
                    "SEM011", "info",
                    "LINQ Where 返回的是延迟执行的 IQueryable/IEnumerable，多次枚举会重复计算",
                    "如需多次使用，用 .ToList() 或 .ToArray() 物化查询结果");
            }
        }
    }

    // SEM001: nullable value type (int? etc.) dereferenced without HasValue check
    // Detect: local/field of Nullable<T> type, then .Value accessed without prior
    // .HasValue guard. Heuristic: flag .Value access on a Nullable-typed symbol.
    foreach (var ma in root.DescendantNodes().OfType<MemberAccessExpressionSyntax>())
    {
        if (ma.Name.Identifier.Text == "Value")
        {
            var typeInfo = semanticModel.GetTypeInfo(ma.Expression);
            if (typeInfo.Type is INamedTypeSymbol named && named.OriginalDefinition.SpecialType ==
                SpecialType.System_Nullable_T)
            {
                Add(diagnostics, filePath, ma.GetLocation(),
                    "SEM001", "warning",
                    "访问 Nullable<" + named.TypeArguments[0] + ">.Value 前未检查 HasValue，可能抛 InvalidOperationException",
                    "先检查 .HasValue，或用 .GetValueOrDefault() / ?? 提供默认值");
            }
        }
    }

    // SEM002: LINQ .First()/.Single() result member-accessed without null check
    foreach (var ma in root.DescendantNodes().OfType<MemberAccessExpressionSyntax>())
    {
        // Pattern: something.First().Member or something.Single().Member
        if (ma.Expression is InvocationExpressionSyntax innerInv &&
            innerInv.Expression is MemberAccessExpressionSyntax innerMa &&
            (innerMa.Name.Identifier.Text == "First" || innerMa.Name.Identifier.Text == "Single"))
        {
            Add(diagnostics, filePath, ma.GetLocation(),
                "SEM002", "warning",
                "LINQ " + innerMa.Name.Identifier.Text + "() 无空集合保护，直接访问成员可能抛 InvalidOperationException",
                "改用 FirstOrDefault()/SingleOrDefault() 并检查 null");
        }
    }

    // SEM009: nullable reference type declaration (string? etc.)
    // Detects NullableTypeSyntax on variable declarations. In C# 7.3 (the
    // default for this analyzer) the parser accepts `string?` syntactically
    // but the type symbol resolves to `string` (not Nullable<string>), so
    // we use the underlying element type's IsValueType to discriminate
    // reference-type nullables (string? / object?) from value-type ones
    // (int? — already covered by SEM001).
    foreach (var nts in root.DescendantNodes().OfType<NullableTypeSyntax>())
    {
        // In C# 7.3 (default), NullableTypeSyntax's parent is the
        // VariableDeclarationSyntax; in C# 8+ nullable context it may be
        // the VariableDeclaratorSyntax. Accept either chain.
        VariableDeclaratorSyntax? vd = nts.Parent as VariableDeclaratorSyntax;
        if (vd == null && nts.Parent is VariableDeclarationSyntax varDecl)
        {
            vd = varDecl.Variables.FirstOrDefault();
        }
        if (vd == null) continue;

        var typeInfo = semanticModel.GetTypeInfo(nts);
        // Discriminate reference-type nullables from value-type ones.
        // In C# 7.3, the type symbol for `string?` is `string` (IsValueType=false),
        // so !IsValueType is sufficient. For nullable-value-type patterns
        // (e.g. `int?`), the type symbol is `int?` (Nullable<int>) which is
        // a value type — these belong to SEM001's domain, so we skip.
        if (typeInfo.Type == null) continue;
        if (typeInfo.Type.IsValueType) continue;
        if (typeInfo.Type.SpecialType == SpecialType.None && typeInfo.Type.Name == "Nullable`1") continue;

        Add(diagnostics, filePath, vd.GetLocation(),
            "SEM009", "info",
            "可空引用类型 " + nts.ElementType + "? 可能为 null，解引用前需判空",
            "使用空条件运算符 ?. 或在访问前显式 null 检查");
    }
}

static bool IsLikelyValueTypeName(string name)
{
    // Quick heuristic for value type names — used only as a fallback when
    // the semantic model can't resolve a type (e.g. C# 7.3 nullable ref).
    return name is "int" or "long" or "short" or "byte" or "sbyte"
        or "uint" or "ulong" or "ushort" or "float" or "double" or "decimal"
        or "bool" or "char" or "DateTime" or "TimeSpan" or "Guid"
        || name.EndsWith("Id", StringComparison.Ordinal) && name.Length <= 8;
}

/// <summary>
/// Intra-procedural taint analysis: track user-input sources flowing into dangerous sinks.
/// Covers indirect assignment, string interpolation, and indexer access — gaps in the AST
/// analyzer's pattern-matching SEC002/003/004 rules.
/// Limitation: method-local only (no cross-method/cross-file propagation).
/// </summary>
void AnalyzeTaint(SemanticModel semanticModel, SyntaxTree syntaxTree,
    string filePath, List<SemanticDiagnostic> diagnostics)
{
    var root = syntaxTree.GetRoot();

    // Taint sources: member/identifier names that indicate user-controlled input
    var sourceMembers = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "Request", "Form", "QueryString", "Headers", "Cookies", "Params", "RouteData", "Item",
        "Console", "Stdin", "userInput", "args", "argv"
    };

    // Taint sinks: dangerous APIs that should not receive unsanitized input
    var sinkMethods = new Dictionary<string, (string Code, string Msg)>(StringComparer.OrdinalIgnoreCase)
    {
        ["Start"] = ("SEC_TAINT_PROCESS", "Process.Start 参数含未净化的用户输入（污点追踪），存在命令注入风险"),
        ["SelectNodes"] = ("SEC_TAINT_XPATH", "XPath 查询含未净化的用户输入（污点追踪），存在 XPath 注入风险"),
        ["SelectSingleNode"] = ("SEC_TAINT_XPATH", "XPath 查询含未净化的用户输入（污点追踪），存在 XPath 注入风险"),
        ["Combine"] = ("SEC_TAINT_PATH", "Path.Combine 含未净化的用户输入（污点追踪），存在路径穿越风险"),
    };

    foreach (var method in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
    {
        if (method.Body == null) continue;

        // Phase 1: collect tainted local symbols from source assignments
        var tainted = new HashSet<ISymbol>(SymbolEqualityComparer.Default);

        foreach (var assign in method.Body.DescendantNodes().OfType<AssignmentExpressionSyntax>())
        {
            // Check if RHS is a direct source: Request["x"], Request.Form["x"], etc.
            if (IsTaintSource(assign.Right, sourceMembers))
            {
            }
            {
                var sym = semanticModel.GetSymbolInfo(assign.Left).Symbol;
                if (sym != null) tainted.Add(sym);
            }
            // Propagate: var y = taintedVar (or expression using taintedVar)
            if (UsesTaintedSymbol(assign.Right, tainted, semanticModel))
            {
                var sym = semanticModel.GetSymbolInfo(assign.Left).Symbol;
                if (sym != null) tainted.Add(sym);
            }
        }

        // Also check local variable declarations: var x = Request["cmd"];
        foreach (var decl in method.Body.DescendantNodes().OfType<LocalDeclarationStatementSyntax>())
        {
            foreach (var v in decl.Declaration.Variables)
            {
                if (v.Initializer != null)
                {
                    var initExpr = v.Initializer.Value;
                    var isSrc = IsTaintSource(initExpr, sourceMembers);
                    if (isSrc ||
                        UsesTaintedSymbol(initExpr, tainted, semanticModel))
                    {
                        var sym = semanticModel.GetDeclaredSymbol(v);
                        if (sym != null)
                        {
                            tainted.Add(sym);
                        }
                    }
                }
            }
        }

        // Phase 2: check sinks — any invocation of a dangerous method with a tainted arg
        foreach (var invoke in method.Body.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            if (invoke.Expression is not MemberAccessExpressionSyntax ma) continue;
            if (!sinkMethods.TryGetValue(ma.Name.Identifier.Text, out var sink)) continue;

            foreach (var arg in invoke.ArgumentList.Arguments)
            {
                var argSym = semanticModel.GetSymbolInfo(arg.Expression).Symbol;
                // Direct source in argument: Process.Start(Request["cmd"])
                if (IsTaintSource(arg.Expression, sourceMembers))
                {
                    Add(diagnostics, filePath, invoke.GetLocation(),
                        sink.Code, "error", sink.Msg,
                        "验证/净化用户输入后再传入危险 API");
                    break;
                }
                // Tainted symbol in argument: var x = Request["cmd"]; Process.Start(x)
                if (UsesTaintedSymbol(arg.Expression, tainted, semanticModel))
                {
                    Add(diagnostics, filePath, invoke.GetLocation(),
                        sink.Code, "error", sink.Msg,
                        "验证/净化用户输入后再传入危险 API");
                    break;
                }
            }
        }
    }
}

static bool IsTaintSource(ExpressionSyntax expr, HashSet<string> sourceMembers)
{
    // Request["cmd"], Request.Form["x"], HttpContext.Current.Request["x"]
    if (expr is ElementAccessExpressionSyntax eaa)
    {
        var receiver = eaa.Expression;
        // Walk member access chain to find source member name
        while (receiver is MemberAccessExpressionSyntax ma)
            receiver = ma.Expression;
        if (receiver is IdentifierNameSyntax id &&
            sourceMembers.Contains(id.Identifier.Text))
            return true;
        // Direct: Request["x"]
        if (eaa.Expression is MemberAccessExpressionSyntax ema &&
            sourceMembers.Contains(ema.Name.Identifier.Text))
            return true;
    }
    // Request.Form, Request.QueryString (property access without indexer)
    if (expr is MemberAccessExpressionSyntax pma &&
        sourceMembers.Contains(pma.Name.Identifier.Text))
        return true;
    // String interpolation: $"...{Request["cmd"]}..."
    if (expr is InterpolatedStringExpressionSyntax interp)
    {
        foreach (var content in interp.Contents)
        {
            if (content is InterpolationSyntax i && IsTaintSource(i.Expression, sourceMembers))
                return true;
        }
    }
    // Method call: Console.ReadLine(), Console.Read()
    if (expr is InvocationExpressionSyntax inv &&
        inv.Expression is MemberAccessExpressionSyntax ima)
    {
        // Check receiver: Console or System.Console → match "Console"
        var receiver = ima.Expression;
        if (receiver is IdentifierNameSyntax rid && sourceMembers.Contains(rid.Identifier.Text))
            return true;
        if (receiver is MemberAccessExpressionSyntax rma &&
            sourceMembers.Contains(rma.Name.Identifier.Text))
            return true;
    }
    return false;
}

static bool UsesTaintedSymbol(ExpressionSyntax expr, HashSet<ISymbol> tainted, SemanticModel model)
{
    // Check expr itself first (DescendantNodes doesn't include self)
    if (expr is IdentifierNameSyntax selfId)
    {
        var selfSym = model.GetSymbolInfo(selfId).Symbol;
        if (selfSym != null && tainted.Contains(selfSym))
            return true;
    }
    // Check descendant identifiers
    foreach (var id in expr.DescendantNodes().OfType<IdentifierNameSyntax>())
    {
        var sym = model.GetSymbolInfo(id).Symbol;
        if (sym != null && tainted.Contains(sym))
            return true;
    }
    // Also check string interpolation with tainted content
    if (expr is InterpolatedStringExpressionSyntax interp)
    {
        foreach (var content in interp.Contents.OfType<InterpolationSyntax>())
        {
            foreach (var id in content.Expression.DescendantNodes().OfType<IdentifierNameSyntax>())
            {
                var sym = model.GetSymbolInfo(id).Symbol;
                if (sym != null && tainted.Contains(sym))
                    return true;
            }
        }
    }
    return false;
}

void AnalyzeAspNetRules(
    SemanticModel semanticModel,
    SyntaxTree syntaxTree,
    string filePath,
    Dictionary<string, (INamedTypeSymbol, string)> allTypes,
    List<SemanticDiagnostic> diagnostics)
{
    var root = syntaxTree.GetRoot();

    // ASP001: Controller 缺 [Authorize]
    // 用语义模型精确定义 Controller：继承自 ControllerBase/Controller 或标记了 [ApiController]
    foreach (var classDecl in root.DescendantNodes().OfType<ClassDeclarationSyntax>())
    {
        var classSym = semanticModel.GetDeclaredSymbol(classDecl) as INamedTypeSymbol;
        if (classSym == null) continue;

        // 检查是否为 ASP.NET Core Controller
        bool isController = classSym.ToDisplayString().EndsWith("Controller");
        if (!isController)
        {
            // 检查基类
            var baseType = classSym.BaseType;
            while (baseType != null)
            {
                if (baseType.ToDisplayString().Contains("Microsoft.AspNetCore.Mvc.ControllerBase") ||
                    baseType.ToDisplayString().Contains("Microsoft.AspNetCore.Mvc.Controller"))
                {
                    isController = true;
                    break;
                }
                baseType = baseType.BaseType;
            }
        }
        if (!isController)
        {
            // 检查 [ApiController] 属性
            foreach (var attrList in classDecl.AttributeLists)
            {
                foreach (var attr in attrList.Attributes)
                {
                    var attrSym = semanticModel.GetTypeInfo(attr).Type;
                    if (attrSym?.ToDisplayString().Contains("ApiControllerAttribute") == true)
                    {
                        isController = true;
                        break;
                    }
                }
                if (isController) break;
            }
        }

        if (isController)
        {
            // 检查 Controller 级别 [Authorize]
            bool hasControllerAuthorize = classDecl.AttributeLists
                .SelectMany(al => al.Attributes)
                .Any(attr =>
                {
                    var attrSym = semanticModel.GetTypeInfo(attr).Type;
                    return attrSym?.ToDisplayString().Contains("AuthorizeAttribute") == true;
                });

            // 检查所有 Action 方法
            var actions = classDecl.Members.OfType<MethodDeclarationSyntax>()
                .Where(m =>
                {
                    // 有 HTTP 方法属性
                    var hasHttpMethod = m.AttributeLists
                        .SelectMany(al => al.Attributes)
                        .Any(attr =>
                        {
                            var attrSym = semanticModel.GetTypeInfo(attr).Type;
                            return attrSym?.ToDisplayString().Contains("HttpGetAttribute") == true ||
                                   attrSym?.ToDisplayString().Contains("HttpPostAttribute") == true ||
                                   attrSym?.ToDisplayString().Contains("HttpPutAttribute") == true ||
                                   attrSym?.ToDisplayString().Contains("HttpDeleteAttribute") == true ||
                                   attrSym?.ToDisplayString().Contains("HttpPatchAttribute") == true ||
                                   attrSym?.ToDisplayString().Contains("HttpHeadAttribute") == true ||
                                   attrSym?.ToDisplayString().Contains("HttpOptionsAttribute") == true;
                        });
                    return hasHttpMethod;
                });

            foreach (var action in actions)
            {
                // 检查 Action 级 [Authorize]
                bool hasActionAuthorize = action.AttributeLists
                    .SelectMany(al => al.Attributes)
                    .Any(attr =>
                    {
                        var attrSym = semanticModel.GetTypeInfo(attr).Type;
                        return attrSym?.ToDisplayString().Contains("AuthorizeAttribute") == true;
                    });

                if (!hasControllerAuthorize && !hasActionAuthorize)
                {
                    Add(diagnostics, filePath, action.Identifier.GetLocation(),
                        "ASP001", "agent_verify",
                        $"Action '{action.Identifier.Text}' 缺少 [Authorize]，确认是否需要认证",
                        "应用 [Authorize] 确认明确");
                }
            }
        }
    }

    // ASP002: [Bind] 含敏感字段
    foreach (var param in root.DescendantNodes().OfType<ParameterSyntax>())
    {
        foreach (var attrList in param.AttributeLists)
        {
            foreach (var attr in attrList.Attributes)
            {
                var attrSym = semanticModel.GetTypeInfo(attr).Type;
                if (attrSym?.ToDisplayString().Contains("BindAttribute") == true ||
                    attrSym?.ToDisplayString().Contains("BindPropertyAttribute") == true)
                {
                    foreach (var arg in attr.ArgumentList?.Arguments ?? Enumerable.Empty<AttributeArgumentSyntax>())
                    {
                        var argText = arg.ToString();
                        if (argText.Contains("Password") || argText.Contains("password") ||
                            argText.Contains("Token") || argText.Contains("token") ||
                            argText.Contains("Secret") || argText.Contains("secret") ||
                            argText.Contains("Key") || argText.Contains("key"))
                        {
                            Add(diagnostics, filePath, attr.GetLocation(),
                                "ASP002", "agent_verify",
                                "[Bind] 包含敏感字段名，可能被用户输入覆盖",
                                "避免绑定特权字段或传递用户输入");
                        }
                    }
                }
            }
        }
    }

    // ASP003: [IgnoreAntiforgeryToken] 跳过 CSRF
    foreach (var method in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
    {
        foreach (var attrList in method.AttributeLists)
        {
            foreach (var attr in attrList.Attributes)
            {
                var attrSym = semanticModel.GetTypeInfo(attr).Type;
                if (attrSym?.ToDisplayString().Contains("IgnoreAntiforgeryTokenAttribute") == true)
                {
                    Add(diagnostics, filePath, attr.GetLocation(),
                        "ASP003", "agent_verify",
                        "[IgnoreAntiforgeryToken] 跳过 CSRF 保护，确认是否有 Token Auth",
                        "非 Cookie 认证请求才可用");
                }
            }
        }
    }
// RCS0052: redundant base() call when base has accessible parameterless constructor
}
    void AnalyzeRedundantBaseConstructorCall(SemanticModel semanticModel, SyntaxTree tree,
        string filePath, List<SemanticDiagnostic> diagnostics)
    {
        var root = tree.GetRoot();
        foreach (var ctor in root.DescendantNodes().OfType<ConstructorDeclarationSyntax>())
        {
            var init = ctor.Initializer;
            if (init == null) continue;
            if (!init.IsKind(SyntaxKind.BaseConstructorInitializer)) continue;

            var baseType = semanticModel.GetTypeInfo(init).Type;
            if (baseType == null) continue;

            var parameterlessCtor = baseType.GetMembers()
                .OfType<IMethodSymbol>()
                .FirstOrDefault(m => m.MethodKind == MethodKind.Constructor &&
                                     m.Parameters.Length == 0 &&
                                     m.DeclaredAccessibility != Accessibility.Private);
            if (parameterlessCtor != null)
            {
                Add(diagnostics, filePath, init.GetLocation(),
                    "RCS0052", "info",
                    "显式调用 base() 参数化构造器，但基类 '" + baseType.Name + "' 已有无参构造器，冗余的 base() 调用可省略（RCS0052）",
                    "移除 : base(...) 或改为 : base()");
            }
        }
    }

    // RCS0096: nameof expression with type name (should use language keyword)
    void AnalyzeRedundantNameofType(SemanticModel semanticModel, SyntaxTree tree,
        string filePath, List<SemanticDiagnostic> diagnostics)
    {
        var root = tree.GetRoot();
        foreach (var inv in root.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            var name = inv.Expression as IdentifierNameSyntax;
            if (name?.Identifier.Text != "nameof") continue;
            if (inv.ArgumentList.Arguments.Count != 1) continue;
            var arg = inv.ArgumentList.Arguments[0];
            if (arg.Expression is TypeOfExpressionSyntax typeofExpr)
            {
                var typeSym = semanticModel.GetTypeInfo(typeofExpr.Type).Type;
                if (typeSym == null) continue;
                string keyword = typeSym.SpecialType switch
                {
                    SpecialType.System_Int32 => "int",
                    SpecialType.System_Int64 => "long",
                    SpecialType.System_String => "string",
                    SpecialType.System_Boolean => "bool",
                    SpecialType.System_Object => "object",
                    SpecialType.System_Double => "double",
                    SpecialType.System_Decimal => "decimal",
                    _ => null
                };
                if (keyword != null)
                {
                    Add(diagnostics, filePath, inv.GetLocation(),
                        "RCS0096", "info",
                        "nameof(typeof(" + typeSym.Name + ")) 应改为 nameof(" + keyword + ")（RCS0096）",
                        "使用语言内置关键字替代 typeof(X).Name");
                }
            }
        }
    }

    // RCS0018: string.Format call with sequential placeholders could use string interpolation
    void AnalyzeUseStringInterpolation(SemanticModel semanticModel, SyntaxTree tree,
        string filePath, List<SemanticDiagnostic> diagnostics)
    {
        var root = tree.GetRoot();
        foreach (var inv in root.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            var member = inv.Expression as MemberAccessExpressionSyntax;
            if (member?.Name.Identifier.Text != "Format") continue;
            if (member.Expression.ToString() != "string") continue;
            if (inv.ArgumentList.Arguments.Count < 2) continue;

            if (inv.ArgumentList.Arguments[0].Expression is not LiteralExpressionSyntax lit) continue;
            if (lit.Token.Value is not string formatStr) continue;

            if (System.Text.RegularExpressions.Regex.IsMatch(formatStr, @"\{\d+\}"))
            {
                Add(diagnostics, filePath, inv.GetLocation(),
                    "RCS0018", "info",
                    "string.Format 调用可替换为字符串插值（" + "\"{...}\"" + "）或 nameof（RCS0018）",
                    "使用 " + "\"{param}\"" + " 替代 string.Format(" + "\"{param}\"" + ", ...) 格式");
            }
        }
    }

    // RCS0013: use collection initializer instead of multiple Add() calls
    void AnalyzeUseCollectionInitializer(SemanticModel semanticModel, SyntaxTree tree,
        string filePath, List<SemanticDiagnostic> diagnostics)
    {
        var root = tree.GetRoot();

        foreach (var method in root.DescendantNodes().OfType<MethodDeclarationSyntax>())
        {
            if (method.Body == null) continue;

            var addCalls = new Dictionary<ISymbol, List<InvocationExpressionSyntax>>();
            foreach (var inv in method.Body.DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                var member = inv.Expression as MemberAccessExpressionSyntax;
                if (member?.Name.Identifier.Text != "Add") continue;
                var collSym = semanticModel.GetSymbolInfo(member.Expression).Symbol;
                if (!addCalls.ContainsKey(collSym)) addCalls[collSym] = new List<InvocationExpressionSyntax>();
                addCalls[collSym].Add(inv);
            }

            foreach (var kvp in addCalls)
            {
                var collSym = kvp.Key;
                var calls = kvp.Value;
                if (calls.Count < 3) continue;

                if (collSym is ILocalSymbol local)
                {
                    var decl = local.DeclaringSyntaxReferences.FirstOrDefault()?.GetSyntax();
                    if (decl is ObjectCreationExpressionSyntax create &&
                        create.ArgumentList?.Arguments.Count == 0 &&
                        create.Initializer == null)
                    {
                        Add(diagnostics, filePath, calls[0].GetLocation(),
                            "RCS0013", "info",
                            "集合 '" + local.Name + "' 通过 3+ 次 Add() 调用初始化，建议使用集合初始化器语法（" +
                            "var x = new List<T> { a, b, c }）（RCS0013）",
                            "将 new " + local.Name + "() 和后续 .Add() 调用合并为集合初始化器语法");
                    }
                }
            }
        }
    }

    // RCS0045: use coalesce expression instead of conditional null check assignment
    void AnalyzeUseCoalesceExpression(SemanticModel semanticModel, SyntaxTree tree,
        string filePath, List<SemanticDiagnostic> diagnostics)
    {
        var root = tree.GetRoot();
        foreach (var stmt in root.DescendantNodes().OfType<IfStatementSyntax>())
        {
            if (stmt.Else != null) continue;
            if (stmt.Condition is not BinaryExpressionSyntax cond) continue;
            if (!cond.OperatorToken.IsKind(SyntaxKind.EqualsEqualsToken)) continue;
            if (cond.Right is not LiteralExpressionSyntax rhsLit) continue;
            if (rhsLit.Token.Value != null) continue;

            var body = stmt.Statement as ExpressionStatementSyntax;
            if (body == null) continue;
            if (body.Expression is not AssignmentExpressionSyntax assign) continue;
            if (assign.Right is not IdentifierNameSyntax rhsId) continue;
            if (cond.Left is not IdentifierNameSyntax condId) continue;
            if (rhsId.Identifier.Text != condId.Identifier.Text) continue;

            var name = condId.Identifier.Text;
            Add(diagnostics, filePath, stmt.GetLocation(),
                "RCS0045", "info",
                "if (" + name + " == null) 可用 null 合并运算符简化（RCS0045）",
                "使用 ?? 或 ??= 替代 null 检查赋值模式");
        }
    }


record class SemanticDiagnostic
{
    [JsonPropertyName("file")] public string File { get; set; } = "";
    [JsonPropertyName("line")] public int Line { get; set; }
    [JsonPropertyName("severity")] public string Severity { get; set; } = "";
    [JsonPropertyName("code")] public string Code { get; set; } = "";
    [JsonPropertyName("message")] public string Message { get; set; } = "";
    [JsonPropertyName("suggestion")] public string Suggestion { get; set; } = "";
    [JsonPropertyName("category")] public string Category { get; set; } = "";
}

// ============================================================
// Record 类型定义（必须在顶级语句之后）
// ============================================================

record CompilationCache
{
    public CSharpCompilation? Compilation { get; init; }
    public Dictionary<string, SyntaxTree> SyntaxTrees { get; init; } = new(StringComparer.OrdinalIgnoreCase);
    public Dictionary<string, string> FileHashes { get; init; } = new(StringComparer.OrdinalIgnoreCase);
    public DateTime Timestamp { get; init; }
}

/// <summary>
/// Incremental cache statistics for a single run. Reset at process start.
/// Surfaced in the JSON output as ``cache_stats`` so callers can assert cache
/// hit rate in regression tests (guards against silent perf regressions when
/// the incremental path is refactored).
/// </summary>
static class IncrementalStats
{
    public static int CacheHits;
    public static int CacheMisses;
    public static bool CompilationReused;
}

record CacheData
{
    [JsonPropertyName("fileHashes")]
    public Dictionary<string, string> FileHashes { get; init; } = new(StringComparer.OrdinalIgnoreCase);

    [JsonPropertyName("syntaxTreePaths")]
    public Dictionary<string, string> SyntaxTreePaths { get; init; } = new(StringComparer.OrdinalIgnoreCase);

    [JsonPropertyName("timestamp")]
    public DateTime Timestamp { get; init; }
}

// ============================================================
// Solution-aware cross-project support
// ============================================================

record SolutionProject
{
    public string Name { get; init; } = "";
    public string CsprojPath { get; init; } = "";
    public string ProjectDir => Path.GetDirectoryName(CsprojPath) ?? "";
}

static class SolutionHelper
{
    internal static List<SolutionProject> ParseSolution(string slnPath)
    {
        var slnDir = Path.GetDirectoryName(Path.GetFullPath(slnPath)) ?? ".";
        var projects = new List<SolutionProject>();
        var pattern = @"Project\(""\{([^}]+)\}""\)\s*=\s*""([^""]+)"",\s*""([^""]+)"",\s*""\{([^}]+)\}""";
        foreach (var line in File.ReadLines(slnPath))
        {
            var m = System.Text.RegularExpressions.Regex.Match(line.Trim(), pattern);
            if (m.Success && m.Groups[3].Value.EndsWith(".csproj"))
            {
                var relPath = m.Groups[3].Value.Replace('\\', Path.DirectorySeparatorChar);
                projects.Add(new SolutionProject
                {
                    Name = m.Groups[2].Value,
                    CsprojPath = Path.GetFullPath(Path.Combine(slnDir, relPath)),
                });
            }
        }
        return projects;
    }

    internal static Dictionary<string, HashSet<string>> BuildDependencyGraph(List<SolutionProject> projects)
    {
        var graph = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
        foreach (var proj in projects)
        {
            var deps = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
            try
            {
                var content = File.ReadAllText(proj.CsprojPath);
                var refPattern = @"<ProjectReference\s+Include=""([^""]+)""";
                foreach (System.Text.RegularExpressions.Match m in
                    System.Text.RegularExpressions.Regex.Matches(content, refPattern))
                {
                    var refRel = m.Groups[1].Value.Replace('\\', Path.DirectorySeparatorChar);
                    var refPath = Path.GetFullPath(Path.Combine(proj.ProjectDir, refRel));
                    deps.Add(refPath);
                }
            }
            catch { }
            graph[proj.CsprojPath] = deps;
        }
        return graph;
    }

    internal static string? FindOutputDll(string csprojPath, string tfm = "net6.0")
    {
        var projDir = Path.GetDirectoryName(Path.GetFullPath(csprojPath)) ?? "";
        var dllName = Path.GetFileNameWithoutExtension(csprojPath) + ".dll";
        var candidates = new[]
        {
            Path.Combine(projDir, "bin", "Debug", tfm, dllName),
            Path.Combine(projDir, "bin", "Release", tfm, dllName),
        };
        foreach (var c in candidates)
        {
            if (File.Exists(c)) return c;
        }
        return null;
    }

    internal static List<string> ResolveTransitiveDeps(
        string targetCsproj,
        Dictionary<string, HashSet<string>> graph,
        List<SolutionProject> allProjects,
        string tfm = "net6.0")
    {
        var dlls = new List<string>();
        var visited = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
        if (!graph.TryGetValue(targetCsproj, out var directDeps)) return dlls;
        var queue = new Queue<string>(directDeps);
        while (queue.Count > 0)
        {
            var dep = queue.Dequeue();
            if (!visited.Add(dep)) continue;
            var dll = FindOutputDll(dep, tfm);
            if (dll != null && !dlls.Contains(dll, StringComparer.OrdinalIgnoreCase))
                dlls.Add(dll);
            if (graph.TryGetValue(dep, out var subDeps))
            {
                foreach (var sub in subDeps)
                    if (!visited.Contains(sub))
                        queue.Enqueue(sub);
            }
        }
        return dlls;
    }

    internal static List<string> CollectAllSourceFiles(List<SolutionProject> projects)
    {
        var files = new List<string>();
        foreach (var proj in projects)
        {
            if (!Directory.Exists(proj.ProjectDir)) continue;
            foreach (var cs in Directory.EnumerateFiles(proj.ProjectDir, "*.cs", SearchOption.AllDirectories))
                files.Add(cs);
        }
        return files;
    }

    internal static List<string> FindCsprojForFiles(string[] files, List<SolutionProject> allProjects)
    {
        var csprojMap = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        foreach (var proj in allProjects)
        {
            var projDir = proj.ProjectDir;
            if (!projDir.EndsWith(Path.DirectorySeparatorChar.ToString()))
                projDir += Path.DirectorySeparatorChar;
            csprojMap[projDir] = proj.CsprojPath;
        }
        var found = new List<string>();
        foreach (var file in files)
        {
            var fileDir = Path.GetDirectoryName(Path.GetFullPath(file)) ?? "";
            foreach (var (projDir, csprojPath) in csprojMap)
            {
                if (fileDir.StartsWith(projDir, StringComparison.OrdinalIgnoreCase))
                {
                    if (!found.Contains(csprojPath, StringComparer.OrdinalIgnoreCase))
                        found.Add(csprojPath);
                    break;
                }
            }
        }
        return found;
    }

    internal static string? FindSolution(string startDir)
    {
        var current = new DirectoryInfo(startDir);
        for (int i = 0; i < 10; i++)
        {
            if (current == null) return null;
            var slns = current.GetFiles("*.sln");
            if (slns.Length > 0) return slns[0].FullName;
            current = current.Parent;
        }
        return null;
    }
}


record ParsedArgs
{
    public List<string> Files { get; init; } = new();
    public List<string> References { get; init; } = new();
    public bool Incremental { get; init; }
    public string? CacheDir { get; init; }
    public string? SolutionPath { get; init; }
    public bool SolutionFull { get; init; }
}

