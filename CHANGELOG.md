# 更新日志

项目使用 GitHub Release 发布可复用版本；日常合并先记录在这里，发布时把对应版本的内容复制到 Release notes。

## [Unreleased]

### 托管浏览器（AdsPower）

- 新增 AdsPower 托管浏览器模式：设置非空 `ADSPOWER_API_KEY` 后，`sau <platform> check|upload-*` 通过 AdsPower Local API V2 启动 `--profile-id` 指定的 Chromium Profile，经 `data.ws.puppeteer` 的 CDP WebSocket 接管现有上下文，复用 Profile 登录态并在结束时停止本次启动的 Profile；不再读写 `cookies/*.json`。
- `--profile-id` 映射 AdsPower 的 `user_id`（V2 请求体字段 `profile_id`），必填；`--folder-id` 注册但静默忽略；`--account` 可选，仅日志/结果标签，缺省为 `profile_id`。`login` 在 AdsPower 模式下拒绝并退出 `1`，Bilibili 同样拒绝；`verify` / `delete` / `article` 仍本地执行。
- 新增 `ADSPOWER_API_BASE`（默认 `http://127.0.0.1:50325`，只允许 `http/https` + host + 可选端口；非法值退出 `2` 且不发请求）。同时设置 `MLX_API_TOKEN` 与 `ADSPOWER_API_KEY` 时退出 `1`。只支持 V2，不做 V1 fallback / 双栈 / 版本探测。
- 新增退出码 `11`（HTTP 429，MLX 与 AdsPower 共用）。**MLX 的 429 已由 `1` 改为 `11`**，这是本次唯一改变 MLX 可观察行为的地方；调度层应改为退避重试。CLI 不 sleep、不自动重试；stop 阶段 429 只 warning，不覆盖主结果。
- 文档与 Skills 同步：`GLOSSARY.md` 泛化 Profile 并新增托管浏览器/AdsPower 术语，`docs/CLI.md` 拆为本地 / Multilogin X / AdsPower 三层并保留旧锚点，README、`docs/skill-distribution.md` 与 18 个 Skill 统一两种托管模式说明，Bilibili 明确不支持。
- 验证范围：离线测试覆盖激活矩阵、双 key 冲突、base 校验、参数矩阵、生命周期、429 → `11` 与 key 脱敏。**真实 AdsPower 冒烟未执行（ticket 09）**：本机未安装 AdsPower、50325 未监听，以下仍未验证——已运行 Profile 的 start 返回形状、重复 stop、429 真实形状、`contexts` 是否恒为 1、超过 30s 的冷启动、旧客户端 V2 状态码、`/status` 是否鉴权、最低 V2 版本。
- 已知限制：命令级登录检测与身份日志已是 provider-aware 文案；但部分平台在**上传过程中**遇到登录页、验证码或 2FA 时，uploader 内部错误仍可能提到 Multilogin，待后续统一。

### 小红书

- 重新设计发布声明能力：`upload-video` / `upload-note` 新增 `--original` / `--no-original`（原创声明开关）与 `--content-type`（`fiction` / `ai` / `marketing` / `self-shot` / `repost`，对应「添加内容类型声明」菜单）。两项声明默认都不操作页面，保持平台默认。
- `--repost-source <媒体名称>` 仅在 `--content-type repost` 时使用并必填；修复此前每条内容都被默认声明为「来源转载」且来源为空的问题。
- `--content-type self-shot` 会打开「自主拍摄」弹窗，新增 `--shoot-location <地点>` 与 `--shoot-date <YYYY-MM-DD>` 填写拍摄地点和日期后确认；两者在 self-shot 时必填。
- 原创声明会弹出《原创声明须知》确认框，CLI 会自动勾选并点击「声明原创」，避免弹窗挡住发布。
- 新增 `--no-publish`：完成内容填写、封面、声明和定时设置后停止，不点击发布，便于 `--headed --debug` 回归验证。
- 发布超时与 TikTok 对齐：整条流程使用 15 分钟总预算；素材上传等待和发布循环共享同一 deadline。未点击发布前超时退出 `1`（确定未发布）；已点击发布后超时退出 `9`（结果未知，禁止自动重发）。
- 声明参数组合在启动浏览器前校验：原创与来源转载互斥；`--no-original` 不可与 `self-shot` / `repost` 组合；缺少来源、缺少拍摄信息或来源与内容类型不匹配均退出 `2`。

### 依赖

