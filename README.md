# Agent Skills

AI Agent 技能（Skills）集合仓库。每个子目录是一个独立、可被 Agent 调用的技能。

## 仓库结构

```
agent-skills/
└── database-explorer/      # 数据库探索 CLI 工具
    ├── SKILL.md            # Agent 指令集（技能主文档）
    ├── pyproject.toml      # Python 项目配置
    ├── requirements.txt    # 依赖声明
    ├── references/         # 参考文档（命令、schema、排错等）
    └── scripts/            # 源代码（CLI + core + tests）
```

## 技能清单

| 技能 | 说明 |
|------|------|
| [database-explorer](./database-explorer/) | 支持 SQL Server / MySQL / PostgreSQL / KingbaseES（人大金仓）/ SQLite 的连接、查询、结构探索、CRUD 生成、CSV 导出。写操作自动确认，密码经 keyring 存入系统密钥链。 |

详细的安装方式、命令速查与触发规则见各技能目录下的 `SKILL.md`：

- [database-explorer/SKILL.md](./database-explorer/SKILL.md)

## 许可证

MIT（见 [database-explorer/pyproject.toml](./database-explorer/pyproject.toml)）。
