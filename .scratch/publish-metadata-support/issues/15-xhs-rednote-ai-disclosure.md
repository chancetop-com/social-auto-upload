# 15: 小红书与 Rednote 回读 AI 内容类型

Status: ready-for-agent
Resolution: completed
Blocked by: None (can start immediately)

## What to build

小红书和 Rednote 的 `upload-video`、`upload-note` 均能确认作者选中的 AI 内容类型。调用方通过终端知道是否满足本次声明以及失败时停在哪里。

## Acceptance criteria

- [ ] 从四条 `sau` 命令验证省略声明时保留页面预设，传 `--content-type ai` 时在菜单收起后读到「笔记含AI合成内容」。同时传 `--original` 可以继续。
- [ ] 同一次调用指定 `ai` 和 `marketing` 等互斥内容类型，在上传前退出 `2`。
- [ ] 受控页面分别模拟找不到声明项、终值为空和选中其他值。终端列出请求、实际读值和原因，退出 `1`，发布按钮点击零次。
- [ ] 用 `--no-publish` 在小红书视频与图文各取得一份菜单收起后的实机终值；Rednote 两种帖型沿用已有证据，并核对当前 CLI 的终端输出。成功保留已有不发布摘要。
- [ ] 更新八行 CLI 支持表中这四行的 AI 栏，分别注明网页证据、CLI 行为、样本账号、界面语言及观察阶段。

[发布元数据规格](../spec.md) · [AI 声明契约](04-ai-disclosure-contract.md#answer) · [八条命令的验收基线与输出](10-release-evidence.md#answer)
