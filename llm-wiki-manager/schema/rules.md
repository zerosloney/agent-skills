# Wiki 编写规范

## 基本原则

1. **LLM 是编译器，不是笔杆子** — 所有内容来自原始素材，LLM 负责编译、结构化、交叉链接
2. **双向链接** — 页面被链接时，主动添加回链
3. **无来源不录入** — 每篇文章必须包含 sources 字段
4. **不重复造轮子** — 优先引用已有页面，不重复定义

## 命名规范

### 文件名
- 英文小写 + 连字符 `-`
- 示例：`python-asyncio.md`、`gpt4-release.md`

### 标题
- 使用文章标题（支持中文）
- 示例：`# Python Asyncio 异步编程`

### 标签
- 英文关键词或中文关键词
- 示例：`python 异步 编程`

### 交叉链接
- 格式：`[[页面名]]`（不含路径）
- 示例：`[[event-loop]]`（无论子目录位置）

## frontmatter 规范

### 必需字段
```yaml
---
entity_type: concept  # 12种实体类型（6基础+6扩展）
confidence: high      # high | medium | low
sources:              # 来源数组，至少一条
  - raw/source.md
  - web:https://url
---
```

### 可选字段
```yaml
aliases: [别名1, 别名2]  # 同义词/别名，用于跨部门统一术语
domains: [领域1, 领域2]  # 知识领域标签
tags: [标签1, 标签2]     # 搜索标签
created: YYYY-MM-DD      # 页面创建日期
updated: YYYY-MM-DD      # 最后更新日期
```

### 可选字段
```yaml
domains: [领域1, 领域2]
tags: [标签1, 标签2]
created: YYYY-MM-DD
updated: YYYY-MM-DD
```

## 章节结构

根据 entity_type 选择对应章节，见 `entity-types.md`。

所有类型必需章节：
- 相关页面（Cross-links）
- 来源与延伸阅读

## 链接规范

### 内部链接
- 格式：`[[页面名]]`
- 示例：`[[event-loop]]`
- 说明：按文件名全局解析，与子目录位置无关

### 外部链接
- 格式：`[标题](URL) — 说明`
- 示例：`[Python 官方文档](https://docs.python.org) — 官方教程`

### 区块引用
- 格式：`> 引用内容`
- 使用场景：引用原文、标注解释

## 矛盾标注规范

发现矛盾时，在相关页面追加：
```markdown
## ⚠️ 矛盾标注

- 在 [[页面A]] 中描述为：{观点A}
- 在 [[页面B]] 中描述为：{观点B}
- 需要确认：{待验证事实}
```

## 时间标记规范

内容的时效性需要标注：
```markdown
**状态**：截至 2026-05-15
**更新**：2026-05-15
```

## 多来源综合规范

综合 3+ 来源时，触发 Counter-Arguments 机制：
```markdown
## ⚖️ Counter-Arguments

- **对立观点**：{来自来源B的不同观点}
- **适用边界**：{方案A的局限性}
- **替代方案**：{其他可行路径}
```

## 问答回写规范

用户问答产生新信息时回写：
```markdown
## 常见问题

- Q: {问题}
  A: {回答}
  来源：用户问答 YYYY-MM-DD
```

## 禁止事项

- ❌ 不要删除 pages/ 中的文件（用 `_archived/` 归档）
- ❌ 不要修改 raw/ 中的原始素材（用 `delete.py` 删除）
- ❌ 不要在 `[[链接]]` 中使用路径分隔符
- ❌ 不要创建超过 30 层的嵌套结构
- ❌ 不要在 frontmatter 中留空 critical 字段

## 更新流程

更新已有页面时：
1. 输出 Structured Diff（见 SKILL.md）
2. 用户确认
3. 执行更新
4. 运行 `compile_post.py` 后处理
