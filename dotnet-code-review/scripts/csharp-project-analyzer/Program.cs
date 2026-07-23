/// C# Project Analyzer — 项目级跨文件依赖图分析
/// 使用 AdhocWorkspace + CSharpCompilation（仅需 Microsoft.CodeAnalysis 4.5.0）
/// 构建类型依赖图、计算 SAP 指标、检测循环依赖
///
/// 输入: --files <.cs1.cs> <.cs2.cs> ...
/// 输出: JSON 格式的依赖图 + 类型指标

using System.Text.Json;
using System.Text.Json.Serialization;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using Microsoft.CodeAnalysis.Text;

if (args.Length == 0)
{
    Console.Error.WriteLine("Usage: dotnet run -- --file-list <path> [--files <.cs1.cs> ...]");
    return 1;
}

// Parse arguments: collect positional files and --file-list entries.
// This replaces the simple `args.Where(a => !a.StartsWith("--"))` filter
// to support the --file-list flag (avoids Windows cmdline length limit).
var files = new List<string>();
{
    var i = 0;
    while (i < args.Length)
    {
        if (args[i] == "--file-list" && i + 1 < args.Length)
        {
            i++;
            var listPath = args[i];
            if (File.Exists(listPath))
            {
                foreach (var line in File.ReadAllLines(listPath))
                {
                    var trimmed = line.Trim();
                    if (trimmed.Length > 0 && File.Exists(trimmed))
                        files.Add(trimmed);
                }
            }
        }
        else if (!args[i].StartsWith("--"))
        {
            files.Add(args[i]);
        }
        i++;
    }
}
if (files.Count == 0)
{
    Console.Error.WriteLine("{\"error\": \"No valid .cs files provided\"}");
    return 1;
}

var result = new ProjectAnalysisResult();

try
{
    await AnalyzeFilesAsync(files.ToArray(), result);
}
catch (Exception ex)
{
    result.errors.Add("Project analysis failed: " + ex.Message);
}

var options = new JsonSerializerOptions
{
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase,
    DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull
};
Console.WriteLine(JsonSerializer.Serialize(result, options));

return result.errors.Count == 0 ? 0 : 1;

