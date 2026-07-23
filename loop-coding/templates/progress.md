## Codebase Patterns
（builder 周期性精炼；只保留非显然、跨轮有用的约定）

- <pattern>

---

## <ISO8601> - Cycle <N>
- What was implemented: <具体实现>
- Files changed: <file1>, <file2>
- **Learnings for future iterations:**
  - Patterns discovered: <pattern 或 无>
  - Gotchas encountered: <gotcha 或 无>
  - Useful context: <context 或 无>
---

## 规则

- builder 每轮只追加新的 Cycle 条目；不改旧条目。
- Codebase Patterns 可精炼，但必须保留可审计 diff。
- 不写故事级细节、临时 debug 笔记、已过时约定。
- 发现非显然项目约定时，可同步追加到 `AGENTS.md`。
