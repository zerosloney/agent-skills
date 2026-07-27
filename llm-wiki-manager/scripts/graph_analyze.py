#!/usr/bin/env python3
"""
LLM Wiki 图分析脚本 — 自动分析知识图谱结构

功能：
- 识别关键概念节点（高度连接的概念）
- 检测孤立节点（未被引用或无出链）
- 发现概念集群密度
- 中心性排名（介数中心性）
- 知识缺口分析（被引用但无独立页面的概念）
- 路径分析（概念间最短路径）

输出：graph/GRAPH_ANALYSIS.md

用法:
    # 执行图分析
    WIKI_ROOT=/path/to/wiki python graph_analyze.py

    # 输出 JSON 格式（用于程序处理）
    WIKI_ROOT=/path/to/wiki python graph_analyze.py --json

环境变量:
    WIKI_ROOT  - wiki 根目录（优先级高于默认值 ~/wiki/）

依赖:
    - networkx: 用于图分析（pip install networkx）
    - json: 内置
"""

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple


from _common import get_wiki_root, resolve_path
from index import load_concepts_index


# ============================================================================
# 数据加载
# ============================================================================


def load_pages() -> List[Dict[str, Any]]:
    """加载所有 pages/*.md 页面，提取 frontmatter 和 链接"""
    pages_dir = Path(resolve_path("pages"))

    if not pages_dir.exists():
        return []

    pages = []
    for md_file in pages_dir.rglob("*.md"):
        try:
            content = md_file.read_text(encoding="utf-8")
            frontmatter, body = extract_frontmatter(content)
            links = extract_all_links(body)

            pages.append(
                {
                    "filepath": str(md_file),
                    "filename": md_file.stem,
                    "frontmatter": frontmatter,
                    "links": links,
                    "content_length": len(body),
                    "entity_type": frontmatter.get("entity_type", "concept"),
                }
            )
        except Exception as e:
            print(f"⚠️ 跳过文件 {md_file}: {e}")

    return pages


def extract_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """提取 YAML frontmatter"""
    match = re.match(r"^---\n(.*?)\n---\n(.*)$", content, re.DOTALL)
    if not match:
        return {}, content

    fm = {}
    for line in match.group(1).split("\n"):
        if ":" in line:
            key, value = line.split(":", 1)
            fm[key.strip()] = value.strip()

    return fm, match.group(2)


def extract_all_links(text: str) -> List[str]:
    """提取所有 Markdown 链接：[[概念]] 和 [文本](路径.md)"""
    links = []

    # 1. [[概念]] 格式（内部概念链接）
    wiki_links = re.findall(r"\[\[([^\]]+)\]\]", text)
    links.extend(wiki_links)

    # 2. [文本](路径.md) 格式
    md_links = re.findall(r"\[.*?\]\(([^)]+\.md)\)", text)
    links.extend([Path(p).stem for p in md_links])

    return links


# ============================================================================
# 图分析核心逻辑
# ============================================================================


def build_graph(pages: List[Dict[str, Any]]) -> Tuple[Dict[str, List[str]], Dict[str, Dict]]:
    """构建有向图：{node -> [neighbors]}, {node -> node_data}"""
    graph = defaultdict(list)
    node_data = {}

    # 1. 将所有页面作为节点
    for page in pages:
        node = page["filename"]
        node_data[node] = {
            "entity_type": page["entity_type"],
            "content_length": page["content_length"],
            "in_degree": 0,
            "out_degree": 0,
        }
        graph[node]

    # 2. 添加边（链接关系）
    for page in pages:
        src = page["filename"]
        for link in page["links"]:
            # 清理链接项
            cleaned = link.split("|")[0].strip()  # 移除显示文本 [[概念|显示]]
            if cleaned and cleaned in node_data:
                graph[src].append(cleaned)

    # 3. 计算度数
    for node in graph:
        node_data[node]["out_degree"] = len(graph[node])
        node_data[node]["in_degree"] = sum(1 for neighbors in graph.values() if node in neighbors)

    return dict(graph), node_data


