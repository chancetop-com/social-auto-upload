---
name: xiaohongshu-upload
description: 当 agent 需要通过已安装的 `sau` CLI 完成小红书登录、登录态检查、视频上传或图文发布时使用这个 skill。该 skill 适用于已经安装 `social-auto-upload` 且可调用 `sau` 命令的环境。优先使用这个 skill 进行稳定的命令式小红书工作流，而不是一开始就阅读 uploader 源码。
license: MIT-0
slug: social-auto-upload-xiaohongshu-upload
displayName: 小红书视频与图文发布
version: 1.0.0
summary: 使用 sau 登录小红书并发布视频或图文。
---

# 小红书上传 Skill

若调度器已预下载远程素材，在上传命令中传 `--task-id <原任务ID> --prepared-media-only` 并沿用完整 URL。命令只读取该任务的缓存，缺少任一远程文件时在进入平台前退出 `1`。本地文件仍按原路径读取。

优先把 `sau` 作为主接口。

不要假设当前环境一定能读取仓库源码。
不要一开始就去读 `uploader/`。
只有在命令不可用或 CLI 执行失败时，才回退到故障排查说明。

## 功能概览

| 功能 | 命令入口 | 说明 |
| --- | --- | --- |
| 小红书登录 | `sau xiaohongshu login --account <name>` | 在指定本地 Profile 中扫码登录 |
| 登录态检查 | `sau xiaohongshu check --account <name>` | 检查指定 Profile 的平台登录态 |
| 视频上传 | `sau xiaohongshu upload-video ...` | 上传并发布小红书视频 |
| 图文上传 | `sau xiaohongshu upload-note ...` | 上传并发布小红书图文 |

元数据约定：

- 视频使用 `title + desc`，公开话题写成 `desc` 里的 `#话题`
- 图文使用 `title + note`，公开话题写成 `note` 里的 `#话题`；旧 `--tags` 已移除，传入会退出 `2`

本地模式按平台、原始账号别名和浏览器种类保存专用持久化 Profile；默认系统 Chrome、有头，已有 `LOCAL_CHROME_HEADLESS` 配置仍生效。只有 `login` 引导登录，其他动作缺少 Profile 或明确未登录时退出 `10`。别名可以重新登录不同真实账号，Chrome 与 Chromium 登录态独立。

## 默认工作流

1. 先确认 `references/runtime-requirements.md` 里的运行前提。
2. 再确认 `references/cli-contract.md` 里的命令契约。
3. 执行匹配的 `sau xiaohongshu ...` 命令。
4. 如果命令失败，再看 `references/troubleshooting.md`。

## 支持动作

- 使用 `sau xiaohongshu login --account <name>` 登录小红书
- 使用 `sau xiaohongshu check --account <name>` 检查平台登录态是否有效
- 使用 `sau xiaohongshu upload-video ...` 上传小红书视频
- 使用 `sau xiaohongshu upload-note ...` 上传小红书图文

## 命令选择建议

- 当用户需要登录或更换 Profile 内的账号时，使用 `login`
- 当用户只需要确认登录态时，使用 `check`
- 当用户要发布视频时，使用 `upload-video`
- 当用户要发布图文时，使用 `upload-note`

## 执行前检查

- 先确认当前 shell 里是否可以调用 `sau`
- 如果 `sau` 不可用，按 `references/runtime-requirements.md` 里的回退方式处理
- 先选定来源：`LOCAL_CHROME_PATH` 优先；无路径时 `--local-browser chrome|chromium` 优先于 `LOCAL_BROWSER`，缺省为 Chrome。安装只需满足选定来源，失败时按诊断修复该来源。
- 当用户明确指定无头或有头模式时，显式传 `--headless` 或 `--headed`
- 验证发布前流程时显式传 `--no-publish`；它会真实上传素材、编辑并等待 ARM 就绪，可能留下临时素材或草稿。
- 用户明确要求重建本地资料时使用 `reset-profile --account <name> --browser-kind chrome|chromium`；只清空指定种类，不重跑旧任务。
- 只有用户明确要求定时发布时，才使用 `--schedule`
- 如果登录流程生成了本地二维码图片，不要只把图片路径告诉用户
- 二维码图片本身就是给用户扫码的，优先直接把本地图片展示/发送给用户

## 发布声明（可选）

`upload-video` / `upload-note` 默认不操作任何声明，需要时再显式传参：

- `--original` / `--no-original`：开启或关闭原创声明；
- `--content-type`：`fiction`（虚构演绎）、`ai`（AI 合成）、`marketing`（营销广告）、`self-shot`（自主拍摄）、`repost`（来源转载）；
- `--content-type repost` 必须同时提供 `--repost-source <媒体名称>`；
- `--content-type self-shot` 必须同时提供 `--shoot-location <地点>` 与 `--shoot-date <YYYY-MM-DD>`；
- 原创与来源转载互斥；组合错误会在启动浏览器前退出 `2`。

```bash
sau xiaohongshu upload-note --account <name> \
  --images videos/demo1.png videos/demo2.png --title "图文标题" --content-type ai
```

## 托管浏览器模式（可选）

兼容 CLI 在同一台机器、同一操作系统用户下默认共享托管 Profile。不同平台各用新页，同一平台上的检查和发布合计限一条，冲突退出 `1`。大陆版小红书与 Rednote 分别计数。最后一条命令离开时关闭整个 Profile，包括桌面原有的标签页。

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，小红书的 `check`、`upload-video` 和 `upload-note` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 都被忽略：不参与身份、日志标签或 cookie 文件，身份由 `profile_id` 决定；`login` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明见 `docs/CLI.md` 的“托管浏览器模式（通用）”。

```bash
# MLX
export MLX_API_TOKEN="<token>"
sau xiaohongshu check --folder-id <folder_id> --profile-id <profile_id>
sau xiaohongshu upload-note --folder-id <folder_id> --profile-id <profile_id> \
  --images videos/demo1.png videos/demo2.png --title "图文标题" --note "正文 #图文 #测试"

# AdsPower（--folder-id 可省略）
unset MLX_API_TOKEN
export ADSPOWER_API_KEY="$KEY"
sau xiaohongshu check --profile-id <profile_id>
sau xiaohongshu upload-note --profile-id <profile_id> \
  --images videos/demo1.png videos/demo2.png --title "图文标题" --note "正文 #图文 #测试"
```

Profile 必须已人工登录且无待处理验证码/2FA；托管模式不授予定位权限，发布若依赖定位请先确认 Profile 配置。

## 参考文档

- 运行前提：`references/runtime-requirements.md`
- CLI 契约：`references/cli-contract.md`
- 故障排查：`references/troubleshooting.md`
