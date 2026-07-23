from __future__ import annotations
import logging

logger = logging.getLogger('dotnet-review')


# ============================================================
# AST Rule Metadata Index
# Maps Roslyn AST rule IDs (LEGACY_*/SEM_*) → {category, suggestion}
# Used by engine.analyze_ast() to populate the correct category and
# suggestion instead of a hardcoded best-practice / empty string.
# ============================================================
AST_RULE_META: dict[str, dict[str, str]] = {
    # Note: ASP001 is NOT here — it is emitted only by the semantic analyzer
    # as "ASP001" (short form). LEGACY_ASP002-006 ARE emitted by the AST analyzer.
    'LEGACY_ASP002_binding_sensitive': {'category': 'security', 'suggestion': 'Use [BindNever] on sensitive properties or a dedicated request DTO. Never bind privilege/account-balance/email-confirmed fields from user input.'},
    'LEGACY_ASP003_antiforgery_skip': {'category': 'security', 'suggestion': 'Confirm this is intentional (e.g. stateless API with token auth, not cookie auth) and documented. For cookie-based auth, keep antiforgery on.'},
    'LEGACY_ASP004_developer_page': {'category': 'security', 'suggestion': 'Only enable UseDeveloperExceptionPage in Development environment (e.g. if (env.IsDevelopment())).'},
    'LEGACY_ASP005_no_https_redirect': {'category': 'security', 'suggestion': 'Add app.UseHttpsRedirection() to redirect HTTP to HTTPS.'},
    'LEGACY_ASP006_no_hsts': {'category': 'security', 'suggestion': 'Add app.UseHsts() in Production to send Strict-Transport-Security headers.'},
    'LEGACY_ArrayList': {'category': 'performance', 'suggestion': 'Use generic List<T> or Dictionary<TKey, TValue> to avoid boxing.'},
    'LEGACY_BP007_sync_wait': {'category': 'best-practice', 'suggestion': 'Use await instead of .Result or .Wait() to avoid deadlocks.'},
    'LEGACY_BP007b_getawaiter_getresult': {'category': 'best-practice', 'suggestion': '.GetAwaiter().GetResult() is equivalent to .Result — same deadlock risk. Use await instead.'},
    'LEGACY_BP008_string_concat_loop': {'category': 'best-practice', 'suggestion': 'Use StringBuilder inside loops to avoid O(n²) string allocation.'},
    'LEGACY_BP021_task_run_server': {'category': 'best-practice', 'suggestion': 'Task.Run in ASP.NET Core server code can starve the thread pool. Offload via the framework or use await directly. Legitimate in desktop/CLI code.'},
    'LEGACY_BP022_random_shared': {'category': 'best-practice', 'suggestion': 'Use Random.Shared instead of new Random() — thread-safe, better performance, no manual disposal.'},
    'LEGACY_BP023_system_text_json': {'category': 'best-practice', 'suggestion': 'Newtonsoft.Json is legacy; prefer System.Text.Json for better performance, source-gen, and AOT compatibility.'},
    'LEGACY_BP024_datetime_modern': {'category': 'best-practice', 'suggestion': 'Consider DateTimeOffset (timezone-agnostic) or DateOnly/TimeOnly (.NET 6+) instead of DateTime.Now/UtcNow/Today.'},
    'LEGACY_BinaryFormatter': {'category': 'security', 'suggestion': 'Avoid BinaryFormatter. Use JsonSerializer or XmlSerializer with settings.'},
    'LEGACY_CS015_nested_conditional': {'category': 'code-smell', 'suggestion': 'Simplify the nested conditionals or use guard clauses.'},
    'LEGACY_CS020_missing_finally': {'category': 'code-smell', 'suggestion': "Add a finally block to ensure cleanup code always runs, or use a 'using' statement."},
    'LEGACY_CSharpCodeProvider': {'category': 'security', 'suggestion': 'Avoid runtime code compilation. Use expression trees or Roslyn Scripting API.'},
    'LEGACY_Catch_Return_Exception': {'category': 'best-practice', 'suggestion': ''},
    'LEGACY_Console_Write': {'category': 'best-practice', 'suggestion': 'Use a logging framework (Serilog, NLog, Microsoft.Extensions.Logging).'},
    'LEGACY_ContinueWith': {'category': 'reliability', 'suggestion': 'Use async/await with proper try/catch or TaskScheduler.UnobservedTaskException.'},
    'LEGACY_DataSet': {'category': 'best-practice', 'suggestion': ''},
    'LEGACY_DirectorySearcher_Concat': {'category': 'security', 'suggestion': 'Use LDAP filter escaping or DirectoryEntry with Properties collection.'},
    'LEGACY_EF002_no_transaction': {'category': 'reliability', 'suggestion': 'Wrap multi-step SaveChangesAsync in an IDbContextTransaction (or an execution strategy with retry) so partial writes roll back on failure.'},
    'LEGACY_EF003_fromsqlraw_concat': {'category': 'security', 'suggestion': 'Use FromSqlInterpolated with parameter interpolation ($"...{value}..."), or FromSqlRaw with {0} placeholders and a parameter array. Never concatenate.'},
    'LEGACY_EF004_missing_asnotracking': {'category': 'performance', 'suggestion': 'Append .AsNoTracking() for read-only queries to skip change tracking and reduce memory allocation. Regex heuristic — confirm the query is genuinely read-only.'},
    'LEGACY_GC_Collect': {'category': 'best-practice', 'suggestion': ''},
    'LEGACY_Global_Mutable_State': {'category': 'best-practice', 'suggestion': ''},
    'LEGACY_Hardcoded_Connection_String': {'category': 'best-practice', 'suggestion': ''},
    'LEGACY_Hashtable': {'category': 'performance', 'suggestion': 'Use generic List<T> or Dictionary<TKey, TValue> to avoid boxing.'},
    'LEGACY_HttpClient_New': {'category': 'best-practice', 'suggestion': 'Use IHttpClientFactory to manage HttpClient lifecycle.'},
    'LEGACY_LDAP_Concat': {'category': 'best-practice', 'suggestion': ''},
    'LEGACY_LOG001_sensitive_logging': {'category': 'security', 'suggestion': 'Never log raw credentials. Mask or redact sensitive fields before logging, or omit them entirely.'},
    'LEGACY_LOG003_no_structured_logging': {'category': 'best-practice', 'suggestion': 'Use structured logging: LogInformation("User {UserId} did {Action}", userId, action) — enables search and aggregation in log systems.'},
    'LEGACY_Linq_Count': {'category': 'best-practice', 'suggestion': ''},
    'LEGACY_N001_class_pascalcase': {'category': 'naming', 'suggestion': ''},
    'LEGACY_N002_method_pascalcase': {'category': 'naming', 'suggestion': ''},
    'LEGACY_N003_private_field_camelcase': {'category': 'naming', 'suggestion': ''},
    'LEGACY_N005_hungarian': {'category': 'naming', 'suggestion': ''},
    'LEGACY_N011_interface_iprefix': {'category': 'naming', 'suggestion': ''},
    'LEGACY_N015_local_variable_name_convention': {'category': 'naming', 'suggestion': 'Use camelCase for local variable names.'},
    'LEGACY_NotImplementedException': {'category': 'best-practice', 'suggestion': 'Implement the method or throw NotSupportedException.'},
    'LEGACY_P001_string_concat': {'category': 'performance', 'suggestion': 'Use StringBuilder for multiple concatenations or interpolation.'},
    'LEGACY_P003_contains_in_loop': {'category': 'performance', 'suggestion': 'Use HashSet<T> for O(1) lookups instead of List.Contains.'},
    'LEGACY_P004_dictionary_in_loop': {'category': 'performance', 'suggestion': 'Cache dictionary values or use TryGetValue pattern.'},
    'LEGACY_P008_regex_not_cached': {'category': 'performance', 'suggestion': 'Cache Regex in static field or use RegexGenerator source generator.'},
    'LEGACY_P014_inefficient_substring': {'category': 'performance', 'suggestion': 'Use string interpolation or StringBuilder for better performance.'},
    'LEGACY_P015_unnecessary_conversion': {'category': 'performance', 'suggestion': 'Use the appropriate conversion method or operator.'},
    'LEGACY_P020_unnecessary_sealed': {'category': 'performance', 'suggestion': 'Remove unnecessary sealed class or use an interface instead.'},
    'LEGACY_P021_prefer_span': {'category': 'performance', 'suggestion': 'In C# 7.2+ use str.AsSpan(0, n) to slice without allocation. For concatenation use string.Concat with span arguments. Reserve Substring only when an actual new string is required.'},
    'LEGACY_R003_catch_swallow': {'category': 'reliability', 'suggestion': 'Log the exception or re-throw it.'},
    'LEGACY_R005_nested_lock': {'category': 'reliability', 'suggestion': 'Avoid nested locks or use lock ordering.'},
    'LEGACY_R006_thread_static': {'category': 'reliability', 'suggestion': 'Initialize ThreadStatic fields in a static constructor or before first use.'},
    'LEGACY_R007_volatile': {'category': 'reliability', 'suggestion': 'Consider using Interlocked methods or lock for thread safety.'},
    'LEGACY_R008_interlocked': {'category': 'reliability', 'suggestion': 'Ensure proper use of Interlocked methods for thread safety.'},
    'LEGACY_R010_monitor': {'category': 'reliability', 'suggestion': 'Ensure proper use of Monitor methods for thread synchronization.'},
    'LEGACY_R011_mutex': {'category': 'reliability', 'suggestion': 'Ensure proper use of Mutex for cross-process synchronization.'},
    'LEGACY_R012_semaphore': {'category': 'reliability', 'suggestion': 'Ensure proper use of Semaphore for thread coordination.'},
    'LEGACY_R013_event_wait_handle': {'category': 'reliability', 'suggestion': 'Ensure proper use of EventWaitHandle for thread signaling.'},
    'LEGACY_R014_cancellation_token': {'category': 'reliability', 'suggestion': 'Ensure proper disposal of CancellationTokenSource.'},
    'LEGACY_R016_task_whenall_not_awaited': {'category': 'reliability', 'suggestion': 'Await the Task returned by WhenAll or call .GetAwaiter().GetResult() for sync contexts.'},
    'LEGACY_R018_opc_not_rethrow': {'category': 'reliability', 'suggestion': 'Check .CancellationToken.IsCancellationRequested before throwing OperationCanceledException.'},
    'LEGACY_R019_switch_no_default': {'category': 'reliability', 'suggestion': 'Add a default case to handle all possible values, including future enum values.'},
    'LEGACY_R021_broad_exception': {'category': 'reliability', 'suggestion': 'Use specific exception types (InvalidOperationException, ArgumentException, etc.).'},
    'LEGACY_R022_idisposable_field': {'category': 'reliability', 'suggestion': 'Implement IDisposable and dispose the field in Dispose().'},
    'LEGACY_R023_method_too_long': {'category': 'complexity', 'suggestion': 'Split into smaller, focused methods.'},
    'LEGACY_R024_too_many_params': {'category': 'complexity', 'suggestion': 'Extract parameters into a parameter object or use a builder pattern.'},
    'LEGACY_R025_lock_await': {'category': 'reliability', 'suggestion': 'Use SemaphoreSlim(1,1).WaitAsync() instead of lock for async code.'},
    'LEGACY_R026_async_void_action': {'category': 'reliability', 'suggestion': 'async void lambda passed as an argument loses exceptions — the caller cannot observe the Task. Use Func<Task> instead of Action.'},
    'LEGACY_R027_fire_and_forget_discard': {'category': 'reliability', 'suggestion': 'The async call result is dropped (fire-and-forget) — exceptions are silently lost. Await the call, or explicitly handle the returned Task.'},
    'LEGACY_Response_Write_Redirect': {'category': 'security', 'suggestion': 'Encode output with HttpUtility.HtmlEncode / UrlEncode.'},
    'LEGACY_S001_todo_no_author': {'category': 'style', 'suggestion': 'Format as `// TODO(username): message`.'},
    'LEGACY_S002_fixme_comment': {'category': 'style', 'suggestion': 'Add a linked issue number and description.'},
    'LEGACY_S003_excessive_region': {'category': 'style', 'suggestion': ''},
    'LEGACY_S004_magic_number': {'category': 'test', 'suggestion': 'Use named constants for magic numbers in tests to improve readability.'},
    'LEGACY_S005_commented_code': {'category': 'style', 'suggestion': 'Remove dead code. Use source control history if needed later.'},
    'LEGACY_SEC002_process_injection': {'category': 'security', 'suggestion': 'Validate input and use ProcessStartInfo with argument list.'},
    'LEGACY_SEC003_xpath_injection': {'category': 'security', 'suggestion': 'Use parameterized XPath queries with variable references.'},
    'LEGACY_SEC004_path_traversal': {'category': 'security', 'suggestion': 'Sanitize user input and verify the final path is within the expected directory.'},
    'LEGACY_SEC021_crlf_injection': {'category': 'security', 'suggestion': 'Sanitize all user input used in HTTP headers to prevent \\r\\n injection.'},
    'LEGACY_SEC022_jwt_misuse': {'category': 'security', 'suggestion': 'Use TokenValidationParameters with ValidateIssuer/ValidateAudience/ValidateLifetime/ValidateIssuerSigningKey all set to true. Never accept "alg": "none". Reject tokens without "exp" claim. Use HS256/RS256 with secure key storage.'},
    'LEGACY_SEC023_cors_misconfig': {'category': 'security', 'suggestion': 'Use an explicit origin allowlist (WithOrigins("https://example.com")). Never combine AllowAnyOrigin with AllowCredentials. If credentials are required, list specific trusted origins. Note: this regex is line-bounded; multi-line CORS policies in fluent builders are detected via the .NET SDK 6+ Roslyn analyzer when available.'},
    'LEGACY_SEC024_open_redirect': {'category': 'security', 'suggestion': 'Validate returnUrl/RedirectUrl against an allowlist of safe paths. Use Url.IsLocalUrl(returnUrl) to ensure the redirect stays on the same site. Never pass user input directly to Redirect().'},
    'LEGACY_SEC_hardcoded_secret': {'category': 'security', 'suggestion': 'Store secrets in environment variables, Azure Key Vault, or user secrets.'},
    'LEGACY_SEC_secret_format': {'category': 'security', 'suggestion': 'The literal value matches a known credential format (AWS/GitHub/Slack/JWT/PEM/Google). Remove from source and load from a secret manager.'},
    'LEGACY_SEC_secret_entropy': {'category': 'security', 'suggestion': 'The literal has high Shannon entropy, characteristic of a key/token. Confirm whether this is a real secret; if so, move it to a secret manager or environment variable.'},
    'LEGACY_TLS_cert_validation_disabled': {'category': 'security', 'suggestion': 'Remove the callback entirely, or implement real certificate validation (chain, errors, thumbprint/pin). Returning true unconditionally disables all TLS MITM protection (CWE-295).'},
    'LEGACY_SEM003_enum_no_none': {'category': 'semantic', 'suggestion': 'Add a None=0 member as the default value.'},
    'LEGACY_SEM004_idisposable_no_using': {'category': 'semantic', 'suggestion': 'Wrap in a `using` statement or `using var` declaration.'},
    'LEGACY_SEM006_struct_no_equalsequals': {'category': 'style', 'suggestion': ''},
    'LEGACY_SEM007_captured_loop_variable': {'category': 'style', 'suggestion': ''},
    'LEGACY_SEM008_class_no_equalsequals': {'category': 'style', 'suggestion': ''},
    'LEGACY_SH001_hardcoded_key': {'category': 'security-hotspot', 'suggestion': 'Use a secure key management system for encryption keys.'},
    'LEGACY_SH002_insecure_random': {'category': 'security-hotspot', 'suggestion': 'Use RNGCryptoServiceProvider or RandomNumberGenerator for cryptographic purposes.'},
    'LEGACY_SH005_weak_crypto': {'category': 'security-hotspot', 'suggestion': 'Use AES-256 for symmetric encryption and SHA-256 or stronger for hashing.'},
    'LEGACY_SH006_insecure_ssl_tls': {'category': 'security-hotspot', 'suggestion': 'Use TLS 1.2 or higher for secure communication.'},
    'LEGACY_SH007_insecure_cookie': {'category': 'security-hotspot', 'suggestion': 'Set Secure=true, HttpOnly=true, and SameSite=Strict for cookies.'},
    'LEGACY_SH008_insecure_file_perm': {'category': 'security-hotspot', 'suggestion': 'Use least privilege principle for file access.'},
    'LEGACY_SH009_insecure_network': {'category': 'security-hotspot', 'suggestion': 'Use TLS for secure network communication.'},
    'LEGACY_SH010_insecure_data_binding': {'category': 'security-hotspot', 'suggestion': 'Validate and sanitize data before binding.'},
    'LEGACY_SH011_cookie_no_secure': {'category': 'security-hotspot', 'suggestion': 'Always set cookie.Secure = true to ensure cookies are only transmitted over HTTPS.'},
    'LEGACY_SHA_Password': {'category': 'security', 'suggestion': 'Use Rfc2898DeriveBytes (PBKDF2), BCrypt.Net, or Argon2 for password hashing.'},
    'LEGACY_SQL_Concat_In_Method': {'category': 'style', 'suggestion': ''},
    'LEGACY_SqlCommand_Concat': {'category': 'security', 'suggestion': 'Use parameterized queries instead of concatenation.'},
    'LEGACY_SqlMethods_Like': {'category': 'security', 'suggestion': 'Use parameterized queries with escaped LIKE patterns.'},
    'LEGACY_T001_missing_test_attribute': {'category': 'test', 'suggestion': 'Consider adding [Test] attribute or marking method as test helper.'},
    'LEGACY_T002_no_assert': {'category': 'test', 'suggestion': 'Add Assert.Equal, Assert.True, etc. to validate behavior.'},
    'LEGACY_T004_empty_test': {'category': 'test', 'suggestion': 'Implement the test or remove it.'},
    'LEGACY_T005_hardcoded_test_data': {'category': 'test', 'suggestion': 'Use named constants for test data to improve readability.'},
    'LEGACY_T006_async_void_test': {'category': 'test', 'suggestion': 'Change async void to async Task for proper async test execution.'},
    'LEGACY_T008_test_magic_sleep': {'category': 'test', 'suggestion': 'Use a named constant for sleep duration in tests.'},
    'LEGACY_T010_no_teardown': {'category': 'test', 'suggestion': 'Use IDisposable pattern or [TestCleanup]/[TestTearDown] for cleanup.'},
    'LEGACY_T016_datetime_now': {'category': 'testability', 'suggestion': 'Inject IFileSystem/IEnvironment abstractions (e.g., System.IO.Abstractions) or pass the value as a parameter. For DateTime.Now, inject ITimeProvider/IClock. For environment variables, use IOptions<T> with a strongly-typed config class.'},
    'LEGACY_T017_static_io': {'category': 'testability', 'suggestion': 'Inject ITimeProvider/IClock (Microsoft.Extensions.TimeProvider.Testing) and call _timeProvider.GetUtcNow(). Reserve DateTime.Now for presentation layer / logging where wall-clock time is genuinely required. Test classes that intentionally use DateTime.Now can be excluded via the project .editorconfig analyzer rule_id:T017.severity=none override.'},
    'LEGACY_Thread_New': {'category': 'test', 'suggestion': ''},
    'LEGACY_Thread_Sleep': {'category': 'best-practice', 'suggestion': 'Use Task.Delay (async/await) or Timer for non-blocking delays.'},
    'LEGACY_URL_Redirect': {'category': 'security', 'suggestion': 'Validate redirect URLs against an allowlist to prevent open redirect attacks.'},
    'LEGACY_WebClient': {'category': 'security', 'suggestion': 'Validate and allowlist all URLs before making HTTP requests.'},
    'LEGACY_WinForms_DoEvents': {'category': 'best-practice', 'suggestion': ''},
    'LEGACY_WinForms_Invoke': {'category': 'best-practice', 'suggestion': ''},
    'LEGACY_WIN01_registry': {'category': 'reliability', 'suggestion': 'Microsoft.Win32.Registry is Windows-only. Use appsettings.json / environment variables / IOptions<T> for cross-platform config.'},
    'LEGACY_WIN02_system_drawing': {'category': 'reliability', 'suggestion': 'System.Drawing.Common is Windows-only since .NET 6. Use ImageSharp / SkiaSharp / Magick.NET for cross-platform image processing.'},
    'LEGACY_WIN03_event_log': {'category': 'reliability', 'suggestion': 'EventLog is Windows-only. Use a logging framework (Serilog) or OpenTelemetry for cross-platform logging.'},
    'LEGACY_WIN04_wmi': {'category': 'reliability', 'suggestion': 'System.Management (WMI) is Windows-only. Use a CLI wrapper or platform-specific abstraction.'},
    'LEGACY_XmlDocument': {'category': 'security', 'suggestion': 'Set XmlDocument.XmlResolver = null before Load, or use XmlReader with DtdProcessing=Prohibit.'},
    'LEGACY_async_lambda_no_await': {'category': 'best-practice', 'suggestion': ''},
    'LEGACY_async_void': {'category': 'best-practice', 'suggestion': 'Use async Task instead of async void.'},
    'LEGACY_async_void_event': {'category': 'reliability', 'suggestion': 'Use async Task for event handlers where possible.'},
    'LEGACY_async_void_lambda': {'category': 'best-practice', 'suggestion': 'Use async Task instead of async void.'},
    'LEGACY_catch_AggregateException': {'category': 'reliability', 'suggestion': 'Use .Flatten() and .Handle() to process each inner exception individually.'},
    'LEGACY_catch_exception': {'category': 'best-practice', 'suggestion': 'Catch specific exception types to avoid masking unexpected errors.'},
    'LEGACY_div_by_zero': {'category': 'best-practice', 'suggestion': ''},
    'LEGACY_dynamic_local': {'category': 'semantic', 'suggestion': 'Consider using interfaces or explicit casting instead of dynamic.'},
    'LEGACY_empty_catch': {'category': 'best-practice', 'suggestion': 'Remove the catch block, log the exception, or re-throw.'},
    'LEGACY_empty_string_compare': {'category': 'performance', 'suggestion': 'Use string.IsNullOrEmpty() for null and empty checks.'},
    'LEGACY_equals_no_gethashcode': {'category': 'semantic', 'suggestion': 'Override GetHashCode whenever Equals is overridden.'},
    'LEGACY_lock_this': {'category': 'best-practice', 'suggestion': 'Lock on a dedicated private readonly object.'},
    'LEGACY_lock_typeof': {'category': 'best-practice', 'suggestion': 'Lock on a dedicated private readonly object.'},
    'LEGACY_missing_StringComparison': {'category': 'performance', 'suggestion': 'Specify StringComparison.Ordinal for performance and correctness.'},
    'LEGACY_new_string_char_int': {'category': 'performance', 'suggestion': 'Consider using string interpolation or StringBuilder.'},
    'LEGACY_null_assignment': {'category': 'reliability', 'suggestion': 'Check for null before dereferencing.'},
    'LEGACY_reflection_in_loop': {'category': 'performance', 'suggestion': 'Cache reflection results outside of loops.'},
    'LEGACY_single_letter_var': {'category': 'naming', 'suggestion': "Use descriptive variable names (e.g., 'index' instead of 'i' for non-loop variables)."},
    'LEGACY_string_eq': {'category': 'best-practice', 'suggestion': ''},
    'LEGACY_string_format_in_loop': {'category': 'performance', 'suggestion': 'Use StringBuilder.AppendFormat or interpolation for better performance.'},
    'LEGACY_test_shared_state': {'category': 'test', 'suggestion': 'Avoid static mutable state in tests to prevent test order dependencies.'},
    'LEGACY_throw_ex': {'category': 'best-practice', 'suggestion': "Use 'throw;' (without the exception variable) to preserve the stack trace."},
    'SEM_TYPE_GETTYPE_CONCAT': {'category': 'security', 'suggestion': 'Validate type names against an allowlist.'},
    'SEM_TYPE_GETTYPE_USERINPUT': {'category': 'security', 'suggestion': 'Validate type names against an allowlist.'},
    'LEGACY_DI1001_too_many_ctor_params': {'category': 'design', 'suggestion': 'A constructor with more than 4 parameters suggests the class has too many responsibilities. Extract dependencies into parameter objects or split the class.'},
    'LEGACY_DI_service_locator': {'category': 'design', 'suggestion': 'Avoid Service Locator anti-pattern. Use constructor injection to make dependencies explicit and testable.'},
    'LEGACY_SA1001_generic_spacing': {'category': 'style', 'suggestion': 'Insert a space before < in generic type references: List<T> → List <T>.'},
    'LEGACY_SA1002_one_statement_per_line': {'category': 'style', 'suggestion': 'Place only one statement per line. Avoid multiple statements or declarations on the same line.'},
    'LEGACY_SA1103_base_this_spacing': {'category': 'style', 'suggestion': 'Add a space between : and base/this in constructor initializer: :base(x) → : base(x).'},
    'LEGACY_SA1113_brace_indent': {'category': 'style', 'suggestion': 'Opening brace should not be followed by statements on the same line.'},
    'LEGACY_SA1118_parameter_newline': {'category': 'style', 'suggestion': 'In a multi-line parameter list, each parameter must be on its own line.'},
    'SEM_OUTREF_NULL_SAFE': {'category': 'reliability', 'suggestion': 'C# mandates out/ref parameters be assigned on every return path; null on a failure path is the required language idiom and not a latent NullReferenceException.'},
}

