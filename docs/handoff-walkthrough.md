# 验证本地 → Instabox → 本地

目标是分别验证代码、聊天上下文与真实执行主机。准备条件见 [配置指南](../skills/instabox-handoff/references/setup.md)。使用专门的示例项目，避免拿有其他工作改动的业务仓库做演练。

## 先验证已提交代码的同步

在两端干净的、同名分支 checkout 上：

1. 本地修改 `app.py` 的 MESSAGE，运行 `python3 app.py`，只提交本次变更。
2. 从控制聊天请求同步到云端，或执行 `handoff.py sync --project my-project --direction to-cloud` 查看计划，再加 `--apply`。
3. 云端运行程序，确认 MESSAGE 更新；修改另一个字段并提交。
4. 同步回本地：`--direction from-cloud --apply`，再运行程序。
5. 核对两端 `git rev-parse HEAD` 相同。

同步脚本不替用户决定提交范围。dirty、detached、不同分支或分歧会阻止同步。源推送和目标快进不是跨机器事务；中间失败时按输出检查共同仓库及目标状态。

## 再验证原生 Handoff

这一步可保留任务内未提交及未跟踪文件，让原生交接验证工作改动的迁移，不必先 Git push。

向本地控制聊天发送类似指令：

```text
$instabox-handoff 在 my-project 创建一个名为“开发空间接力验证”的兼容聊天。
第一阶段在本地运行 app.py，记录主机名和工作目录，修改 MESSAGE，并创建未跟踪的 handoff-proof.json。
只在聊天中记住校验词“接力测试七号”，不要将它写到文件。
第二阶段交接到 Instabox：确认本地改动和未跟踪文件均存在，回忆校验词，再改 MESSAGE，运行程序并向 proof 追加 cloud 阶段。
第三阶段交回本地：确认云端最新改动和 proof 都存在，回忆校验词，运行程序并追加 local-return。
各阶段完成后再切换，结束时报告实际主机、cwd、聊天 ID 和 Git 状态。
```

不使用真实秘密做聊天标记。测试文件只记录 system、hostname、cwd 和 stage。

## 成功判据

| 维度 | 需要实际观察的结果 |
| --- | --- |
| 主机 | 本地系统 → Instabox Linux → 本地系统；各阶段 hostname/cwd 正确 |
| 代码 | 云端读到本地修改；返回后保留云端最新修改 |
| 未跟踪文件 | proof 三阶段存在且内容完整 |
| 聊天 | 两次交接后都能回忆仅在聊天中提供的校验词 |
| 原生操作 | 两次 get_handoff_status 明确成功，有新的目标 threadId 和 worktree |
| 续跑 | 目标任务实际执行完毕，而非仅发出了 followUpPrompt |

每次原生迁移都可能产生新的聊天 ID；控制聊天用 `remember` 更新 session 索引。不要向已迁移的旧聊天 ID 继续发送任务，也不要假设执行目录仍是侧边栏保存项目的根目录。

## 收尾

确认当前实际工作目录，检查 diff，然后按正常开发流程提交或保留改动。若为解决 checkout 分支冲突创建了命名 stash，记录其 SHA，人工比较后决定如何处理；不要自动 pop/drop 把起始版本覆盖到最新返回版本。

本机直接运行 `handoff.py create` 只创建 legacy 聊天并命名、记索引。发送任务、原生 Handoff 和等待状态由桌面 Skill 调用 Codex 工具完成，因此纯 CLI 或 CI 中不能仅靠这条脚本完成整个聊天迁移。
