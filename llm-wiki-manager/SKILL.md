---
name: llm-wiki-manager
version: "1.5"
description: "LLM 驱动的个人知识库（Wiki）管理系统。
  导入→编译→搜索→问答→Lint→进化，全闭环。
  核心理念：LLM 就是编译器，人类只需掌舵。
   触发词：wiki、知识库、笔记、个人维基、导入文章、检查知识覆盖、lint、书籍笔记、知识管理"
---

# 📚 LLM Wiki 管理器

---

## 全局变量

| 变量 | 说明 | 示例 |
|------|------|------|
| `WIKI_ROOT` | 知识库内容目录（环境变量，默认 `~/wiki/`） | `D:\wiki` |
| `skill_dir` | LLM Wiki Manager 技能安装目录 | `~/.qclaw/skills/llm-wiki-manager` |

> 脚本位于 `skill_dir`，数据位于 `WIKI_ROOT`，**两者不同**。
> 所有脚本调用格式：`WIKI_ROOT=<路径> python {skill_dir}/scripts/<脚本>.py [参数]`
> 以下文档中的命令示例**省略 `WIKI_ROOT=` 前缀**以保持简洁，实际使用时需补上。

---

## 闭环工作流

```
原始资料 → LLM 编译 → 结构化 Wiki → 用户提问 → 即时答案
     ↑                         ↓                    ↓
     └── 用户主动导入 /     lint 健康检查 ←─── 发现缺口，用户确认后补充
         我主动建议导入
```

