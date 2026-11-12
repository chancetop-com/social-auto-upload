# 更新日志

项目使用 GitHub Release 发布可复用版本；日常合并先记录在这里，发布时把对应版本的内容复制到 Release notes。

## [Unreleased]

### 人类化交互层（W3 国内冲突）

- 抖音：53 个交互点接入人类化（视频/图文发布，删除 `_native_click` 及其合成事件重放；`uploader/douyin_uploader/`）。

### 人类化交互层（W2 国外）

- Facebook 个人主页：3 个交互点接入人类化（正文输入 + 正文聚焦 / 发布点击），删除/管理点击与文件选择保持原生并逐条标记（`uploader/meta_uploader/facebook_uploader/`）。
- YouTube：标题/简介逐字输入（含 `#` 逐段等待候选并按文本全等点选、失败降级纯文本继续）、播放列表名与标签改为全选覆盖后逐字、12 处可见点击（含 `_click_if_present`）统一走人类化指针（uploader/youtube_uploader）。
- Facebook Page：14 个交互点接入人类化（`uploader/meta_uploader/facebook_page_uploader/`）。

### 人类化交互层（W3 国内冲突）

- 微博：23 个交互点接入人类化（首页入口与 popup 发布页各一实例、跨页不复用；发布按钮比例落点 `(0.65,0.5)` → 失败且未派发时 `(0.35,0.5)` 再试一次；封面「完成」只点一次；`uploader/weibo_uploader/`）。

### 人类化交互层（W4 国内主体）

- 大鱼号：36 个交互点接入人类化（`uploader/dayu_uploader/`）。
- 知乎：30 个交互点接入人类化（视频表单标题/介绍、领域与标记下拉、原创勾选、文章标题与正文聚焦、定时表单 17 处、两个发布点），失焦点击与发布后详情跳转保持原生并逐条标记（`uploader/zhihu_uploader/`）。
- 视频号：34 个交互点接入人类化（`uploader/tencent_uploader/`）。
- 快手：13 个交互点接入人类化（描述/正文清空序列与话题逐字、描述聚焦、发布确认弹窗、定时开关与日期 picker、合集下拉与选项、封面入口/上传 tab/确认、视频与图文发布），登录二维码、文件入口、「我知道了」提示条和 Joyride 引导层保持原生并逐条标记（`uploader/ks_uploader/`）。

### 移除历史 Web 与旧示例脚本

- 删除已停止维护的 Web 版本：`sau_backend.py`、`sau_backend/`、`sau_frontend/`、`myUtils/`、`db/`、`Dockerfile`、`.dockerignore`、`start-win.bat`、`requirements.txt`，以及 `pyproject.toml` 中的 `web` extra。
- 删除 CLI 不可达的旧小红书签名实现 `uploader/xhs_uploader/`，并移除 `conf.XHS_SERVER`。
- 删除 `examples/` 下的历史直连上传/登录脚本，仅保留文章渲染与发布示例素材（`article.md`、`dayu_article.html`、`xueqiu_article.*`、`images/`）。
- 同步清理 README、`docs/install.md`、`docs/update.md`、`docs/agent-bootstrap.md` 中对上述内容的引用。

### 客户端发布闸门

- 所有发布命令（`upload-video` / `upload-note` / `upload-article`）新增 `--not-before "YYYY-MM-DDTHH:MM:SS+08:00"`（带时区的绝对时刻）：先完成上传、填表、封面、声明、合集等全部准备，解析后换算到运行机器本地时区，到达目标时刻才点击发布；不传时立即发布，目标时间已过也立即发布。
- 与平台原生 `--schedule` 互不替代，可同时使用：`--schedule` 传 UTC 绝对时刻（`YYYY-MM-DDTHH:MM:00Z`）并由平台在目标时间发布；`--not-before` 传带时区的绝对时刻（例如 `YYYY-MM-DDTHH:MM:SS+08:00`），负责本地提交时刻。
- 使用 `--no-publish` / `--prepare-only` / `--draft` 时跳过等待；Bilibili 因 `biliup` 单命令提交，等待发生在启动命令之前。
- 新增 `uploader/publish_gate.py` 与 `BaseVideoUploader.publish_not_before`；等待期间分段睡眠并定期输出剩余时间。
- **破坏性变更（CLI）**：`--schedule` 不再接受 `YYYY-MM-DD HH:MM`，改为 UTC ISO 8601（`YYYY-MM-DDTHH:MM:00Z`）；`--not-before` 同样改为带时区偏移的绝对时刻。旧格式会退出 `2`。
- **破坏性变更（Python API）**：`BaseVideoUploader.validate_publish_date`、`validate_dayu_schedule`、`validate_zhihu_schedule` 现在拒绝无时区的 `datetime`；直接调用上传器 API 时也必须传带偏移的绝对时刻。
- YouTube 的 `--schedule` 明确标记为尚未实现，传入退出 `2`；Facebook Page 结果 JSON 不再写 `timezone` 字段。

### 托管浏览器（AdsPower）

