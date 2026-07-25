# api-contract-tester — 设计文档

> **状态**：设计阶段（仅 DESIGN.md，未实现）。待 frontend-audit 标杆验证模板后推进。
> **对标**：dotnet-code-review / frontend-audit 的"Python CLI + 编排层 + json-compact 输出"形态。

## 1. 定位

检测**代码实现 vs API 契约文件**的漂移，重点是**破坏性变更**。回答：
- "我改了路由/参数/响应，OpenAPI spec 同步了吗？"
- "这份新 spec 相比旧 spec，哪些是破坏性变更？"
- "代码里实际有哪些端点，spec 漏了哪些？"

**典型触发**："API 契约检查" / "spec 漂移" / "破坏性变更" / "openapi 对不上" / "PR 改了接口"。

## 2. 与现有 skill 的复用关系

| 复用来源 | 复用什么 |
|---------|---------|
| dotnet-code-review | Finding dataclass 形态、exit code 体系、ReviewError、json-compact 输出、Triage→Verify |
| frontend-audit | engine.py 编排模式（多 tier + degradation_notices）、输出格式器骨架、pytest.ini 模板 |
| database-explorer | 安全确认协议（破坏性变更报告需用户确认才能写回 spec） |

**不复用**：不重新发明 OpenAPI 解析——用 `pyyaml` + 自写遍历（避免引入 openapi-core 重依赖）。

## 3. SKILL.md 大纲

```yaml
---
name: api-contract-tester
description: |
  API 契约漂移检测 CLI：对比代码实现 vs OpenAPI/proto/GraphQL schema，识别破坏性变更。
  4 类漂移：端点缺失/参数变更/响应 schema 漂移/必填字段变化。
  破坏性判定：breaking（必影响客户端）/ additive（向后兼容）/ informational。
  Agent 通过 subprocess 调用 scripts/contract.py，用户不接触 CLI。
  触发：用户说"API 契约检查" / "spec 漂移" / "破坏性变更" 时。
agent_created: true
version: 0.1.0
---
```

章节（对标 frontend-audit）：核心原则 → §0 前置条件 → §1 命令速查 → §2 Agent 决策规则（意图映射 + 漂移分类 + 破坏性判定） → §3 输出处理 → §4 报告模板 → §5 边界处理（框架未支持时降级） → §6 故障排查 → §7 references 索引 → §8 测试状态。

## 4. CLI 接口

```
contract.py diff --code <dir> --spec <openapi.yaml>
                 [--framework express|fastapi|aspnet|spring]  # 自动检测可不传
                 [--format json-compact|json|markdown]
contract.py breaking --spec-old v1.yaml --spec-new v2.yaml
                 [--format json-compact|json|markdown]
contract.py extract --code <dir> --framework <name>   # 从代码反向生成 spec 片段
contract.py validate --spec <openapi.yaml>             # spec 自身合法性
```

**Exit Code**：0=无破坏性变更 / 1=有破坏性变更 / 2=环境错误 / 3=配置错误 / 4=框架不支持。

## 5. 文件结构（规划）

```
api-contract-tester/
├── SKILL.md
├── pytest.ini
├── requirements.txt          # pyyaml, tree-sitter(可选,精确 AST)
├── references/
│   ├── diff-semantics.md     # 漂移分类与破坏性判定规则（唯一权威源）
│   ├── framework-support.md  # 各框架路由解析能力矩阵
│   └── troubleshooting.md
├── scripts/
│   ├── contract.py           # CLI 入口
│   ├── count_drift.py        # 维护脚本：统计规则数
│   └── contract/
│       ├── __init__.py
│       ├── engine.py         # 编排：解析代码端点 + 解析 spec + diff
│       ├── models.py         # Endpoint / Drift / Finding dataclass
│       ├── errors.py         # ContractError + exit codes
│       ├── parsers/          # 代码路由解析（每框架一个适配器）
│       │   ├── __init__.py
│       │   ├── express.py    # app.get/post/... 路由提取
│       │   ├── fastapi.py    # @app.get 装饰器 + 类型标注
│       │   ├── aspnet.py     # [HttpGet] 特性 + 路由模板
│       │   └── spring.py     # @GetMapping 等
│       ├── spec/
│       │   ├── __init__.py
│       │   ├── openapi.py    # OpenAPI 3.x 解析（paths/components/schemas）
│       │   ├── proto.py      # .proto service 解析（预留）
│       │   └── graphql.py    # .graphql schema 解析（预留）
│       ├── diff.py           # 漂移计算 + 破坏性判定
│       ├── output.py         # json-compact / json / markdown
│       └── rules.py          # 漂移规则元数据（BREAKING-001 等）
└── tests/
    ├── conftest.py
    ├── test_parsers_express.py
    ├── test_parsers_fastapi.py
    ├── test_spec_openapi.py
    ├── test_diff.py          # 漂移分类与破坏性判定
    ├── test_output.py
    └── test_e2e.py           # fixtures/express-demo + fixtures/fastapi-demo
```