AUTO_FIXES: dict[str, list[dict]] = {
    "S002": [
        {
            "find": r"//\s*FIXME\b[^\n]*",
            "replace": "// REVIEW: needs an issue link",
            "description": "Replace FIXME comments with REVIEW marker",
        },
    ],
    "S003": [
        {
            # Tempered-dot pattern: matches #region..#endregion without crossing
            # nested #region boundaries. Outer region needs a second pass when
            # nested regions exist, but never produces orphaned #region/#endregion.
            "find": (
                r"\n\s*#region\b[^\n]*\n"
                r"(?:(?!\n\s*#(?:region|endregion)\b)[\s\S])*"
                r"\n\s*#endregion\b[^\n]*\n"
            ),
            "replace": "\n",
            "description": "Remove #region/#endregion blocks (safe with nesting)",
        },
    ],
    "S005": [
        {
            "find": r"^\s*//\s*(?:if|for|foreach|while|switch|return|var|int|string|bool)\b[^\n]*\n",
            "replace": "",
            "description": "Remove commented-out code",
        },
    ],
    # CS002 intentionally excluded — removing unused parameters requires
    # understanding the full signature and callers, which a single regex
    # cannot safely do.
    "BP010": [
        {
            "find": r"throw\s+new\s+NotImplementedException\s*\(\s*\)\s*;",
            "replace": "throw new NotSupportedException(\"Not implemented\");",
            "description": "Replace NotImplementedException with NotSupportedException",
        },
    ],
    # S001: TODO without author -> insert empty owner placeholder.
    # Only matches the S001 trigger shape (TODO not followed by ( or :), so
    # already-attributed `// TODO(user): ...` is left untouched.
    "S001": [
        {
            "find": r"(//\s*TODO)(?![(:])(\s*)",
            "replace": r"\1():\2",
            "description": "Add empty owner placeholder to TODO comments",
        },
    ],
    # P010: `x == ""` -> `string.IsNullOrEmpty(x)`. Captures the identifier and
    # rewrites the whole comparison. Only matches the simple identifier form
    # (`\w+`), so member-access like `this.x == ""` is intentionally NOT touched
    # (rewriting those needs balanced-expression awareness).
    "P010": [
        {
            "find": r"(\b[A-Za-z_]\w*)\s*==\s*\"\"",
            "replace": r"string.IsNullOrEmpty(\1)",
            "description": "Rewrite `x == \"\"` as string.IsNullOrEmpty(x)",
        },
        {
            "find": r"\"\"\s*==\s*(\b[A-Za-z_]\w*)",
            "replace": r"string.IsNullOrEmpty(\1)",
            "description": "Rewrite `\"\" == x` as string.IsNullOrEmpty(x)",
        },
    ],
    # BP011: `throw ex;` loses the original stack trace. Rethrow with `throw;`
    # to preserve it. Only matches a bare identifier (not `throw new ...`),
    # so `throw new InvalidOperationException()` is untouched.
    "BP011": [
        {
            "find": r"\bthrow\s+([A-Za-z_]\w*)\s*;",
            "replace": r"throw;",
            "description": "Replace `throw ex;` with `throw;` to preserve stack trace",
        },
    ],
    # S006: `new String('x', n)` → `new string(...)` — C# convention is
    # lowercase `string`/`char` type keywords. Only matches the capitalized
    # `String` constructor form, not `string` (already correct).
    "S006": [
        {
            "find": r"\bnew\s+String\s*\(",
            "replace": "new string(",
            "description": "Capitalize `new String(` to `new string(`",
        },
    ],
    # R021: throw new Exception(...) → throw new InvalidOperationException(...)
    "R021": [
        {
            "find": r"\bthrow\s+new\s+Exception\s*\(",
            "replace": "throw new InvalidOperationException(",
            "description": "Replace overly broad Exception with InvalidOperationException",
        },
        {
            "find": r"\bthrow\s+new\s+ApplicationException\s*\(",
            "replace": "throw new InvalidOperationException(",
            "description": "Replace overly broad ApplicationException with InvalidOperationException",
        },
        {
            "find": r"\bthrow\s+new\s+System\.Exception\s*\(",
            "replace": "throw new System.InvalidOperationException(",
            "description": "Replace System.Exception with System.InvalidOperationException",
        },
    ],
}

