# 从零配置 Instabox 与 Codex SSH

适用：本机 macOS / Linux，Instabox Linux 云电脑，支持 SSH Connections 的 Codex 桌面应用。命令里的 `devbox`、`instabox-devbox`、`my-project` 是示例名称。机器规格、额度和界面文案以当前服务与客户端为准。

## 1. 检查本机工具

```sh
python3 --version
git --version
ssh -V
node --version
npm --version
codex --version
instabox --version
```

Python 需要 3.9+；Node.js 版本按当前 CLI 的要求安装。缺少 CLI 时：

```sh
npm install -g @openai/codex
npm install -g instabox
```

官方入口：[Codex](https://developers.openai.com/codex/)、[Instabox npm 包](https://www.npmjs.com/package/instabox)。本项目脚本仅使用 Python 标准库，不需要 OpenAI API Key；Codex 自身需有效登录和使用权限。

## 2. 登录并选择已有云电脑

```sh
instabox login --device
instabox whoami
instabox ls --json
```

在 CLI 指引的官方页面完成自己的设备授权，不转发密码、私钥或设备验证码。机器存在时直接复用。只有用户明确需要新机器且当前套餐允许时才创建，例如：

```sh
instabox create --name devbox --template agent-browser
```

检查所选机器：

```sh
instabox get devbox --json
```

自动空闲休眠可用 `instabox wake devbox`；显式挂起用 `instabox resume devbox`，已停止用 `instabox start devbox`。按实际状态选择，不反复新建机器或改套餐。

## 3. 配置并验证 SSH

```sh
instabox ssh-config devbox
```

这会输出官方生成的 Host block。先备份现有 `~/.ssh/config`，再将该 block 合并到其中，保留已有 Include 和其他主机。已经存在同名 alias 时更新对应块，不再追加冲突定义。示例 alias 为 `instabox-devbox`，实际以 CLI 输出为准。

使用生成的 HostName、Port、User、IdentityFile、CertificateFile 与 known_hosts；不要把机器 ID 当作 Linux 用户自行猜测，也不要替换生成的密钥或关闭 host key 验证。

```sh
ssh -T instabox-devbox 'hostname'
ssh -T instabox-devbox 'pwd'
```

证书过期时：

```sh
instabox ssh-cert devbox
```

### 可选：自动续期

Skill 安装目录中的 `scripts/renew_ssh.py` 会在证书有效期不足 10 分钟时调用官方 CLI 续期，用文件锁避免多个连接重复申请。它只负责证书，不创建机器或替你登录。

先从官方 Host block 确认 CertificateFile 和本机 CLI 的绝对路径，再手动验证：

```sh
python3 /ABSOLUTE/PATH/instabox-handoff/scripts/renew_ssh.py \
  --machine devbox \
  --cert /ABSOLUTE/PATH/machine-cert.pub \
  --cli /ABSOLUTE/PATH/instabox
```

若要接入 SSH，可在该主机 Host block 之前添加如下规则，替换所有绝对路径：

```sshconfig
Match originalhost instabox-devbox exec "/ABSOLUTE/PATH/python3 /ABSOLUTE/PATH/instabox-handoff/scripts/renew_ssh.py --machine devbox --cert /ABSOLUTE/PATH/machine-cert.pub --cli /ABSOLUTE/PATH/instabox"
Match all

# Below: retain the official Host block returned by instabox ssh-config.
```

保留可恢复的配置备份，然后重新测试 `ssh -T instabox-devbox 'hostname'`。不要将本机生成的 Host block、私钥或登录目录提交到此仓库。

## 4. 远端安装与认证 Codex

在云电脑终端确认 Node.js / npm 已安装，再安装 CLI：

```sh
ssh -t instabox-devbox
npm install -g @openai/codex
codex --version
codex login --device-auth
codex login status
exit
```

安装如需用户级 npm prefix，应确保其 bin 目录进入远端登录 shell 的 PATH。桌面连接通过远端登录 shell 启动 Codex；仅在某个交互终端里临时设置 PATH 不够。可在远端登录 shell 中检查 `command -v codex`，并在添加桌面连接后确认能够实际运行聊天。

远端单独使用官方登录流程，不把本机 `~/.codex/auth.json` 复制过去。设备登录若受账户策略限制，按官方认证说明选择允许的流程，不绕过策略。

## 5. 准备两端共同 Git 仓库

已有项目：保留现有 GitHub/GitLab 等 origin，用用户已有认证在两端 clone。**两端的原始 origin URL 必须完全一致**，不要一端 HTTPS、另一端 SSH。

没有共同仓库时，可使用 Instabox 持久磁盘上的专用 bare repo。下面适用于全新示例，已有目录一律不覆盖。

云端新建 bare repo：

```sh
ssh -T instabox-devbox 'mkdir -p /data/home/codex-git'
ssh -T instabox-devbox 'git init --bare --initial-branch=main /data/home/codex-git/my-project.git'
```

执行前确认该路径不存在。已有同名仓库时使用它或换新名称，不对未知目录运行初始化。

本机 clone、添加一个最小程序并首次提交：

```sh
git clone ssh://instabox-devbox/data/home/codex-git/my-project.git /ABSOLUTE/LOCAL/my-project
cd /ABSOLUTE/LOCAL/my-project
# 将本仓库 examples/app.py 复制为当前项目的 app.py。
# 确保 Git 的提交姓名与邮箱已按你的身份配置。
git add app.py
git commit -m 'Add workspace host probe'
git push -u origin main
```

云端从本地 bare 路径 clone，再保留共同 canonical origin，并添加云端直连的 `sync` remote：

```sh
ssh -T instabox-devbox 'git clone /data/home/codex-git/my-project.git /data/home/my-project'
ssh -T instabox-devbox 'git -C /data/home/my-project remote set-url origin ssh://instabox-devbox/data/home/codex-git/my-project.git'
ssh -T instabox-devbox 'git -C /data/home/my-project remote add sync /data/home/codex-git/my-project.git'
ssh -T instabox-devbox 'git -C /data/home/my-project fetch sync'
ssh -T instabox-devbox 'git -C /data/home/my-project branch --set-upstream-to=sync/main main'
```

这个额外 remote 避免云电脑经本机 alias 反向 SSH 自己，同时保留相同 origin 供 Codex 匹配。已有远程 Git 服务时，两端都使用原有 origin，无需增加 sync。

## 6. 在 Codex 保存两个项目

**先完成 Git origin 配置，再首次打开并保存项目。**

1. 确认本机终端 SSH 可用。
2. 桌面应用进入设置 → Connections → SSH，添加或启用 `instabox-devbox`。
3. 在该 SSH 主机下添加 `/data/home/my-project`，并保存为远程项目。
4. 将 `/ABSOLUTE/LOCAL/my-project` 保存为本地项目。
5. 请本地控制聊天通过 `list_projects` 核对两个已保存项目及返回的远端 hostId。

`codex app /path` 可能只打开目录；工具返回的已保存列表才是判据。当前工具无添加已保存项目接口时，由用户完成这一次界面操作。OpenAI 官方 [远程连接](https://learn.chatgpt.com/docs/remote-connections) 说明 SSH alias 发现、远端 Codex 安装认证和项目连接流程；具体入口随版本可能变化。

## 7. 配置 Skill 的项目索引

使用仓库 `examples/profile.example.json` 新建本机 `~/.config/codex-instabox-handoff/profile.json`；若文件已经存在，合并需要的字段，保留已有 projects 和 sessions。不要覆盖现有索引。

需要替换：

- instabox.machine / sshHost / cli：现有机器名、SSH alias、CLI 可执行路径。
- projects.my-project.localPath / remotePath：真实 Git 根目录，必须是绝对路径，不使用 `~` 或 `$HOME` 字面量。
- origin：两端完全一致的原始地址。
- localRemote / remoteRemote：普通服务用 origin/origin；上述 bare repo 示例用 origin/sync。
- hostId：由桌面工具 `list_projects` 实际发现的值，不由机器 ID 推导。

Skill 安装包保持自包含；若没有克隆本仓库，可按同目录 [workflow.md](workflow.md#项目配置) 中的 JSON 格式创建 profile。

然后验证：

```sh
python3 /ABSOLUTE/PATH/instabox-handoff/scripts/handoff.py profile
python3 /ABSOLUTE/PATH/instabox-handoff/scripts/handoff.py doctor --wake
```

doctor 应返回远端真实主机名、Linux、两端 Codex 版本。profile 不含认证数据，CLI 登录和 SSH key 继续由各自官方工具管理。

## 8. 创建并交接兼容聊天

从本地控制聊天请求：

```text
$instabox-handoff 为 my-project 创建可交接聊天，先在本地运行 app.py，然后到云端验证，最后切回本地。
```

完整验证方法见仓库的 [接力示例](https://github.com/jingchang0623-crypto/codex-instabox-handoff/blob/main/docs/handoff-walkthrough.md)。失败时按 [操作与排障](workflow.md) 检查，不篡改私有数据库或强制覆盖代码。
