# rules-catalog

> **职责契约**：本文档是 frontend-audit 自研规则的**唯一权威源**。
> 只包含：每条规则的 ID / 维度 / 严重度 / CWE / triage / 描述 / 修复建议。
> 不包含：评分权重（→ scoring-and-thresholds.md）、输出字段（→ reporting-and-fix.md）。
>
> Agent 使用路径：SKILL.md §2 看到 finding 的 rule id → 本文档查规则细节。
> 数据来源：`scripts/audit/ruledefs/{security,reliability,secrets}.py`。

## 规则总览

共 **13 条**自研规则，按维度分组：

| 维度 | 规则数 | 规则 ID 前缀 |
|------|--------|-------------|
| security | 10 | SEC-REACT / SEC-JS / SEC-SECRET |
| reliability | 2 | RELI-JS |
| best-practice | 0（交给 eslint） | — |
| arch | 0（预留） | — |
| deps | 0（交给 npm audit） | — |

---

## Security 规则

> **Sink 规则的净化抑制（SEC-REACT-001 / SEC-JS-002 / SEC-JS-003 共用）**：
> 这三条规则的"值"若被已知净化/转义函数包裹，则**不报**。识别的净化函数（正则层，大小写不敏感）：`sanitize` / `escapeHtml` / `escape_html` / `encodeHTML` / `encodeURI` / `escape` / `purge` / `stripTags` / `textContent`，允许 `DOMPurify.sanitize(...)` 这类带前缀的形态。
> 这是规则自身修复建议（"用 sanitize 净化"）能真正清掉 finding 的保证。
> **局限**（`intentional-simple`）：正则层只识别单层、直名调用；别名（`const s = sanitize; s(x)`）或嵌套净化不识别。升级路径：tree-sitter 层做精确调用目标解析。

> **已知误报（所有 sink 规则共通）**：正则层不区分代码与字符串字面量，所以**字符串内的 sink 调用会被误报**。例如 `const s = "eval(foo)";` 会触发 SEC-JS-001，尽管它只是一个字符串。Agent 报告这类 finding 时应读上下文确认是否在字符串内（`triage=deterministic` 但 evidence 一眼可辨）。升级路径：tree-sitter 层能区分字符串字面量节点，可消除此类误报。

### SEC-REACT-001 — dangerouslySetInnerHTML with non-literal __html
- **维度**: security | **严重度**: error | **CWE**: CWE-79 | **OWASP**: A03:2021
- **triage**: deterministic（静态可证）
- **检测**: React 的 `dangerouslySetInnerHTML={{__html: <值>}}`，当 `<值>` 既非字面量、也未被净化函数包裹时。
- **修复**: 用 `DOMPurify.sanitize()` 净化后再赋值，或避免 `dangerouslySetInnerHTML`。
- **正例**（触发）: `<div dangerouslySetInnerHTML={{__html: bio}} />`
- **反例**（不触发）: `<div dangerouslySetInnerHTML={{__html: "<b>safe</b>"}} />` 或 `{{__html: sanitize(bio)}}`

### SEC-REACT-002 — bare __html key in object literal
- **维度**: security | **严重度**: error | **CWE**: CWE-79
- **triage**: deterministic
- **检测**: 对象字面量里的裸 `__html: <值>`（即 JSX `dangerouslySetInnerHTML` 之外构造 `{__html: ...}` 对象的形态，如 `const obj = {__html: userInput}`）。SEC-REACT-001 已认领的 `{{__html: ...}}` 偏移会被排除，避免同 sink 重复报。净化抑制见本节开头共通说明。
- **修复**: 同 SEC-REACT-001，用 `DOMPurify.sanitize()` 净化。

### SEC-JS-001 — eval() / new Function() with non-literal argument
- **维度**: security | **严重度**: error | **CWE**: CWE-94（代码注入）
- **triage**: deterministic
- **检测**: `eval(<非字面量>)` 或 `new Function(<非字面量>)`。
- **修复**: 改用 `JSON.parse`、查找表、或专用 parser。

