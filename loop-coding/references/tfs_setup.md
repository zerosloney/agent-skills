# TFS 前置条件

loop-coding 只使用 `tf status / checkout / undo / shelve / unshelve`，禁止自动 `tf checkin`。

## 必要条件

1. `tf` 在 PATH 中。
2. 用户已执行 `tf login`。
3. 当前目录位于 TFS workspace 映射内。

如需 collection：

```bash
tf login /collection:http://server:8080/tfs/DefaultCollection
```

## 检测流程

1. `.git` -> Git；`.tf` -> TFS；否则 other。
2. TFS 首次实际调用时运行 `tf status /recursive` 或 `tf workspaces /format:detailed`。
3. 认证失败（401 / TF30063）-> 暂停，提示重新 `tf login`。
4. 网络失败（TF40049 / TF31002）-> 暂停，提示检查网络/服务器。
5. 成功后校验 workspace 映射。

## Workspace 校验

解析 `tf workspaces` 的 `Working folders`，确认 `project_root` 位于某个 local path 下。Windows 不区分大小写。

不匹配时报告检测到的 workspace、本地路径和当前目录，要求用户创建/映射 workspace 或移动项目。

匹配后写入 `.loop-state.json.config.tfs_workspace`。

## 凭证与配置

当前推荐只用 `tf login`。loop-coding 不保存 TFS 密码，也不要求 `~/loop_coding_tfs_config.json`。

`templates/tfs_config.example.json` 仅为旧版兼容和测试保留。