- patchright 精确升级到 `1.64.4`，对应 Chromium 156（与 Multilogin Mimic 156 对齐）；`uv.lock` 同步更新。
  - 本次只做离线测试用例回归，未做真实账号的完整上传验证；stealth 行为差异属于已知未验证风险。
  - 回滚：把 `pyproject.toml` 恢复为 `patchright==1.58.2`，重新 `uv lock` / `uv sync`，再执行 `patchright install chromium`。

### 结构与 CLI

- 将 `sau_cli.py` 从单体入口拆为 `sau_commands/` 下的按平台命令模块，入口只负责注册和分发。
- README、CLI 文档和 Skill 按平台及视频、文章、图文三类整理发布入口。
- 移除知乎没有实际用途的 `--expected-name` 参数；登录时直接读取当前页面身份并保存账号绑定信息。
- 知乎文章正式 URL 校验排除 `/edit` 草稿地址，避免把自动保存草稿误报为已发布。

### TikTok

- `upload-video` 新增可选发布选项：`--privacy`（`public` / `friends` / `followers` / `only-me`）、`--no-comments`、`--disable-reuse`（同时影响 Duet、Stitch、Stickers、Story）、`--aigc` / `--no-aigc`、`--your-brand`、`--branded-content`。不传时保持页面默认；显式传参后设置并回读，不一致即失败且不发布。
- 新增 `upload-note` 图文发布：1–35 张 JPG/JPEG/PNG/WEBP（单张 ≤50 MB）、Title ≤90 字符、Description ≤4000 字符（含 tags）、最多 50 个 hashtag；支持 `--note` / `--notef`、`--tags`、`--schedule` 及同一组发布选项（不含内容复用）。第 1 张图片即封面。
- 新增退出码 `9`（发布结果未知）：发布点击已发出但未确认成功；禁止自动重发，需先到 TikTok Studio → Content/Posts 按标题与发布时间人工核对。
- 新增本地 cookie 模式：未设置 `MLX_API_TOKEN` 时使用本地 Chromium 与 `cookies/tiktok_<account>.json`；支持 `login`（有头浏览器人工登录后回终端按 Enter）、`check`（`0`/`1`）、`upload-video`、`upload-note`。本地模式 `--account` 必填，`--folder-id` / `--profile-id` 忽略；Multilogin 模式行为不变。
- 真实账号验收发现并修复：首次上传时 `Turn on automatic content checks?` 弹窗与 react-joyride 新手引导遮罩会拦截表单点击；新增共用 `dismiss_blocking_overlays`，并在 caption 编辑器点击时重试。Studio 为客户端渲染，MLX 入口等待从 5s 放宽到 15s，本地校验用 20s。
- 刷新视频自定义封面选择器：`Edit cover` → `Upload cover` → `Save`。
- `upload-note` 增加 Photos tab 探测与回退：优先 `?tab=photo`，未进入图片表单时点击 `Photos`；账号不在灰度内时在选文件前退出 `1`。
- 待验收：上述视频发布选项、`upload-note`、封面选择器刷新、Photos tab 回退与本地模式登录/发布均未在真实账号上执行验收（真实账号验收 ticket 19 未执行）；发布前仍以页面回读为准，不视为已验证。

### 知乎文章

- 支持 HTML、Markdown、TXT 原稿，正文图片按原稿中的位置上传，不再统一追加到文末。
- 支持知乎真实编辑器中的 h2、加粗、编号列表、引用和外链校验。
- PNG 图片使用剪贴板粘贴路径，发布前核对文字、图片顺序、格式和链接。

### 知乎视频

- CLI 提供完整领域和视频声明可选值，支持实时菜单核对、编号选择和 `--show-options` 查询。
- 上传前拒绝小于或等于 100KB 的视频。
- 修正发布成功判断，读取成功弹层打开的 `/pin/<作品ID>` 详情链接；链接读取失败时保留已发表状态。
- 作品查询兼容新版视频链接；定时发布标为实验性功能。

## 发布流程

1. 在 `Unreleased` 中记录用户可感知的变更和验证结果。
2. 更新 `pyproject.toml` 的 `project.version`，遵循 `MAJOR.MINOR.PATCH`。
3. 运行专项测试、`git diff --check` 和构建检查。
4. 创建版本提交和 `v<version>` 标签，推送到 GitHub。
5. 在 GitHub 创建同名 Release，把本版本日志粘贴到 Release notes，并保留验证范围和已知限制。

版本发布前，未完成真实平台验收的能力必须明确写成“待验收”，不能写成已支持。
