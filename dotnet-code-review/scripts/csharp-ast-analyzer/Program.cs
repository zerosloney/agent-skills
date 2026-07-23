/// C# AST Analyzer — 基于 Roslyn 语法树的 C# 代码缺陷检测工具
/// 输入：C# 文件路径列表（空格分隔）
/// 输出：JSON 格式的诊断列表到 stdout
///
/// 用法: dotnet run -- <file1.cs> <file2.cs> ...
///
/// 比正则匹配的优势：
/// - 只检测实际代码中的模式（忽略注释和字符串字面量）
/// - 语义感知：.Result 只在 Task 类型上报，不是新的 Result 类
/// - 精确定位：检测到的是实际的方法声明/调用，不是字符串中的偶然匹配

using System.Text.Json;
using System.Text.Json.Serialization;
using System.Text.RegularExpressions;
using Microsoft.CodeAnalysis;
using Microsoft.CodeAnalysis.CSharp;
using Microsoft.CodeAnalysis.CSharp.Syntax;
using System.Linq;
using System.Collections.Generic;

var files = args.Where(f => File.Exists(f)).ToArray();
if (files.Length == 0)
{
    Console.Error.WriteLine("{\"error\": \"No valid .cs files provided\"}");
    return 1;
}

var diagnostics = new List<AstDiagnostic>();

foreach (var file in files)
{
    try
    {
        var code = File.ReadAllText(file);
        var tree = CSharpSyntaxTree.ParseText(code, new CSharpParseOptions(LanguageVersion.Latest));
        var root = await tree.GetRootAsync();

        var walker = new PatternWalker(file);
        walker.Visit(root);
        diagnostics.AddRange(walker.Diagnostics);
    }
    catch (Exception ex)
    {
        diagnostics.Add(new AstDiagnostic
        {
            File = file,
            Line = 1,
            Severity = "info",
            Code = "PARSE_ERROR",
            Message = $"文件无法解析为 C# 语法树: {ex.Message}"
        });
    }
}

var output = new
{
    tool = "csharp-ast-analyzer",
    runtime = Environment.Version.ToString(),
    files_scanned = files.Length,
    diagnostics
};

Console.WriteLine(JsonSerializer.Serialize(output, new JsonSerializerOptions
{
    WriteIndented = true,
    PropertyNamingPolicy = JsonNamingPolicy.CamelCase
}));

return 0;


/// <summary>
/// 语法树遍历器，检测代码中的已知反模式。
/// </summary>
class PatternWalker : CSharpSyntaxWalker
{
    private readonly string _file;
    public List<AstDiagnostic> Diagnostics { get; } = new();

    // BP023: 收集当前文件的 using Newtonsoft.Json* 命名空间导入（顺序安全：
    // using 在 CompilationUnit 顶部，CSharpSyntaxWalker 按声明顺序访问，
    // 故收集一定先于 VisitObjectCreationExpression）。
    private readonly HashSet<string> _newtonsoftUsings = new();

    // BP023: Newtonsoft.Json 核心类型的短名（用于 using 导入存在时的短名匹配）。
    // intentional-simple: 静态短名列表，覆盖最常用类型；非全量，罕见的会漏报。
    //   对 info 级建议规则可接受；全量覆盖需语义模型 + dll 引用，成本不符。
    private static readonly HashSet<string> _newtonsoftShortNames = new()
    {
        "JsonSerializerSettings", "JsonSerializer", "JsonReader", "JsonWriter",
        "JsonConvert", // static，但常见于 using Newtonsoft.Json 后的引用上下文
        "JObject", "JArray", "JToken", "JValue", "JProperty", // Newtonsoft.Json.Linq
    };

    public PatternWalker(string file)
    {
        _file = file;
    }

    // ── using 指令：记录 Newtonsoft.Json 命名空间导入（BP023 短名匹配前置）──
    public override void VisitUsingDirective(UsingDirectiveSyntax node)
    {
        var ns = node.Name.ToString();
        if (ns.StartsWith("Newtonsoft.Json", StringComparison.Ordinal))
            _newtonsoftUsings.Add(ns);
        base.VisitUsingDirective(node);
    }

    // ── async void 方法声明 ──
    public override void VisitMethodDeclaration(MethodDeclarationSyntax node)
    {
        if (node.Modifiers.Any(SyntaxKind.AsyncKeyword) &&
            node.ReturnType is PredefinedTypeSyntax pts &&
            pts.Keyword.IsKind(SyntaxKind.VoidKeyword))
        {
                        Add("LEGACY_async_void", "error",
                "async void 方法在异常时会直接崩溃进程，仅事件处理允许，推荐 async Task", node.GetLocation());
        }

        // R004: async void method with name ending in "Event" — likely event handler
        if (node.Modifiers.Any(SyntaxKind.AsyncKeyword) &&
            node.ReturnType is PredefinedTypeSyntax r4Pts &&
            r4Pts.Keyword.IsKind(SyntaxKind.VoidKeyword) &&
            node.Identifier.ValueText.EndsWith("Event"))
        {
            Add("LEGACY_async_void_event", "warning",
                "async void 事件处理器在异常时会崩溃进程，推荐改用 async Task 并确保异常处理", node.GetLocation());
        }

        // N002: method name PascalCase (skip property/event accessors & operators)
        bool isAccessor = node.Identifier.ValueText == "get" || node.Identifier.ValueText == "set"
                          || node.Identifier.ValueText == "add" || node.Identifier.ValueText == "remove";
        if (!isAccessor)
        {
            CheckPascalCase(node.Identifier, "LEGACY_N002_method_pascalcase", "方法名");
        }

        // ── test-method rules (T004 / T006) ──
        bool isTestMethod = HasTestMethodAttribute(node);
        if (isTestMethod)
        {
            // T006: async void test → should be async Task (swallows exceptions)
            if (node.Modifiers.Any(SyntaxKind.AsyncKeyword) &&
                node.ReturnType is PredefinedTypeSyntax rt &&
                rt.Keyword.IsKind(SyntaxKind.VoidKeyword))
            {
                Add("LEGACY_T006_async_void_test", "error",
                    "async void 测试方法会吞掉异常，测试框架无法捕获失败，应改为 async Task", node.GetLocation());
            }
            // T004: empty test method body
            if (node.Body is BlockSyntax block && block.Statements.Count == 0)
            {
                Add("LEGACY_T004_empty_test", "warning",
                    "空测试方法体——测试无任何断言，可能是占位或遗漏实现", node.GetLocation());
            }
            // T002/T003: test method without Assert.* calls
            if (node.Body != null)
            {
                bool hasAssert = node.Body.DescendantNodes()
                    .OfType<InvocationExpressionSyntax>()
                    .Any(inv => inv.Expression is MemberAccessExpressionSyntax assertMa &&
                                assertMa.Expression is IdentifierNameSyntax assertId &&
                                assertId.Identifier.Text == "Assert");
                if (!hasAssert)
                {
                    Add("LEGACY_T002_no_assert", "warning",
                        "测试方法 " + node.Identifier.Text + " 无 Assert 断言，测试通过不代表行为正确", node.GetLocation());
                }
                // T005: Assert.Equal(numericLiteral, ...)
                foreach (var inv in node.Body.DescendantNodes().OfType<InvocationExpressionSyntax>())
                {
                    if (inv.Expression is MemberAccessExpressionSyntax eqMa &&
                        eqMa.Expression is IdentifierNameSyntax eqId &&
                        eqId.Identifier.Text == "Assert" &&
                        (eqMa.Name.Identifier.Text == "Equal" || eqMa.Name.Identifier.Text == "AreEqual") &&
                        inv.ArgumentList.Arguments.Count > 0)
                    {
                        var firstArg = inv.ArgumentList.Arguments[0].Expression;
                        if (firstArg.IsKind(SyntaxKind.NumericLiteralExpression))
                        {
                            Add("LEGACY_T005_hardcoded_test_data", "info",
                                "Assert.Equal 使用硬编码数字字面量，建议用命名常量提升可读性", inv.GetLocation());
                        }
                    }
                    // T008: Thread.Sleep(magicNumber) in tests
                    if (inv.Expression is MemberAccessExpressionSyntax sleepMa &&
                        sleepMa.Expression is IdentifierNameSyntax sleepId &&
                        sleepId.Identifier.Text == "Thread" &&
                        sleepMa.Name.Identifier.Text == "Sleep" &&
                        inv.ArgumentList.Arguments.Count > 0)
                    {
                        var sleepArg = inv.ArgumentList.Arguments[0].Expression;
                        if (sleepArg.IsKind(SyntaxKind.NumericLiteralExpression) &&
                            sleepArg is LiteralExpressionSyntax sleepLit &&
                            sleepLit.Token.Value is int sleepVal && sleepVal >= 10)
                        {
                            Add("LEGACY_T008_test_magic_sleep", "info",
                                $"Thread.Sleep({sleepVal}) 硬编码延时使测试变慢且不稳定，建议用命名常量或取消依赖", inv.GetLocation());
                        }
                    }
                }
            }
        }

        // T010: test method creates a resource via `new` but the body has no
        // using / try-finally / IDisposable-style cleanup. Heuristic: detect
        // ObjectCreationExpressionSyntax inside the test method body that is
        // NOT wrapped in a using statement AND not followed by a Dispose() /
        // Close() / cleanup-style call in the same block.
        if (isTestMethod && node.Body is BlockSyntax t010Body)
        {
            var creations = t010Body.DescendantNodes()
                .OfType<ObjectCreationExpressionSyntax>()
                .ToList();
            if (creations.Count > 0)
            {
                // Check 1: any creation is inside a using statement (OK).
                bool anyInUsing = creations.Any(c =>
                    c.Ancestors().Any(a => a is UsingStatementSyntax));
                // Check 2: any creation is in a try block that has a finally
                // with cleanup calls (heuristic: finally exists and has
                // statements — we don't try to validate Dispose() presence to
                // avoid false negatives).
                bool anyInTryFinally = t010Body.DescendantNodes()
                    .OfType<TryStatementSyntax>()
                    .Any(t => t.Finally != null && t.Finally.Block?.Statements.Count > 0);
                // Check 3: body has a [TestCleanup]/[TestTearDown] method on
                // the same class (instance cleanup, not in-body). Detected
                // later via class-level walk; here we conservatively skip
                // if the class has such a method.
                bool classHasTeardownAttribute = false;
                var classDecl = node.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
                if (classDecl != null)
                {
                    classHasTeardownAttribute = classDecl.Members
                        .OfType<MethodDeclarationSyntax>()
                        .Any(m => HasTestTeardownAttribute(m));
                }

                if (!anyInUsing && !anyInTryFinally && !classHasTeardownAttribute)
                {
                    var firstCreation = creations[0];
                    Add("LEGACY_T010_no_teardown", "info",
                        "测试方法内创建了 " + firstCreation.Type + " 但未发现 using/try-finally/IDisposable 清理"
                        + "，可能造成资源泄漏或测试间状态污染",
                        firstCreation.GetLocation());
                }
            }
        }

        // T001: missing test attribute. A non-test public method (no
        // [Fact]/[Test]/[Theory]) inside a class that *does* contain at least
        // one test method is suspicious — it might be a test helper that
        // needs a [Test]/[Fact] attribute, or a forgotten test. Heuristic
        // narrows to public non-static methods to avoid noise on
        // infrastructure / framework code.
        if (!isTestMethod &&
            node.Modifiers.Any(SyntaxKind.PublicKeyword) &&
            !node.Modifiers.Any(SyntaxKind.StaticKeyword))
        {
            var classDecl = node.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
            if (classDecl != null)
            {
                bool classHasAnyTest = classDecl.Members
                    .OfType<MethodDeclarationSyntax>()
                    .Any(m => HasTestMethodAttribute(m));
                if (classHasAnyTest)
                {
                    // Skip if this method is a known test-helper attribute
                    // (TestInitialize/TestSetup/OneTimeSetUp/etc.) or the
                    // Dispose cleanup we already detected.
                    bool isTestLifecycleMethod = HasTestTeardownAttribute(node)
                        || HasTestInitializeAttribute(node);
                    if (!isTestLifecycleMethod)
                    {
                        Add("LEGACY_T001_missing_test_attribute", "info",
                            "公共方法 '" + node.Identifier.Text + "' 在含测试方法的类中，但本身无 [Test]/[Fact]/[Theory] 标记"
                            + "——可能是遗漏的测试或需 [TestInitialize] 等生命周期标记",
                            node.GetLocation());
                    }
                }
            }
        }

        base.VisitMethodDeclaration(node);
    }

    private static bool HasTestInitializeAttribute(MethodDeclarationSyntax node)
    {
        foreach (var al in node.AttributeLists)
            foreach (var a in al.Attributes)
            {
                var name = a.Name.ToString();
                if (name == "TestInitialize" || name == "TestSetUp" ||
                    name == "SetUp" || name == "OneTimeSetUp" ||
                    name == "FixtureSetUp" || name == "BeforeAll" ||
                    name == "BeforeEach" || name == "Constructor")
                    return true;
            }
        return false;
    }

    private static bool HasTestTeardownAttribute(MethodDeclarationSyntax node)
    {
        foreach (var al in node.AttributeLists)
            foreach (var a in al.Attributes)
            {
                var name = a.Name.ToString();
                if (name == "TestCleanup" || name == "TestTearDown" ||
                    name == "TearDown" || name == "ClassCleanup" ||
                    name == "ClassTearDown" || name == "OneTimeTearDown" ||
                    name == "FixtureTearDown" || name == "AfterAll" ||
                    name == "AfterEach" || name == "Dispose")
                    return true;
            }
        return false;
    }