TEST_PROJECT_RELAXED_RULES = {
    "BP001",  # Console.WriteLine OK in tests
    "BP010",  # NotImplementedException OK in tests
    "LEGACY_Console_Write",  # Roslyn migration of BP001
    "LEGACY_NotImplementedException",  # Roslyn migration of BP010
}


# Windows-only API rules — suppressed when the target framework is itself
# Windows-only (.NET Framework, or net*-windows TFM). These APIs are only a
# problem in CROSS-PLATFORM projects where they crash at runtime on Linux/macOS.
WIN_ONLY_API_RULES = {
    "LEGACY_WIN01_registry",
    "LEGACY_WIN02_system_drawing",
    "LEGACY_WIN03_event_log",
    "LEGACY_WIN04_wmi",
}


_AST_PREFIX_CATEGORY: list[tuple[str, str]] = [
    ("LEGACY_SEC", "security"),
    ("LEGACY_SH", "security-hotspot"),
    ("LEGACY_BP", "best-practice"),
    ("LEGACY_R0", "reliability"),
    ("LEGACY_R", "reliability"),
    ("LEGACY_P0", "performance"),
    ("LEGACY_P", "performance"),
    ("LEGACY_N", "naming"),
    ("LEGACY_T0", "test"),
    ("LEGACY_T", "test"),
    ("LEGACY_WIN", "reliability"),
    ("LEGACY_S", "style"),
    ("SEM_", "semantic"),
]