- 新增 AdsPower 托管浏览器模式：设置非空 `ADSPOWER_API_KEY` 后，`sau <platform> check|upload-*` 通过 AdsPower Local API V2 启动 `--profile-id` 指定的 Chromium Profile，经 `data.ws.puppeteer` 的 CDP WebSocket 接管现有上下文，复用 Profile 登录态并在结束时停止本次启动的 Profile；不再读写 `cookies/*.json`。
- `--profile-id` 映射 AdsPower 的 `user_id`（V2 请求体字段 `profile_id`），必填；`--folder-id` 注册但静默忽略；`--account` 可选，仅日志/结果标签，缺省为 `profile_id`。`login` 在 AdsPower 模式下拒绝并退出 `1`，Bilibili 同样拒绝；`verify` / `delete` / `article` 仍本地执行。
- 新增 `ADSPOWER_API_BASE`（默认 `http://127.0.0.1:50325`，只允许 `http/https` + host + 可选端口；非法值退出 `2` 且不发请求）。同时设置 `MLX_API_TOKEN` 与 `ADSPOWER_API_KEY` 时退出 `1`。只支持 V2，不做 V1 fallback / 双栈 / 版本探测。
- 新增退出码 `11`（HTTP 429，MLX 与 AdsPower 共用）。**MLX 的 429 已由 `1` 改为 `11`**，这是本次唯一改变 MLX 可观察行为的地方；调度层应改为退避重试。CLI 不 sleep、不自动重试；stop 阶段 429 只 warning，不覆盖主结果。
- 文档与 Skills 同步：`GLOSSARY.md` 泛化 Profile 并新增托管浏览器/AdsPower 术语，`docs/CLI.md` 拆为本地 / Multilogin X / AdsPower 三层并保留旧锚点，README、`docs/skill-distribution.md` 与 18 个 Skill 统一两种托管模式说明，Bilibili 明确不支持。
- 验证范围：离线测试覆盖激活矩阵、双 key 冲突、base 校验、参数矩阵、生命周期、429 → `11` 与 key 脱敏。**真实 AdsPower 冒烟未执行（ticket 09）**：本机未安装 AdsPower、50325 未监听，以下仍未验证——已运行 Profile 的 start 返回形状、重复 stop、429 真实形状、`contexts` 是否恒为 1、超过 30s 的冷启动、旧客户端 V2 状态码、`/status` 是否鉴权、最低 V2 版本。
- 已知限制：命令级登录检测与身份日志已是 provider-aware 文案；但部分平台在**上传过程中**遇到登录页、验证码或 2FA 时，uploader 内部错误仍可能提到 Multilogin，待后续统一。

### 发布超时（全平台）

- 浏览器发布平台统一与 TikTok 对齐：抖音、快手、视频号、百家号、支付宝生活号、YouTube、微博、虎扑、知乎视频/文章、雪球文章、大鱼号视频/文章、Facebook 个人主页、Facebook Page 均使用 15 分钟总预算（`uploader/publish_timeout.py`）。预算覆盖打开发布页、上传素材、填写元数据、封面/声明/合集、点击发布和等待平台确认。
- 未点击发布前超时退出 `1`（确定未发布）；点击发布后超时退出 `9`（结果未知，禁止自动重发）。知乎、雪球、大鱼号、Facebook Page 等原本只记录 `submission_unknown` 的流程现在会保留专用错误类型。
- TikTok、小红书与 Instagram 迁移到同一个 `PublishTimeoutBudget`，仅通过构造参数保留各自更具体的错误文案；deadline 计算、点击前检查与点击后 unknown 判断统一由 helper 负责。
- `--not-before` 主动等待不计入预算，并从 deadline 中顺延；素材上传/转码等待按剩余预算收紧。Bilibili 因 `biliup` 单命令提交，保留“启动前等待”的语义，并给命令本身增加 15 分钟超时；命令启动后超时按结果未知退出 `9`。

### 小红书

- 重新设计发布声明能力：`upload-video` / `upload-note` 新增 `--original` / `--no-original`（原创声明开关）与 `--content-type`（`fiction` / `ai` / `marketing` / `self-shot` / `repost`，对应「添加内容类型声明」菜单）。两项声明默认都不操作页面，保持平台默认。
- `--repost-source <媒体名称>` 仅在 `--content-type repost` 时使用并必填；修复此前每条内容都被默认声明为「来源转载」且来源为空的问题。
- `--content-type self-shot` 会打开「自主拍摄」弹窗，新增 `--shoot-location <地点>` 与 `--shoot-date <YYYY-MM-DD>` 填写拍摄地点和日期后确认；两者在 self-shot 时必填。
- 原创声明会弹出《原创声明须知》确认框，CLI 会自动勾选并点击「声明原创」，避免弹窗挡住发布。
- 新增 `--no-publish`：完成内容填写、封面、声明和定时设置后停止，不点击发布，便于 `--headed --debug` 回归验证。
- 发布超时与 TikTok 对齐：整条流程使用 15 分钟总预算；素材上传等待和发布循环共享同一 deadline。未点击发布前超时退出 `1`（确定未发布）；已点击发布后超时退出 `9`（结果未知，禁止自动重发）。
- 发布失败快速识别：点击发布后命中「因违反社区规范禁止发笔记」「账号异常」「发布失败」等 toast/弹窗时立即退出 `1`，不等待 15 分钟、不重试；错误信息携带平台原文，便于定位账号或内容限制。
- 「操作频繁」「请稍后再试」按可恢复限流处理，不立即失败，保留原有重试逻辑，由 15 分钟总预算兜底。
- 本地模式固定 `locale=zh-CN` 与 `Accept-Language: zh-CN`，不依赖系统语言；托管模式不应用该设置，Multilogin / AdsPower 的小红书 Profile 界面必须保持中文。
- 声明参数组合在启动浏览器前校验：原创与来源转载互斥；`--no-original` 不可与 `self-shot` / `repost` 组合；缺少来源、缺少拍摄信息或来源与内容类型不匹配均退出 `2`。