### SEC-JS-002 — document.write with non-literal argument
- **维度**: security | **严重度**: error | **CWE**: CWE-79
- **triage**: deterministic
- **检测**: `document.write(<非字面量且未净化>)` / `document.writeln(...)`。净化抑制见本节开头共通说明。
- **修复**: 用 DOM API（`textContent`、`createElement`）替代。

### SEC-JS-003 — .innerHTML assignment with non-literal value
- **维度**: security | **严重度**: error | **CWE**: CWE-79
- **triage**: deterministic
- **检测**: `el.innerHTML = <非字面量且未净化>`。净化抑制见本节开头共通说明。
- **修复**: 用 `textContent`，或先 `DOMPurify.sanitize()`。

### SEC-JS-004 — window/document.location assignment from non-literal (open redirect)
- **维度**: security | **严重度**: warning | **CWE**: CWE-601
- **triage**: deterministic
- **检测**: `window.location = <非字面量>` 或 `document.location.href = <非字面量>`。
- **修复**: 赋值前用 allow-list 校验 URL，拒绝 `javascript:` 协议。

### SEC-JS-005 — postMessage without origin check
- **维度**: security | **严重度**: warning | **CWE**: CWE-346
- **triage**: **agent_verify**（规则只能看到发送方，看不到接收方的 origin 校验）
- **检测**: 任何 `.postMessage(...)` 调用（低置信度，需 Agent 读接收方代码确认是否校验 `event.origin`）。
- **修复**: 接收方 `if (event.origin !== "https://expected") return;`。

### SEC-SECRET-001/002/003 — 硬编码云厂商密钥
- **维度**: security | **严重度**: error | **CWE**: CWE-798 | **OWASP**: A02:2021
- **triage**: deterministic
- **检测**:
  - 001: AWS Access Key ID（`AKIA` + 16 位大写字母数字）
  - 002: GitHub PAT（`ghp_` + 36+ 位）
  - 003: Google API Key（`AIza` + 35 位）
- **修复**: 移到环境变量 / secrets manager；**已泄露的必须立即轮换**。
- **证据脱敏**: 输出的 evidence 只保留前 6 字符 + `...REDACTED`。

### SEC-SECRET-004 — 可疑密钥变量赋值（启发式）
- **维度**: security | **严重度**: warning | **CWE**: CWE-798
- **triage**: **agent_only**（变量名启发式，不可靠，Agent 调查后可 dismissed）
- **检测**: `const/let/var NAME = "..."`，其中 `NAME`（去分隔符小写后）含 credential 词（`password`/`passwd`/`secret`/`apikey`/`accesstoken`/`authtoken`），且**不以** `mock`/`fake`/`dummy`/`test`/`example`/`sample`/`fixture` 开头。`apiKey`/`MY_PASSWORD`/`accessToken` 触发；`mockApiKey`/`testSecret` 被抑制。
- **修复**: 改为从 `process.env` 读取。

---

## Reliability 规则

### RELI-JS-001 — async callback passed to useEffect
- **维度**: reliability | **严重度**: warning | **CWE**: CWE-754
- **triage**: **agent_verify**
- **检测**: `useEffect(async () => {...}, ...)`——返回值是 Promise 而非 cleanup 函数，rejection 会变成未处理。
- **修复**: `useEffect(() => { const run = async () => {...}; run(); }, [deps])`。

### RELI-JS-002 — addEventListener without matching removeEventListener
- **维度**: reliability | **严重度**: info | **CWE**: CWE-401（资源泄漏）
- **triage**: **agent_verify**（文件级启发式，跨文件未覆盖）
- **检测**: 文件内 `addEventListener("X", ...)` 的事件名集合 减去 `removeEventListener("X", ...)` 的集合非空。
- **修复**: 在 `useEffect` 的 cleanup 里 `removeEventListener`。

---

## 规则 ID 命名约定

- `SEC-REACT-NNN`: React 专属安全规则
- `SEC-JS-NNN`: 通用 JS 安全规则
- `SEC-SECRET-NNN`: 密钥检测
- `RELI-JS-NNN`: 可靠性规则
- `ESLINT-SUMMARY` / `TSC-ERROR` / `NPM-AUDIT-*`: 来自外部工具（非自研，但统一在 findings 里）
