#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKF (Open Knowledge Format) v0.1 字段增强工具 — llm-wiki-manager

用途：在编译后处理（compile_post.py）中调用，自动填充缺失的 OKF v0.1 标准字段：
  - type: 从 entity_type 派生（或反之），OKF v0.1 唯一必须字段
  - title: 从文件名派生
  - description: 从正文首段提取
  - timestamp: ISO 8601 最后修改时间
  - tags: 确保存在

同时维护项目扩展字段（非 OKF 标准，但项目内部使用）：
  - status: 生命周期状态 draft|review|published|archived
  - confidence: 置信度 0.0-1.0
  - provenance.sha256: 关联缓存哈希

向后兼容：保留旧的 okf_* 字段，同时写入新的无前缀字段。

用法:
  python scripts/okf_enhance.py <page_path> [--dry-run]
  python scripts/okf_enhance.py pages/my-page.md
  python scripts/okf_enhance.py pages/my-page.md --dry-run

被 compile_post.py 自动调用，无需手动执行。
"""

import json
import os
import re
import sys

# Windows console UTF-8 支持
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

import yaml
from datetime import datetime, timezone
from pathlib import Path


def _get_wiki_root():
    """从环境变量或 .wiki_root 文件获取 wiki 根目录。"""
    env_root = os.environ.get("WIKI_ROOT", "").strip()
    if env_root:
        return env_root
    wiki_root_file = Path.cwd() / ".wiki_root"
    if wiki_root_file.exists():
        return wiki_root_file.read_text("utf-8").strip()
    return str(Path.home() / "wiki")


WIKI_ROOT = _get_wiki_root()
CACHE_FILE = Path(WIKI_ROOT) / ".cache" / "sources.json"


# --- 旧字段名 → 新字段名 映射 ---
FIELD_MIGRATION = {
    "okf_status": "status",
    "okf_confidence": "confidence",
    "okf_provenance": "provenance",
    "okf_related": "related_articles",
    "okf_version_history": "version_history",
}
# 废弃的 okf_* 字段（不再使用，不写入）
DEPRECATED_FIELDS = {"okf_version", "okf_created", "okf_modified", "okf_tags"}


def load_cache():
    """加载 .cache/sources.json 哈希缓存。"""
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text("utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return {}


def parse_frontmatter(content: str):
    """解析 YAML frontmatter，返回 (frontmatter_dict, body)。

    支持两种分隔符：--- (OKF 标准) 和 +++ (Obsidian 兼容)。
    兼容 old okf_* 字段名称。

    返回:
        fm: dict — 合并了新字段名和旧字段名的字典
        body: str — 正文文本
    """
    # 非破坏性解析：读取原始 frontmatter 文本
    # 用于判断 YAML 格式是否正确
    fm = {}
    body = content
    raw_fm_text = ""

    # 尝试标准 --- 分隔符
    m = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if m:
        raw_fm_text = m.group(1)
        body = content[m.end():].lstrip("\n")
    else:
        # 尝试 +++ 分隔符
        m = re.match(r"^\+\+\+\s*\n(.*?)\n\+\+\+", content, re.DOTALL)
        if m:
            raw_fm_text = m.group(1)
            body = content[m.end():].lstrip("\n")

    if not raw_fm_text:
        return fm, body

    # YAML 解析
    try:
        parsed = yaml.safe_load(raw_fm_text)
        if isinstance(parsed, dict):
            fm = parsed
    except yaml.YAMLError:
        pass

    # 如果 YAML 解析失败，尝试简易行解析
    if not fm:
        for line in raw_fm_text.split("\n"):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                continue
            key, _, val = stripped.partition(":")
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if val and val != "None" and val != "null":
                fm[key] = val

    return fm, body


def build_frontmatter_text(fm: dict) -> str:
    """将 frontmatter 字典转回 YAML 文本。支持嵌套对象和嵌套列表。

    手动序列化以避免 PyYAML 对中文字符的转义问题。
    """
    lines = []

    def _serialize_value(val, indent=0):
        prefix = " " * indent
        if val is None or val == "":
            return f"{prefix}"
        if isinstance(val, bool):
            return f"{prefix}{str(val).lower()}"
        if isinstance(val, (int, float)):
            return f"{prefix}{val}"
        if isinstance(val, str):
            # 多行字符串
            if "\n" in val:
                return f"{prefix}|-\n" + "\n".join(f"  {line}" for line in val.split("\n"))
            # 需要引号的字符串
            if any(c in val for c in ":[]{}'\","):
                return f'{prefix}"{val}"'
            return f"{prefix}{val}"
        if isinstance(val, list):
            if not val:
                return f"{prefix}[]"
            # 简单类型列表：内联
            if all(isinstance(v, (str, int, float, bool)) for v in val) and len(val) <= 8:
                items = []
                for v in val:
                    if isinstance(v, str):
                        items.append(f'"{v}"' if " " in v else v)
                    else:
                        items.append(str(v).lower() if isinstance(v, bool) else str(v))
                return f"{prefix}[{', '.join(items)}]"
            # 复杂列表：分行
            result_lines = []
            for v in val:
                if isinstance(v, dict):
                    result_lines.append(f"{prefix}-")
                    for k, vv in v.items():
                        if vv is None or vv == "":
                            continue
                        sub = _serialize_value(vv, indent + 2)
                        result_lines.append(f"  {k}: {sub.strip()}")
                else:
                    result_lines.append(f"{prefix}- {_serialize_value(v, indent + 2).strip()}")
            return "\n".join(result_lines)
        if isinstance(val, dict):
            if not val:
                return f"{prefix}{{}}"
            result_lines = []
            for k, vv in val.items():
                if vv is None or vv == "":
                    continue
                sub = _serialize_value(vv, indent + 2)
                result_lines.append(f"{prefix}{k}: {sub.strip()}")
            return "\n".join(result_lines)
        return f"{prefix}{str(val)}"

    for key, val in fm.items():
        if val is None or val == "":
            continue
        serialized = _serialize_value(val)
        if "\n" in serialized:
            # 多行值：键后直接换行
            lines.append(f"{key}:")
            for sub_line in serialized.split("\n"):
                lines.append(sub_line)
        else:
            lines.append(f"{key}: {serialized.strip()}")

    return "\n".join(lines)


def estimate_confidence(sources: list, has_counter_arguments: bool = False) -> float:
    """根据 okf-schema.yaml 的置信度估算规则计算置信度。"""
    count = get_source_count(sources)

    if count >= 3 and has_counter_arguments:
        # 3+ 来源 + Counter-Arguments: [0.85, 1.0] 中值
        return round(0.92, 2)
    if count >= 3:
        # 3+ 来源: [0.85, 1.0] 下界
        return round(0.88, 2)
    if count >= 2:
        # 2-3 来源: [0.75, 0.9] 中值
        return round(0.82, 2)
    # 单一来源: [0.6, 0.75] 中值
    return round(0.68, 2)


def get_source_count(sources) -> int:
    """计算来源数量。"""
    if not sources:
        return 0
    if isinstance(sources, (list, tuple)):
        return len(sources)
    if isinstance(sources, str):
        return 1 if sources.strip() else 0
    return 0


def get_current_date() -> str:
    """获取当前日期 ISO 8601 字符串。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_file_mtime(page_path: Path) -> str:
    """获取文件最后修改时间（ISO 8601 完整格式）。"""
    try:
        mtime = page_path.stat().st_mtime
        return datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except OSError:
        return get_current_date()


