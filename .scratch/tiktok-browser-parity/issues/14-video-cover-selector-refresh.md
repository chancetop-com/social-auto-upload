# 14 — 视频自定义封面选择器刷新

Status: resolved
Type: task
Blocked by: 10
规格依据: spec.md §5.2、§5.4、§11.1

## What to build

传 `--thumbnail` 时，视频自定义封面在新版封面编辑器里继续可用；不传时完全不碰封面控件。用户语义不变：指定一张本地图片作为视频封面，并确认服务端接受这次上传。

## Acceptance criteria

- [x] `--thumbnail` 仍接受现有路径校验；文件不存在时在启动浏览器前退出 `2`。
- [x] 打开 `Edit cover`，进入 `Upload cover`，选择本地图片，等待上传完成，点击保存并确认编辑器关闭。
- [x] 保存后保留现有 3 秒等待，再进入定时/发布。
- [x] 不传 `--thumbnail` 时对封面控件零交互。
- [x] 封面步骤失败时退出 `1`，stderr 能定位到控件名与阶段。
- [x] 不暴露按毫秒选帧、`--cover-ms` 或 `--cover-index`。

## Comments

- 2026-11-06：实现完成并合入 `integration/tiktok-browser-parity`（feature commit `4601c86`）。TikTok 专项 188 tests 全绿；默认离线套件 726 tests，基线 5 failures + 1 error + 2 skips 均为既有、非 TikTok 问题。真实账号发布验收见 ticket 19，尚未执行。
