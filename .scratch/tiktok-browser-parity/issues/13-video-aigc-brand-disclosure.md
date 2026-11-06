# 13 — 视频 AI 标识与品牌声明

Status: resolved
Type: task
Blocked by: 10, 12
规格依据: spec.md §4.1、§4.4、§5.4、§6.1

## What to build

视频发布时可以显式声明 AI 生成内容、Your brand 或 Branded content。品牌任一为真时自动打开声明总开关，并同时设置两个复选框，避免页面残留上一次的勾选。请求与页面最终状态不一致就失败，不发布。

## Acceptance criteria

- [x] `--aigc` 与 `--no-aigc` 互斥；两者都不传时对 AIGC 控件零交互。
- [x] 首次开启 AIGC 出现 `Labeling AI-generated content` 引导时点击 `Turn on`，弹窗消失后回读 `aria-checked`。
- [x] AIGC 容器不存在但显式请求时退出 `1`，不把“缺失”当成“关闭”。
- [x] `--your-brand` 与 `--branded-content` 可同时为真；任一为真时自动打开 `Disclose post content`。
- [x] 品牌总开关打开后两个复选框都显式设置：请求为真的勾选，未请求的显式取消勾选。
- [x] `--branded-content` 搭配 `--privacy only-me` 时在启动浏览器前退出 `2`。
- [x] 品牌/AIGC 回读不一致时退出 `1`，stderr 含选项名、请求值与实际值。
- [x] 不传品牌/AIGC 参数时，旧 `upload-video` 不产生任何相关交互。

## Comments

- 2026-11-06：实现完成并合入 `integration/tiktok-browser-parity`（feature commit `d0ace31`）。TikTok 专项 188 tests 全绿；默认离线套件 726 tests，基线 5 failures + 1 error + 2 skips 均为既有、非 TikTok 问题。真实账号发布验收见 ticket 19，尚未执行。
