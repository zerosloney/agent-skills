# frontend-audit 测试

> **职责契约**：测试运行方式、覆盖表、设计原则。

## 运行方式

```bash
# 在 frontend-audit/ 目录下
python -m pytest tests/                    # 全部
python -m pytest tests/test_rules_security.py -v   # 单文件
python -m pytest tests/test_e2e.py::TestFixtureScan::test_detects_all_seed_findings  # 单测试
python -m pytest tests/ -q                 # 安静模式
```

不需要任何外部依赖（Node/eslint/npm/tree-sitter 都不依赖）：
- linter 编排测试用 monkeypatch mock `subprocess.run`。
- 端到端测试用 `--no-lint` 跑，只验证自研规则层。
- 依赖测试用 fixture package.json（无 lockfile，npm audit 返回 0 漏洞）。

## 测试文件覆盖表

| 文件 | 覆盖模块 | 关键场景 |
|------|----------|----------|
| `test_rules_security.py` | `visitors.py` + `ruledefs/*` | 每条规则的正/负例 + 元数据传播 + 净化抑制 + H5 启发式 |
| `test_scoring.py` | `scoring.py` | 维度扣分、等级、dedup、eslint 折叠 |
| `test_triage.py` | `triage.py` | triage 回填、未知规则默认、summary 计数 |
| `test_output.py` | `output.py` | 4 种格式（json-compact/json/sarif/markdown） |
| `test_linters.py` | `linters.py` | eslint/tsc 编排（mock subprocess）、降级 |
| `test_engine.py` | `engine.py` | 进程内 run_scan：tier 顺序、维度过滤、dedup、B1 空路径、降级 notice（补 coverage，e2e 走 subprocess 不计） |
| `test_deps.py` | `deps.py` | npm audit JSON 解析（via dict/str/空）、npm 缺失降级、_resolve_npm |
| `test_errors.py` | `errors.py` | exit code 常量、AuditError 层级与 to_dict |
| `test_discover.py` | `visitors.py` | 文件发现：扩展名过滤、lockfile 跳过、H6 符号链接不跟随 |
| `test_e2e.py` | `audit.py` CLI | 真实 subprocess 调用 + fixture 项目 + B1 空路径 + threshold 语义 |

## 设计原则

1. **零外部依赖**：测试不依赖 Node/eslint/npm，CI 上裸 Python 即可跑。
2. **隔离**：每个测试自包含，不共享状态。
3. **真实调用路径**：`test_e2e.py` 走完整 subprocess，捕获 CLI 行为而非内部函数。
4. **正负例对称**：每条规则既测触发，也测安全变体不误报。

## 当规则改动时，哪些测试会红

| 改动 | 失败的测试 |
|------|-----------|
| 新增/删除规则 ID | `test_rules_security.py::TestRuleMetadataPropagation` + `test_e2e.py::TestRulesSubcommand::test_lists_all_rules_json`（断言 ≥13 条） |
| 改正则（如 SEC-REACT-001 的 __html 匹配） | `test_rules_security.py::TestDangerouslySetInnerHTML` + `test_e2e.py::test_detects_all_seed_findings` |
| 改评分权重 | `test_scoring.py::TestCalculateScore::test_security_errors_drop_security_dimension_only`（硬编码了 90） |
| 改 threshold 等级映射 | `test_scoring.py::test_grade_bands` |
| 改 json-compact 字段 | `test_output.py::TestJsonCompact` |
| 改 fixture 漏洞代码 | `test_e2e.py::TestFixtureScan::test_detects_all_seed_findings`（预期 ID 列表） |
