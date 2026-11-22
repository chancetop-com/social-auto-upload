# 11: TikTok 和 Instagram 准备视频与图文草稿

Status: ready-for-agent
Resolution: completed
Blocked by: 07

## What to build

运营者可以把视频或图文准备到 TikTok 和 Instagram 编辑器中，通过 `--no-publish` 检查内容，取得各平台原有的准备结果。

## Acceptance criteria

- [ ] 从正式 `sau` 入口分别运行 TikTok 和 Instagram 的 `upload-video`、`upload-note`，四项均传 `--no-publish`，使用模拟比特浏览器 Local API 和受控平台页面。
- [ ] 每项核对 API 收到的窗口 ID、命令使用的新页、素材就绪状态与编辑器中可读回的本次草稿标记。TikTok 图文用例使用可用的 Photos 入口。
- [ ] 四项均退出 `0`，受控页面观察到的最终提交次数各为零。核对各自的 stdout、stderr 与平台结果，TikTok 有发布前检查通过的摘要，Instagram 报告 `prepared`。

[比特浏览器托管模式规格](../spec.md) · [验收决定](05-acceptance.md)

## Comments

已完成并合并到 `feat/bitbrowser-managed-mode`（最终集成 HEAD `6b5d490`）。离线契约证据：`tests/test_bitbrowser_tiktok_instagram_drafts.py`。真机验收由 14 独立跟踪。
