#!/usr/bin/env python3
"""
Entity Type 验证 — 检查页面合规性

检查项：
1. entity_type frontmatter 是否在 12 种实体类型内（6基础+6扩展）
2. 必需章节是否完整（按 entity_type 判断）
3. frontmatter 格式是否正确

用法:
    WIKI_ROOT=<path> python scripts/validate_entities.py            # 检查所有页面
    WIKI_ROOT=<path> python scripts/validate_entities.py --fix      # 自动修复小问题
    WIKI_ROOT=<path> python scripts/validate_entities.py --page <path>  # 检查单个页面

环境变量:
    WIKI_ROOT  - wiki 根目录（默认 ~/wiki/）
"""

import os
import sys
from pathlib import Path
from typing import Dict, List, Tuple

from _common import get_wiki_root as _get_wiki_root


# 必需章节（所有类型）
REQUIRED_ALL = ["相关页面", "来源"]


def _load_entity_schema() -> tuple[dict, set]:
    """从 schema/entity-types.yaml 动态加载实体类型定义"""
    schema_path = Path(__file__).parent.parent / "schema" / "entity-types.yaml"
    if not schema_path.exists():
        return {}, set()
    try:
        import yaml

        data = yaml.safe_load(schema_path.read_text("utf-8")) or {}
    except (ImportError, yaml.YAMLError):
        return {}, set()

    all_types = {}
    for type_name, type_info in data.get("base_types", {}).items():
        all_types[type_name] = type_info.get("require_sections", [])
    for ext in data.get("extensions", []):
        type_name = ext.get("type")
        if type_name:
            all_types[type_name] = ext.get("require_sections", [])

    valid_types = set(all_types.keys())
    return all_types, valid_types


STANDARD_TYPES, VALID_ENTITY_TYPES = _load_entity_schema()


WIKI_ROOT = _get_wiki_root()
PAGES_DIR = os.path.join(WIKI_ROOT, "pages")


def _parse_frontmatter(content: str) -> Dict:
    """解析 YAML frontmatter"""
    if not content.startswith("---"):
        return {}

    end = content.find("\n---", 3)
    if end < 0:
        return {}

    fm_str = content[3:end]
    frontmatter = {}

    try:
        import yaml

        frontmatter = yaml.safe_load(fm_str) or {}
    except ImportError:
        # 无yaml时手动解析简单case
        for line in fm_str.split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and value:
                    frontmatter[key] = value
    except yaml.YAMLError:
        # frontmatter 格式异常，忽略
        pass

    return frontmatter


def _extract_sections(content: str) -> List[str]:
    """提取所有二级标题（## 开头）"""
    sections = []
    for line in content.split("\n"):
        if line.strip().startswith("##"):
            section_name = line.strip()[2:].strip()
            # 移除标题层级标记（如 ### → ##）
            if section_name.startswith("#"):
                section_name = section_name.lstrip("#").strip()
            sections.append(section_name)
    return sections


def _check_page(page_path: Path, auto_fix: bool = False) -> Tuple[bool, List[str], List[str]]:
    """
    检查单个页面的合规性。

    Returns:
        (is_valid, warnings, errors)
    """
    warnings: List[str] = []
    errors: List[str] = []

    try:
        content = page_path.read_text("utf-8", errors="replace")
    except OSError:
        return False, [], ["无法读取文件"]

    # 1. 检查 frontmatter
    frontmatter = _parse_frontmatter(content)

    if not frontmatter:
        # 无frontmatter，尝试添加默认frontmatter
        if auto_fix:
            default_type = "concept"
            new_fm = f"---\nentity_type: {default_type}\nconfidence: medium\ndomains: []\n---\n\n{content}"
            page_path.write_text(new_fm, "utf-8")
            warnings.append(f"已自动添加默认frontmatter（entity_type: {default_type}）")
        else:
            errors.append("缺少 frontmatter")
        return len(errors) == 0, warnings, errors

    # 2. 检查 entity_type
    entity_type = frontmatter.get("entity_type", "").strip()
    if not entity_type:
        errors.append("frontmatter 缺少 entity_type 字段")
        return False, warnings, errors

    # 3. 检查必需章节（提前提取 sections，供 auto_fix 使用）
    sections = _extract_sections(content)

    if entity_type not in VALID_ENTITY_TYPES:
        errors.append(f"无效的 entity_type: '{entity_type}'，有效值: {', '.join(sorted(VALID_ENTITY_TYPES))}")
        if auto_fix:
            # 尝试猜测类型
            guess = _guess_entity_type(content, sections)
            if guess:
                errors.append(f"建议改为: entity_type: {guess}")
    required = STANDARD_TYPES.get(entity_type, []) + REQUIRED_ALL

    missing_sections = []
    for req in required:
        if req not in sections:
            missing_sections.append(req)

    if missing_sections:
        errors.append(f"缺少必需章节: {', '.join(missing_sections)}")
        if auto_fix:
            # 自动添加缺失章节（仅模板）
            warnings.append(f"建议添加章节: {', '.join(missing_sections)}")

    # 4. 检查 frontmatter 其他字段
    if "confidence" not in frontmatter:
        warnings.append("frontmatter 缺少 confidence 字段")
        if auto_fix:
            frontmatter["confidence"] = "medium"
            errors.append("已自动添加 confidence: medium")

    if "domains" not in frontmatter:
        warnings.append("frontmatter 缺少 domains 字段")
        if auto_fix:
            frontmatter["domains"] = []
            errors.append("已自动添加 domains: []")

    # 自动修复frontmatter
    if auto_fix and (warnings or errors):
        _update_frontmatter(page_path, frontmatter)

    return len(errors) == 0, warnings, errors


