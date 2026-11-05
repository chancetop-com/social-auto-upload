---
name: tiktok-upload
description: 使用 `sau tiktok` 通过 Multilogin X Profile 检查登录并发布 TikTok 视频。Use when 用户要发布 TikTok 视频，且 CLI 与 Multilogin 桌面应用在同一台机器。
license: MIT-0
slug: social-auto-upload-tiktok-upload
displayName: TikTok 视频发布
version: 1.0.0
summary: 使用 sau tiktok 和 Multilogin Profile 检查登录并发布视频。
---

# TikTok 视频发布

TikTok 仅支持 Multilogin X（MLX）模式，使用 `sau tiktok` CLI；没有本地浏览器或 cookie 文件路径。未设置 `MLX_API_TOKEN` 时，任何 `sau tiktok` 命令都会退出 `1`。

## 部署前提

- CLI 与 Multilogin 桌面应用在同一台 macOS/Windows 机器，桌面应用已启动。
- Profile 使用 Mimic 内核，已人工登录 TikTok，且没有待处理验证码或 2FA。
- Profile 界面语言必须为 **English (US)**；MLX 模式会跳过 CLI 内的语言切换。

## 命令

```bash
export MLX_API_TOKEN="<token>"

# 0=已登录，10=需要人工登录
sau tiktok check --folder-id <folder_id> --profile-id <profile_id>

sau tiktok upload-video \
  --folder-id <folder_id> --profile-id <profile_id> \
  --file videos/demo.mp4 --title "标题" --tags tag1,tag2 \
  --schedule "2026-10-21 10:30" --thumbnail covers/demo.png
```

- `--folder-id` / `--profile-id` 必填；`--account` 可选，仅作日志标签，缺省为 `profile_id`。
- 仅支持 `check` 和 `upload-video`；`login` 退出 `1`，请先在 Multilogin 应用中登录 Profile。
- TikTok 没有 `upload-note`，不要虚构该子命令。
- 不读写 `cookies/tk_uploader/*.json`；登录页、验证码或 2FA 退出 `10`；发布循环总超时为 15 分钟。
- 退出码：`0` 成功、`1` 运行失败、`2` 用法错误、`10` 需要人工登录、`130` 中断。

`TiktokVideo` 没有独立简介参数。定时发布使用 `--schedule "YYYY-MM-DD HH:MM"`；只有用户明确给出时间才传。MLX 只验证“已登录”，Profile 即身份，调度侧需确保 `profile_id` 与目标账号匹配。

每次发布前让用户确认账号、单条视频、标题、标签及立即/定时方式。页面布局或登录状态不符合预期时停止并报告；只有平台页面确认提交后才报告成功，未知结果先核查 TikTok Studio，不能直接重发。
