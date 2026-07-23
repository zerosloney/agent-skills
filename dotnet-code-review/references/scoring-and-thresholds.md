# Scoring & Thresholds（评分与阈值）

> 加载时机：解读 score/grade、解读某类扣分、解读技术债务分钟数、解读圈/认知复杂度是否超标。
> 数据来源：`scripts/review/scoring.py` + `scripts/review/complexity.py` + `scripts/review/engine.py`。

## 一、总分计算（`calculate_score`）

总分 = Σ(各类别分数 × 类别权重)，四舍五入到 1 位小数。

### 1.1 类别权重（`CATEGORY_WEIGHTS`，总和 = 1.00）

| 类别 | 权重 |
|------|------|
| security | **0.20** |
| best-practice | **0.20** |
| semantic | 0.10 |
| complexity | 0.10 |
| code-smell | 0.10 |
| style | 0.05 |
| test | 0.05 |
| performance | 0.05 |
| naming | 0.05 |
| reliability | 0.05 |
| security-hotspot | 0.05 |

> **security 与 best-practice 各占 20%**，是权重最高的两类——同类 issue 多发会快速拉低总分。

### 1.2 类别分数

```
category_score = max(0, 100 − Σ SEVERITY_PENALTY[该类下所有 issue])
```

### 1.3 严重度扣分（`SEVERITY_PENALTIES`）

| severity | 每条扣分 |
|----------|---------|
| error | **10** |
| warning | **5** |
| info | **1** |

> 单类扣到 0 即止（`max(0, …)`），不会负分累加到其他类。

## 二、等级（grade）

| 分数区间 | 等级 |
|---------|------|
| ≥ 90 | A |
| ≥ 80 | B |
| ≥ 70 | C |
| ≥ 60 | D |
| < 60 | F |

## 三、质量门禁交互

- `--quality-gate-score N`：总分 < N 时 exit code = 1。
- `--fail-on {error|warning|info|none}`：存在该级别及以上 issue 时 exit 非零（默认 error）。
- 二者**独立判定**：可能总分达标但仍有 error → exit 1（因 fail-on）。

## 四、技术债务（`estimate_technical_debt`，分钟）

按 (severity, category) 查 `FIX_TIME_MINUTES` 表累加：

| category | error | warning | info |
|----------|-------|---------|------|
| security | 30 | 15 | 5 |
| reliability | 25 | 12 | 5 |
| complexity | 45 | 20 | 10 |
| best-practice | 20 | 10 | 3 |
| semantic | 20 | 10 | 3 |
| performance | 20 | 10 | 3 |
| security-hotspot | 15 | 10 | 5 |
| code-smell | 15 | 8 | 3 |
| style | 10 | 5 | 2 |
| test | 10 | 5 | 2 |
| naming | 5 | 3 | 2 |

> 未命中表的 (severity, category) 默认按 **5 分钟**计。

## 五、复杂度阈值（Layer 2，`analyze_complexity`）

| 规则 | error 阈值 | warning 阈值 | 维度 |
|------|-----------|-------------|------|
| CC001 | 圈复杂度 > **20** | > **10** | 圈复杂度 |
| CC002 | 方法 > **100** 行 | > **50** 行 | 方法长度 |
| CC003 | 参数 > **8** | > **5** | 参数个数 |
| CC004 | 最大嵌套 > **6** | > **4** | 嵌套深度 |

## 六、认知复杂度（`complexity.py`，SonarSource 算法）

**仅作文件级汇总分数，不单独产 issue**（无 CC 规则绑定）。算法：
- +1 每个命名方法/构造函数（基础）
- +1 结构化分流：`if` / `else`（独立）/ `for` / `foreach` / `while` / `catch` / `do` / `switch` / `case` / `default:` / `try` / `finally` / `throw`
- 嵌套层级随 `{` 累加

### 已知精度边界（regex 实现）

- 无法准确处理嵌套泛型、lambda 嵌套、模式匹配
- LINQ 链可能被误计为嵌套
- switch 表达式按分支计
- 精度：简单方法 ±5%，复杂方法 ±20%（vs SonarSource 参考实现）
- **精确结果请用 Roslyn 层**（Layer 3，需 .NET SDK）

## 七、可维护性指数（`calculate_maintainability_index`，Microsoft 变体）

```
MI = max(0, min(100, (171 − 5.2·ln(V) − 0.23·CC − 16.2·ln(LOC)) × 100 / 171))
```
- V = Halstead Volume（未实测时用 LOC 近似）
- CC = 平均圈复杂度
- LOC = 代码行数

## 八、覆盖率阈值

- `--coverage <cobertura.xml>`：读 Cobertura 报告
- `--coverage-threshold R`：最低行覆盖率，默认 **0.6**（60%）；低于阈值产 issue

## 九、去重

- **位置去重**：`file:line:rule` 相同保留更严重者（`dedup_issues`）
- **层间抑制**：regex 与 AST 同 file:line 命中同概念时，AST（`source in {ast, semantic}`）权威，regex 抑制（`suppress_builtin_overlap`，映射见 `LAYER_SUPPRESSION_MAP`）
