# 验证范围

## 真实环境基线

首次真实往返验证日期：2026-10-21。

| 组件 | 实测版本 / 环境 |
| --- | --- |
| 桌面应用 | 26.1013.40934 |
| 本地 CLI | codex-cli 0.156.1 |
| 远端 CLI | codex-cli 0.160.0 |
| Instabox npm 分发包 | 0.6.3 |
| 本地 / 远端 | macOS Darwin / Instabox Linux |

这不是最低版本承诺或全平台支持矩阵。用户需检查当前客户端的 SSH 入口、工具和本机协议；升级后重新验证实验性 historyMode 支持。

## 已完成的真实验证

- 官方 App Server stdio 能创建 historyMode=legacy 的持久聊天并命名、读取。
- 默认 paginated 聊天在原生跨主机迁移时失败，错误为分页聊天不能在另一台主机继续。
- legacy 聊天完成本地→Instabox→本地原生 Handoff。
- 本地未提交的跟踪文件修改与未跟踪文件迁到云端，云端新增修改再带回本地。
- 仅在聊天中出现、未写入项目文件的非敏感校验词，在两次交接后均能被回忆。
- 最终程序在返回的本地 worktree 实际运行；proof 包含三阶段，主机系统依次为 Darwin、Linux、Darwin。
- 已提交代码完成两端 push / fast-forward 往返，最终 SHA 一致。
- 安装后的 helper 实际连接 SSH、读取已有 legacy 聊天并更新索引；干净示例仓库完成真实双向幂等同步。

公开仓库只发布结果和复现方法，不发布私人聊天记录、真实机器标识、认证目录、个人路径或原始 App Server 快照。

## 自动化测试

```sh
python3 -m unittest discover -s tests -v
```

测试包含真实的临时 Git 仓库操作；SSH 传输端用本机包装器模拟，以测试远端命令引用及空格路径，不需要网络。另有模拟 App Server、临时 OpenSSH 测试证书和隔离 Skill 安装目录。

覆盖重点：预览无推送、代码双向变更、dirty 拒绝、分支分歧保留、legacy 协议字段、无权限/模型覆盖、重复 session 拒绝、输出不暴露 reasoning 项、SSH 参数拒绝、证书临期更新与有效证书跳过、安装覆盖保护与升级备份。

自动化结果不等同于远端登录、桌面 Handoff 或模型续跑成功。真实交接需要在有对应工具和已保存项目的桌面客户端按 [接力示例](handoff-walkthrough.md) 完成。

## 来源与观察

- 官方 SSH 行为说明：[OpenAI Remote connections](https://learn.chatgpt.com/docs/remote-connections)。
- 官方 JSON-RPC / stdio 接口说明：[Codex App Server](https://developers.openai.com/codex/app-server)。
- historyMode 字段以实测 CLI 的 `codex app-server generate-json-schema --out /临时/目录 --experimental` 输出为准。
- origin 检测缓存、legacy 读取兼容性、目标 checkout 分支冲突等是指定版本的实际观察，详见 [workflow.md](../skills/instabox-handoff/references/workflow.md)，不是官方未来行为保证。
