---
name: douyin-upload
description: 当 agent 需要通过已安装的 `sau` CLI 完成抖音登录、登录态检查、视频上传或图文发布时使用这个 skill。该 skill 适用于已经安装 `social-auto-upload` 且可调用 `sau` 命令的环境。优先使用这个 skill 进行稳定的命令式抖音工作流，而不是一开始就阅读 uploader 源码。
license: MIT-0
slug: social-auto-upload-douyin-upload
displayName: 抖音视频与图文发布
version: 1.0.0
summary: 使用 sau 登录抖音并发布视频或图文。
---

# 抖音上传 Skill

优先把 `sau` 作为主接口。

不要假设当前环境一定能读取仓库源码。
不要一开始就去读 `uploader/`。
只有在命令不可用或 CLI 执行失败时，才回退到故障排查说明。

## 功能概览

| 功能 | 命令入口 | 说明 |
| --- | --- | --- |
| 抖音登录 | `sau douyin login --account <name>` | 在专用持久化 Profile 完成登录 |
| 登录态检查 | `sau douyin check --account <name>` | 检查指定 Profile 登录态 |
| 视频上传 | `sau douyin upload-video ...` | 上传并发布抖音视频 |
| 图文上传 | `sau douyin upload-note ...` | 上传并发布抖音图文 |

元数据约定：

- 视频使用 `title + desc + tags`
- 图文使用 `title + note + tags`

## 默认工作流

1. 先确认 `references/runtime-requirements.md` 里的运行前提。
2. 再确认 `references/cli-contract.md` 里的命令契约。
3. 执行匹配的 `sau douyin ...` 命令。
4. 如果命令失败，再看 `references/troubleshooting.md`。

## 支持动作

- 使用 `sau douyin login --account <name>` 登录抖音
- 使用 `sau douyin check --account <name>` 检查 Profile 登录态
- 使用 `sau douyin upload-video ...` 上传抖音视频
- 使用 `sau douyin upload-note ...` 上传抖音图文

## 命令选择建议

- 当用户需要登录，或现有 Profile 登录失效时，使用 `login`
- 当用户只需要确认登录状态时，使用 `check`
- 当用户要发布视频时，使用 `upload-video`
- 当用户要发布图文时，使用 `upload-note`

## 执行前检查

- 先确认当前 shell 里是否可以调用 `sau`
- 如果 `sau` 不可用，按 `references/runtime-requirements.md` 里的回退方式处理
- 当用户明确指定无头或有头模式时，显式传 `--headless` 或 `--headed`
- 只有用户明确要求定时发布时，才使用 `--schedule`
- 如果登录流程生成了本地二维码图片，不要只把图片路径告诉用户
- 二维码图片本身就是给用户扫码的，优先直接把本地图片展示/发送给用户

## 本地 Profile 与结果处理

抖音 login/check/视频/图文及直接 uploader 使用 `browser_profiles/douyin/<原始别名>/<chrome|chromium>/`。默认系统 Chrome、有头；`LOCAL_CHROME_PATH` 非空优先，否则显式 `--local-browser chrome|chromium` > `LOCAL_BROWSER` > Chrome。显式 `--headed`/`--headless` > `LOCAL_CHROME_HEADLESS` > False，保留用户已有配置。只要求所选浏览器，失败不回退；Chrome 由用户安装，Chromium 用 `uv run patchright install --no-shell chromium`。预检与发布共用一个会话，浏览器保存完整状态，旧 Cookie JSON 不导入、读写或删除。

只有 login 引导扫码或验证；缺少 Profile、明确未登录/验证退出 `10`，网络、权限和页面故障退出 `1`。同别名可以重新登录另一真实账号，Chrome 与 Chromium 各自隔离。发布中遇到验证即结束本次任务；提交后退出 `10` 会附 `publish_attempted=true`，退出 `9` 表示结果未知，都先核对作品再决定重试。重建使用 `sau douyin reset-profile --account creator --browser-kind chrome`，无需 binary，拒绝占用，保留另一浏览器及历史结果；不会自动恢复发布任务。抖音没有 `--no-publish`，环境验证使用离线或受控页面，不能以真实提交验收。

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，抖音的 `check`、`upload-video` 和 `upload-note` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 被忽略，身份由 `profile_id` 决定；`login` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 托管忽略本地浏览器选择/路径，只采用上述 headless 来源；本地安装和资料不参与。
- 退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明见 `docs/CLI.md` 的“托管浏览器模式（通用）”。

```bash
# MLX
export MLX_API_TOKEN="<token>"
sau douyin check --folder-id <folder_id> --profile-id <profile_id>
sau douyin upload-video --folder-id <folder_id> --profile-id <profile_id> \
  --file videos/demo.mp4 --title "标题" --desc "简介" --tags tag1,tag2

# AdsPower（--folder-id 可省略）
export ADSPOWER_API_KEY="$KEY"
sau douyin check --profile-id <profile_id>
sau douyin upload-video --profile-id <profile_id> \
  --file videos/demo.mp4 --title "标题" --desc "简介" --tags tag1,tag2
```

Profile 必须已人工登录且无待处理验证码/2FA。

## 参考文档

- 运行前提：`references/runtime-requirements.md`
- CLI 契约：`references/cli-contract.md`
- 故障排查：`references/troubleshooting.md`
