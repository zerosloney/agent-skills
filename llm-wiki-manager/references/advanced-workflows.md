# 高级工作流指南

> 本文件为高级工作流参考。核心工作流、行为规范见 [`SKILL.md`](../SKILL.md)。

---

## 知识合成

当知识库中关于某个主题积累了多个页面后，可以跨页面合成**新的洞察**。

**触发场景**：
- 用户说"帮我分析一下 X 主题的知识覆盖"、"生成洞察"、"做知识合成"
- LLM 发现同一主题有 3 个以上相关页面

**执行步骤**：

1. **选择主题** — 用户指定，或基于热点自动选择
2. **收集相关页面** — 用 `search.py --query` 找到所有相关页面，全部读完
3. **合成输出**（LLM 直接在对话中输出，不写新文件）：

   ```markdown
   ## 🔬 知识合成：{主题}

   ### 基于资料
   - [[页面A]] — 核心定义
   - [[页面B]] — 应用场景
   - [[页面C]] — 对比分析

   ### 交叉洞察
   - {已有知识 A} 和 {已有知识 B} 之间存在隐含联系：…
   - {来自不同来源的同一个概念} 两篇文章侧重不同角度…

   ### 知识缺口
   - [ ] {缺口 1} — 现有页面未覆盖
   - [ ] {缺口 2} — 跨领域的延伸未涉及

   ### 探索方向
   1. {方向 1} — 建议用户导入资料的方向
   2. {方向 2}

   ```

4. **跟进行动**：
   - 输出中的知识缺口和探索方向 → 触发 LLM 主动建议
   - 如需新建或更新页面 → 走 Two-Step Compile 流程（用户确认后执行）

---

## 查询提升

查询产生的优质回答，不是终点，是知识积累的起点。

**触发条件：**
- 用户提问后，LLM 的回答包含了现有页面未覆盖的深度内容
- 回答引用了多个页面的交叉信息，形成了新洞察
- 用户主动说"把这个回答保存到知识库"

**自动化工具（推荐）：**

```bash
# 列出待提升的候选人查询
WIKI_ROOT=/path/to/wiki python scripts/promote.py --list

# 手动提升单个查询
WIKI_ROOT=/path/to/wiki python scripts/promote.py --promote "outputs/queries/2026-05-13_redis-delay-queue.md"

# 自动提升（智能评分 + 自动筛选）
WIKI_ROOT=/path/to/wiki python scripts/promote.py --auto --threshold 60
```

**Promote 评分算法**：
- 回答长度（40 pts）：>1000字=40, >500字=30, >200字=15, ≤200字=5
- 跨页面引用数（30 pts）：≥3个=30, 2个=20, 1个=10, 0个=0
- 新信息检测（30 pts）：跨页引用≥2 且回答长度>400 =30，否则=0
- 默认阈值 60/100，可自定义 `--threshold`

**`--list` 输出格式**（`promote.py` 逐行打印）：
```
📋 可提升查询列表（共 N 个）

  [1] filename.md
      问题: 用户提问标题
      长度: N 字 | 链接: M | 新信息: 是/否
      评分: NN/100
      文件: outputs/queries/filename.md
```

**`--auto` 输出格式**：
```
🚀 自动提升（阈值: NN分）| 共 N 个

  提升: filename.md (NN分)
  📄 查询文件: filename.md
  ❓ 问题: ...
  📊 评分: NN/100
  📝 目标: raw/xxx.txt

  ✅ 已移动到: raw/xxx.txt
```

**自动化流程**（使用 promote.py）：
1. 扫描 `outputs/queries/` 目录，评分所有候选查询
2. ⚠️ **检查点**：展示候选列表及评分（含摘要），用户选择要 promote 的查询后再继续
3. 选中查询移动到 `raw/` 作为素材源
4. ⚠️ **检查点**：展示拟编译页面清单，用户确认后进入 Two-Step Compile
5. 编译完成后更新缓存、搜索索引、概念索引

**手动流程**（LLM 执行）：
1. 查询回答先暂存到 `outputs/queries/`（临时）
2. LLM 标记哪些回答值得提升为正式文章
3. 用户确认后，走 Two-Step Compile 流程（步骤 3️⃣）写入 `pages/`
4. 暂存文件移动到 `raw/` 作为来源

**输出示例：**
```
💡 查询已暂存: outputs/queries/2026-05-13_redis-delay-queue.md
📌 建议提升：该回答包含 3 个页面的交叉洞察，建议编译为 implementation-detail 类型文章
📊 Promote 评分：75/100（长度: 35pts, 链接: 25pts, 新信息: 15pts）
```

---

## 深度研究

发现知识缺口后，自动闭环补全。

**触发条件：**
- lint 发现知识空白（被引用但不存在的重要概念）
- 用户说"研究一下 X 主题"
- Counter-Arguments 暴露出论据不足

**流程：**
1. 识别缺口 → 生成搜索策略（3-5 个搜索方向）
2. 每个方向自动搜索（web_fetch / Playwright）
3. 搜索结果 → ingest（存入 raw/，更新缓存）
4. 批量 compile（编译为知识页面）
5. lint 确认闭环

**注意：** 每个搜索方向消耗一次网络请求。批量 Deep Research 建议用户确认方向后再执行。

---

## 安全删除

删除 raw 素材时，同步清理引用该素材的知识页面。

```bash
# 预览影响（不实际删除）
python scripts/delete.py --dry-run raw/article.md

# 确认后删除
python scripts/delete.py raw/article.md

# 强制删除（跳过确认）
python scripts/delete.py --force raw/article.md
```

**执行流程：**
1. 查找所有 frontmatter `sources[]` 引用该文件的知识页面
2. 从引用页面的 frontmatter 中移除该 source 条目
3. 删除 raw/ 下的源文件
4. 更新 `.cache/sources.json` 缓存
