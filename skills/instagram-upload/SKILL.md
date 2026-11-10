---
name: instagram-upload
description: 使用 sau CLI 在 Instagram 独立网页登录、立即发布 Reels/单图/轮播、核验原作品并移至最近删除。
license: MIT-0
slug: social-auto-upload-instagram-upload
displayName: Instagram 视频与图文发布
version: 1.0.0
summary: 发布 Instagram Reels、单图或轮播，并核验作品。
---

# Instagram 独立网页发布

调用现有 CLI，不自行实现浏览器上传。使用工程 Patchright Chrome 和独立 Instagram 会话，不使用 Business Suite 的绑定入口。默认可见浏览器，未配置代理时按系统网络直连；需要代理时显式使用 `--proxy` 或设置 `SAU_INSTAGRAM_PROXY`。传 `--proxy ""` 可忽略环境变量并直连。

```powershell
sau instagram login --account creator
sau instagram check --account creator
sau instagram upload-video --account creator --file videos/demo.mp4 --thumbnail covers/demo.png --title "标题" --desc "正文" --tags 生活,分享 --result .local/instagram-video.json
sau instagram upload-note --account creator --images images/1.jpg images/2.jpg --title "轮播标题" --note "正文" --result .local/instagram-images.json
```

视频/Reel 可用 `--thumbnail` 指定 JPG/JPEG/PNG 封面；省略时使用 Instagram 默认封面。指定图片后会检查主预览确实使用该图片，失败则停止提交。封面按当前视频画幅居中裁剪，图片边缘的重要文字应留出安全区域。图文发布不接受此参数。

账号文件保存为 `cookies/instagram_creator.json`。密码和验证由用户在工程浏览器输入。上传流程会自动跳过首次通知提示、确认 Reels 介绍，没有提示则继续。登录验证仍由用户完成；未知弹窗或提示关闭失败须报告，不能宣称上传成功。

视频支持 MP4/MOV，照片支持 JPG/JPEG/PNG/AVIF/HEIC/HEIF，实际处理取决于平台。多图按输入顺序发布轮播，单图和两图轮播已实测。标题、正文、标签合计最多 2200 字符；超过时退出 `2`，且静态校验都在启动浏览器前完成。当前账号独立网页版的照片/Reels 表单及高级设置没有定时入口，当前 CLI 仅支持立即发布；不能把定时任务转换成立即发布。

已接入四项网页发布选项，`upload-video` / `upload-note` 均可用，全部可选，不传即完全不动页面默认：

- `--location TEXT`：按联想列表忽略大小写与多余空白的精确匹配；无精确匹配退出 `1`、不发布，错误信息列出候选。
- `--no-comments`：请求关闭评论；入口缺失或不可用视为已满足（`default_off`，退出 `0`）。没有 `--comments`。
- `--ai-generated` / `--no-ai-generated`：互斥，同传退出 `2`；开启时入口缺失退出 `1`，关闭时已是关闭或入口缺失退出 `0`；没有 `--aigc` 别名。
- `--alt-text TEXT`（仅 `upload-note`）：可重复，每张图片一条；条数必须为 0 或等于图片张数，每条 1–1000 字符，不截断。

```powershell
sau instagram upload-note --account creator --images images/1.jpg images/2.jpg --title "轮播标题" --note "正文" --location "Shanghai, China" --no-comments --ai-generated --alt-text "第一张的替代文字" --alt-text "第二张的替代文字" --result .local/instagram-images.json
```

协作者、Stories、定时发布、配乐、选帧封面、用户标签、滤镜、隐藏点赞/播放数和声音设置仍未接入，沿用页面默认。四项新选项在点击 Share 前完成设置与回读，任一项未生效即退出 `1` 且不发布。结果 JSON 的顶层 `options` 记录 `location`、`alt_text`、`comments`、`ai_generated` 的 `requested` / `applied` / `status`（必要时含 `reason`）。

选择器只在 **English 界面 + Personal 账号**验证过，中文标签为未验证回退，专业账号未验证。本地模式固定 `locale=en-US`；托管模式需把 Profile 界面保持 English（账号语言设为中文时 Instagram 仍可能渲染中文）。四项能力已在真实账号真发验收通过（2026-11-10，English UI / Personal / 本地 cookie）：图片轮播与 Reel 各发一条，地点、替代文字、关闭评论、AI 标识与 `--tags` 发布后回读一致，均已删除。`--not-before`、`--proxy`、`--headless`、中文界面、专业账号与托管模式仍未验收，不得据此宣称支持。

最终结果 `published` 代表平台确认作品创建，返回作品编号、原作品链接和媒体数。`processing` 表示已受理且仍在处理，`submission_unknown` 表示提交后结果未确认；不能当成已发布，也不能直接重发。默认结果位于 `.local/instagram-results/`，使用 `--result` 固定记录路径。

整条上传/发布流程与 TikTok 一样使用 15 分钟总预算。**尚未点击发布**时超时退出 `1`，确定没有发布；**点击发布后**等待最终创建响应超时退出 `9`，结果未知，禁止自动重发，先按配文和发布时间在账号主页核对。`--not-before` 的主动等待不计入预算，会从 deadline 中顺延。

```powershell
sau instagram verify --account creator --post-url "原作品链接" --expected-text "原作品中的准确文字" --result .local/instagram-verify.json
sau instagram delete --account creator --post-url "原作品链接" --expected-text "原作品中的准确文字" --result .local/instagram-delete.json
```

结果未知但没有链接时，先在同一账号主页按素材、配文和发布时间找原作品，复制链接再运行 `verify`；未找到不证明失败，不重复上传。链接支持 `/p/编号/`、`/reel/编号/` 和带作者名的形式。核对登录用户、作者、作品编号和正文后才允许删除。删除返回 `deleted`，作品进入“最近删除”；批量删除和提前永久清空不在范围内。本地素材不会删除。`deletion_unknown` 须先查询原作品和“最近删除”，不重复提交删除。

完整参数和能力边界以 `sau instagram upload-video --help`、`upload-note --help`、`verify --help` 和 `delete --help` 为准。失败时根据结果文件中的错误及本地证据分析；不得把账号状态、截图或页面记录提交到 Git。

## 托管浏览器模式（可选）

设置 `MLX_API_TOKEN`（Multilogin X）或 `ADSPOWER_API_KEY`（AdsPower）后，`check`、`upload-video` 和 `upload-note` 可改用托管浏览器 Profile；登录态与出口 IP 由 Profile 决定，CLI 不读写 `cookies/*.json`。`verify` / `delete` 仍为本地模式。

- MLX：`--folder-id` 与 `--profile-id` 必填。
- AdsPower：`--profile-id` 必填（映射 AdsPower `user_id`），`--folder-id` 忽略。
- 两种模式下 `--account` 仅作日志标签，缺省为 `profile_id`；`login` 一律拒绝，请先在对应桌面应用中登录 Profile。
- 退出码（含 `11` 请求过于频繁）、部署前提、调度责任、身份风险与安全说明见 `docs/CLI.md` 的“托管浏览器模式（通用）”。

## 示例脚本

`scripts/examples/` 下的文件是复制用示例，不是运行时依赖。执行前先查看当前 CLI 的 `--help`，替换账号、素材和正文；这些命令可能创建真实作品。

- `instagram_commands.ps1`：PowerShell
- `instagram_commands.sh`：Bash
- `instagram_cli_template.py`：Python subprocess