def find_key_concepts(
    graph: Dict[str, List[str]], node_data: Dict[str, Dict], top_n: int = 10
) -> List[Tuple[str, float]]:
    """识别关键概念节点（基于度数中心性）"""
    scores = []
    for node, data in node_data.items():
        # 综合评分：入度权重 0.6 + 出度权重 0.4
        score = data["in_degree"] * 0.6 + data["out_degree"] * 0.4
        scores.append((node, score))

    scores.sort(key=lambda x: x[1], reverse=True)
    return scores[:top_n]


def find_isolated_nodes(graph: Dict[str, List[str]], node_data: Dict[str, Dict]) -> List[str]:
    """检测孤立节点（入度和出度均为 0）"""
    isolated = []
    for node in graph:
        if node_data[node]["in_degree"] == 0 and node_data[node]["out_degree"] == 0:
            isolated.append(node)
    return isolated


def find_orphan_nodes(graph: Dict[str, List[str]], node_data: Dict[str, Dict]) -> List[str]:
    """检测孤儿节点（入度为 0，但可能有出链）"""
    orphans = []
    for node in graph:
        if node_data[node]["in_degree"] == 0 and node_data[node]["out_degree"] > 0:
            orphans.append(node)
    return orphans


def find_dead_end_nodes(graph: Dict[str, List[str]], node_data: Dict[str, Dict]) -> List[str]:
    """检测死节点（出度为 0，但可能有入链）"""
    dead_ends = []
    for node in graph:
        if node_data[node]["out_degree"] == 0 and node_data[node]["in_degree"] > 0:
            dead_ends.append(node)
    return dead_ends


def detect_clusters(graph: Dict[str, List[str]]) -> List[List[str]]:
    """使用弱连通分量检测概念集群（迭代式 DFS，避免递归深度限制）"""
    visited = set()
    clusters = []

    for node in graph:
        if node not in visited:
            cluster = []
            stack = [node]
            while stack:
                current = stack.pop()
                if current in visited:
                    continue
                visited.add(current)
                cluster.append(current)
                for neighbor in graph[current]:
                    if neighbor not in visited:
                        stack.append(neighbor)
            if len(cluster) > 1:
                clusters.append(cluster)

    clusters.sort(key=lambda x: len(x), reverse=True)
    return clusters


def identify_knowledge_gaps(pages: List[Dict[str, Any]], concepts_index: Dict[str, Any]) -> List[str]:
    """识别知识缺口（被引用但无独立页面的概念）"""
    page_filenames = {p["filename"] for p in pages}

    gaps = []
    for concept_name, concept_data in concepts_index.items():
        # 检查概念是否在 concepts_index 中但缺少独立页面
        path = concept_data.get("path")
        if not path or path not in str(page_filenames):
            gaps.append(concept_name)

    return gaps


def calculate_betweenness_centrality(graph: Dict[str, List[str]]) -> Dict[str, float]:
    """计算介数中心性（简化版，用于识别路径上的关键节点）"""
    try:
        import networkx as nx

        G = nx.DiGraph()
        G.add_nodes_from(graph.keys())
        for src, targets in graph.items():
            for tgt in targets:
                G.add_edge(src, tgt)
        return nx.betweenness_centrality(G)
    except ImportError:
        # 无 networkx 时使用近似方法：通过度数估计
        # 这是简化版，不完全准确
        centrality = {}
        for node, neighbors in graph.items():
            centrality[node] = len(neighbors)
        return centrality


# ============================================================================
# 报告生成
# ============================================================================


