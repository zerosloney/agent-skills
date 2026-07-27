---
# ═══════════════════════════════════════════════════════════════
# OKF (Open Knowledge Format) v0.1 — Google 标准字段
# 来源: https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md
# ═══════════════════════════════════════════════════════════════

# OKF Required (唯一必须字段)
type: concept                        # 从 schema/entity-types.yaml 选择

# OKF Recommended
title: 页面标题                       # 人类可读展示名称
description: 单句摘要                 # 用于搜索摘要和预览
resource:                            # 可选：底层资产的规范 URI
tags: [tag1, tag2]                   # 跨领域分类标签
timestamp: YYYY-MM-DDThh:mm:ssZ      # 最后有意义变更时间 (ISO 8601)

# ═══════════════════════════════════════════════════════════════
# 项目扩展字段（OKF §4.1 允许生产者包含任何额外键）
# 这些字段不是 OKF 标准的一部分，但项目内部使用。
# ═══════════════════════════════════════════════════════════════

# 向后兼容：entity_type 是 type 的别名
entity_type: concept

# 生命周期管理
status: draft                        # draft | review | published | archived
confidence: 0.85                     # 置信度 0.0-1.0，自动估算

# 术语统一
aliases: [别名1, 别名2]               # 同义词/别名
domains: [AI, 深度学习]               # 知识领域分区

# 来源追溯
sources:
  - raw/article.md
  - web:https://example.com/article
provenance:                          # 来源追溯增强
  original_source: "https://example.com/article"
  extracted_by: web_fetch           # web_fetch | fetch.py | manual
  extracted_at: YYYY-MM-DD
  sha256: abc123def456              # 与 .cache/sources.json 关联

# 知识关联
related_articles:
  - id: prerequisite-page
    relation: prerequisite          # prerequisite | extends | contradicts | references | supersedes | related
    note: 关联说明（可选）

# 版本追踪
version_history:
  - version: "1.0"
    date: YYYY-MM-DD
    changes: "初版创建"

# ═══════════════════════════════════════════════════════════════
# 旧版 OKF 字段（向后兼容，新页面可不写）
# 迁移说明：旧 okf_* 字段已废弃，用上面的无前缀字段替代。
# migrate 命令会自动转换。
# ═══════════════════════════════════════════════════════════════
# okf_status: draft                  # 已废弃，用 status
# okf_confidence: 0.85              # 已废弃，用 confidence
# okf_provenance: {}                # 已废弃，用 provenance
# okf_related: []                   # 已废弃，用 related_articles
# okf_version_history: []           # 已废弃，用 version_history
# okf_version: "1.0"                # 已废弃，不在 OKF spec 中
# okf_created: YYYY-MM-DD           # 已废弃，用 timestamp
# okf_modified: YYYY-MM-DD          # 已废弃，用 timestamp
# okf_tags: [tag1, tag2]            # 已废弃，合并到 tags
---