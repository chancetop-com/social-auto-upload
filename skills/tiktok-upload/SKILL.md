---
name: tiktok-upload
description: 使用 `sau tiktok` 在本地持久化 Profile 模式或托管浏览器 Profile（Multilogin X / AdsPower）下检查登录并发布 TikTok 视频与图文。Use when 用户要发布 TikTok 视频或图文。
license: MIT-0
slug: social-auto-upload-tiktok-upload
displayName: TikTok 视频与图文发布
version: 1.3.0
summary: 使用 sau tiktok 在本地模式或托管浏览器模式（MLX / AdsPower）下检查登录并发布视频与图文。
---

# TikTok 视频与图文发布

TikTok 支持本地与两种托管子模式，使用同一个 `sau tiktok` CLI：

- **本地模式**（默认）：不设置托管凭据，使用专用 `browser_profiles/<chrome|chromium>/tiktok/<原始别名>`。`--account` 必填，`--folder-id` / `--profile-id` 忽略；浏览器保存完整状态，旧 Cookie JSON 不读写或自动清理。
- **Multilogin X（MLX）模式**：设置非空 `MLX_API_TOKEN`，并要求 `--folder-id` / `--profile-id`。
- **AdsPower 模式**：设置非空 `ADSPOWER_API_KEY`，只要求 `--profile-id`（映射 AdsPower `user_id`）；`--folder-id` 忽略。

## 部署前提

