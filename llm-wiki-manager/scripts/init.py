#!/usr/bin/env python3
"""LLM Wiki 初始化工具 — 支持 4 种场景模板

用法:
    WIKI_ROOT=/path/to/wiki python init.py
    WIKI_ROOT=/path/to/wiki python init.py --force
    WIKI_ROOT=/path/to/wiki python init.py --template research
    WIKI_ROOT=/path/to/wiki python init.py --template reading
    WIKI_ROOT=/path/to/wiki python init.py --template project

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import sys
from pathlib import Path


from _common import get_wiki_root as _get_wiki_root

WIKI_ROOT = _get_wiki_root()

MARKERS = {
    ".ai-knowledge": "",  # 空文件标记此为知识库目录
}

# ── purpose.md 模板（按场景） ──

PURPOSE_GENERAL = """# 知识库目标

## 核心问题
- 我想积累和检索什么知识？
- 目标读者：未来的我 / 团队成员

## 研究范围
- 涵盖领域：（按实际填写）
- 明确不涵盖：（防止膨胀）

## 演进论点
- 当前最想验证的假设：
- 季度审视日期：
"""

PURPOSE_RESEARCH = """# 研究目标

## 核心问题
- 我的研究方向是什么？
- 核心论文/理论是什么？
- 目标读者：同行研究者

## 研究范围
- 核心领域：
- 子领域：
- 交叉学科：
- 明确不涵盖：

## 演进论点
- 研究假设（可被证伪）：
- 实验验证计划：
- 当前阶段：文献调研 / 实验 / 写作

## 关键指标
- 论文阅读量：___
- 笔记转化率：___
- 发表计划：
"""

PURPOSE_READING = """# 阅读目标

## 核心问题
- 我为什么要读书？（研究方向 / 技能提升 / 兴趣）
- 目标读者：未来的我

## 阅读范围
- 核心领域：
- 关注的作者/信息源：
- 明确不读：（什么书不浪费时间）

## 笔记标准
- 每本书至少提取 3 个可执行洞察
- Counter-Arguments：同一主题 3+ 本书时自动触发

## 阅读进度
- 当前在读：
- 待读队列：
- 今年已读：
"""

PURPOSE_PROJECT = """# 项目知识库目标

## 项目定义
- 项目名称：
- 一句话描述：
- 关键决策者/干系人：

## 核心问题
- 这个项目要解决什么问题？
- 目标读者：团队成员 / 新加入者 / 未来的维护者

## 文档范围
- 架构设计
- 技术决策（ADR）
- 运维手册
- 常见问题
- 明确不涵盖：业务知识（另行维护）

## 演进
- 当前阶段：设计 / 开发 / 维护
- 关键里程碑：
"""

PURPOSE_TEMPLATES = {
    "general": PURPOSE_GENERAL,
    "research": PURPOSE_RESEARCH,
    "reading": PURPOSE_READING,
    "project": PURPOSE_PROJECT,
}

# ── KNOWLEDGE.md 模板 ──

KNOWLEDGE_TEMPLATE = """# 📚 知识库 — {title}

> 这是一个 LLM Wiki 管理的个人知识库。
> 本文件是**机器可读的说明**，任何 AI 工具读取后可自动识别并使用本知识库。

---

## 目录结构

| 目录/文件 | 用途 | 说明 |
|-----------|------|------|
| `pages/` | 知识页面 | 标准 Markdown，按主题/领域分类 |
| `_archived/` | 已归档页面 | 永不删除，不被索引/搜索/lint 涉及 |
| `raw/` | 原始素材 | 只读不修改 |
| `schema/` | 模板与规范 | 页面模板与维护约定 |
| `meta/` | 元数据索引 | 概念索引、源文件追溯、文件名重名检测 |
| `graph/` | 知识图谱 | 全局图谱摘要（Level 0 查询入口） |
| `references/` | 参考文档 | 编译流程、更新规范、实体类型 |
| `outputs/` | 输出目录 | 问答暂存、lint 报告 |
| `purpose.md` | 知识库灵魂 | 目标、范围、演进方向 |
| `index.md` | 导航首页 | 按分区组织，知识地图 |
| `.ai-knowledge` | 标记文件 | AI 工具扫描到此文件即知为知识库目录 |