def _fallback_category(ast_rule_id: str) -> str:
    """Infer a scoring category from the AST rule ID prefix."""
    for prefix, cat in _AST_PREFIX_CATEGORY:
        if ast_rule_id.startswith(prefix):
            return cat
    return "best-practice"


# ============================================================
# Rule Triage Classification
# ============================================================
RULE_TRIAGE: dict[str, str] = {
    "LEGACY_SqlCommand_Concat": "deterministic",
    "LEGACY_SEC024_open_redirect": "agent_verify",
    "LEGACY_SEC_hardcoded_secret": "agent_verify",
    "LEGACY_SEC_secret_format": "agent_verify",
    "LEGACY_SEC_secret_entropy": "agent_verify",
    "LEGACY_SEC023_cors_misconfig": "agent_verify",
    "LEGACY_ASP003_antiforgery_skip": "agent_verify",
    "LEGACY_BinaryFormatter": "deterministic",
    "LEGACY_CSharpCodeProvider": "deterministic",
    "LEGACY_SH001_hardcoded_key": "agent_verify",
    "LEGACY_SH002_insecure_random": "deterministic",
    "LEGACY_SH005_weak_crypto": "deterministic",
    "LEGACY_SH006_insecure_ssl_tls": "deterministic",
    "LEGACY_SH007_insecure_cookie": "deterministic",
    "LEGACY_TLS_cert_validation_disabled": "deterministic",
    "LEGACY_ASP004_developer_page": "agent_verify",
    "LEGACY_ASP005_no_https_redirect": "agent_verify",
    "LEGACY_ASP006_no_hsts": "agent_verify",
    "LEGACY_ASP002_binding_sensitive": "agent_verify",
    "LEGACY_SqlMethods_Like": "deterministic",
    "LEGACY_URL_Redirect": "agent_verify",
    "LEGACY_XmlDocument": "deterministic",
    "LEGACY_WebClient": "agent_verify",
    "LEGACY_async_void": "deterministic",
    "LEGACY_async_void_event": "agent_verify",
    "LEGACY_async_void_lambda": "deterministic",
    "LEGACY_R026_async_void_action": "deterministic",
    "LEGACY_async_lambda_no_await": "deterministic",
    "LEGACY_BP007_sync_wait": "deterministic",
    "LEGACY_BP007b_getawaiter_getresult": "deterministic",
    "LEGACY_BP008_string_concat_loop": "deterministic",
    "LEGACY_BP021_task_run_server": "agent_verify",
    "LEGACY_BP022_random_shared": "agent_verify",
    "LEGACY_BP023_system_text_json": "agent_verify",
    "LEGACY_BP024_datetime_modern": "agent_verify",
    "LEGACY_Thread_Sleep": "agent_verify",
    "LEGACY_Console_Write": "agent_verify",
    "LEGACY_catch_AggregateException": "deterministic",
    "LEGACY_Catch_Return_Exception": "deterministic",
    "LEGACY_WIN01_registry": "deterministic",
    "LEGACY_WIN02_system_drawing": "deterministic",
    "LEGACY_WIN03_event_log": "deterministic",
    "LEGACY_WIN04_wmi": "deterministic",
    "LEGACY_ArrayList": "deterministic",
    "P021": "agent_verify",
    "SEM003_enum_no_none": "deterministic",
    "SEM004_idisposable_no_using": "deterministic",
    "SEM_OUTREF_NULL_SAFE": "deterministic",
    "SEM_CANCELLATION_TOKEN": "deterministic",
    "EF001": "deterministic", "EF002": "deterministic",
    "EF003": "deterministic", "EF004": "agent_verify",
    "EF005": "deterministic", "EF006": "deterministic",
    "LAYER001": "agent_verify", "ARCH001": "deterministic",
    "ARCH002": "agent_verify", "ARCH003": "agent_verify",
    "ARCH004": "agent_verify", "CS006": "agent_verify",
    "S001": "deterministic", "S002": "deterministic",
    "S005": "deterministic",
    "LEGACY_T002_no_assert": "deterministic",
    "LEGACY_T004_empty_test": "deterministic",
    "LEGACY_T005_hardcoded_test_data": "agent_verify",
    "LEGACY_T006_async_void_test": "deterministic",
    "LEGACY_T008_test_magic_sleep": "agent_verify",
    "LEGACY_T010_no_teardown": "agent_verify",
    "DI001": "agent_verify",
    "RCS0052": "deterministic",
    "RCS0096": "deterministic",
    "RCS0018": "deterministic",
    "RCS0013": "deterministic",
    "RCS0045": "deterministic",
    # StyleCop SA rules
    "LEGACY_SA1001_generic_spacing": "deterministic",
    "LEGACY_SA1002_one_statement_per_line": "deterministic",
    "LEGACY_SA1103_base_this_spacing": "deterministic",
    "LEGACY_SA1113_brace_indent": "deterministic",
    "LEGACY_SA1118_parameter_newline": "deterministic",
}