/// <summary>
/// 加载文件，构建依赖图，计算指标
/// </summary>
async Task AnalyzeFilesAsync(string[] filePaths, ProjectAnalysisResult result)
{
    var validFiles = filePaths.Where(File.Exists).ToArray();
    if (validFiles.Length == 0) return;

    result.projectRoot = Path.GetDirectoryName(validFiles.First()) ?? "";

    using var workspace = new AdhocWorkspace();
    var projectInfo = ProjectInfo.Create(
        ProjectId.CreateNewId(), VersionStamp.Create(),
        "VirtualProject", "VirtualAssembly", LanguageNames.CSharp,
        compilationOptions: new CSharpCompilationOptions(OutputKind.DynamicallyLinkedLibrary)
    );
    var project = workspace.AddProject(projectInfo);

    // 加载文件
    var syntaxTrees = new Dictionary<string, SyntaxTree>(StringComparer.OrdinalIgnoreCase);
    foreach (var file in validFiles)
    {
        var code = await File.ReadAllTextAsync(file);
        var tree = CSharpSyntaxTree.ParseText(code, new CSharpParseOptions(LanguageVersion.Latest), path: file);
        syntaxTrees[file] = tree;

        var docId = DocumentId.CreateNewId(project.Id);
        var sourceText = SourceText.From(code, tree.Encoding ?? System.Text.Encoding.UTF8);
        var docInfo = DocumentInfo.Create(
            docId,
            Path.GetFileName(file),
            loader: TextLoader.From(TextAndVersion.Create(sourceText, VersionStamp.Create(), file)),
            filePath: file
        );
        workspace.AddDocument(docInfo);
    }

    var newProject = workspace.CurrentSolution.Projects.First();
    var compilation = await newProject.GetCompilationAsync();
    if (compilation == null) return;

    // 收集每个文件的类型声明
    var fileToTypes = new Dictionary<string, List<string>>(StringComparer.OrdinalIgnoreCase);
    var typeNameToFile = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);

    foreach (var (file, tree) in syntaxTrees)
    {
        var root = tree.GetRoot();
        var typeNames = new List<string>();

        foreach (var node in root.DescendantNodes())
        {
            string? typeName = null;

            if (node.Kind() == SyntaxKind.ClassDeclaration)
            {
                typeName = ((ClassDeclarationSyntax)node).Identifier.Text;
            }
            else if (node.Kind() == SyntaxKind.EnumDeclaration)
            {
                typeName = ((EnumDeclarationSyntax)node).Identifier.Text;
            }

            if (!string.IsNullOrEmpty(typeName))
            {
                // 完全限定名：namespace.type
                var ns = GetNamespace(root, node);
                var fullName = string.IsNullOrEmpty(ns) ? typeName : ns + "." + typeName;

                // 处理嵌套类型（不处理 namespace：GetNamespace 已处理）
                var parent = node.Parent;
                while (parent != null && (parent.Kind() == SyntaxKind.ClassDeclaration ||
                                          parent.Kind() == SyntaxKind.InterfaceDeclaration ||
                                          parent.Kind() == SyntaxKind.StructDeclaration))
                {
                    var parentId = parent is ClassDeclarationSyntax c ? c.Identifier.Text
                                 : parent is InterfaceDeclarationSyntax i ? i.Identifier.Text
                                 : ((StructDeclarationSyntax)parent).Identifier.Text;
                    fullName = fullName + "+" + parentId;
                    parent = parent.Parent;
                }

                if (!typeNameToFile.ContainsKey(fullName))
                    typeNameToFile[fullName] = file;
                typeNames.Add(fullName);
            }
        }

        fileToTypes[file] = typeNames;
    }

    // 构建文件依赖图
    var graph = new Dictionary<string, HashSet<string>>(StringComparer.OrdinalIgnoreCase);
    foreach (var file in validFiles)
        graph[file] = new HashSet<string>(StringComparer.OrdinalIgnoreCase);

    // 对每个文件，查找对其他文件类型的引用
    foreach (var (sourceFile, tree) in syntaxTrees)
    {
        var root = tree.GetRoot();

        // 通过 QualifiedName 查找（完全限定引用）
        foreach (var qnode in root.DescendantNodes())
        {
            if (qnode is QualifiedNameSyntax qns)
            {
                var qname = qns.ToString().Trim();
                if (typeNameToFile.TryGetValue(qname, out var targetFile) &&
                    !string.Equals(sourceFile, targetFile, StringComparison.OrdinalIgnoreCase))
                {
                    graph[sourceFile].Add(targetFile);
                }
            }
        }

        // 通过标识符匹配（简单名引用）— 使用语义模型消除虚假依赖
        // 必须使用 compilation.SyntaxTrees（而非预解析的 trees），否则
        // GetSemanticModel 会抛出 "SyntaxTree 不在编译中"。
        foreach (var srcTree in compilation.SyntaxTrees)
        {
            var srcRoot = srcTree.GetRoot();
            var semanticModel = compilation.GetSemanticModel(srcTree);
            var srcFile = srcTree.FilePath;

            foreach (var id in srcRoot.DescendantNodes())
            {
                if (id is not IdentifierNameSyntax ids)
                    continue;

                // 优先使用语义模型：确认该标识符是否解析为类型符号
                INamedTypeSymbol? resolvedType = null;
                try
                {
                    var symbolInfo = semanticModel.GetSymbolInfo(ids);
                    resolvedType = symbolInfo.Symbol as INamedTypeSymbol;
                }
                catch
                {
                    // 无引用程序集时语义分析可能失败，回退到语法匹配
                }

                if (resolvedType != null)
                {
                    // 语义模型成功解析：使用解析后的类型名精确匹配
                    var resolvedName = resolvedType.ToDisplayString(
                        SymbolDisplayFormat.MinimallyQualifiedFormat);
                    foreach (var (fullName, targetFile) in typeNameToFile)
                    {
                        if (string.Equals(srcFile, targetFile,
                            StringComparison.OrdinalIgnoreCase))
                            continue;
                        var simpleName = fullName.Split('.').Last().Split('+').Last();
                        if (string.Equals(resolvedName, simpleName,
                                StringComparison.OrdinalIgnoreCase) ||
                            string.Equals(resolvedName, fullName,
                                StringComparison.OrdinalIgnoreCase))
                        {
                            graph[srcFile].Add(targetFile);
                            break;
                        }
                    }
                }
                else
                {
                    // 回退：语法级匹配（缩小范围：仅类型声明位置）
                    var idName = ids.Identifier.Text;
                    foreach (var (fullName, targetFile) in typeNameToFile)
                    {
                        if (string.Equals(srcFile, targetFile,
                            StringComparison.OrdinalIgnoreCase))
                            continue;
                        var simpleName = fullName.Split('.').Last().Split('+').Last();
                        if (idName == simpleName)
                        {
                            // 排除 using 别名和 typeof
                            var parent = ids.Parent;
                            if (parent?.Kind() == SyntaxKind.UsingDirective ||
                                parent?.Kind() == SyntaxKind.TypeOfExpression)
                                continue;
                            // 仅当标识符位于类型位置时才视为依赖
                            var grandParent = parent?.Parent;
                            if (grandParent is ObjectCreationExpressionSyntax ||
                                grandParent is CastExpressionSyntax ||
                                grandParent is VariableDeclarationSyntax ||
                                grandParent is BaseListSyntax ||
                                parent is QualifiedNameSyntax)
                            {
                                graph[srcFile].Add(targetFile);
                                break;
                            }
                        }
                    }
                }
            }
        }

        // 通过基类/接口列表查找
        foreach (var classOrInt in root.DescendantNodes())
        {
            if (classOrInt is ClassDeclarationSyntax cd && cd.BaseList != null)
            {
                foreach (var baseType in cd.BaseList.Types)
                {
                    var btName = baseType.Type.ToString().Trim();
                    if (typeNameToFile.TryGetValue(btName, out var btFile) &&
                        !string.Equals(sourceFile, btFile, StringComparison.OrdinalIgnoreCase))
                    {
                        graph[sourceFile].Add(btFile);
                    }
                }
            }
            else if (classOrInt is InterfaceDeclarationSyntax id2 && id2.BaseList != null)
            {
                foreach (var baseType in id2.BaseList.Types)
                {
                    var btName = baseType.Type.ToString().Trim();
                    if (typeNameToFile.TryGetValue(btName, out var btFile) &&
                        !string.Equals(sourceFile, btFile, StringComparison.OrdinalIgnoreCase))
                    {
                        graph[sourceFile].Add(btFile);
                    }
                }
            }
        }
    }

    // 构建图输出
    var nodes = validFiles.Select(f => new { file = Path.GetFileName(f), path = f }).ToList<object>();
    var edges = new List<object>();

    foreach (var (src, deps) in graph)
    {
        foreach (var tgt in deps)
        {
            edges.Add(new { from_ = Path.GetFileName(src), to = Path.GetFileName(tgt), type = "type_reference" });
        }
    }

    result.graph = new { nodes, edges };
    result.totalFiles = validFiles.Length;
    result.totalDependencies = edges.Count;

    // 计算类型指标
    CalculateTypeMetrics(fileToTypes, typeNameToFile, graph, result);

    // 循环依赖检测
    DetectCycles(graph, result);

    // 孤儿类型检测（定义但未被其他文件引用的类型）
    DetectOrphanTypes(graph, fileToTypes, result);

    // 跨层依赖检测
    DetectCrossLayerViolations(validFiles, result);

    // God class 检测（通过成员计数）
    AnalyzeGodClasses(fileToTypes, syntaxTrees, compilation, result);

    // 调用链分析：未调用 public API + 接口无实现
    AnalyzeCallGraph(compilation, fileToTypes, result);
}