## AI 工具使用指南

> ⚠️ **注意**：以下命令中的 `scripts/` 路径相对于**本项目的 skill 目录**（即 LLM Wiki 管理器项目根目录），而非本知识库目录。
> 实际使用时，请将 `scripts/xxx.py` 替换为完整路径或保持当前工作目录为 skill 目录，同时设置 `WIKI_ROOT` 环境变量指向本知识库目录。
> 示例：`WIKI_ROOT=D:\\wiki python D:\\llm-wiki-manager\\scripts\\search_engine.py query "关键词" --level 1`

### 搜索知识
1. 先读 `index.md` 了解分区结构
2. 三层查询（推荐）：`python scripts/search_engine.py query "关键词" --level 1`
3. 传统搜索：`python scripts/search.py "关键词"`

### 写入知识
1. 将原始素材放入 `raw/`
2. 按 `schema/page-template.md` 格式在 `pages/` 下创建 .md 文件
3. 建立交叉链接 `[[页面名]]`
4. 更新 `index.md`
5. 大中型 wiki 运行 `search.py --rebuild`

### 概念管理
1. 添加概念：`python scripts/index.py concepts-add "概念名" --path "pages/xxx.md"`
2. 查看概念：`python scripts/index.py concepts-show`
3. 匹配概念：`python scripts/index.py concepts-match "关键词"`

详见 `schema/rules.md`。
"""

WIKI_REF_TEMPLATE = """# wiki-ref

本项目关联的知识库位于：
{wiki_root}

AI 工具应首先读取 {wiki_root}/KNOWLEDGE.md 了解知识库结构和使用方法。
"""

INDEX_TEMPLATE = """# {title}

> 本知识库导航首页

## 分区

### 专业
<!-- 专业知识，按领域分子目录 -->

### 通用
<!-- 通用知识、方法论、工具 -->

### 待分类
<!-- 尚未分类的知识 -->

## 最近更新
<!-- 自动维护 -->
"""

PAGE_TEMPLATE = """# [页面标题]

> [一句话摘要]
> 标签：`标签1` `标签2`

---

## 概述
[核心定义和背景]

## 详细信息
[详细内容]

## 相关页面
<!-- [[相关页面]] — 关联说明 -->

## 来源
<!-- 来源说明 -->
"""

RULES_TEMPLATE = """# 知识库维护规范

## 内容规范
1. 所有页面必须使用 page-template.md 格式
2. 页面之间必须建立交叉链接
3. 每个页面至少包含一个来源引用

## 分区规范
1. 专业：专业知识、框架、算法、架构
2. 通用：通用知识、方法论、工具
3. 待分类：临时存放，定期整理

