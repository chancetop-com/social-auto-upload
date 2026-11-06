# 更新日志

项目使用 GitHub Release 发布可复用版本；日常合并先记录在这里，发布时把对应版本的内容复制到 Release notes。

## [Unreleased]

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
