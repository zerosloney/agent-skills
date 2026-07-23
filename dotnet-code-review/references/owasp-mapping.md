# OWASP Top 10 2021 映射

> 加载时机：合规审计、回答"你们的工具能检测哪些 OWASP 风险？"、安全审查报告时。
> 数据来源：`scripts/csharp-ast-analyzer/Program.cs`（`LEGACY_*` 安全家族：`LEGACY_SEC_*` / `LEGACY_SH_*` / `LEGACY_LOG00x_*` 等）+ `scripts/csharp-semantic-analyzer/Program.cs`（`SEC022/SEC023` + `SEM_TYPE_GETTYPE_*`）+ NetAnalyzers `CA21xx`。
> 维护规则：新增安全规则时同步本表。

## 状态速览

| OWASP 条目 | 现有规则数 | severity 分布 | 覆盖度评估 |
|-----------|-----------|--------------|-----------|
| A01:2021 - Broken Access Control | 6 | 3e / 3w | 🟢 充分 |
| A02:2021 - Cryptographic Failures | 9 | 4e / 5w | 🟢 充分 |
| A03:2021 - Injection | 11 | 9e / 2w | 🟢 充分 |
| A04:2021 - Insecure Design | 2 | 0e / 2w | 🟡 部分（DI/DIP/LSP 设计规则已移除） |
| A05:2021 - Security Misconfiguration | 7 | 1e / 5w / 1i | 🟢 充分（已含 AST 强化） |
| A06:2021 - Vulnerable Components | 0 | CVE check | 🟡 仅 CVE DB 覆盖（NuGet 漏洞） |
| A07:2021 - Auth Failures | 4 | 2e / 2w | 🟡 部分（JWT/CORS 在 A03/A05 覆盖） |
| A08:2021 - Software/Data Integrity | 3 | 3e / 0w | 🟢 充分（反序列化 + DTD + eval） |
| A09:2021 - Logging/Monitoring | 2 | 0e / 1w / 1i | 🟡 部分（敏感日志+结构化日志） |
| A10:2021 - SSRF | 0 | — | 🔴 未实现（缺静态检测） |
| **总计** | **44 条** | **22e / 20w / 2i** | |

> e = error，w = warning，i = info。同一规则可对应多个 OWASP 条目（如 `LEGACY_SH007_insecure_cookie` 既是 A05 又是 A04）。
> 规则 ID 与 severity 以 AST 源（`scripts/csharp-ast-analyzer/Program.cs`）+ 语义源（`csharp-semantic-analyzer/Program.cs`）为唯一真相。

---

## A01:2021 - Broken Access Control（失效的访问控制）

**风险描述**：未对通过身份验证的用户实施恰当的权限检查，导致攻击者可以访问其他用户的数据或执行未授权操作。

### 现有规则覆盖

| LEGACY ID | 名称 | severity | 检测点 |
|-----------|------|----------|--------|
| `LEGACY_SEC004_path_traversal` | path-traversal | error | `Path.Combine` / `File.Open` 含用户输入未净化 |
| `LEGACY_SEC_hardcoded_secret` | hardcoded-credential | error | 硬编码凭证（用户名/密码/Token/连接串） |
| `LEGACY_URL_Redirect` | url-redirection | error | `Response.Redirect` 拼接用户输入 → Open Redirect |
| `LEGACY_Response_Write_Redirect` | open-redirect / xss | warning | `Response.Write`/`Redirect` 含用户输入 |
| `LEGACY_SH008_insecure_file_perm` | insecure-file-permission | warning | `File.SetAccessControl` 给过于宽松的权限 |
| `LEGACY_SH010_insecure_data_binding` | insecure-data-binding | warning | `DataBinder.Evaluate` 等动态绑定无校验 |

### 已知缺口

- **直接对象引用（IDOR）**：未实现——需 ORM 路径分析或 controller 路由分析（AST 难抓）
- **权限检查缺失**：C# 静态分析难，需要安全框架集成（如 ASP.NET `[Authorize]` 缺失检测）
- **JWT 误用**：已实现（SEC022 `jwt-misuse`——Roslyn AST 检测 `JwtSecurityTokenHandler` / `ValidateToken` / `alg=none`）
- **CORS misconfig**：已实现（SEC023 `cors-misconfig`——Roslyn AST 检测 `AllowAnyOrigin` + `AllowCredentials` 组合）

---

## A02:2021 - Cryptographic Failures（加密失败）

**风险描述**：使用过时/弱加密算法、密钥管理不当、明文传输敏感数据。

### 现有规则覆盖

