# scoring-and-thresholds

> **职责契约**：本文档是 frontend-audit 评分模型与阈值的**唯一权威源**。
> 只包含：维度权重、扣分公式、等级映射、threshold 门禁语义。
> 不包含：规则细节（→ rules-catalog.md）、输出字段（→ reporting-and-fix.md）。
>
> Agent 使用路径：用户问"为什么 security 维度分这么低" / "调 threshold" 时读。
> 数据来源：`scripts/audit/scoring.py`。

## 维度权重

| 维度 | 权重 | 数据来源 |
|------|------|----------|
| security | **35%** | 自研 SEC-* 规则（含 secrets） |
| reliability | 20% | 自研 RELI-* 规则 |
| best-practice | 20% | eslint 折叠 + tsc 类型错误 |
| deps | 15% | npm audit CVE |
| arch | 10% | （预留，本版本无规则，恒 100） |

权重和 = 1.00。arch 维度本版本无规则，所以恒为 100，相当于把权重让给其他维度（实际只影响"arch 有没有问题"的可信度标注）。

## 扣分公式

每个维度独立计分：

```
维度分 = max(0, 100 - 该维度所有 finding 的扣分之和)
单条扣分 = {error: 10, warning: 5, info: 1}[severity]
```

总分 = Σ(维度分 × 权重)，四舍五入到 1 位小数。

**特殊处理**：source = `eslint` / `tsc` 的 finding 一律计入 `best-practice` 维度，即使 rule 名暗示其他维度。理由：自研 security 规则是 security 维度的唯一权威来源，避免 eslint 的 no-unused-vars 之类稀释 security 分。

## 等级映射

| 等级 | 总分区间 | 含义 |
|------|----------|------|
| A | ≥ 90 | 优秀，可直接合并 |
| B | 80–89 | 良好，建议修完 warning 再合 |
| C | 70–79 | 一般，有必修的 error |
| D | 60–69 | 较差，error 较多 |
| F | < 60 | 不合格 |

## Threshold 门禁

`--threshold <grade>` 让 CLI 在等级**低于**该值时 exit 1（用于 CI / PR 检查）：

```bash
# PR 必须达 B 级
audit.py scan --path . --threshold B
# exit 0 = 通过，exit 1 = 不达标
```

等级比较：A > B > C > D > F。`--threshold B` 允许 A 和 B，拒绝 C/D/F。

## 解读示例

`scan` 返回 `score: 83.0, grade: B, dimensions: {security: 55, reliability: 94, ...}`:
- security=55 意味着该维度累计扣了 45 分（如 4 个 error + 1 warning = 4×10 + 5 = 45）。
- 总分 83.0 = 0.35×55 + 0.20×94 + 0.20×100 + 0.10×100 + 0.15×100 = 19.25 + 18.8 + 20 + 10 + 15 = 83.05 → 83.0。
- **结论**：security 是主要扣分项，应优先修 security 维度的 error。