    // ── ObjectCreationExpression: 统一处理所有 new 表达式 ──
    public override void VisitObjectCreationExpression(ObjectCreationExpressionSyntax node)
    {
        var typeName = node.Type.ToString();

        // SH002: insecure RNG — `new Random()` (predictable, not for security)
        if (typeName == "Random" || typeName == "System.Random")
        {
            Add("LEGACY_SH002_insecure_random", "warning",
                "new Random() 不适用于安全场景（可预测），密钥/token 生成应用 RandomNumberGenerator", node.GetLocation());
            Add("LEGACY_BP022_random_shared", "info",
                "new Random() 可替换为 Random.Shared——线程安全、性能更好、无需显式释放", node.GetLocation());
        }

        // SH005/SEC019: weak/deprecated crypto — MD5/SHA1/DES/TripleDES/RC2
        switch (typeName)
        {
            case "MD5":
            case "System.Security.Cryptography.MD5":
            case "SHA1":
            case "System.Security.Cryptography.SHA1":
            case "MD5CryptoServiceProvider":
            case "SHA1CryptoServiceProvider":
                Add("LEGACY_SH005_weak_crypto", "warning",
                    $"{typeName} 是弱/已弃用的加密算法（存在碰撞/安全性问题），推荐 SHA256+ 或现代算法", node.GetLocation());
                break;
            case "DES":
            case "System.Security.Cryptography.DES":
            case "TripleDES":
            case "System.Security.Cryptography.TripleDES":
            case "RC2":
            case "DESCryptoServiceProvider":
            case "TripleDESCryptoServiceProvider":
            case "RC2CryptoServiceProvider":
                Add("LEGACY_SH005_weak_crypto", "warning",
                    $"{typeName} 是已弃用的对称加密算法，推荐 AES (Aes.Create())", node.GetLocation());
                break;
        }

        switch (typeName)
        {
            // Security
            case "BinaryFormatter":
            case "System.Runtime.Serialization.Formatters.Binary.BinaryFormatter":
                Add("LEGACY_BinaryFormatter", "error",
                    "BinaryFormatter 反序列化存在安全风险（CVE 多个）, 推荐替换为 JSON/Protobuf 序列化",
                    node.GetLocation());
                break;

            case "SqlCommand":
            case "System.Data.SqlClient.SqlCommand":
            case "Microsoft.Data.SqlClient.SqlCommand":
            case "OleDbCommand":
            case "System.Data.OleDb.OleDbCommand":
            case "MySqlCommand":
            case "MySql.Data.MySqlClient.MySqlCommand":
                var arg = node.ArgumentList.Arguments.FirstOrDefault();
                if (arg != null && arg.Expression is BinaryExpressionSyntax bin &&
                    bin.OperatorToken.IsKind(SyntaxKind.PlusToken))
                {
                    Add("LEGACY_SqlCommand_Concat", "error",
                        $"{typeName} 使用字符串拼接，存在 SQL 注入风险",
                        node.GetLocation());
                }
                break;

            case "XmlDocument":
            case "System.Xml.XmlDocument":
                Add("LEGACY_XmlDocument", "warning",
                    "XmlDocument 默认启用 DTD，存在 XXE 风险",
                    node.GetLocation());
                break;

            case "CSharpCodeProvider":
            case "Microsoft.CSharp.CSharpCodeProvider":
                Add("LEGACY_CSharpCodeProvider", "error",
                    "CSharpCodeProvider 动态编译存在安全风险，推荐预编译程序集",
                    node.GetLocation());
                break;

            // SEC009: DirectorySearcher with string concatenation → LDAP injection
            case "DirectorySearcher":
            case "System.DirectoryServices.DirectorySearcher":
                var dsArg = node.ArgumentList?.Arguments.FirstOrDefault();
                if (dsArg != null && dsArg.Expression is BinaryExpressionSyntax dsBin &&
                    dsBin.OperatorToken.IsKind(SyntaxKind.PlusToken))
                {
                    Add("LEGACY_DirectorySearcher_Concat", "error",
                        "DirectorySearcher 使用字符串拼接，存在 LDAP 注入风险",
                        node.GetLocation());
                }
                break;

            case "Thread":
                Add("LEGACY_Thread_New", "warning",
                    "Thread 直接创建可能影响线程池，推荐 Task.Run",
                    node.GetLocation());
                break;

            // Best Practice
            case "WebClient":
            case "System.Net.WebClient":
                Add("LEGACY_WebClient", "warning",
                    "WebClient 已过时，推荐使用 HttpClient（using 正确释放资源）",
                    node.GetLocation());
                break;

            case "HttpClient":
            case "System.Net.Http.HttpClient":
                Add("LEGACY_HttpClient_New", "warning",
                    "new HttpClient() 可能导致 socket 耗尽，推荐使用 IHttpClientFactory",
                    node.GetLocation());
                break;

            case "Hashtable":
            case "System.Collections.Hashtable":
                Add("LEGACY_Hashtable", "info",
                    "Hashtable 已过时，推荐 Dictionary<TKey,TValue>",
                    node.GetLocation());
                break;

            case "ArrayList":
            case "System.Collections.ArrayList":
                Add("LEGACY_ArrayList", "info",
                    "ArrayList 已过时，推荐 List<T>",
                    node.GetLocation());
                break;

            case "DataSet":
            case "System.Data.DataSet":
                Add("LEGACY_DataSet", "info",
                    "DataSet/DataTable 内存占用高，推荐 ORM (EF Core/Dapper)",
                    node.GetLocation());
                break;

            // ── Windows-only types — crash on Linux/macOS at runtime.
            // These have cross-platform replacements; flag for review in
            // cross-platform projects. Engine filters by TargetFramework.
            case "EventLog":
            case "System.Diagnostics.EventLog":
                Add("LEGACY_WIN03_event_log", "warning",
                    "EventLog 仅 Windows 可用——跨平台项目应使用日志框架（Serilog）或 OpenTelemetry",
                    node.GetLocation());
                break;

            case "ManagementClass":
            case "System.Management.ManagementClass":
            case "ManagementObject":
            case "System.Management.ManagementObject":
            case "ManagementObjectSearcher":
            case "System.Management.ManagementObjectSearcher":
                Add("LEGACY_WIN04_wmi", "warning",
                    "System.Management (WMI) 仅 Windows 可用——跨平台项目应使用 CLI 包装或平台特定抽象",
                    node.GetLocation());
                break;

            // System.Drawing.Common — Windows-only since .NET 6 (needs
            // libgdiplus on Linux, deprecated). Common GDI+ types.
            case "Bitmap":
            case "System.Drawing.Bitmap":
            case "Graphics":
            case "System.Drawing.Graphics":
            case "Image":
            case "System.Drawing.Image":
            case "Icon":
            case "System.Drawing.Icon":
                Add("LEGACY_WIN02_system_drawing", "warning",
                    "System.Drawing.Common 在 .NET 6+ 仅 Windows 支持（Linux 需 libgdiplus 且已弃用）——跨平台项目应换 ImageSharp/SkiaSharp/Magick.NET",
                    node.GetLocation());
                break;

            // Password hashing
            case "SHA1CryptoServiceProvider":
            case "SHA256CryptoServiceProvider":
            case "SHA384CryptoServiceProvider":
            case "SHA512CryptoServiceProvider":
            case "SHA1Managed":
            case "SHA256Managed":
            case "SHA384Managed":
            case "SHA512Managed":
                Add("LEGACY_SHA_Password", "warning",
                    "SHA* 不适合密码哈希，推荐使用 Rfc2898DeriveBytes (PBKDF2)、BCrypt.Net 或 Argon2",
                    node.GetLocation());
                break;
        }

        // BP023: Newtonsoft.Json → System.Text.Json modernization
        // 匹配：① 全限定名 Newtonsoft.Json.* ② 文件存在 using Newtonsoft.Json* + 已知核心类型短名
        if (typeName.StartsWith("Newtonsoft.Json.", StringComparison.Ordinal) ||
            (_newtonsoftUsings.Count > 0 && _newtonsoftShortNames.Contains(typeName)))
        {
            Add("LEGACY_BP023_system_text_json", "info",
                "Newtonsoft.Json 未使用 .NET 内置的 System.Text.Json——性能更好、支持 source-gen、AOT 友好",
                node.GetLocation());
        }

                        // P008: new Regex(...) not cached (excluding static field declarations)
        if (typeName == "Regex")
        {
            // Exclude when declared as a static field (cached pattern):
            // `private static readonly Regex _r = new Regex(...);`
            bool isStaticField = node.Ancestors().OfType<FieldDeclarationSyntax>()
                .Any(f => f.Modifiers.Any(SyntaxKind.StaticKeyword));
            if (!isStaticField)
            {
                Add("LEGACY_P008_regex_not_cached", "info",
                    "new Regex() 每次实例化都重新编译模式，建议缓存为 static readonly 或用 Regex.CompileToAssembly", node.GetLocation());
            }
        }

        // P012: new string(char, int) → unnecessary allocation
        if (typeName == "string" && node.ArgumentList.Arguments.Count >= 2)
        {
            bool isCharInt = node.ArgumentList.Arguments[0].Expression.IsKind(SyntaxKind.CharacterLiteralExpression);
            if (isCharInt)
            {
                Add("LEGACY_new_string_char_int", "info",
                    "new string(char, int) 可能不必要，可考虑用 string 字面量或 StringBuilder", node.GetLocation());
            }
        }

        // ── Concurrency primitives (R011-R014): flag for review, low false-positive ──
        switch (typeName)
        {
            case "Mutex":
            case "System.Threading.Mutex":
                Add("LEGACY_R011_mutex", "info",
                    "Mutex 用于跨进程同步，确认是否真需跨进程（同进程优先 lock/Monitor）", node.GetLocation());
                break;
            case "Semaphore":
            case "System.Threading.Semaphore":
            case "SemaphoreSlim":
            case "System.Threading.SemaphoreSlim":
                Add("LEGACY_R012_semaphore", "info",
                    "Semaphore(Slim) 用于限流/协调，确认释放逻辑正确（建议 using 或 try/finally Release）", node.GetLocation());
                break;
            case "AutoResetEvent":
            case "System.Threading.AutoResetEvent":
            case "ManualResetEvent":
            case "System.Threading.ManualResetEvent":
            case "ManualResetEventSlim":
            case "System.Threading.ManualResetEventSlim":
                Add("LEGACY_R013_event_wait_handle", "info",
                    "Auto/ManualResetEvent 用于线程信号，确认 Set/WaitOne 配对且无死锁风险", node.GetLocation());
                break;
            case "CancellationTokenSource":
            case "System.Threading.CancellationTokenSource":
                Add("LEGACY_R014_cancellation_token", "info",
                    "CancellationTokenSource 实现 IDisposable，确认在使用后 Dispose（建议 using）", node.GetLocation());
                break;
            case "TcpClient":
            case "System.Net.Sockets.TcpClient":
            case "UdpClient":
            case "System.Net.Sockets.UdpClient":
                Add("LEGACY_SH009_insecure_network", "warning",
                    "TcpClient/UdpClient 不加密，生产环境应使用 TLS（SslStream）或 HTTPS", node.GetLocation());
                break;
            case "HttpCookie":
            case "System.Web.HttpCookie":
                Add("LEGACY_SH011_cookie_no_secure", "info",
                    "新建 HttpCookie，确认设置 Secure=true 和 HttpOnly=true 防止窃取", node.GetLocation());
                break;
        }

        base.VisitObjectCreationExpression(node);
    }

    // ── MemberAccessExpression: HttpContext.Current / Thread.Abort / AppDomain.CreateDomain ──
    // NOTE: .Result / .Wait() detection lives in the BP007 block below — it gates on a
    // Task-ish receiver to avoid false positives. Do NOT re-add a bare ".Result" rule:
    // the previous "LEGACY_.Result" id contained a dot, broke by-rule JSON grouping,
    // and fired on every member named Result (e.g. calculation results), not just Task.Result.
    public override void VisitMemberAccessExpression(MemberAccessExpressionSyntax node)
    {
        var name = node.Name.Identifier.Text;

        if (name == "Current" && node.Expression.ToString() == "HttpContext")
        {
            Add("LEGACY_HttpContext.Current", "warning",
                "HttpContext.Current 在异步代码中可能为 null，推荐通过方法参数传递",
                node.GetLocation());
        }
        else if (name == "Abort" && node.Expression.ToString() == "Thread")
        {
            Add("LEGACY_Thread.Abort", "error",
                "Thread.Abort 不可预测，推荐 CancellationToken", node.GetLocation());
        }
        else if (name == "CreateDomain" && node.Expression.ToString() == "AppDomain")
        {
            Add("LEGACY_AppDomain.CreateDomain", "warning",
                "AppDomain.CreateDomain 在 .NET Core+ 中受限，推荐 AssemblyLoadContext",
                node.GetLocation());
        }
        else if (name == "Filter" && node.Expression.ToString().Contains("DirectorySearcher"))
        {
            var parent = node.Parent;
            if (parent is AssignmentExpressionSyntax assign &&
                assign.Right is BinaryExpressionSyntax bin &&
                bin.OperatorToken.IsKind(SyntaxKind.PlusToken))
            {
                Add("LEGACY_LDAP_Concat", "error",
                    "DirectorySearcher.Filter 使用字符串拼接，存在 LDAP 注入风险",
                    node.GetLocation());
            }
        }

        // T016/T017: non-injectable environment dependencies in production code.
        // These hurt testability. Detected as member accesses on static
        // environment surfaces: DateTime.Now/UtcNow/Today (T016) and File.* /
        // Path.* / Directory.* static IO (T017). Intentionally conservative
        // (heuristic, may false-positive) and reported at info level.
        if (node.Expression is IdentifierNameSyntax envId)
        {
            var owner = envId.Identifier.Text;
            if (owner == "DateTime" &&
                (name == "Now" || name == "UtcNow" || name == "Today"))
            {
                Add("LEGACY_T016_datetime_now", "info",
                    $"{owner}.{name} 隐式依赖系统时钟，难以测试；建议注入 IDateTimeProvider 或 IClock 抽象", node.GetLocation());
                Add("LEGACY_BP024_datetime_modern", "info",
                    $"{owner}.{name} 考虑使用 DateTimeOffset（时区无关）或 DateOnly/TimeOnly（.NET 6+ 日期/时间分离）", node.GetLocation());
            }
            else if ((owner == "File" || owner == "Directory" || owner == "Path") &&
                     IsStaticIoMember(name))
            {
                Add("LEGACY_T017_static_io", "info",
                    $"{owner}.{name} 直接依赖静态文件系统 API，难以测试；建议封装为 IFileSystem 抽象注入", node.GetLocation());
            }
        }

        // BP007: .Result / .Wait() sync-block on a Task-ish receiver.
        // Heuristic on naming only (this walker has no SemanticModel). Flag only
        // receivers that plausibly hold a Task: an explicit Task/Async suffix, or
        // the conventional short Task variable names `t`/`task`. This deliberately
        // avoids the previous broad `char.IsLower(receiver[0])` branch, which
        // flagged every `local.Result` property access (high FP on calculation
        // results). False negatives on unconventionally-named Task locals are
        // acceptable; the authoritative signal is the regex rule BP007 + the
        // Roslyn semantic analyzer's type-aware checks elsewhere.
        {
            var bpName = node.Name.Identifier.Text;
            if (bpName == "Result" || bpName == "Wait")
            {
                string receiver = node.Expression.ToString();
                bool looksAsync = receiver.EndsWith("Task", StringComparison.Ordinal)
                                  || receiver.EndsWith("Async", StringComparison.Ordinal)
                                  || receiver == "task"
                                  || receiver == "t";
                if (looksAsync)
                {
                    Add("LEGACY_BP007_sync_wait", "warning",
                        $".{bpName} 同步阻塞异步操作，可能导致死锁/线程池耗尽，推荐 await", node.GetLocation());
                }
            }
        }

        // ── WIN01: Microsoft.Win32.Registry — Windows-only (no cross-platform
        // equivalent; Linux uses /proc or a config file). Flags static member
        // access like Registry.LocalMachine / Registry.GetValue(...).
        // Covers both bare `Registry.X` and fully-qualified `Microsoft.Win32.Registry.X`.
        {
            string receiver = node.Expression.ToString();
            if (receiver == "Registry" || receiver.EndsWith(".Registry", StringComparison.Ordinal))
            {
                Add("LEGACY_WIN01_registry", "warning",
                    "Microsoft.Win32.Registry 仅 Windows 可用——跨平台项目应使用配置文件（appsettings.json）/环境变量/IOptions<T>",
                    node.GetLocation());
            }
        }

        // ── SEC022: JWT misconfiguration — ValidateToken without validation parameters.
        if (name == "ValidateToken")
        {
            // Check if the call has a TokenValidationParameters argument
            bool hasValidationParams = false;
            if (node.Parent is InvocationExpressionSyntax inv)
            {
                hasValidationParams = inv.ArgumentList.Arguments.Count >= 2;
            }
            if (!hasValidationParams)
            {
                Add("LEGACY_SEC022_jwt_misuse", "error",
                    "JWT 验证可能缺少 TokenValidationParameters（ValidateIssuer/ValidateAudience/ValidateLifetime/ValidateIssuerSigningKey），存在签名绕过或过期忽略风险", node.GetLocation());
            }
        }

        // ── SH006: ServicePointManager.SecurityProtocol / CheckCertificateRevocationList ──
        if (node.Expression is IdentifierNameSyntax spmId && spmId.Identifier.Text == "ServicePointManager")
        {
            if (name == "SecurityProtocol" || name == "CheckCertificateRevocationList")
            {
                Add("LEGACY_SH006_insecure_ssl_tls", "warning",
                    $"ServicePointManager.{name} 配置影响 TLS 安全，确认使用 TLS 1.2+ 且启用证书吊销检查", node.GetLocation());
            }
        }

        base.VisitMemberAccessExpression(node);
    }

    // ── VariableDeclaration: WebClient type declaration ──
    public override void VisitVariableDeclaration(VariableDeclarationSyntax node)
    {
        var typeName = node.Type.ToString();
        if (typeName is "WebClient" or "System.Net.WebClient")
        {
            Add("LEGACY_WebClient", "warning",
                "WebClient 已过时，推荐使用 HttpClient（using 正确释放资源）",
                node.GetLocation());
        }

        base.VisitVariableDeclaration(node);
    }

    // ── LockStatement: lock(this) / lock(typeof(...)) ──
    public override void VisitLockStatement(LockStatementSyntax node)
    {
        var expr = node.Expression.ToString();
        if (expr == "this")
        {
            Add("LEGACY_lock_this", "warning",
                "lock(this) 允许外部代码干扰，推荐 lock 专用私有对象",
                node.GetLocation());
        }
        else if (expr.StartsWith("typeof("))
        {
            Add("LEGACY_lock_typeof", "warning",
                "lock(typeof(T)) 允许外部代码干扰，推荐 lock 专用私有对象",
                node.GetLocation());
        }

        // R009: lock(string literal) — string interning allows external interference
        else if (node.Expression is LiteralExpressionSyntax lit &&
                 lit.IsKind(SyntaxKind.StringLiteralExpression))
        {
            Add("LEGACY_lock_typeof", "warning",
                "lock(字符串字面量) 因字符串驻留机制允许外部代码干扰，推荐 lock 专用私有对象",
                node.GetLocation());
        }

        // R005: nested lock → deadlock risk
        if (node.Ancestors().OfType<LockStatementSyntax>().Any())
        {
            Add("LEGACY_R005_nested_lock", "warning",
                "嵌套 lock 可能导致死锁，推荐检查锁顺序或使用 SemaphoreSlim",
                node.GetLocation());
        }

        // R025: lock statement containing await — deadlock risk
        if (node.Statement != null &&
            node.Statement.DescendantNodes().OfType<AwaitExpressionSyntax>().Any())
        {
            Add("LEGACY_R025_lock_await", "error",
                "lock 内含 await 可能导致死锁——锁在 await 期间不释放，其他线程阻塞等待。改用 SemaphoreSlim(1,1).WaitAsync() 或重构为无锁异步",
                node.GetLocation());
        }

        base.VisitLockStatement(node);
    }

    // ── CatchClause: empty catch + catch(Exception) ──
    public override void VisitCatchClause(CatchClauseSyntax node)
    {
        // 修复: Body 改为 Block (Roslyn 4.12+ API 变更)
        if (node.Block is BlockSyntax block && block.Statements.Count == 0)
        {
            Add("LEGACY_empty_catch", "warning",
                "空 catch 块会静默吞掉异常，推荐记录日志或重新抛出",
                node.GetLocation());
        }

        if (node.Declaration != null && node.Declaration.Type.ToString() == "Exception")
        {
            Add("LEGACY_catch_exception", "warning",
                "捕获 Exception 过宽，推荐捕获具体异常类型",
                node.GetLocation());
        }

        // R018: catch(OperationCanceledException) without re-throw
        if (node.Declaration != null)
        {
            var dt = node.Declaration.Type.ToString();
            if (dt == "OperationCanceledException" || dt == "System.OperationCanceledException")
            {
                bool rethrows = node.Block?.DescendantNodes()
                    .OfType<ThrowStatementSyntax>().Any() ?? false;
                if (!rethrows)
                {
                    Add("LEGACY_R018_opc_not_rethrow", "info",
                        "catch(OperationCanceledException) 未重新抛出，可能掩盖取消信号", node.GetLocation());
                }
            }
        }

        // R003: non-empty catch without throw or logging → swallowed exception
        if (node.Block is BlockSyntax rb && rb.Statements.Count > 0)
        {
            bool hasThrow = rb.DescendantNodes().OfType<ThrowStatementSyntax>().Any();
            bool hasLogCall = rb.DescendantNodes()
                .OfType<InvocationExpressionSyntax>()
                .Any(inv =>
                {
                    // Resolve the called method name from either a member access
                    // (logger.LogError, _logSer.InsertExternalLogInfo) or a bare
                    // identifier call (LogError(...)).
                    string name = inv.Expression switch
                    {
                        MemberAccessExpressionSyntax ma => ma.Name.Identifier.Text,
                        IdentifierNameSyntax id => id.Identifier.Text,
                        _ => "",
                    };
                    if (name.Length == 0) return false;
                    // Exact allowlist: Microsoft.Extensions.Logging / Console /
                    // common logger verbs.
                    if (name is "Log" or "LogError" or "LogWarning"
                        or "LogInformation" or "LogDebug" or "Error" or "WriteLine"
                        or "LogCritical" or "LogTrace")
                        return true;
                    // Heuristic: business frameworks name their logging methods
                    // freely (InsertExternalLogInfo, SaveLog, RecordLog, WriteLog,
                    // AddLog, ...). Treat a call whose name contains "log" or
                    // "trace" (case-insensitive) as logging. Conservative: "error"
                    // / "warning" / "info" alone are NOT included here to avoid
                    // matching unrelated methods (e.g. GetErrorInfo).
                    var lower = name.ToLowerInvariant();
                    return lower.Contains("log") || lower.Contains("trace");
                });
            if (!hasThrow && !hasLogCall)
            {
                Add("LEGACY_R003_catch_swallow", "warning",
                    "catch 块未重新抛出或记录日志，异常可能被静默吞咽", node.GetLocation());
            }
        }

        // R020: catch(AggregateException) — should handle inner exceptions
        if (node.Declaration != null)
        {
            var dt = node.Declaration.Type.ToString();
            if (dt == "AggregateException" || dt == "System.AggregateException")
            {
                Add("LEGACY_catch_AggregateException", "info",
                    "catch(AggregateException) 应遍历 .InnerExceptions 处理所有嵌套异常", node.GetLocation());
            }
        }

        // ── Catch block that returns exception details to caller ──
        // Detects: catch (Exception e) { return e.ToString(); }
        // Found in both CRS and ASS Jamtc frameworks (PlatformSynchronizer etc.)
        // Exposes internal exception details → information disclosure + breaks chain
        if (node.Block is BlockSyntax cbBlock && node.Declaration != null)
        {
            var catchVarName = node.Declaration.Identifier.Text;
            var returnStmts = cbBlock.DescendantNodes().OfType<ReturnStatementSyntax>();
            foreach (var ret in returnStmts)
            {
                // Check if return value references the catch variable
                var identifiers = ret.DescendantNodes().OfType<IdentifierNameSyntax>();
                bool refsCatchVar = identifiers.Any(id => id.Identifier.Text == catchVarName);
                if (refsCatchVar)
                {
                    // Check for .ToString(), .Message, .StackTrace (exception detail exposure)
                    var memberAccesses = ret.DescendantNodes().OfType<MemberAccessExpressionSyntax>();
                    bool exposesDetail = memberAccesses.Any(ma =>
                        ma.Name.Identifier.Text is "ToString" or "Message" or "StackTrace"
                            or "InnerException" or "Source" or "TargetSite");
                    if (exposesDetail)
                    {
                        Add("LEGACY_Catch_Return_Exception", "warning",
                            $"catch 块将异常详情 ({catchVarName}) 返回给调用方，暴露内部实现细节且破坏异常处理链",
                            node.GetLocation());
                        break;
                    }
                }
            }
        }

        base.VisitCatchClause(node);
    }

