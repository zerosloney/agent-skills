# test-scaffolder — 设计文档

> **状态**：设计阶段（仅 DESIGN.md，未实现）。
> **对标**：frontend-audit 的"Python CLI + 纯计算 + json-compact 输出"形态（更轻，无外部编排）。

## 1. 定位

输入函数/端点签名 → 生成参数等价类 + 边界值矩阵 + 测试骨架（pytest + jest）。回答：
- "这个函数该测哪些输入？"
- "帮我生成这个端点的测试骨架"
- "这个签名有哪些边界值没覆盖？"

**典型触发**："生成测试" / "测试用例" / "边界值" / "等价类" / "pytest 骨架" / "jest 骨架"。

**与 implement skill 的关系**：implement 提倡 TDD 但不教"怎么写好测试"。test-scaffolder 填这个 gap——在 implement 调用前先用 test-scaffolder 生成骨架。

## 2. 与现有 skill 的复用关系

| 复用来源 | 复用什么 |
|---------|---------|
| frontend-audit | engine 编排模式、output.py 骨架、pytest.ini、models.py dataclass 风格 |
| dotnet-code-review | Finding 形态（这里叫 `TestCase`）、exit code 体系 |
| loop-coding | templates/ 模板文件组织（生成的骨架本质是模板填充） |

**不复用**：不重新发明 AST 解析——Python 用内置 `ast`，JS/TS 用 tree-sitter（与 frontend-audit 共享依赖）。

## 3. SKILL.md 大纲

```yaml
---
name: test-scaffolder
description: |
  测试骨架生成 CLI：从函数/端点签名生成参数等价类 + 边界值矩阵 + pytest/jest 测试骨架。
  支持类型：Python（typing）/ TypeScript（interface/类型标注）。
  生成内容：参数等价类表、笛卡尔积边界矩阵、parametrize 表、mock 模板。
  Agent 通过 subprocess 调用 scripts/scaffold.py，用户不接触 CLI。
  触发：用户说"生成测试" / "测试用例" / "边界值" / "等价类" 时。
agent_created: true
version: 0.1.0
---
```

章节：核心原则 → §0 前置条件 → §1 命令速查 → §2 Agent 决策规则（意图映射 + 等价类生成规则 + 骨架选择） → §3 输出处理 → §4 生成模板 → §5 边界处理（无类型标注时降级） → §6 故障排查 → §7 references → §8 测试状态。

## 4. CLI 接口

```
scaffold.py gen --target <func:file:line | route:GET:/api/users>
                --lang python|js
                [--framework pytest|jest]
                [--format json-compact|markdown]
                [--max-cases 50]            # 笛卡尔积裁剪上限
scaffold.py matrix --signature "def f(x: int, y: str) -> bool"
                   [--lang python]
scaffold.py list-functions --file <path>    # 列出可生成测试的函数
```

**Exit Code**：0=成功生成 / 1=签名无法解析 / 2=环境错误 / 3=配置错误。

## 5. 文件结构（规划）

```
test-scaffolder/
├── SKILL.md
├── pytest.ini
├── requirements.txt          # tree-sitter（JS/TS 解析，可选）
├── references/
│   ├── equivalence-rules.md  # 各类型的等价类与边界值规则（唯一权威源）
│   ├── renderer-specs.md     # pytest/jest 骨架渲染规范
│   └── troubleshooting.md
├── scripts/
│   ├── scaffold.py           # CLI 入口
│   └── scaffold/
│       ├── __init__.py
│       ├── engine.py         # 编排：签名 → 等价类 → 矩阵 → 渲染
│       ├── models.py         # Signature / Param / EquivalenceClass / TestCase
│       ├── errors.py
│       ├── signature/        # AST 签名提取
│       │   ├── __init__.py
│       │   ├── python.py     # 内置 ast 模块
│       │   └── typescript.py # tree-sitter
│       ├── equivalence.py    # 等价类 + 边界值生成（纯函数，核心）
│       ├── matrix.py         # 笛卡尔积 + 裁剪策略
│       ├── renderers/        # 骨架渲染
│       │   ├── __init__.py
│       │   ├── pytest.py     # @pytest.mark.parametrize 表
│       │   ├── jest.py       # test.each 表
│       │   └── plain.py      # 纯 markdown 矩阵（不生成代码）
│       └── output.py
└── tests/
    ├── conftest.py
    ├── test_signature_python.py
    ├── test_signature_typescript.py
    ├── test_equivalence.py   # 核心测试：每种类型的等价类
    ├── test_matrix.py        # 笛卡尔积裁剪
    ├── test_renderers.py
    └── test_e2e.py
```