// ─── 调用链分析 ──────────────────────────────────────────────────────────────

void AnalyzeCallGraph(Compilation compilation,
    Dictionary<string, List<string>> fileToTypes, ProjectAnalysisResult result)
{
    var comparer = SymbolEqualityComparer.Default;

    // HTTP method attributes that indicate a public method is an API entry point
    var httpEntryAttributes = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
    {
        "HttpGet", "HttpPost", "HttpPut", "HttpDelete", "HttpPatch",
        "Route", "HttpGetAttribute", "HttpPostAttribute"
    };

    // ── Phase 1: collect all public method symbols ──
    var publicMethods = new Dictionary<ISymbol, (string file, string display)>(comparer);
    foreach (var tree in compilation.SyntaxTrees)
    {
        var model = compilation.GetSemanticModel(tree);
        var root = tree.GetRoot();
        var filePath = tree.FilePath;

        foreach (var cls in root.DescendantNodes().OfType<ClassDeclarationSyntax>())
        {
            var clsSym = model.GetDeclaredSymbol(cls) as INamedTypeSymbol;
            if (clsSym == null) continue;

            foreach (var method in cls.Members.OfType<MethodDeclarationSyntax>())
            {
                var mSym = model.GetDeclaredSymbol(method);
                if (mSym == null) continue;

                // Only public methods (not explicit interface implementations)
                if (mSym.DeclaredAccessibility != Accessibility.Public) continue;
                // Skip overrides, abstract, virtual (may be called via base)
                if (mSym.IsOverride || mSym.IsAbstract || mSym.IsVirtual) continue;
                // Skip property accessors, event add/remove, constructors, operators
                if (mSym.MethodKind is MethodKind.PropertyGet or MethodKind.PropertySet
                    or MethodKind.EventAdd or MethodKind.EventRemove
                    or MethodKind.Constructor or MethodKind.StaticConstructor
                    or MethodKind.UserDefinedOperator or MethodKind.Conversion
                    or MethodKind.Destructor) continue;
                // Skip methods with HTTP entry-point attributes
                bool isHttpEntry = method.AttributeLists
                    .SelectMany(al => al.Attributes)
                    .Any(a => httpEntryAttributes.Contains(a.Name.ToString()));
                if (isHttpEntry) continue;
                // Skip Main entry point
                if (mSym.Name == "Main" && mSym.IsStatic) continue;
                // Skip test methods
                bool isTest = method.AttributeLists
                    .SelectMany(al => al.Attributes)
                    .Any(a => a.Name.ToString() is "Test" or "Fact" or "Theory" or "TestMethod");
                if (isTest) continue;

                publicMethods[mSym] = (filePath, $"{clsSym.Name}.{mSym.Name}");
            }
        }
    }

    // ── Phase 2: collect all called method symbols ──
    var calledMethods = new HashSet<ISymbol>(comparer);
    foreach (var tree in compilation.SyntaxTrees)
    {
        var model = compilation.GetSemanticModel(tree);
        foreach (var invoke in tree.GetRoot().DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            try
            {
                var symInfo = model.GetSymbolInfo(invoke);
                if (symInfo.Symbol is IMethodSymbol target)
                {
                    calledMethods.Add(target);
                    // Also add the original definition (for interface calls resolved to derived)
                    if (target.OriginalDefinition is IMethodSymbol def && !comparer.Equals(def, target))
                        calledMethods.Add(def);
                }
            }
            catch { /* resolution failure — skip */ }
        }
    }

    // ── Phase 3: uncalled public methods ──
    foreach (var (sym, (file, display)) in publicMethods)
    {
        // Check if this method or its original definition is in called set
        if (calledMethods.Contains(sym)) continue;
        if (sym is IMethodSymbol ms && ms.OriginalDefinition != null &&
            calledMethods.Contains(ms.OriginalDefinition)) continue;

        result.uncalledPublicMethods.Add(new
        {
            method = display,
            file = Path.GetFileName(file),
            problem = $"public 方法 {display} 在所有输入文件中未被调用"
        });
    }

    // ── Phase 4: interfaces without implementation ──
    var allInterfaces = new HashSet<INamedTypeSymbol>(comparer);
    var implementedInterfaces = new HashSet<INamedTypeSymbol>(comparer);

    foreach (var tree in compilation.SyntaxTrees)
    {
        var model = compilation.GetSemanticModel(tree);
        var root = tree.GetRoot();

        foreach (var iface in root.DescendantNodes().OfType<InterfaceDeclarationSyntax>())
        {
            var iSym = model.GetDeclaredSymbol(iface) as INamedTypeSymbol;
            if (iSym != null) allInterfaces.Add(iSym);
        }

        foreach (var cls in root.DescendantNodes().OfType<ClassDeclarationSyntax>())
        {
            var cSym = model.GetDeclaredSymbol(cls) as INamedTypeSymbol;
            if (cSym == null) continue;
            foreach (var impl in cSym.AllInterfaces)
                implementedInterfaces.Add(impl);
        }
    }

    foreach (var iface in allInterfaces)
    {
        if (!implementedInterfaces.Contains(iface))
        {
            result.interfacesWithoutImpl.Add(new
            {
                type = iface.Name,
                file = "",
                problem = $"接口 {iface.Name} 在所有输入文件中无实现类"
            });
        }
    }

    // ── Phase 5: call graph output (informational) ──
    var callGraph = new List<object>();
    foreach (var (sym, (file, display)) in publicMethods)
    {
        var callers = new List<object>();
        foreach (var tree in compilation.SyntaxTrees)
        {
            var model = compilation.GetSemanticModel(tree);
            foreach (var invoke in tree.GetRoot().DescendantNodes().OfType<InvocationExpressionSyntax>())
            {
                try
                {
                    var si = model.GetSymbolInfo(invoke);
                    if (comparer.Equals(si.Symbol, sym))
                    {
                        var lineSpan = invoke.GetLocation().GetLineSpan();
                        callers.Add(new { file = Path.GetFileName(tree.FilePath), line = lineSpan.StartLinePosition.Line + 1 });
                    }
                }
                catch { }
            }
        }
        if (callers.Count > 0)
            callGraph.Add(new { method = display, callers });
    }
    result.callGraph = callGraph;
}