    // ── ParenthesizedLambdaExpression: async void lambda + async 无 await ──
    public override void VisitParenthesizedLambdaExpression(ParenthesizedLambdaExpressionSyntax node)
    {
        if (node.Modifiers.Any(SyntaxKind.AsyncKeyword) &&
            node.ReturnType is PredefinedTypeSyntax pts &&
            pts.Keyword.IsKind(SyntaxKind.VoidKeyword))
        {
            Add("LEGACY_async_void_lambda", "warning",
                "async void lambda 异常会传播到调用方堆栈，推荐 async Task 或 async ValueTask",
                node.GetLocation());
            // R026: async void lambda passed as an argument — fire-and-forget
            // with lost exceptions. More dangerous than a bare async void
            // declaration because the consumer (e.g. Task.Run, event add) has
            // no way to observe the returned Task. Only fires when the lambda
            // is in argument position (parent is ArgumentSyntax).
            if (node.Parent is ArgumentSyntax)
            {
                Add("LEGACY_R026_async_void_action", "warning",
                    "async void lambda 作为参数传递——异常将丢失且调用方无法观察，这是 fire-and-forget 陷阱，改用 Func<Task>", node.GetLocation());
            }
        }
        // async 但体内无 await
        if (node.Modifiers.Any(SyntaxKind.AsyncKeyword))
        {
            var body = (CSharpSyntaxNode)node.Block ?? node.ExpressionBody;
            if (body != null && !body.DescendantNodes().OfType<AwaitExpressionSyntax>().Any())
            {
                Add("LEGACY_async_lambda_no_await", "warning",
                    "async lambda 内无 await，可能误用 async（徒增状态机开销）或漏写 await", node.GetLocation());
            }
        }

        // SEM007: loop variable captured by lambda (classic C# closure bug)
        CheckCapturedLoopVariable(node);

        base.VisitParenthesizedLambdaExpression(node);
    }

    // ── ThrowStatement: throw ex + NotImplementedException ──
    public override void VisitThrowStatement(ThrowStatementSyntax node)
    {
        // throw ex (loses stack trace)
        if (node.Expression is IdentifierNameSyntax id &&
            id.Identifier.Text != "null" &&
            node.Parent is BlockSyntax parentBlock)
        {
            var enclosing = node.Ancestors().OfType<CatchClauseSyntax>().FirstOrDefault();
            if (enclosing != null && enclosing.Declaration != null)
            {
                var varName = enclosing.Declaration.Identifier.Text;
                if (id.Identifier.Text == varName)
                {
                    Add("LEGACY_throw_ex", "error",
                        "throw ex 会丢失原始堆栈跟踪，推荐 throw; 保留原始堆栈",
                        node.GetLocation());
                }
            }
        }

        // NotImplementedException
        if (node.Expression is ObjectCreationExpressionSyntax ocs &&
            ocs.Type.ToString() is "NotImplementedException" or "System.NotImplementedException")
        {
            Add("LEGACY_NotImplementedException", "info",
                "NotImplementedException 应被实际实现替换，或改用 NotSupportedException",
                node.GetLocation());
        }

        // R021: throw new Exception / SystemException (overly broad exception type)
        if (node.Expression is ObjectCreationExpressionSyntax broad &&
            broad.Type.ToString() is "Exception" or "System.Exception" or
                "ApplicationException" or "System.ApplicationException" or
                "SystemException" or "System.SystemException")
        {
            Add("LEGACY_R021_broad_exception", "warning",
                $"throw new {broad.Type} 过于宽泛，应使用具体异常类型（如 InvalidOperationException、ArgumentException、InvalidOperationException 等），便于调用方精确 catch",
                node.GetLocation());
        }

        base.VisitThrowStatement(node);
    }