def get_sha256_from_cache(page_rel_path: str, cache: dict) -> str:
    """从缓存中获取文件的 SHA256。"""
    for key, val in cache.items():
        if isinstance(val, dict):
            if val.get("path", "") == page_rel_path:
                return str(key)[:12]
        elif isinstance(val, str):
            return str(val)[:12]
    return ""


def check_has_counter_arguments(body: str) -> bool:
    """检查页面内容是否包含 Counter-Arguments 区块。"""
    return "## ⚖️ Counter-Arguments" in body or "## Counter-Arguments" in body


def _derive_title(fm, page: Path) -> str:
    """从 frontmatter 或文件名派生 title。"""
    # 1. 已有 title
    title = fm.get("title", "").strip()
    if title and title != "页面标题":
        return title

    # 2. 从 filename
    return page.stem.replace("-", " ").replace("_", " ").title()


def _derive_type(fm) -> str:
    """从 frontmatter 派生 OKF type 字段。"""
    # 1. 已有 type
    t = fm.get("type", "").strip()
    if t:
        return t

    # 2. 从 entity_type
    et = fm.get("entity_type", "").strip()
    if et:
        return et

    # 3. 从旧 okf_type
    ot = fm.get("okf_type", "").strip()
    if ot:
        return ot

    # 4. 默认
    return "concept"