/// <summary>
/// 获取一个类型节点的外层命名空间
/// </summary>
string? GetNamespace(SyntaxNode root, SyntaxNode node)
{
    var parent = node.Parent;
    while (parent != null)
    {
        if (parent.Kind() == SyntaxKind.NamespaceDeclaration)
        {
            return ((NamespaceDeclarationSyntax)parent).Name.ToString();
        }
        if (parent.Kind() == SyntaxKind.FileScopedNamespaceDeclaration)
        {
            return ((FileScopedNamespaceDeclarationSyntax)parent).Name.ToString();
        }
        if (parent.Kind() == SyntaxKind.ClassDeclaration ||
            parent.Kind() == SyntaxKind.InterfaceDeclaration ||
            parent.Kind() == SyntaxKind.StructDeclaration)
        {
            parent = parent.Parent;
            continue;
        }
        break;
    }
    return null;
}

/// <summary>
/// 计算类型 fan-in/fan-out/instability/abstractness
/// </summary>
void CalculateTypeMetrics(Dictionary<string, List<string>> fileToTypes,
    Dictionary<string, string> typeNameToFile,
    Dictionary<string, HashSet<string>> graph,
    ProjectAnalysisResult result)
{
    var typeMetrics = new List<object>();
    var instabilityScores = new List<double>();

    foreach (var (typeName, declaringFile) in typeNameToFile)
    {
        var simpleName = typeName.Split('.').Last().Split('+').Last();

        // Fan-in: 其他文件引用此类型所在文件
        var fanIn = 0;
        foreach (var (src, deps) in graph)
        {
            if (string.Equals(src, declaringFile, StringComparison.OrdinalIgnoreCase)) continue;
            if (deps.Contains(declaringFile)) fanIn++;
        }

        // Fan-out: 此文件依赖多少其他文件
        var fanOut = graph.GetValueOrDefault(declaringFile, new HashSet<string>(StringComparer.OrdinalIgnoreCase)).Count;

        // Instability = Ce / (Ca + Ce)
        var instability = fanIn + fanOut == 0 ? 0.0 : (double)fanOut / (fanIn + fanOut);
        instabilityScores.Add(instability);

        // Abstractness: 估算（接口=1.0, 类=0.3, 结构体=0.2, 枚举=0.1）
        var abstractness = 0.0;
        if (typeName.StartsWith("I")) abstractness = 1.0;
        else if (typeName.Contains("+")) abstractness = 0.5; // 嵌套类型通常是内部实现
        else abstractness = 0.3;

        var distance = Math.Round(Math.Abs(instability + abstractness - 1), 3);

        typeMetrics.Add(new
        {
            type = typeName,
            file = Path.GetFileName(declaringFile),
            fanIn,
            fanOut,
            instability = Math.Round(instability, 3),
            abstractness = Math.Round(abstractness, 3),
            distance
        });
    }

    // 稳定抽象原则 (SAP): 高抽象度 + 高稳定性 = 理想类型
    var stableAbstractions = new List<object>();
    foreach (var m in typeMetrics)
    {
        dynamic tm = m;
        if (tm.abstractness > 0.5 && tm.instability < 0.5)
        {
            stableAbstractions.Add(new
            {
                type = tm.type,
                file = tm.file,
                abstractness = tm.abstractness,
                instability = tm.instability,
                distance = tm.distance,
                note = "Stable abstraction — good design anchor"
            });
        }
    }
    result.stableAbstractions = stableAbstractions;

    result.typeMetrics = typeMetrics;
    if (instabilityScores.Count > 0)
        result.projectInstability = Math.Round(instabilityScores.Average(), 3);

    // 架构违反
    result.architecturalViolations = typeMetrics
        .Select(m => (dynamic)m)
        .Where(m => m.distance > 0.2 && (m.instability > 0.6 || m.abstractness < 0.2))
        .Select(v => new
        {
            type = v.type,
            file = v.file,
            instability = v.instability,
            abstractness = v.abstractness,
            distance = v.distance,
            problem = v.instability > 0.6
                ? "Highly unstable concrete type (zone of pain)"
                : "Highly abstract but used by unstable dependents (zone of uselessness)"
        }).ToList<object>();
}