## 6. 核心逻辑

### 6.1 签名提取

```python
@dataclass
class Param:
    name: str
    type: str           # "int" / "str" / "Optional[int]" / "List[str]" / "MyType"
    default: Any | None # 有默认值 = 可选
    optional: bool      # Optional[X] 或 有默认值

@dataclass
class Signature:
    name: str
    params: list[Param]
    return_type: str | None
    source_file: str
    line: int
```

Python 用 `ast.parse` + `ast.walk` 找 `FunctionDef`，读 `args` + `annotation`。TS 用 tree-sitter 找 `function_declaration` / `arrow_function`，读类型标注。

### 6.2 等价类生成（核心，纯函数）

每个类型 → 一组等价类（每类取一个代表值）。规则表（详见 references/equivalence-rules.md）：

| 类型 | 等价类（代表值） |
|------|-----------------|
| `int` | {MIN_INT, -1, 0, 1, MAX_INT} |
| `float` | {负零, -1.0, 0.0, 1.0, NaN, INF} |
| `str` | {""(空), " "(空白), "a"(普通), "很长的字符串", "<script>"(特殊), None(若 Optional)} |
| `bool` | {True, False} |
| `List[X]` | {[](空), [X代表], [X,X](多元素)} |
| `Optional[X]` | {None} ∪ X 的等价类 |
| 自定义类型 | {一个 mock 实例} + 标 `agent_verify`（需 Agent 补充） |

### 6.3 边界值矩阵（笛卡尔积 + 裁剪）

朴素笛卡尔积会爆炸（5 参数 × 5 类 = 3125 case）。裁剪策略：

1. **同类合并**：每参数只取最有代表性的 N 个（默认 3：正常值 + 边界值 + 异常值）。
2. ** pairwise**（可选，`--strategy pairwise`）：用 all-pairs 算法覆盖每对参数的组合，大幅减少 case 数。
3. **`--max-cases` 硬上限**：超过则截断 + 提示。

### 6.4 骨架渲染

**pytest**：
```python
@pytest.mark.parametrize("x,y,expected", [
    (0, "", None),       # boundary
    (1, "a", True),      # normal
    (-1, None, False),   # negative / None
])
def test_f(x, y, expected):
    # TODO: assert f(x, y) == expected
    pass
```

**jest**：
```javascript
test.each([
    [0, "", null],
    [1, "a", true],
    [-1, null, false],
])("f(%p, %p) -> %p", (x, y, expected) => {
    // TODO: expect(f(x, y)).toBe(expected);
});
```

**关键纪律**：生成的骨架里 `assert`/`expect` 是 TODO 占位，**不预填 expected 值的断言**（因为不知道函数实际行为），Agent 需根据函数语义补全。

## 7. MVP 范围

**MVP 必须有**：
- Python 签名提取（ast）+ TS 签名提取（tree-sitter）
- 6 种基础类型（int/float/str/bool/List/Optional）的等价类
- pytest + jest 两个渲染器
- `gen` + `matrix` 子命令
- 笛卡尔积 + 同类合并裁剪

**MVP 不做**：
- pairwise 策略（后续版本）
- 自定义类型的智能 mock（标 agent_verify，让 Agent 补）
- 运行测试（只生成骨架，不跑）
- xUnit/NUnit（.NET，后续）

## 8. 验证计划

1. Python 签名提取 + 单测 → 验证：提取 typing 标注、默认值、Optional
2. 等价类生成 + 单测 → 验证：每种类型的代表值集合正确
3. 笛卡尔积 + 裁剪 + 单测 → 验证：case 数受控，边界值覆盖
4. pytest/jest 渲染 + 单测 → 验证：生成的代码语法正确（用 `ast.parse` 反向验证 pytest，用 tree-sitter 验证 jest）
5. 端到端 → 验证：对一个 fixture 函数生成骨架，且骨架能被对应测试框架 collect（不报语法错）

## 9. 风险与取舍

- **无类型标注降级**：Python 无 typing / JS 纯 JS（非 TS）时，参数全当 `Any`，等价类退化为 {None, 一个 generic 值}，标 `intentional-simple` + 提示用户加类型标注。
- **自定义类型**：无法静态知道字段，只能 mock，标 `agent_verify`。
- **笛卡尔积爆炸**：硬上限 + 同类合并兜底；不保证全覆盖（覆盖率优先级低于可用性）。
