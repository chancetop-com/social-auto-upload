---
name: weibo-upload
description: 使用 social-auto-upload 的 `sau weibo` 登录微博并发布视频，可指定封面。Use when 用户要向微博发布视频或检查微博账号状态。
license: MIT-0
slug: social-auto-upload-weibo-upload
displayName: 微博视频发布
version: 1.0.0
summary: 使用 sau 登录微博并发布视频，可指定封面。
---

# 微博视频发布

调用现有 CLI，不另写网页上传流程。账号名是本地会话别名。

```powershell
sau weibo login --account creator
sau weibo check --account creator
sau weibo upload-video --account creator --file videos/demo.mp4 --title "标题" --desc "简介" --tags 微博,测试 --thumbnail covers/demo.png
```

当前仅支持视频，不支持图文和定时发布。标题最多 30 个字；封面建议小于 5 MB。登录时若出现二维码，展示二维码图片供用户扫码。完整参数以 `sau weibo upload-video --help` 为准。

发布前核对账号、视频、标题长度、简介、标签和封面。提交后只根据实际平台反馈报告结果；超时或状态不明时先在微博后台确认原作品，不重复上传。

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，`check` 和 `upload-video` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 仅作日志标签，缺省为 `profile_id`；`login` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明见 `docs/CLI.md` 的“托管浏览器模式（通用）”。