## 命名规范
1. 页面文件名使用英文 + 连字符，如 `python-asyncio.md`
2. 标签使用小写英文缩写或中文关键词
"""


def ensure_dirs() -> None:
    """创建 wiki 目录结构"""
    dirs = [
        "raw",
        "pages",
        "schema",
        "_archived",
        "outputs/queries",  # 问答暂存（promote 前）
        "outputs/reports",  # lint 报告存档
        ".cache",  # SHA256 增量缓存
        "meta",  # 元数据索引（v1.2）
        "graph",  # 知识图谱（v1.2）
        "references",  # 参考文档
    ]
    for d in dirs:
        path = Path(WIKI_ROOT) / d
        path.mkdir(parents=True, exist_ok=True)
        print(f"  ✅ 创建目录: {d}/")


def generate_files(template: str, force_mode: bool = False) -> None:
    """生成核心文档、模板与标记文件"""
    wiki_name = Path(WIKI_ROOT).name

    # 基础文件
    files: dict[str, str] = {
        "index.md": INDEX_TEMPLATE.format(title=wiki_name),
        "schema/page-template.md": PAGE_TEMPLATE,
        "schema/rules.md": RULES_TEMPLATE,
        "purpose.md": PURPOSE_TEMPLATES.get(template, PURPOSE_GENERAL),
    }

    # 标记文件（供外部工具识别）
    marker_files: dict[str, str] = {
        ".ai-knowledge": MARKERS[".ai-knowledge"],
        "KNOWLEDGE.md": KNOWLEDGE_TEMPLATE.format(title=wiki_name),
        ".wiki-ref": WIKI_REF_TEMPLATE.format(wiki_root=WIKI_ROOT),
    }
    files.update(marker_files)

    for rel_path, content in files.items():
        file_path = Path(WIKI_ROOT) / rel_path
        if file_path.exists() and not force_mode:
            print(f"  ⏭️  已存在，跳过: {rel_path}")
            continue
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(content, encoding="utf-8")
        if file_path.exists() and force_mode:
            print(f"  🔄 已覆盖: {rel_path}")
        else:
            print(f"  ✅ 创建文件: {rel_path}")


def init_meta() -> None:
    """初始化 meta/ 目录的 JSON 索引文件（v1.2）"""
    import json

    meta_files = {
        "meta/concepts_index.json": {},  # 概念索引
        "meta/source_map.json": {},  # 源文件追溯
        "meta/filename_index.json": {},  # 文件名重名检测
    }

    for rel_path, content in meta_files.items():
        file_path = Path(WIKI_ROOT) / rel_path
        if file_path.exists():
            print(f"  ⏭️  已存在，跳过: {rel_path}")
            continue
        file_path.write_text(json.dumps(content, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  ✅ 创建文件: {rel_path}")

    # graph/GRAPH_SUMMARY.md 初始模板
    graph_summary_path = Path(WIKI_ROOT) / "graph" / "GRAPH_SUMMARY.md"
    if not graph_summary_path.exists():
        summary_content = """# 知识图谱摘要

> 本文件由 LLM 定期生成，用于 Level 0 查询。

## 核心概念

<!-- 列出 Top 20 核心概念及其关系 -->

## 关键洞察

<!-- LLM 从知识库中提取的洞察 -->

## 知识缺口

<!-- 发现的薄弱区域 -->
"""
        graph_summary_path.write_text(summary_content, encoding="utf-8")
        print("  ✅ 创建文件: graph/GRAPH_SUMMARY.md")


def main() -> None:
    force_mode = "--force" in sys.argv or "-f" in sys.argv

    # 解析模板参数
    template = "general"
    if "--template" in sys.argv:
        idx = sys.argv.index("--template")
        if idx + 1 < len(sys.argv):
            t = sys.argv[idx + 1].lower()
            if t in PURPOSE_TEMPLATES:
                template = t
            else:
                valid = ", ".join(PURPOSE_TEMPLATES.keys())
                print(f"  ⚠️  未知模板 '{t}'，可选: {valid}")
                print("  使用默认 general 模板")

    print(f"🏗️  初始化知识库 | wiki_root: {WIKI_ROOT} | template: {template}\n")

    is_nonempty = Path(WIKI_ROOT).exists() and list(Path(WIKI_ROOT).iterdir())

    if is_nonempty:
        if force_mode:
            print("  ⚠️  目标目录非空，--force 已指定，继续执行")
        elif sys.stdin.isatty():
            response = input("  ❓ 目标目录非空，确认继续？(y/N): ").strip().lower()
            if response != "y":
                print("  ❌ 取消")
                sys.exit(0)
        else:
            print("  ❌ 目标目录非空且非交互模式，请使用 --force 参数强制继续")
            sys.exit(1)

    ensure_dirs()
    generate_files(template, force_mode)
    init_meta()
    print("\n✅ 初始化完成")


if __name__ == "__main__":
    main()