**你的角色（LLM 行为规范）**：
1. **编译器** — 把 raw/ 下的杂散素材编译为结构化的 pages/*.md
2. **图书管理员** — 维护 index.md 目录和交叉链接
3. **检索引擎** — 用户提问时，定向命中相关页面
4. **质量检查官** — 定期执行 lint，发现问题后**主动向用户建议补充方向**
5. **知识猎人** — 发现风险缺口时主动说："我发现 X 主题的覆盖很薄弱，要不要我找一些资料导入？"

**已实现特性**：
三层查询（L0-L2 Token 优化）| Concept Aliases | 12 种实体类型与验证 | Counter-Arguments 反偏见 | Deep Research 闭环 | 自动图分析 | Promote 提升 | 自动概念检测 | SHA256 缓存 | Safe Delete | source_map 追溯 | Two-Step Compile | **OKF (Open Knowledge Format) v0.1** — Google 企业知识标准融合（2026-06）

**辅助工具**（按需调用，非核心流程）：
- `wiki.py` — Wiki 统一管理入口（聚合常用命令）
- `check_state.py` — Wiki 状态一致性检查
- `git_backup.py` — Git 自动备份
- `suggest_tags.py` — 标签自动建议
- `validate_claims.py` — 来源标注与事实准确性校验
- `validate.py` — 技能结构自校验

**循环触发条件**（有任一项就执行整个循环）：
- 用户发送一个 URL 或文件
- 用户提问后发现 wiki 中没有相关内容
- lint 发现孤悬页面
- 用户主动要求"检查知识覆盖"

> 工作流扩展说明（各步骤细节、场景示例）详见 [`references/workflow-details.md`](references/workflow-details.md)。

---

## 用户 wiki 目录结构

```
{wiki_root}/
├── index.md              # 导航首页（LLM 维护）
├── .lint_report.md       # lint 报告（软链到 outputs/reports/latest.md）
├── .search_index.db      # FTS5 搜索索引（search --rebuild 自动生成）
├── feedback_log.yaml     # 搜索反馈日志（feedback.py 写入，update_weights.py 读取）
├── page_weights.json     # 动态权重缓存（update_weights.py 输出）
├── .cache/
│   └── sources.json      # SHA256 增量缓存（Body-Only Hashing，跳过未变更的 raw 素材）
├── meta/                 # 元数据索引（v1.2 新增）
│   ├── concepts_index.json  # 概念索引：{name → {path, aliases, summary, article_count}}
│   ├── source_map.json      # 源文件追溯：{sha256 → {original_filename, raw_path, generated_pages}}
│   └── filename_index.json  # 文件名重名检测：{stem → [sha256, ...]}
├── graph/                # 知识图谱（v1.2 新增）
│   ├── GRAPH_SUMMARY.md  # 全局图谱摘要（Level 0 查询入口）
│   └── GRAPH_ANALYSIS.md # 自动图分析报告（graph_analyze.py 生成）
├── outputs/
│   ├── queries/          # 问答暂存（promote 前）
│   └── reports/          # lint 报告存档
├── pages/                # 知识页面目录
│   ├── python-asyncio.md
│   └── ...
├── _archived/            # 已归档页面（不被索引/搜索/lint 涉及，永不删除）
├── raw/                  # 原始素材（URL 抓取 / 文件导入）
│   ├── article-on-design-patterns.html.txt
│   └── meeting-notes-2024.md
├── schema/               # 模板与规则
│   ├── page-template.md
│   └── rules.md
└── references/            # 参考文档（编译流程、更新规范、实体类型、工具速查）
    ├── compilation-guide.md
    ├── update-patterns.md
    ├── entity-types.md
    ├── scripts-reference.md
    ├── workflow-details.md      # 工作流扩展说明
    ├── llm-behavior-guide.md    # LLM 行为规范扩展
    ├── retrieval-strategies.md
    ├── advanced-workflows.md
    └── troubleshooting.md
```

`{wiki_root}` 默认 `~/wiki/`，可通过环境变量 `WIKI_ROOT` 覆盖。

---

## ⚠️ 路径规范

> `skill_dir` = LLM Wiki Manager 技能安装目录（如 `~/.qclaw/skills/llm-wiki-manager`）
> `WIKI_ROOT` = 知识库内容目录（如 `D:\wiki`），**两者不同**。脚本位于 skill 目录，数据位于 wiki 目录。

所有脚本执行格式：
```bash
WIKI_ROOT=<wiki路径> python <skill_dir>/scripts/<脚本>.py [参数]
```

| 常见错误 | 正确写法 |
|---------|---------|
| `python scripts/compile_post.py` | `WIKI_ROOT=D:\wiki python {skill_dir}/scripts/compile_post.py` |
| `{WIKI_ROOT}/scripts/xxx.py` | `{skill_dir}/scripts/xxx.py` |

> **WIKI_ROOT 解析顺序**：环境变量 `WIKI_ROOT` → 当前目录 `.wiki_root` 文件 → 默认 `~/wiki/`。
> 生产使用建议显式传入环境变量，避免依赖隐式回退。

---

## purpose.md — 知识库灵魂

`purpose.md` 是知识库的"宪法"。LLM 每次会话开始必须先读取它，对齐方向。

**内容结构：**
```markdown
# 知识库目标

## 核心问题
- 这个知识库要回答的核心问题是什么？
- 目标读者是谁？

## 研究范围
- 涵盖哪些领域？
- 明确不涵盖哪些领域（防止膨胀）？

## 演进论点
- 当前最想验证/推翻的假设是什么？
```

**LLM 行为：**
- 每次会话开始，先读 `purpose.md` 对齐方向
- 发现内容偏离 purpose 范围时，主动提醒用户
- 每季度建议用户审视并更新 purpose.md

## 搜索与检索体系

### 检索决策树

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

### 规模分级策略

知识库规模不同，LLM 的检索策略必须不同。**提前判断规模，选择对应策略。**

#### Scala 1：小型（< 200 页 / < 40 万字）

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

### 三层查询架构

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

> **工具速查**：完整命令表、环境要求、脚本前置条件、错误码见 [`references/scripts-reference.md`](references/scripts-reference.md)。

### Concept Aliases（跨部门术语统一）

**问题**：销售说"数字平台"，研发说"Digital Platform"，法务说"数字化平台" —— 三者指的是同一个概念。

**解决方案**：`meta/concepts_index.json` 维护概念别名。

```json
{
  "Digital Platform": {
    "path": "pages/digital-platform.md",
    "aliases": ["数字平台", "数字化平台", "digital-base"],
    "summary": "企业数字化转型的基础设施层...",
    "article_count": 12
  }
}
```

**LLM 行为**：
- 编译新文章时，自动识别新概念并更新 concepts_index
- 概念名优先用英文（跨语言兼容），aliases 填中文同义词
- 用户提到任何 alias 时，都能匹配到正确的 concept

> **管理命令**：`index.py concepts-show/add/match`、`detect_concepts.py` 详细参数见 [`references/scripts-reference.md`](references/scripts-reference.md)。

**概念检测与验证工具**：
- `detect_concepts.py`：自动从页面提取概念，更新 `concepts_index.json`
- `validate_entities.py`：验证 entity_type 合规性，检查必需章节

> **Scala 2/3 检索策略**：详见 [`references/retrieval-strategies.md`](references/retrieval-strategies.md)。

#### Scala 2：中型（200~1000 页 / 40~200 万字）

详见 [`references/retrieval-strategies.md`](references/retrieval-strategies.md)。

#### Scala 3：大型（1000+ 页 / 200 万字以上）

详见 [`references/retrieval-strategies.md`](references/retrieval-strategies.md)。

---

### Token 预算管理

详见 [`references/retrieval-strategies.md`](references/retrieval-strategies.md)。

## 核心流程

### 1️⃣ 初始化新 wiki

```powershell
# 运行初始化（自动创建 outputs/ 和 .cache/ 目录）
WIKI_ROOT=D:\wiki python scripts/init.py

# 指定场景模板
WIKI_ROOT=D:\wiki python scripts/init.py --template research
```

### 2️⃣ 导入素材

**URL 抓取由 LLM 使用 `web_fetch` 工具完成**（反爬、编码、正文提取都比 Python 脚本更可靠）。

**URL 导入流程（LLM 执行）：**

1. LLM 使用 `web_fetch` 工具抓取 URL，获取正文内容
2. LLM 将抓取到的内容写入 `raw/` 目录（自动命名）
3. 运行 `python scripts/cache.py update <新文件>` 更新缓存
4. 进入编译流程（步骤 3️⃣）

**本地文件导入（脚本辅助）：**

```bash
# 导入本地文件到 raw/（同时更新 SHA256 缓存）
WIKI_ROOT=D:\wiki python scripts/fetch.py C:\path\to\file.md

# 粘贴内容
echo "正文内容" | python scripts/fetch.py --stdin "标题"
```

**SHA256 增量缓存**：
- `scripts/cache.py status` — 查看缓存状态
- `scripts/cache.py sync` — 同步所有 raw 文件哈希
- ingest 时用 `cache.py check <file>` 判断是否有变化，无变化跳过 compile

**分工原则：**
- URL 抓取 → `web_fetch`（LLM 工具），成功率高、正文提取准
- 本地文件 / stdin → `fetch.py`（Python 脚本），操作文件系统
- 编译知识页面 → LLM（步骤 3️⃣）

### 3️⃣ 编译知识页面（Two-Step Compile）

**两步编译**：Analyze（分析）→ Generate（生成），先分析后输出，避免直接生成的盲目性。

#### 步骤一：Analyze（分析）

读取 raw 素材后，先输出结构化分析，**不写文件**：

```markdown
## 📋 分析：{素材标题}

### 实体类型判定
- 类型：从 `{skill_root}/schema/entity-types.yaml` 中选择
  - 优先匹配 **base_types**（concept / implementation-detail / tutorial / reference / case-study / opinion）
  - 如果 base_types 都不够贴切，再匹配 **extensions**
  - 如果 extensions 也不够贴切，可以**向用户提议**添加新的扩展类型
    → 说明：新类型名称、适用场景、必需章节
    → 用户确认后，在 schema/entity-types.yaml 的 extensions 中添加
- 判定理由：...

### 核心概念
- {概念A}：{1句话定义}
- {概念B}：{1句话定义}

### 关联已有知识
- [[已有页面X]] — 关联点：...（补充/扩展/修正）
- [[已有页面Y]] — 关联点：...

### 知识缺口
- [ ] {缺口1}：现有 wiki 未覆盖
- [ ] {缺口2}：被引用但不存在的重要概念

### 编译方向
- 新建页面：{页面标题}（全新主题）
- 或更新页面：[[已有页面]]（补充章节/修正内容）

### Counter-Arguments 评估
- 来源数量：N（触发阈值：≥3）
- 对立观点：{来源B的不同观点}（如有）
```

用户确认分析结果后，进入 Step 2。

#### 步骤二：Generate（生成）

用户确认后，按模板生成或更新页面：

```bash
# 新建页面 → 写入 pages/
# 更新页面 → 先输出 Structured Diff，用户确认后更新
```

**参考示例**：编译前先读 `examples/concept-example.md`，了解已完成页面的风格和结构。

**实体类型分类优先级**：见 `schema/entity-types.yaml`

选择规则：
1. 优先匹配 **base_types**（6 种核心类型，稳定不动）
2. 如果 base_types 都不贴切，匹配 **extensions**
3. 如果 extensions 也不够贴切，向用户提议新增扩展类型

**实体类型与必需章节映射**（来自 schema/entity-types.yaml）：

| 类型 | 适用场景 | 必需章节 |
|------|----------|----------|
| `concept` | 抽象概念、理论、算法 | 定义与核心思想、关键原理 |
| `implementation-detail` | 技术实现、架构方案 | 方案描述、关键考量 |
| `tutorial` | 操作指南、最佳实践 | 前提条件、步骤 |
| `reference` | 外部资料索引、论文笔记 | 来源、核心内容 |
| `case-study` | 场景实践、案例分析 | 背景、方案、结果 |
| `opinion` | 观点、思辨分析 | 主张、论据 |
| `comparison` | 多方案对比 | 对比维度、各方特点、结论 |
| `decision-record` | 架构决策ADRs | 背景、方案、论证、结论 |
| `troubleshooting` | 问题诊断、故障处理 | 现象、原因、解决步骤 |
| `survey` | 领域综述、趋势分析 | 背景、各派观点、趋势判断 |
| `cheat-sheet` | 语法速查、API参考 | 条目列表 |
| `standard` | 编码规范、团队约定 | 适用范围、规则、违反后果 |

> 12 种类型（6 基础 + 6 扩展），详见 `schema/entity-types.yaml` 和 `references/entity-types.md`。

**实体类型验证工具**：

验证所有页面的 entity_type frontmatter 是否符合 `schema/entity-types.yaml` 定义：

```bash
# 检查所有页面
WIKI_ROOT=/path/to/wiki python scripts/validate_entities.py

# 自动修复缺失的 frontmatter 字段
WIKI_ROOT=/path/to/wiki python scripts/validate_entities.py --fix

# 验证单个页面
WIKI_ROOT=/path/to/wiki python scripts/validate_entities.py --page "pages/python-asyncio.md"
```

**验证内容**：
- frontmatter 是否包含 `entity_type` 字段
- entity_type 是否属于 schema 定义的类型（base_types + extensions）
- 是否包含该类型必需的章节
- 自动推断类型（基于关键词）
- 自动补充缺失的 frontmatter 字段（`--fix` 模式）

**实体类型写入 frontmatter（OKF v0.1 标准）：**
```yaml
---
type: implementation-detail    # OKF v0.1 标准字段（推荐）
entity_type: implementation-detail  # 向后兼容别名
title: 页面标题
description: 单句摘要
tags: [分布式系统, 中间件]
timestamp: 2026-06-19T14:30:00Z
confidence: 0.85
status: draft
domains: [分布式系统, 中间件]
sources: [raw/order-timeout-wechat.md]
---
```

**Counter-Arguments 反偏见机制**（综合 3+ 来源时自动触发）：
编译文章时，如果引用了 3 个及以上不同来源，在文章末尾自动生成反论段落：

```markdown
## ⚖️ Counter-Arguments

- **对立观点**：{来自来源B的不同观点}
- **适用边界**：{方案A的局限性}
- **替代方案**：{其他可行路径}
```

**LLM 编译步骤（完整流程）**：

1. **读取素材**：`read_file` 读取 raw/ 下的原始内容
2. **Analyze**：输出结构化分析（见上方），用户确认
3. **浏览已有知识**：
   - 先读 `index.md` 了解分区结构
   - 用 `glob` 查找相关页面
   - 用 `search.py --query "关键词"` 检索已有内容（页面多时优先用索引）
4. **判断新建还是更新**：
   - 新建 → 全新主题 → 走 Step 2 Generate
   - 更新 → 已有页面覆盖类似内容 → **先输出 Structured Diff**，用户确认后更新
5. **创建/更新页面**：按 `schema/page-template.md` 格式写入 `pages/`
   - 自动分配标签（小写英文或中文关键词）
   - **建立双向交叉链接**：新页面 `## 相关页面` 指向旧页面，同时编辑旧页面添加回链
   - ⚠️ **检查点**：补回链前，列出「需回链页面清单」（页面名 + 关联说明），用户确认后再批量编辑
6. **更新导航**：
   - 小型：直接编辑 `index.md` 添加条目
   - 中型/大型：同时编辑**所在子目录的 index.md**
7. **编译后处理**：运行 `python scripts/compile_post.py`
   - **Step 1**：缓存更新（SHA256 Body-Only Hashing）
   - **Step 2**：搜索索引重建（FTS5 + 词项 + 元数据）
   - **Step 3**：index.md 时间戳更新
   - **Step 4**：概念检测与索引刷新（自动识别新概念并更新 `meta/concepts_index.json`）
   - **Step 4b**：OKF v0.1 字段自动增强（自动填充 `type`/`title`/`description`/`timestamp`/`status`/`confidence` 等字段，兼容旧 `okf_*` 字段）
   - **Step 5**（可选）：标签自动建议（仅当传入 `--page` 时触发，为指定页面推荐标签）
   - **Step 6**（可选）：Git 自动备份（将所有变更提交到 git，防止数据丢失）
   - 此脚本原子完成所有步骤，如果 LLM 在前几步崩溃，此脚本保证状态一致

**概念检测自动化（compile_post.py Step 4）**：

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
- 概念定义模式（"[概念]是..."、"[概念]属于..."）
- 技术关键词匹配（async、await、API、REST 等 30+ 模式）
- Markdown 加粗术语（`**概念**`）
- [[概念]] 链接格式

---

### 7️⃣ OKF (Open Knowledge Format) v0.1 管理命令

OKF v0.1 是谷歌 2026-06 发布的知识标准化格式（[官方规范](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md)）。
CLI 工具提供字段管理、生命周期管理、Bundle 导出和知识图谱导出：

```bash
# 检查 OKF v0.1 字段完整性（type 为唯一必须字段）
WIKI_ROOT=D:\wiki python scripts/okf_cli.py check pages/python-asyncio.md

# 推进生命周期状态（draft→review→published→archived）
WIKI_ROOT=D:\wiki python scripts/okf_cli.py promote pages/python-asyncio.md published

# 查看版本历史
WIKI_ROOT=D:\wiki python scripts/okf_cli.py history pages/python-asyncio.md

# 迁移旧 okf_* 字段到 OKF v0.1 新命名（先试运行）
WIKI_ROOT=D:\wiki python scripts/okf_cli.py migrate --dry-run
WIKI_ROOT=D:\wiki python scripts/okf_cli.py migrate

# 导出 OKF v0.1 规范 Bundle（含 index.md + log.md）
WIKI_ROOT=D:\wiki python scripts/okf_cli.py export
WIKI_ROOT=D:\wiki python scripts/okf_cli.py export --output /path/to/bundle

# 导出知识图谱 JSON
WIKI_ROOT=D:\wiki python scripts/okf_cli.py graph-export

# 显示 OKF v0.1 统计
WIKI_ROOT=D:\wiki python scripts/okf_cli.py status
```

**状态流转规则**：
| 当前状态 | 允许流转 → |
|---------|-----------|
| draft | review, archived |
| review | published, draft, archived |
| published | review, archived |
| archived | review（恢复需重新审核） |

**规模自适应策略**（自动根据知识库规模选择）：
| 页面数 | 模式 | 特点 | 每页最大概念数 |
|--------|------|------|---------------|
| < 50 | fast | 启发式推断，简化规则 | 10 |
| 50-1000 | balanced | 半自动化，嵌套检测 | 20 |
| > 1000 | deep | 完全自动化，递归检测 | 50 |

**概念索引结构**（`meta/concepts_index.json`）：
```json
{
  "Asyncio": {
    "path": "pages/python-asyncio.md",
    "aliases": ["异步IO", "asyncio"],
    "summary": "Python 异步编程核心框架...",
    "article_count": 12
  }
}
```

**编译输出示例**：
```
✅ 已编译：pages/python-asyncio.md
🔗 交叉链接：3 个页面（asyncio-vs-threads.md, event-loop.md, async-await.md）
📊 分区：开发/后端
🏷 标签：python 异步 并发
📌 索引已更新
📦 缓存已更新
```

### 4️⃣ 搜索知识库（用户提问）

**重要：搜索前先分类（零 Token 成本）**
调用 `python scripts/question_classifier.py classify "<用户问题>"`，
判断问题类型后选择对应的检索策略：

| 问题类型 | 特征 | 检索策略 | Token 成本 |
|---------|------|---------|-----------|
| meta | "多少页""最近更新" | 直接读 index.md | ~200 |
| entity | "什么是X""解释X" | Level 1 概念索引 | ~1.5K |
| compare | "X和Y的区别" | Level 2 加载两篇全文 | ~3-5K |
| relation | "X依赖Y" | graph 关系查询 | ~500 |
| synthesis | "发展趋势""挑战" | Level 0 图摘要+多篇 | ~3-6K |
| unknown | 其他 | 标准 Level 1→Level 2自动降级 | ~1.5-6K |

根据 wiki 规模选择策略（见上方的「规模分级策略」）。Claude 遵循：

- **小规模**：先用 `glob` 按文件名匹配，再用原生查找命令搜内容
- **中大规模**：优先用 `search.py --query "关键词"`（替代原生查找）

LLM 读取匹配文件后自行判断相关性并组织回答。**不要把所有匹配文件都读完**——先读文件名和摘要，只读最相关的 2~3 页。

### 5️⃣ 问答回写

用户提问并得到答案后，**如果问答产生了新信息**，将其回写到相关页面的 `## 常见问题` 部分：

```markdown
## 常见问题

- Q: Rust 的异步运行时和 Go 的 goroutine 有什么区别？
  A: Rust 使用协作式调度（await 点让出控制权），Go 使用抢占式调度（runtime 自动切换）。
  来源：用户问答 2026-05-15
```

**什么情況回写**：
- ✅ 用户的问号揭示了已有知识之间的关联
- ✅ 答案补充了页面中未覆盖的细节
- ✅ 问答涉及跨页面的对比（这是最有价值的回写）
- ❌ 答案完全可以从已有页面直接读出（无新信息）
- ❌ 用户随口一问的简单确认（"xx 是不是这样做？" "是的"）

**回写格式**：
- 追加到最相关页面的底部，放在 `## 常见问题` 区块
- 标注来源为"用户问答 {日期}"
- 如果问答跨越多个页面（如对比），在主页面追加，在对比页面添加 [[链接]]

### 6️⃣ 健康检查

先快速扫描实体类型合规性，再运行完整 lint：

```bash
# 扫描所有页面的实体类型（自动修复缺失字段）
python scripts/validate_entities.py --scan --fix

# 完整健康检查
python scripts/lint.py
```

脚本自动检查八项：
- 🔗 **孤悬页面** — 没有任何页面引用它
- 💔 **断链** — `[[目标]]` 在 `pages/**/*.md` 中全局搜索不到（rglob 匹配）
- 🏷 **缺少标签** — 不含 `> 标签：`xxx`` 格式的标签声明
- 📝 **缺少摘要** — 标题后无 `>` 开头的摘要行
- 📋 **缺少必要章节**（相关页面 / 来源）
- 🧩 **概念一致性** — `meta/concepts_index.json` 中概念指向不存在的文件
- **📋 OKF 必填字段** — `type` 缺失（OKF v0.1 唯一必须字段）
- **📋 OKF 字段合法性** — `status` 非法值、`confidence` 越界、日期格式错误、`related_articles` 引用不存在页面
- **⚠️ OKF 推荐字段缺失警告** — `title`/`description`/`resource`/`tags`/`timestamp` 缺失（非 blocking）

> OKF 校验由 `scripts/lint.py` 内置执行，无需额外命令。

脚本输出完成后，LLM 还需人工检查两项：

**矛盾检测**：
- 同一概念在不同页面中是否有不一致的描述？
  > 例：A 页面说"PostgreSQL 默认隔离级别是 Read Committed"，B 页面说"PostgreSQL 默认隔离级别是可序列化" → 矛盾
- 同一实体在不同来源中是否有矛盾的数值/日期/事实？
- 涉及时间的页面是否已过时？

**知识空白检测**：
- 页面的 `[[链接]]` 指向了不存在的概念，但这个概念值得独立成篇？
- 用户提问反复涉及某个主题但没有对应页面？

如发现矛盾，在相关页面追加 `⚠️ 矛盾标注` 区块：

```markdown
## ⚠️ 矛盾标注