def _derive_description(fm, body: str) -> str:
    """从 frontmatter 或正文首段派生 description。"""
    desc = fm.get("description", "").strip()
    if desc and desc != "单句摘要":
        return desc

    # 从正文提取：找第一个有意义的段落
    if body:
        # 去掉 frontmatter-like 行
        clean = body.strip()
        # 找第一个非标题、非空行的文本段落
        paragraphs = re.split(r"\n\s*\n", clean)
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            if para.startswith("#"):
                continue
            if para.startswith("---") or para.startswith("+++"):
                continue
            # 取前 200 字符
            desc = para[:200].replace("\n", " ").strip()
            if desc and len(desc) > 10:
                return desc
    return ""


def _derive_tags(fm) -> list:
    """从 frontmatter 派生 tags（合并 tags 和旧 okf_tags）。"""
    tags = []

    # 从 okf_tags（旧字段）合并
    old_tags = fm.get("okf_tags", [])
    if isinstance(old_tags, list):
        for t in old_tags:
            if t and t not in tags:
                tags.append(t)
    elif isinstance(old_tags, str) and old_tags.strip():
        for t in old_tags.split(","):
            t = t.strip().strip('"').strip("[]")
            if t and t not in tags:
                tags.append(t)

    # 从 tags（OKF 标准字段）合并
    current_tags = fm.get("tags", [])
    if isinstance(current_tags, list):
        for t in current_tags:
            if t and t not in tags:
                tags.append(t)
    elif isinstance(current_tags, str) and current_tags.strip():
        for t in current_tags.split(","):
            t = t.strip().strip('"').strip("[]")
            if t and t not in tags:
                tags.append(t)

    return tags


def _ensure_field(fm, key: str, default):
    """如果字段缺失或为占位符，填充默认值。"""
    val = fm.get(key)
    if val is None or val == "" or (isinstance(val, str) and val in ("", "YYYY-MM-DD", "页面标题", "单句摘要")):
        return default
    return val