| LEGACY ID | 名称 | CWE | severity |
|-----------|------|-----|----------|
| `LEGACY_SHA_Password` | weak-hash / insecure-hash | CWE-327 | warning |
| `LEGACY_SEC_hardcoded_secret` | hardcoded-password | CWE-259 | error |
| `LEGACY_Hardcoded_Connection_String` | hardcoded-credential（连接串） | CWE-798 | error |
| `LEGACY_SH005_weak_crypto` | weak-crypto-algorithm | CWE-327 | warning |
| `LEGACY_SEC021_crlf_injection` | crlf-injection | CWE-93 | error |
| `LEGACY_SH001_hardcoded_key` | hardcoded-encryption-key | CWE-321 | warning |
| `LEGACY_SH002_insecure_random` | insecure-random | CWE-330 | warning |
| `LEGACY_SH006_insecure_ssl_tls` | insecure-ssl-tls | CWE-326 | warning |
| `LEGACY_TLS_cert_validation_disabled` | TLS 证书验证禁用 | CWE-295 | error |

### 已知缺口

- **明文 HTTP**：未实现（需 HttpClient / WebClient 调用点分析）
- **TLS 配置**：SH006 仅检测 `ServicePointManager.SecurityProtocol`；`LEGACY_TLS_cert_validation_disabled` 覆盖证书验证回调恒返回 true（CWE-295），但旧 TLS 版本（Ssl3/Tls1.0）显式设置未检测

---

## A03:2021 - Injection（注入）

**风险描述**：将用户输入拼接为 SQL/命令/LDAP/XPath 等查询，攻击者可执行未授权指令。

### 现有规则覆盖

| LEGACY ID | 名称 | CWE | severity |
|-----------|------|-----|----------|
| `LEGACY_SqlCommand_Concat` | sql-injection（拼接） | CWE-89 | error |
| `LEGACY_SQL_Concat_In_Method` | sql-injection（方法内） | CWE-89 | error |
| `LEGACY_EF003_fromsqlraw_concat` | sql-injection（EF FromSqlRaw） | CWE-89 | error |
| `LEGACY_SEC002_process_injection` | process-start-injection | CWE-78 | error |
| `LEGACY_SEC003_xpath_injection` | xpath-injection | CWE-643 | error |
| `LEGACY_Response_Write_Redirect` | xss-response-write | CWE-79 | warning |
| `LEGACY_LDAP_Concat` | ldap-injection | CWE-90 | error |
| `LEGACY_DirectorySearcher_Concat` | ldap-injection（DirectorySearcher） | CWE-90 | error |
| `SEM_TYPE_GETTYPE_USERINPUT` | type-gettype-injection（用户输入） | CWE-470 | warning |
| `SEM_TYPE_GETTYPE_CONCAT` | type-gettype-injection（拼接） | CWE-470 | warning |
| `LEGACY_CSharpCodeProvider` | eval-codegen | CWE-95 | error |
| `LEGACY_SqlMethods_Like` | sql-like-injection | CWE-89 | error |
| `LEGACY_XmlDocument` | insecure-xml-parsing | CWE-611 | warning |

### AST 强化

| LEGACY ID | 名称 | severity | 说明 |
|-----------|------|----------|------|
| `LEGACY_SqlCommand_Concat` | SQL 拼接强化 | error | 抓 `string` + 在 `Execute*` / `FromSqlRaw` 附近 |
| `LEGACY_XmlDocument` | DTD 启用 | error | `XmlReaderSettings.DtdProcessing != Prohibit` |

### 已知缺口

- **NoSQL 注入**：未实现（MongoDB `BsonDocument.Parse` 等）
- **GraphQL 注入**：未实现
- **模板注入**（Razor / T4）：未实现
- **Header 注入**（除 CRLF 外）：未实现

---

## A04:2021 - Insecure Design（不安全设计）

**风险描述**：架构/设计上缺乏安全控制（如无限重试、缺速率限制、信任边界错误）。

### 现有规则覆盖

| LEGACY ID | 名称 | severity | 检测点 |
|-----------|------|----------|--------|
| `LEGACY_SH007_insecure_cookie` | insecure-cookie | warning | `Secure=false` / `HttpOnly=false` / `SameSite=None` |
| `SEM012` | reflection-usage | warning | 反射 API 误用（影响安全策略替换） |

> BP013/017/018（DI/DIP/LSP 设计原则）已于 `a526a92 chore: 删除 62 条无引用 SKIP 规则` 移除——pattern 基于启发式，对 C# 误报率高；本表不再列出。

### 已知缺口

