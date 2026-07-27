# 检索策略详细指南

> 本文件为检索策略参考。核心工作流、决策树见 [`SKILL.md`](../SKILL.md)。

---

## 规模分级策略

知识库规模不同，LLM 的检索策略必须不同。**提前判断规模，选择对应策略。**

### Scala 1：小型（< 200 页 / < 40 万字）

**特征**：一个 `pages/` 目录，所有 .md 平铺；总 token 可在 LLM 上下文内过一遍。

**策略 — 纯原生工具检索**：

```
用户提问
    ↓
glob("pages/*关键词*")        # 文件名匹配
grep -rn "关键词" pages/      # 内容行匹配（Linux）
findstr /s "关键词" pages\*   # 内容行匹配（Windows）
    ↓
read_file 匹配结果页          # 最多 5~10 页
    ↓
LLM 在上下文中组织答案
```

**LLM 行为**：
- 每次搜索先把 `index.md` 读一遍，了解分区结构
- 先从文件名猜方向，再 grep 补充
- 读完相关页后**直接回答**，不需要索引

### Scala 2：中型（200~1000 页 / 40~200 万字）

**特征**：单目录平铺性能下降，需建立 **子目录索引结构**。

**策略 — 层级导航 + 倒排索引**：

```
用户提问
    ↓
read_file pages/index.md                      # 总导航
    ↓
read_file pages/开发/编程语言/index.md         # 下钻子目录
    ↓
python scripts/search.py --query "Rust 异步"  # 索引检索（非 grep）
    ↓
read_file 匹配结果页（2~3 页）
    ↓
LLM 在上下文中组织答案
```

**LLM 行为 — 子目录索引维护规范**：

1. 当 `pages/` 下 .md 文件超过 50 个时，**自动建议**用户划分子目录
2. 划分依据：index.md 中的分区（每个分区一个子目录）
3. 子目录内必须有一个 `index.md`，列出该子目录的所有页面及其一句话摘要
4. 子目录 index.md 中的链接统一用 `[[页面名]]` 格式（不含路径），跨子目录引用时也只用文件名
5. 子目录 index.md 格式：
   ```markdown
   # 后端开发

   | 页面 | 摘要 | 标签 |
   |------|------|------|
   | [fastapi-intro](fastapi-intro.md) | FastAPI 基础概念和入门 | `python web` |
   | [postgresql-indexing](postgresql-indexing.md) | PostgreSQL 索引优化 | `sql 性能` |
   ```
6. 新增页面时，**必须同时更新**所在子目录的 index.md
7. 执行 `search.py --rebuild` 重建倒排索引
8. **索引检索优于 grep**：用 `search.py --query "..."`，不要用 grep 全量扫描

### Scala 3：大型（1000+ 页 / 200 万字以上）

**特征**：倒排索引的结果集也可能太大，需分级精化。

**策略 — 索引 + 分层过滤**：

```
用户提问
    ↓
子目录 index 导航（定位到最相关的子目录）
    ↓
search.py --query "关键词"          # 全库搜索 → 限定到子目录
    ↓
子目录内 read_file index           # 缩小候选范围
    ↓
read_file 最终判定（1~3 页）
    ↓
LLM 组织答案
```

**LLM 行为**：
- 先读子目录 index 缩小范围，再用索引检索
- 如果一个关键词命中 >30 页，不要全部读完。提示用户："这个主题覆盖很广，有 30+ 页面。你想重点看哪方面？"
- 每季度（或每 200 个新增页面）建议用户运行 `search.py --rebuild` 刷新索引

---

## 三层查询架构

**核心理念**：大部分查询不需要加载全文，优先用最小上下文回答问题。

```
┌─────────────────────────────────────────────────────────────┐
│ Level 0: GRAPH_SUMMARY（全局图谱摘要，~500 tokens）              │
│   - graph/GRAPH_SUMMARY.md                                        │
│   - 核心概念列表 + 关系概览                                         │
│   - 快速回答宏观问题                                                │
├─────────────────────────────────────────────────────────────┤
│ Level 1: concepts_index + matched concepts（~1.5K tokens）      │
│   - meta/concepts_index.json                                     │
│   - 匹配的相关概念（名 + 别名）                                    │
│   - 概念 summary（首段）                                           │
├─────────────────────────────────────────────────────────────┤
│ Level 2: Full article body（按需加载，~3K tokens）               │
│   - 完整文章体                                                    │
│   - 通过 FTS5 搜索匹配                                            │
│   - 仅在 Level 0/1 不够时使用                                      │
└─────────────────────────────────────────────────────────────┘
```