def enhance_page(page_path: str, dry_run: bool = False, migrate_old_fields: bool = False) -> dict:
    """对单个页面执行 OKF 增强。返回增强信息字典。

    增强操作：
    1. type: 从 entity_type 派生（或反之），OKF 唯一必须字段
    2. title: 从文件名派生
    3. description: 从正文首段提取
    4. timestamp: ISO 8601 最后修改时间
    5. tags: 合并 tags 和旧 okf_tags，确保存在
    6. status: 若缺失，默认 draft
    7. confidence: 根据来源数量自动估算
    8. provenance.sha256: 关联缓存中的哈希

    Args:
        page_path: 页面路径（相对 WIKI_ROOT 或绝对路径）
        dry_run: 只输出不写入
        migrate_old_fields: 迁移旧的 okf_* 字段到新名称
    """
    page = Path(page_path)
    if not page.is_absolute():
        page = Path(WIKI_ROOT) / page

    if not page.exists():
        return {"error": f"文件不存在: {page_path}"}

    content = page.read_text("utf-8", errors="replace")
    fm, body = parse_frontmatter(content)

    if not fm:
        return {"error": "无法解析 frontmatter，页面可能不包含 YAML 头部"}

    enhanced = {}
    new_fm = dict(fm)

    # 如果是旧格式且指定迁移：读取旧 okf_* 字段
    if migrate_old_fields:
        for old_key, new_key in FIELD_MIGRATION.items():
            if old_key in fm and new_key not in fm:
                new_fm[new_key] = fm[old_key]
                enhanced[new_key] = f"从 {old_key} 迁移"
        # 删除废弃字段
        for old_key in DEPRECATED_FIELDS:
            if old_key in new_fm:
                enhanced[f"_{old_key}_removed"] = f"已移除废弃字段 {old_key}"

    # ════════════════════════════════════════════════════════════
    # OKF v0.1 Required: type
    # ════════════════════════════════════════════════════════════
    okf_type = _derive_type(fm)
    new_fm["type"] = okf_type
    if "entity_type" not in new_fm or not new_fm.get("entity_type"):
        new_fm["entity_type"] = okf_type  # 保持别名同步
    elif "type" not in fm or not fm.get("type"):
        # entity_type 已存在但 type 缺失，从 entity_type 同步
        new_fm["type"] = new_fm.get("entity_type", okf_type)
    enhanced["type"] = okf_type

    # ════════════════════════════════════════════════════════════
    # OKF v0.1 Recommended: title
    # ════════════════════════════════════════════════════════════
    title = _derive_title(fm, page)
    if title != fm.get("title", "").strip():
        new_fm["title"] = title
        enhanced["title"] = title

    # ════════════════════════════════════════════════════════════
    # OKF v0.1 Recommended: description
    # ════════════════════════════════════════════════════════════
    description = _derive_description(fm, body)
    if description:
        new_fm["description"] = description
        if "description" not in fm or not fm.get("description") or fm.get("description") == "单句摘要":
            enhanced["description"] = f"从正文提取: {description[:60]}..."
        else:
            enhanced["description"] = f"已保留 ({len(description)} 字符)"

    # ════════════════════════════════════════════════════════════
    # OKF v0.1 Recommended: timestamp
    # ════════════════════════════════════════════════════════════
    if not fm.get("timestamp"):
        timestamp = get_file_mtime(page)
        new_fm["timestamp"] = timestamp
        enhanced["timestamp"] = timestamp
    else:
        enhanced["timestamp"] = f"已保留: {fm['timestamp']}"

    # ════════════════════════════════════════════════════════════
    # OKF v0.1 Recommended: tags
    # ════════════════════════════════════════════════════════════
    tags = _derive_tags(fm)
    if tags:
        new_fm["tags"] = tags
        if "tags" not in fm or not fm.get("tags"):
            enhanced["tags"] = tags
    # 如果 okf_tags 存在，迁移到 tags 后删除
    if "okf_tags" in new_fm and "tags" in new_fm:
        del new_fm["okf_tags"]
        enhanced["_okf_tags_merged"] = "已合并到 tags"

    # ════════════════════════════════════════════════════════════
    # Project Extension: status
    # ════════════════════════════════════════════════════════════
    status = _ensure_field(fm, "status", "draft")
    # 也尝试从 okf_status 读取（向后兼容）
    if status == "draft" and not fm.get("status"):
        old_status = fm.get("okf_status", "").strip()
        if old_status in ("draft", "review", "published", "archived"):
            status = old_status
    new_fm["status"] = status
    if "status" not in fm or not fm.get("status"):
        enhanced["status"] = f"自动设置为 {status}"
    else:
        enhanced["status"] = status

    # ════════════════════════════════════════════════════════════
    # Project Extension: confidence
    # ════════════════════════════════════════════════════════════
    sources = fm.get("sources", [])
    has_ca = check_has_counter_arguments(body)
    confidence = estimate_confidence(sources, has_ca)
    # 如果已有旧 okf_confidence，优先保留
    old_conf = fm.get("okf_confidence")
    if old_conf is not None:
        try:
            old_conf_f = float(old_conf)
            if 0.0 <= old_conf_f <= 1.0:
                confidence = old_conf_f
        except (ValueError, TypeError):
            pass
    new_fm["confidence"] = confidence
    enhanced["confidence"] = confidence
    enhanced["_confidence_reason"] = f"来源数量={get_source_count(sources)}, Counter-Arguments={'有' if has_ca else '无'}"

    # ════════════════════════════════════════════════════════════
    # Project Extension: provenance.sha256
    # ════════════════════════════════════════════════════════════
    cache = load_cache()
    try:
        page_rel = page.relative_to(Path(WIKI_ROOT))
    except ValueError:
        page_rel = page.name
    sha = get_sha256_from_cache(str(page_rel), cache)
    # 读取旧 okf_provenance 或新 provenance
    existing_prov = fm.get("provenance", {})
    if not existing_prov:
        existing_prov = fm.get("okf_provenance", {})
    if isinstance(existing_prov, dict):
        if "provenance" not in new_fm:
            new_fm["provenance"] = dict(existing_prov)
        if isinstance(new_fm["provenance"], dict) and sha:
            new_fm["provenance"]["sha256"] = sha
        # 已迁移到 provenance，删除旧字段
        if "okf_provenance" in new_fm:
            del new_fm["okf_provenance"]
    else:
        # 旧格式字符串，迁移
        new_fm["provenance"] = {"original_source": str(existing_prov) if existing_prov else "", "sha256": sha}
        if "okf_provenance" in new_fm:
            del new_fm["okf_provenance"]

    enhanced["provenance_sha256"] = sha if sha else "(未找到缓存)"

    # ════════════════════════════════════════════════════════════
    # Project Extension: related_articles（从 okf_related 迁移）
    # ════════════════════════════════════════════════════════════
    okf_related = fm.get("okf_related", [])
    related_articles = fm.get("related_articles", [])
    if okf_related and not related_articles:
        new_fm["related_articles"] = okf_related
        enhanced["related_articles"] = f"从 okf_related 迁移 ({len(okf_related)} 项)"
        del new_fm["okf_related"]
    elif related_articles:
        enhanced["related_articles"] = f"已保留 ({len(related_articles)} 项)"

    # 标注 [[链接]] 检测
    if not related_articles and not okf_related:
        link_pattern = re.compile(r'\[\[(\w[\w\s\-/]+)\]\]')
        links = link_pattern.findall(body)
        if links:
            enhanced["_wikilinks_detected"] = f"检测到 {len(links)} 个内链（未自动生成 related_articles，需人工确认关系类型）"

    # ════════════════════════════════════════════════════════════
    # 清理空的废弃字段
    # ════════════════════════════════════════════════════════════
    for old_key in list(new_fm.keys()):
        if old_key in DEPRECATED_FIELDS:
            del new_fm[old_key]
            enhanced[f"_{old_key}_removed"] = "已移除废弃字段"

    # ════════════════════════════════════════════════════════════
    # 写入文件
    # ════════════════════════════════════════════════════════════
    if not dry_run:
        fm_text = build_frontmatter_text(new_fm)
        new_content = "---\n" + fm_text + "\n---\n" + body
        page.write_text(new_content, "utf-8")

    return {"page": str(page), "enhanced": enhanced}


def main():
    dry_run = "--dry-run" in sys.argv
    migrate = "--migrate" in sys.argv
    page_filter = None

    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        page_filter = args[0]

    if not page_filter:
        print("用法: python scripts/okf_enhance.py <page_path> [--dry-run] [--migrate]")
        print(f"  wiki_root: {WIKI_ROOT}")
        sys.exit(1)

    print(f"🔧 OKF v0.1 增强 | page: {page_filter} | wiki_root: {WIKI_ROOT}")
    if dry_run:
        print("  🧪 试运行模式（不实际写入）")
    if migrate:
        print("  🔄 迁移模式（自动转换旧 okf_* 字段到新命名）")
    print()

    result = enhance_page(page_filter, dry_run=dry_run, migrate_old_fields=migrate)

    if "error" in result:
        print(f"  ❌ {result['error']}")
        sys.exit(1)

    print("  ✅ OKF 增强完成")
    for key, val in result["enhanced"].items():
        if key.startswith("_"):
            continue
        print(f"    {key}: {val}")

    if dry_run:
        print("  ⚠️  试运行 — 未写入文件")


if __name__ == "__main__":
    main()