---
name: instabox-handoff
description: 为 Codex 项目创建可 Handoff 的兼容聊天，通过 Git 同步代码，并在本地与 Instabox SSH 云电脑之间继续开发。用于首次配置和连接 Instabox、创建兼容聊天、切到云端、切回本地或诊断交接失败。
---

# Instabox 开发空间交接

作为本地控制聊天，协调另一个开发聊天的创建、代码同步和原生 Handoff。用户说“用 Instabox 开一个可交接聊天”“把验证聊天切到云端继续”“切回本地”时执行相应动作；不因技能被加载就新建聊天或切换主机。

脚本路径均相对此 SKILL.md 所在目录，运行时替换为绝对路径。使用 `python3 scripts/handoff.py --help` 查看命令。用户配置和聊天索引存于 `~/.config/codex-instabox-handoff/profile.json`，可用 `--profile PATH` 指定其他配置；不存密码、令牌或私钥。

## 首次配置

用户尚未连接云电脑或要求从零配置时，先读 [setup.md](references/setup.md)，依次准备官方 CLI 登录、已有机器、SSH、远端 Codex 认证、共同 Git origin 与双端已保存项目。复用已有机器和账户配置；配置指南中的新建示例不等于授权购买或新建资源。配置就绪再进入下述流程。

## 选择目标

- 先运行 `profile`，再通过 Codex `list_projects` 核对实际已保存的项目、路径和 hostId。当前项目优先；跨项目调用时使用用户指定的项目/聊天。配置中的示例项目不自动代表当前业务项目。
- 聊天索引按 session 名保存最新 threadId、hostId、cwd。目标不明确且存在多个候选时，才询问用户。不能只按标题猜聊天。
- 使用 Codex 专用聊天工具；不要自动操作 Codex 自身界面或修改私有会话数据库。当前调用聊天不能交接自身：用户在开发聊天内要求交接时，说明需从另一个本地控制聊天发出同一条指令。

## 创建兼容聊天

仅在用户要求创建时执行。先按 [项目配置](references/workflow.md#项目配置) 准备两端共同 Git origin，并确认两端均已保存为 Codex 项目。接着：

```sh
python3 /绝对路径/instabox-handoff/scripts/handoff.py create --cwd /本地/项目 --title '项目开发（兼容交接）' --session 项目名
```

脚本通过官方 `codex app-server --stdio` 的 `thread/start` 显式指定 `historyMode=legacy`，不修改用户的全局默认模式、模型或权限。返回 ID 后，使用 `send_message_to_thread` 发送用户要求的开发指令；最终回复用 `::created-thread{threadId="返回的ID"}` 展示聊天入口。

当前实测 Codex Desktop 26.1013.40934：默认 paginated 聊天无法跨主机交接；legacy 兼容聊天已完成本地→Instabox→本地。升级后重新验证该约束，不能承诺普通旧聊天自动转换或一键无损转换。

## 本地 / 云端切换

读取 [交接步骤与错误处理](references/workflow.md#原生交接)，按原生工具的实际结果推进：

1. 确认目标是另一个 legacy 聊天，读取实际 cwd；检查源聊天是否仍在运行，避免在未保存工作中途打断。用户明确要求立即切换时可按其意图交接。
2. 需要云端时运行 `doctor --wake`。这只唤醒自动休眠的已有机器；显式停止/挂起的机器按用户切换意图使用官方 resume/start，不新建或购买机器。
3. `list_projects` 发现目标 SSH hostId。`handoff_thread` 必须显式指定目的 hostId；回本地用 `local`。省略目的主机会变成同主机 checkout/worktree 切换。云端指 SSH Instabox，不是 Codex 托管 Cloud 任务。
4. `get_handoff_status` 用 operationId、afterRevision、30000–60000ms 等待变化；无变化退避，不反复播报。仅成功才更新索引：`remember --session 名称 --thread 新ID --host-id 实际hostId --cwd 实际目标路径 --operation-id 操作ID`。
5. 原生交接会迁移聊天上下文、已跟踪改动及未跟踪文件，并创建新的 threadId / 托管 worktree。下一步始终使用新 ID 和实际 cwd。依赖、运行进程和凭证需在目标机器另行配置。
6. 用户要求“继续”时，把具体开发要求作为 followUpPrompt；否则仅交接，不擅自派发开发任务。验证主机名、cwd、代码及所需运行结果；遗留聊天读取用下面的 API 后备。

用户一句话要求“本地开始→云端继续→再回本地”时，按其指定的阶段任务串行完成，等待每阶段完成再交接；不在发送阶段任务后立刻迁移。若只说切换一次，则完成这一次切换。

legacy 的 `read_thread` / `wait_threads` 可能报 `thread/items/list is not supported yet`。改用：

```sh
python3 /绝对路径/instabox-handoff/scripts/handoff.py read --thread ID
python3 /绝对路径/instabox-handoff/scripts/handoff.py read --thread ID --ssh SSH别名
```

脚本只显示元数据、完成状态与末轮助手消息。独立读取中的 interrupted 且 completedAt 为空不充分证明运行失败；等待完成记录或原生工具结果。不要改写会话 JSONL。

## 独立代码同步

先读 [代码同步](references/workflow.md#代码同步)。Git 同步用于共享已提交代码；原生 Handoff 本身能迁移未提交改动，不必为切换强制先提交。

```sh
python3 /绝对路径/instabox-handoff/scripts/handoff.py sync --project 项目名 --direction to-cloud
python3 /绝对路径/instabox-handoff/scripts/handoff.py sync --project 项目名 --direction from-cloud
```

不加 `--apply` 时预览。用户明确要求同步时，代理检查后直接加 `--apply` 执行，不需要再索取一次确认。脚本检查 origin、干净工作树、分支和快进关系，执行 push / fetch / fast-forward，并核对两端 SHA。聊天在托管 worktree 时，必须传 `--source-cwd` / `--dest-cwd` 的实际路径；不要在保存项目根目录强行切换被其他 worktree 占用的分支。

脚本不提交、强推、硬重置或自动 stash。用户要求同步未提交工作时，先查看 diff，只提交任务范围内的文件；无关改动或分歧需保留并明确说明阻塞点。授权过的步骤不重复索取确认。不要把 SSH 私钥、Codex 登录态、.env 或凭证作为同步内容。

## 完成与边界

报告实际主机、聊天 ID、cwd、代码状态及验证结果。失败时区分代码已推送、聊天已迁移、目标续跑是否完成，不能把 dispatch 当成功。原生 Handoff 不可用时可以按用户意图同步代码/交接摘要，但需明确这没有完成原生聊天迁移。

浏览器登录遵循当前用户的浏览器工具和授权策略；日常已登录的 SSH、Git 和 App Server 流程无需浏览器。
