# 页面更新规范（Structured Diff）

## 核心原则

**不直接修改，必须先 Diff，用户确认，再执行。**

已有页面的每一次更新都是对原始素材的重新解读，需要：
- 明确改了什么（Current vs Proposed）
- 理由充分（Reason）
- 来源可查（Source）

---

## 更新类型分类

### Type 1：补充章节

已有页面缺少某个必需章节，需要补充。

```markdown
## 📝 页面更新：{页面标题}

### Current（当前内容）
> 现有页面仅有 4 个章节：
> - 概述
> - 详细信息
> - 相关页面
> - 来源

### Proposed（建议修改）
> 新增 ## 补充内容 章节：
> ## 补充
> {新内容段落}

### Reason（修改理由）
> - 实体类型为 {type}，## {章节名} 是必需章节
> - 新素材 {raw/file.md} 提供了相关补充内容

### Source（来源依据）
> - raw/{filename}.md：{具体引用}
```

### Type 2：修正内容

已有内容与新来源矛盾或不准确。

```markdown
## 📝 页面更新：{页面标题}

### Current（当前内容）
> 现有描述：PostgreSQL 默认隔离级别是可序列化（RLS）

### Proposed（建议修改）
> 修改为：PostgreSQL 默认隔离级别是 Read Committed（大多数场景）
> 注：可序列化隔离级别需要显式设置 `ALTER TABLE ... SET TRANSACTION ISOLATION LEVEL SERIALIZABLE`

### Reason（修改理由）
> - 来源 {raw/article.md} 和 {web:url} 均指出原描述有误
> - PostgreSQL 官方文档明确：默认即 Read Committed

### Source（来源依据）
> - raw/{filename}.md
> - https://www.postgresql.org/docs/current/transaction-iso.html
```

### Type 3：扩展内容

已有页面覆盖不足，需要扩展深度或广度。

```markdown
## 📝 页面更新：{页面标题}

### Current（当前内容）
> 现有内容约 500 字，仅覆盖 Rust ownership 基础概念。

### Proposed（建议修改）
> 扩展以下子话题：
> - ## RAII 与 ownership 的关系
> - ## 生命周期标注（'a 语法）
> - ## 常见编译错误解析
>
> 总字数预计扩展至 1500 字。

### Reason（修改理由）
> - 新素材 {raw/rust-advanced.md} 包含深度内容
> - 多个页面引用了 [[rust-ownership]] 但内容不够深入

### Source（来源依据）
> - raw/rust-advanced.md：第 3-5 节
```

### Type 4：合并页面

两个高度重叠的页面应合并。

```markdown
## 📝 页面更新：合并 {pageA} ← {pageB}

### Current（当前内容）
> 现有两个页面内容高度重叠：
> - [[pageA]]：约 300 字，侧重理论
> - [[pageB]]：约 300 字，侧重实践
> 两者核心内容重复率 >60%

### Proposed（建议修改）
> 保留 [[pageA]]，将 [[pageB]] 内容合并为 ## 实践案例 章节
> [[pageB]] 页面移动到 _archived/（永不删除，用户可查阅）

### Reason（修改理由）
> - 合并后减少重复，提升检索效率
> - 理论和实践在同一页面，关联性更强

### Source（来源依据）
> - [[pageA]] 现有内容
> - [[pageB]] 现有内容
```

### Type 5：添加交叉链接

页面之间需要建立双向链接。

```markdown
## 📝 页面更新：{页面标题} — 补充交叉链接

### Current（当前内容）
> 现有相关页面：
> - [[pageA]]（有链接）
> - [[pageB]]（有链接）
> 缺少链接：[[missing-page]]（存在但未被引用）

### Proposed（建议修改）
> 在 ## 相关页面 中新增：
> - [[missing-page]] — {一句话说明关联点}

> 同时在 [[missing-page]] 的 ## 相关页面 中添加：
> - [[{页面标题}]] — {一句话说明关联点}

### Reason（修改理由）
> - lint 发现 {页面标题} 和 missing-page 之间存在潜在关联（共享标签：{tag}）
> - 建立双向链接后，图分析中 {missing-page} 不再是孤悬页面

### Source（来源依据）
> - {页面标题}.md 中的 {引用内容}
> - missing-page.md 中的 {引用内容}
```

---

## 更新执行清单

收到用户 `y` 确认后，按顺序执行：

- [ ] 1. 读取现有页面完整内容
- [ ] 2. 执行修改（补充/修正/扩展/合并）
- [ ] 3. 若合并：将被合并页面移动到 `_archived/`
- [ ] 4. 若新增交叉链接：同步更新被引用页面的 `## 相关页面`
- [ ] 5. 更新 `index.md`（如有新增分区/分类变更）
- [ ] 6. 运行 `python scripts/cache.py update {raw_file}`（如有新来源）
- [ ] 7. 运行 `python scripts/search.py --rebuild`（如内容变化较大）
- [ ] 8. 输出更新摘要

---

## 更新摘要模板

```
✅ 页面已更新：{页面标题}

📝 更新类型：{Type N}
🔗 交叉链接：+N 个
📊 字数变化：+N / -N
📦 缓存状态：已更新 / 无需更新
🔍 索引状态：已重建 / 无需重建
```
