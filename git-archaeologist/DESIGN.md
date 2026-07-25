# git-archaeologist — 设计文档

> **状态**：设计阶段（仅 DESIGN.md，未实现）。
> **对标**：frontend-audit 的"Python CLI + 编排外部工具（git/gh）+ json-compact 输出"形态。

## 1. 定位

回答"这段代码为什么存在"。流程：blame → 引入 commit → 关联 PR/issue → 提取设计意图 → 生成考古报告。回答：
- "这行代码是谁加的？为什么？"
- "这个函数的历史演化？"
- "这个奇怪的 workaround 当初是为哪个 bug 加的？"

**典型触发**："这段代码为什么这么写" / "git blame" / "代码考古" / "这个 hack 哪来的" / "这个函数的历史"。

**与 diagnosing-bugs 的关系**：diagnosing-bugs 是"修 bug"，git-archaeologist 是"修 bug 前先懂历史"。两者上下游：考古报告帮诊断定位"这是 feature 还是 regression"。

## 2. 与现有 skill 的复用关系

| 复用来源 | 复用什么 |
|---------|---------|
| frontend-audit | engine 编排模式、subprocess 调用外部工具（这里调 git/gh 而非 eslint/npm）、output.py 骨架、degradation_notices 机制 |
| dotnet-code-review | Finding 形态、exit code 体系、context_bundle（给 Agent 打包上下文） |
| loop-coding | vcs_abstraction.md 的 git/tfs 能力边界思路 |

**不复用**：不重新发明 git 操作——直接 subprocess 调 `git` / `gh` CLI（与 database-explorer 调驱动同理）。

## 3. SKILL.md 大纲

```yaml
---
name: git-archaeologist
description: |
  代码考古 CLI：blame 链 + PR/issue 关联 + 设计意图提取，回答"这段代码为什么存在"。
  能力：行级 blame 追溯、文件历史时间线、commit ↔ PR/issue 关联（via gh）、多版本演化对比。
  Agent 通过 subprocess 调用 scripts/archaeologist.py + git/gh CLI，用户不接触 CLI。
  触发：用户说"这段代码为什么这么写" / "git blame" / "代码考古" 时。
agent_created: true
version: 0.1.0
---
```

章节：核心原则 → §0 前置条件（git 必需，gh 可选） → §1 命令速查 → §2 Agent 决策规则（意图映射 + blame 策略 + 意图提取协议） → §3 输出处理 → §4 报告模板（时间线式） → §5 边界处理（非 git 仓库 / 无 gh / 大文件） → §6 故障排查 → §7 references → §8 测试状态。

## 4. CLI 接口

```
archaeologist.py why --target <file:line | symbol:FuncName>
                     [--depth 3]              # blame 追溯层数
                     [--format json-compact|markdown]
archaeologist.py history --target <file>
                     [--since <commit>]
                     [--format json-compact|markdown]
archaeologist.py blame --target <file:line>
                     [--format json-compact]
archaeologist.py pr --commit <sha>            # 找关联 PR/issue
```

**Exit Code**：0=成功 / 1=未找到目标 / 2=非 git 仓库 / 3=配置错误 / 4=gh 缺失（降级而非失败）。

## 5. 文件结构（规划）

```
git-archaeologist/
├── SKILL.md
├── pytest.ini
├── requirements.txt          # 无强依赖（只用 stdlib subprocess）
├── references/
│   ├── blame-strategy.md     # blame 链追溯策略（唯一权威源）
│   ├── vcs-abstraction.md    # git/gh 能力边界 + 降级
│   └── troubleshooting.md
├── scripts/
│   ├── archaeologist.py      # CLI 入口
│   ├── count_capabilities.py # 维护脚本：统计能力数
│   └── archaeologist/
│       ├── __init__.py
│       ├── engine.py         # 编排：blame → link → timeline
│       ├── models.py         # BlameEntry / Commit / PR / Timeline dataclass
│       ├── errors.py
│       ├── git_blame.py      # git blame / log / show 封装
│       ├── pr_linker.py      # gh CLI 封装（pr/issue 关联）
│       ├── symbol.py         # 符号 → 行范围解析（func/class 定位）
│       ├── timeline.py       # 时间线组装
│       ├── context_bundle.py # 给 Agent 打包上下文
│       └── output.py
└── tests/
    ├── conftest.py
    ├── test_git_blame.py     # 用真实临时 git 仓库
    ├── test_pr_linker.py     # mock gh 输出
    ├── test_symbol.py        # 符号定位
    ├── test_timeline.py
    ├── test_output.py
    └── test_e2e.py           # 在 fixtures/git-repo（真实 git 历史）上跑
```