# Verification hints for agent_verify rules — tells Agent what to check
RULE_VERIFICATION_HINTS: dict[str, list[str]] = {
    "LEGACY_SEC_hardcoded_secret": [
        "Check if value is in a test method ([Test]/[Fact]/[TestMethod])",
        "Check if variable name contains 'test', 'sample', 'dummy', 'placeholder'",
    ],
    "LEGACY_SEC_secret_format": [
        "Verify if this is a real credential or a placeholder/test value",
    ],
    "LEGACY_SEC_secret_entropy": [
        "High entropy suggests a real key/token — verify if production code",
    ],
    "LEGACY_SH001_hardcoded_key": [
        "Check if the key is a well-known constant (IV, salt)",
    ],
    "LEGACY_BP021_task_run_server": [
        "Check if ASP.NET Core pipeline (problematic) vs background service/CLI (OK)",
        "If project does not reference Microsoft.AspNetCore, likely safe",
    ],
    "LEGACY_BP023_system_text_json": [
        "Check if Newtonsoft features not in STJ are needed (JsonPath, schema)",
    ],
    "LEGACY_BP024_datetime_modern": [
        "DateTime.Now acceptable in presentation/logging layers",
    ],
    "LEGACY_ASP003_antiforgery_skip": [
        "Verify this is stateless API with token auth (not cookie auth)",
    ],
    "LEGACY_ASP004_developer_page": [
        "Check if inside if (env.IsDevelopment()) guard",
    ],
    "LEGACY_ASP005_no_https_redirect": [
        "Check if HTTPS handled by reverse proxy (IIS, nginx, YARP)",
    ],
    "LEGACY_ASP006_no_hsts": [
        "Check if HSTS configured at reverse proxy level",
    ],
    "LEGACY_SEC024_open_redirect": [
        "Check if redirect target validated with Url.IsLocalUrl() or allowlist",
    ],
    "LEGACY_SEC023_cors_misconfig": [
        "Check if AllowAnyOrigin + AllowCredentials truly combined in same policy",
    ],
    "LEGACY_ASP002_binding_sensitive": [
        "Check if property has [BindNever] or dedicated request DTO is used",
    ],
    "LEGACY_Thread_Sleep": [
        "Check if in test code or initialization/setup code",
    ],
    "LEGACY_Console_Write": [
        "Check if CLI/console application (Console.Write expected)",
    ],
    "LEGACY_URL_Redirect": [
        "Check if redirect URL validated against allowlist",
    ],
    "LEGACY_WebClient": [
        "Check if URLs are from config/constants (not user input)",
    ],
    "LEGACY_async_void_event": [
        "Event handlers in WinForms/WPF legitimately use async void",
    ],
    "P021": ["Check if hot-path method (called frequently in loop)"],
    "EF004": ["Check if query result is modified and saved later"],
    "LAYER001": [
        "Check if dependency is through an interface (acceptable abstraction)",
    ],
    "ARCH002": ["Check if type is entry point or used via reflection/DI"],
    "ARCH003": ["Check if method is Web API endpoint ([HttpGet], [HttpPost])"],
    "ARCH004": ["Check if interface implemented in different assembly/project"],
    "CS006": [
        "Check if class is legitimate facade/aggregate (DbContext, orchestrator)",
    ],
    "DI001": [
        "High param count acceptable for composition root / facade patterns",
    ],
    "LEGACY_T005_hardcoded_test_data": [
        "Trivially simple data acceptable for unit tests",
    ],
    "LEGACY_T008_test_magic_sleep": [
        "Check if sleep is for async retry/polling — may need real delay",
    ],
    "LEGACY_T010_no_teardown": [
        "Check if test uses IDisposable instead of [TestCleanup]",
    ],
    # Note: RCS0013/0018/0045/0052/0096 and the StyleCop SA1001/1002/1103/1113/1118
    # rules are NOT in RULE_VERIFICATION_HINTS. They are triaged 'deterministic'
    # (the semantic analyzer resolves them against a fully-bound model), so per
    # the invariant in test_triage.test_hints_dict_subset_of_triage they carry
    # no agent-verification hints. Their actionable guidance lives in
    # AST_RULE_META[...]['suggestion'].
}


def get_triage_for_rule(rule_id: str) -> str:
    """Return the triage level for a rule ID. Fallback: 'deterministic'."""
    return RULE_TRIAGE.get(rule_id, "deterministic")


def get_verification_hints(rule_id: str) -> list[str]:
    """Return verification hints for agent_verify rules."""
    return RULE_VERIFICATION_HINTS.get(rule_id, [])


def get_ast_rule_meta(ast_rule_id: str) -> dict[str, str]:
    """Return {category, suggestion} for an AST rule ID.

    Looks up AST_RULE_META first; falls back to prefix-inferred
    category and empty suggestion if the rule ID is unknown."""
    return AST_RULE_META.get(
        ast_rule_id,
        {"category": _fallback_category(ast_rule_id), "suggestion": ""},
    )
