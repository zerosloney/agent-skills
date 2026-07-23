# AGENTS.md 模板

## 作用

项目级局部约定，覆盖 `references/model_tiers.md` 的默认模型分派。适合项目需要固定 builder/checker 模型或当前环境没有默认映射中某些模型时使用。

## 可选字段

```yaml
---
loop_coding:
  model_map:
    orchestrator: <当前会话模型>   # 一般不动
    builder: <弱一级模型>          # 填当前环境可用的模型标识
    checker: <弱一级模型>
    explorer: <弱两级模型>
  skip_dispatch: false            # true 时所有子任务均使用当前会话模型
  max_cycles: 5                   # 覆盖 contract.budget.max_cycles 默认值
  check_commands:                 # 覆盖自动检测的检查命令
    test: ["npm", "test"]
    lint: ["npm", "run", "lint"]
    typecheck: ["npx", "tsc", "--noEmit"]
    format: ["npm", "run", "format:check"]
  unreliable: []                  # 基线阶段已知不稳定的命令，循环中仅参考
```

## 使用方式

将文件放在项目根目录：

```bash
project_root/
├── AGENTS.md
├── package.json
└── ...
```

orchestrator 启动时检测到 `AGENTS.md` 存在，读取其中 `loop_coding.model_map` 并直接用于 Agent 分派，不再按 Tier 推导。

## 注意事项

- `model_map` 中的值必须是当前运行环境实际可用的模型标识，否则会被忽略并回退到 `references/model_tiers.md` 的默认推导。
- `skip_dispatch: true` 时，所有子任务都使用当前会话模型，相当于关闭多 Agent 编排。
- 不要在此文件存放 API 密钥或密码，凭证应走 keyring。
