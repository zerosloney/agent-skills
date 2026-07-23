# Cycle -1 Bootstrap

在项目根目录不存在、为空，或没有可用检查命令时执行。Bootstrap 只建壳，不写业务实现。

## 流程

1. 创建 `{project_root}`。
2. 根据任务推断技术栈并初始化项目：
   - .NET: `dotnet new webapi`
   - Node/TS: `npm init -y` 或项目要求的脚手架
   - Python: `pyproject.toml` / `requirements.txt`
   - 纯前端: `index.html`
3. 写 `AGENTS.md`，至少包含一条真实 `check_commands`。
4. 生成 1-2 个 expected-fail 种子测试，用于证明检查链路可执行。
5. 运行检查命令，确认命令可执行且种子测试能被发现并失败。

## 最小检查命令

| 技术栈 | 命令 |
|---|---|
| .NET | `dotnet build --no-restore` |
| Python | `python -m pytest --co` |
| Node/TS | `npx tsc --noEmit` 或 `npm test` |
| HTML | `node -e "require('fs').existsSync('index.html')"` |

## 种子测试规则

- 覆盖核心入口，断言故意失败。
- 数量不超过 3 个。
- 文件名含 `BootstrapTest` 或 `_bootstrap_test`，便于 checker 区分真实失败。

## 完成报告

```text
=== Bootstrap 完成 ===
项目骨架：{技术栈}
检查命令：{命令列表}
种子测试：{N 个 expected-fail}
已生成：AGENTS.md、项目文件
→ 进入 Cycle 0 (Planner)
```

## 红线

- 不写业务逻辑。
- `check_commands` 不得是占位符。
- 种子测试不能 trivially pass。
