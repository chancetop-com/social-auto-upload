---
name: kuaishou-upload
description: 当 agent 需要通过已安装的 `sau` CLI 完成快手登录、Profile 检查、视频上传、图文发布或 Profile 重建时使用这个 skill。该 skill 适用于已经安装 `social-auto-upload` 且可调用 `sau` 命令的环境。优先使用这个 skill 进行稳定的命令式快手工作流，而不是一开始就阅读 uploader 源码。
license: MIT-0
slug: social-auto-upload-kuaishou-upload
displayName: 快手视频与图文发布
version: 1.0.0
summary: 使用 sau 登录快手并发布视频或图文。
---

# 快手上传 Skill

优先把 `sau` 作为主接口。

不要假设当前环境一定能读取仓库源码。
不要一开始就去读 `uploader/`。
只有在命令不可用或 CLI 执行失败时，才回退到故障排查说明。

## 功能概览

| 功能 | 命令入口 | 说明 |
| --- | --- | --- |
| 快手登录 | `sau kuaishou login --account <name>` | 在所选本地 Profile 扫码登录 |
| 登录检查 | `sau kuaishou check --account <name>` | 检查所选 Profile 的当前登录态 |
| 视频上传 | `sau kuaishou upload-video ...` | 上传并发布快手视频 |
| 图文上传 | `sau kuaishou upload-note ...` | 上传并发布快手图文 |

元数据约定：

- 视频使用 `title + desc + tags`
- 图文使用 `title + note + tags`

## 默认工作流

1. 先确认 `references/runtime-requirements.md` 里的运行前提。
2. 再确认 `references/cli-contract.md` 里的命令契约。
3. 执行匹配的 `sau kuaishou ...` 命令。
4. 如果命令失败，再看 `references/troubleshooting.md`。

## 支持动作

- 使用 `sau kuaishou login --account <name>` 登录快手
- 使用 `sau kuaishou check --account <name>` 检查当前登录态
- 使用 `sau kuaishou upload-video ...` 上传快手视频
- 使用 `sau kuaishou upload-note ...` 上传快手图文

## 命令选择建议

- 当用户需要登录，或当前登录态已失效时，使用 `login`
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

## 本地 Profile

login/check/视频/图文统一使用 `browser_profiles/<chrome|chromium>/kuaishou/<原始别名>/`。只有 login 创建资料并引导扫码；Profile 是唯一登录态来源，旧 JSON 不读取、写回或自动迁移。一个别名可重新登录其他真实账号；两种浏览器独立，同一 Profile 同时仅一个任务使用。

默认系统 Chrome、有头；显式 `--headless` / `--headed` > `LOCAL_CHROME_HEADLESS` > False。`LOCAL_CHROME_PATH` 优先并按真实产品选资料，否则 `--local-browser` > `LOCAL_BROWSER` > chrome。只安装所选来源，失败不回退；保留已有配置、当前语言和自然窗口。完整 Chromium 安装方式见运行前提。

缺少 Profile 或明确未登录退出 `10`，安排 `sau kuaishou login --account <name> --headed`；`reason=verification` 表示先完成人机验证。网络、权限、页面结构故障退出 `1`。收到 `publish_attempted=true` 或退出 `9` 时，先核查作品，禁止自动重发。快手没有 `--no-publish`，上传命令会真实提交。

用户明确要求重建时运行 `sau kuaishou reset-profile --account <name> --browser-kind chrome`（或 chromium）。无需 browser binary，只清空明确目标；占用时停止，不自动清锁。重建不授权重新提交旧任务。

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，`check`、`upload-video` 和 `upload-note` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 被忽略（仅记录在启动日志 ignored 列）；身份和结果标签使用 `profile_id`；`login` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 托管仅采用上述 headless 来源，忽略本地 browser/path，不访问本地 Profile；只停止本次启动的 Profile。两个凭据同时设置退出 `1`；请求限流退出 `11`，交给调度层退避，CLI 不重试。
- MLX / AdsPower 需与 CLI 同机、桌面客户端和本地 API 可用；AdsPower 需付费版与 Chromium Profile。提前在对应应用登录并完成验证。

## 参考文档

- 运行前提：`references/runtime-requirements.md`
- CLI 契约：`references/cli-contract.md`
- 故障排查：`references/troubleshooting.md`
