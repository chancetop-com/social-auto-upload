---
name: xiaohongshu-upload
description: 当 agent 需要通过已安装的 `sau` CLI 完成小红书登录、cookie 校验、视频上传或图文发布时使用这个 skill。该 skill 适用于已经安装 `social-auto-upload` 且可调用 `sau` 命令的环境。优先使用这个 skill 进行稳定的命令式小红书工作流，而不是一开始就阅读 uploader 源码。
license: MIT-0
slug: social-auto-upload-xiaohongshu-upload
displayName: 小红书视频与图文发布
version: 1.0.0
summary: 使用 sau 登录小红书并发布视频或图文。
---

# 小红书上传 Skill

优先把 `sau` 作为主接口。

不要假设当前环境一定能读取仓库源码。
不要一开始就去读 `uploader/`。
只有在命令不可用或 CLI 执行失败时，才回退到故障排查说明。

## 功能概览

| 功能 | 命令入口 | 说明 |
| --- | --- | --- |
| 小红书登录 | `sau xiaohongshu login --account <name>` | 生成或刷新指定账号的 cookie |
| cookie 校验 | `sau xiaohongshu check --account <name>` | 检查指定账号 cookie 是否有效 |
| 视频上传 | `sau xiaohongshu upload-video ...` | 上传并发布小红书视频 |
| 图文上传 | `sau xiaohongshu upload-note ...` | 上传并发布小红书图文 |

元数据约定：

- 视频使用 `title + desc + tags`
- 图文使用 `title + note + tags`

## 默认工作流

1. 先确认 `references/runtime-requirements.md` 里的运行前提。
2. 再确认 `references/cli-contract.md` 里的命令契约。
3. 执行匹配的 `sau xiaohongshu ...` 命令。
4. 如果命令失败，再看 `references/troubleshooting.md`。

## 支持动作

- 使用 `sau xiaohongshu login --account <name>` 登录小红书
- 使用 `sau xiaohongshu check --account <name>` 校验 cookie 是否有效
- 使用 `sau xiaohongshu upload-video ...` 上传小红书视频
- 使用 `sau xiaohongshu upload-note ...` 上传小红书图文

## 命令选择建议

- 当用户需要新的 cookie，或现有 cookie 已失效时，使用 `login`
- 当用户只需要确认 cookie 状态时，使用 `check`
- 当用户要发布视频时，使用 `upload-video`
- 当用户要发布图文时，使用 `upload-note`

## 执行前检查

- 先确认当前 shell 里是否可以调用 `sau`
- 如果 `sau` 不可用，按 `references/runtime-requirements.md` 里的回退方式处理
- 当用户明确指定无头或有头模式时，显式传 `--headless` 或 `--headed`
- 只有用户明确要求定时发布时，才使用 `--schedule`
- 如果登录流程生成了本地二维码图片，不要只把图片路径告诉用户
- 二维码图片本身就是给用户扫码的，优先直接把本地图片展示/发送给用户

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，小红书的 `check`、`upload-video` 和 `upload-note` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 仅作日志标签，缺省为 `profile_id`；`login` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明见 `docs/CLI.md` 的“托管浏览器模式（通用）”。

```bash
# MLX
export MLX_API_TOKEN="<token>"
sau xiaohongshu check --folder-id <folder_id> --profile-id <profile_id>
sau xiaohongshu upload-note --folder-id <folder_id> --profile-id <profile_id> \
  --images videos/1.png videos/2.png --title "图文标题" --note "正文" --tags 图文,测试

# AdsPower（--folder-id 可省略）
export ADSPOWER_API_KEY="$KEY"
sau xiaohongshu check --profile-id <profile_id>
sau xiaohongshu upload-note --profile-id <profile_id> \
  --images videos/1.png videos/2.png --title "图文标题" --note "正文" --tags 图文,测试
```

Profile 必须已人工登录且无待处理验证码/2FA；托管模式不授予定位权限，发布若依赖定位请先确认 Profile 配置。

## 参考文档

- 运行前提：`references/runtime-requirements.md`
- CLI 契约：`references/cli-contract.md`
- 故障排查：`references/troubleshooting.md`
