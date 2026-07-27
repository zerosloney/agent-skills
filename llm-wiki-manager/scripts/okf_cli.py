#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OKF (Open Knowledge Format) v0.1 CLI — llm-wiki-manager

Google 2026-06 发布的 OKF v0.1 标准管理工具：
  https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md

用法:
  WIKI_ROOT=D:\\wiki python scripts/okf_cli.py check [page_path]
  WIKI_ROOT=D:\\wiki python scripts/okf_cli.py promote <page> <status>
  WIKI_ROOT=D:\\wiki python scripts/okf_cli.py status
  WIKI_ROOT=D:\\wiki python scripts/okf_cli.py history <page>
  WIKI_ROOT=D:\\wiki python scripts/okf_cli.py migrate [--dry-run]
  WIKI_ROOT=D:\\wiki python scripts/okf_cli.py export [--output <dir>] [--dry-run]
  WIKI_ROOT=D:\\wiki python scripts/okf_cli.py graph-export [--output <path>]
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

from datetime import datetime, date, timezone
from pathlib import Path

# 将 scripts/ 加入路径以便导入 _common
_scripts_dir = os.path.dirname(os.path.abspath(__file__))
if _scripts_dir not in sys.path:
    sys.path.insert(0, _scripts_dir)

from _common import get_wiki_root as _get_wiki_root  # noqa: E402

WIKI_ROOT = _get_wiki_root()
PAGES_DIR = Path(WIKI_ROOT) / "pages"

# ═══════════════════════════════════════════════════════════════
# OKF v0.1 字段定义
# ═══════════════════════════════════════════════════════════════

# OKF Required (spec §4.1)
OKF_REQUIRED = {"type"}

# OKF Recommended (spec §4.1, priority order)
OKF_RECOMMENDED = {"title", "description", "resource", "tags", "timestamp"}

# 项目扩展字段（非 OKF 标准，项目内部使用）
OKF_EXTENSIONS = {"status", "confidence", "aliases", "domains", "sources",
                  "provenance", "related_articles", "version_history",
                  "entity_type"}

# 生命周期状态
OKF_STATUSES = {"draft", "review", "published", "archived"}

# 生命周期流转规则
OKF_TRANSITIONS = {
    "draft": ["review", "archived"],
    "review": ["published", "draft", "archived"],
    "published": ["review", "archived"],
    "archived": ["review"],
}

# 旧字段 → 新字段映射（仅用于 migrate）
OLD_TO_NEW = {
    "okf_status": "status",
    "okf_confidence": "confidence",
    "okf_provenance": "provenance",
    "okf_related": "related_articles",
    "okf_version_history": "version_history",
    "okf_created": None,  # 废弃，用 timestamp
    "okf_modified": None,  # 废弃，用 timestamp
    "okf_version": None,  # 废弃
    "okf_tags": None,  # 废弃，合并到 tags
}


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def _import_okf_enhance():
    """惰性导入 okf_enhance 模块。"""
    try:
        sys.path.insert(0, os.path.dirname(__file__))
        import okf_enhance as _mod
        return _mod
    except ImportError:
        return None


