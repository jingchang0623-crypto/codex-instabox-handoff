# 操作细节

## 项目配置

`handoff.py profile` 显示本地配置。配置格式如下；路径、origin、hostId 应来自真实项目和 `list_projects`，不是从示例猜测。使用普通文件编辑工具维护此公开元数据文件；写入时保留其他项目和 session。

```json
{
  "schemaVersion": 1,
  "instabox": {"machine": "devbox", "sshHost": "instabox-devbox", "cli": "/绝对路径/instabox"},
  "projects": {
    "项目名": {
      "localPath": "/本地/项目",
      "remotePath": "/data/home/项目",
      "origin": "两端完全一致的原始 origin URL",
      "localRemote": "origin",
      "remoteRemote": "origin",
      "sshHost": "instabox-devbox",
      "hostId": "从 list_projects 获取"
    }
  },
  "sessions": {}
}
```

- 保留已有业务仓库 origin。没有共同服务器时，可在现有 Instabox `/data/home/codex-git/<项目>.git` 新建专用 bare repo，绝不覆盖已存在的路径；两端 clone 并配置同一 canonical origin。
- 例如本机会通过 `ssh://instabox-devbox/data/home/codex-git/<项目>.git` 访问 bare repo；云端仍保留这个原始 origin 用于 Codex 项目匹配，但另加 `sync` remote 指向 `/data/home/codex-git/<项目>.git`，cloud 的 remoteRemote 填 sync。不要使用 insteadOf 掩盖 origin。
- **先配 origin，再首次保存 Codex 项目**。当前客户端 origin 检测有 24 小时缓存。保存后再改 origin 可能仍匹配旧地址；可用新目录克隆、配好 origin 后重新保存。不要篡改缓存、强制关闭整个 Codex 或覆盖现有 checkout。
- `codex app PATH` 可能只打开目录。以 `list_projects` 为准；当前无添加已保存项目 API，必要时请用户在侧边栏保存已准备好的本地路径和 SSH 路径，并解释这一具体限制。已保存过的不重复要求。
- 新开发任务可从干净 checkout 建专用 feature 分支，减少 main 与多个 worktree 冲突；保留现有分支选择，不强制重命名正在开发的分支。
- 复用现有机器、SSH alias 与远端 Codex 登录；不复制本机 auth.json。证书由官方 `instabox ssh-cert <machine>` 更新，SSH host key 验证保持开启。

## 原生交接

工具通过 ALL_TOOLS 查找 `list_projects`、`handoff_thread`、`get_handoff_status`、`send_message_to_thread`，依各自实时 schema 调用。当前工具描述的 destinationHostId 有时仅列 local，但本机实测接受 `list_projects` 返回的 `remote-ssh-discovered:instabox-devbox`。仅尝试实际发现的 hostId；若当前工具层拒绝该值，报告限制，不编造 ID 或绕过工具校验。

调用示意：

```js
handoff_thread({threadId: currentTargetId, destinationHostId: discoveredHostId,
  followUpPrompt: userRequestedContinuation});
get_handoff_status({operationId, afterRevision: revision, waitMs: 30000});
```

原生完成后，`remember` 会用目标机器的官方 API 验证 threadId、legacy 和 cwd 后写索引。目标数据尚未可读时保留 operationId 和新 ID，等待后再重试，不能回退到旧聊天继续发送。

| 实际错误 | 处理 |
| --- | --- |
| 分页聊天不能在另一台主机继续 | 不重复交接。说明兼容格式要求；用户要求新建时创建 legacy，并可将允许的工作摘要交给新聊天。不能声称旧聊天完整迁移。 |
| No matching saved project | 比对真实 origin、保存列表和缓存；按“项目配置”准备新克隆。 |
| pending composer state | 防止丢失草稿。请用户查看目标聊天草稿/队列；若用户已确认均为空，重新打开该聊天后重试一次。不编辑私有草稿存储。 |
| Destination checkout already using handoff branch / cannot switch to default branch | 检查该目标项目 worktree、branch、status。已知源 checkout 留下的本任务改动可用唯一命名 `git stash push --include-untracked -m ...` 保存后重试，记录 stash SHA；不自动 pop/drop，不 stash 无关工作。范围不明则询问。 |
| SSH 证书过期 / machine paused | 使用 doctor、官方 CLI 和 renew_ssh.py，复用已有机器。显式停止需按用户意图 resume/start，不创建付费资源。 |
| 未知或重复失败 | 根据新证据做一次有针对性的修复；同一错误无新证据停止重试，保留 Git 状态和 operationId，报告具体阻塞。 |

返回本地后，核对本机运行输出及云端最新改动；仅有“本地聊天出现”不足以证明代码和上下文迁移成功。需要验证聊天上下文时用用户允许的非敏感标记，不要求模型暴露隐藏推理。

## 代码同步

`sync` 默认只预览；加 `--apply` 执行。用户明确要求同步时，代理可在检查预览后直接加 --apply，无需重复确认。源/目的定义：to-cloud 为 local→remote；from-cloud 为 remote→local。

每端检查 Git 根、origin、分支、已跟踪与未跟踪改动；拒绝 dirty 或 detached checkout。对选定项目的 sourceRemote 推送源提交，再在目标从 destRemote 获取该分支，验证目标 HEAD 是源提交祖先后执行 `merge --ff-only`。最后检查两端 HEAD 相同。脚本不修改 remote 或 upstream。分享预览前检查 Git URL 是否内嵌凭证；不要使用带密码/token 的 Git URL。

目标发生分歧时，源提交可能已安全推到共同仓库，目标工作树保持原状。报告这个中间状态，不能声称同步完成。先处理分歧再重试，不自动 rebase/force。暂停两端并发编辑后同步；这不是跨机器事务或实时文件镜像。

## 本机验证基线

2026-10-21：Desktop 26.1013.40934 / local codex-cli 0.156.1 / remote 0.160.0。
已验证官方 stdio `thread/start(historyMode=legacy)`、`thread/name/set`、`thread/read(includeTurns=true)`；默认 paginated 的原生跨主机交接失败，legacy 的 Darwin→Linux→Darwin 成功，包含未提交和未跟踪文件及仅存在于聊天的上下文。

`codex app-server proxy` 在本机无 managed daemon socket 时初始化挂起，因此使用独立 `--stdio` 子进程；只终止脚本自己启动的子进程。App Server 参数变更时，用安装的 `codex app-server generate-json-schema --out <临时目录> --experimental` 检查官方协议，不修改内部会话文件。
