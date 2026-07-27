#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
LLM Wiki 搜索引擎 — FTS5 + 三层查询 + Concept Aliases

 三层查询架构（Token 优化）：
- Level 0: GRAPH_SUMMARY（全局图谱摘要，~500 tokens）
- Level 1: concepts_index + matched concepts（概念索引 + 首段，~1.5K tokens）
- Level 2: Full article body（完整文章体，按需加载，~3K tokens）

用法:
    # 方式1：通过环境变量指定 wiki 根目录
    WIKI_ROOT=/path/to/wiki python search_engine.py rebuild
    WIKI_ROOT=/path/to/wiki python search_engine.py search "关键词"
    WIKI_ROOT=/path/to/wiki python search_engine.py query "什么是延迟队列?" --level 1

    # 方式2：直接使用默认路径（~/wiki/）
    python search_engine.py rebuild

环境变量:
    WIKI_ROOT  - wiki 根目录（优先级高于默认值 ~/wiki/）

脚本位置:
    位于技能目录 scripts/ 中，不复制到 wiki 目录。
"""

import json
import os
import re
import sqlite3
import sys

# Windows console UTF-8 支持
try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass

from datetime import datetime, timezone
from pathlib import Path

from _common import file_hash, get_wiki_root, resolve_path

# 确保 scripts/ 在 sys.path 中（从非 scripts/ 目录调用时也能导入 index）
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# jieba 延迟加载（仅 rebuild/search 时需要）
_jieba = None
# ═══════════════════════════════════════════════════════════════
# OKF v0.1 字段定义
# ═══════════════════════════════════════════════════════════════
OKF_STATUS_FIELD = "status"
OKF_CONFIDENCE_FIELD = "confidence"
OKF_PUBLISHED_STATUS = "published"

def _get_jieba():
    global _jieba
    if _jieba is None:
        import jieba as _j

        _j.setLogLevel(_j.logging.INFO)
        _jieba = _j
    return _jieba


def _tokenize_for_fts5(text: str) -> str:
    """jieba 分词 + 保留非 CJK 原文，空格连接供 FTS5 unicode61 消费。"""
    parts = []
    for segment in re.split(r"([\u4e00-\u9fff]+)", text):
        if re.match(r"[\u4e00-\u9fff]+", segment):
            parts.extend(_get_jieba().lcut(segment))
        elif segment.strip():
            parts.append(segment)
    return " ".join(parts)


# ============================================================================
# 核心配置 — 必须通过环境变量获取路径，禁止硬编码
# ============================================================================


# 路径常量
WIKI_ROOT = get_wiki_root()
RAW_DIR = resolve_path("raw")
PAGES_DIR = resolve_path("pages")
SCHEMA_DIR = resolve_path("schema")
META_DIR = resolve_path("meta")
INDEX_PATH = resolve_path("index.md")
LOG_PATH = resolve_path("log.md")
SEARCH_INDEX_PATH = resolve_path("search_index.db")
GRAPH_SUMMARY_PATH = resolve_path("graph/GRAPH_SUMMARY.md")
CONCEPTS_INDEX_PATH = resolve_path("meta/concepts_index.json")


def ensure_dirs():
    """确保目录存在"""
    for path in [RAW_DIR, PAGES_DIR, SCHEMA_DIR, META_DIR]:
        Path(path).mkdir(parents=True, exist_ok=True)


def get_db() -> sqlite3.Connection:
    """获取数据库连接"""
    db_path = SEARCH_INDEX_PATH
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


# ============================================================================
# 三层查询支持
# ============================================================================


def load_level0_summary() -> str:
    """Level 0: 加载全局图谱摘要"""
    path = Path(GRAPH_SUMMARY_PATH)
    if path.exists():
        return path.read_text("utf-8", errors="replace")
    return ""


def load_level1_concepts(key_terms: list[str], top_n: int = 5) -> list[dict]:
    """
    Level 1: 根据 key_terms 匹配相关概念，返回概念摘要列表。
    委托 index.py::match_related_concepts() 进行匹配。
    """
    # 惰性导入 index.py（避免模块级 E402）
    from index import load_concepts_index as _load_concepts_index  # noqa: E402
    from index import match_related_concepts as _match_related_concepts  # noqa: E402

    concepts_index = _load_concepts_index()
    if not concepts_index:
        return []

    # 委托 index.py 进行匹配
    matched_names = _match_related_concepts(key_terms, concepts_index, top_n=top_n)

    # 返回概念摘要（首段 + aliases）
    results = []
    for name in matched_names:
        info = concepts_index.get(name, {})
        concept_path = info.get("path", "")
        summary = info.get("summary", "")

        # 如果 summary 为空，尝试从概念页面读取首段
        if not summary and concept_path:
            full_path = Path(resolve_path(concept_path))
            if full_path.exists():
                try:
                    content = full_path.read_text("utf-8", errors="replace")
                    summary = _extract_first_paragraph(content)
                except OSError:
                    pass

        results.append(
            {
                "name": name,
                "path": concept_path,
                "summary": summary,
                "aliases": info.get("aliases", []),
                "article_count": info.get("article_count", 0),
            }
        )

    return results


def _extract_first_paragraph(content: str) -> str:
    """从 markdown 中提取首段（跳过 frontmatter 和标题）"""
    lines = content.split("\n")
    in_frontmatter = False
    for line in lines:
        if line.strip() == "---":
            in_frontmatter = not in_frontmatter
            continue
        if in_frontmatter:
            continue
        if line.strip().startswith("#"):
            continue
        if line.strip():
            return line.strip()
    return ""


# ============================================================================
# FTS5 全文索引管理
# ============================================================================


def init_fts5(conn: sqlite3.Connection):
    """初始化 FTS5 全文索引表"""
    conn.execute("""
        CREATE VIRTUAL TABLE IF NOT EXISTS wiki_fts USING fts5(
            content,
            title,
            tags,
            tokenize='unicode61'
        )
    """)
    conn.commit()


def create_fts5_virtual_table(conn: sqlite3.Connection):
    """创建虚拟内容表"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wiki_pages(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            file_path TEXT UNIQUE NOT NULL,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            tags TEXT,
            file_hash TEXT NOT NULL,
            weight REAL DEFAULT 1.0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'draft',
            confidence REAL DEFAULT 0.5
        )
    """)
    conn.commit()


def build_fts5_index(conn: sqlite3.Connection):
    """重建 FTS5 索引"""
    # 完全清除旧索引（DROP 表确保 id 从 1 开始，与 FTS5 rowid 对齐）
    try:
        conn.execute("DELETE FROM wiki_fts")
        conn.execute("DROP TABLE wiki_pages")
        conn.commit()
        print("  [OK] 已清除旧索引")
    except Exception:
        pass
    # 重建 wiki_pages 表（id 从 1 开始）
    create_fts5_virtual_table(conn)

    print("📥 开始构建 FTS5 全文索引...")

    pages_path = Path(PAGES_DIR)
    if not pages_path.exists():
        print("  [!] pages 目录不存在，跳过")
        return

    files = list(pages_path.glob("**/*.md"))
    print(f"  找到 {len(files)} 个页面文件")

    for i, md_file in enumerate(files, 1):
        try:
            content = md_file.read_text(encoding="utf-8", errors="replace")
            title = md_file.stem.replace("_", " ").replace("-", " ")

            # 提取标签和 OKF 字段（从 YAML frontmatter）
            tags = []
            status = "draft"
            confidence = 0.5
            if content.startswith("---"):
                end = content.find("\n---", 3)
                if end > 3:
                    frontmatter = content[3:end]
                    for line in frontmatter.split("\n"):
                        if line.startswith("tags:"):
                            tags_str = line.split(":", 1)[1].strip()
                            # 支持 YAML 行内列表: tags: [a, b, c]
                            if tags_str.startswith("[") and tags_str.endswith("]"):
                                inner = tags_str[1:-1]
                                tags = [
                                    t.strip().strip("`").strip('"').strip("'") for t in inner.split(",") if t.strip()
                                ]
                            # 支持空格分隔: tags: a b c
                            else:
                                tags = [
                                    t.strip().strip("`").strip('"').strip("'") for t in tags_str.split() if t.strip()
                                ]
                        # status（双读新/旧字段名）
                        if line.startswith("status:"):
                            status = line.split(":", 1)[1].strip().strip('"').strip("'")
                            if status not in ("draft", "review", "published", "archived"):
                                status = "draft"
                        if line.startswith("okf_status:"):
                            status = line.split(":", 1)[1].strip().strip('"').strip("'")
                            if status not in ("draft", "review", "published", "archived"):
                                status = "draft"
                        # confidence（双读新/旧字段名）
                        if line.startswith("confidence:"):
                            try:
                                confidence = float(line.split(":", 1)[1].strip().strip('"').strip("'"))
                                if not (0.0 <= confidence <= 1.0):
                                    confidence = 0.5
                            except (ValueError, TypeError):
                                confidence = 0.5
                        if line.startswith("okf_confidence:"):
                            try:
                                confidence = float(line.split(":", 1)[1].strip().strip('"').strip("'"))
                                if not (0.0 <= confidence <= 1.0):
                                    confidence = 0.5
                            except (ValueError, TypeError):
                                confidence = 0.5

            # 正文内容（去除 frontmatter）
            body = content
            if content.startswith("---"):
                end = content.find("\n---", 3)
                if end > 0:
                    body = content[end + 5 :]

            # 统一使用 file_hash 传入完整 content（内含 frontmatter 拆分逻辑）
            h = file_hash(content)

            conn.execute(
                """
                INSERT OR REPLACE INTO wiki_pages (file_path, title, content, tags, file_hash, status, confidence)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
                (str(md_file), title, body, " ".join(tags), h, status, confidence),
            )

            conn.execute(
                """
                INSERT INTO wiki_fts(content, title, tags)
                VALUES (?, ?, ?)
                """,
                (_tokenize_for_fts5(body), _tokenize_for_fts5(title), " ".join(tags)),
            )

            if i % 50 == 0:
                print(f"  已处理 {i}/{len(files)} 个文件...")

        except Exception as e:
            print(f"  [X] 处理 {md_file.name} 失败: {e}")

    conn.commit()
    print(f"[OK] FTS5 索引构建完成，共 {len(files)} 个页面")
    print("  OKF v0.1 集成: 已捕获 status（双读 status/okf_status）和 confidence 字段")