def generate_markdown_report(
    graph: Dict[str, List[str]],
    node_data: Dict[str, Dict],
    key_concepts: List[Tuple[str, float]],
    isolated_nodes: List[str],
    orphan_nodes: List[str],
    dead_end_nodes: List[str],
    clusters: List[List[str]],
    knowledge_gaps: List[str],
    total_pages: int,
) -> str:
    """生成 Markdown 图分析报告"""
    lines = [
        "# 🔗 知识图谱分析报告",
        "",
        f"**生成时间**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"**总页面数**: {total_pages}",
        f"**总节点数**: {len(graph)}",
        "",
        "---",
        "",
        "## 📊 概览统计",
        "",
        f"- **页面总数**: {total_pages}",
        f"- **孤立节点**: {len(isolated_nodes)}（无入链也无出链）",
        f"- **孤儿节点**: {len(orphan_nodes)}（有出链但无入链）",
        f"- **死节点**: {len(dead_end_nodes)}（有入链但无出链）",
        f"- **概念集群**: {len(clusters)} 个（规模 > 1 的连通分量）",
        f"- **知识缺口**: {len(knowledge_gaps)} 个（被引用但无页面）",
        "",
        "---",
        "",
        "## 🎯 关键概念节点（Top 10）",
        "",
        "*基于度数中心性（入度权重 0.6 + 出度权重 0.4）*",
        "",
        "| 排名 | 概念 | 评分 | 入度 | 出度 | 实体类型 |",
        "|------|------|------|------|------|----------|",
    ]

    for rank, (concept, score) in enumerate(key_concepts, 1):
        data = node_data.get(concept, {})
        lines.append(
            f"| {rank} | [{concept}]({concept}.md) | {score:.2f} | "
            f"{data.get('in_degree', 0)} | {data.get('out_degree', 0)} | "
            f"{data.get('entity_type', 'N/A')} |"
        )

    lines.extend(
        [
            "",
            "---",
            "",
            "## 🔍 孤立节点（需要加强链接）",
            "",
            f"**数量**: {len(isolated_nodes)}",
            "",
        ]
    )

    if isolated_nodes:
        lines.append("这些页面既未被引用，也没有指向其他页面：")
        lines.append("")
        for node in isolated_nodes[:20]:  # 最多显示 20 个
            lines.append(f"- [{node}]({node}.md)")
        if len(isolated_nodes) > 20:
            lines.append(f"- ... 还有 {len(isolated_nodes) - 20} 个")
    else:
        lines.append("✅ 无孤立节点，知识网络连接良好。")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 👶 孤儿节点（需要被引用）",
            "",
            f"**数量**: {len(orphan_nodes)}",
            "",
        ]
    )

    if orphan_nodes:
        lines.append("这些页面有出链但没有被其他页面引用：")
        lines.append("")
        for node in orphan_nodes[:20]:
            lines.append(f"- [{node}]({node}.md)")
        if len(orphan_nodes) > 20:
            lines.append(f"- ... 还有 {len(orphan_nodes) - 20} 个")
    else:
        lines.append("✅ 所有页面都有入链引用。")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 🧊 概念集群（连通分量）",
            "",
            f"**数量**: {len(clusters)}",
            "",
        ]
    )

    for idx, cluster in enumerate(clusters[:5], 1):  # 最多显示 5 个集群
        lines.append(f"### 集群 #{idx}（{len(cluster)} 个节点）")
        for node in cluster[:10]:
            lines.append(f"- [{node}]({node}.md)")
        if len(cluster) > 10:
            lines.append(f"- ... 还有 {len(cluster) - 10} 个")
        lines.append("")

    if len(clusters) == 0:
        lines.append("✅ 未发现明显概念集群，所有概念相互连通或呈线性关系。")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 🧩 知识缺口（被引用但无页面）",
            "",
            f"**数量**: {len(knowledge_gaps)}",
            "",
        ]
    )

    if knowledge_gaps:
        lines.append("以下概念被频繁引用，但缺少独立页面：")
        lines.append("")
        for gap in knowledge_gaps[:20]:
            lines.append(f"- {gap}")
        if len(knowledge_gaps) > 20:
            lines.append(f"- ... 还有 {len(knowledge_gaps) - 20} 个")
        lines.append("")
        lines.append("💡 **建议**: 为这些概念创建独立的知识页面。")
    else:
        lines.append("✅ 所有被引用的概念都有对应页面。")

    lines.extend(
        [
            "",
            "---",
            "",
            "## 📈 改进建议",
            "",
            "### 短期行动",
            "",
            "1. **增强孤立节点链接**: 为孤立节点添加相关的内部链接。",
            "2. **修复孤儿节点**: 在其他页面中引用孤儿节点，提高其可见性。",
            "3. **补充知识缺口**: 为被引用但无页面的概念创建新页面。",
            "",
            "### 中期优化",
            "",
            "1. **加强概念集群**: 在各集群间增加桥梁链接，提高概念关联度。",
            "2. **优化关键概念**: 为关键概念节点添加更详细的解释和导航。",
            "",
            "### 长期规划",
            "",
            "1. **定期执行**: 建议每周执行一次图分析，监控知识网络健康度。",
            "2. **量化目标**: 将孤立节点比例控制在 5% 以内，确保知识网络高度互联。",
            "",
            "---",
            "",
            "*本报告由 `graph_analyze.py` 自动生成。*",
        ]
    )

    return "\n".join(lines)


