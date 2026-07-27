#!/usr/bin/env python3
"""
概念检测脚本 — 从页面内容中自动提取概念并更新 concepts_index.json

功能：
- 识别页面中的新概念（使用关键词启发式和 NLP 技术）
- 更新 meta/concepts_index.json
- 维护概念别名和摘要
- 识别概念关联关系
- 基于知识库规模的自动检测策略

规模策略：
- 小于 50 页：启发式推断（快速模式）
- 50-1000 页：半自动化（平衡模式）
- 大于 1000 页：完全自动化（深度模式）

用法:
    # 扫描所有页面，检测并更新概念索引（自动判断策略）
    WIKI_ROOT=/path/to/wiki python detect_concepts.py

    # 仅检查单个页面
    WIKI_ROOT=/path/to/wiki python detect_concepts.py --page "pages/python-asyncio.md"

    # 输出检测到的概念列表（不修改索引）
    WIKI_ROOT=/path/to/wiki python detect_concepts.py --dry-run

    # 强制使用深度模式（忽略规模自动判断）
    WIKI_ROOT=/path/to/wiki python detect_concepts.py --mode deep

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import argparse
import os
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple


from _common import get_wiki_root, resolve_path
from index import load_concepts_index, save_concepts_index


# ============================================================================
# 概念提取规则
# ============================================================================

# 技术概念关键词（启发式）
TECH_CONCEPT_PATTERNS = [
    # 编程语言和框架
    r"\b(?:Python|JavaScript|TypeScript|Java|Go|Rust|C\+\+|Node\.js|React|Vue|Angular|Spring|Django|Flask|FastAPI|Express)\b",
    r"\b(?:async|await|coroutine|generator|promise|future|Promise|Callback|EventLoop)\b",
    r"\b(?:WebSocket|HTTP|REST|API|GraphQL|gRPC|RPC|Microservices)\b",
    r"\b(?:Database|SQL|NoSQL|PostgreSQL|MySQL|MongoDB|Redis|Cassandra|Elasticsearch)\b",
    # 系统和架构
    r"\b(?:Architecture|Pattern|Design|Microservice|Monolithic|Distributed|Cloud|Serverless|Kubernetes|Docker|Container)\b",
    r"\b(?:LoadBalancer|Proxy|Gateway|Firewall|Cache|CDN|Scale|Scalability)\b",
    # 数据处理
    r"\b(?:Data|Pipeline|ETL|Streaming|Batch|Analytics|MachineLearning|ML|AI|DeepLearning|NeuralNetwork)\b",
    # 开发工具和流程
    r"\b(?:Git|CI/CD|DevOps|Testing|Unit|Integration|E2E|Deployment|Release|Agile|Scrum)\b",
    # 性能和安全
    r"\b(?:Performance|Optimization|Latency|Throughput|Security|Authentication|Authorization|Encryption|CORS|XSS|CSRF)\b",
    # 通用技术术语
    r"\b(?:Algorithm|DataStructure|Complexity|O\(n\)|TimeComplexity|SpaceComplexity)\b",
]

# 概念定义模式（例如："[概念]是..."）
CONCEPT_DEFINITION_PATTERNS = [
    r"([A-Z][a-zA-Z\s]+)(?:是一个|属于|指的是|定义为|代表)",
    r"([A-Z][a-zA-Z\s]{4,30})(?:\s+是\s+)",
    r"\*\*([A-Z][a-zA-Z\s]+)\*\*\s+(?:是|定义)",
]

# 常见概念别名映射（用于去重）
ALIAS_NORMALIZATION = {
    "javascript": "JavaScript",
    "typescript": "TypeScript",
    "python async": "Asyncio",
    "asyncio": "Asyncio",
    "micro-service": "Microservice",
    "microservices": "Microservice",
    "machine learning": "Machine Learning",
    "ml": "Machine Learning",
    "deep learning": "Deep Learning",
    "api": "API",
    "http request": "HTTP",
    "websocket": "WebSocket",
    "restful api": "REST API",
}


# ============================================================================
# 规模检测策略
# ============================================================================

DETECTION_MODES = {
    "fast": {
        "threshold": 50,
        "description": "启发式推断 - 小型知识库（<50页）",
        "use_abbreviated_patterns": True,
        "use_recursive_detection": False,
        "max_concepts_per_page": 10,
    },
    "balanced": {
        "threshold": 1000,
        "description": "半自动化 - 中型知识库（50-1000页）",
        "use_abbreviated_patterns": False,
        "use_recursive_detection": True,
        "max_concepts_per_page": 20,
    },
    "deep": {
        "threshold": float("inf"),
        "description": "完全自动化 - 大型知识库（>1000页）",
        "use_abbreviated_patterns": False,
        "use_recursive_detection": True,
        "max_concepts_per_page": 50,
    },
}


def determine_detection_mode(page_count: int = None) -> str:
    """
    根据知识库规模自动确定检测模式

    Args:
        page_count: 页面数量，如果为 None 则自动扫描计算

    Returns:
        检测模式名称：'fast', 'balanced', 或 'deep'
    """
    if page_count is None:
        pages_dir = Path(resolve_path("pages"))
        if pages_dir.exists():
            page_count = len(list(pages_dir.rglob("*.md")))
        else:
            page_count = 0

    if page_count <= 50:
        return "fast"
    elif page_count <= 1000:
        return "balanced"
    else:
        return "deep"


def get_detection_config(mode: str) -> Dict[str, any]:
    """获取指定模式的配置"""
    return DETECTION_MODES.get(mode, DETECTION_MODES["balanced"])


# ============================================================================
# 核心功能
# ============================================================================


def extract_frontmatter(content: str) -> Tuple[Dict[str, str], str]:
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


def normalize_concept_name(name: str) -> str:
    """规范化概念名称"""
    cleaned = name.strip()
    # 移除多余空格
    cleaned = re.sub(r"\s+", " ", cleaned)
    # 应用别名映射
    normalized = ALIAS_NORMALIZATION.get(cleaned.lower(), cleaned)
    # 首字母大写（如果全是小写）
    if normalized.islower():
        normalized = normalized.capitalize()
    return normalized


def extract_concepts_from_page(content: str, frontmatter: Dict[str, str], mode: str = "balanced") -> List[str]:
    """
    从单个页面中提取概念（支持不同检测模式）

    Args:
        content: 页面内容
        frontmatter: frontmatter 数据
        mode: 检测模式（'fast', 'balanced', 'deep'）

    Returns:
        提取到的概念列表
    """
    config = get_detection_config(mode)
    concepts = set()

    # 1. 从 frontmatter 提取 entity_type（如果是概念类型）
    if frontmatter.get("entity_type", "").lower() in ("concept", "pattern", "tool"):
        # 使用页面文件名作为概念名
        # 注意：这里依赖外部传入文件名
        pass

    # 2. 检测概念定义模式
    patterns_to_use = CONCEPT_DEFINITION_PATTERNS
    if config["use_abbreviated_patterns"]:
        # 快速模式只使用最简单的模式
        patterns_to_use = CONCEPT_DEFINITION_PATTERNS[:1]

    for pattern in patterns_to_use:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            cleaned = normalize_concept_name(match)
            if len(cleaned) >= 2:  # 过滤太短的候选
                concepts.add(cleaned)

    # 3. 通过关键词模式提取技术概念
    patterns_to_use = TECH_CONCEPT_PATTERNS
    if config["use_abbreviated_patterns"]:
        # 快速模式只使用核心技术关键词
        patterns_to_use = TECH_CONCEPT_PATTERNS[:3]

    for pattern in patterns_to_use:
        matches = re.findall(pattern, content, re.IGNORECASE)
        for match in matches:
            cleaned = normalize_concept_name(match)
            if len(cleaned) >= 2:
                concepts.add(cleaned)

    # 4. 检测 Markdown 加粗的术语（常见于定义和强调）
    bold_terms = re.findall(r"\*\*([^*]+)\*\*", content)
    for term in bold_terms[:10]:  # 限制检查数量
        cleaned = normalize_concept_name(term)
        if len(cleaned) >= 2:
            concepts.add(cleaned)

    # 5. 检测 [[概念]] 链接格式
    wiki_links = re.findall(r"\[\[([^\]]+)\]\]", content)
    for link in wiki_links[:20]:  # 限制检查数量
        cleaned = normalize_concept_name(link.split("|")[0])
        if len(cleaned) >= 2:
            concepts.add(cleaned)

    # 6. 深度模式：递归检测（识别嵌套概念）
    if config["use_recursive_detection"]:
        # 检测"X 的 Y"模式（子概念）
        sub_concept_patterns = [
            r"([A-Z][a-zA-Z\s]+)\s+(的|of|of\s+the)\s+([A-Z][a-zA-Z\s]+)",
        ]
        for pattern in sub_concept_patterns:
            matches = re.findall(pattern, content, re.IGNORECASE)
            for match in matches:
                for part in [match[0], match[2]]:
                    cleaned = normalize_concept_name(part)
                    if len(cleaned) >= 2:
                        concepts.add(cleaned)

    # 限制每页最大概念数量
    concept_list = sorted(list(concepts))
    if len(concept_list) > config["max_concepts_per_page"]:
        # 按长度排序，优先保留较长的概念（通常更具体）
        concept_list.sort(key=lambda x: len(x), reverse=True)
        concept_list = concept_list[: config["max_concepts_per_page"]]

    return concept_list


def generate_concept_summary(content: str, concept_name: str, max_length: int = 100) -> str:
    """从页面内容中生成概念摘要"""
    # 尝试找到概念定义句（通常在首段）
    paragraphs = content.split("\n\n")
    for para in paragraphs[:3]:  # 检查前三段
        if concept_name in para:
            # 提取包含概念的句子
            sentences = re.split(r"[.!?。！？]", para)
            for sent in sentences:
                if concept_name in sent and len(sent.strip()) > 10:
                    # 截取到 max_length
                    summary = sent.strip()[:max_length]
                    if len(summary) == max_length:
                        summary += "..."
                    return summary

    # 如果没找到定义句，使用首句
    first_sent = re.split(r"[.!?。！？]", paragraphs[0])[0].strip()
    return first_sent[:max_length] if first_sent else ""


def detect_aliases(content: str, concept_name: str) -> List[str]:
    """从内容中检测概念别名（同义词）"""
    aliases = []

    # 常见别名模式："概念（别名）" 或 "概念 (别名)"
    alias_pattern = rf"{re.escape(concept_name)}\s*[(（]([^)））]+)[)）]"
    matches = re.findall(alias_pattern, content)
    aliases.extend(matches)

    # 检测"也叫...""又称..."模式
    also_patterns = [
        rf"{re.escape(concept_name)}(?:也叫|又称|亦称)\s*([^\s,，.。]+)",
        rf"([^\s,，.。]+)(?:也叫|又称|亦称)\s*{re.escape(concept_name)}",
    ]
    for pattern in also_patterns:
        matches = re.findall(pattern, content)
        aliases.extend(matches)

    # 去重并过滤
    unique_aliases = []
    for alias in aliases:
        clean = alias.strip()
        if clean != concept_name and len(clean) >= 2:
            unique_aliases.append(clean)

    return list(set(unique_aliases))


def detect_and_update(page_path: str, dry_run: bool = False, mode: str = "balanced") -> Dict[str, any]:
    """
    检测单个页面中的概念并更新索引

    Args:
        page_path: 页面相对路径
        dry_run: 是否仅检测不更新
        mode: 检测模式（'fast', 'balanced', 'deep'）
    """
    result = {"page": page_path, "mode": mode, "detected_concepts": [], "updated_concepts": [], "skipped": []}

    try:
        # 读取页面内容
        page_file = Path(resolve_path(page_path))
        if not page_file.exists():
            return {"error": f"页面不存在: {page_path}"}

        content = page_file.read_text(encoding="utf-8", errors="replace")
        frontmatter, body = extract_frontmatter(content)

        # 提取概念（使用指定模式）
        detected = extract_concepts_from_page(body, frontmatter, mode)
        result["detected_concepts"] = detected

        if dry_run:
            return result

        # 更新索引
        index = load_concepts_index()
        for concept in detected:
            # 使用页面的实际相对路径（支持子目录），去掉 "pages/" 前缀
            page_rel = str(page_file.relative_to(Path(resolve_path("pages")))).replace("\\", "/")
            concept_path = f"pages/{page_rel}"
            existing = index.get(concept, {})

            # 生成摘要
            summary = generate_concept_summary(body, concept)

            # 检测别名
            # 优先从 frontmatter 读取显式别名，其次从正文检测
            fm_aliases = frontmatter.get("aliases", [])
            if fm_aliases:
                # 显式别名（Agent/用户手动写入 frontmatter）优先级最高
                all_aliases = list(dict.fromkeys(fm_aliases))  # 去重保序
            else:
                # 无显式别名时，从正文自动检测
                detected = detect_aliases(body, concept)
                existing_aliases = existing.get("aliases", [])
                all_aliases = list(set(existing_aliases + detected))

            # 更新或新增
            index[concept] = {"path": concept_path, "aliases": all_aliases, "summary": summary, "article_count": 1}

            if concept not in existing:
                result["updated_concepts"].append(concept)
            else:
                result["skipped"].append(concept)

        # 保存索引
        save_concepts_index(index)

    except Exception as e:
        return {"error": str(e)}

    return result


def scan_all_pages(dry_run: bool = False, mode: str = None) -> Dict[str, any]:
    """
    扫描所有页面并批量更新概念索引

    Args:
        dry_run: 是否仅检测不更新
        mode: 检测模式，如果为 None 则自动判断
    """
    pages_dir = Path(resolve_path("pages"))

    if not pages_dir.exists():
        return {"error": "pages/ 目录不存在"}

    # 自动确定检测模式
    if mode is None:
        page_count = len(list(pages_dir.rglob("*.md")))
        mode = determine_detection_mode(page_count)

    global_result = {
        "total_pages": 0,
        "total_concepts": 0,
        "new_concepts": [],
        "pages_processed": [],
        "mode": mode,
        "mode_description": DETECTION_MODES[mode]["description"],
    }

    index = load_concepts_index()

    for page_file in sorted(pages_dir.rglob("*.md")):
        if "_archived" in str(page_file):
            continue

        page_rel = str(page_file.relative_to(pages_dir)).replace("\\", "/")
        full_path = f"pages/{page_rel}"
        page_result = detect_and_update(full_path, dry_run=dry_run, mode=mode)

        if "error" in page_result:
            print(f"⚠️  {page_rel}: {page_result['error']}")
            continue

        global_result["total_pages"] += 1
        global_result["pages_processed"].append(
            {"page": page_rel, "concepts": page_result.get("detected_concepts", [])}
        )

        # 收集统计
        for concept in page_result.get("detected_concepts", []):
            global_result["total_concepts"] += 1
            if concept not in index:
                global_result["new_concepts"].append(concept)

    return global_result


# ============================================================================
# CLI
# ============================================================================


def main():
    parser = argparse.ArgumentParser(description="概念检测脚本")
    parser.add_argument("--page", help="指定单个页面路径")
    parser.add_argument("--dry-run", action="store_true", help="检测但不修改索引")
    parser.add_argument("--mode", choices=["fast", "balanced", "deep"], help="强制使用指定检测模式（默认自动判断）")
    args = parser.parse_args()

    wiki_root = get_wiki_root()
    print(f"🔍 概念检测 | WIKI_ROOT={wiki_root}\n")

    if args.page:
        # 处理单个页面
        print(f"📄 检测页面: {args.page}")
        result = detect_and_update(args.page, dry_run=args.dry_run, mode="balanced")  # 单页默认使用 balanced

        if "error" in result:
            print(f"❌ {result['error']}")
            sys.exit(1)

        print(f"   检测到 {len(result['detected_concepts'])} 个概念:")
        for concept in result["detected_concepts"]:
            print(f"   - {concept}")

        if not args.dry_run:
            print(f"   更新 {len(result['updated_concepts'])} 个概念")
            print(f"   跳过 {len(result['skipped'])} 个已存在概念")

    else:
        # 扫描所有页面
        print("📁 扫描所有页面...")
        print(" Strategy: determine mode automatically")
        result = scan_all_pages(dry_run=args.dry_run, mode=args.mode)  # 按 args.mode 判断模式（auto=None）

        if "error" in result:
            print(f"❌ {result['error']}")
            sys.exit(1)

        print(f" 📊 Detection mode: {result['mode']} ({result['mode_description']})")
        print(f"   Processed {result['total_pages']} pages")
        print(f"   Detected {result['total_concepts']} concept instances")
        print(f"   Added {len(result['new_concepts'])} new concepts")

        if args.dry_run:
            print("\nNew concepts:")
            for concept in result["new_concepts"]:
                print(f"   - {concept}")
        else:
            print("\n✅ Concepts index updated")

    if not args.dry_run:
        # 重新计算 article_count
        print("\n🔄 重新计算 article_count...")
        sys.path.insert(0, os.path.dirname(__file__))
        try:
            from index import recalc_article_counts, save_concepts_index

            index = recalc_article_counts()
            save_concepts_index(index)
            print("   ✅ article_count 已刷新")
        except ImportError:
            print("   ⚠️  无法刷新 article_count（缺少 index 模块）")


if __name__ == "__main__":
    main()