/// <summary>
/// Tarjan SCC 检测循环依赖
/// </summary>
void DetectCycles(Dictionary<string, HashSet<string>> graph, ProjectAnalysisResult result)
{
    var index = 0;
    var indices = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
    var lowlinks = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase);
    var onStack = new Dictionary<string, bool>(StringComparer.OrdinalIgnoreCase);
    var stack = new Stack<string>();
    var sccs = new List<List<string>>();

    foreach (var node in graph.Keys)
    {
        if (!indices.ContainsKey(node))
            StrongConnect(node);
    }

    void StrongConnect(string v)
    {
        indices[v] = index;
        lowlinks[v] = index;
        index++;
        stack.Push(v);
        onStack[v] = true;

        foreach (var w in graph.GetValueOrDefault(v, new HashSet<string>(StringComparer.OrdinalIgnoreCase)))
        {
            if (!indices.ContainsKey(w))
            {
                StrongConnect(w);
                lowlinks[v] = Math.Min(lowlinks[v], lowlinks[w]);
            }
            else if (onStack.GetValueOrDefault(w, false))
            {
                lowlinks[v] = Math.Min(lowlinks[v], indices[w]);
            }
        }

        if (lowlinks[v] == indices[v])
        {
            var scc = new List<string>();
            string w2;
            do
            {
                w2 = stack.Pop();
                onStack[w2] = false;
                scc.Add(w2);
            } while (w2 != v);
            sccs.Add(scc);
        }
    }

    foreach (var scc in sccs.Where(s => s.Count > 1))
    {
        var files = scc.Select(f => Path.GetFileName(f)).ToList();
        var namespaces = scc
            .Select(f => Path.GetDirectoryName(f)?.Replace("\\", "/").Split('/').LastOrDefault() ?? "")
            .Where(n => !string.IsNullOrEmpty(n))
            .Distinct()
            .ToList();

        result.cycles.Add(new
        {
            files,
            namespace_ = namespaces.FirstOrDefault() ?? "default",
            description = "循环依赖: " + string.Join(" → ", files)
        });
    }
}