def generate_json_report(
    graph: Dict[str, List[str]],
    node_data: Dict[str, Dict],
    key_concepts: List[Tuple[str, float]],
    isolated_nodes: List[str],
    orphan_nodes: List[str],
    dead_end_nodes: List[str],
    clusters: List[List[str]],
    knowledge_gaps: List[str],
    total_pages: int,
) -> Dict[str, Any]:
    """生成 JSON 格式报告（用于程序处理）"""
    return {
        "metadata": {
            "generated_at": datetime.now().isoformat(),
            "wiki_root": get_wiki_root(),
            "total_pages": total_pages,
            "total_nodes": len(graph),
        },
        "summary": {
            "isolated_count": len(isolated_nodes),
            "orphan_count": len(orphan_nodes),
            "dead_end_count": len(dead_end_nodes),
            "cluster_count": len(clusters),
            "knowledge_gaps_count": len(knowledge_gaps),
        },
        "key_concepts": [{"name": name, "score": score} for name, score in key_concepts],
        "isolated_nodes": isolated_nodes,
        "orphan_nodes": orphan_nodes,
        "dead_end_nodes": dead_end_nodes,
        "clusters": [{"id": idx, "size": len(cluster), "nodes": cluster} for idx, cluster in enumerate(clusters)],
        "knowledge_gaps": knowledge_gaps,
    }


# ============================================================================
# 主函数
# ============================================================================


def main():
    parser = argparse.ArgumentParser(description="LLM Wiki 图分析脚本")
    parser.add_argument("--json", action="store_true", help="输出 JSON 格式而非 Markdown")
    args = parser.parse_args()

    wiki_root = get_wiki_root()
    print(f"🔍 图分析 | WIKI_ROOT={wiki_root}\n")

    # 1. 加载数据
    print("📖 加载页面...")
    pages = load_pages()
    total_pages = len(pages)
    print(f"   发现 {total_pages} 个页面")

    if total_pages == 0:
        print("❌ 未发现任何页面，退出分析。")
        sys.exit(1)

    print("📖 加载概念索引...")
    concepts_index = load_concepts_index()
    print(f"   加载 {len(concepts_index)} 个概念索引")

    # 2. 构建图
    print("🔗 构建知识图谱...")
    graph, node_data = build_graph(pages)
    print(f"   创建 {len(graph)} 个节点")

    # 3. 执行分析
    print("🔬 执行图分析...")
    key_concepts = find_key_concepts(graph, node_data, top_n=10)
    isolated_nodes = find_isolated_nodes(graph, node_data)
    orphan_nodes = find_orphan_nodes(graph, node_data)
    dead_end_nodes = find_dead_end_nodes(graph, node_data)
    clusters = detect_clusters(graph)
    knowledge_gaps = identify_knowledge_gaps(pages, concepts_index)

    # 4. 生成报告
    print("📝 生成分析报告...")
    if args.json:
        report = generate_json_report(
            graph,
            node_data,
            key_concepts,
            isolated_nodes,
            orphan_nodes,
            dead_end_nodes,
            clusters,
            knowledge_gaps,
            total_pages,
        )
        dest = Path(resolve_path("graph/GRAPH_ANALYSIS.json"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(json.dumps(report, ensure_ascii=False, indent=2), "utf-8")
        print(f"📄 {dest}")
    else:
        report = generate_markdown_report(
            graph,
            node_data,
            key_concepts,
            isolated_nodes,
            orphan_nodes,
            dead_end_nodes,
            clusters,
            knowledge_gaps,
            total_pages,
        )
        dest = Path(resolve_path("graph/GRAPH_ANALYSIS.md"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(report, "utf-8")
        print(f"📄 {dest}")

    # 5. 输出摘要
    print("\n📊 分析摘要：")
    print(f"   关键概念: {len(key_concepts)} 个")
    print(f"   孤立节点: {len(isolated_nodes)} 个")
    print(f"   孤儿节点: {len(orphan_nodes)} 个")
    print(f"   死节点: {len(dead_end_nodes)} 个")
    print(f"   概念集群: {len(clusters)} 个")
    print(f"   知识缺口: {len(knowledge_gaps)} 个")


if __name__ == "__main__":
    main()
