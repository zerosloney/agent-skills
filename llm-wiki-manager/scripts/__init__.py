"""
LLM Wiki Manager 脚本包

核心脚本（20 个）：
  初始化：    init.py
  导入：      fetch.py, cache.py
  编译：      compile_post.py, detect_concepts.py, suggest_tags.py
  搜索：      search_engine.py, search.py, question_classifier.py
  索引：      index.py, graph_analyze.py
  校验：      lint.py, validate.py, validate_entities.py, validate_claims.py
  维护：      delete.py, promote.py, git_backup.py
  反馈：      feedback.py, update_weights.py

依赖：
  - jieba:     中文分词（搜索索引 + 概念检测 + 标签建议）
  - pyyaml:    YAML 解析（反馈日志 + frontmatter）
  - networkx:  图分析介数中心性（可选，缺失时降级为度数近似）
"""
