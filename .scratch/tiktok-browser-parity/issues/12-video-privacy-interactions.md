# 12 — 视频隐私与互动开关

Status: ready-for-agent
Type: task
Blocked by: 10
规格依据: spec.md §4.1、§4.3、§4.4、§5.4、§6.1

## What to build

视频发布时可以显式设置隐私级别、关闭评论、关闭内容复用；不传就完全不动页面默认。显式设置后回读页面最终状态，只有一致才发布。这样运营可以发布“仅自己可见、禁评论、禁复用”的视频，同时旧命令行为不变。

## Acceptance criteria

- [ ] `--privacy` 只接受 `public` / `friends` / `followers` / `only-me`；非法值在启动浏览器前退出 `2`。
- [ ] 未传隐私/评论/复用任一选项时，对相应控件零交互；旧 `upload-video` 行为不变。
- [ ] 显式传值时设置控件并回读最终状态；一致才继续发布。
- [ ] 回读不一致时退出 `1`，stderr 含选项名、请求值与实际值，且不点击发布。
- [ ] 目标状态已满足但控件置灰时视为成功（例如账号已禁评论且有 `--no-comments`）。
- [ ] 隐私文案按公开/私有账号归一化：`Everyone`/`Public`、`Friends`、`Followers`、`Only you`/`Private`；账号类型不匹配时严格失败，不回退、不降级。
- [ ] `--disable-reuse` 是单开关；测试与后续文档都体现它同时影响 Duet、Stitch、Stickers、Story。
- [ ] CLI → 请求对象 → 上传选项的映射保持三态：未传为 `None`，不得提前填默认值。