### Instagram

- **破坏性变更**：配文（标题、正文、标签合计）超过 2200 字符的退出码由 `1`（`ValueError`）改为 `2`（`UsageError`），与 TikTok、小红书对齐；调度层若按 `1` 判断需改用 `2`。
- 新增四项网页发布选项，`upload-video` / `upload-note` 均可用，全部可选，**不传即完全不动页面默认、也不读取相关控件**：
  - `--location TEXT`：按 Instagram 联想列表忽略大小写与多余空白的精确匹配；无精确匹配退出 `1`、不发布，错误信息列出观察到的候选。
  - `--no-comments`：请求关闭评论；入口缺失或不可用视为已满足（`default_off`，退出 `0`）。没有 `--comments`。
  - `--ai-generated` / `--no-ai-generated`：互斥，同传由 argparse 退出 `2`；开启时入口缺失或不可用退出 `1`，关闭时已是关闭或入口缺失退出 `0`；没有 `--aigc` 别名。
  - `--alt-text TEXT`（仅 `upload-note`）：可重复，每张图片一条；条数必须为 0 或等于 `--images` 张数，每条 1–1000 字符，不截断；`upload-video --alt-text` 由 argparse 退出 `2`。
- 所有静态校验（配文超长、视频与图片互斥、`--thumbnail` 与图片同传、替代文字条数/长度、空 `--location`）在启动浏览器或托管 Profile 前完成并退出 `2`。
- 本地模式固定 `locale=en-US` 与 `Accept-Language: en-US`（`INSTAGRAM_CONTEXT_KWARGS`，此前为空表），界面语言不再随操作系统的浏览器语言漂移；登录窗口同样固定。托管模式不应用该设置，Profile 界面必须人工保持 English。选项入口缺失时会打印页面 `html[lang]`，便于区分“选择器漂移”与“账号语言不是英文”。
- 选项设置与回读在点击 Share **之前**完成：任一项未生效退出 `1`、不点击发布，不会退化为 `9`；结果文件仍写入失败证据。既有退出码 `0/1/9/10/11` 含义不变。
- 结果 JSON 新增顶层 `options`，固定含 `location`、`alt_text`、`comments`、`ai_generated`，每项 `{requested, applied, status[, reason]}`；`status` ∈ `not_requested` / `set` / `default_off` / `unsupported` / `mismatch`，`reason` ∈ `entry_missing` / `account_ineligible`。字段为新增，旧消费方可忽略。
- 验证范围：离线 A/B/C/D 测试与真实 Chrome DOM 哨兵通过；2026-11-10 完成真实账号真发验收（English UI、Personal、本地 cookie）：两图轮播同时设置地点/两条替代文字/关闭评论/AI 标识，发布后 `img[alt]`、地点、`AI content` 与无评论输入框均回读一致；同日再发一条 Reel 验证 `--file` / `--thumbnail` / `--desc` / `--tags` 与两项开关，两条帖子随后均由 `delete` 确认删除。证据见 `.scratch/instagram-browser-parity/research/08-acceptance-evidence.md`。`--not-before`、`--proxy`、`--headless`、中文界面、专业账号与托管模式仍未验收。
- 真机验收中发现的问题：Instagram 可能在点击创建后弹出 `Turn on Notifications`，已改为在等待素材入口期间主动关闭并在整个上传流程注册 handler；作品菜单新增项导致删帖下标漂移，已改为精确匹配 `Delete` 项。
- 已知限制：选择器仅在 **English 界面 + Personal 账号**观察，中文标签为未验证回退，专业账号未验证；协作者、Stories、定时、配乐、选帧封面、用户标签、滤镜、隐藏点赞等仍保留页面默认且不在本轮范围。
- 发布超时与 TikTok 对齐：整条上传/发布流程使用 15 分钟总预算；打开首页、身份核验、素材上传、裁剪/编辑、配文、封面与点击发布共享同一 deadline，关键等待按剩余预算收紧。未点击发布前超时退出 `1`（确定未发布）；点击发布后等待最终创建响应超时退出 `9`（结果未知，禁止自动重发）。
- `--not-before` 的主动等待不计入预算，等待时长会从 deadline 中顺延；超时错误的现场证据仍写入本地结果目录。

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