    // ── InvocationExpression: Console.WriteLine + Thread.Sleep ──
    public override void VisitInvocationExpression(InvocationExpressionSyntax node)
    {
        if (node.Expression is MemberAccessExpressionSyntax member &&
            member.Expression is IdentifierNameSyntax id)
        {
            if (id.Identifier.Text == "Console" &&
                (member.Name.Identifier.Text == "WriteLine" || member.Name.Identifier.Text == "Write"))
            {
                Add("LEGACY_Console_Write", "info",
                    "Console.WriteLine 不适合生产环境，推荐使用日志框架（Serilog/NLog/Microsoft.Extensions.Logging）",
                    node.GetLocation());
            }
            else if (id.Identifier.Text == "Thread" && member.Name.Identifier.Text == "Sleep")
            {
                Add("LEGACY_Thread_Sleep", "warning",
                    "Thread.Sleep 阻塞线程池，推荐使用 Task.Delay（async/await）",
                    node.GetLocation());
            }
            // GC.Collect() — 显式调用 GC 在生产代码中通常是反模式
            else if (id.Identifier.Text == "GC" && member.Name.Identifier.Text == "Collect")
            {
                Add("LEGACY_GC_Collect", "warning",
                    "显式 GC.Collect() 通常不必要，会降低性能，推荐让 GC 自行调度", node.GetLocation());
            }
            // R008: Interlocked.* — flag for review (low false-positive, fixed API names)
            else if (id.Identifier.Text == "Interlocked")
            {
                Add("LEGACY_R008_interlocked", "info",
                    "Interlocked 原子操作，确认操作的变量类型正确（非 double/string 等不支持类型）", node.GetLocation());
            }
            // R010: Monitor.Enter/Exit/Wait/Pulse/PulseAll — low false-positive
            else if (id.Identifier.Text == "Monitor" &&
                     (member.Name.Identifier.Text == "Enter" || member.Name.Identifier.Text == "Exit" ||
                      member.Name.Identifier.Text == "Wait" || member.Name.Identifier.Text == "Pulse" ||
                      member.Name.Identifier.Text == "PulseAll" || member.Name.Identifier.Text == "TryEnter"))
            {
                Add("LEGACY_R010_monitor", "info",
                    "Monitor 显式同步，确认 Exit 在 finally 中调用（推荐用 lock 语句自动管理）", node.GetLocation());
            }
        }

        // R016: Task.WhenAll(...) result not awaited → exceptions silently lost.
        // Detect `Task.WhenAll(...)` whose enclosing statement is not awaited.
        if (node.Expression is MemberAccessExpressionSyntax wama &&
            wama.Expression is IdentifierNameSyntax waid && waid.Identifier.Text == "Task" &&
            wama.Name.Identifier.Text == "WhenAll")
        {
            // If the invocation is the operand of an AwaitExpression, it IS awaited.
            bool isAwaited = node.Ancestors().OfType<AwaitExpressionSyntax>().Any();
            // If assigned/discarded to a variable, the caller may await later — be conservative, skip.
            bool isAssigned = node.Parent is EqualsValueClauseSyntax ||
                              (node.Parent is AssignmentExpressionSyntax);
            if (!isAwaited && !isAssigned)
            {
                Add("LEGACY_R016_task_whenall_not_awaited", "warning",
                    "Task.WhenAll(...) 结果未 await，异常会被静默吞掉", node.GetLocation());
            }
        }

        // P003: .Contains() inside a loop → O(n²) complexity
        if (node.Expression is MemberAccessExpressionSyntax p3ma &&
            p3ma.Name.Identifier.Text == "Contains" &&
            IsInsideLoop(node))
        {
            Add("LEGACY_P003_contains_in_loop", "warning",
                ".Contains() 在循环内调用导致 O(n²) 复杂度，推荐使用 HashSet<T> 或 Dictionary", node.GetLocation());
        }

        // P004: .ContainsKey() inside a loop → redundant dictionary lookups
        if (node.Expression is MemberAccessExpressionSyntax p4ma &&
            p4ma.Name.Identifier.Text == "ContainsKey" &&
            IsInsideLoop(node))
        {
            Add("LEGACY_P004_dictionary_in_loop", "info",
                ".ContainsKey() 在循环内调用，可考虑 TryGetValue 减少字典查找次数", node.GetLocation());
        }

        // SEC016: SqlMethods.Like(...) with concatenation → SQL LIKE injection
        if (node.Expression is MemberAccessExpressionSyntax sec16ma &&
            sec16ma.Name.Identifier.Text == "Like" &&
            node.ArgumentList.Arguments.Any(a => a.Expression is BinaryExpressionSyntax sec16bin &&
                sec16bin.OperatorToken.IsKind(SyntaxKind.PlusToken)))
        {
            Add("LEGACY_SqlMethods_Like", "error",
                "SqlMethods.Like 使用字符串拼接，存在 SQL 注入风险", node.GetLocation());
        }

                // SEC007: Response.Write/Redirect → XSS risk (ASP.NET Web Forms)
        if (node.Expression is MemberAccessExpressionSyntax sec7ma &&
            (sec7ma.Name.Identifier.Text == "Write" || sec7ma.Name.Identifier.Text == "Redirect") &&
            HasResponseReceiver(sec7ma))
        {
            Add("LEGACY_Response_Write_Redirect", "warning",
                "Response.Write/Redirect 输出用户输入可能导致 XSS，建议对输出进行 HTML 编码", node.GetLocation());
        }

                // SEC013: URL redirection detection
        if (node.Expression is MemberAccessExpressionSyntax sec13ma &&
            (sec13ma.Name.Identifier.Text == "Redirect" ||
             sec13ma.Name.Identifier.Text == "RedirectToRoute" ||
             sec13ma.Name.Identifier.Text == "RedirectToAction") &&
            HasResponseReceiver(sec13ma))
        {
            Add("LEGACY_URL_Redirect", "warning",
                "Response.Redirect 可能被用于开放重定向攻击，建议使用本地重定向（如 RedirectToLocal）", node.GetLocation());
        }

        // R017: Task.ContinueWith without exception handling
        if (node.Expression is MemberAccessExpressionSyntax r17ma &&
            r17ma.Name.Identifier.Text == "ContinueWith")
        {
            Add("LEGACY_ContinueWith", "info",
                "Task.ContinueWith 不会传播原始 Task 的异常，推荐使用 await 替代", node.GetLocation());
        }

        // ── BP007b: .GetAwaiter().GetResult() — sync-over-async deadlock trap.
        // Equivalent to .Result/.Wait() but evades BP007 (which keys on the
        // member names Result/Wait). Matches the canonical pattern
        // `task.GetAwaiter().GetResult()`: an invocation of GetResult whose
        // receiver is itself an invocation of GetAwaiter.
        if (node.Expression is MemberAccessExpressionSyntax gaMa &&
            gaMa.Name.Identifier.Text == "GetResult" &&
            gaMa.Expression is InvocationExpressionSyntax gaInv &&
            gaInv.Expression is MemberAccessExpressionSyntax gaInner &&
            gaInner.Name.Identifier.Text == "GetAwaiter")
        {
            Add("LEGACY_BP007b_getawaiter_getresult", "warning",
                ".GetAwaiter().GetResult() 同步阻塞异步操作，与 .Result/.Wait() 等价的死锁陷阱，推荐 await", node.GetLocation());
        }

        // ── BP021: Task.Run / Task.Factory.StartNew in server code.
        // info-level — Task.Run is legitimate in desktop/CLI code but a thread-
        // pool starvation risk in ASP.NET Core server code. Flag for human
        // review; does not block.
        if (node.Expression is MemberAccessExpressionSyntax trMa &&
            trMa.Name.Identifier.Text is "Run" or "StartNew" &&
            trMa.Expression.ToString() is "Task" or "Task.Factory")
        {
            Add("LEGACY_BP021_task_run_server", "info",
                "Task.Run/Task.Factory.StartNew 在 ASP.NET Core 服务端代码中可能导致线程池饥饿，确认是否真的需要（桌面/CLI 代码可忽略此提示）", node.GetLocation());
        }

        // ── R027: fire-and-forget async call — discarded or statement-position.
        // Catches `_ = SomeAsync()` (explicit discard) and `SomeAsync();` (bare
        // statement) where the method name ends in "Async" (naming heuristic —
        // this walker has no SemanticModel to confirm the return type is Task).
        // The result Task is dropped, so exceptions are silently lost.
        // Excluded contexts where the result IS observed: await, assignment to
        // a variable, return, argument, conditional, member access.
        bool isAsyncNamedInvocation = false;
        if (node.Expression is IdentifierNameSyntax r27id &&
            r27id.Identifier.Text.EndsWith("Async", StringComparison.Ordinal) &&
            r27id.Identifier.Text.Length > 5)
        {
            isAsyncNamedInvocation = true;
        }
        else if (node.Expression is MemberAccessExpressionSyntax r27ma &&
                 r27ma.Name.Identifier.Text.EndsWith("Async", StringComparison.Ordinal) &&
                 r27ma.Name.Identifier.Text.Length > 5)
        {
            isAsyncNamedInvocation = true;
        }
        if (isAsyncNamedInvocation && IsFireAndForgetContext(node))
        {
            Add("LEGACY_R027_fire_and_forget_discard", "warning",
                "Async 方法调用结果未 await（fire-and-forget）——异常将丢失且无法观察，确认是否需要 await 或显式处理 Task", node.GetLocation());
        }


                // P006: typeof/GetMethod/GetProperty in loop → reflection overhead
        if (IsInsideLoop(node) &&
            node.Expression is MemberAccessExpressionSyntax p6ma &&
            (p6ma.Name.Identifier.Text == "GetMethod" ||
             p6ma.Name.Identifier.Text == "GetProperty" ||
             p6ma.Name.Identifier.Text == "GetField" ||
             p6ma.Name.Identifier.Text == "Invoke" ||
             p6ma.Name.Identifier.Text == "GetTypes"))
        {
            Add("LEGACY_reflection_in_loop", "warning",
                "反射调用在循环内导致性能开销，建议将反射结果缓存到循环外", node.GetLocation());
        }
        // P006 variant: typeof() in loop
        if (IsInsideLoop(node) &&
            node.Expression is IdentifierNameSyntax p6id &&
            p6id.Identifier.Text == "typeof")
        {
            Add("LEGACY_reflection_in_loop", "warning",
                "typeof 在循环内调用导致性能开销，建议缓存到循环外", node.GetLocation());
        }

        // P007: string.Format in loop
        if (IsInsideLoop(node) && node.Expression is MemberAccessExpressionSyntax p7ma &&
            p7ma.Name.Identifier.Text == "Format" &&
            (p7ma.Expression.ToString() == "string" || p7ma.Expression.ToString() == "String"))
        {
            Add("LEGACY_string_format_in_loop", "warning",
                "循环内 string.Format 导致重复字符串分配，推荐使用 StringBuilder", node.GetLocation());
        }

        // P002: string comparison without StringComparison argument
        if (node.Expression is MemberAccessExpressionSyntax p2ma &&
            (p2ma.Name.Identifier.Text == "Equals" ||
             p2ma.Name.Identifier.Text == "Compare" ||
             p2ma.Name.Identifier.Text == "StartsWith" ||
             p2ma.Name.Identifier.Text == "EndsWith" ||
             p2ma.Name.Identifier.Text == "IndexOf") &&
            (p2ma.Expression is IdentifierNameSyntax p2id && p2id.Identifier.Text == "string" ||
             p2ma.Expression is PredefinedTypeSyntax))
        {
            // Check if any argument is StringComparison
            bool hasStringComparison = node.ArgumentList.Arguments
                .Any(a => a.Expression is MemberAccessExpressionSyntax scma &&
                          scma.Name.Identifier.Text == "StringComparison");
            if (!hasStringComparison)
            {
                Add("LEGACY_missing_StringComparison", "info",
                    "字符串比较方法缺少 StringComparison 参数，可能导致区域性意外行为", node.GetLocation());
            }
        }

        // LOG001: logging a sensitive-named identifier (password/token/secret/...)
        // Sinks are common logger calls: Logger.LogX / _logger.LogX / log.LogX /
        // Console.WriteLine. Reporting when an argument's name looks like a
        // credential — a code-level proxy for "secret may end up in logs".
        if (node.Expression is MemberAccessExpressionSyntax logma &&
            IsLoggingCall(logma.Name.Identifier.Text))
        {
            foreach (var arg in node.ArgumentList.Arguments)
            {
                if (arg.Expression is IdentifierNameSyntax argId &&
                    LooksSensitive(argId.Identifier.Text))
                {
                    Add("LEGACY_LOG001_sensitive_logging", "warning",
                        $"日志中包含疑似敏感字段 '{argId.Identifier.Text}'，禁止记录密码/token/信用卡等明文，建议脱敏或删除", node.GetLocation());
                    break; // one report per logging call is enough
                }
            }

            // LOG003: non-structured logging — message built via string concat
            // or interpolation instead of a structured log template.
            // Only fires on logger calls (not Console.Write*, which is its own rule)
            // and skips the first arg when it's already a template string ($"...").
            if (!logma.Name.Identifier.Text.Equals("WriteLine", StringComparison.Ordinal) &&
                !logma.Name.Identifier.Text.Equals("Write", StringComparison.Ordinal))
            {
                foreach (var arg in node.ArgumentList.Arguments)
                {
                    if (arg.Expression is BinaryExpressionSyntax logBin &&
                        logBin.OperatorToken.IsKind(SyntaxKind.PlusToken))
                    {
                        Add("LEGACY_LOG003_no_structured_logging", "info",
                            "日志消息使用字符串拼接而非结构化模板，推荐使用 Logger.LogInformation(\"User {UserId} logged in\", userId) 形式以便搜索和聚合",
                            node.GetLocation());
                        break;
                    }
                }
            }
        }

        // ── SQL execution methods with string concat/interpolation → injection ──
        // Catches enterprise ORM patterns (Jamtc, custom DALs, etc.) where raw SQL
        // is built via string concatenation or interpolation.  Current
        // LEGACY_SqlCommand_Concat only covers `new SqlCommand("..." + x)`.
        if (node.Expression is MemberAccessExpressionSyntax sqlMa)
        {
            var methodName = sqlMa.Name.Identifier.Text;
            if (_sqlExecutionMethods.Contains(methodName))
            {
                foreach (var arg in node.ArgumentList.Arguments)
                {
                    if (IsSqlConcatPattern(arg.Expression))
                    {
                        Add("LEGACY_SQL_Concat_In_Method", "error",
                            $"{methodName}(...) 使用字符串拼接/插值构建 SQL，存在 SQL 注入风险（如 Jamtc ORM SelectData/ExecuteSql/SqlQuery），推荐参数化查询",
                            node.GetLocation());
                        break;
                    }
                }
            }
        }

        // ── EF003: FromSqlRaw with string concat/interpolation → SQL injection ──
        if (node.Expression is MemberAccessExpressionSyntax ef3ma &&
            (ef3ma.Name.Identifier.Text == "FromSqlRaw" || ef3ma.Name.Identifier.Text == "FromSqlInterpolated"))
        {
            foreach (var arg in node.ArgumentList.Arguments)
            {
                // String concatenation (+) in either FromSqlRaw or FromSqlInterpolated
                if (arg.Expression is BinaryExpressionSyntax ef3bin &&
                    ef3bin.OperatorToken.IsKind(SyntaxKind.PlusToken))
                {
                    Add("LEGACY_EF003_fromsqlraw_concat", "error",
                        "FromSql 使用字符串拼接，存在 SQL 注入风险", node.GetLocation());
                    break;
                }
                // FromSqlRaw with string interpolation ($"...") — parameterization bypassed
                if (ef3ma.Name.Identifier.Text == "FromSqlRaw" &&
                    arg.Expression is InterpolatedStringExpressionSyntax)
                {
                    Add("LEGACY_EF003_fromsqlraw_concat", "error",
                        "FromSqlRaw 使用字符串插值，参数未正确化，存在 SQL 注入风险", node.GetLocation());
                    break;
                }
            }
        }

        // ── Application.DoEvents() — WinForms anti-pattern ──
        if (node.Expression is MemberAccessExpressionSyntax adeMa &&
            adeMa.Name.Identifier.Text == "DoEvents" &&
            adeMa.Expression is IdentifierNameSyntax adeId &&
            adeId.Identifier.Text == "Application")
        {
            Add("LEGACY_WinForms_DoEvents", "warning",
                "Application.DoEvents() 可能导致重入、性能下降和难以调试的 Bug，推荐使用 async/await 或 BackgroundWorker",
                node.GetLocation());
        }

        // ── Control.Invoke for cross-thread UI access ──
        // Detect patterns like `this.Invoke((Action)(() => ...))` which may deadlock
        if (node.Expression is MemberAccessExpressionSyntax invMa &&
            invMa.Name.Identifier.Text == "Invoke" &&
            invMa.Expression is ThisExpressionSyntax)
        {
            Add("LEGACY_WinForms_Invoke", "info",
                "Control.Invoke 同步跨线程调用可能导致 UI 线程死锁，推荐使用 BeginInvoke 或 async/await 模式",
                node.GetLocation());
        }

        // ── SEC023: CORS misconfiguration — AllowAnyOrigin with AllowCredentials ──
        // Walk the full invocation ancestor chain (handles fluent builder chains
        // like p.AllowAnyOrigin().AllowAnyHeader().AllowAnyMethod().AllowCredentials()).
        if (node.Expression is MemberAccessExpressionSyntax corsMa &&
            (corsMa.Name.Identifier.Text == "AllowAnyOrigin" || corsMa.Name.Identifier.Text == "AllowCredentials"))
        {
            var chainMemberAccesses = new List<MemberAccessExpressionSyntax> { corsMa };
            var ancestorExpr = corsMa.Expression;
            while (ancestorExpr is InvocationExpressionSyntax ancestorInv)
            {
                if (ancestorInv.Expression is MemberAccessExpressionSyntax ancestorMa)
                {
                    chainMemberAccesses.Add(ancestorMa);
                    ancestorExpr = ancestorMa.Expression;
                }
                else
                {
                    break;
                }
            }
            bool hasAllowAnyOrigin = chainMemberAccesses.Any(m => m.Name.Identifier.Text == "AllowAnyOrigin");
            bool hasAllowCredentials = chainMemberAccesses.Any(m => m.Name.Identifier.Text == "AllowCredentials");
            if (hasAllowAnyOrigin && hasAllowCredentials)
            {
                Add("LEGACY_SEC023_cors_misconfig", "error",
                    "CORS 配置中同时使用 AllowAnyOrigin 和 AllowCredentials，存在安全风险（CWE-942），应使用显式 origin 允许列表", node.GetLocation());
            }
        }

        // ── SEC024: Open redirect — user-controlled parameter in redirect methods ──
        // Handles both `this.Redirect(url)` (MemberAccessExpressionSyntax) and
        // `Redirect(url)` called directly (IdentifierNameSyntax, e.g. in Controller).
        if (node.Expression is MemberAccessExpressionSyntax redirMa &&
            _redirectMethods.Contains(redirMa.Name.Identifier.Text))
        {
            CheckRedirectArgs(node, redirMa.Name.Identifier.Text);
        }
        else if (node.Expression is IdentifierNameSyntax redirId &&
                 _redirectMethods.Contains(redirId.Identifier.Text))
        {
            CheckRedirectArgs(node, redirId.Identifier.Text);
        }

        // ── SH001: crypto creation with hardcoded key/iv/salt argument ──
        // Aes.Create("...", hardcodedKey) / DES.Create(...) — flag when args contain
        // a string literal that looks like a key (length > 8, not a known algorithm name).
        if (node.Expression is MemberAccessExpressionSyntax cryptoMa)
        {
            var cryptoOwner = cryptoMa.Expression.ToString();
            var cryptoMethod = cryptoMa.Name.Identifier.Text;
            bool isCryptoCreate = (cryptoOwner == "Aes" || cryptoOwner == "DES" ||
                                   cryptoOwner == "TripleDES" || cryptoOwner == "Rijndael") &&
                                  (cryptoMethod == "Create" || cryptoMethod == "Encrypt" ||
                                   cryptoMethod == "Decrypt");
            if (isCryptoCreate && node.ArgumentList.Arguments.Count > 0)
            {
                foreach (var arg in node.ArgumentList.Arguments)
                {
                    if (arg.Expression is LiteralExpressionSyntax lit &&
                        lit.IsKind(SyntaxKind.StringLiteralExpression))
                    {
                        var val = lit.Token.ValueText;
                        if (val.Length >= 8)
                        {
                            Add("LEGACY_SH001_hardcoded_key", "warning",
                                $"加密操作 {cryptoOwner}.{cryptoMethod}(...) 含硬编码字符串参数（疑似 key/iv/salt），密钥应来自密钥管理系统", node.GetLocation());
                            break;
                        }
                    }
                }
            }
        }

        // ── SH008: File.SetAccessControl/Create/Open with write access ──
        if (node.Expression is MemberAccessExpressionSyntax fileMa &&
            fileMa.Expression is IdentifierNameSyntax fileId &&
            fileId.Identifier.Text == "File")
        {
            var fileMethod = fileMa.Name.Identifier.Text;
            bool isWriteOp = fileMethod == "SetAccessControl" || fileMethod == "Create" ||
                             fileMethod == "Open" || fileMethod == "OpenWrite";
            if (isWriteOp)
            {
                Add("LEGACY_SH008_insecure_file_perm", "warning",
                    $"File.{fileMethod}(...) 文件写操作，确认使用最小权限（避免 Everyone/匿名写入）", node.GetLocation());
            }
        }

        // ── SH010: DataBinder.Eval / GetPropertyValue — ASP.NET WebForms risk ──
        if (node.Expression is MemberAccessExpressionSyntax dbMa &&
            dbMa.Expression is IdentifierNameSyntax dbId &&
            dbId.Identifier.Text == "DataBinder" &&
            (dbMa.Name.Identifier.Text == "Eval" || dbMa.Name.Identifier.Text == "GetPropertyValue"))
        {
            Add("LEGACY_SH010_insecure_data_binding", "warning",
                "DataBinder.Eval 直接绑定未净化数据，存在 XSS/注入风险，应在绑定前验证", node.GetLocation());
        }

        // ── EF002: SaveChanges/SaveChangesAsync — verify transaction wrapping (any receiver) ──
        if (node.Expression is MemberAccessExpressionSyntax efMa &&
            (efMa.Name.Identifier.Text == "SaveChanges" || efMa.Name.Identifier.Text == "SaveChangesAsync"))
        {
            Add("LEGACY_EF002_no_transaction", "info",
                "SaveChangesAsync 调用——确认多步写操作已包裹在显式事务中以保证原子性", node.GetLocation());
        }

        // ── Performance hints (P009/P014/EF004) ──
        if (node.Expression is MemberAccessExpressionSyntax perfMa)
        {
            var perfMethod = perfMa.Name.Identifier.Text;
            // P014: Substring(0, n) used in string concatenation context
            if (perfMethod == "Substring" && node.Parent is BinaryExpressionSyntax p14Bin &&
                p14Bin.OperatorToken.IsKind(SyntaxKind.PlusToken))
            {
                Add("LEGACY_P014_inefficient_substring", "info",
                    "Substring 结果用于字符串拼接，建议用 string.Concat 或 Span<char> 减少分配", node.GetLocation());
            }
            // EF004: missing AsNoTracking on read-only EF query
            // Heuristic: .Select(...) or .FirstOrDefault(...) without AsNoTracking in the chain
            if ((perfMethod == "Select" || perfMethod == "FirstOrDefault" || perfMethod == "ToList") &&
                node.Expression.ToString().Contains("DbSet") ||
                (perfMa.Expression is InvocationExpressionSyntax efInner &&
                 efInner.Expression is MemberAccessExpressionSyntax efInnerMa &&
                 efInnerMa.Name.Identifier.Text == "DbSet"))
            {
                Add("LEGACY_EF004_missing_asnotracking", "info",
                    "EF 只读查询建议加 .AsNoTracking() 以跳过变更追踪，提升性能", node.GetLocation());
            }
        }

        // ── Injection heuristics (SEC002/003/004/017/018/021) ──
        // Pattern: dangerous API called with string concat (+) containing user-input identifiers.
        // Only fires when args are BinaryExpression(+) AND contain user-input — pure literals don't fire.
        if (node.Expression is MemberAccessExpressionSyntax injMa &&
            node.ArgumentList.Arguments.Count > 0)
        {
            var owner = (injMa.Expression as IdentifierNameSyntax)?.Identifier.Text ?? "";
            var method = injMa.Name.Identifier.Text;

            // SEC002: Process.Start(... + userInput) or Process.Start(userInput)
            if (owner == "Process" && method == "Start")
            {
                foreach (var arg in node.ArgumentList.Arguments)
                {
                    if (ContainsUserInput(arg.Expression))
                    {
                        Add("LEGACY_SEC002_process_injection", "error",
                            "Process.Start 参数含用户输入，存在命令注入风险", node.GetLocation());
                        break;
                    }
                }
            }
            // SEC003/SEC018: SelectNodes/SelectSingleNode(... + userInput) — XPath injection
            if ((method == "SelectNodes" || method == "SelectSingleNode") &&
                node.ArgumentList.Arguments.Count > 0)
            {
                var firstArg = node.ArgumentList.Arguments[0].Expression;
                if (ContainsUserInput(firstArg))
                {
                    Add("LEGACY_SEC003_xpath_injection", "error",
                        "XPath 查询使用用户输入，存在 XPath 注入风险", node.GetLocation());
                }
            }
            // SEC004: Path.Combine(..., userInput) — path traversal
            if (owner == "Path" && method == "Combine")
            {
                foreach (var arg in node.ArgumentList.Arguments)
                {
                    if (ContainsUserInput(arg.Expression))
                    {
                        Add("LEGACY_SEC004_path_traversal", "warning",
                            "Path.Combine 含用户输入，可能导致路径穿越（访问预期外文件）", node.GetLocation());
                        break;
                    }
                }
            }
            // SEC021: Response.AddHeader/AppendHeader(... + userInput) — CRLF/header injection
            if (owner == "Response" &&
                (method == "AddHeader" || method == "AppendHeader"))
            {
                foreach (var arg in node.ArgumentList.Arguments)
                {
                    if (arg.Expression is BinaryExpressionSyntax hdrBin &&
                        hdrBin.OperatorToken.IsKind(SyntaxKind.PlusToken) &&
                        ContainsUserInput(hdrBin))
                    {
                        Add("LEGACY_SEC021_crlf_injection", "error",
                            "Response.AddHeader 参数含用户输入拼接，存在 CRLF/响应拆分注入风险", node.GetLocation());
                        break;
                    }
                }
            }
            // EF002: SaveChanges/SaveChangesAsync — verify transaction wrapping (any receiver)
            if (method == "SaveChanges" || method == "SaveChangesAsync")
            {
                Add("LEGACY_EF002_no_transaction", "info",
                    "SaveChangesAsync 调用——确认多步写操作已包裹在显式事务中以保证原子性", node.GetLocation());
            }
        }

        // ── ASP.NET Core security pipeline checks ──
        if (node.Expression is MemberAccessExpressionSyntax pipeMa)
        {
            var pipeMethod = pipeMa.Name.Identifier.Text;
            // Track middleware calls for pipeline-level checks (collected per file)
            if (pipeMethod is "UseHttpsRedirection" or "UseHsts" or
                "UseAuthentication" or "UseAuthorization" or
                "UseCors" or "UseDeveloperExceptionPage" or
                "AddCors" or "AddAuthentication")
            {
                _pipelineCalls.Add(pipeMethod);
            }
            // ASP004: DeveloperExceptionPage used without #if DEBUG guard
            if (pipeMethod == "UseDeveloperExceptionPage" &&
                !node.Ancestors().OfType<IfStatementSyntax>().Any())
            {
                Add("LEGACY_ASP004_developer_page", "warning",
                    "UseDeveloperExceptionPage 可能泄漏堆栈/源码信息到客户端，确认仅在开发环境启用",
                    node.GetLocation());
            }
        }

        // DI1002: Service Locator anti-pattern — GetService / GetRequiredService
        // These methods indicate runtime service resolution instead of constructor injection.
        // Matches both generic (GetService<T>) and non-generic (GetService(typeof(T))) forms.
        if (node.Expression is MemberAccessExpressionSyntax slMa &&
            (slMa.Name.Identifier.Text == "GetService" || slMa.Name.Identifier.Text == "GetRequiredService"))
        {
            Add("LEGACY_DI_service_locator", "warning",
                "Service Locator 反模式（GetService/GetRequiredService），推荐使用构造函数注入",
                node.GetLocation());
        }

        base.VisitInvocationExpression(node);
    }

    // Track ASP.NET Core middleware calls for pipeline-level analysis
    private readonly HashSet<string> _pipelineCalls = new();

    /// <summary>
    /// Called after all files are analyzed. Checks pipeline-level security.
    /// </summary>
    void CheckAspNetPipeline()
    {
        // Only check if this looks like an ASP.NET project
        if (!_pipelineCalls.Any()) return;

        if (!_pipelineCalls.Contains("UseHttpsRedirection"))
        {
            Add("LEGACY_ASP005_no_https_redirect", "info",
                "ASP.NET 管道未调用 UseHttpsRedirection()——HTTP 流量不会被重定向到 HTTPS",
                Location.None);
        }
        if (!_pipelineCalls.Contains("UseHsts"))
        {
            Add("LEGACY_ASP006_no_hsts", "info",
                "ASP.NET 管道未调用 UseHsts()——缺少 Strict-Transport-Security 头",
                Location.None);
        }
    }

    private static readonly HashSet<string> _loggingMethods = new()
    {
        "Log", "LogInformation", "LogWarning", "LogError", "LogCritical",
        "LogDebug", "LogTrace", "Information", "Warning", "Error", "Fatal",
        "Debug", "Verbose", "WriteLine", "Write"
    };

    private static bool IsLoggingCall(string methodName) =>
        _loggingMethods.Contains(methodName);

    private static readonly HashSet<string> _sensitiveTokens = new(StringComparer.OrdinalIgnoreCase)
    {
        "password", "passwd", "pwd", "secret", "token", "accesstoken",
        "refreshtoken", "apikey", "api_key", "credential", "privatekey",
        "creditcard", "cardnumber", "cvv", "ssn"
    };

    private static bool LooksSensitive(string identifier)
    {
        if (string.IsNullOrEmpty(identifier)) return false;
        var lower = identifier.ToLowerInvariant();
        foreach (var tok in _sensitiveTokens)
        {
            if (lower.Contains(tok)) return true;
        }
        return false;
    }

    private static readonly HashSet<string> _staticIoMembers = new()
    {
        "Exists", "ReadAllText", "ReadAllBytes", "ReadAllLines", "WriteAllText",
        "WriteAllBytes", "WriteAllLines", "AppendAllText", "Delete", "Create",
        "Copy", "Move", "Open", "OpenRead", "OpenWrite", "GetFiles",
        "GetDirectories", "EnumerateFiles", "EnumerateDirectories", "Combine",
        "GetFullPath", "GetDirectoryName", "GetFileName", "GetExtension"
    };