- 在 [[页面A]] 中描述为：PostgreSQL 默认隔离级别是 Read Committed
- 在 [[页面B]] 中描述为：PostgreSQL 默认隔离级别是可序列化
- 需要确认：实际是 Read Committed（除非特殊情况）
```

输出一份 Markdown 报告到 `{wiki_root}/outputs/reports/{日期}.md`（存档），并复制到 `{wiki_root}/.lint_report.md` 供快速查阅。

**图分析**（纯文本，无 GUI 依赖）：

lint 完成后，LLM 自动做一次纯文本图分析。**或者使用自动化工具 `graph_analyze.py` 获得更准确的分析结果**：

```bash
# 自动化图分析（推荐）
WIKI_ROOT=/path/to/wiki python scripts/graph_analyze.py

# 输出 JSON 格式（用于程序处理）
WIKI_ROOT=/path/to/wiki python scripts/graph_analyze.py --json
```

**graph_analyze.py 分析结果**（自动生成 `graph/GRAPH_ANALYSIS.md`）：

**LLM 手动图分析示例**（可选）：

```markdown
## 🔬 图分析摘要

### 桥接节点（连接多个孤立区域）
- [[分布式系统]] → 连接了 [[延迟队列]]、[[CAP定理]]、[[共识算法]] 三个区域

