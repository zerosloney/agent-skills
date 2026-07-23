# Agent Skills

AI Agent 技能（Skills）集合仓库。每个子目录是一个独立、可被 Agent 调用的技能，自带 `SKILL.md` 指令集。

## 技能清单

| 技能 | 版本 | 说明 |
|------|------|------|
| [database-explorer](./database-explorer/) | 0.6.0 | 数据库探索 CLI：连接、查询、结构探索、CRUD 生成、CSV 导出。支持 SQL Server / MySQL / PostgreSQL / KingbaseES（人大金仓）/ SQLite。写操作自动确认，密码经 keyring 存入系统密钥链。 |
| [dotnet-code-review](./dotnet-code-review/) | 0.4.1 | C#/.NET 代码审查。基于 Roslyn（AST + Semantic + Project）+ dotnet build/format + 离线 CVE 库，覆盖安全/性能/可靠性/最佳实践/架构/测试 6 维度，支持 SARIF 输出与自动修复。 |
| [loop-coding](./loop-coding/) | — | 循环式 AI 编码：builder 修改、checker 验证，直到检查通过或触发停止条件。默认 `--once` 单轮模式。 |
| [winforms-dev-flow](./winforms-dev-flow/) | — | WinForm + DevExpress 业务窗体生成（.NET Framework 4.7.2）：列表窗体、主从结构、编辑弹窗、查询/新增/修改/删除界面，支持增量编辑与架构迁移。 |

> 各技能的安装方式、命令速查、触发规则与设计约束，见对应目录下的 `SKILL.md`。

## 仓库结构

```
agent-skills/
├── database-explorer/      # 数据库探索 CLI（Python）
│   ├── SKILL.md
│   ├── pyproject.toml
│   ├── requirements.txt
│   ├── references/         # 参考文档
│   └── scripts/            # 源代码（cli + core + tests）
├── dotnet-code-review/     # .NET 代码审查（Python + Roslyn C# 分析器）
│   ├── SKILL.md
│   ├── pytest.ini
│   ├── references/
│   └── scripts/            # review.py + csharp-*-analyzer 工程
├── loop-coding/            # 循环式编码
│   ├── SKILL.md
│   ├── INDEX.md
│   ├── prompts/
│   ├── references/
│   ├── scripts/
│   └── templates/
└── winforms-dev-flow/      # WinForm 业务窗体生成
    ├── SKILL.md
    ├── examples/
    ├── references/
    └── scripts/
```

## 许可证

MIT（各技能的配置见对应 `pyproject.toml`）。