    private static bool IsStaticIoMember(string memberName) =>
        _staticIoMembers.Contains(memberName);

    // ── SQL injection: method names commonly used for raw SQL execution ──
    private static readonly HashSet<string> _sqlExecutionMethods = new()
    {
        "SelectData", "ExecuteSql", "SqlQuery", "ReadDataToDataTable",
        "ExecuteScalarSql", "ExecuteNonQuery", "QuerySql",
        "ExecuteReader", "Fill", "FillDataTable"
    };

    private static bool IsSqlExecutionMethod(string methodName) =>
        _sqlExecutionMethods.Contains(methodName);

    // User-input source identifiers for injection heuristics (SEC002/003/004/017/021)
    private static readonly HashSet<string> _userInputIdentifiers = new(StringComparer.OrdinalIgnoreCase)
    {
        "Request", "HttpContext", "QueryString", "Form", "input", "userInput",
        "args", "argv", "Console", "Stdin", "Environment"
    };

    private static bool ContainsUserInput(ExpressionSyntax expr)
    {
        if (expr == null) return false;
        // Check expr itself (DescendantNodes doesn't include the node itself)
        if (expr is IdentifierNameSyntax selfId)
        {
            var selfName = selfId.Identifier.Text;
            if (_userInputIdentifiers.Contains(selfName) ||
                selfName.EndsWith("Request", StringComparison.Ordinal) ||
                selfName.EndsWith("Input", StringComparison.Ordinal)) return true;
        }
        foreach (var id in expr.DescendantNodes().OfType<IdentifierNameSyntax>())
        {
            var name = id.Identifier.Text;
            if (_userInputIdentifiers.Contains(name)) return true;
            if (name.EndsWith("Request", StringComparison.Ordinal) ||
                name.EndsWith("Input", StringComparison.Ordinal)) return true;
        }
        return false;
    }

    private static readonly HashSet<string> _httpMethodAttributes = new(StringComparer.OrdinalIgnoreCase)
    {
        "HttpGet", "HttpPost", "HttpPut", "HttpDelete", "HttpPatch",
        "Route", "HttpGetAttribute", "HttpPostAttribute"
    };

    private static readonly string[] _sensitiveBindFields =
    { "IsAdmin", "Role", "Balance", "Password", "PasswordHash", "EmailConfirmed",
      "Permissions", "IsSuperAdmin", "CreditLimit" };

    private static readonly HashSet<string> _redirectMethods = new(StringComparer.OrdinalIgnoreCase)
    {
        "Redirect", "RedirectToAction", "RedirectToRoute", "LocalRedirect", "RedirectPermanent"
    };

    private static readonly string[] _userControlledParams =
    { "returnUrl", "RedirectUrl", "Url", "target", "callback", "next", "returnTo", "redirectUrl" };

    /// <summary>Detect string concatenation or interpolation patterns used to build SQL.</summary>
    private static bool IsSqlConcatPattern(ExpressionSyntax expr)
    {
        // Binary expression with + (string concatenation): "SELECT ... " + x
        if (expr is BinaryExpressionSyntax bin &&
            bin.OperatorToken.IsKind(SyntaxKind.PlusToken))
            return true;
        // String interpolation: $"SELECT ... {x} ..."
        if (expr is InterpolatedStringExpressionSyntax)
            return true;
        return false;
    }

    /// <summary>Check redirect method arguments for user-controlled parameters (SEC024).</summary>
    private void CheckRedirectArgs(InvocationExpressionSyntax node, string methodName)
    {
        foreach (var arg in node.ArgumentList.Arguments)
        {
            var argExpr = arg.Expression.ToString();
            foreach (var userParam in _userControlledParams)
            {
                if (argExpr.Contains(userParam))
                {
                    Add("LEGACY_SEC024_open_redirect", "warning",
                        $"重定向方法 {methodName} 使用用户可控参数 '{userParam}'，可能存在开放重定向风险（CWE-601），建议验证 URL 是否在允许列表中",
                        node.GetLocation());
                    break;
                }
            }
        }
    }

    /// <summary>Exclude config/settings/constants classes from global-state warnings.</summary>
    private static bool IsConfigOrSettingsClass(ClassDeclarationSyntax cls)
    {
        var name = cls.Identifier.Text.ToLowerInvariant();
        return name.Contains("config") || name.Contains("settings")
            || name.Contains("constants") || name.Contains("appsetting")
            || name.Contains("program");
    }


    // ── R018: catch(OperationCanceledException) without re-throw ──
        // ── SEM004/R001: IDisposable created without using statement ──
    private static readonly string[] DisposableTypes =
        { "StreamReader", "StreamWriter", "FileStream", "MemoryStream",
          "SqlConnection", "SqlCommand", "FileStream", "BinaryReader", "BinaryWriter" };

    public override void VisitLocalDeclarationStatement(LocalDeclarationStatementSyntax node)
    {
        // SEM014: `dynamic` keyword in local variable declaration
        if (node.Declaration.Type.ToString() == "dynamic")
        {
            Add("LEGACY_dynamic_local", "info",
                "dynamic 类型绕过了编译时类型检查，可能导致运行时异常，推荐使用具体类型或模式匹配", node.GetLocation());
        }

        // SA1002: multi-variable local declarations on the same line as another statement.
        if (node.Parent is BlockSyntax block)
        {
            var lineNum = node.GetLocation().GetLineSpan().StartLinePosition.Line;
            var sameLine = block.Statements
                .OfType<LocalDeclarationStatementSyntax>()
                .Where(s => s != node &&
                            s.Declaration.Variables.Count > 0 &&
                            s.GetLocation().GetLineSpan().StartLinePosition.Line == lineNum)
                .ToList();
            if (sameLine.Count > 0)
            {
                Add("LEGACY_SA1002_one_statement_per_line", "info",
                    "同一行存在多个语句，建议每行一个声明或语句", node.GetLocation());
            }
        }

        // `var x = new StreamReader(...)` (no `using`) → resource leak risk
        if (!node.UsingKeyword.IsKind(SyntaxKind.UsingKeyword))
        {
            foreach (var v in node.Declaration.Variables)
            {
                if (v.Initializer?.Value is ObjectCreationExpressionSyntax oce)
                {
                    var tn = oce.Type.ToString();
                    foreach (var d in DisposableTypes)
                    {
                        if (tn == d || tn.EndsWith("." + d, StringComparison.Ordinal))
                        {
                            Add("LEGACY_SEM004_idisposable_no_using", "warning",
                                $"{tn} 实现了 IDisposable 但未用 using 语句，可能资源泄漏", v.GetLocation());
                            break;
                        }
                    }
                }
            }
        }
        base.VisitLocalDeclarationStatement(node);
    }

    // ── 新增高价值 AST 规则（正则层难以精准覆盖，且与 builtin 重叠）──

    // 所有二元运算符统一在此处理（CSharpSyntaxWalker 无 VisitEqualsExpression/VisitDivideExpression）
    public override void VisitBinaryExpression(BinaryExpressionSyntax node)
    {
        // 1) .Count() > 0 / == 0 / < 1 等 → 推荐 .Any()
        if ((node.IsKind(SyntaxKind.GreaterThanExpression) || node.IsKind(SyntaxKind.GreaterThanOrEqualExpression) ||
             node.IsKind(SyntaxKind.EqualsExpression) || node.IsKind(SyntaxKind.LessThanExpression)) &&
            (IsCountCall(node.Left) || IsCountCall(node.Right)))
        {
            Add("LEGACY_Linq_Count", "info",
                ".Count() > 0 应使用 .Any()，Count() 会枚举整个集合", node.GetLocation());
        }

        // 2) 字符串字面量参与 == / != → 推荐显式 string.Equals(..., StringComparison)
        if ((node.IsKind(SyntaxKind.EqualsExpression) || node.IsKind(SyntaxKind.NotEqualsExpression)) &&
            HasStringLiteralOperand(node))
        {
            Add("LEGACY_string_eq", "info",
                "字符串用 == 比较，推荐 string.Equals(x, y, StringComparison.Ordinal) 以显式语义", node.GetLocation());
        }

        // 3) 除以字面量 0
        if ((node.IsKind(SyntaxKind.DivideExpression) || node.IsKind(SyntaxKind.ModuloExpression)) &&
            node.Right.IsKind(SyntaxKind.NumericLiteralExpression) &&
            node.Right is LiteralExpressionSyntax lit && lit.Token.Value is int v && v == 0)
        {
            Add("LEGACY_div_by_zero", "error",
                "除以字面量 0，恒抛 DivideByZeroException，可能是错误", node.GetLocation());
        }

        // P010: x == "" → should be string.IsNullOrEmpty
        if ((node.IsKind(SyntaxKind.EqualsExpression) || node.IsKind(SyntaxKind.NotEqualsExpression)) &&
            node.Right.IsKind(SyntaxKind.StringLiteralExpression) &&
            node.Right is LiteralExpressionSyntax p10lit &&
            p10lit.Token.ValueText == "" &&
            node.Left is not LiteralExpressionSyntax)
        {
            Add("LEGACY_empty_string_compare", "info",
                "字符串与空字符串比较，推荐使用 string.IsNullOrEmpty 或 string.IsNullOrWhiteSpace", node.GetLocation());
        }

        base.VisitBinaryExpression(node);
    }

    private static bool IsCountCall(ExpressionSyntax expr)
    {
        return expr is InvocationExpressionSyntax inv &&
               inv.Expression is MemberAccessExpressionSyntax ma &&
               ma.Name.Identifier.Text == "Count";
    }

    private static bool HasStringLiteralOperand(BinaryExpressionSyntax node)
    {
        return node.Left.IsKind(SyntaxKind.StringLiteralExpression) ||
               node.Right.IsKind(SyntaxKind.StringLiteralExpression);
    }

    // async lambda（无参/有参）体内无 await → 可疑
    public override void VisitSimpleLambdaExpression(SimpleLambdaExpressionSyntax node)
    {
        CheckAsyncLambdaMissingAwait(node, node.Modifiers, node.Body);
        CheckCapturedLoopVariable(node);
        base.VisitSimpleLambdaExpression(node);
    }

    private void CheckAsyncLambdaMissingAwait(SyntaxNode node, SyntaxTokenList modifiers, CSharpSyntaxNode body)
    {
        if (!modifiers.Any(SyntaxKind.AsyncKeyword)) return;
        bool hasAwait = body.DescendantNodes().OfType<AwaitExpressionSyntax>().Any();
        if (!hasAwait)
        {
            Add("LEGACY_async_lambda_no_await", "warning",
                "async lambda 内无 await，可能误用 async（徒增状态机开销）或漏写 await", node.GetLocation());
        }
    }

    // SEM007: lambda captures loop variable (classic C# closure bug: all closures see the final value)
    private void CheckCapturedLoopVariable(SyntaxNode lambdaNode)
    {
        // Find the nearest enclosing for loop. Modern C# foreach iteration
        // variables are fresh per iteration, so they do not have the classic
        // closure bug this rule targets.
        StatementSyntax? enclosingLoop = lambdaNode.Ancestors().OfType<ForStatementSyntax>().FirstOrDefault();
        if (enclosingLoop == null) return;

        // Collect loop variable names
        var loopVarNames = new HashSet<string>(StringComparer.Ordinal);
        var asFor = enclosingLoop as ForStatementSyntax;
        if (asFor != null)
        {
            foreach (var decl in asFor.Declaration?.Variables ?? Enumerable.Empty<VariableDeclaratorSyntax>())
                loopVarNames.Add(decl.Identifier.Text);
        }
        if (loopVarNames.Count == 0) return;

        // Check if the lambda body references any loop variable
        var body = lambdaNode is ParenthesizedLambdaExpressionSyntax p ? p.Body
                 : lambdaNode is SimpleLambdaExpressionSyntax s ? s.Body : null;
        if (body == null) return;

        bool captures = body.DescendantNodes().OfType<IdentifierNameSyntax>()
            .Any(id => loopVarNames.Contains(id.Identifier.Text));
        if (captures)
        {
            string loopKind;
            if (enclosingLoop is ForStatementSyntax) loopKind = "for";
            else if (enclosingLoop is ForEachStatementSyntax) loopKind = "foreach";
            else loopKind = "loop";
            Add("LEGACY_SEM007_captured_loop_variable", "warning",
                $"lambda 捕获 {loopKind} 循环变量，所有闭包将看到最终值（经典 C# 闭包陷阱），建议将变量复制到局部再捕获",
                lambdaNode.GetLocation());
        }
    }

    // Equals 重写但未重写 GetHashCode（破坏字典/HashSet 语义）
    public override void VisitClassDeclaration(ClassDeclarationSyntax node)
    {
        bool hasEquals = node.Members.OfType<MethodDeclarationSyntax>().Any(m => m.Identifier.Text == "Equals");
        bool hasGetHashCode = node.Members.OfType<MethodDeclarationSyntax>().Any(m => m.Identifier.Text == "GetHashCode");
        if (hasEquals && !hasGetHashCode)
        {
            Add("LEGACY_equals_no_gethashcode", "warning",
                "重写 Equals 未重写 GetHashCode，相等对象会落入不同哈希桶，破坏字典/HashSet 语义", node.GetLocation());
        }
        // N001: class name PascalCase
        CheckPascalCase(node.Identifier, "LEGACY_N001_class_pascalcase", "类名");

        // ASP001: Controller 安全检测已由语义分析器实现 (3b 层)
        // AST 层删除——语义模型能更精确地判断基类和属性

        // SEM008: class overrides Equals but no operator==/operator!=
        bool hasClassEquals = node.Members.OfType<MethodDeclarationSyntax>().Any(m => m.Identifier.Text == "Equals");
        bool hasClassOpEquals = node.Members.OfType<OperatorDeclarationSyntax>().Any(op =>
            op.OperatorToken.IsKind(SyntaxKind.EqualsEqualsToken));
        bool hasClassOpNotEquals = node.Members.OfType<OperatorDeclarationSyntax>().Any(op =>
            op.OperatorToken.IsKind(SyntaxKind.ExclamationEqualsToken));
        if (hasClassEquals && !hasClassOpEquals && !hasClassOpNotEquals)
        {
            Add("LEGACY_SEM008_class_no_equalsequals", "warning",
                "重写 Equals 但未重载 operator==/operator!=，相等性语义不完整", node.GetLocation());
        }

    base.VisitClassDeclaration(node);

        // R022: class has IDisposable fields but doesn't implement IDisposable
        var disposableTypes = new HashSet<string>(StringComparer.OrdinalIgnoreCase)
        {
            "SqlConnection", "SqlCommand", "FileStream", "StreamReader", "StreamWriter",
            "MemoryStream", "HttpClient", "Timer", "Mutex", "Semaphore", "SemaphoreSlim",
            "ManualResetEvent", "AutoResetEvent", "CancellationTokenSource",
            "Process", "RegistryKey", "CryptographicStream", "BinaryReader", "BinaryWriter",
        };
        var fields = node.Members.OfType<FieldDeclarationSyntax>()
            .Where(f => !f.Modifiers.Any(SyntaxKind.StaticKeyword))
            .SelectMany(f => f.Declaration.Variables.Select(v => f.Declaration.Type.ToString()))
            .Where(t => disposableTypes.Contains(t.Split('.').Last()));
        bool hasDisposableField = fields.Any();
        bool implementsDisposable = node.BaseList != null &&
            node.BaseList.Types.Any(t => t.Type.ToString() == "IDisposable");
        if (hasDisposableField && !implementsDisposable)
        {
            Add("LEGACY_R022_idisposable_field", "warning",
                $"类持有 IDisposable 字段但未实现 IDisposable，可能导致资源泄漏（应在 Dispose 中释放）",
                node.Identifier.GetLocation());
        }

        // R023: method too long (>50 lines, excluding blank/comment lines)
        foreach (var method in node.Members.OfType<MethodDeclarationSyntax>())
        {
            if (method.Body == null) continue;
            int lineCount = method.Body.Statements.Count;
            if (lineCount > 50)
            {
                Add("LEGACY_R023_method_too_long", "info",
                    $"方法 {method.Identifier.Text} 有 {lineCount} 条语句（>50），建议拆分为更小的方法",
                    method.Identifier.GetLocation());
            }
        }

        // R024: too many parameters (>5)
        foreach (var method in node.Members.OfType<MethodDeclarationSyntax>())
        {
            int paramCount = method.ParameterList.Parameters.Count;
            if (paramCount > 5)
            {
                Add("LEGACY_R024_too_many_params", "info",
                    $"方法 {method.Identifier.Text} 有 {paramCount} 个参数（>5），考虑提取为参数对象",
                    method.ParameterList.GetLocation());
            }
        }

        // ASP002: [Bind] / [BindProperties] with sensitive field names
        bool hasBindAttribute = node.AttributeLists.SelectMany(al => al.Attributes)
            .Any(a => a.Name.ToString() == "BindProperties" || a.Name.ToString() == "Bind");
        if (hasBindAttribute)
        {
            var sensitiveMembers = node.Members.OfType<PropertyDeclarationSyntax>()
                .Where(p => _sensitiveBindFields.Contains(p.Identifier.Text))
                .Select(p => p.Identifier.Text)
                .ToList();
            foreach (var sensitive in sensitiveMembers)
            {
                Add("LEGACY_ASP002_binding_sensitive", "warning",
                    $"Bind 属性包含敏感字段 '{sensitive}'，存在 mass-assignment 风险，建议用 [BindNever] 或 DTO",
                    node.Identifier.GetLocation());
            }
        }
    }

    // SEM006: struct overrides Equals but no operator==/operator!=
    public override void VisitStructDeclaration(StructDeclarationSyntax node)
    {
        bool hasEquals = node.Members.OfType<MethodDeclarationSyntax>().Any(m => m.Identifier.Text == "Equals");
        bool hasOpEquals = node.Members.OfType<OperatorDeclarationSyntax>().Any(op =>
            op.OperatorToken.IsKind(SyntaxKind.EqualsEqualsToken));
        bool hasOpNotEquals = node.Members.OfType<OperatorDeclarationSyntax>().Any(op =>
            op.OperatorToken.IsKind(SyntaxKind.ExclamationEqualsToken));
        if (hasEquals && !hasOpEquals && !hasOpNotEquals)
        {
            Add("LEGACY_SEM006_struct_no_equalsequals", "warning",
                "struct 重写 Equals 但未重载 operator==/operator!=，值类型相等性语义不完整", node.GetLocation());
        }
        base.VisitStructDeclaration(node);
    }