/// <summary>
/// 孤儿类型检测：定义但未被其他文件引用的类型
/// </summary>
void DetectOrphanTypes(Dictionary<string, HashSet<string>> graph,
    Dictionary<string, List<string>> fileToTypes, ProjectAnalysisResult result)
{
    // 收集所有被引用的文件
    var referencedFiles = new HashSet<string>(StringComparer.OrdinalIgnoreCase);
    foreach (var (src, deps) in graph)
    {
        foreach (var dep in deps)
            referencedFiles.Add(dep);
    }

    foreach (var (file, typeNames) in fileToTypes)
    {
        // 如果该文件没有任何其他文件引用它，其中的类型就是孤儿类型
        if (referencedFiles.Contains(file)) continue;

        foreach (var typeName in typeNames)
        {
            var simpleName = typeName.Split('.').Last().Split('+').Last();
            result.orphanTypes.Add(new
            {
                type = simpleName,
                file = Path.GetFileName(file),
                problem = "Type defined but never referenced by other files"
            });
        }
    }
}

/// <summary>
/// 跨层依赖检测（基于目录约定）
/// </summary>
void DetectCrossLayerViolations(string[] files, ProjectAnalysisResult result)
{
    var layerOrder = new Dictionary<string, int>(StringComparer.OrdinalIgnoreCase)
    {
        ["Domain"] = 1,
        ["Application"] = 2,
        ["Services"] = 3,
        ["Infrastructure"] = 4,
        ["Data"] = 4,
        ["Presentation"] = 5,
        ["Controllers"] = 5,
        ["Models"] = 6
    };

    foreach (var file in files)
    {
        var dir = Path.GetDirectoryName(file)?.Replace("\\", "/") ?? "";
        var parts = dir.Split('/');
        var fileLayer = parts.LastOrDefault(p => layerOrder.ContainsKey(p)) ?? "";

        if (string.IsNullOrEmpty(fileLayer)) continue;
        var fileOrder = layerOrder[fileLayer];
        if (fileOrder == 0) continue;

        // 检查该文件引用了哪些其他层
        var depDirs = parts.Take(parts.Length - 1).ToArray();
        foreach (var dep in depDirs)
        {
            if (layerOrder.TryGetValue(dep, out var depOrder) && depOrder > 0)
            {
                if (fileOrder > depOrder && fileOrder - depOrder > 1)
                {
                    result.crossLayerViolations.Add(
                        Path.GetFileName(file) + ":" + fileLayer + " 依赖了低层模块 " + dep);
                }
            }
        }
    }
}

