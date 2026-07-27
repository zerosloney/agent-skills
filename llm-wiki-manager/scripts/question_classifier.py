#!/usr/bin/env python3
"""
问题分类器 — 零 Token 成本的规则引擎

用途：在 Agent 调用搜索之前，先判断问题类型和复杂度，选择最经济的检索路径。
不依赖任何 LLM 调用，纯规则匹配，零 Token 成本。

用法:
    # 直接调用
    python scripts/question_classifier.py classify "什么是 Redis"

    # 作为模块导入
    from question_classifier import classify
    result = classify("Redis 和 MySQL 的区别")
    print(result["type"], result["action"], result["cost"])
"""

import re
import sys
import json


def classify(question: str) -> dict:
    """
    对用户问题进行零成本分类。

    Args:
        question: 用户原始问题字符串

    Returns:
        dict 包含:
            type: str — meta | entity | compare | relation | synthesis | unknown
            action: str — 推荐的检索动作
            cost: str — low | medium | high
            targets: list[str] — 提取的关键实体名（如有）
            note: str — 给 Agent 的简短建议
    """
    q = question.strip()
    if not q:
        return {
            "type": "unknown",
            "action": "standard_search",
            "cost": "medium",
            "targets": [],
            "note": "空查询，默认标准搜索",
        }

    # === 元问题：直接读 index.md / 索引文件即可，不用搜索 ===
    if _match_any(
        q,
        [
            r"有.*多少.*页",
            r"页面.*数量",
            r"一共.*几.*页",
            r"最近.*更新",
            r"最新.*添加",
            r"知识库.*结构",
            r"目录.*结构",
            r"wiki.*目录",
            r"哪些.*概念",
            r"有哪些.*概念",
            r"总.*([数量])",
            r"统计",
        ],
    ):
        return {
            "type": "meta",
            "action": "read_index",
            "cost": "low",
            "targets": [],
            "note": "直接读 index.md 就够了，不需要搜索",
        }

    # === 综合/趋势问题：需要图摘要 + 多篇全文（优先级高于 entity，防止"发展趋势"被当实体提取） ===
    if _match_any(
        q,
        [
            r"发展趋势",
            r"未来方向",
            r"未来.*趋势",
            r"总结.*领域",
            r"领域.*概述",
            r"全面.*了解",
            r"有哪些.*挑战",
            r"主流.*方案",
            r"如何.*入门",
            r"学习.*路线",
            r"最佳实践",
            r"为什么.*重要",
        ],
    ):
        return {
            "type": "synthesis",
            "action": "graph_summary",
            "cost": "high",
            "targets": [],
            "note": "需要 Level 0 图摘要 + 多篇 Level 2 全文",
        }

    # === 实体问题：Level 1 概念索引足够 ===
    # "什么是XXX" "XXX是什么" "解释XXX" "聊聊XXX"
    m = _extract_entity(
        q,
        [
            r"什么是(.+)",
            r"(.+)是什么",
            r"解释[一下]*(.+)",
            r"聊聊(.+)",
            r"介绍[一下]*(.+)",
            r"说说(.+)",
            r"(.+)怎么[用玩样理解看办]",
        ],
    )
    if m:
        return {
            "type": "entity",
            "targets": [m],
            "action": "level1_concept",
            "cost": "low",
            "note": f"搜索概念 '{m}' 的概念索引即可",
        }

    # === 对比问题：需要两篇全文 ===
    m = _extract_pair(
        q,
        [
            r"(.+?)和(.+?)的?(?:区别|差异|对比|比较|异同)",
            r"(.+?) vs\.?\s*(.+)",
            r"(.+?) VS\.?\s*(.+)",
            r"对比(.+?)和(.+?)",
            r"(.+?)与(.+?)的?(?:异同|比较)",
            r"(.+?)还是(.+?)好",
            r"选(.+?)还是(.+?)",
        ],
    )
    if m:
        return {
            "type": "compare",
            "targets": [m[0], m[1]],
            "action": "level2_two_pages",
            "cost": "high",
            "note": f"需要加载 '{m[0]}' 和 '{m[1]}' 两篇全文进行对比",
        }

    # === 关系问题：需要查图关系 ===
    m = _extract_dependency(
        q,
        [
            r"(.+)依赖(.+)",
            r"(.+)基于(.+)",
            r"(.+)和(.+)的?关系",
            r"(.+)属于(.+)",
            r"(.+)是(.+)的?一部分",
            r"(.+)为(.+)提供",
        ],
    )
    if m:
        return {
            "type": "relation",
            "targets": list(m),
            "action": "graph_lookup",
            "cost": "medium",
            "note": f"需要查图关系: {m[0]} ↔ {m[1]}",
        }

    # === 未知类型：标准三层 ===
    return {
        "type": "unknown",
        "action": "standard_search",
        "cost": "medium",
        "targets": [],
        "note": "标准 Level 1 → Level 2 自动降级",
    }


# ============================================================================
# 内部工具函数
# ============================================================================


def _match_any(text: str, patterns: list[str]) -> bool:
    """检查 text 是否匹配任一正则模式"""
    for p in patterns:
        if re.search(p, text):
            return True
    return False


def _extract_entity(text: str, patterns: list[str]) -> str | None:
    """从 text 中提取单个实体名"""
    for p in patterns:
        m = re.search(p, text)
        if m:
            name = m.group(1).strip()
            # 过滤掉太短或无效的提取
            if len(name) >= 2:
                return name
    return None


def _extract_pair(text: str, patterns: list[str]) -> tuple[str, str] | None:
    """从 text 中提取对比对 (A, B)"""
    for p in patterns:
        m = re.search(p, text)
        if m:
            a = m.group(1).strip()
            b = m.group(2).strip()
            # 清理：去除末尾常见的疑问词/后缀
            b = _trim_trailing_particles(b)
            if len(a) >= 1 and len(b) >= 1:
                return (a, b)
    return None


def _extract_dependency(text: str, patterns: list[str]) -> tuple[str, str] | None:
    """从 text 中提取关系对 (依赖方, 被依赖方)"""
    for p in patterns:
        m = re.search(p, text)
        if m:
            a = m.group(1).strip()
            b = m.group(2).strip()
            b = _trim_trailing_particles(b)
            if len(a) >= 1 and len(b) >= 1:
                return (a, b)
    return None


def _trim_trailing_particles(s: str) -> str:
    """去除末尾疑问词/助词：有什么、怎么、如何、可以、哪些、什么"""
    return re.sub(r"(有什么|怎么|如何|可以|哪些|什么|吗|呢|的)$", "", s).strip()


# ============================================================================
# CLI 入口
# ============================================================================


def cmd_classify(args: list[str]) -> None:
    """CLI: classify <question>"""
    if not args:
        print("用法: python scripts/question_classifier.py classify <问题>")
        sys.exit(1)
    question = " ".join(args)
    result = classify(question)
    print(json.dumps(result, ensure_ascii=False, indent=2))


def main() -> None:
    if len(sys.argv) < 2:
        print("用法: python scripts/question_classifier.py <command> [args...]")
        print()
        print("命令:")
        print("  classify <问题>    分类问题并输出 JSON")
        sys.exit(1)

    cmd = sys.argv[1].lower()
    if cmd == "classify":
        cmd_classify(sys.argv[2:])
    else:
        print(f"未知命令: {cmd}")
        sys.exit(1)


if __name__ == "__main__":
    main()