    // ── ASP003: attribute-level security checks ──
    public override void VisitAttributeList(AttributeListSyntax node)
    {
        foreach (var attr in node.Attributes)
        {
            var attrName = attr.Name.ToString();

            // ASP003: [IgnoreAntiforgeryToken] — CSRF protection bypassed
            if (attrName == "IgnoreAntiforgeryToken")
            {
                Add("LEGACY_ASP003_antiforgery_skip", "info",
                    "IgnoreAntiforgeryToken 禁用了 CSRF 保护，确认是否为有意的（如无状态 API 使用 token 认证）", attr.GetLocation());
            }
            // R006: [ThreadStatic] field — not initialized on new threads
            else if (attrName == "ThreadStatic" || attrName == "System.ThreadStatic" ||
                     attrName == "ThreadStaticAttribute")
            {
                Add("LEGACY_R006_thread_static", "warning",
                    "[ThreadStatic] 字段在新线程上不会自动初始化（默认值），需在静态构造函数或首次使用前初始化", attr.GetLocation());
            }
        }
        base.VisitAttributeList(node);
    }

    // ── R019: switch statement missing default case ──
    public override void VisitSwitchStatement(SwitchStatementSyntax node)
    {
        bool hasDefault = node.Sections.Any(s =>
            s.Labels.Any(l => l.IsKind(SyntaxKind.DefaultSwitchLabel)));
        if (!hasDefault)
        {
            Add("LEGACY_R019_switch_no_default", "info",
                "switch 语句缺少 default 分支，未覆盖的枚举/取值会被静默忽略", node.SwitchKeyword.GetLocation());
        }
        base.VisitSwitchStatement(node);
    }

    // ── SEM003: enum missing a None=0 member ──
    public override void VisitEnumDeclaration(EnumDeclarationSyntax node)
    {
        bool hasZeroNone = node.Members.Any(m =>
        {
            var name = m.Identifier.Text;
            bool isNoneName = name == "None" || name == "Default" || name == "Empty";
            bool equalsZero = m.EqualsValue is EqualsValueClauseSyntax eq &&
                              eq.Value is LiteralExpressionSyntax lit &&
                              lit.Token.Value is int v && v == 0;
            return isNoneName || equalsZero;
        });
        if (!hasZeroNone)
        {
            Add("LEGACY_SEM003_enum_no_none", "info",
                "枚举缺少值为 0 的 None/Default 成员，建议加 `None = 0` 作为默认/未设置值", node.Identifier.GetLocation());
        }
        base.VisitEnumDeclaration(node);
    }

    public override void VisitInterfaceDeclaration(InterfaceDeclarationSyntax node)
    {
        // N011: interface name must be PascalCase AND start with 'I'
        var name = node.Identifier.Text;
        if (!name.StartsWith("I") || name.Length < 2 || !char.IsUpper(name[1]))
        {
            Add("LEGACY_N011_interface_iprefix", "warning",
                $"接口名 '{name}' 应以 I 开头并 PascalCase（如 I{name}）", node.Identifier.GetLocation());
        }
        else if (!IsPascalCase(name))
        {
            Add("LEGACY_N011_interface_iprefix", "warning",
                $"接口名 '{name}' 应 PascalCase", node.Identifier.GetLocation());
        }
        base.VisitInterfaceDeclaration(node);
    }

    public override void VisitFieldDeclaration(FieldDeclarationSyntax node)
    {
        // N003: private field should be _camelCase; N014/N005: field naming
        bool isPrivate = node.Modifiers.Any(SyntaxKind.PrivateKeyword)
                         && !node.Modifiers.Any(SyntaxKind.PublicKeyword)
                         && !node.Modifiers.Any(SyntaxKind.ProtectedKeyword)
                         && !node.Modifiers.Any(SyntaxKind.InternalKeyword);
        bool isConst = node.Modifiers.Any(SyntaxKind.ConstKeyword);
        // R007: volatile field — flag for review (low false-positive)
        bool isVolatile = node.Modifiers.Any(SyntaxKind.VolatileKeyword);
        if (isVolatile)
        {
            Add("LEGACY_R007_volatile", "info",
                "volatile 字段仅保证可见性不保证原子性，复合操作应改用 Interlocked 或 lock", node.GetLocation());
        }
        foreach (var v in node.Declaration.Variables)
        {
            var name = v.Identifier.Text;
            if (isConst) continue; // const uses PascalCase convention, different rule
            if (isPrivate)
            {
                // N003: private instance field -> _camelCase
                if (!(name.StartsWith("_") && name.Length > 1 && char.IsLower(name[1])))
                {
                    Add("LEGACY_N003_private_field_camelcase", "info",
                        $"私有字段 '{name}' 建议用 _camelCase（如 _{char.ToLower(name[0]) + name.Substring(1)}）",
                        v.Identifier.GetLocation());
                }
            }
            // N005: Hungarian notation (str/int/bool/obj/dbl/flt prefix)
                        if (IsHungarian(name))
            {
                Add("LEGACY_N005_hungarian", "info",
                    $"字段 '{name}' 疑似匈牙利命名（str/int/bool/obj 等类型前缀），现代 .NET 不推荐", v.Identifier.GetLocation());
            }
        }

        // T009: private static field with initializer in test class → shared mutable state
        if (node.Modifiers.Any(SyntaxKind.PrivateKeyword) &&
            node.Modifiers.Any(SyntaxKind.StaticKeyword) &&
            !node.Modifiers.Any(SyntaxKind.ReadOnlyKeyword) &&
            node.Declaration.Variables.Any(v => v.Initializer != null) &&
            IsInsideTestClass(node))
        {
            foreach (var v in node.Declaration.Variables)
            {
                if (v.Initializer != null)
                {
                    Add("LEGACY_test_shared_state", "warning",
                        $"测试类中静态字段 '{v.Identifier.Text}' 在测试间共享可变状态，可能导致测试隔离问题", v.Identifier.GetLocation());
                }
            }
        }

        // ── Global mutable static state ──
        // Detects public static mutable fields in non-config/settings classes.
        // Pattern: `public static Xxx` without readonly/const (e.g., Varlist in CRS).
        if (node.Modifiers.Any(SyntaxKind.PublicKeyword) &&
            node.Modifiers.Any(SyntaxKind.StaticKeyword) &&
            !node.Modifiers.Any(SyntaxKind.ReadOnlyKeyword) &&
            !node.Modifiers.Any(SyntaxKind.ConstKeyword))
        {
            var classDecl = node.Ancestors().OfType<ClassDeclarationSyntax>().FirstOrDefault();
            if (classDecl != null && !IsConfigOrSettingsClass(classDecl))
            {
                foreach (var v in node.Declaration.Variables)
                {
                    Add("LEGACY_Global_Mutable_State", "warning",
                        $"public static 可变字段 '{v.Identifier.Text}'（类 '{classDecl.Identifier.Text}'）——全局可变状态线程不安全且难以测试，建议通过 DI/IoC 容器管理",
                        v.Identifier.GetLocation());
                }
            }
        }

        base.VisitFieldDeclaration(node);
    }

    // DI1001: constructor parameter count > 4
    // Indicates the class has too many injected dependencies, violating SRP.
    public override void VisitConstructorDeclaration(ConstructorDeclarationSyntax node)
    {
        var paramCount = node.ParameterList.Parameters.Count;
        if (paramCount > 4)
        {
            Add("LEGACY_DI1001_too_many_ctor_params", "warning",
                $"构造函数参数超过 4 个（当前 {paramCount} 个），表明该类职责过多，建议拆分",
                node.GetLocation());
        }

        // SA1103: space between `:` and `base`/`this` in constructor initializer.
        var initializer = node.Initializer;
        if (initializer != null)
        {
            var colon = initializer.ColonToken;
            var keyword = initializer.ThisOrBaseKeyword;
            if (colon.Kind() != SyntaxKind.None && keyword.Kind() != SyntaxKind.None)
            {
                var colonEnd = colon.Span.End;
                var keywordStart = keyword.Span.Start;
                if (colonEnd == keywordStart)
                {
                    Add("LEGACY_SA1103_base_this_spacing", "info",
                        "构造函数初始化器 `:` 和 `base`/`this` 之间缺少空格，应写为 `: base(...)` 而非 `:base(...)`",
                        initializer.GetLocation());
                }
            }
        }

        base.VisitConstructorDeclaration(node);
    }



    // ── naming helpers ──
    private static bool IsPascalCase(string name)
    {
        if (string.IsNullOrEmpty(name)) return false;
        // leading underscore is not PascalCase
        return char.IsUpper(name[0]);
    }

    private void CheckPascalCase(SyntaxToken identifier, string code, string label)
    {
        var name = identifier.Text;
        if (!IsPascalCase(name))
        {
            Add(code, "warning",
                $"{label} '{name}' 应 PascalCase（首字母大写）", identifier.GetLocation());
        }
    }

    private static bool IsHungarian(string name)
    {
        if (string.IsNullOrEmpty(name) || name.Length < 2) return false;
        // known type-prefix stems; must be followed by an uppercase letter (the real name)
        string[] stems = { "str", "int", "bool", "obj", "dbl", "flt", "lng", "chr", "byt" };
        foreach (var s in stems)
        {
            if (name.Length > s.Length && name.StartsWith(s) && char.IsUpper(name[s.Length]))
                return true;
        }
        return false;
    }

    private static bool HasResponseReceiver(MemberAccessExpressionSyntax ma)
    {
        // Check if the receiver chain contains "Response" at any level.
        // Handles: Response.Write, Context.Response.Write, HttpContext.Current.Response.Write
        var expr = ma.Expression;
        while (expr is MemberAccessExpressionSyntax inner)
        {
            if (inner.Name.Identifier.Text == "Response") return true;
            expr = inner.Expression;
        }
        if (expr is IdentifierNameSyntax id && id.Identifier.Text == "Response") return true;
        return false;
    }

    private bool IsInCommentOrString(SyntaxNode node)
    {
        foreach (var trivia in node.GetLeadingTrivia())
        {
            if (trivia.IsKind(SyntaxKind.SingleLineCommentTrivia) ||
                trivia.IsKind(SyntaxKind.MultiLineCommentTrivia))
                return true;
        }
        return false;
    }

    // ── S003: excessive #region directives (file-level count) ──
    public override void VisitCompilationUnit(CompilationUnitSyntax node)
    {
        // Count #region directives across the whole file (trivia on any token).
        int regionCount = node.DescendantTrivia()
            .Count(t => t.IsKind(SyntaxKind.RegionDirectiveTrivia));
        // Threshold: more than 5 #region per file is considered excessive.
        if (regionCount > 5)
        {
            Add("LEGACY_S003_excessive_region", "info",
                $"文件内 #region 数量过多（{regionCount} 个，建议 ≤5），过度分块降低可读性", node.GetLocation());
        }

        // S001: TODO without author. Match `// TODO` not followed by `(` or `:`.
        // S002: FIXME without plan. Match any `// FIXME` (no author format check).
        // S005: commented-out code — heuristic: 3+ consecutive single-line
        // comment lines each containing a C# statement marker (;, =, (, {, if,
        // for, while, return, var, etc.) suggests commented code, not prose.
        // P021: prefer Span — `str.Substring(0, n) + ...` or `str.Substring(i, .Length - j)`.
        CheckTodoFixmeComments(node);
        CheckCommentedOutCode(node);
        CheckPreferSpan(node);

        // CS020: try without finally. A missing finally alone is NOT a resource
        // leak (try/catch already handles exceptions; not every try manages a
        // disposable). So the default is info. We escalate to warning ONLY when
        // there is a concrete resource-management signal: the try block creates
        // an object AND makes an explicit Dispose/Close call — that pattern means
        // the developer knows a resource is in play but isn't protecting it with
        // finally/using. A bare `new Stopwatch()` (non-disposable, no Dispose
        // call) stays at info.
        // intentional-simple: no SemanticModel, so IDisposable membership is
        // approximated by the presence of an explicit Dispose/Close call. Upgrade
        // path: move this rule to the semantic analyzer to resolve actual
        // IDisposable types.
        foreach (var tryStmt in node.DescendantNodes().OfType<TryStatementSyntax>())
        {
            if (tryStmt.Finally != null) continue;
            bool createsObject = tryStmt.Block?.DescendantNodes()
                .OfType<ObjectCreationExpressionSyntax>().Any() ?? false;
            bool hasDisposeCall = tryStmt.Block?.DescendantNodes()
                .OfType<InvocationExpressionSyntax>()
                .Any(inv => inv.Expression is MemberAccessExpressionSyntax ma &&
                            ma.Name.Identifier.Text is "Dispose" or "DisposeAsync"
                                or "Close" or "Release") ?? false;
            if (createsObject && hasDisposeCall)
            {
                Add("LEGACY_CS020_missing_finally", "warning",
                    "try 块内创建了资源并调用 Dispose/Close，但缺少 finally——异常路径可能泄漏资源", tryStmt.GetLocation());
            }
            else
            {
                Add("LEGACY_CS020_missing_finally", "info",
                    "try 块缺少 finally 子句（若无 IDisposable 资源可忽略此提示）", tryStmt.GetLocation());
            }
        }

        // P020: unnecessary sealed class. Heuristic: a sealed class that is
        // not directly inheriting from anything (BaseList is null/empty) and
        // has no other classes deriving from it (compile-time check is hard,
        // so we just flag every leaf sealed class — useful as a starting
        // signal; users can suppress).
        foreach (var cls in node.DescendantNodes().OfType<ClassDeclarationSyntax>())
        {
            if (cls.Modifiers.Any(SyntaxKind.SealedKeyword) &&
                (cls.BaseList == null || cls.BaseList.Types.Count == 0))
            {
                Add("LEGACY_P020_unnecessary_sealed", "info",
                    "sealed class '" + cls.Identifier.Text + "' 无继承且无子类，sealed 修饰符可能是多余的",
                    cls.GetLocation());
            }
        }

        // N015: local variable naming convention. Local variables declared
        // with `var` or an explicit type should use camelCase (first char
        // lowercase) or be ALL_CAPS for constants. PascalCase or other
        // capitalised names are suspicious. We also tolerate single-letter
        // loop variables (i, j, k) and underscore-prefixed names (_foo).
        // Skip out-variables and foreach loop variables (common idioms).
        foreach (var localDecl in node.DescendantNodes().OfType<LocalDeclarationStatementSyntax>())
        {
            foreach (var variable in localDecl.Declaration.Variables)
            {
                var name = variable.Identifier.Text;
                if (string.IsNullOrEmpty(name)) continue;
                if (name.Length == 1) continue;          // i, j, k loop vars
                if (name.StartsWith("_", StringComparison.Ordinal)) continue; // _disposables
                if (IsAllUpper(name)) continue;          // MAX_VALUE
                // For each loop variable: also tolerate short names.
                if (localDecl.Parent is ForEachStatementSyntax fes &&
                    fes.Identifier.Text == name) continue;
                // First character must be lowercase for camelCase.
                if (char.IsUpper(name[0]))
                {
                    Add("LEGACY_N015_local_variable_name_convention", "info",
                        "局部变量 '" + name + "' 以大写字母开头——按 C# 约定应使用 camelCase",
                        variable.GetLocation());
                }
            }
        }

        // CS015: nested conditional (deep if/else nesting). Walk every
        // IfStatement and count how many IfStatement ancestors it has
        // (i.e. how deep it's nested). 4+ levels triggers the warning.
        // We report the deepest nested if in each chain to avoid noise.
        var reportedDeepIf = new HashSet<IfStatementSyntax>();
        foreach (var ifStmt in node.DescendantNodes().OfType<IfStatementSyntax>())
        {
            int depth = ifStmt.Ancestors().OfType<IfStatementSyntax>().Count();
            if (depth >= 3 && reportedDeepIf.Add(ifStmt))
            {
                Add("LEGACY_CS015_nested_conditional", "warning",
                    "if 嵌套 " + (depth + 1) + " 层（" + depth + " 个祖先 if）——考虑提前返回或提取方法",
                    ifStmt.GetLocation());
            }
        }

        // P015: unnecessary Convert.ToXxx(x) where the argument already has
        // the target type. We can't always know the type statically, so we
        // catch the suspicious bare-identifier pattern:
        //   var y = Convert.ToInt32(x);   // x is the same identifier
        //   var z = x.ToString();          // redundant when x is already string
        // Heuristic: flag `Convert.ToXxx(<single identifier>)` calls — the
        // conversion is often unnecessary or can be simplified.
        var convertMethods = new HashSet<string>(StringComparer.Ordinal)
        {
            "ToInt32", "ToInt64", "ToInt16", "ToUInt32", "ToUInt64", "ToUInt16",
            "ToString", "ToBoolean", "ToDouble", "ToDecimal", "ToSingle",
            "ToByte", "ToSByte", "ToChar"
        };
        foreach (var inv in node.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            if (inv.Expression is not MemberAccessExpressionSyntax ma) continue;
            // Only proceed if this is a Convert.ToXxx or a ToString call.
            bool isConvert = ma.Expression is IdentifierNameSyntax cid && cid.Identifier.Text == "Convert";
            bool isQualifiedConvert = ma.Expression is MemberAccessExpressionSyntax qcMa
                && qcMa.Name.Identifier.Text == "Convert";
            if (!isConvert && !isQualifiedConvert && ma.Name.Identifier.Text != "ToString")
            {
                continue;
            }
            // Case 1: Convert.ToXxx(<id>) or System.Convert.ToXxx(<id>) — flag
            // any single-identifier arg. The "Convert" part may be wrapped in
            // a qualified name (e.g. `System.Convert`).
            bool isConvertCall = false;
            if (ma.Expression is IdentifierNameSyntax convertId &&
                convertId.Identifier.Text == "Convert")
            {
                isConvertCall = true;
            }
            else if (ma.Expression is MemberAccessExpressionSyntax qualifiedMa &&
                qualifiedMa.Name.Identifier.Text == "Convert")
            {
                isConvertCall = true;
            }
            if (isConvertCall &&
                convertMethods.Contains(ma.Name.Identifier.Text) &&
                inv.ArgumentList.Arguments.Count == 1 &&
                inv.ArgumentList.Arguments[0].Expression is IdentifierNameSyntax)
            {
                Add("LEGACY_P015_unnecessary_conversion", "info",
                    "Convert." + ma.Name.Identifier.Text + "(...) 通常可省——若参数类型已匹配，去掉 Convert 调用",
                    inv.GetLocation());
            }
        }

        base.VisitCompilationUnit(node);
    }

