---
name: tiktok-upload
description: 使用 `sau tiktok` 在本地 cookie 模式或 Multilogin X Profile 下检查登录并发布 TikTok 视频与图文。Use when 用户要发布 TikTok 视频或图文。
license: MIT-0
slug: social-auto-upload-tiktok-upload
displayName: TikTok 视频与图文发布
version: 1.1.0
summary: 使用 sau tiktok 在本地模式或 Multilogin Profile 下检查登录并发布视频与图文。
---

# TikTok 视频与图文发布

TikTok 支持两种模式，使用同一个 `sau tiktok` CLI：

- **本地模式**（默认）：不设置 `MLX_API_TOKEN`，使用本地 Chromium 与 `cookies/tiktok_<account>.json`。`--account` 必填，`--folder-id` / `--profile-id` 忽略。
- **Multilogin X（MLX）模式**：设置非空 `MLX_API_TOKEN`，并要求 `--folder-id` / `--profile-id`。

## 部署前提

**本地模式**
- CLI 所在机器可运行 Chromium（Patchright）。
- 首次使用先运行 `sau tiktok login --account <name>`：会打开有头浏览器，人工完成 TikTok 登录后回到终端按 Enter 保存 cookie。
- 图文（`upload-note`）要求账号已被 TikTok Studio 的 Photos tab 灰度覆盖。

**Multilogin 模式**
- CLI 与 Multilogin 桌面应用在同一台 macOS/Windows 机器，桌面应用已启动。
- Profile 使用 Mimic 内核，已人工登录 TikTok，且没有待处理验证码或 2FA。
- Profile 界面语言必须为 **English (US)**；MLX 模式会跳过 CLI 内的语言切换。
- 图文（`upload-note`）还要求账号已被 TikTok Studio 的 Photos tab 灰度覆盖；没有入口时命令在选文件前退出 `1`。

## 命令

```bash
# 本地模式：先登录一次
sau tiktok login --account creator
# 0=已登录，1=无效
sau tiktok check --account creator
sau tiktok upload-video --account creator --file videos/demo.mp4 --title "标题"
sau tiktok upload-note --account creator --images images/1.jpg images/2.png

# Multilogin 模式
export MLX_API_TOKEN="<token>"

# 0=已登录，10=需要人工登录
sau tiktok check --folder-id <folder_id> --profile-id <profile_id>

# 视频：新选项都可选，不传即保持页面默认
sau tiktok upload-video \
  --folder-id <folder_id> --profile-id <profile_id> \
  --file videos/demo.mp4 --title "标题" --tags tag1,tag2 \
  --privacy public --no-comments --disable-reuse --aigc --your-brand \
  --schedule "2026-10-21 10:30" --thumbnail covers/demo.png

# 图文：1–35 张本地图片，按传入顺序展示，第 1 张即封面
sau tiktok upload-note \
  --folder-id <folder_id> --profile-id <profile_id> \
  --images images/1.jpg images/2.png \
  --title "图文标题" --note "图文正文" --tags 图文,测试 \
  --privacy friends --no-comments --aigc
```

- 本地模式必填 `--account`；MLX 模式 `--account` 可选，仅作日志标签，缺省为 `profile_id`。
- 支持 `check`、`upload-video`、`upload-note`；`login` 仅本地模式，MLX 下退出 `1`。
- 本地模式读写 `cookies/tiktok_<account>.json`；MLX 模式不读写 cookie 文件。
- MLX 下登录页、验证码或 2FA 退出 `10`，本地模式按运行失败退出 `1`；两种模式的发布循环总超时均为 15 分钟。
- 真实账号的本地登录与发布**待验收**；首次使用请先用测试账号验证。

## 视频参数

- `--privacy`：`public` / `friends` / `followers` / `only-me`；不传则保持页面默认。账号类型与选项不匹配时会回读失败并退出 `1`。
- `--no-comments`：关闭评论。
- `--disable-reuse`：关闭内容复用，同时影响 Duet、Stitch、Stickers 和 Story。
- `--aigc` / `--no-aigc`：开启/关闭 AI 生成内容标识；两者互斥，不传则保持页面默认。
- `--your-brand` / `--branded-content`：品牌内容声明；可同时使用。`--branded-content` 不能与 `--privacy only-me` 同时使用（退出 `2`）。
- `--thumbnail`：自定义视频封面。
- 视频标题仍为必填，没有独立简介参数；标题与 tags 写入同一个 caption 编辑器。

## 图文参数

- `--images`：1–35 张，仅 JPG/JPEG/PNG/WEBP，单张 ≤50 MB；传入顺序即展示顺序，第 1 张为封面。
- `--title`：页面 Title，≤90 字符，可选；不传则不改动页面输入。
- `--note` / `--notef`：Description，≤4000 字符（含 tags 展开后的文本）；`--notef` 从本地 txt/md 读取；两者互斥；都不传且无 tags 时不改动页面输入。
- `--tags`：逗号分隔，最多 50 个。
- `--schedule`：`YYYY-MM-DD HH:MM`。
- 发布选项：`--privacy`、`--no-comments`、`--aigc`/`--no-aigc`、`--your-brand`、`--branded-content` 与视频相同。
- `upload-note` 没有 `--disable-reuse`、`--thumbnail` 或 `--cover-index`。

## 退出码与失败处理

- `0` 成功、`1` 运行失败、`2` 用法错误、`9` 发布结果未知、`10` 需要人工登录、`130` 中断。
- 图片数量/格式/大小、Title/Description/hashtag 超限、`--note`/`--notef` 冲突等本地校验失败在启动浏览器前退出 `2`。
- 显式设置的发布选项会写入页面后回读；回读不一致退出 `1`，且不会点击发布。
- 收到 `9` 时**禁止自动重发**：发布点击已发出但未确认成功，先到 TikTok Studio → Content/Posts 按标题与发布时间核对；已存在不要重发，不存在才可人工重试。
- 不提供 `--cover-ms`、`--cover-index`、`--bgm`、`--json`，也不提供独立的 Duet / Stitch 开关。

定时发布使用 `--schedule "YYYY-MM-DD HH:MM"`；只有用户明确给出时间才传。MLX 只验证“已登录”，Profile 即身份，调度侧需确保 `profile_id` 与目标账号匹配；本地模式则由 `--account` 决定 cookie 文件。

每次发布前让用户确认账号、单条视频或一组图片、标题、正文/标签及立即/定时方式。页面布局或登录状态不符合预期时停止并报告；只有平台页面确认提交后才报告成功，未知结果先核查 TikTok Studio，不能直接重发。
