# 12: 大陆版小红书和 Rednote 准备视频与图文草稿

Status: ready-for-agent
Blocked by: 07

## What to build

运营者从同一套 CLI 选择大陆版小红书或 Rednote，在对应平台已登录的创作中心准备视频或图文，并在发布前读回草稿。

## Acceptance criteria

- [ ] 从正式 `sau` 入口分别运行大陆版小红书和 Rednote 的 `upload-video`、`upload-note`，四项均传 `--no-publish`。使用模拟比特浏览器 Local API 和各自的受控创作中心页面。
- [ ] 逐项核对请求中的窗口 ID、实际进入的创作中心和新标签页归属。在对应页面观察到素材与编辑器就绪，并能读回本次草稿的标记。
- [ ] 四项均按各平台现有格式报告准备结果，核对 stdout、stderr 和退出码 `0`。两种素材在两个创作中心的最终提交次数均为零。

[比特浏览器托管模式规格](../spec.md) · [验收决定](05-acceptance.md)
