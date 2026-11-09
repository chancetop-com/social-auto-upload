---
name: alipay-upload
description: 使用 social-auto-upload 的 `sau alipay` 登录支付宝生活号并发布视频。Use when 用户要向支付宝生活号发布视频或检查创作账号状态。
license: MIT-0
slug: social-auto-upload-alipay-upload
displayName: 支付宝生活号视频发布
version: 1.0.0
summary: 登录支付宝生活号并发布视频，支持封面与合集。
---

# 支付宝生活号视频发布

调用现有 `sau alipay` CLI。首次使用前，用户需要在支付宝内容创作后台登录并确认账号已开通生活号内容创作权限。

```powershell
sau alipay login --account creator
sau alipay check --account creator
sau alipay upload-video --account creator --file videos/demo.mp4 --title "标题" --desc "简介" --tags 生活号,测试
```

当前仅支持视频，不支持图文和定时发布。可选 `--thumbnail` 指定封面，`--collection` 指定已有合集。账号名是本地会话别名；登录需要扫码时，把二维码图片展示给用户。

发布前核对账号、素材、标题、简介和标签。不要把 CLI 返回“已提交”扩大解释成审核通过或公开可见；结果不确定时先查支付宝后台，不盲目重试。

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，`check` 和 `upload-video` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 仅作日志标签，缺省为 `profile_id`；`login` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明见 `docs/CLI.md` 的“托管浏览器模式（通用）”。
