# 脚本工具参考

> 本文件为工具速查手册。核心工作流、行为规范见 [`SKILL.md`](../SKILL.md)。

---

## CLI 工具速查

| 场景 | 命令 | 说明 |
|------|------|------|
| 三层查询（LLM 首选） | `search_engine.py query "..." --level 1` | 概念→FTS5 自动降级 |
| 快速关键词搜索 | `search.py "关键词"` | grep→JSON→FTS5 三级降级 |
| 精确 FTS5 检索 | `search.py --query "..."` | 仅 FTS5 引擎 |
| FTS5 标题搜索（旧接口） | `search_engine.py search "关键词"` | 仅标题匹配，建议用 `query` |
| 重建全部索引 | `search_engine.py rebuild` | FTS5+词项+元数据全量重建 |
| 增量更新索引 | `search_engine.py update` | 仅更新变更页面 |
| 索引统计 | `search_engine.py stats` | 页面/概念/词项数量 |
| 概念索引管理 | `index.py concepts-show` | 查看概念索引 |
| 概念索引管理 | `index.py concepts-add "名" --path "path" --aliases "a1,a2"` | 添加概念 |
| 概念索引管理 | `index.py concepts-match "关键词"` | 匹配相关概念 |
| 概念索引管理 | `index.py source-show` | 查看源文件映射 |
| 问题分类（检索前调用） | `question_classifier.py classify "问题"` | 零 Token 成本判断问题类型 |
| 搜索反馈记录 | `feedback.py log --query ... --results ... --click 1 --helpful yes` | 记录用户对搜索结果的满意度 |
| 反馈统计 | `feedback.py stats` | 查看反馈数据概览 |
| 动态权重更新 | `update_weights.py` | 基于反馈调整搜索排序权重 |
| 权重查看 | `update_weights.py --show` | 查看当前所有页面的权重分布 |
| 事实校验 | `validate_claims.py pages/some-page.md` | 检查页面的来源标注和事实准确性 |
| 全量校验 | `validate_claims.py --all` | 批量检查所有页面 |
| 实体类型扫描 | `validate_entities.py --scan --fix` | 批量扫描并自动修复实体类型 |
| 安全删除（预览） | `delete.py --dry-run raw/file.md` | 预览删除影响 |
| 安全删除（执行） | `delete.py raw/file.md` | 级联清理 + 归档 |
| 概念检测 | `detect_concepts.py --dry-run` | 自动发现新概念 |
| 图分析 | `graph_analyze.py` | 孤立节点/集群检测/桥接节点 |
| 编译后处理 | `compile_post.py` | 增量缓存→索引→图|

> **注意**：`_common.py` 是所有脚本的公共依赖模块（`get_wiki_root` / `resolve_path` / `body_for_hash` / `file_hash`），不直接调用。

### 关键区别

- `search_engine.py query` = **三层查询引擎**（LLM 首选，`--level 0/1/2`）
- `search_engine.py search` = **旧版标题搜索**（仅匹配标题，无分层）
- `search_engine.py stats` = 索引统计信息
- `search.py` = **用户友好前端**（三级降级：FTS5→JSON→grep），适合终端手动搜索

---

## 环境要求

- Python 3.8+，需安装依赖：`pip install -r requirements.txt`
  - `requests>=2.28.0`（URL 抓取）
  - `jieba>=0.42.1`（中文分词，FTS5 索引需要）
- FTS5 扩展：Python 内置 SQLite 通常已包含 FTS5；如缺失，安装 `pysqlite3-binary` 或重新编译 Python 时启用 `--enable-loadable-sqlite-extensions`
- 操作系统：Linux / macOS / Windows 均支持；路径分隔符在脚本内部自动适配

---

## 脚本前置条件

每个脚本调用前，确保以下目录/文件存在（`init.py` 已全部创建）：

| 脚本 | 前置条件 | 缺失时行为 |
|------|---------|-----------|
| `compile_post.py` | `WIKI_ROOT` 设置；`pages/` 目录（可空） | `.cache/` 不存在时自动创建 |
| `search_engine.py rebuild` | `WIKI_ROOT` 设置；`pages/` 目录（可空） | `graph/` `meta/` 不存在时自动创建 |
| `search_engine.py update` | `WIKI_ROOT` 设置；`pages/` 必须存在 | 不存在则打印警告并返回 |
| `search_engine.py query` | FTS5 索引已存在（先运行 `rebuild`） | 空结果或报错 |
| `search_engine.py search` | FTS5 索引已存在（先运行 `rebuild`） | 空结果或报错 |
| `promote.py --list` | `outputs/queries/` 目录 | 不存在则提示"目录为空" |
| `promote.py --promote` | `outputs/queries/` 目录 | 同上 |
| `detect_concepts.py` | `pages/` 有内容；`meta/concepts_index.json` 存在 | 索引不存在时自动创建空文件 |
| `lint.py` | `pages/` 目录存在 | `meta/concepts_index.json` 缺失时跳过概念检查 |
| `validate_entities.py` | `pages/` 目录存在；`schema/entity-types.yaml` 存在 | 两者任一缺失时报错 |
| `delete.py` | `WIKI_ROOT` 设置；`meta/source_map.json` 存在 | 无 source_map 则无法级联清理 |

---

## 统一错误码

当前所有脚本统一使用以下 exit code（脚本直接 `sys.exit`，无需额外解析）：

| exit code | 含义 | 触发场景 |
|-----------|------|---------|
| `0` | 成功 | 脚本正常执行完成 |
| `1` | 通用错误 | 参数错误、未知子命令、文件不存在、权限不足、JSON 损坏、数据库异常等 |

> **现状说明**：目前所有脚本统一使用 `0`（成功）/`1`（所有错误）。不区分错误子类型。
> **LLM 判断方式**：优先通过 `$LASTEXITCODE`（PowerShell）/`$?`（bash）判断 0/1，
> 其次解析输出文本中的错误描述（如"❌"、"⚠️"、"错误"等前缀）。
> **未来扩展**：如需更细粒度错误码，可在此定义 `2`/`3`/`4`，并同步更新各脚本的 `sys.exit()` 调用。

---

## Concept Aliases 管理命令

`meta/concepts_index.json` 维护概念别名，实现跨部门术语统一。

```bash
# 查看概念索引
python scripts/index.py concepts-show

# 添加概念
python scripts/index.py concepts-add "AI Agent" --path "pages/ai-agent.md" --aliases "智能代理,AI代理"

# 匹配相关概念
python scripts/index.py concepts-match "数字平台"

# 概念检测（自动维护 concepts_index.json）
python scripts/detect_concepts.py              # 扫描所有页面
python scripts/detect_concepts.py --page "pages/python-asyncio.md"  # 单页检测
python scripts/detect_concepts.py --dry-run     # 仅检测不修改
python scripts/detect_concepts.py --mode deep   # 强制深度模式
```

**参数说明**：
- `--dry-run`：扫描并打印检测结果，不写入 `concepts_index.json`
- `--page <路径>`：仅检测指定页面（可单独使用，也可与 `--dry-run` / `--mode` 组合）
- `--mode <fast|balanced|deep>`：覆盖自动规模判断，强制使用对应检测策略
  - `fast`：启发式推断，<50 页场景，每页最多 10 个概念
  - `balanced`：半自动化，50~1000 页场景，每页最多 20 个概念
  - `deep`：完全自动化，>1000 页场景，每页最多 50 个概念