### 孤立页面（有内容但无任何链接）
- [[rust-ownership]] — 建议关联 [[内存管理]]、[[RAII]]

### 知识集群（密集互连的区域）
- 后端架构集群（12 页面，核心：[[微服务]]）
- AI 集群（8 页面，核心：[[Transformer]])

### 惊喜连接（跨领域关联）
- [[消息队列]] 的延时机制 ≈ [[Redis ZSet]] 的延迟队列原理
```

**graph_analyze.py 自动分析包含**：
- 关键概念节点 Top 10（度数中心性排名）
- 孤立节点、孤儿节点、死节点统计
- 概念集群（弱连通分量分析）
- 知识缺口识别（被引用但无页面的概念）
- 改进建议（短期/中期/长期）

**lint 后的闭环**：

```
lint 输出报告
    ↓
LLM 分析报告
    ├── 孤悬页面 → 判断是"知识缺口"还是"漏链"还是"废弃页面"
    │   ├── 知识缺口 → 主动建议用户补充资料
    │   ├── 漏链 → 补回链
    │   └── 废弃页面 → 用户确认后**移动到 _archived/**（永不删除）
    ├── 断链 → 修正或删除无效引用
    ├── 缺少标签 → 补充
    ├── 缺少章节 → 补充
    ├── 矛盾 → 追加矛盾标注，通知用户确认
    └── 知识空白
        ├── 有素材缺页面 → 主动建议用户导入资料
        └── 有页面引用指向不存在的概念，值得独立成篇 → 走编译新建流程（回到步骤 3️⃣）
    ↓
⚠️ **检查点**：输出「知识缺口优先级清单」（按影响面排序，标注紧急/重要），等用户确认补充方案
    ↓
用户确认或提供新素材
    ↓
重新编译（回到步骤 3️⃣）
    ↓
再次 lint 确认闭环
```

**LLM 主动建议的话术示例**：
> "我发现孤悬页面 `rust-ownership.md` 有知识但没有其他页面引用它。同时我注意到你的 wiki 没有 `borrowing` 和 `lifetime` 的独立页面。要不要我找些资料补充这两个概念？如果 `rust-ownership` 已经不再需要，我可以把它移到 `_archived/` 归档。"

**归档策略**：
- 永不做 `rm`/`delete`：废弃页面统一移动到 `_archived/`，用户可随时手动恢复
- 归档前须用户确认，不可自行归档
- `_archived/` 下的文件被 lint、search、索引构建**自动排除**
- 如需恢复：将文件从 `_archived/` 移回 `pages/`，运行 `search.py --rebuild` 重建索引

> **高级工作流**：知识合成、查询提升、深度研究、安全删除详见 [`references/advanced-workflows.md`](references/advanced-workflows.md)。

---

## 页面模板

按 `schema/page-template.md` 格式撰写。

### 来源追溯

每篇文章的 frontmatter 中记录 `sources` 数组：

```yaml
---
sources:
  - raw/order-timeout-wechat.md
  - web:https://redis.io/docs/data-types/sorted-sets/
  - query:2026-05-13_redis-delay-queue
---
```

**级联规则：**
- 删除 raw/ 源文件时，自动触发 Safe Delete（步骤 🔟），清理所有引用页面的 sources[]
- Query 暂存文件提升为正式文章后，更新引用链
- lint 时检测缺少来源的文章（标记为"来源待追溯"）

### 命名规范

| 约定 | 说明 | 示例 |
|------|------|------|
| 文件名 | 英文小写 + 连字符 `-` | `python-asyncio.md` |
| 标签 | 英文缩写或中文关键词 | `python 异步` |
| 交叉链接 | `[[页面名]]` 格式（按文件名全局解析，与子目录位置无关） | `[[event-loop]]` |
| 分区 | 根级 h2 分类 | `## 后端开发` |
| 子目录 index | 含页面名 + 摘要 + 标签 | 见 Scala 2 规范 |

## Structured Diff 更新规范

更新已有页面时，必须先输出 Structured Diff，用户确认后再执行：

```markdown
## 📝 页面更新：{页面标题}

### Current（当前内容）
> {现有描述...}

### Proposed（建议修改）
> {修改为...}

### Reason（修改理由）
> {为什么要这样改...}

### Source（来源依据）
> {哪个素材/来源支持这个修改}
```

用户用 `y` 确认后才更新页面。

## LLM 行为规范（完整版）

### 主动行为

LLM 在以下情况下**必须主动执行**，不等待用户指令：

- **lint 发现孤悬页面** → 立即分析并建议：补链 / 归档 / 补充素材
- **用户提问但 wiki 中无相关内容** → 主动建议导入相关资料方向
- **Counter-Arguments 被触发** → 主动提示用户对立观点
- **lint 发现 3+ 来源可触发 Counter-Arguments** → 主动触发
- **同一 raw 素材被多次引用** → 建议合并编译
- **pages/ 下 .md 文件超过 50 个** → 主动建议划分子目录
- **Promote 暂存的查询** → 定期提醒用户是否提升为正式文章
- **purpose.md 季度审视日期临近** → 主动提醒用户审视知识库方向

### 禁止事项

- ❌ 不要在 `pages/` 之外创建 .md 页面文件
- ❌ 不要删除页面文件（废弃页面应由用户确认后移动到 `_archived/` 归档）
- ❌ 不要修改 `raw/` 下的原始素材（用 Safe Delete 流程删除）
- ❌ 不要删除其他 LLM 创建的交叉链接（只追加）
- ❌ 不要在页面文件名中使用中文、空格或特殊字符
- ❌ 不要在 `[[链接]]` 中使用路径分隔符 `/`，一律只用文件名
- ❌ 不要直接手写 `schema/page-template.md` 和 `schema/rules.md`（这两个模板由 `init.py` 初始化）
- ✅ `schema/entity-types.yaml` 的 `extensions` 部分：用户确认添加新类型后，由 LLM 写入
- ✅ `meta/concepts_index.json`、`meta/source_map.json`、`meta/filename_index.json`：由 `index.py` / `detect_concepts.py` / `compile_post.py` 自动维护，LLM 不直接手写
- ❌ 用户提问时，不要一次读超过 30 个页面到上下文
- ❌ 更新已有页面时，不经用户确认直接修改（必须先输出 Structured Diff）

### 优先级

1. **知识归类优先级**：匹配已有分区 → 创建新分区 → 归入"待分类"
2. **检索优先级**：问题分类 → 子目录 index → search.py → grep
3. **回答优先级**：精准引用 wiki 内容 → 结合自身知识补充 → 告诉用户暂无相关知识
4. **多请求优先级**：
   - 导入素材优先于问答（先入库，再回答）
   - 同一会话中：先收到的指令先处理；后收到的指令排队
   - 用户说"先帮我查 X 再导入 Y" → 按用户显式顺序执行
   - **检查点指令**（确认 / 合并 / 归档）优先于新建操作
5. **冲突仲裁**：多会话编辑冲突时，以最后一次 `read_file` 的版本为准，由 LLM 负责合并而非覆盖

### Token 优先级

1. **识别问题类型优先于搜索**：先调用 `question_classifier.py classify` 判断，
   明确问题的类型和复杂度，然后选择对应的检索路径。
2. **简单问题走短路径**：实体类问题只用 Level 1，不要自动降级到 Level 2
3. **复杂问题走深路径**：对比/综合类问题直接走 Level 2，不需要先 Level 1 碰运气

### 自我校验

编译页面时遵循：
1. 如果页面包含具体数字、日期、名称，标注来源
2. 无法标注来源的，在页面中添加 `[需要验证]` 标记
3. 区分"根据资料 X"（事实引用）和"通常来说"（观点推断）

> **行为规范扩展**：并发冲突保护、批量操作失败处理、网络异常、大文件素材分块、compile_post 部分失败回滚、编码异常等进阶场景详见 [`references/llm-behavior-guide.md`](references/llm-behavior-guide.md)。

---

## 常见问题

| 现象 | 原因 | 解决方案 |
|------|------|----------|
| search 命令报错 | 可能是索引未建立 | 先运行 `search.py --rebuild` 重建索引 |
| pages/ 下文件太多记不住 | 即达到 Scala 2 规模 | 建议划分子目录，建索引 |
| 中文搜索不准确 | grep 不支持中文分词 | 运行 `search.py --rebuild` 建索引 |
| URL 抓取失败 | 网络问题或反爬 | 手动复制内容后 `--stdin` 导入 |
| lint 输出大量孤悬页面 | 可能是未建立链接 | 分析后逐页面确认：补链还是缺口 |
| 用户问的内容 wiki 里没有 | 知识覆盖不足 | 主动建议导入相关资料 |
| 搜索返回空结果 | FTS5 索引损坏或不完整 | 运行 `search_engine.py rebuild` 重建索引 |
| concepts_index.json 解析失败 | JSON 损坏或空文件 | 运行 `detect_concepts.py` 重新扫描所有页面 |
| raw 素材乱码 | 编码非 UTF-8（如 GBK） | `Get-Content -Encoding UTF8` 显式指定编码读取 |
| 脚本返回 exit code 1 | 通用错误 | 检查输出文本中的错误描述，确认具体原因后重试或修复 |

---

## 异常恢复

### 元数据损坏

`meta/` 下的 JSON 文件损坏时，按优先级恢复：

| 损坏文件 | 影响 | 恢复命令 |
|----------|------|----------|
| `concepts_index.json` | 三层查询 L1 降级到 L2 | `python scripts/detect_concepts.py` |
| `source_map.json` | 无法追溯页面来源 | 下次 `compile_post.py` 自动重建 |
| `filename_index.json` | 重名检测失效 | 下次 `compile_post.py` 自动重建 |
| `feedback_log.yaml` | 权重更新无数据源 | 删除后自动重建空日志 |
| `page_weights.json` | 动态权重失效 | `python scripts/update_weights.py` |

> ⚠️ **检查点**：检测到元数据异常时，先告知用户影响范围（搜索精度降级 / 来源追溯中断），再执行恢复。

### 搜索索引异常

```
症状：search.py 返回空 / FTS5 报错
    ↓
先验证：python scripts/search_engine.py stats  # 检查索引状态
    ↓
异常 → python scripts/search_engine.py rebuild  # 重建
    ↓
回退方案：grep 全文搜索（精度低但可用）
```

> **故障排查**：并发冲突、批量失败、网络异常、大文件处理、compile_post 回滚、编码异常详见 [`references/troubleshooting.md`](references/troubleshooting.md)。