## 6. 核心逻辑

### 6.1 端点提取（代码侧）

每个框架适配器实现 `extract_endpoints(code_dir) -> list[Endpoint]`：

```python
@dataclass
class Endpoint:
    method: str          # GET/POST/...
    path: str            # /api/users/{id}（规范化）
    params: list[Param]  # path/query/body 参数
    response_schema: dict | None
    source_file: str
    line: int
```

- **Express**：正则 + AST 提取 `app.<method>(<path>, ...)`，参数从 `req.params`/`req.query`/`req.body` 反推（启发式，标 `intentional-simple`）。
- **FastAPI**：装饰器 + 函数签名类型标注（最精确，因为 FastAPI 强制类型）。
- **ASPNET**：`[HttpGet("route")]` 特性 + 方法签名（需要 Roslyn，可复用 dotnet-code-review 的分析器工程结构）。
- **Spring**：`@GetMapping` 等 + 方法签名。

### 6.2 端点提取（spec 侧）

OpenAPI 解析：遍历 `paths` → 每个路径 × 方法 → 提取 `parameters` / `requestBody` / `responses`。把 `$ref` 解开（components/schemas）。

### 6.3 漂移计算

以 `(method, normalized_path)` 为 join key，三向比较：

| 情况 | 判定 |
|------|------|
| 代码有、spec 没有 | `breaking`（客户端依赖 spec，新端点不影响，但**代码删了端点 spec 还有** = `breaking`） |
| spec 有、代码没有 | `breaking`（端点被删了，客户端会 404） |
| 参数：代码新增必填、spec 没有 | `breaking` |
| 参数：类型变化（如 int→str） | `breaking` |
| 参数：代码新增可选 | `additive` |
| 响应字段：必填新增 | `breaking` |
| 响应字段：移除 | `breaking` |
| 响应字段：新增可选 | `additive` |

详见 references/diff-semantics.md（实现时的唯一权威源）。

### 6.4 两版 spec 对比（`breaking` 子命令）

不读代码，只比 `--spec-old` vs `--spec-new`：路径/方法/参数/响应 schema 的差异 + 同上判定规则。

## 7. MVP 范围

**MVP 必须有**：
- OpenAPI 3.x 解析（paths + components/schemas + $ref 解开）
- Express + FastAPI 两个代码适配器
- `diff` 子命令（代码 vs spec）
- `breaking` 子命令（两版 spec 对比）
- 漂移分类 + 破坏性判定
- json-compact 输出

**MVP 不做**（标 `intentional-simple` 或后续版本）：
- proto / GraphQL 解析（预留接口，不实现）
- ASPNET / Spring 适配器（需要 Roslyn/JVM，工程量大）
- 自动修复 spec（只报告，不写回）
- OAuth/scope 变更检测

## 8. 验证计划

1. OpenAPI 解析器 + 单测 → 验证：解析真实 openapi.yaml，字段齐全
2. Express/FastAPI 适配器 + 单测 → 验证：fixtures 项目端点全部提取
3. diff 算法 + 单测 → 验证：每类漂移的正/负例
4. 破坏性判定 + 单测 → 验证：breaking/additive/informational 分类正确
5. 端到端 → 验证：fixtures/express-demo 与故意改坏的 spec 跑出预期 drift
6. SKILL.md + references → 验证：模板合规

## 9. 风险与取舍

- **路由参数推断是启发式**：Express 的 `req.body.x` 无法静态知道 x 的类型，标 `intentional-simple`，破坏性判定降级为 `agent_verify`。
- **$ref 解开深度**：递归引用需防环，用 visited 集合。
- **路径规范化**：`/users/:id`（Express）vs `/users/{id}`（OpenAPI）需统一，建一个 normalizer。
