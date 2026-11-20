# 16: TikTok 区分 AI 开关已关、缺失和读值失败

Status: ready-for-agent
Resolution: completed
Blocked by: None (can start immediately)

## What to build

`sau tiktok upload-video` 与 `upload-note` 保留 `--aigc` / `--no-aigc`。调用方能分别看出页面已关、操作后关闭和确实找不到入口。

## Acceptance criteria

- [ ] 两种帖型省略参数时保留页面当前值。显式开启须读到开启才可继续。两个方向同时传入时在上传前退出 `2`。
- [ ] 显式关闭时分别覆盖原本已关、操作后读到关、可操作编辑器中确认入口缺失。第三种结果标 `default_off` 和 `entry_missing`，终值为未知。
- [ ] 视频与 Photos 各用受控页面复现关闭请求遇到入口缺失，以及可见开关禁用且仍为开。前者可继续，后者退出 `1`。可见但无法读值也须失败，失败现场发布按钮点击零次。
- [ ] 从命令核对终端的请求值、终值、可否继续和原因，并保留原成功摘要。实机以 `--no-publish` 停止，文档在两条命令的 AI 栏分别注明 CLI 接入、账号样本、语言和证据阶段。

[发布元数据规格](../spec.md) · [AI 声明契约](04-ai-disclosure-contract.md#answer) · [八条命令的验收基线与输出](10-release-evidence.md#answer)