/// <summary>
/// God class 检测（通过成员计数 + 行数）
/// </summary>
void AnalyzeGodClasses(Dictionary<string, List<string>> fileToTypes,
    Dictionary<string, SyntaxTree> syntaxTrees, Compilation compilation,
    ProjectAnalysisResult result)
{
    var godClasses = new List<object>();

    foreach (var (file, typeNames) in fileToTypes)
    {
        var tree = syntaxTrees.GetValueOrDefault(file);
        if (tree == null) continue;

        var root = tree.GetRoot();

        foreach (var typeName in typeNames)
        {
            var simpleName = typeName.Split('.').Last().Split('+').Last();

            var methodCount = 0;
            var fieldCount = 0;
            var ctorCount = 0;

            var typeNode = root.DescendantNodes().FirstOrDefault(node =>
                (node.Kind() == SyntaxKind.ClassDeclaration ||
                 node.Kind() == SyntaxKind.InterfaceDeclaration ||
                 node.Kind() == SyntaxKind.StructDeclaration) &&
                (node is ClassDeclarationSyntax c ? c.Identifier.Text
                 : node is InterfaceDeclarationSyntax i ? i.Identifier.Text
                 : ((StructDeclarationSyntax)node).Identifier.Text) == simpleName);
            if (typeNode == null) continue;

            // ChildNodes() on ClassDeclaration returns braces/tokens;
            // members live in the Members collection.
            var members = typeNode switch
            {
                ClassDeclarationSyntax cd => cd.Members,
                InterfaceDeclarationSyntax id => id.Members,
                StructDeclarationSyntax sd => sd.Members,
                _ => default
            };

            foreach (var member in members)
            {
                if (member.Kind() == SyntaxKind.MethodDeclaration ||
                    member.Kind() == SyntaxKind.ConstructorDeclaration ||
                    member.Kind() == SyntaxKind.DestructorDeclaration ||
                    member.Kind() == SyntaxKind.PropertyDeclaration ||
                    member.Kind() == SyntaxKind.IndexerDeclaration ||
                    member.Kind() == SyntaxKind.EventDeclaration)
                    methodCount++;
                else if (member.Kind() == SyntaxKind.FieldDeclaration)
                    fieldCount++;
                if (member.Kind() == SyntaxKind.ConstructorDeclaration)
                    ctorCount++;
            }

            var totalMembers = methodCount + fieldCount;
            var span = typeNode.GetLocation().GetLineSpan().Span;
            var typeLineCount = span.End.Line - span.Start.Line + 1;
            if (totalMembers > 20 || fieldCount > 15 || typeLineCount > 500)
            {
                var problems = new List<string>();
                if (methodCount > 20) problems.Add($"Too many methods ({methodCount})");
                if (fieldCount > 15) problems.Add($"Too many fields ({fieldCount})");
                if (typeLineCount > 500) problems.Add($"Too many lines ({typeLineCount})");

                godClasses.Add(new
                {
                    type = typeName,
                    file = Path.GetFileName(file),
                    methodCount,
                    fieldCount,
                    ctorCount,
                    lineCount = typeLineCount,
                    totalMembers,
                    problem = string.Join("; ", problems)
                });
            }
        }
    }

    result.godClasses = godClasses;
}