    private void CheckTodoFixmeComments(CompilationUnitSyntax root)
    {
        foreach (var trivia in root.DescendantTrivia())
        {
            if (!trivia.IsKind(SyntaxKind.SingleLineCommentTrivia)) continue;
            var text = trivia.ToString();
            // text is like "// TODO fix this" (Roslyn prepends the //)
            if (text.StartsWith("//", StringComparison.Ordinal))
            {
                var body = text.Substring(2).TrimStart();
                if (body.StartsWith("TODO", StringComparison.Ordinal))
                {
                    // TODO must be followed by '(' or ':' to mark an author.
                    // Otherwise the TODO has no owner and will be forgotten.
                    var afterTodo = body.Substring(4).TrimStart();
                    if (afterTodo.Length == 0 ||
                        (afterTodo[0] != '(' && afterTodo[0] != ':'))
                    {
                        Add("LEGACY_S001_todo_no_author", "info",
                            "// TODO 缺少作者标记（应为 // TODO(name): 或 // TODO:）",
                            trivia.GetLocation());
                    }
                }
                else if (body.StartsWith("FIXME", StringComparison.Ordinal))
                {
                    Add("LEGACY_S002_fixme_comment", "info",
                        "// FIXME 缺少跟进计划（应关联 issue 编号或修复日期）",
                        trivia.GetLocation());
                }
            }
        }
    }

    private void CheckCommentedOutCode(CompilationUnitSyntax root)
    {
        // Walk all single-line comment trivia in source order. Group consecutive
        // runs. If a run has 3+ lines and >= 60% of them contain a "code marker"
        // (;, =, (, {, ), [, ], if, for, while, return, var, =>), treat as
        // commented-out code.
        var allComments = root.DescendantTrivia()
            .Where(t => t.IsKind(SyntaxKind.SingleLineCommentTrivia))
            .ToList();
        if (allComments.Count < 3) return;

        // Group consecutive comments (same span start, adjacent).
        var codeMarkers = new HashSet<string>(StringComparer.Ordinal)
        {
            ";", "=", "(", ")", "{", "}", "[", "]", "=>",
            "if", "for", "while", "return", "var", "new", "class", "void",
            "int", "string", "bool", "double", "float", "public", "private"
        };

        int runStartLine = -1;
        int runCount = 0;
        int runCodeMarker = 0;
        var runDiagnostics = new List<SyntaxTrivia>();

        for (int i = 0; i < allComments.Count; i++)
        {
            var t = allComments[i];
            var lineSpan = t.GetLocation().GetLineSpan();
            int line = lineSpan.StartLinePosition.Line;

            if (runCount == 0)
            {
                runStartLine = line;
                runCount = 1;
            }
            else if (line == runStartLine + runCount)
            {
                runCount++;
            }
            else
            {
                // Run broken — evaluate the previous run.
                EmitCommentedCodeIfMatch(runDiagnostics, runCount, runCodeMarker);
                runCount = 1;
                runStartLine = line;
                runCodeMarker = 0;
                runDiagnostics.Clear();
            }

            runDiagnostics.Add(t);

            var body = t.ToString();
            if (body.StartsWith("//", StringComparison.Ordinal))
                body = body.Substring(2).Trim();
            // Count code markers: any token in the comment line that matches.
            var tokens = body.Split(new[] { ' ', '\t' }, StringSplitOptions.RemoveEmptyEntries);
            foreach (var tok in tokens)
            {
                var clean = tok.Trim(';', ',', '.', '(', ')', '{', '}', '[', ']');
                if (codeMarkers.Contains(clean)) { runCodeMarker++; break; }
            }
        }
        // Evaluate the last run.
        EmitCommentedCodeIfMatch(runDiagnostics, runCount, runCodeMarker);
    }

    private void EmitCommentedCodeIfMatch(List<SyntaxTrivia> run, int count, int codeMarkerCount)
    {
        if (count < 3) return;
        // 60% of lines must have at least one code marker.
        if (codeMarkerCount * 5 < count * 3) return;
        foreach (var trivia in run)
        {
            Add("LEGACY_S005_commented_code", "info",
                "代码块被注释掉（" + count + " 行连续注释，含代码标记），建议删除或还原",
                trivia.GetLocation());
        }
    }

    private void CheckPreferSpan(CompilationUnitSyntax root)
    {
        // P021: prefer Span<T>/ReadOnlySpan<T> for Substring slicing.
        // Detect two common patterns:
        //   1. `x.Substring(0, n) + ...` — slicing at the start + concat
        //   2. `x.Substring(i, .Length - j)` or `x.Substring(i, x.Length - j)`
        //      — slicing relative to length
        // In both cases, AsSpan() avoids a string allocation.
        // Note: .NET Framework 4.7.2 doesn't ship Span<T> by default; users
        // need the System.Memory NuGet package. Severity is `info` so this
        // surfaces as a hint, not a blocker.
        foreach (var node in root.DescendantNodes().OfType<InvocationExpressionSyntax>())
        {
            if (node.Expression is not MemberAccessExpressionSyntax ma) continue;
            if (ma.Name.Identifier.Text != "Substring") continue;

            // Pattern 2: .Substring(<int>, <expr>.Length - <int>)
            if (node.ArgumentList.Arguments.Count == 2)
            {
                var secondArg = node.ArgumentList.Arguments[1].Expression;
                bool isLengthSubtract = secondArg is BinaryExpressionSyntax bin
                    && bin.Kind() == SyntaxKind.SubtractExpression
                    && (bin.Right is LiteralExpressionSyntax || bin.Right is IdentifierNameSyntax)
                    && (bin.Left is MemberAccessExpressionSyntax lenMa
                        && lenMa.Name.Identifier.Text == "Length"
                        || bin.Left is IdentifierNameSyntax idn
                        && idn.Identifier.Text == "Length");
                if (isLengthSubtract)
                {
                    Add("LEGACY_P021_prefer_span", "info",
                        "Substring(i, .Length - j) 模式可用 AsSpan() 替代，避免字符串分配",
                        node.GetLocation());
                    continue;
                }
            }

            // Pattern 1: .Substring(0, n) used in a binary + expression
            if (node.ArgumentList.Arguments.Count == 2 &&
                node.ArgumentList.Arguments[0].Expression is LiteralExpressionSyntax lit0 &&
                lit0.IsKind(SyntaxKind.NumericLiteralExpression) &&
                lit0.Token.ValueText == "0" &&
                node.Parent is BinaryExpressionSyntax bin2 &&
                bin2.Kind() == SyntaxKind.AddExpression)
            {
                Add("LEGACY_P021_prefer_span", "info",
                    ".Substring(0, n) + ... 模式可用 AsSpan() 替代，避免字符串分配",
                    node.GetLocation());
            }
        }
    }

    private void EvaluateCommentedCodeRun(List<(SyntaxTrivia trivia, int line)> run, int count, int codeMarkerCount)
    {
        if (count < 3 || run.Count == 0) return;
        if (codeMarkerCount * 5 < count * 3) return; // < 60% have markers — treat as prose.
        foreach (var (trivia, _) in run)
        {
            Add("LEGACY_S005_commented_code", "info",
                "代码块被注释掉（" + count + " 行连续注释，含代码标记），建议删除或还原",
                trivia.GetLocation());
        }
    }

    // ── S004: magic number (numeric literal in suspicious context) ──
    public override void VisitLiteralExpression(LiteralExpressionSyntax node)
    {
        if (node.IsKind(SyntaxKind.NumericLiteralExpression))
        {
            CheckMagicNumber(node);
        }

        // ── Hardcoded connection string detection ──
        // Found in Jamtc framework NCUtils.cs patterns:
        //   "Data Source=(DESCRIPTION=...User ID=xxx;Password=yyy"
        // Matches string literals containing key=value connection details.
        if (node.IsKind(SyntaxKind.StringLiteralExpression) &&
            node.Token.Value is string strValue && strValue.Length > 20)
        {
            var lower = strValue.ToLowerInvariant();
            bool hasServer = lower.Contains("data source=")
                || lower.Contains("server=")
                || lower.Contains("host=")
                || lower.Contains("initial catalog=");
            bool hasCredential = lower.Contains("password=")
                || lower.Contains("user id=")
                || lower.Contains("uid=")
                || lower.Contains("pwd=");
            if (hasServer && hasCredential)
            {
                // Exclude: variable name/format string placeholders
                var parent = node.Parent;
                if (parent is not InterpolationSyntax) // Not inside $"..." interpolation
                {
                    Add("LEGACY_Hardcoded_Connection_String", "error",
                        "字符串包含数据库连接凭据（Data Source/Server + Password/User ID），连接字符串应从配置或 Secret Manager 读取",
                        node.GetLocation());
                }
            }
        }

        base.VisitLiteralExpression(node);
    }

    private void CheckMagicNumber(LiteralExpressionSyntax node)
    {
        // Only flag integers >= 100 (small literals like 0/1/2 and common
        // idioms are tolerated). String/double literals are ignored.
        if (node.Token.Value is not int value || value < 100) return;

        // ── Exclusions: contexts where a bare literal is expected, not "magic" ──
        var ancestors = node.Ancestors();
        // 1) const field declaration: `const int X = 100;` (named constant)
        if (ancestors.OfType<FieldDeclarationSyntax>()
            .Any(f => f.Modifiers.Any(SyntaxKind.ConstKeyword)))
            return;
        // 1b) const local declaration inside a method: `const int X = 100;`
        if (ancestors.OfType<LocalDeclarationStatementSyntax>()
            .Any(l => l.Modifiers.Any(SyntaxKind.ConstKeyword)))
            return;
        // 2) enum member: `enum E { A = 100 }`
        if (ancestors.Any(a => a is EnumMemberDeclarationSyntax)) return;
        // 3) default/optional parameter: `void M(int x = 100)`
        if (ancestors.Any(a => a is ParameterSyntax)) return;
        // 4) attribute argument: `[Foo(100)]`
        if (ancestors.Any(a => a is AttributeArgumentSyntax)) return;
        // 5) array size / collection initializer literal list — still flag (magic)
        // 6) part of a named assignment to an obvious unit field — too complex, skip

        Add("LEGACY_S004_magic_number", "info",
            $"魔数 {value}：建议提取为有意义的命名常量（const）以提升可读性", node.GetLocation());
    }

    // ── SEC005/SEC014: hardcoded credentials (context-aware) ──
    // Flags string-literal assignments to credential-named identifiers.
    // Regex version matched `password="..."` anywhere (incl. test fixtures,
    // documentation, short non-secret values) → high false-positive rate.
    private static readonly string[] CredentialStems =
        { "password", "passwd", "pwd", "secret", "apikey", "api_key",
          "connectionstring", "accesstoken", "authtoken", "privatekey",
          // extended stems — catch neutral/generic secret-bearing names.
          // Note: bare "token" is intentionally excluded — it is a substring of
          // common identifiers like cancellationToken/refreshToken assigned to
          // non-secret values, which would raise false positives.
          "credential", "signingkey", "clientsecret", "jwttoken", "bearertoken" };

    private static bool IsCredentialName(string name)
    {
        if (string.IsNullOrEmpty(name)) return false;
        var lower = name.ToLowerInvariant();
        foreach (var stem in CredentialStems)
            if (lower.Contains(stem)) return true;
        return false;
    }

    // ── TLS certificate validation callback names ──
    // Both HttpClientHandler and ServicePointManager expose callbacks that,
    // when set to return true unconditionally, disable all TLS verification.
    private static bool IsCertificateValidationCallback(string memberName) =>
        memberName == "ServerCertificateCustomValidationCallback" ||
        memberName == "ServerCertificateValidationCallback";

    // Returns true ONLY when the lambda body is unambiguously `true`:
    //   - expression-bodied:  (...) => true
    //   - block-bodied terminal:  (...) => { ...; return true; }
    // Real validation logic (conditional returns, cert API calls, complex
    // expressions) does NOT match — this avoids flagging legitimate callbacks.
    private static bool LambdaReturnsTrueUnconditionally(ExpressionSyntax rhs)
    {
        CSharpSyntaxNode? body = null;
        if (rhs is ParenthesizedLambdaExpressionSyntax p) body = p.Body;
        else if (rhs is SimpleLambdaExpressionSyntax s) body = s.Body;
        else return false;

        // Expression-bodied lambda: `=> true`
        if (body is ExpressionSyntax expr)
            return expr.IsKind(SyntaxKind.TrueLiteralExpression);

        // Block-bodied: must end with `return true;` as the terminal statement,
        // AND contain nothing but the return (no conditionals, no other returns,
        // no API calls that could be the real validation).
        if (body is BlockSyntax block)
        {
            if (block.Statements.Count != 1) return false;
            if (block.Statements[0] is not ReturnStatementSyntax ret) return false;
            return ret.Expression?.IsKind(SyntaxKind.TrueLiteralExpression) == true;
        }
        return false;
    }

    // ── BP008: string += inside a loop (O(n²) allocation) ──
    public override void VisitAssignmentExpression(AssignmentExpressionSyntax node)
    {
        // Detect `x += ...` where the loop context makes it quadratic.
        // Regex version fired on any `+=`; Roslyn checks it is inside a loop
        // AND the left operand looks like a string variable.
        if (node.IsKind(SyntaxKind.AddAssignmentExpression) &&
            node.Left is IdentifierNameSyntax lv &&
            IsInsideLoop(node) && IsLikelyStringContext(node.Right))
        {
            Add("LEGACY_BP008_string_concat_loop", "warning",
                $"循环内字符串 += 触发 O(n²) 内存分配，推荐 StringBuilder", node.GetLocation());
        }

                // R002: assignment of null — a syntax-level check is already an improvement
        // over the regex `\b\w+\s*=\s*null\s*;` which fires on ANY null assignment
        // (including comments/strings). The AST only detects actual code.
        if (node.IsKind(SyntaxKind.SimpleAssignmentExpression) &&
            node.Right.IsKind(SyntaxKind.NullLiteralExpression) &&
            node.Left is IdentifierNameSyntax r2Id)
        {
            // C# requires out parameters to be assigned on every return path, so a
            // null assignment on a failure path (e.g. `serialNos = null; return false;`)
            // is the language-mandated pattern, not a latent NullReferenceException.
            // This walker has no SemanticModel, so we match the identifier against the
            // enclosing method/constructor's out/ref parameter names (pure AST).
            if (!IsOutOrRefParameter(r2Id.Identifier.Text, node))
            {
                Add("LEGACY_null_assignment", "warning",
                    $"变量 '{r2Id.Identifier.Text}' 被赋值为 null，可能导致 NullReferenceException", node.GetLocation());
            }
        }

        // `x = "literal"` where x is a credential-named identifier
        if (node.IsKind(SyntaxKind.SimpleAssignmentExpression) &&
            node.Left is IdentifierNameSyntax id &&
            IsCredentialName(id.Identifier.Text) &&
            node.Right.IsKind(SyntaxKind.StringLiteralExpression))
        {
            CheckHardcodedSecret(node.Right as LiteralExpressionSyntax, id.Identifier.Text, node.GetLocation());
        }
        // SEC value-format fallback: identifier doesn't look like a credential
        // name, but the literal value matches a known secret format / high entropy.
        // Orthogonal to the name-based check above — fires only when the name
        // gives no hint, catching `var x = "AKIA...";`.
        else if (node.IsKind(SyntaxKind.SimpleAssignmentExpression) &&
                 node.Left is IdentifierNameSyntax vfId &&
                 !IsCredentialName(vfId.Identifier.Text) &&
                 node.Right.IsKind(SyntaxKind.StringLiteralExpression))
        {
            CheckSecretByValueFormat(node.Right as LiteralExpressionSyntax, vfId.Identifier.Text, node.GetLocation());
        }

        // SH007: HttpCookie.Secure / .HttpOnly = false — insecure cookie
        if (node.IsKind(SyntaxKind.SimpleAssignmentExpression) &&
            node.Left is MemberAccessExpressionSyntax cookieMa &&
            node.Right.IsKind(SyntaxKind.FalseLiteralExpression))
        {
            var propName = cookieMa.Name.Identifier.Text;
            if (propName == "Secure" || propName == "HttpOnly")
            {
                Add("LEGACY_SH007_insecure_cookie", "warning",
                    $"HttpCookie.{propName} = false 禁用了安全属性，生产环境应设为 true", node.GetLocation());
            }
        }

        // ── TLS: certificate validation callback disabled (CWE-295) ──
        // One callback that returns `true` disables ALL TLS protection —
        // single point of failure for MITM. We only flag the unambiguous
        // "always accept" pattern; real validation logic (calling cert
        // APIs, conditional returns) is NOT flagged.
        if (node.IsKind(SyntaxKind.SimpleAssignmentExpression) &&
            node.Left is MemberAccessExpressionSyntax tlsMa &&
            IsCertificateValidationCallback(tlsMa.Name.Identifier.Text) &&
            LambdaReturnsTrueUnconditionally(node.Right))
        {
            Add("LEGACY_TLS_cert_validation_disabled", "error",
                "证书验证回调恒返回 true——完全禁用 TLS 中间人保护（CWE-295），移除此回调或实现真实证书校验", node.GetLocation());
        }

        // P001: string += concatenation outside loops (BP008 handles the in-loop case)
        if (node.IsKind(SyntaxKind.AddAssignmentExpression) &&
            node.Left is IdentifierNameSyntax p1Id &&
            !IsInsideLoop(node))
        {
            // Only flag when right side looks like a string (literal or interpolation)
            if (IsLikelyStringContext(node.Right))
            {
                Add("LEGACY_P001_string_concat", "info",
                    $"字符串 {p1Id.Identifier.Text} += 拼接，多次拼接建议用 StringBuilder 减少分配", node.GetLocation());
            }
        }

        base.VisitAssignmentExpression(node);
    }