def _parse_frontmatter(text: str):
    """解析 frontmatter，返回 (frontmatter_dict, body)。"""
    mod = _import_okf_enhance()
    if mod:
        try:
            return mod.parse_frontmatter(text)
        except Exception:
            pass
    # fallback: 简易解析
    m = re.match(r"^---\s*\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return {}, text
    fm_text = m.group(1)
    body = text[m.end():].lstrip("\n")
    fm = {}
    for line in fm_text.split("\n"):
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


def _build_frontmatter(fm: dict) -> str:
    """序列化 frontmatter 字典为 YAML 文本。"""
    mod = _import_okf_enhance()
    if mod:
        try:
            return mod.build_frontmatter_text(fm)
        except Exception:
            pass
    # fallback 极简序列化
    lines = []
    for k, v in fm.items():
        if v is None or v == "":
            continue
        if isinstance(v, (list, dict)):
            import yaml
            try:
                yaml_str = yaml.dump({k: v}, allow_unicode=True, default_flow_style=False).strip()
                lines.append(yaml_str)
            except Exception:
                lines.append(f"{k}: {v}")
        else:
            lines.append(f"{k}: {v}")
    return "\n".join(lines)


def _load_page(page_path: str):
    """加载页面，返回 (Path, frontmatter, body, original_content)。"""
    page = Path(page_path) if Path(page_path).is_absolute() else PAGES_DIR / page_path
    if not page.exists():
        return None, {}, "", ""
    try:
        content = page.read_text("utf-8")
    except OSError:
        return None, {}, "", ""
    fm, body = _parse_frontmatter(content)
    return page, fm, body, content


def _save_page(page: Path, fm: dict, body: str):
    """保存页面。"""
    fm_text = _build_frontmatter(fm)
    new_content = "---\n" + fm_text + "\n---\n" + body
    page.write_text(new_content, "utf-8")


def _today_str():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _to_serializable(val):
    """将 date/datetime 转为字符串以便 JSON 序列化。"""
    if isinstance(val, (datetime, date)):
        return val.strftime("%Y-%m-%d") if isinstance(val, date) else val.isoformat()
    return val


def _resolve_field(fm: dict, field: str, old_field: str = None):
    """从 frontmatter 读取字段，支持新旧字段名双读。"""
    val = fm.get(field)
    if val is not None and val != "":
        return val
    if old_field:
        old_val = fm.get(old_field)
        if old_val is not None and old_val != "":
            return old_val
    return None


# ═══════════════════════════════════════════════════════════════
# Command: check
# ═══════════════════════════════════════════════════════════════

def cmd_check(page_filter=None):
    """检查页面 OKF 字段完整性。"""
    if page_filter:
        pages_to_check = [page_filter]
    else:
        pages_to_check = [str(p.relative_to(PAGES_DIR))
                          for p in sorted(PAGES_DIR.rglob("*.md"))
                          if "_archived" not in p.parts]

    errors = []
    warnings = []

    for rel in pages_to_check:
        page, fm, body, _ = _load_page(rel)
        if page is None:
            print(f"  [X] 文件不存在: {rel}")
            continue

        # 1. OKF Required field: type
        type_val = _resolve_field(fm, "type", "entity_type")
        if not type_val:
            errors.append(f"  [X] [{rel}] 缺失 OKF 必须字段: type")

        # 2. OKF Recommended fields 缺失警告
        for field in OKF_RECOMMENDED:
            if field not in fm or not fm[field]:
                # timestamp 稍微宽松：检查旧 okf_modified
                if field == "timestamp" and fm.get("okf_modified"):
                    continue
                warnings.append(f"  [⚠️] [{rel}] OKF 推荐字段缺失: {field}")

        # 3. status 合法性（扩展字段检查）
        status = _resolve_field(fm, "status", "okf_status")
        if status and str(status).strip() not in OKF_STATUSES:
            errors.append(f"  [X] [{rel}] status 非法值: '{status}'（应为 {OKF_STATUSES}）")

        # 4. confidence 范围
        conf = _resolve_field(fm, "confidence", "okf_confidence")
        if conf is not None:
            try:
                conf_f = float(conf)
                if not (0.0 <= conf_f <= 1.0):
                    errors.append(f"  [X] [{rel}] confidence 越界: {conf_f}（应为 0.0~1.0）")
            except (ValueError, TypeError):
                errors.append(f"  [X] [{rel}] confidence 非数字: '{conf}'")

        # 5. timestamp 格式检查
        ts = fm.get("timestamp", "")
        if ts:
            if not re.match(r"^\d{4}-\d{2}-\d{2}", str(ts)):
                errors.append(f"  [X] [{rel}] timestamp 日期格式错误: '{ts}'（应为 ISO 8601）")

        # 6. related_articles 引用检查
        related = fm.get("related_articles", fm.get("okf_related", []))
        if isinstance(related, list):
            page_stems = {p.stem for p in PAGES_DIR.rglob("*.md") if "_archived" not in p.parts}
            for item in related:
                if isinstance(item, dict):
                    mid = item.get("id", "").strip()
                    if mid and mid not in page_stems:
                        errors.append(f"  [X] [{rel}] related_articles 引用不存在的页面: '{mid}'")
                elif isinstance(item, str):
                    mid = item.strip().lstrip("pages/")
                    if mid.endswith(".md"):
                        mid = mid[:-3]
                    if mid and mid not in page_stems:
                        errors.append(f"  [X] [{rel}] related_articles 引用不存在的页面: '{item}'")

    # 输出
    if page_filter:
        print(f"[CHK] OKF v0.1 检查: {page_filter}")
    else:
        print(f"[CHK] OKF v0.1 检查: 全部 {len(pages_to_check)} 页")

    if not errors and not warnings:
        print("  [OK] 全部通过")
    else:
        if errors:
            print(f"\n  错误（{len(errors)}）:")
            for e in errors:
                print(e)
        if warnings:
            print(f"\n  警告（{len(warnings)}）:")
            for w in warnings:
                print(w)

    return len(errors) == 0


# ═══════════════════════════════════════════════════════════════
# Command: promote
# ═══════════════════════════════════════════════════════════════

def cmd_promote(page_filter, new_status, dry_run=False):
    """推进页面生命周期状态。"""
    if new_status not in OKF_STATUSES:
        print(f"[X] 非法状态: '{new_status}'（应为 {OKF_STATUSES}）")
        return False

    page, fm, body, _ = _load_page(page_filter)
    if page is None:
        print(f"[X] 文件不存在: {page_filter}")
        return False

    # 双读 status/okf_status
    current_status = _resolve_field(fm, "status", "okf_status")
    current_status = (current_status or "").strip()

    if current_status in OKF_TRANSITIONS:
        allowed = OKF_TRANSITIONS[current_status]
        if new_status not in allowed:
            print(f"[X] 状态流转非法: {current_status} -> {new_status}")
            print(f"   允许的流转: {allowed}")
            return False
    elif current_status:
        print(f"⚠️  当前状态 '{current_status}' 不在已知流转规则中，强制推进")
    else:
        print(f"⚠️  当前无 status 字段，直接设置为 '{new_status}'")

    old_status = current_status
    fm["status"] = new_status
    fm["timestamp"] = _now_iso()

    if not dry_run:
        _save_page(page, fm, body)
        print(f"[OK] [{page_filter}] 状态: {old_status or '(缺失)'} -> {new_status}")
        print(f"   timestamp 更新为 {_today_str()}")
    else:
        print(f"[TEST] 试运行: [{page_filter}] 状态: {old_status or '(缺失)'} -> {new_status}")

    return True


# ═══════════════════════════════════════════════════════════════
# Command: history
# ═══════════════════════════════════════════════════════════════

def cmd_history(page_filter):
    """查看页面版本历史。"""
    page, fm, body, _ = _load_page(page_filter)
    if page is None:
        print(f"[X] 文件不存在: {page_filter}")
        return

    history = fm.get("version_history", fm.get("okf_version_history", []))
    if not history or (isinstance(history, list) and len(history) == 0):
        print(f"[DOC] [{page_filter}] 无版本历史记录")
        print(f"   类型: {fm.get('type', fm.get('entity_type', '(缺失)'))}")
        print(f"   状态: {fm.get('status', fm.get('okf_status', '(缺失)'))}")
        print(f"   时间戳: {fm.get('timestamp', fm.get('okf_modified', '(缺失)'))}")
        return

    print(f"[HIST] [{page_filter}] 版本历史:")
    print()
    print("| 版本 | 日期 | 变更说明 |")
    print("|------|------|----------|")
    for entry in history:
        if isinstance(entry, dict):
            ver = entry.get("version", "?")
            date = entry.get("date", "?")
            changes = entry.get("changes", "")
            print(f"| {ver} | {date} | {changes} |")
        else:
            print(f"| {entry} | | |")


# ═══════════════════════════════════════════════════════════════
# Command: migrate
# ═══════════════════════════════════════════════════════════════

def cmd_migrate(dry_run=False, page_filter=None):
    """批量迁移页面到 OKF v0.1 格式。

    操作：
    1. 添加 type 字段（从 entity_type 派生，或默认 concept）
    2. 添加 timestamp（从文件 mtime 派生）
    3. 迁移旧 okf_* 字段到新无前缀命名
    4. 删除废弃的 okf_* 字段
    5. 合并 okf_tags 到 tags
    """
    if page_filter:
        pages_to_migrate = [page_filter]
    else:
        pages_to_migrate = [str(p.relative_to(PAGES_DIR))
                            for p in sorted(PAGES_DIR.rglob("*.md"))
                            if "_archived" not in p.parts]


    migrated = 0
    skipped = 0

    for rel in pages_to_migrate:
        page, fm, body, _ = _load_page(rel)
        if page is None:
            continue

        changed = False

        # 1. type — OKF 唯一必须字段
        if "type" not in fm or not fm.get("type"):
            # 从 entity_type 派生
            et = fm.get("entity_type", "").strip()
            fm["type"] = et if et else "concept"
            changed = True

        # 2. title — 从文件名派生
        if "title" not in fm or not fm.get("title") or fm.get("title") in ("", "页面标题"):
            fm["title"] = page.stem.replace("-", " ").replace("_", " ").title()
            changed = True

        # 3. timestamp — 从文件 mtime 派生
        if "timestamp" not in fm or not fm.get("timestamp"):
            try:
                mtime = page.stat().st_mtime
                ts = datetime.fromtimestamp(mtime, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except OSError:
                ts = _now_iso()
            fm["timestamp"] = ts
            changed = True

        # 4. tags — 合并 okf_tags
        okf_tags = fm.get("okf_tags", [])
        if okf_tags and "tags" not in fm:
            if isinstance(okf_tags, list):
                fm["tags"] = okf_tags
            else:
                fm["tags"] = [t.strip() for t in str(okf_tags).split(",") if t.strip()]
            changed = True

        # 5. Migrate old fields: okf_status → status, etc.
        for old_key, new_key in OLD_TO_NEW.items():
            if old_key in fm:
                if new_key:
                    # 新字段尚未设置时迁移
                    if new_key not in fm or not fm.get(new_key):
                        fm[new_key] = fm[old_key]
                        changed = True
                    # 删除旧字段
                    if old_key in fm:
                        del fm[old_key]
                        changed = True
                else:
                    # 废弃字段，直接删除
                    del fm[old_key]
                    changed = True

        if changed:
            if not dry_run:
                _save_page(page, fm, body)
            migrated += 1
            print(f"  {'[TEST] [DRY-RUN] ' if dry_run else ''}[OK] [{rel}] 已迁移到 OKF v0.1 (type={fm.get('type')})")
        else:
            skipped += 1

    print(f"\n迁移完成: {migrated} 页迁移, {skipped} 页已满足 OKF v0.1 要求")
    if dry_run:
        print("⚠️  试运行模式，未实际写入文件")


# ═══════════════════════════════════════════════════════════════
# Command: export — 导出 OKF v0.1 规范 Bundle
# ═══════════════════════════════════════════════════════════════

def cmd_export(output_dir=None, dry_run=False):
    """导出 OKF v0.1 规范 Bundle。

    将 pages/ 下的扁平结构导出为 OKF §3 规定的规范 Bundle：
    - 保留原有目录结构（如 pages/subdir/ 成为 bundle 中的子目录）
    - 自动生成 index.md（§6 渐进式披露）
    - 可选生成 log.md（§7 更新日志）
    - 转换 [[WikiLink]] 为 OKF 标准链接（§5 绝对 bundle-相对路径）
    - frontmatter 仅保留 OKF 标准字段 + 项目扩展字段（§4.1）

    Args:
        output_dir: 输出目录。默认在 WIKI_ROOT/okf_export/
        dry_run: 只预览，不写入
    """
    if output_dir is None:
        output_dir = Path(WIKI_ROOT) / "okf_export"
    else:
        output_dir = Path(output_dir)

    pages = sorted(PAGES_DIR.rglob("*.md"))
    pages = [p for p in pages if "_archived" not in p.parts]

    if not pages:
        print("[X] pages/ 目录中没有页面")
        return

    print("  来源追溯:")
    print(f"   来源: {PAGES_DIR}")
    print(f"   目标: {output_dir}")
    print(f"   页面: {len(pages)}")
    print()

    bundle_files = []

    for src in pages:
        rel = src.relative_to(PAGES_DIR)
        dest = output_dir / rel

        try:
            content = src.read_text("utf-8")
        except OSError as e:
            print(f"  ⚠️  无法读取: {rel} — {e}")
            continue

        fm, body = _parse_frontmatter(content)

        # 构建 OKF 标准 frontmatter
        out_fm = {}

        # Required: type
        type_val = _resolve_field(fm, "type", "entity_type")
        if type_val:
            out_fm["type"] = type_val

        # Recommended fields
        title = fm.get("title", "")
        if title:
            out_fm["title"] = title

        desc = fm.get("description", "")
        if desc:
            out_fm["description"] = desc

        resource = fm.get("resource", "")
        if resource:
            out_fm["resource"] = resource

        tags = fm.get("tags", fm.get("okf_tags", []))
        if tags:
            out_fm["tags"] = tags if isinstance(tags, list) else [tags]

        timestamp = fm.get("timestamp", fm.get("okf_modified", ""))
        if timestamp:
            out_fm["timestamp"] = timestamp

        def _convert_wikilink(m):
            target = m.group(1)
            alias = m.group(2)
            # 防止路径穿越
            if ".." in target or target.startswith("/"):
                display = alias if alias else target
                return f"[{display}](#invalid)"
            # 尝试找到实际文件
            target_page = PAGES_DIR / f"{target}.md"
            if target_page.exists():
                target_rel = target_page.relative_to(PAGES_DIR)
                link_target = "/" + str(target_rel).replace("\\", "/")
            else:
                # 在子目录中搜索
                for sp in pages:
                    if sp.stem == target or sp.stem.lower() == target.lower():
                        target_rel = sp.relative_to(PAGES_DIR)
                        link_target = "/" + str(target_rel).replace("\\", "/")
                        break
                else:
                    # 未找到: 用规范化名称构建链接
                    norm_target = target.replace(" ", "-").lower() + ".md"
                    link_target = "/" + norm_target
            display = alias if alias else target
            return f"[{display}]({link_target})"

        body = re.sub(r"\[\[([^\]|#]+)(?:\|([^\]]+))?\]\]", _convert_wikilink, body)

        # 写入导出文件
        if not dry_run:
            dest.parent.mkdir(parents=True, exist_ok=True)
            fm_text = _build_frontmatter(out_fm)
            export_content = "---\n" + fm_text + "\n---\n" + body
            dest.write_text(export_content, "utf-8")

        bundle_files.append(rel)
        print(f"  {'[TEST] ' if dry_run else ''}[OK] /{rel} ({out_fm.get('type', '?')})")

    # 生成 index.md (OKF §6 渐进式披露)
    print()
    index_entries = _build_index_entries(pages)
    if index_entries:
        index_content = "# Knowledge Bundle — OKF v0.1\n\n"
        index_content += "*Auto-generated by llm-wiki-manager*\n\n"
        for heading, items in index_entries:
            index_content += f"## {heading}\n\n"
            for title, path, desc in items:
                desc_text = f" - {desc}" if desc else ""
                index_content += f"* [{title}](/{path}){desc_text}\n"
            index_content += "\n"

        if not dry_run:
            index_path = output_dir / "index.md"
            index_path.parent.mkdir(parents=True, exist_ok=True)
            index_path.write_text(index_content, "utf-8")
        print(f"  {'[TEST] ' if dry_run else ''}[OK] /index.md ({len(pages)} 页)")

    # 生成 log.md (OKF §7 更新日志，含版本声明)
    log_content = "# Directory Update Log\n\n"
    log_content += "<!-- OKF v0.1 Bundle -- " + _today_str() + " -->\n\n"
    log_content += f"## {_today_str()}\n"
    log_content += f"* **Pages**: {len(pages)} concepts exported.\n"

    if not dry_run:
        log_path = output_dir / "log.md"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_content_full = "---\nokf_version: \"0.1\"\n---\n" + log_content
        log_path.write_text(log_content_full, "utf-8")
    print(f"  {'[TEST] ' if dry_run else ''}[OK] /log.md")

    print(f"\n{'[TEST] ' if dry_run else ''}✅ OKF v0.1 Bundle 导出完成 — {len(bundle_files)} 个概念")
    print(f"   输出目录: {output_dir}")


def _build_index_entries(pages):
    """为 index.md 构建按类型分组的条目列表。"""
    from collections import defaultdict

    groups = defaultdict(list)

    for p in pages:
        rel = p.relative_to(PAGES_DIR)
        path_str = str(rel).replace("\\", "/")
        try:
            content = p.read_text("utf-8")
        except OSError:
            continue
        fm, _ = _parse_frontmatter(content)
        type_val = _resolve_field(fm, "type", "entity_type") or "concept"
        title = fm.get("title", p.stem.replace("-", " ").title())
        desc = fm.get("description", "")
        groups[type_val].append((title, path_str, desc))

    # 排序：组内按标题字母序
    result = []
    for type_name in sorted(groups.keys()):
        items = sorted(groups[type_name], key=lambda x: x[0])
        result.append((type_name, items))
    return result


# ═══════════════════════════════════════════════════════════════
# Command: graph-export
# ═══════════════════════════════════════════════════════════════

def cmd_graph_export(output_path=None):
    """导出知识图谱 JSON。"""
    if output_path is None:
        output_path = Path(WIKI_ROOT) / "okf_graph.json"

    pages = sorted(PAGES_DIR.rglob("*.md"))
    pages = [p for p in pages if "_archived" not in p.parts]

    graph = {
        "okf_version": "0.1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "total_pages": len(pages),
        "nodes": [],
        "edges": [],
        "status_distribution": {},
        "confidence_distribution": {"0.0-0.3": 0, "0.3-0.6": 0, "0.6-0.8": 0, "0.8-1.0": 0},
    }

    for p in pages:
        rel = str(p.relative_to(PAGES_DIR))
        _, fm, _, _ = _load_page(str(p))

        # 使用文件路径作为唯一 ID（避免 pages/a-b.md 和 pages/a/b.md 碰撞）
        node = {
            "id": rel.replace(".md", "").replace("\\", "/"),
            "path": rel,
            "type": _to_serializable(_resolve_field(fm, "type", "entity_type") or "unknown"),
            "title": _to_serializable(fm.get("title", p.stem)),
            "description": _to_serializable(fm.get("description", "")),
            "status": _to_serializable(_resolve_field(fm, "status", "okf_status") or "draft"),
            "confidence": float(_resolve_field(fm, "confidence", "okf_confidence") or 0.0),
            "timestamp": _to_serializable(fm.get("timestamp", fm.get("okf_modified", ""))),
            "tags": _to_serializable(fm.get("tags", fm.get("okf_tags", []))),
            "domains": _to_serializable(fm.get("domains", [])),
        }
        graph["nodes"].append(node)

        # 统计
        status = str(node["status"])
        graph["status_distribution"][status] = graph["status_distribution"].get(status, 0) + 1

        conf = node["confidence"]
        if conf < 0.3:
            graph["confidence_distribution"]["0.0-0.3"] += 1
        elif conf < 0.6:
            graph["confidence_distribution"]["0.3-0.6"] += 1
        elif conf < 0.8:
            graph["confidence_distribution"]["0.6-0.8"] += 1
        else:
            graph["confidence_distribution"]["0.8-1.0"] += 1

        # 边：from related_articles
        related = fm.get("related_articles", fm.get("okf_related", []))
        if isinstance(related, list):
            for rel_entry in related:
                if isinstance(rel_entry, dict):
                    edge = {
                        "source": node["id"],
                        "target": rel_entry.get("id", ""),
                        "relation": rel_entry.get("relation", "related"),
                        "note": rel_entry.get("note", ""),
                    }
                    graph["edges"].append(edge)

        # 内链 [[xxx]] 边
        _, fm, body, _ = _load_page(str(p))
        if body:
            link_matches = re.findall(r"\[\[([^\]|#]+)", body)
            existing_targets = set()
            if isinstance(related, list):
                for r in related:
                    if isinstance(r, dict):
                        existing_targets.add(r.get("id", ""))
            for link in link_matches:
                link_clean = link.strip()
                if link_clean not in existing_targets:
                    edge = {
                        "source": node["id"],
                        "target": link_clean,
                        "relation": "related",
                        "note": "内链（未显式标注关系类型）",
                    }
                    graph["edges"].append(edge)

    # 写入
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    Path(output_path).write_text(json.dumps(graph, ensure_ascii=False, indent=2), "utf-8")
    print(f"[OK] OKF 图谱已导出: {output_path}")
    print(f"   节点: {len(graph['nodes'])}  |  边: {len(graph['edges'])}")

    return graph


# ═══════════════════════════════════════════════════════════════
# Command: status
# ═══════════════════════════════════════════════════════════════

def cmd_status():
    """显示全 wiki OKF 统计。"""
    pages = sorted(PAGES_DIR.rglob("*.md"))
    pages = [p for p in pages if "_archived" not in p.parts]

    if not pages:
        print(f"[STS] OKF 统计: WIKI_ROOT={WIKI_ROOT}")
        print("  pages/ 目录为空")
        return

    total = len(pages)
    type_count = {}
    status_count = {}
    confidence_vals = []
    missing_type = 0
    missing_status = 0
    okf_compliant = 0  # 有 type 字段

    for p in pages:
        _, fm, _, _ = _load_page(str(p))

        type_val = _resolve_field(fm, "type", "entity_type")
        if type_val:
            type_count[type_val] = type_count.get(type_val, 0) + 1
            okf_compliant += 1
        else:
            missing_type += 1

        status = _resolve_field(fm, "status", "okf_status")
        if status:
            status_count[status] = status_count.get(status, 0) + 1
        else:
            missing_status += 1

        conf = _resolve_field(fm, "confidence", "okf_confidence")
        if conf:
            try:
                confidence_vals.append(float(conf))
            except (ValueError, TypeError):
                pass

    print(f"[STS] OKF v0.1 统计: WIKI_ROOT={WIKI_ROOT}")
    print(f"      总页面数: {total}")
    print(f"      OKF v0.1 合规: {okf_compliant}/{total}（有 type 字段）")
    if missing_type:
        print(f"      缺少 type 字段: {missing_type} ⚠️")
    print()

    if type_count:
        print("  类型分布:")
        for t, c in sorted(type_count.items(), key=lambda x: -x[1]):
            pct = c / total * 100
            bar = "█" * int(pct / 5) + "░" * (20 - int(pct / 5))
            print(f"    {bar}  {t:<24s}  {c:3d}  ({pct:.0f}%)")
        print()

    if status_count:
        print("  状态分布:")
        for s in ("published", "review", "draft", "archived"):
            c = status_count.get(s, 0)
            if c:
                pct = c / total * 100
                print(f"    {s:<12s}: {c:3d}  ({pct:.0f}%)")
        if missing_status:
            print(f"    (无 status) : {missing_status:3d}")
        print()

    if confidence_vals:
        avg_conf = sum(confidence_vals) / len(confidence_vals)
        print("  置信度统计:")
        print(f"      范围:    {min(confidence_vals):.3f} ~ {max(confidence_vals):.3f}")
        print(f"      平均:    {avg_conf:.3f}")


# ═══════════════════════════════════════════════════════════════
# 主入口
# ═══════════════════════════════════════════════════════════════

USAGE = r"""
OKF (Open Knowledge Format) v0.1 CLI — llm-wiki-manager

用法:
  python scripts/okf_cli.py check [page_path]         检查 OKF 字段完整性
  python scripts/okf_cli.py promote <page> <status>   推进生命周期状态
  python scripts/okf_cli.py history <page>             查看版本历史
  python scripts/okf_cli.py status                     显示全量 OKF 统计
  python scripts/okf_cli.py migrate [--dry-run]        迁移旧 okf_* 字段
  python scripts/okf_cli.py export [--output <dir>]    导出 OKF v0.1 Bundle
                        [--dry-run]
  python scripts/okf_cli.py graph-export [--output <p>] 导出知识图谱 JSON

参数:
  check:    如果指定 page_path，只检查该页面；否则检查全部页面
  promote:  status 值: draft | review | published | archived
  migrate:  --dry-run 仅预览不写入
  export:   --output 指定输出目录（默认 {wiki_root}/okf_export/）
            --dry-run 仅预览
  graph-export:  --output 指定输出路径（默认 {wiki_root}/okf_graph.json）
"""


def main():
    args = sys.argv[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(USAGE)
        return

    cmd = args[0]
    cmd_args = args[1:]

    if cmd == "check":
        page_filter = cmd_args[0] if cmd_args else None
        sys.exit(0 if cmd_check(page_filter) else 1)

    elif cmd == "promote":
        if len(cmd_args) < 2:
            print("用法: python scripts/okf_cli.py promote <page> <status>")
            sys.exit(1)
        page_filter = cmd_args[0]
        new_status = cmd_args[1]
        dry_run = "--dry-run" in cmd_args
        sys.exit(0 if cmd_promote(page_filter, new_status, dry_run) else 1)

    elif cmd == "history":
        if not cmd_args:
            print("用法: python scripts/okf_cli.py history <page>")
            sys.exit(1)
        cmd_history(cmd_args[0])

    elif cmd == "status":
        cmd_status()

    elif cmd == "migrate":
        dry_run = "--dry-run" in cmd_args
        page_filter = None
        for a in cmd_args:
            if not a.startswith("--"):
                page_filter = a
                break
        cmd_migrate(dry_run=dry_run, page_filter=page_filter)

    elif cmd == "export":
        dry_run = "--dry-run" in cmd_args
        output_dir = None
        for i, a in enumerate(cmd_args):
            if a == "--output" and i + 1 < len(cmd_args):
                output_dir = cmd_args[i + 1]
                break
        cmd_export(output_dir=output_dir, dry_run=dry_run)

    elif cmd == "graph-export":
        output_path = None
        for i, a in enumerate(cmd_args):
            if a == "--output" and i + 1 < len(cmd_args):
                output_path = cmd_args[i + 1]
                break
        cmd_graph_export(output_path=output_path)

    else:
        print(f"[X] 未知命令: {cmd}")
        print(USAGE)
        sys.exit(1)


if __name__ == "__main__":
    # Windows 控制台 UTF-8 编码修复
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    main()