def _guess_entity_type(content: str, sections: List[str]) -> str | None:
    """根据内容猜测实体类型（与 schema/entity-types.yaml 对齐）"""
    content_lower = content.lower()

    # 扩展类型（优先匹配）
    if "对比" in content or "vs" in content_lower or "比较" in content:
        return "comparison"
    if any(kw in content_lower for kw in ["决策", "选型", "取舍"]):
        return "decision-record"
    if any(kw in content_lower for kw in ["排查", "故障", "troubleshoot"]):
        return "troubleshooting"
    if any(kw in content_lower for kw in ["速查", "cheatsheet", "备忘"]):
        return "cheat-sheet"
    if any(kw in content_lower for kw in ["综述", "调研", "survey"]):
        return "survey"
    if any(kw in content_lower for kw in ["规范", "标准", "standard"]):
        return "standard"

    # 基础类型
    if any(kw in content_lower for kw in ["教程", "入门", "指南", "how to"]):
        return "tutorial"
    if any(kw in content_lower for kw in ["api", "参考", "reference"]):
        return "reference"
    if any(kw in content_lower for kw in ["案例", "实战", "case study"]):
        return "case-study"
    if any(kw in content_lower for kw in ["观点", "评论", "opinion"]):
        return "opinion"
    if any(kw in content_lower for kw in ["实现", "原理", "内部", "架构"]):
        return "implementation-detail"

    return "concept"


def _update_frontmatter(page_path: Path, new_frontmatter: Dict) -> None:
    """更新页面的 frontmatter"""
    try:
        content = page_path.read_text("utf-8", errors="replace")
    except OSError:
        return

    # 重建 frontmatter
    import yaml

    new_fm_str = yaml.dump(new_frontmatter, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # 替换或添加frontmatter
    if content.startswith("---"):
        end = content.find("\n---", 3)
        if end >= 0:
            # 替换现有frontmatter
            new_content = f"---\n{new_fm_str}{content[end:]}"
        else:
            # 格式异常，追加
            new_content = f"---\n{new_fm_str}---\n\n{content}"
    else:
        # 添加新frontmatter
        new_content = f"---\n{new_fm_str}---\n\n{content}"

    try:
        page_path.write_text(new_content, "utf-8")
    except OSError:
        pass


def check_all(auto_fix: bool = False) -> None:
    """检查所有页面"""
    pages_path = Path(PAGES_DIR)
    if not pages_path.exists():
        print("  ❌ pages/ 目录不存在")
        return

    pages = sorted(pages_path.rglob("*.md"))
    pages = [p for p in pages if "_archived" not in p.parts]

    if not pages:
        print("  📭 pages/ 目录为空")
        return

    print(f"🔍 检查实体类型合规性 | 共 {len(pages)} 个页面\n")

    valid_count = 0
    warning_count = 0
    error_count = 0

    for page in pages:
        rel_path = str(page.relative_to(pages_path)).replace("\\", "/")
        is_valid, warnings, errors = _check_page(page, auto_fix)

        if is_valid and not warnings:
            valid_count += 1
        else:
            line = f"  {'✅' if is_valid else '❌'} {rel_path}"
            if warnings:
                line += f"  ⚠️  {', '.join(warnings)}"
                warning_count += len(warnings)
            if errors:
                line += f"  ❌ {', '.join(errors)}"
                error_count += len(errors)
            print(line)

    print("\n📊 总结:")
    print(f"  ✅ 合规: {valid_count}/{len(pages)}")
    print(f"  ⚠️  警告: {warning_count}")
    print(f"  ❌ 错误: {error_count}")

    if error_count > 0 and auto_fix:
        print("\n💡 已自动修复部分问题，请重新运行检查确认")


def check_single(page_path: str, auto_fix: bool = False) -> None:
    """检查单个页面"""
    page = Path(page_path)
    if not page.exists():
        print(f"  ❌ 文件不存在: {page_path}")
        sys.exit(1)

    is_valid, warnings, errors = _check_page(page, auto_fix)

    print(f"📄 检查页面: {page.name}\n")

    if is_valid:
        print("  ✅ 页面合规")
    else:
        print("  ❌ 页面不合规")

    if warnings:
        print(f"\n  ⚠️  警告 ({len(warnings)}):")
        for w in warnings:
            print(f"    - {w}")

    if errors:
        print(f"\n  ❌ 错误 ({len(errors)}):")
        for e in errors:
            print(f"    - {e}")


# ── 主入口 ──


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n用法:")
        print("  python validate_entities.py                    # 检查所有页面")
        print("  python validate_entities.py --fix              # 自动修复问题")
        print("  python validate_entities.py --page <path>      # 检查单个页面")
        sys.exit(1)

    auto_fix = "--fix" in sys.argv

    if "--page" in sys.argv:
        idx = sys.argv.index("--page")
        if idx + 1 < len(sys.argv):
            check_single(sys.argv[idx + 1], auto_fix)
        else:
            print("  ❌ 请指定页面路径")
            sys.exit(1)
    else:
        check_all(auto_fix)


if __name__ == "__main__":
    main()