# ============================================================================
# 词项倒排索引（TF-IDF 简单实现）
# ============================================================================


def init_inverted_index(conn: sqlite3.Connection):
    """初始化词项倒排索引表"""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS wiki_terms(
            term TEXT PRIMARY KEY,
            doc_count INTEGER DEFAULT 0,
            doc_ids TEXT  -- JSON array of document ids
        )
    """)
    conn.commit()


def build_inverted_index(conn: sqlite3.Connection):
    """构建词项倒排索引"""
    print("📊 开始构建词项倒排索引...")

    pages = conn.execute("SELECT id, content, tags FROM wiki_pages").fetchall()
    if not pages:
        print("  ⚠️  无页面内容")
        return

    for page in pages:
        text = page["content"] + " " + (page["tags"] or "")
        words = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z]+", text.lower())

        unique_words = set(words)
        for term in unique_words:
            if len(term) < 2:
                continue

            existing = conn.execute("SELECT doc_ids FROM wiki_terms WHERE term = ?", (term,)).fetchone()

            if existing:
                doc_ids = json.loads(existing["doc_ids"])
                if page["id"] not in doc_ids:
                    doc_ids.append(page["id"])
                    conn.execute(
                        "UPDATE wiki_terms SET doc_ids = ?, doc_count = doc_count + 1 WHERE term = ?",
                        (json.dumps(doc_ids), term),
                    )
            else:
                conn.execute(
                    "INSERT INTO wiki_terms (term, doc_count, doc_ids) VALUES (?, 1, ?)",
                    (term, json.dumps([page["id"]])),
                )

    conn.commit()
    total_terms = conn.execute("SELECT COUNT(*) FROM wiki_terms").fetchone()[0]
    print(f"✅ 词项倒排索引构建完成，共 {total_terms} 个词项")


# ============================================================================
# 索引操作入口
# ============================================================================


def rebuild():
    """重建完整索引"""
    print(f"🏗️  重建索引 | wiki_root: {WIKI_ROOT}")
    ensure_dirs()

    conn = get_db()
    try:
        create_fts5_virtual_table(conn)
        init_fts5(conn)
        init_inverted_index(conn)

        build_fts5_index(conn)
        build_inverted_index(conn)

        print("\n✅ 索引重建完成")

        # 自动同步元数据索引（source_map + filename_index）
        try:
            from index import sync_meta_from_files, recalc_article_counts, load_concepts_index, save_concepts_index

            meta_result = sync_meta_from_files()
            if meta_result["source_map_updated"] or meta_result["filename_index_updated"]:
                print(
                    f"  📇 元数据已同步: source_map +{meta_result['source_map_updated']}, filename +{meta_result['filename_index_updated']}"
                )
            # 自动重算概念 article_count
            concepts = load_concepts_index()
            if concepts:
                concepts = recalc_article_counts(concepts)
                save_concepts_index(concepts)
                print("  📊 概念 article_count 已刷新")
        except Exception as e:
            print(f"  ⚠️  元数据同步跳过: {e}")

        print("  💡 建议更新 graph/GRAPH_SUMMARY.md（LLM 根据索引内容生成摘要）")
    finally:
        conn.close()


def update():
    """增量更新索引"""
    print(f"🔄 增量更新索引 | wiki_root: {WIKI_ROOT}")
    ensure_dirs()

    conn = get_db()
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        sync_marker = datetime.now(timezone.utc).isoformat()

        pages_path = Path(PAGES_DIR)
        if not pages_path.exists():
            print("  ⚠️  pages 目录不存在")
            return

        all_files = {}
        for f in pages_path.glob("**/*.md"):
            try:
                all_files[str(f)] = file_hash(f.read_text(encoding="utf-8", errors="replace"))
            except Exception as e:
                print(f"  ⚠️ 跳过 {f.name}: {e}")
                continue

        db_files = conn.execute("SELECT id, file_path, file_hash FROM wiki_pages").fetchall()
        for db_file in db_files:
            if db_file["file_path"] not in all_files:
                print(f"  🗑️  删除: {Path(db_file['file_path']).name}")
                conn.execute("DELETE FROM wiki_pages WHERE id = ?", (db_file["id"],))
            else:
                if db_file["file_hash"] != all_files[db_file["file_path"]]:
                    print(f"  🔄 更新: {Path(db_file['file_path']).name}")
                    try:
                        new_content = Path(db_file["file_path"]).read_text(encoding="utf-8", errors="replace")
                    except Exception as e:
                        print(f"  ⚠️ 读取失败 {Path(db_file['file_path']).name}: {e}")
                        continue
                    new_hash = file_hash(new_content)
                    title = Path(db_file["file_path"]).stem.replace("_", " ").replace("-", " ")
                    conn.execute(
                        """
                        UPDATE wiki_pages SET title = ?, content = ?, file_hash = ?, updated_at = ? WHERE id = ?
                    """,
                        (title, new_content, new_hash, datetime.now(timezone.utc).isoformat(), db_file["id"]),
                    )

        for path, h in all_files.items():
            existing = conn.execute("SELECT id FROM wiki_pages WHERE file_path = ?", (path,)).fetchone()
            if not existing:
                print(f"  ✨ 添加: {Path(path).name}")
                try:
                    content = Path(path).read_text(encoding="utf-8", errors="replace")
                except Exception as e:
                    print(f"  ⚠️ 读取失败 {Path(path).name}: {e}")
                    continue
                title = Path(path).stem.replace("_", " ").replace("-", " ")
                conn.execute(
                    """
                    INSERT INTO wiki_pages (file_path, title, content, file_hash)
                    VALUES (?, ?, ?, ?)
                """,
                    (path, title, content, h),
                )

        total_pages = conn.execute("SELECT COUNT(*) FROM wiki_pages").fetchone()[0]
        if total_pages == 0:
            print("  首次运行，跳过增量同步")
        else:
            changed = conn.execute(
                """
                SELECT p.id, p.content, p.title, COALESCE(p.tags, '') as tags
                FROM wiki_pages p
                WHERE p.updated_at >= ?
            """,
                (sync_marker,),
            ).fetchall()
            for row in changed:
                conn.execute(
                    "INSERT INTO wiki_fts(wiki_fts) VALUES('delete', ?)",
                    (row["id"],),
                )
                conn.execute(
                    """
                    INSERT INTO wiki_fts(rowid, content, title, tags)
                    VALUES (?, ?, ?, ?)
                """,
                    (
                        row["id"],
                        _tokenize_for_fts5(row["content"]),
                        _tokenize_for_fts5(row["title"]),
                        row["tags"],
                    ),
                )
            conn.commit()
            print(f"  FTS5 incremental sync: {len(changed)} pages")
        print("\n✅ 增量更新完成")
        print("  ⚠️  注意：增量更新不刷新词项倒排索引(wiki_terms)，")
        print("  如需完整索引请运行: python scripts/search_engine.py rebuild")
    finally:
        conn.close()


# ============================================================================
# 三层查询入口
# ============================================================================


def query_three_layer(query: str, level: int = 1, limit: int = 5) -> dict:
    """
    三层查询入口。

    Args:
        query: 查询关键词或问题
        level: 查询层级（0/1/2）
        limit: 每层返回数量

    Returns:
        {
            "level": int,
            "summary": str (Level 0),
            "concepts": list[dict] (Level 1),
            "articles": list[dict] (Level 2),
        }
    """
    result = {"level": level, "summary": "", "concepts": [], "articles": []}

    # Level 0: 全局图谱摘要（始终加载，开销极小）
    result["summary"] = load_level0_summary()

    # Level 1: 概念索引 + matched concepts
    if level >= 1:
        key_terms = _extract_key_terms(query)
        result["concepts"] = load_level1_concepts(key_terms, top_n=limit)

        # 自动降级：如果 Level 1 无结果，尝试 Level 2
        if not result["concepts"] and level < 2:
            result["articles"] = search_articles(query, limit=limit)
            if result["articles"]:
                result["level"] = 2  # 标记实际降级到了 Level 2

    # Level 2: 完整文章体（FTS5 搜索，默认 published 仅）
    if level >= 2:
        result["articles"] = search_articles(query, limit=limit)

    return result


def _extract_key_terms(query: str) -> list[str]:
    """从查询中提取关键词（简单分词）"""
    # 提取中文和英文词汇
    words = re.findall(r"[\u4e00-\u9fff]+|[a-zA-Z]+", query.lower())
    return [w for w in words if len(w) >= 2]


def search_articles(query: str, limit: int = 10, all_status: bool = False) -> list[dict]:
    """FTS5 搜索文章（rebuild 后 rowid 与 wiki_pages.id 对齐）

    默认只返回 status='published' 的页面（OKF 标准），可通过 all_status=True 查看非 published 页面。
    结果按 confidence 降序排列（置信度高的优先）。
    """
    conn = get_db()
    try:
        if all_status:
            fts_results = conn.execute(
                """
                SELECT wp.file_path, wp.title, wp.content, wp.status, wp.confidence
                FROM wiki_fts wf
                JOIN wiki_pages wp ON wp.id = wf.rowid
                WHERE wiki_fts MATCH ?
                ORDER BY wp.confidence DESC, rank / MAX(wp.weight, 0.5), rank
                LIMIT ?
            """,
                (_tokenize_for_fts5(query), limit),
            ).fetchall()
        else:
            fts_results = conn.execute(
                """
                SELECT wp.file_path, wp.title, wp.content, wp.status, wp.confidence
                FROM wiki_fts wf
                JOIN wiki_pages wp ON wp.id = wf.rowid
                WHERE wiki_fts MATCH ? AND wp.status = ?
                ORDER BY wp.confidence DESC, rank / MAX(wp.weight, 0.5), rank
                LIMIT ?
            """,
                (_tokenize_for_fts5(query), OKF_PUBLISHED_STATUS, limit),
            ).fetchall()

        results = []
        for row in fts_results:
            results.append(
                {
                    "file_path": row[0],
                    "title": row[1],
                    "content": row[2][:500] + "..." if len(row[2]) > 500 else row[2],
                    "status": row[3],
                    "confidence": row[4],
                }
            )
        return results
    finally:
        conn.close()


def search(query: str, limit: int = 10, all_status: bool = False):
    """搜索 wiki 内容（向后兼容）

    默认只返回 status='published' 的页面（OKF 标准）。
    结果按 confidence 降序排列（置信度高的优先）。
    """
    mode_label = "all status（含 draft/review/archived）" if all_status else "published 仅（OKF 标准）"
    print(f'[STAT] 搜索: "{query}"  |  模式: {mode_label}')

    conn = get_db()
    try:
        if all_status:
            fts_results = conn.execute(
                """
                SELECT wf.rowid, wp.file_path, wp.title, wp.status, wp.confidence
                FROM wiki_fts wf
                JOIN wiki_pages wp ON wp.id = wf.rowid
                WHERE wiki_fts MATCH ?
                ORDER BY wp.confidence DESC, rank / MAX(wp.weight, 0.5), rank
                LIMIT ?
            """,
                (_tokenize_for_fts5(query), limit),
            ).fetchall()
        else:
            fts_results = conn.execute(
                """
                SELECT wf.rowid, wp.file_path, wp.title, wp.status, wp.confidence
                FROM wiki_fts wf
                JOIN wiki_pages wp ON wp.id = wf.rowid
                WHERE wiki_fts MATCH ? AND wp.status = ?
                ORDER BY wp.confidence DESC, rank / MAX(wp.weight, 0.5), rank
                LIMIT ?
            """,
                (_tokenize_for_fts5(query), OKF_PUBLISHED_STATUS, limit),
            ).fetchall()

        if not fts_results:
            if all_status:
                print("  [!] 未找到结果（全库无匹配）")
            else:
                print("  [!] 未找到结果（published 仅模式）")
            # 提示用户是否尝试 --all-status
            # 先检查全库（含draft）的匹配数
            all_match = conn.execute(
                "SELECT COUNT(*) FROM wiki_fts WHERE wiki_fts MATCH ?",
                (_tokenize_for_fts5(query),)
            ).fetchone()[0]
            if all_match > 0:
                published_count = conn.execute(
                    "SELECT COUNT(*) FROM wiki_pages WHERE status = ?",
                    (OKF_PUBLISHED_STATUS,)
                ).fetchone()[0]
                if all_status:
                    print(f"  提示: 全库有 {all_match} 页匹配，其中 {published_count} 页为 published 状态")
                else:
                    print(f"  提示: 全库有 {all_match} 页匹配（含 draft），其中 {published_count} 页为 published 状态")
                    print(f"  建议: 尝试 python search_engine.py search \"{query}\" --all-status")
            return []

        found_label = "all status" if all_status else "published 仅"
        print(f"  找到 {len(fts_results)} 个结果（{found_label}）:\n")
        for i, row in enumerate(fts_results, 1):
            status_tag = f" [{row['status']}]"
            conf_tag = f" 置信度:{row['confidence']}"
            print(f"  {i}. [{row['title']}]  {row['file_path']}{status_tag}{conf_tag}")

        return fts_results
    finally:
        conn.close()


def stats():
    """统计索引信息"""
    conn = get_db()
    try:
        page_count = conn.execute("SELECT COUNT(*) FROM wiki_pages").fetchone()[0]
        try:
            term_count = conn.execute("SELECT COUNT(*) FROM wiki_terms").fetchone()[0]
        except Exception:
            term_count = 0

        # 惰性导入 index.py（避免模块级 E402）
        from index import load_concepts_index as _load_concepts_index  # noqa: E402
        concepts = _load_concepts_index()
        concept_count = len(concepts)

        # OKF 状态分布统计
        okf_dist = conn.execute(
            "SELECT status, COUNT(*) as cnt FROM wiki_pages GROUP BY status"
        ).fetchall()

        print("[STAT] OKF 集成索引统计:")
        print(f"  页面数量: {page_count}")
        print(f"  概念数量: {concept_count}")
        print(f"  词项数量: {term_count}")
        if Path(SEARCH_INDEX_PATH).exists():
            print(f"  数据库大小: {Path(SEARCH_INDEX_PATH).stat().st_size / 1024:.1f} KB")

        if okf_dist:
            print()
            print("[STAT] OKF 状态分布:")
            for row in okf_dist:
                status, cnt = row
                bar = "█" * (cnt // max(1, page_count // 20))
                print(f"    {status:12s}  {cnt:4d}  {bar}")
    finally:
        conn.close()


# ============================================================================
# CLI 入口
# ============================================================================


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        print("\n可用命令: rebuild | update | search <query> | query <query> [--level N] | stats")
        sys.exit(1)

    cmd = sys.argv[1].lower()

    if cmd == "rebuild":
        rebuild()
    elif cmd == "update":
        update()
    elif cmd == "search":
        if len(sys.argv) < 3:
            print('用法: python search_engine.py search "关键词"')
            sys.exit(1)
        all_status = "--all-status" in sys.argv
        search(sys.argv[2], all_status=all_status)
    elif cmd == "query":
        if len(sys.argv) < 3:
            print('用法: python search_engine.py query "问题" [--level 0|1|2] [--all-status]')
            sys.exit(1)
        query_text = sys.argv[2]
        level = 1
        all_status = "--all-status" in sys.argv
        if "--level" in sys.argv:
            idx = sys.argv.index("--level")
            if idx + 1 < len(sys.argv):
                level = int(sys.argv[idx + 1])

        # query_three_layer 默认走 published 仅，--all-status 模式下需扩展
        result = query_three_layer(query_text, level=level)

        actual_level = result.get("level", level)
        if actual_level > level:
            print(f"\n[CHK] 三层查询 (Level {level} -> 自动降级到 Level {actual_level})")
        else:
            print(f"\n[CHK] 三层查询 (Level {level})")
        print(f"  搜索模式: {'全部状态' if all_status else 'published 仅（OKF 标准）'}")

        if result["summary"]:
            print("\n[DOC] Level 0 全局摘要:")
            print(f"   {result['summary'][:200]}...")

        if result["concepts"]:
            print(f"\n[CHK] Level 1 相关概念 ({len(result['concepts'])} 个):")
            for c in result["concepts"]:
                aliases = ", ".join(c.get("aliases", []))
                print(f"   - {c['name']}")
                if aliases:
                    print(f"     别名: {aliases}")
                if c.get("summary"):
                    print(f"     {c['summary'][:100]}...")

        if result["articles"]:
            print(f"\n[DOC] Level 2 相关文章 ({len(result['articles'])} 个):")
            for a in result["articles"]:
                status_tag = f" [{a.get('status', '?')}]"
                conf_tag = f" 置信度:{a.get('confidence', 0)}"
                print(f"   - [{a['title']}]  {a['file_path']}{status_tag}{conf_tag}")

    elif cmd == "stats":
        stats()
    else:
        print(f"[X] 未知命令: {cmd}")
        print("可用命令: rebuild | update | search | query | stats")
        sys.exit(1)


if __name__ == "__main__":
    main()
