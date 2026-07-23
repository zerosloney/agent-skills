# Orchestrator 消息模板

## 脏基线

```text
⚠️ 脏基线检测
项目已有 N 个预存失败：
{baseline_failures}
是否需要一并修复？[是/否（推荐）]
```

## TFS 签出

```text
📋 TFS 签出确认
以下文件需要在 TFS 中签出：
{scope_files}
请签出后回复“已签出”。
```

追加 scope 外文件时，把标题改为“追加签出”，列出 `{new_files}`。

## Cycle 开始

```text
=== Cycle N/{max_cycles} ===
当前目标：{in_progress_item}
契约总范围：{contract.scope}
本轮 item 范围：{item.scope}
```

## Loop Contract

见 `templates/loop_contract.md`。

## 报告

- success 字段见 `references/loop_contract.md` 的 REPORT。
- incomplete 字段见 `references/stop_conditions.md` 的升级报告。
- aborted_by_user 字段见 `references/loop_contract.md`。