class ProjectAnalysisResult
{
    [JsonPropertyName("tool")] public string tool { get; set; } = "csharp-project-analyzer";
    [JsonPropertyName("project_root")] public string projectRoot { get; set; } = "";
    [JsonPropertyName("total_files")] public int totalFiles { get; set; }
    [JsonPropertyName("total_dependencies")] public int totalDependencies { get; set; }
    [JsonPropertyName("project_instability")] public double projectInstability { get; set; }
    [JsonPropertyName("errors")] public List<string> errors { get; set; } = new();
    [JsonPropertyName("graph")] public object? graph { get; set; }
    [JsonPropertyName("type_metrics")] public List<object> typeMetrics { get; set; } = new();
    [JsonPropertyName("cycles")] public List<object> cycles { get; set; } = new();
    [JsonPropertyName("cross_layer_violations")] public List<string> crossLayerViolations { get; set; } = new();
    [JsonPropertyName("architectural_violations")] public List<object> architecturalViolations { get; set; } = new();
    [JsonPropertyName("god_classes")] public List<object> godClasses { get; set; } = new();
    [JsonPropertyName("stable_abstractions")] public List<object> stableAbstractions { get; set; } = new();
    [JsonPropertyName("orphan_types")] public List<object> orphanTypes { get; set; } = new();
    [JsonPropertyName("uncalled_public_methods")] public List<object> uncalledPublicMethods { get; set; } = new();
    [JsonPropertyName("interfaces_without_impl")] public List<object> interfacesWithoutImpl { get; set; } = new();
    [JsonPropertyName("call_graph")] public List<object>? callGraph { get; set; }
}
