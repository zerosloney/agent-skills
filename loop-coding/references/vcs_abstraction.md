# VCS 抽象层

支持 Git 和 TFS；其他 VCS 进入降级模式。

## 接口

```typescript
interface VCSCapabilities {
  type: "git" | "tfs" | "other";
  snapshot(): VCSSnapshot;
  changedFilesSince(snapshot: VCSSnapshot): string[];
  restore(snapshot: VCSSnapshot): RestoreResult;
  isDirty(): boolean;
  stashPush(message: string): string;
  stashRestore(ref: string): void;
}
```

快照必须记录 VCS 头、本地变更列表、文件指纹和时间戳，用于计算“本轮实际改动”。

## Git

- snapshot: `git rev-parse HEAD` + 本地变更指纹。
- changedFilesSince: `git diff --name-only` + untracked。
- isDirty: `git status --porcelain`。
- stash: `git stash push -u -m "<message>"` / `git stash pop <ref>`。
- restore/reset 前先 stash 保护用户改动。

## TFS

前置条件见 `references/tfs_setup.md`。

- snapshot: `tf status /recursive` + pending changes 指纹。
- changedFilesSince: 对比当前 pending changes 与 snapshot。
- checkout: `tf checkout <files...>`。
- restore: 用户确认后 `tf undo . /recursive`。
- stash: `tf shelve` / `tf unshelve`。
- 禁止自动 `tf checkin`。

## TFS 签出确认

Cycle 1 前，orchestrator 从 scope 提取文件列表并要求用户签出：

```text
📋 TFS 签出确认
以下文件需要在 TFS 中签出：
{file_list}
请签出后回复“已签出”。
```

循环中需要新增 scope 外文件时，暂停、更新 scope、要求签出并重新确认。

## SCOPE_DRIFT

每轮 Cycle start 记录快照。Post-check 只能用 `changedFilesSince(cycle_start)` 判定本轮改动；禁止直接用全量 `git status` / `tf status`，因为循环前可能已有用户改动。

## Monorepo

`contract.scope` 相对于 `project_root`。若需要跨包修改，把 `project_root` 提升到共同根目录，或把其他包路径显式加入 scope。

TFS workspace 可映射多项目；跨映射修改必须在签出确认阶段列出所有文件。

## Other 降级

无 `.git` 且无 `.tf`，或 TFS 命令不可用时：

- 可运行 Bootstrap、基线检查、builder/checker、状态文件。
- 无精确 snapshot/restore/SCOPE_DRIFT。
- 不建议用于生产代码或长循环任务。
- 首选建议：用户执行 `git init` 后重跑。