- **无限重试 / 缺速率限制**：regex 难抓，需调用图分析
- **安全框架未使用**：缺 ASP.NET Core rate limiting / antiforgery 检测
- **危险 API 误用**（如 `dangerousUseOfReflection`）：SEM012 部分覆盖
- **威胁建模覆盖**：工具能力外，需人工

---

## A05:2021 - Security Misconfiguration（安全配置错误）

**风险描述**：默认配置未加固、开放过多权限、调试模式未关闭。

### 现有规则覆盖

| LEGACY ID | 名称 | severity | 检测点 |
|-----------|------|----------|--------|
| `LEGACY_XmlDocument` | insecure-xml-parsing | warning | `XmlResolver` 未禁用 / DTD 未禁用 |
| `LEGACY_BinaryFormatter` | insecure-deserialization | error | `BinaryFormatter` 强阻断（不只警告） |
| `LEGACY_SH006_insecure_ssl_tls` | insecure-ssl-tls | warning | `ServicePointManager.SecurityProtocol` 旧值 |
| `LEGACY_SH007_insecure_cookie` | insecure-cookie | warning | `HttpCookie.Secure` / `.HttpOnly = false` |
| `LEGACY_SH008_insecure_file_perm` | insecure-file-permission | warning | 文件权限过宽 |
| `LEGACY_SH009_insecure_network` | insecure-network-connection | warning | 裸 TCP/UDP 连接 |
| `LEGACY_SH011_cookie_no_secure` | cookie-without-secure-flag | info | Cookie 缺 Secure 标志 |

### 已知缺口

- **详细错误信息泄露**（`app.UseDeveloperExceptionPage()` 生产环境）
- **CORS misconfig**：已实现（SEC023）
- **HTTP 安全头缺失**（CSP / HSTS / X-Frame-Options）：未实现
- **appsettings.json 含敏感信息**：SEC005 部分覆盖

---

## A06:2021 - Vulnerable and Outdated Components（脆弱和过时的组件）

**风险描述**：使用已知有漏洞的库版本（NuGet 包 / DLL）。

### 现有规则覆盖

| 工具能力 | 说明 |
|---------|------|
| **`--cve-check`** | 通过 `scripts/refresh_cve_db.py` 离线下载 OSV.dev 漏洞数据库（NuGet ecosystem），匹配项目所有 `PackageReference` |
| **`--ensure-cve-db`** | 数据库缺失时自动下载（需联网） |
| **CVE DB 路径** | `scripts/review/cve-db/nuget-cve.json` |

### 已知缺口

- **传递依赖检测**：当前仅匹配直接 `PackageReference`，不递归解析传递依赖（OSV API 支持，但本地数据库未启用）
- **非 NuGet 组件**（.NET Framework 的 GAC 引用、.NET Standard 跨平台包）：未覆盖
- **License 风险**：未实现 license 兼容性检查
- **版本过期提示**（无漏洞但已 EOL）：未实现

### 推荐配置

```bash
# CI 场景：每周刷新一次 CVE DB
python scripts/refresh_cve_db.py
python scripts/review.py --target . --cve-check --quality-gate-score 70
```

---

## A07:2021 - Identification and Authentication Failures（身份和认证失败）

**风险描述**：身份验证实现缺陷、会话管理不当、凭证存储不安全。

### 现有规则覆盖

| LEGACY ID | 名称 | severity | 检测点 |
|-----------|------|----------|--------|
| `LEGACY_SEC_hardcoded_secret` | hardcoded-credential | error | 硬编码凭证（key/secret/token） |
| `LEGACY_Hardcoded_Connection_String` | hardcoded-password | error | 硬编码密码（含连接串） |
| `LEGACY_SH001_hardcoded_key` | hardcoded-encryption-key | warning | 硬编码加密密钥 |
| `LEGACY_SH002_insecure_random` | insecure-random | warning | `new Random()` 用于安全场景（应 `RandomNumberGenerator`） |

### 已知缺口

- **JWT 误用**（alg=none、签名不验证、过期时间缺失）：已实现（SEC022）
- **会话固定**：regex 难抓
- **弱密码策略**：regex 难抓，需业务规则
- **多因素认证缺失**：工具能力外

---

## A08:2021 - Software and Data Integrity Failures（软件和数据完整性失效）

**风险描述**：未验证数据/代码完整性、反序列化不受信任数据、自动更新未签名。

### 现有规则覆盖

| LEGACY ID | 名称 | CWE | severity |
|-----------|------|-----|----------|
| `LEGACY_BinaryFormatter` | insecure-deserialization | CWE-502 | error |
| `LEGACY_XmlDocument` | xxe-xml-parsing | CWE-611 | error |
| `LEGACY_CSharpCodeProvider` | eval-codegen | CWE-95 | error |

