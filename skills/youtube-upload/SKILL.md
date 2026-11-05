---
name: youtube-upload
description: 使用 social-auto-upload 的 `sau youtube` 登录 YouTube 并上传、安排定时或设置视频可见范围。Use when 用户要向 YouTube 发布或定时发布视频，或检查 Google/YouTube 登录状态。
license: MIT-0
slug: social-auto-upload-youtube-upload
displayName: YouTube 视频发布
version: 1.0.0
summary: 使用 sau 登录 YouTube 并上传或定时发布视频。
---

# YouTube 视频发布

调用现有 `sau youtube` CLI。登录在浏览器中完成 Google 账号登录，不使用二维码；账号名是本地会话别名。

```powershell
sau youtube login --account creator
sau youtube check --account creator
sau youtube upload-video --account creator --file videos/demo.mp4 --title "标题" --desc "简介" --tags tag1,tag2 --visibility public
```

标题最多 100 个字符。`--visibility` 可选 `public`、`unlisted`、`private`，默认 `public`；`--thumbnail` 指定封面，`--playlist` 指定已有播放列表。只有用户明确给出定时时间才传 `--schedule "YYYY-MM-DD HH:MM"`；该选项会使用 YouTube Studio 的 Schedule 状态，需核对页面显示的日期与时间。

## Multilogin X 模式（可选）

设置 `MLX_API_TOKEN` 后，`check` 和 `upload-video` 可以改用 Multilogin Profile。`--folder-id` / `--profile-id` 必填；`--account` 仅作日志标签，缺省为 `profile_id`。此时 CLI 不读写 `cookies/*.json`，`login` 会被拒绝并退出 `1`。

```bash
export MLX_API_TOKEN="<token>"

sau youtube check --folder-id <folder_id> --profile-id <profile_id>

sau youtube upload-video \
  --folder-id <folder_id> --profile-id <profile_id> \
  --file videos/demo.mp4 --title "标题" --desc "简介" --tags tag1,tag2 --visibility public
```

MLX 下 `YT_PROXY` / `--proxy` 会被忽略，出口 IP 由 Profile 决定。退出码：`0` 成功、`1` 运行失败、`2` 用法错误、`10` 需要人工登录、`130` 中断。Profile 必须已人工登录且无待处理验证码/2FA；部署前提、调度侧责任和账号一致性风险见仓库 `docs/CLI.md` 的 Multilogin X 模式。

发布前再次核对账号、视频、标题、说明、标签、可见范围及立即/定时意图。上传或发布遇到超时时先查 YouTube Studio 中的原视频，不盲目重传。上传成功不等于审核完成或公开视频已可播放。