**本地模式**
- 默认系统 Chrome，由用户从 [Google Chrome 官网](https://www.google.com/chrome/) 安装；显式 `--local-browser chromium` 使用项目固定 Patchright 的完整浏览器，安装命令 `uv run patchright install --no-shell chromium`。只需准备选定来源，启动失败不自动切换。
- `conf.py` 的非空 `LOCAL_CHROME_PATH` 优先；否则显式 --local-browser > LOCAL_BROWSER > chrome。自定义产品不能可靠识别时退出 1，不能靠改文件名强行指定种类。
- 显式 --headed/--headless > LOCAL_CHROME_HEADLESS > False；升级保留用户已有 True，只有首次配置才复制示例。托管同样采用此 headless 优先级，并完全忽略本地来源。
- Profile 按平台、原始别名、浏览器种类隔离；同种类修改路径/版本/有头模式继续复用。别名允许换登录账号，另一个浏览器种类须单独登录。
- 窗口、UA、语言均沿用当前浏览器；现有选择器仍需要支持的页面布局。
- 首次使用在交互终端运行 `sau tiktok login --account <name> --headed`：人工完成登录后回到终端按 Enter，取得正向登录证据；随后同一来源运行 check。只有 login 引导登录，业务失效会停止。
- 图文（`upload-note`）要求账号已被 TikTok Studio 的 Photos tab 灰度覆盖。

**Multilogin 模式**
- CLI 与 Multilogin 桌面应用在同一台 macOS/Windows 机器，桌面应用已启动。
- Profile 使用 Mimic 内核，已人工登录 TikTok，且没有待处理验证码或 2FA。
- Profile 界面语言必须为 **English (US)**；本地保留当前语言；托管保留既有 English 登录探测入口，不修改 Profile 偏好。
- 图文（`upload-note`）还要求账号已被 TikTok Studio 的 Photos tab 灰度覆盖；没有入口时命令在选文件前退出 `1`。

**AdsPower 模式**
- AdsPower 付费版；桌面应用与 CLI 在同一台 macOS/Windows 机器，Local API 已开启，`50325` 未被占用。
- Profile 为 Chromium 内核，已人工登录 TikTok，且没有待处理验证码或 2FA。
- Profile 界面语言必须为 **English (US)**；`--folder-id` 忽略，`--profile-id` 映射 AdsPower `user_id`。
- AdsPower 客户端需支持 V2 Local API。

## 命令

```bash
# 本地模式：先登录一次
sau tiktok login --account creator --headed
# 0=已登录，10=需登录/验证，1=运行故障
sau tiktok check --account creator
sau tiktok upload-video --account creator --file videos/demo.mp4 --title "标题"
sau tiktok upload-note --account creator --images videos/demo1.png videos/demo2.png

# 托管浏览器模式（MLX）
export MLX_API_TOKEN="<token>"

# 0=已登录，10=需要人工登录
sau tiktok check --folder-id <folder_id> --profile-id <profile_id>

# 视频：新选项都可选，不传即保持页面默认
sau tiktok upload-video \
  --folder-id <folder_id> --profile-id <profile_id> \
  --file videos/demo.mp4 --title "标题" --tags tag1,tag2 \
  --privacy public --no-comments --disable-reuse --aigc --your-brand \
  --schedule "2026-10-21T02:30:00Z" --thumbnail videos/demo.png

# 图文：1–35 张本地图片，按传入顺序展示，第 1 张即封面
sau tiktok upload-note \
  --folder-id <folder_id> --profile-id <profile_id> \
  --images videos/demo1.png videos/demo2.png \
  --title "图文标题" --note "图文正文" --tags 图文,测试 \
  --privacy friends --no-comments --aigc

# AdsPower 模式（--folder-id 可省略）
unset MLX_API_TOKEN
export ADSPOWER_API_KEY="$KEY"

sau tiktok check --profile-id <profile_id>

sau tiktok upload-video \
  --profile-id <profile_id> \
  --file videos/demo.mp4 --title "标题" --tags tag1,tag2 \
  --privacy public --no-comments --schedule "2026-10-21T02:30:00Z"
```

- 本地模式必填 `--account`；托管模式 --account 被忽略，身份及日志标签取 profile_id。
- 支持 `check`、`upload-video`、`upload-note`；`login` 仅本地模式，托管模式下退出 `1`。
- 本地 Profile 是唯一登录态来源；检查/发布不引导登录。重建一个明确目标：`sau tiktok reset-profile --account creator --browser-kind chrome`；不启动浏览器，不删除另一种类、旧文件或历史结果，之后先重新 login。占用时立即失败，禁止抢占。
- 两种模式登录/验证均退出 `10`，网络/页面结构/浏览器故障退出 `1`；共享 15 分钟发布预算。提交后错误带 `publish_attempted=true` 时，先核查作品再决定重跑。
- 安装、浏览器启动与当前 Profile 登录分开核验。验收视频/图文显式传 `--no-publish`：上传素材、编辑并等待发布就绪后停止，可能留下临时素材/草稿，不证明已经发布。

## 托管浏览器模式（可选）

兼容 CLI 在同一台机器、同一操作系统用户下默认共享托管 Profile。不同平台各用新页，同一平台上的检查和发布合计限一条，冲突退出 `1`。最后一条命令离开时关闭整个 Profile，包括桌面原有的标签页。

`check`、`upload-video` 和 `upload-note` 均可改用托管浏览器 Profile：MLX 需要 `--folder-id` + `--profile-id`，AdsPower 只需要 `--profile-id`（`--folder-id` 忽略）。两种模式都不读写 cookie 文件，`--account` 被忽略，日志标签取 profile_id，`login` 一律拒绝。使用托管模式前，读取运行 `sau` 的项目根目录 `docs/CLI.md` 的“托管浏览器模式（通用）”（[在线入口](https://github.com/dreammis/social-auto-upload/blob/main/docs/CLI.md#托管浏览器模式通用)），确认共同退出码、部署前提、调度责任与身份安全。

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
- `--schedule`：`YYYY-MM-DDTHH:MM:00Z`（UTC 绝对时刻，填写前换算到浏览器时区；精确到 5 分钟）。
- 发布选项：`--privacy`、`--no-comments`、`--aigc`/`--no-aigc`、`--your-brand`、`--branded-content` 与视频相同。
- `upload-note` 没有 `--disable-reuse`、`--thumbnail` 或 `--cover-index`。

## 退出码与失败处理

- `0` 成功、`1` 运行失败、`2` 用法错误、`9` 发布结果未知、`10` 需要登录或验证、`130` 中断。
- 图片数量/格式/大小、Title/Description/hashtag 超限、`--note`/`--notef` 冲突等本地校验失败在启动浏览器前退出 `2`。
- 显式设置的发布选项会写入页面后回读；回读不一致退出 `1`，且不会点击发布。
- 收到 `9` 时**禁止自动重发**：发布点击已发出但未确认成功，先到 TikTok Studio → Content/Posts 按标题与发布时间核对；已存在不要重发，不存在才可人工重试。
- 不提供 `--cover-ms`、`--cover-index`、`--bgm`、`--json`，也不提供独立的 Duet / Stitch 开关。

定时发布使用 `--schedule "YYYY-MM-DDTHH:MM:00Z"`；只有用户明确给出时间才传。托管 Profile 即身份，本地别名选择独立 Profile。关闭故障不覆盖主结果；重新登录、崩溃或重建都不代表可以重新提交旧任务。

每次发布前让用户确认账号、单条视频或一组图片、标题、正文/标签及立即/定时方式。页面布局或登录状态不符合预期时停止并报告；只有平台页面确认提交后才报告成功，未知结果先核查 TikTok Studio，不能直接重发。