    public override void VisitVariableDeclarator(VariableDeclaratorSyntax node)
    {
        // N004: single-letter variable name (exclude loop variables i, j, k in for/foreach)
        if (node.Identifier.Text.Length == 1 &&
            char.IsLetter(node.Identifier.Text[0]) &&
            !IsInsideLoop(node))
        {
            // Only flag if we can find the enclosing declaration with a type
            if (node.Parent is VariableDeclarationSyntax n4Decl &&
                (n4Decl.Type.ToString() is "int" or "string" or "var" or "bool"
                 or "double" or "float" or "long" or "object" or "char"))
            {
                Add("LEGACY_single_letter_var", "info",
                    $"单字母变量名 '{node.Identifier.Text}' 降低可读性，建议使用有意义的名称",
                    node.Identifier.GetLocation());
            }
        }

                // field/local/property initializer: `string password = "literal";`
        if (node.Initializer is EqualsValueClauseSyntax init &&
            IsCredentialName(node.Identifier.Text) &&
            init.Value.IsKind(SyntaxKind.StringLiteralExpression))
        {
            CheckHardcodedSecret(init.Value as LiteralExpressionSyntax,
                                 node.Identifier.Text, node.GetLocation());
        }
        // SEC value-format fallback for initializers: name doesn't hint at
        // credential but value matches a known secret format / high entropy.
        else if (node.Initializer is EqualsValueClauseSyntax vfInit &&
                 !IsCredentialName(node.Identifier.Text) &&
                 vfInit.Value.IsKind(SyntaxKind.StringLiteralExpression))
        {
            CheckSecretByValueFormat(vfInit.Value as LiteralExpressionSyntax,
                                     node.Identifier.Text, node.GetLocation());
        }
        base.VisitVariableDeclarator(node);
    }

    private void CheckHardcodedSecret(LiteralExpressionSyntax? literal, string varName, Location loc)
    {
        if (literal == null) return;
        var value = literal.Token.ValueText ?? "";
        // Exclude empty / placeholder values (not real secrets)
        if (string.IsNullOrWhiteSpace(value)) return;
        // Exclude very short values (likely config keys/placeholders, not secrets)
        if (value.Length < 4) return;
        // Exclude obvious placeholders
        string lower = value.ToLowerInvariant();
        if (lower == "null" || lower.Contains("your_") || lower.Contains("placeholder")
            || lower.Contains("example") || lower == "xxx" || lower.Contains("changeme"))
            return;
        // Exclude test classes (fixtures legitimately contain sample secrets)
        if (IsInsideTestClass(literal)) return;

        Add("LEGACY_SEC_hardcoded_secret", "error",
            $"疑似硬编码凭证：'{varName}' 被赋值为字符串字面量，敏感信息应来自配置/密钥管理（如 Azure Key Vault）", loc);
    }

    // ── SEC: detect secrets by VALUE FORMAT (not variable name) ──
    // Catches `var x = "AKIAIOSF...";` where the variable name gives no hint
    // but the value matches a known credential format. This is the orthogonal
    // complement to CheckHardcodedSecret (which keys on the identifier).
    // Reuses the same placeholder/test-class exclusions.
    private static readonly Regex[] SecretFormatPatterns =
    {
        // AWS Access Key ID (20 chars, AKIA prefix)
        new(@"\bAKIA[0-9A-Z]{16}\b", RegexOptions.Compiled),
        // AWS Secret Access Key (40 base64 chars) — only when surrounded by quotes
        // to avoid matching random base64 blobs; kept conservative.
        new(@"\b[A-Za-z0-9/+=]{40}\b", RegexOptions.Compiled),
        // GitHub PAT (classic + fine-grained)
        new(@"\bgh[ps]_[A-Za-z0-9]{36}\b", RegexOptions.Compiled),
        new(@"\bgithub_pat_[A-Za-z0-9_]{82}\b", RegexOptions.Compiled),
        // Slack token
        new(@"\bxox[abp]-[A-Za-z0-9-]{10,}\b", RegexOptions.Compiled),
        // JWT (three base64url segments separated by dots)
        new(@"\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*\b", RegexOptions.Compiled),
        // PEM private key header
        new(@"-----BEGIN (?:RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----", RegexOptions.Compiled),
        // Google API key
        new(@"\bAIza[0-9A-Za-z_-]{35}\b", RegexOptions.Compiled),
    };

    private void CheckSecretByValueFormat(LiteralExpressionSyntax? literal, string varName, Location loc)
    {
        if (literal == null) return;
        var value = literal.Token.ValueText ?? "";
        if (string.IsNullOrWhiteSpace(value)) return;
        // Reuse the same exclusions as CheckHardcodedSecret so the two detectors
        // stay aligned on what counts as a placeholder/test fixture.
        string lower = value.ToLowerInvariant();
        if (lower == "null" || lower.Contains("your_") || lower.Contains("placeholder")
            || lower.Contains("example") || lower == "xxx" || lower.Contains("changeme"))
            return;
        if (IsInsideTestClass(literal)) return;

        // 1) Known credential format — high precision, error level.
        foreach (var rx in SecretFormatPatterns)
        {
            if (rx.IsMatch(value))
            {
                Add("LEGACY_SEC_secret_format", "error",
                    $"字符串字面量匹配已知凭证格式（AWS/GitHub/Slack/JWT/PEM 等），疑似硬编码密钥——变量名 '{varName}' 未暗示敏感用途，应来自密钥管理服务", loc);
                return; // one finding per literal, don't double-report entropy
            }
        }

        // 2) High Shannon entropy fallback — catches unknown formats.
        // Conservative: long string (>= 20) AND high entropy (>= 4.5) to minimize
        // false positives on regular Base64 / hash / UUID strings.
        if (value.Length >= 20)
        {
            double entropy = ShannonEntropy(value);
            if (entropy >= 4.5)
            {
                Add("LEGACY_SEC_secret_entropy", "warning",
                    $"字符串字面量熵值高（{entropy:F2} bits/char），疑似密钥/token——变量名 '{varName}' 未暗示敏感用途，请确认是否应来自配置", loc);
            }
        }
    }

    // Shannon entropy in bits per character. Base64 random data ≈ 6.0;
    // English text ≈ 4.0; structured config keys ≈ 3.5. Threshold 4.5 is
    // intentionally above prose to reduce false positives.
    private static double ShannonEntropy(string s)
    {
        if (s.Length == 0) return 0.0;
        var freq = new Dictionary<char, int>();
        foreach (var c in s)
        {
            freq.TryGetValue(c, out int n);
            freq[c] = n + 1;
        }
        double entropy = 0.0;
        double len = s.Length;
        foreach (var kv in freq)
        {
            double p = kv.Value / len;
            entropy -= p * Math.Log(p, 2);
        }
        return entropy;
    }

    private static bool HasTestMethodAttribute(MethodDeclarationSyntax node)
    {
        // Detect [Fact] / [Test] / [Theory] / [TestMethod] attributes
        foreach (var al in node.AttributeLists)
            foreach (var a in al.Attributes)
            {
                var name = a.Name.ToString();
                if (name == "Fact" || name == "Test" || name == "Theory" || name == "TestMethod")
                    return true;
            }
        return false;
    }

    private static bool IsInsideLoop(SyntaxNode node)
    {
        return node.Ancestors().Any(a => a is ForEachStatementSyntax
                                         || a is ForStatementSyntax
                                         || a is WhileStatementSyntax
                                         || a is DoStatementSyntax);
    }

    // R002 helper: does ``identifier`` name an out/ref parameter of the enclosing
    // method/constructor? C# mandates out parameters be assigned on every path,
    // so `param = null;` on a failure path is the language-required idiom — not a
    // latent NullReferenceException. No SemanticModel here, so we match the
    // identifier against the nearest enclosing member's parameter list (pure AST).
    private static bool IsOutOrRefParameter(string identifier, SyntaxNode node)
    {
        if (string.IsNullOrEmpty(identifier)) return false;
        var member = node.FirstAncestorOrSelf<BaseMethodDeclarationSyntax>();
        if (member?.ParameterList == null) return false;
        foreach (var p in member.ParameterList.Parameters)
        {
            if (p.Identifier.Text != identifier) continue;
            if (p.Modifiers.Any(m => m.IsKind(SyntaxKind.OutKeyword) ||
                                     m.IsKind(SyntaxKind.RefKeyword)))
            {
                return true;
            }
        }
        return false;
    }

    // R027 helper: true when an invocation's result is dropped (fire-and-forget).
    // Fires on:
    //   - ExpressionStatementSyntax (bare statement: `SomeAsync();`)
    //   - discard assignment (`_ = SomeAsync();`)
    // Excluded (result IS observed): await, assignment to a real variable,
    // return, argument to another call, conditional/ternary, member access.
    private static bool IsFireAndForgetContext(InvocationExpressionSyntax node)
    {
        var parent = node.Parent;
        // Bare statement: `SomeAsync();` — result discarded.
        if (parent is ExpressionStatementSyntax) return true;
        // Explicit discard: `_ = SomeAsync();`
        if (parent is AssignmentExpressionSyntax ae &&
            ae.Left is IdentifierNameSyntax discardId &&
            discardId.Identifier.Text == "_")
        {
            return true;
        }
        return false;
    }

    private static bool IsLikelyStringContext(ExpressionSyntax expr)
    {
        // Heuristic: the RHS suggests a string operation (string literal, ToString,
        // interpolation, or string method call). Avoids flagging numeric +=.
        if (expr is LiteralExpressionSyntax lit &&
            lit.IsKind(SyntaxKind.StringLiteralExpression)) return true;
        if (expr is InterpolatedStringExpressionSyntax) return true;
        var s = expr.ToString();
        return s.Contains("ToString()") || s.Contains(".Substring") || s.Contains("\"");
    }

    private static bool IsAllUpper(string name)
    {
        // Returns true if every letter in the name is uppercase, allowing
        // underscores and digits. Treats single-letter names conservatively
        // (returns true to avoid false positives on "T", "X", etc.).
        if (string.IsNullOrEmpty(name)) return true;
        bool hasLetter = false;
        foreach (var c in name)
        {
            if (char.IsLetter(c))
            {
                hasLetter = true;
                if (char.IsLower(c)) return false;
            }
        }
        return hasLetter;
    }

    private static bool IsInsideTestClass(SyntaxNode node)
    {
        // Heuristic: class named like a test, or carrying [Test]/[Fact]/[TestMethod]
        foreach (var cls in node.Ancestors().OfType<ClassDeclarationSyntax>())
        {
            var cname = cls.Identifier.Text.ToLowerInvariant();
            if (cname.Contains("test") || cname.Contains("fixture") || cname.Contains("spec"))
                return true;
            bool hasTestAttr = cls.AttributeLists.SelectMany(al => al.Attributes)
                .Any(a => a.Name.ToString().Contains("Test"));
            if (hasTestAttr) return true;
        }
        return false;
    }

    // ════════════════════════════════════════════════════════════════════
    // StyleCop SA rules (LEGACY_SA*)
    // ════════════════════════════════════════════════════════════════════

    // SA1001: generic < spacing — `<` in List<T> should be preceded by a space.
    // Triggers on `List<T>` (no space before <) but not `List <T>`.
    public override void VisitGenericName(GenericNameSyntax node)
    {
        var taList = node.TypeArgumentList;
        if (taList == null) { base.VisitGenericName(node); return; }
        var lt = taList.LessThanToken;
        if (lt.Kind() == SyntaxKind.None) { base.VisitGenericName(node); return; }
        var span = lt.Span;
        if (span.Start > 0)
        {
            var text = node.SyntaxTree.GetText();
            var idx = span.Start - 1;
            // Skip whitespace/SOA to find the preceding character
            while (idx >= 0 && (text[idx] == ' ' || text[idx] == '\t')) idx--;
            if (idx >= 0)
            {
                char preceding = text[idx];
                // If the character before the identifier is a letter/digit/], it's likely
                // `List<T>` with no space (e.g. `List<T>`, `Func<T>`, `Action<T>`).
                // `await Task.Delay<T>()` is also covered (Task is the identifier).
                // Space is required before `<`.
                if (char.IsLetterOrDigit(preceding) || preceding == ']')
                {
                    Add("LEGACY_SA1001_generic_spacing", "info",
                        "泛型类型引用 < 前缺少空格，例如 List<T> 应写为 List <T>", lt.GetLocation());
                }
            }
        }
        base.VisitGenericName(node);
    }

    // SA1002: one statement per line — sibling ExpressionStatements on the same line.
    public override void VisitExpressionStatement(ExpressionStatementSyntax node)
    {
        var lineNum = node.GetLocation().GetLineSpan().StartLinePosition.Line;
        if (node.Parent is BlockSyntax block)
        {
            var sameLine = block.Statements
                .OfType<ExpressionStatementSyntax>()
                .Where(s => s != node &&
                            s.GetLocation().GetLineSpan().StartLinePosition.Line == lineNum)
                .ToList();
            if (sameLine.Count > 0)
            {
                Add("LEGACY_SA1002_one_statement_per_line", "info",
                    "同一行存在多个 ExpressionStatement，建议每行一个语句", node.GetLocation());
            }
        }
        base.VisitExpressionStatement(node);
    }

    // SA1002: also flag multi-variable local declarations on the same line.
    // (merged into existing VisitLocalDeclarationStatement above)

    // SA1103: space between `:` and `base`/`this` in constructor initializer.
    // Style: `public C() : base(x)` — the `:` and `base` must be separated by whitespace.
    // (merged into existing VisitConstructorDeclaration above)

    // SA1113: opening brace followed by non-whitespace on the same line.
    // Triggers on `public void Foo() { Do();` (content on same line as {).
    public override void VisitBlock(BlockSyntax node)
    {
        var openBrace = node.OpenBraceToken;
        var closeBrace = node.CloseBraceToken;
        if (openBrace.Kind() == SyntaxKind.None || closeBrace.Kind() == SyntaxKind.None)
        {
            base.VisitBlock(node);
            return;
        }

        var tree = node.SyntaxTree;
        var text = tree.GetText();
        var afterOpen = openBrace.Span.End;

        // Only relevant for blocks that span multiple lines (multi-line blocks).
        var openLine = openBrace.GetLocation().GetLineSpan().StartLinePosition.Line;
        var closeLine = closeBrace.GetLocation().GetLineSpan().StartLinePosition.Line;
        if (closeLine <= openLine)
        {
            base.VisitBlock(node);
            return;
        }

        // Look at line 0 of the block (the line containing `{`) and the line after it.
        // If there's non-whitespace on the same line as `{`, flag it.
        var fullText = text.ToString();
        var lineStarts = text.Lines;
        if (openLine < lineStarts.Count)
        {
            var openLineText = lineStarts[openLine].Span;
            var lineContent = fullText.Substring(openLineText.Start, openLineText.Length);
            // `lineContent` starts at beginning of line — skip leading whitespace (indentation).
            var trimmedStart = lineContent.TrimStart();
            // If the line ends with `{` and has non-whitespace before it (other than indentation),
            // and there's also content after `{` on the same line...
            // Actually simpler: if there are non-space chars after `{` on the same line.
            var afterBraceContent = lineContent.Substring(openBrace.Span.End - lineStarts[openLine].Start);
            if (!string.IsNullOrWhiteSpace(afterBraceContent))
            {
                Add("LEGACY_SA1113_brace_indent", "info",
                    "开括号 `{` 后面不应在同一行放置其他语句，闭合括号应与开括号同行对齐", openBrace.GetLocation());
            }
        }
        base.VisitBlock(node);
    }

    // SA1118: in a multi-line parameter list, all parameters must be on separate lines.
    // Triggers when two parameters share the same line in a multi-line parameter list.
    public override void VisitParameterList(ParameterListSyntax node)
    {
        CheckMultiLineParameterList(node);
        base.VisitParameterList(node);
    }

    public override void VisitIndexerDeclaration(IndexerDeclarationSyntax node)
    {
        // SA1118: check BracketedParameterListSyntax for multi-line same-line params.
        var paramList = node.ParameterList;
        if (paramList.Parameters.Count >= 2)
        {
            var openLine = paramList.OpenBracketToken.GetLocation().GetLineSpan().StartLinePosition.Line;
            var closeLine = paramList.CloseBracketToken.GetLocation().GetLineSpan().StartLinePosition.Line;
            if (closeLine > openLine) // multi-line
            {
                var paramLines = paramList.Parameters
                    .Select(p => p.GetLocation().GetLineSpan().StartLinePosition.Line)
                    .ToList();
                var duplicates = paramLines.GroupBy(x => x).Where(g => g.Count() > 1).ToList();
                if (duplicates.Count > 0)
                {
                    Add("LEGACY_SA1118_parameter_newline", "info",
                        "多行参数列表中，同一行不应放置多个参数，每个参数应单独成行", paramList.GetLocation());
                }
            }
        }
        base.VisitIndexerDeclaration(node);
    }

    public override void VisitDelegateDeclaration(DelegateDeclarationSyntax node)
    {
        CheckMultiLineParameterList(node.ParameterList);
        base.VisitDelegateDeclaration(node);
    }

    private void CheckMultiLineParameterList(ParameterListSyntax? paramList)
    {
        if (paramList == null || paramList.Parameters.Count < 2) return;
        var openLine = paramList.OpenParenToken.GetLocation().GetLineSpan().StartLinePosition.Line;
        var closeLine = paramList.CloseParenToken.GetLocation().GetLineSpan().StartLinePosition.Line;
        if (closeLine <= openLine) return; // Single-line, not relevant.

        // Group parameters by their line number.
        var paramLines = paramList.Parameters
            .Select(p => p.GetLocation().GetLineSpan().StartLinePosition.Line)
            .ToList();

        // SA1118: two or more parameters on the same line in a multi-line list.
        var duplicates = paramLines.GroupBy(x => x).Where(g => g.Count() > 1).Select(g => g.Key).ToList();
        if (duplicates.Count > 0)
        {
            Add("LEGACY_SA1118_parameter_newline", "info",
                "多行参数列表中，同一行不应放置多个参数，每个参数应单独成行", paramList.GetLocation());
        }
    }

    private void Add(string code, string severity, string message, Location location)
    {
        var lineSpan = location.GetLineSpan();
        Diagnostics.Add(new AstDiagnostic
        {
            File = _file,
            Line = lineSpan.StartLinePosition.Line + 1,
            Severity = severity,
            Code = code,
            Message = message
        });
    }
}


record class AstDiagnostic
{
    [JsonPropertyName("code")] public string Code { get; set; } = "";
    [JsonPropertyName("message")] public string Message { get; set; } = "";
    [JsonPropertyName("line")] public int Line { get; set; }
    [JsonPropertyName("severity")] public string Severity { get; set; } = "";
    [JsonPropertyName("source_file")] public string File { get; set; } = "";
}