## 6. 核心逻辑

### 6.1 blame 链（多版本追溯）

`why --target file:42 --depth 3`：
1. `git blame -L 42,42 -- file` → 得到引入该行的 commit C1。
2. 对 C1 的父提交 C0，再 `git blame -L <对应行>,<对应行> -- file`（需先用 `git show C1:file` 找到行号映射）→ 得到 C2。
3. 重复 depth 次，或直到 initial commit。

输出：blame 链 `[(C1, line, snippet), (C2, ...), ...]`。

**关键难点**：跨 commit 的行号映射。策略——用 `git blame --porcelain` 拿到 `(orig_line, final_line, orig_sha)`，必要时用 `git log -L` 跟踪行演化（`intentional-simple`：`git log -L` 在大文件上慢，depth 兜底）。

### 6.2 PR/issue 关联

对每个 commit：
1. 解析 commit message 里的 `#123` 引用 → issue/PR 编号。
2. 调 `gh pr list --search <sha>` / `gh pr view <num> --json title,body,url` 找关联 PR。
3. gh 缺失 → 降级：只用 commit message + author + date。

### 6.3 符号定位

`--target symbol:FuncName`：先 `grep -n "def FuncName\|function FuncName\|class FuncName"` 找到符号起始行，再根据缩进/花括号推断结束行，转成 `file:start-end` 喂给 blame。

### 6.4 时间线组装

```python
@dataclass
class TimelineEntry:
    sha: str
    date: str
    author: str
    message: str
    pr: PR | None          # 关联 PR（标题 + body 摘要 + url）
    issue: Issue | None    # 关联 issue
    change_type: str       # added | modified | removed
    snippet_before: str    # 改之前
    snippet_after: str     # 改之后
    intent_hypothesis: str # 从 PR/commit 提取的"存在理由"假说（Agent 进一步提炼）
```

按时间倒序，让 Agent 看到演化脉络。

## 7. MVP 范围

**MVP 必须有**：
- `why` 子命令（blame 链 + PR 关联）
- `history` 子命令（文件时间线）
- blame 链 depth 控制
- commit message `#N` 引用解析
- gh CLI 封装（缺失降级）
- json-compact + markdown 输出

**MVP 不做**：
- 跨分支 blame（merge commit 处理复杂）
- 非 git VCS（TFS/SVN，预留 vcs_abstraction 接口）
- 自动总结"存在理由"（只给 Agent 原始数据，意图提炼交给 Agent）
- blame 整个目录（性能差，限制在行/符号级）

## 8. 验证计划

1. git blame 封装 + 单测 → 验证：在临时 git 仓库（`git init` + 多次 commit）跑 blame 链
2. PR linker + 单测 → 验证：mock gh 输出，解析 `#123` + JSON
3. 符号定位 + 单测 → 验证：Python/JS 函数定义行范围
4. 时间线组装 + 单测 → 验证：多 commit 按时间排序 + change_type 判定
5. 端到端 → 验证：在 fixtures/git-repo（用脚本构造有 PR 引用的真实历史）跑完整流程
6. SKILL.md + references → 验证：模板合规

**测试策略**：用 `tmp_path` fixture 在每个测试里 `git init` 构造迷你历史，不依赖外部仓库。gh 测试全部 mock。

## 9. 风险与取舍

- **行号映射是难点**：跨 commit 的行号对应不完美（插入/删除会导致偏移），用 `git log -L` 跟踪 + depth 兜底，标 `intentional-simple`。
- **gh 速率限制**：`gh api` 有 rate limit，对大量 commit 批量查 PR 时需缓存 + 限流。
- **大文件性能**：blame 在万行文件上慢，加 `--max-lines` 守卫（如超过 5000 行提示用户缩小范围）。
- **merge commit**：`git blame` 默认跟随 first parent，可能跳过 merge 进来的变更；MVP 不处理，提示用户。
- **隐私**：author email 等可能在输出里，提供 `--redact` 选项脱敏（对标 database-explorer 的错误脱敏）。