**查询命令**：
```bash
# Level 0: 只看全局摘要
python scripts/search_engine.py query "什么是延迟队列?" --level 0

# Level 1: 概念索引匹配（推荐）
python scripts/search_engine.py query "什么是延迟队列?" --level 1

# Level 2: 全文搜索（最后手段）
python scripts/search_engine.py query "什么是延迟队列?" --level 2
```

**LLM 行为**：
- 优先使用 Level 1 查询（大多数问题在此解决）
- 只有当 Level 1 的信息不够详细时，才深入 Level 2
- Level 0 用于回答"有哪些核心概念"等宏观问题

---

## 概念检测自动化

编译后自动执行概念检测，维护 `meta/concepts_index.json` 索引：

```bash
# 单独执行概念检测（独立于编译流程）
WIKI_ROOT=/path/to/wiki python scripts/detect_concepts.py

# 仅检测不修改索引（dry-run 模式）
WIKI_ROOT=/path/to/wiki python scripts/detect_concepts.py --dry-run

# 检测单个页面（可与 --dry-run 组合）
WIKI_ROOT=/path/to/wiki python scripts/detect_concepts.py --page "pages/python-asyncio.md"

# 强制使用深度模式（忽略规模自动判断）
WIKI_ROOT=/path/to/wiki python scripts/detect_concepts.py --mode deep
```

**参数说明**：
- `--dry-run`：扫描并打印检测结果，不写入 `concepts_index.json`
- `--page <路径>`：仅检测指定页面（可单独使用，也可与 `--dry-run` / `--mode` 组合）
- `--mode <fast|balanced|deep>`：覆盖自动规模判断，强制使用对应检测策略
  - `fast`：启发式推断，<50 页场景，每页最多 10 个概念
  - `balanced`：半自动化，50~1000 页场景，每页最多 20 个概念
  - `deep`：完全自动化，>1000 页场景，每页最多 50 个概念

**概念检测规则**：
- 概念定义模式（"[概念]是…"、"[概念]属于…"）
- 技术关键词匹配（async、await、API、REST 等 30+ 模式）
- Markdown 加粗术语（`**概念**`）
- [[概念]] 链接格式

**规模自适应策略**：

| 页面数 | 模式 | 特点 | 每页最大概念数 |
|--------|------|------|---------------|
| < 50 | fast | 启发式推断，简化规则 | 10 |
| 50-1000 | balanced | 半自动化，嵌套检测 | 20 |
| > 1000 | deep | 完全自动化，递归检测 | 50 |

---

## 检索决策树

```
用户提问
  → 调用 question_classifier.py classify "问题"
      判断类型和复杂度
  → 根据 wiki 规模选择策略
      → Scala 1（<200 页）
          → glob("pages/*关键词*") 文件名匹配
          → grep/findstr 内容行匹配
          → read_file 匹配结果页（最多 5~10 页）→ 组织答案
      → Scala 2/3（≥200 页）
          → read_file index.md 了解分区
          → 子目录 index 下钻
          → search.py --query "关键词" 索引检索
  → 三层查询（query --level N）
      → L0/L1 命中？→ 直接回答
      → 未命中？→ 降级 L2 全文搜索
      → 仍为空？→ 回退 grep 或告知用户无相关内容
```

---

## 问题分类与检索策略

调用 `python scripts/question_classifier.py classify "<用户问题>"` 判断问题类型：

| 问题类型 | 特征 | 检索策略 | Token 成本 |
|---------|------|---------|-----------|
| meta | "多少页""最近更新" | 直接读 index.md | ~200 |
| entity | "什么是X""解释X" | Level 1 概念索引 | ~1.5K |
| compare | "X和Y的区别" | Level 2 加载两篇全文 | ~3-5K |
| relation | "X依赖Y" | graph 关系查询 | ~500 |
| synthesis | "发展趋势""挑战" | Level 0 图摘要+多篇 | ~3-6K |
| unknown | 其他 | 标准 Level 1→Level 2自动降级 | ~1.5-6K |