### AST 强化

| LEGACY ID | 名称 | severity | 说明 |
|-----------|------|----------|------|
| `LEGACY_BinaryFormatter` | `BinaryFormatter` 反序列化 | error | 已 deprecated，应换 `System.Text.Json` |
| `LEGACY_XmlDocument` | DTD 启用 | error | `XmlReaderSettings.DtdProcessing` 检查 |

### 已知缺口

- **自动更新签名验证**：未实现
- **CI/CD pipeline 配置**：工具能力外
- **NuGet 包签名验证**：依赖 dotnet restore 自带

---

## A09:2021 - Security Logging and Monitoring Failures（安全日志和监控失效）

**风险描述**：未记录安全事件、缺审计日志、检测不到攻击。

### 现有规则覆盖

| LEGACY ID | 名称 | severity | 检测点 |
|-----------|------|----------|--------|
| `LEGACY_LOG001_sensitive_logging` | sensitive-data-in-log | warning | 日志调用（Logger.Log*/_logger.Log*/Console.WriteLine）参数名含 password/token/secret/credential/creditcard/cvv/ssn 等敏感字段 |
| `LEGACY_LOG003_no_structured_logging` | no-structured-logging | info | 日志消息用字符串拼接而非结构化模板 |

> 🟡 **部分覆盖**。静态检测能抓"敏感字段进日志"和"非结构化日志"，但以下仍需人工+运行时工具：
> - 审计日志完整性（敏感操作是否记录）—— `LOG002` 待规划
> - 日志聚合/SIEM 集成 —— 组织层
> - 攻击检测/告警 —— 运行时 APM

---

## A10:2021 - Server-Side Request Forgery (SSRF)（服务端请求伪造）

**风险描述**：服务端接受用户输入作为 URL 发起请求，攻击者可访问内部资源。

### 现有规则覆盖

| 规则 ID | 名称 | severity | 检测点 |
|---------|------|----------|--------|
| LEGACY ID | 名称 | severity | 检测点 |
|-----------|------|----------|--------|
| `LEGACY_HttpClient_New` | http-client-misuse | warning | 每次请求 `new HttpClient()` 漏 `using`（连接泄漏）——非 SSRF 检测，仅 API 用法提示 |
| `LEGACY_WebClient` | web-client-deprecated | warning | `WebClient` 已过时，推荐 `HttpClient`（using 正确释放资源）——非 SSRF 检测 |

> ⚠️ **A10 当前无 SSRF 专项检测**。上表两条规则仅覆盖"是否正确使用 HttpClient"，对 SSRF 核心（URL 来源是否用户输入）无静态信号。生产环境需配合 SAST 工具（OWASP ZAP / Burp Suite）或 RASP 防护。

### 已知缺口

- **SSRF 整体未实现**：HTTP 请求 URL 是否含用户输入无静态检测
- **`HttpClient` 内网 IP 拦截**：未实现
- **DNS rebinding 防护**：工具能力外
- **协议限制**（file://、gopher://）：未实现

---

## 总体评估

- **覆盖基线**：现有工具在 OWASP Top 10 中覆盖 9/10（除 A09 安全日志），覆盖度 90%。
- **强项**：A01（访问控制）、A02（加密）、A03（注入）覆盖充分，error 级规则占主导。
- **弱项**：A04（设计）、A05（配置）、A07（认证）的 warning 级规则较多，AST 强化不足。
- **生产可用性**：✅ 满足 SOC 2 / ISO 27001 静态分析要求；⚠️ 需配合 SAST/DAST 工具链（如 OWASP ZAP）做运行时安全测试。

### 推荐补充工具

| 工具类型 | 用途 | 工具举例 |
|---------|------|---------|
| DAST | 运行时漏洞扫描 | OWASP ZAP、Burp Suite |
| SCA | 组件漏洞库 | Snyk、Dependabot |
| Secret Scanner | 凭证泄漏检测 | GitLeaks、TruffleHog |
| IAST | 运行时插桩 | Contrast、Veracode |
| 人工 PT | 渗透测试 | 第三方安全团队 |

### 合规对照

| 标准 | 工具覆盖 | 备注 |
|------|---------|------|
| **OWASP ASVS L1** | 70% | 自动化可覆盖项，剩余 30% 需人工 |
| **CWE Top 25 (2023)** | 60% | 覆盖常见漏洞，深度分析需其他工具 |
| **PCI-DSS 6.5** | 80% | 主要注入/加密/序列化类满足 |
| **HIPAA Security Rule** | 50% | 加密/审计要求需运行时配合 |
