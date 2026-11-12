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

标题最多 100 个字符。`--visibility` 可选 `public`、`unlisted`、`private`，默认 `public`；`--thumbnail` 指定封面，`--playlist` 指定已有播放列表。当前只支持立即发布；`--schedule` 尚未实现，传入会退出 `2`。

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，`check` 和 `upload-video` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 仅作日志标签，缺省为 `profile_id`；`login` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明见 `docs/CLI.md` 的“托管浏览器模式（通用）”。

```bash
# MLX
export MLX_API_TOKEN="<token>"
sau youtube check --folder-id <folder_id> --profile-id <profile_id>
sau youtube upload-video --folder-id <folder_id> --profile-id <profile_id> \
  --file videos/demo.mp4 --title "标题" --desc "简介" --tags tag1,tag2 --visibility public

# AdsPower（--folder-id 可省略）
export ADSPOWER_API_KEY="$KEY"
sau youtube check --profile-id <profile_id>
sau youtube upload-video --profile-id <profile_id> \
  --file videos/demo.mp4 --title "标题" --desc "简介" --tags tag1,tag2 --visibility public
```

托管模式下 `YT_PROXY` / `--proxy` 会被忽略，出口 IP 由 Profile 决定。Profile 必须已人工登录且无待处理验证码/2FA。

发布前再次核对账号、视频、标题、说明、标签、可见范围及立即/定时意图。上传或发布遇到超时时先查 YouTube Studio 中的原视频，不盲目重传。上传成功不等于审核完成或公开视频已可播放。
