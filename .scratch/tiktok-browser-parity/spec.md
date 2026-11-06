# TikTok 浏览器能力对齐 — v1 实施规格

- 状态：规格完成，可交给后续会话实施；真实账号冒烟与发布验收**尚未执行**。
- 来源：ticket [01](./issues/01-photo-post-feasibility.md)、[02](./issues/02-aigc-brand-disclosure.md)、[03](./issues/03-privacy-interactions.md)、[04](./issues/04-covers.md)、[05](./issues/05-cli-parameter-contract.md)、[06](./issues/06-preflight-failure-semantics.md)、[07](./issues/07-test-strategy.md)、[09](./issues/09-shared-flow-extension-points.md)；研究细节见 [research/](./research/)。
- 术语以仓库根目录 `GLOSSARY.md` 为准；本规格新增术语需回写 GLOSSARY。
- 本 effort 只产出规格：**不改生产代码、不改选择器、不执行测试**。
- 置信度标记：
  - `[官方文档]`：TikTok 官方开发者文档。
  - `[官方前端代码]`：TikTok Studio 线上静态 bundle 只读抓取（2026-11-05），比截图强、比正式文档弱。
  - `[开源实现]`：公开生产脚本的实测路径。
  - `[本仓]`：当前仓库代码事实。
  - `[设计]`：本规格新增决策。
  - `[仅推断]`：无直接证据，实施时必须先实测。

---

## 0. 摘要

在不接入 TikTok Content Posting API 的前提下，把 API 的作者侧发布能力尽量映射到 TikTok Studio 网页端：隐私级别、评论/内容复用开关、AI 生成标识、品牌内容声明、视频自定义封面，以及全新的图片帖（`upload-note`）。

实现方式是在现有 `uploader/tk_uploader/main_chrome.py` 视频流程上抽一个模板方法骨架，视频与图片各自实现钩子；新增能力做成“显式传参才设置、设置后回读”的独立步骤。旧 `upload-video` 不传新参数时，行为、输出与退出码完全不变。

---

## 1. 目标与非目标

### 1.1 目标

1. `sau tiktok upload-video` 支持隐私、评论、内容复用、AI 标识、品牌声明的可选设置。
2. 新增 `sau tiktok upload-note`，支持 1–35 张本地图片、Title、Description、tags、定时与同一组发布选项。
3. 视频自定义封面（现有 `--thumbnail`）在新版封面编辑器下继续可用。
4. 两条路径共用同一套登录检测、15 分钟发布预算、登录错误映射与发布结果语义。
5. 参数契约、UI 流程、失败语义、测试矩阵、验收清单足以让后续会话直接实施，不再需要产品决策。

### 1.2 非目标

- 官方 Content Posting API、OAuth、开发者 App 审核。
- `PULL_FROM_URL`、图床、域名验证、分片上传、`MEDIA_UPLOAD` 收件箱、`post_mode`、`auto_add_music`。
- `video_cover_timestamp_ms` 的毫秒级精确选帧，以及 `--cover-ms` 参数。
- `photo_cover_index` / `--cover-index`：网页只能第 1 张作封面。
- 图片帖配乐 `--bgm`；手动 Add sound 不纳入 v1。
- TikTok 本地模式（Firefox / Chromium cookie 文件）。
- Flask `sau_backend.py`、Vue 前端、调度 App、账号↔Profile 映射与身份校验。
- `--json` 输出：v1 不提供；机器信号只有退出码与 stderr。若后续需要，另立 effort。
- 本规格不交付代码，也不执行真实账号验收。

---

## 2. 术语、约束与代码基线

### 2.1 术语

| 术语 | 含义 |
| --- | --- |
| 设置后回读（set-then-readback） | CLI 显式传参后操作控件，再从页面读取最终状态；不一致即失败。本规格不叫“能力预检”。 |
| 发布结果未知 | 发布点击已发出、未观察到成功页、未命中登录/验证码跳转；对应退出码 `9`。 |
| Photos tab | TikTok Studio 上传页的图片帖模式入口；按账号/地区灰度。 |
| 内容复用（reuse） | 页面上的 `Allow reuse of content`，同时控制 Duet / Stitch / Stickers / Story。 |
| 图片帖（note） | TikTok 的多图帖，对应 API 的 Photo post；本仓命令名 `upload-note`。 |
| 图文字段 | 图片帖的 Title（≤90）与 Description（≤4000，含 hashtags）。 |

### 2.2 通道约束（charter）

1. 只走浏览器 + Multilogin X Profile；不注册开发者 App、不接 OAuth、不走 Content Posting API。
2. 图片按本地文件处理，与视频相同；不使用 `PULL_FROM_URL`，不要求图床或域名验证。
3. 实现基线是当前 `main_chrome.py` 的视频发布流程；新能力作为可选步骤插入，不另起架构。
4. 旧 `upload-video` 的参数、行为、退出码保持向后兼容。
5. MLX Profile 界面语言固定 **English (US)**；不新增本地模式、不做 CLI 内语言切换。
6. 每项能力先确认浏览器 UI 可做；不能等价表达的 API 概念直接不暴露。

### 2.3 代码基线事实

| 事实 | 位置 |
| --- | --- |
| CLI 入口 → 平台命令 → 上传器 | `sau_cli.py` → `sau_commands/tiktok.py` → `uploader/tk_uploader/main_chrome.py` |
| 现有视频能力 | 本地文件、标题、tags、定时、缩略图、登录检测、15 分钟发布超时 |
| 现有选择器 | `uploader/tk_uploader/tk_config.py` 的 `Tk_Locator.tk_iframe` / `default`；其余内联在 `main_chrome.py` |
| 浏览器客户端 | `patchright`（Multilogin 分支同仓其他 uploader） |
| 现有定位方式 | `self.locator_base = page.frame_locator('[data-tt="Upload_index_iframe"]')` 或 `page.locator('body')` |
| 现有构造器 | `TiktokVideo(title, file_path, tags, publish_date, account_file, thumbnail_path=None)`；前 5 个 positional 顺序不能动 |
| 现有请求对象 | `TiktokVideoUploadRequest`（`sau_commands/tiktok.py`） |
| 现有退出码映射 | `sau_cli.main`：`LoginRequiredError → 10`、`UsageError → 2`、其他 `Exception → 1` |
| 现有测试 | `unittest`；TikTok 契约在 `tests/test_mlx_tiktok.py` |
| 可复用 CLI helper | `sau_commands/arguments.py` 的 `parse_tags`、`parse_image_files`、`schedule_value`、`existing_file_path` |
| 图文的同仓先例 | `sau_commands/douyin.py` 的 `upload-note`；`uploader/xiaohongshu_uploader` 的图文路径 |

---

## 3. API 能力 ↔ 浏览器实现矩阵

### 3.1 结论图例

- **可行**：网页端有稳定等价控件，按本规格即可实现。
- **条件可行**：受账号类型、灰度、A/B flag 或页面组合规则限制；需回读，不能承诺所有账号可用。
- **不可行**：网页端无法等价表达，或只能近似到不可接受。
- **不做**：传输机制或本 effort 明确排除的概念。

### 3.2 矩阵

| 能力 | API 字段 | 网页表达 | 结论 | 置信度 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 视频本地文件 | `source_info` 本地文件路径 | `Select video` → file chooser | 可行 | `[本仓]` | 现有行为 |
| 视频标题 / caption | `post_info.title` | Draft.js caption 编辑器 | 可行 | `[本仓]` | 现有行为，不新增长度校验 |
| 图片帖入口 | Photo post | `?tab=photo` + `Photos` tab | 条件可行 | `[官方前端代码]` + `[开源实现]` | 2026-07 起按账号灰度；缺失必须报错，不能落到视频 input |
| 图片数量与格式 | `photo_images` | image file input | 条件可行 | `[官方前端代码]` | 1–35 张；JPG/JPEG/PNG/WebP；单张 ≤50 MB |
| 图片帖 Title | `title` | `Add a catchy title` 输入框 | 可行 | `[官方前端代码]` + `[开源实现]` | ≤90 字符 |
| 图片帖 Description | `description` | Draft.js / caption 区 | 可行 | `[官方前端代码]` + `[开源实现]` | ≤4000 字符；hashtags 计入 |
| Hashtags | `hashtags` | Description 内文本 | 可行 | `[官方前端代码]` | ≤50 个；网页不单独存储 |
| 多图排序 | `photo_images` 顺序 | 图片卡片拖拽 | 可行（不暴露） | `[官方前端代码]` | CLI 按 `--images` 传入顺序，不做排序参数 |
| 图片帖封面 | `photo_cover_index` | 无独立控件；第 1 张即封面 | 不可行 | `[官方前端代码]` | 换封面等于改顺序，v1 不暴露 |
| 隐私级别 | `privacy_level` | `video_visibility_container` 下拉 | 条件可行 | `[官方文档]` + `[官方前端代码]` | 只有 3 项；公开/私有账号文案不同；不可用项置灰 |
| 评论 | `disable_comment` | `Allow comments` 复选框 | 可行 | `[官方前端代码]` | 账号级禁止时置灰；回读一致即成功 |
| 合拍 | `disable_duet` | 合并进 `Allow reuse of content` | 条件可行 | `[官方前端代码]` | 不能独立设置 |
| 拼接 | `disable_stitch` | 合并进 `Allow reuse of content` | 条件可行 | `[官方前端代码]` | 不能独立设置 |
| 内容复用总开关 | 无单独字段 | `Allow reuse of content` | 可行 | `[官方前端代码]` | 同时影响 Stickers / Story；CLI 用 `--disable-reuse` |
| AI 生成标识 | `is_aigc` | `AI-generated content` 开关 | 条件可行 | `[官方前端代码]` | 受 A/B `show_aigc_toggle` 控制；首次开启需点 `Turn on` |
| 品牌：Your brand | `brand_organic_toggle` | `Disclose post content` + `Your brand` | 可行 | `[官方前端代码]` | 发布后标签 `Promotional content` |
| 品牌：Branded content | `brand_content_toggle` | `Disclose post content` + `Branded content` | 条件可行 | `[官方前端代码]` | 与 `Only you` 互斥；发布后标签 `Paid partnership` |
| 品牌 campaign 关联 | 无 | 无 | 不可行 | `[官方文档]` + `[官方前端代码]` | 发布后需在移动端 `Ad settings` 完成 |
| 视频自定义封面 | 无（`video_cover_timestamp_ms` 近似） | `Edit cover` → `Upload cover` | 可行 | `[官方前端代码]` + `[开源实现]` | 现有 `thumbnail_path` 语义不变，选择器需刷新 |
| 视频按毫秒选帧 | `video_cover_timestamp_ms` | 11 帧胶片 + 拖拽指示器 | 不可行（精确） | `[官方前端代码]` | 精度约 `duration/429` ms/px；v1 不暴露 |
| 定时发布 | 无 | `Schedule` 控件 | 可行 | `[本仓]` + `[开源实现]` | 需账号 `schedule_enable`；沿用现有格式 |
| 草稿 | 无 | 页面草稿按钮 | 不做 | `[仅推断]` | 存在但手动按钮未复核；不自动化 |
| 配乐 | `auto_add_music` | `Add sound` 手动选曲 | 不做（v1） | `[官方前端代码]` + `[开源实现]` | 无自动配乐；`--bgm` 不提供 |
| AI remix | 无（页面额外开关） | `Allow AI to remix content` | 不做（v1） | `[官方前端代码]` | 默认开启；不传参时保持默认，显式关闭不暴露 |
| 图片帖 AIGC / 品牌 | 同上 | 代码路径存在，页面渲染未实测 | 条件可行（未验证） | `[官方前端代码]` + `[仅推断]` | 控件缺失且显式请求时按回读失败处理 |
| `PULL_FROM_URL` / 图床 / 分片 / `MEDIA_UPLOAD` / `post_mode` | 传输机制 | 无等价物 | 不做 | `[官方文档]` | 本地文件直接上传已是网页唯一路径 |

### 3.3 明确不能等价表达的项

- `disable_duet` 与 `disable_stitch` 不能分别设置；两者不一致时网页无可表达方式。
- `photo_cover_index` 不能在不改变图片顺序的情况下指定。
- `video_cover_timestamp_ms` 不能精确到毫秒。
- 品牌 campaign 关联、品牌政策审核状态不在网页自动化范围内。

---

## 4. 命令与参数契约

### 4.1 `upload-video` 新增参数

现有 positional 参数与行为不变；新增项全部 keyword-only。

| 参数 | 取值 | 缺省 | 语义 |
| --- | --- | --- | --- |
| `--privacy` | `public` / `friends` / `followers` / `only-me` | 不传 = 不动 | 显式设置隐私级别并回读 |
| `--no-comments` | 开关 | 不传 = 不动 | 取消 `Allow comments` |
| `--disable-reuse` | 开关 | 不传 = 不动 | 取消 `Allow reuse of content`（同时影响 Duet/Stitch/Stickers/Story） |
| `--aigc` / `--no-aigc` | 互斥三态 | 不传 = 不动 | 开启/关闭 `AI-generated content` |
| `--your-brand` | 开关 | 不传 = 不动 | 勾选 `Your brand` |
| `--branded-content` | 开关 | 不传 = 不动 | 勾选 `Branded content` |
| `--thumbnail` | 现有 | 不传 = 不改封面 | 自定义视频封面，语义保持 |

### 4.2 `upload-note` 参数

| 参数 | 必填 | 语义 |
| --- | --- | --- |
| `--images` | 是 | 1–35 张本地图片，按传入顺序展示；第 1 张即封面 |
| `--title` | 否 | 页面 Title，≤90 字符；不传则不动 |
| `--note` | 否 | 页面 Description，≤4000 字符；不传则不动 |
| `--notef` | 否 | 从 txt/md 读 Description；与 `--note` 互斥 |
| `--tags` | 否 | 逗号分隔，规范化后追加到 Description |
| `--schedule` | 否 | 与视频相同的 `YYYY-MM-DD HH:MM` |
| `--privacy` / `--no-comments` / `--aigc` / `--no-aigc` / `--your-brand` / `--branded-content` | 否 | 与视频相同语义 |
| `--account` / `--debug` / `--headed` / `--headless` / `--folder-id` / `--profile-id` | 否 | 与现有平台一致 |

`upload-note` **不注册**：

- `--disable-reuse`：图片帖没有内容复用设置。
- `--thumbnail`、`--cover-index`：第 1 张即封面。
- `--bgm`：网页无自动配乐，手动选曲不纳入 v1。

### 4.3 隐私枚举映射

| CLI 值 | API 枚举 | 公开账号页面文案 | 私有账号页面文案 | 备注 |
| --- | --- | --- | --- | --- |
| `public` | `PUBLIC_TO_EVERYONE` | `Everyone`（变体 `Public`） | 不出现 | 私有账号请求 → 回读失败 |
| `friends` | `MUTUAL_FOLLOW_FRIENDS` | `Friends` | `Friends` | 两类型都可用 |
| `followers` | `FOLLOWER_OF_CREATOR` | 不出现 | `Followers` | 公开账号请求 → 回读失败 |
| `only-me` | `SELF_ONLY` | `Only you`（变体 `Private`） | `Only you` | 两类型都可用 |

账号类型不匹配按严格策略失败，不自动改名、不回退、不降级。

### 4.4 缺省值、互斥与组合规则

1. 未传任何新参数 → 不操作对应控件，保持页面原生默认；旧 `upload-video` 行为不变。
2. 显式传参 → 设置后回读；回读不一致视为失败，**不点击发布**。
3. `--aigc` 与 `--no-aigc` 互斥；`--note` 与 `--notef` 互斥。
4. `--your-brand` 与 `--branded-content` 可同时为真。只要有一项为真：
   - 自动打开 `Disclose post content`；
   - 两个复选框都显式设置：请求为真的勾选，未请求的显式取消勾选。
5. `--branded-content` + `--privacy only-me` → 本地直接报错，退出 `2`（不需要启动浏览器）。
6. `--branded-content` + `friends` 允许，但标为**待实测**；发布前仍以回读为准。
7. `--disable-reuse` 是单开关；文档必须注明它同时影响 Stickers / Story。API 的 `disable_duet` / `disable_stitch` 不分别暴露。
8. 不提供 `--cover-ms`、`--cover-index`、`--bgm`、`--ai-remix`。
9. 图片帖没有 `--disable-reuse`；视频帖没有 `--images`。
10. `--title` 对图片帖可选；不传则保留页面空标题。视频 `--title` 仍为必填。

### 4.5 本地校验（启动浏览器前，失败退出 2）

- 图片：1–35 张；仅 `JPG` / `JPEG` / `PNG` / `WEBP`（大小写不敏感）；单张 ≤50 MB。
- Photo Title ≤90 字符；Description（含 tags 展开后的文本）≤4000 字符；hashtag 总数 ≤50。
- `--privacy` 只接受四个枚举值（argparse `choices`）。
- `--schedule` 沿用 `sau_commands.arguments.schedule_value`。
- `--note` / `--notef` 互斥；`--notef` 文件不存在或不可读 → 退出 `2`。
- 视频 caption 不新增长度校验，保持旧行为。
- 超长/超限**直接报错，不截断**。

### 4.6 输出契约

- 成功时沿用现有 stdout 风格：视频 `TikTok video upload submitted: <path>`；图片帖新增同类一行（实现阶段定稿，需含图片数量）。
- 不提供 `--json`。机器信号为退出码 + stderr 文本。
- stderr 中的失败消息必须能定位到控件/阶段，并包含请求值与实际值。

---

## 5. UI 流程与选择器

### 5.1 模板方法骨架

```python
async def _upload_on_page(self, page, *, multilogin, deadline):
    await self.open_upload_page(page, multilogin=multilogin)   # goto + shell + locator + ensure_mode
    await self.attach_media(page)
    await self.fill_metadata(page)
    await self.wait_media_ready(page, deadline=deadline, multilogin=multilogin)
    await self.apply_options(page)
    await self.apply_cover(page)
    await self.apply_schedule(page)
    await self.click_publish(page, deadline=deadline, multilogin=multilogin)
    self.last_item_id = await self.read_result(page)
```

顺序与现有视频流程逐字等价：`fill_metadata` 在 `wait_media_ready` 之前，即“先填标题再等上传完成”。

### 5.2 视频路径

| # | 步骤 | 动作 | 候选选择器（按优先级） | 等待/置信度 |
| --- | --- | --- | --- | --- |
| 1 | `open_upload_page` | `goto(TIKTOK_UPLOAD_URL)`；`choose_base_locator` | iframe `[data-tt="Upload_index_iframe"]`；否则 `body` | `wait_for_url` 10s；shell 10s；`[本仓]` |
| 2 | `attach_media` | `expect_file_chooser` + `set_files([file_path])` | `button:has-text("Select video"):visible` → `button[aria-label="Select file"]` | 按钮可见 30s；`[本仓]` |
| 3 | `fill_metadata` | 清空 caption，插入 title，逐个插入 `#tag ` | `div.public-DraftEditor-content` | 每步 1s；`[本仓]` |
| 4 | `wait_media_ready` | 等 Post 可点；失败时重选文件 | `div.button-group > button >> text=Post`；重试入口 `button[aria-label="Select file"]` | 2s 轮询，受总预算约束；`[本仓]` |
| 5 | `apply_options` | 展开高级设置，按请求设置隐私/评论/复用/AIGC/品牌 | 见 5.4 | 每步 Playwright 默认 30s；`[官方前端代码]` |
| 6 | `apply_cover` | 仅 `thumbnail_path` 非空时执行 | 见 5.4 | 固定 3s；`[官方前端代码]` + `[开源实现]` |
| 7 | `apply_schedule` | 现有定时控件 | `get_by_label('Schedule')`、`div.scheduled-picker` | `[本仓]` |
| 8 | `click_publish` | 单次点击发布并等成功页；未到成功页时最多点一次弹窗 `Post now` | `[data-e2e="post_video_button"]` → `button:has-text("Post").last` → `div.button-group button` nth(0)；弹窗 `button:has-text("Post now")` / role button | 单次 3s，0.5s 重试，总预算 15min；首次点击成功后不再点击原 Post 按钮；`[官方前端代码]` + `[本仓]` |
| 9 | `read_result` | 读 Content 列表首条视频 ID | `div[data-tt="components_PostTable_Container"]`、`a[href*="/video/"]` | 现有；失败退出 1（已知风险） |

### 5.3 图片路径

| # | 步骤 | 动作 | 候选选择器（按优先级） | 等待/置信度 |
| --- | --- | --- | --- | --- |
| 1 | `ensure_mode` | `goto(".../upload?tab=photo")`；确认图片表单；必要时点 `Photos` | `page.get_by_text("Photos", exact=True).first`；Title `input[placeholder*="catchy"]` 作为已进入图片模式的信号 | 入口探测在选文件前；缺失退出 1；`[官方前端代码]` + `[开源实现]` |
| 2 | `attach_media` | `set_input_files(image_paths)` | `input[type="file"][accept*="image"]` → `input[type="file"][multiple]` | 必须先切 tab；`[官方前端代码]` + `[开源实现]` |
| 3 | `fill_metadata` | 填 Title；Description；追加 tags | Title `input[placeholder*="catchy"]` / `input[placeholder="Add a catchy title"]`；Description `.public-DraftEditor-content`（限定在 `.caption-textarea` 或 caption 区） | `[官方前端代码]` + `[开源实现]`；描述选择器待实测 |
| 4 | `wait_media_ready` | 等图片处理完成、Post 可点 | 至少一个 `div[data-id]`；`text=Cover` 徽标；`[data-e2e="post_video_button"]` 可用 | 2s 轮询，受总预算约束；`[官方前端代码]` + `[仅推断]` |
| 5 | `apply_options` | 同视频，但跳过 reuse | 见 5.4 | 控件缺失且显式请求 → 退出 1；`[官方前端代码]` + `[仅推断]` |
| 6 | `apply_cover` | no-op（第 1 张即封面） | — | `[官方前端代码]` |
| 7 | `apply_schedule` | 基类复用 | 同视频 | `[本仓]` + `[开源实现]` |
| 8 | `click_publish` | 同视频；若出现 `Post now` 弹窗则兜底点击 | `[data-e2e="post_video_button"]` → `button:has-text("Post").last` → `div.button-group button` nth(0)；弹窗 `button:has-text("Post now")` | 图片帖通常无弹窗；兜底待实测 |
| 9 | `read_result` | 读图片帖 item id | `a[href*="/post/photo?item_id="]` | 失败退出 1（与视频一致） |

### 5.4 选项控件与回读

作用域默认 `self.locator_base`（可能位于 iframe）；只有 `Turn on` 等弹窗在顶层 `page` 上查找。

| 选项 | 容器/入口 | 候选选择器 | 读取方式 |
| --- | --- | --- | --- |
| 展开高级设置 | `[data-e2e="advanced_settings_container"]` | `.more-btn` → `text="Show more"`；检查 `.collapsed` | 等待目标控件可见 |
| 隐私 | `[data-e2e="video_visibility_container"]` | `button[role="combobox"]` → 点击 → `li[role="option"]` | combobox 文本；选项 `aria-selected="true"` |
| 评论 | `[data-e2e="user_perm_container"]` | `get_by_role("checkbox", name="Allow comments")` → label 文本 | `is_checked()` |
| 内容复用 | 同上 | `get_by_role("checkbox", name="Allow reuse of content")` → label 文本 | `is_checked()` |
| AIGC | `[data-e2e="aigc_container"]` | `[role="switch"]` → `.Switch__content` | `aria-checked` |
| AIGC 首次引导 | 顶层 dialog | `get_by_role("button", name="Turn on")` → `[role="dialog"] button:has-text("Turn on")` | 弹窗消失后再回读 |
| 品牌总开关 | `[data-e2e="disclose_content_container"]` | `[role="switch"]` → `.Switch__content` | `aria-checked` |
| Your brand | 总开关后的兄弟容器 | `get_by_role("checkbox", name="Your brand")` → `get_by_text("Your brand", exact=True)` | `checked` / `aria-checked` |
| Branded content | 同上 | `get_by_role("checkbox", name="Branded content")` → `get_by_text("Branded content", exact=True)` | `checked` / `aria-checked` |
| 视频封面入口 | 预览区 | `get_by_text("Edit cover", exact=True)` → `get_by_role("button", name="Edit cover")` | 编辑器出现 |
| 封面上传页签 | 封面编辑器 | `get_by_text("Upload cover", exact=True)` | 文件输入可用 |
| 封面文件输入 | 封面编辑器 | `[aria-label="Upload cover image"] input[type="file"]` → `input[type="file"][accept*="image/jpeg"]`（限定在编辑器内） | 上传后出现 `[aria-label="Uploaded cover image"]` |
| 封面保存 | 封面编辑器 | `get_by_role("button", name=re.compile(r"^(Save|Confirm)$"))` | 编辑器关闭 |

### 5.5 选择器策略（08 决策）

1. 每个步骤维护**有序候选列表**；主选优先 `data-e2e`，其次 role/accessible name，最后文本。
2. 第一个命中的候选胜出；命中后记录 INFO 日志（步骤名 + 候选序号），便于漂移诊断。
3. **不做跨步骤通用兜底**，不做全页模糊搜索；hash class 只能作为已有控件的最后兜底。
4. 所有候选失败时，错误消息必须包含：控件名、阶段、已尝试候选、当前 URL。
5. 设置与回读使用同一候选列表解析控件，避免“点到一个、读的是另一个”。
6. `data-e2e` 选择器作用在 `locator_base` 上；弹窗/toast 才用顶层 `page`。

---

## 6. 设置后回读、失败语义与退出码

### 6.1 回读规则

1. `None`（未传）→ **零次**控件交互；测试必须能断言“没有设置类调用”。
2. 显式传值 → 设置 → 回读最终状态 → 比较：
   - 一致 → 成功，即使控件置灰、账号级限制已满足。例：账号已禁评论 + `--no-comments` → 成功。
   - 不一致 → 失败，不点击发布，退出 `1`；stderr 写明选项名、请求值、实际值。
3. 不回退页面默认值，不“警告后继续”。
4. 品牌声明：请求任一品牌项时，先打开 `Disclose post content`，再显式设置两个复选框；未请求项取消勾选。
5. AIGC：切换开关；若出现 `Labeling AI-generated content`，点 `Turn on`；随后回读 `aria-checked`。容器不存在且显式传了 `--aigc/--no-aigc` → 失败退出 `1`。
6. `apply_options` 必须完整成功后才进入封面/定时/发布；任一步失败立即中止。
7. 不做“能力预检”（不预先读取选项矩阵、`disabled` 状态、视频时长上限）。唯一例外：图片帖的 Photos tab 探测，因为它决定文件进入哪个 input。

### 6.2 退出码

| 码 | 含义 | 典型场景 |
| --- | --- | --- |
| `0` | 成功 | 发布已提交；check 已登录 |
| `1` | 运行失败 | 账号能力不支持、回读不一致、网络/5xx/超时、页面结构异常、未点击发布即失败 |
| `2` | 用法错误 / 本地校验失败 | 未知子命令、缺必填、图片数量/格式/大小、Title/Description 超长、非法互斥组合 |
| `9` | **发布结果未知**（新增） | 点击已发出、未到成功页、未命中登录跳转；**禁止自动重发** |
| `10` | 需要人工登录 | 登录页、验证码、2FA 跳转 |
| `130` | 用户中断 | Python 默认；不在 `sau_cli` 显式映射 |

实现落点：

- `utils/errors.py` 新增 `PublishResultUnknownError`。
- `sau_cli.main` 在 `LoginRequiredError` 分支之后、通用 `Exception` 之前映射为 `9`。
- `upload-video` 与 `upload-note` 共用同一映射。
- `README.md`、`docs/CLI.md`、调度侧退出码契约加入 `9`，并注明“禁止自动重发”。
- 账号能力不支持**不新增**退出码，仍为 `1`。

### 6.3 发布结果未知（9）判定

定义：**点击动作已发出 + 没有观察到成功页 + 没有命中登录/验证码跳转**。

1. 跟踪 `publish_clicked`：`publish_button.click()` 调用返回且未抛异常即置真。
2. 到达 `https://www.tiktok.com/tiktokstudio/content` → 成功；之后仍调用 `read_result`。查询失败会导致整次运行退出 `1`（现状，已知风险，本 effort 不改）。
3. 总预算耗尽但 `publish_clicked == False` → 普通失败，退出 `1`，消息说明“未发布”。
4. 已点击、到总预算仍未到成功页、且未命中登录 URL → `PublishResultUnknownError`，退出 `9`。
5. 已点击后页面/上下文关闭、CDP 断开、停在表单报错、点击落在禁用按钮上空操作 → 同样按第 4 条处理，不再吞异常空转到预算耗尽。
6. 点击后 URL 命中 `/login`、`captcha`、`verify`、`two-factor`、`2fa` → `LoginRequiredError`，退出 `10`（优先于 `9`）。
7. `PublishResultUnknownError` 只能由发布阶段抛出；新增步骤函数不得吞异常。

点击去重约束：首次 `click()` 返回成功后，代码只等待/重试导航，**永不再次点击原 Post 按钮**，避免生成重复帖子。唯一允许的兜底点击是成功页未出现时对可见 `Post now` 弹窗按钮的一次点击；该按钮也只点一次。

调度侧契约：

- 收到 `9`：**禁止自动重发**，可能已经发出。
- 人工核验：TikTok Studio → Content/Posts，按标题与发布时间核对；已存在不要重发，不存在才可人工重试。
- 机器信号只有退出码 `9`；stderr 写中文说明与核验路径。

### 6.4 登录 / 验证码 / 能力不足

- 发布前 `is_logged_in(session.context)`：登录页或登录表单 → `False` → 退出 `10`；无法识别页面结构 → 抛异常 → `1`。
- 发布过程中每轮调用 `_raise_if_login_required(page)`：只看 URL path 的 `/login`、`captcha`、`verify`、`two-factor`、`2fa` → `10`。
- 内嵌验证码/2FA 如果不跳 URL → 不识别，落到普通失败 `1`。这是**已知盲区**，不新增 DOM 检测。
- 账号能力不支持 → `1`，消息写明请求值与实际值。

### 6.5 超时常量（沿用现状，不新增单步上限）

| 环节 | 值 | 现状 |
| --- | --- | --- |
| 登录检测总预算 | 20s | `TIKTOK_LOGIN_CHECK_TIMEOUT_MS` |
| 登录检测入口轮询 | 5s | `TIKTOK_ENTRY_WAIT_MS` |
| 进入上传页 URL | 10s | `page.wait_for_url` |
| iframe / `div.upload-container` 出现 | 10s | `wait_for_selector` |
| 上传按钮可见 | 30s | Playwright 默认 |
| 发布循环总预算 | 15 分钟 | `TIKTOK_PUBLISH_TIMEOUT_SECONDS` |
| 点击发布后等成功页 | 单次 3s，失败 0.5s 后重试，直到总预算 | `click_publish` |
| 封面上传后 | 固定 3s | 现有等待 |
| 表单输入之间 | 固定 1s | 现有等待 |
| 新增隐私/开关/AI/品牌步骤 | 每次操作 Playwright 默认 30s，步骤之间沿用 1s | 新代码按现有风格 |

图片帖使用同一个 15 分钟预算。35×50 MB 极端情况如确不够，后续单独调常量，不在本规格预设。

---

## 7. 代码落点与实施阶段

### 7.1 类型与构造器

```python
@dataclass(frozen=True, slots=True)
class TiktokPublishOptions:
    privacy: str | None = None          # public / friends / followers / only-me
    allow_comments: bool | None = None  # None = 不动页面默认
    allow_reuse: bool | None = None
    aigc: bool | None = None
    your_brand: bool | None = None
    branded_content: bool | None = None
```

- 位置：`uploader/tk_uploader/main_chrome.py`（避免 CLI → uploader 的反向依赖）。
- `TiktokVideo.__init__(title, file_path, tags, publish_date, account_file, thumbnail_path=None, *, options=None)`：前 5 个 positional 逐字不变，第 6 个保持兼容，新增项 keyword-only。
- `TiktokNote.__init__(image_paths, note, tags, publish_date, account_file, *, title=None, options=None, debug=True, headless=True)`。
- `TiktokVideoUploadRequest` 增加 `options: TiktokPublishOptions | None = None`；新增 `TiktokNoteUploadRequest` 与 `_build_note_uploader`；视频 builder 名字不改。

### 7.2 类与方法迁移

| 现方法 | 去处 |
| --- | --- |
| `_upload_on_page` | `TiktokBaseUploader`，重写为 9 步模板 |
| `upload_in` / `_check_publish_deadline` / `click_publish` / `choose_base_locator` | `TiktokBaseUploader`，名字不改 |
| `set_schedule_time` | `TiktokBaseUploader.apply_schedule` |
| `add_title_tags` | `TiktokBaseUploader.fill_caption(text, tags)`（逻辑不变，`self.title` 改参数） |
| `detect_upload_status` | `TiktokVideo.wait_media_ready` |
| `upload_thumbnails` | `TiktokVideo.apply_cover`（选择器刷新） |
| `get_last_video_id` | `TiktokVideo.read_result` |
| `handle_upload_error` / `change_language` / 本地 `upload()` | 留在 `TiktokVideo` |
| `upload()`（session 分支） | `TiktokBaseUploader.upload_in`；视频保留“本地 + session”双分支 |

- 新增基类：`TiktokBaseUploader(BaseVideoUploader)`；子类 `TiktokVideo`、`TiktokNote`。
- 全部代码仍在 `uploader/tk_uploader/main_chrome.py`；超过约 800 行再按仓库多文件先例拆分。
- `TiktokNote.upload()` 只有 session 分支，本地模式直接报错（与 TikTok 仅 MLX 一致）。
- 选择器内联在所属步骤；`tk_config.py` 改为常量文件，保留 `Tk_Locator.tk_iframe` / `default` 供 `choose_base_locator` 与未接线的 Firefox 分支使用。
- `tk_config.py` 新增常量：`TIKTOK_PHOTO_UPLOAD_URL`、图片张数上限 35、单张 ≤50 MB、Title ≤90、Description ≤4000、hashtag ≤50。

### 7.3 实施阶段

| 阶段 | 内容 | 验证 |
| --- | --- | --- |
| 1 | `utils/errors.py` 加 `PublishResultUnknownError`；`sau_cli.py` 映射 `9`；`tk_config.py` 常量与 `TIKTOK_UPLOAD_URL` 迁移 | 退出码离线测试 |
| 2 | 抽出 `TiktokBaseUploader`，按 7.2 改名；不改变任何行为 | 全量离线套件；旧 TikTok 契约只改 2 条断言 |
| 3 | 视频选项：`TiktokPublishOptions`、`apply_options`、`readback_options`、品牌/AIGC 规则 | 7 组离线测试中的映射/步骤/顺序组 |
| 4 | 视频封面选择器刷新：`Edit cover` → `Upload cover` → `Save` | 覆盖 `[官方前端代码]` 路径；冒烟验证 |
| 5 | `upload-note` CLI + `TiktokNote` + Photos 探测 + 图片上传/表单 | 参数/图片组；冒烟图片用例 |
| 6 | 图片帖选项复用 + Title/Description/tags | 步骤组；冒烟 |
| 7 | 文档、Skill、CHANGELOG、冒烟手册、人工验收清单 | `git diff --check`；文档审阅 |
| 8 | 真实账号冒烟与发布验收（外部依赖） | 第 8.3 节清单；未完成项标记“待验收” |

### 7.4 兼容性边界

- `upload-video` 不传任何新参数时：操作序列与当前实现一致，**不得多出任何设置类调用**；stdout 不变。
- 旧 positional 构造调用（含 `examples/upload_video_to_tiktok.py` 的 5/6 参调用）继续可用。
- 旧退出码 `0/1/2/10/130` 语义不变；`9` 是纯新增。
- `patchright` 版本与 MLX 契约不变；不新增依赖。

---

## 8. 测试与验收

### 8.1 默认离线套件（`python -m unittest discover -s tests`）

不引入 pytest、不新增依赖、默认不启浏览器、不访问网络。7 组，每组至少一条正向 + 一条负向断言：

| # | 组 | 覆盖与断言要点 |
| --- | --- | --- |
| 1 | 参数与校验 | `upload-video` 新 flag 全部出现在 parser；`upload-note` 注册为合法 action；`--images` 1..35、仅 JPG/JPEG/PNG/WEBP、单张 ≤50 MB；Title ≤90、Description ≤4000、hashtag ≤50；`--note`/`--notef` 互斥；`--aigc`/`--no-aigc` 互斥；`--privacy` 仅四个枚举；非法值/超限 → `2`，且在启动浏览器前失败 |
| 2 | 映射 | CLI → request dataclass；未传 = `None` 三态，不得提前填默认值；隐私枚举 ↔ 页面语义；`--your-brand`/`--branded-content` 归一化（未请求项显式取消勾选）；`--disable-reuse` 单开关；`upload-note` 不产生 reuse / thumbnail 字段 |
| 3 | 步骤逻辑 | 内存 fake 上五条分支：未传不操作；显式设置后回读；回读不一致 → 失败并报选项名/请求值/实际值；置灰但目标已满足 → 成功；品牌声明自动打开 + 两个复选框都显式设置 |
| 4 | 流程顺序 | 粗粒度断言：设置步骤先于发布；封面步骤后于处理完成；旧 `upload-video` 不带新参数时，操作序列与当前实现一致（无设置类调用） |
| 5 | 退出码 | `0/1/2/9/10`；`PublishResultUnknownError` 仅在“点击已发出 + 未到成功页 + 未命中登录”时产生；`9` 的消息含“禁止自动重发”；从未点击发布 → `1` 而不是 `9` |
| 6 | 超时与登录 | `TIKTOK_LOGIN_CHECK_TIMEOUT_MS == 20_000`、`TIKTOK_PUBLISH_TIMEOUT_SECONDS == 900`；中途 URL 命中 login/captcha/verify/2fa → `10`；内嵌验证码不识别 → `1`（锁现状） |
| 7 | 图片特有 | 先探测 Photos tab 再选文件；探测失败在选文件前退出 `1`；不调用 reuse/duet/stitch；第 1 张即封面；`--thumbnail` 不存在于 `upload-note` |

页面 fake 边界：

- 新增能力写成步骤函数，只依赖极简控件接口：`set(value) -> None`、`read() -> value`、`disabled -> bool`。
- 默认套件用内存 fake：记录调用、维护当前值、可模拟“置灰但目标已满足”“set 后 read 不一致”。
- 不模拟 DOM 标签、`Show more` 折叠、label 文案、层级结构；不断言 CSS 字符串。

新增测试文件：

- `tests/test_tiktok_settings.py`：内存 fake + 步骤逻辑。
- `tests/test_tiktok_note_cli.py`：`upload-note` 参数、校验、映射、图片特有流程。
- `tests/test_tiktok_smoke.py`：opt-in 冒烟（8.2）。

### 8.2 opt-in 表单级冒烟

文件：`tests/test_tiktok_smoke.py`；开关 `SAU_TIKTOK_SMOKE=1`，未设置整模块 skip。

前置：

1. Multilogin 桌面应用在本机运行，Profile 使用 Mimic 内核。
2. Profile 界面语言 English (US)，已登录一个可发布的公开 TikTok 账号。
3. 复用 `MLX_API_TOKEN`、`SAU_MLX_FOLDER_ID`、`SAU_MLX_PROFILE_ID`；与 `SAU_MLX_SMOKE` 共用 Profile 时串行运行。
4. 样本：`videos/demo.mp4`、`videos/demo.png`，不新增二进制。

视频用例：

1. 打开 `TIKTOK_UPLOAD_URL`，断言上传入口存在。
2. 选 `videos/demo.mp4`，等表单出现。
3. 展开 Settings / Show more。
4. 逐控件定位 → 设置安全值 → 回读断言；覆盖隐私、评论、reuse、AIGC、Your brand、Branded content。
5. 打开封面编辑器并验证 `Upload cover` 入口。
6. **绝不点击 Post / Schedule。**

图片用例：

1. 探测 Photos tab；缺失 → 只 skip 本用例并输出原因（灰度，不是代码失败）。
2. 有则选 `videos/demo.png`，验证 Title/Description/tags 与隐私/评论/AIGC/品牌控件（不测 reuse）。
3. 第 1 张即封面；**绝不点击 Post / Schedule。**

失败与跳过矩阵：

| 情况 | 行为 |
| --- | --- |
| `SAU_TIKTOK_SMOKE` 未设置 | 整模块 skip |
| 开关打开但变量缺失 | fail，指出缺哪个变量 |
| 未登录 / 登录页 / 验证码跳转 | fail，要求先在 Multilogin 登录 |
| 上传页打不开 / 视频路径控件缺失 | fail，报控件名 + 候选 + URL |
| 账号没有 Photos tab | 只 skip 图片用例 |
| 设置后回读不一致 | fail，报选项/请求值/实际值 |

副作用：不发布，但可能留下未发布草稿。冒烟不自动删除；清理方式：TikTok Studio → Content/Drafts 手动删除。设置不跨表单记忆，冒烟不会污染后续运行。

### 8.3 人工发布验收清单

证据 = 退出码 + 帖子 URL/截图，记录日期、账号类型、Profile。

| 项 | 必做/条件 | 核对方式 |
| --- | --- | --- |
| 视频无新参数发布 | 必做（公开账号） | 退出 `0`；Content 列表出现新帖 |
| `--privacy only-me` | 必做 | 帖子仅自己可见 |
| `--no-comments` | 必做 | 评论入口关闭 |
| `--disable-reuse` | 必做 | 合拍/拼接/贴纸/Story 复用关闭 |
| `--aigc` | 必做 | 帖子显示 AI-generated 标识 |
| `--your-brand` / `--branded-content` | 必做 | 声明出现在帖子/审核态 |
| 视频自定义封面 | 必做 | 封面为上传图 |
| `--schedule` | 必做 | 到点发布，时间正确 |
| `upload-note` 多图 | 必做 | 顺序正确，第 1 张为封面，标题/正文/tags 正确 |
| 图片帖设置项 | 必做 | 页面若渲染 AIGC/品牌则核对；未渲染记为“页面不支持” |
| 私有账号首项文案、`friends` + 品牌组合 | 有条件（第二个账号） | 首项显示 `Followers`；组合可用性记录为置信度 |
| Photos tab 灰度 | 有条件 | 无入口时记录账号未覆盖 |
| 账号能力不支持时退出 `1` | 有条件 | 用不匹配组合触发，stderr 含请求值/实际值 |
| 退出码 `9` 的破坏性复现 | **不要求** | 离线已锁映射；人工不制造“结果未知” |

私有账号 / Photos 灰度 / `friends`+品牌组合未实测时，结论保持“条件可行 / 未验证”，不得写成已验证。

### 8.4 选择器漂移刷新流程

1. 跑 `SAU_TIKTOK_SMOKE=1` 冒烟。
2. 失败信息会给出控件名、已尝试候选、当前 URL、阶段。
3. 只更新对应步骤的候选列表，不做全局替换。
4. 重跑冒烟；再跑默认离线套件确认无回归。
5. 更新 `research/` 中对应条目的置信度（若从 `[官方前端代码]` 变为 `[实测]`）。

### 8.5 现有测试改动

- `tests/test_mlx_tiktok.py` 保留为旧 `upload-video` 回归基线。
- 只改两条必然冲突的断言：
  1. `test_actions_are_check_upload_video_login_only`：action 集合加入 `upload-note`，并改名去掉 `_only` 语义。
  2. `test_unknown_subcommand_still_exits_2`：未知子命令样本换成真正不存在的名字（如 `upload-audio`），不再用 `upload-note`。
- `test_init_positional_order_is_unchanged`：改为断言前 5 个 positional 前缀不变 + 新参数必须 keyword-only。
- `detect_upload_status` → `wait_media_ready` 的调用点改名（2 行）。
- 复用现有 `_run`、`_AsyncCM`、`_subparser`、`_option_strings` 与 `tests/fakes.py`；不重写旧文件、不拆文件、不 skip。

---

## 9. 文档与 Agent Skill 变更清单

| 文件 | 变更 |
| --- | --- |
| `README.md` | 平台表 TikTok 行：图文列改为 `✅`，说明补“视频与图文；仅 Multilogin 模式；Profile 界面需 English (US)”；部署前提/不支持列表复核 |
| `docs/CLI.md` | 退出码表加入 `9`（禁止自动重发）；平台支持范围 TikTok 加 `upload-note`；TikTok 小节补新 flag、`upload-note` 示例、限制与错误语义 |
| `skills/tiktok-upload/SKILL.md` | 删除“TikTok 没有 `upload-note`，不要虚构该子命令”；命令示例补 `upload-note` 与新 flag；退出码补 `9`；保留“未知结果先核查、不能直接重发”的约束；把 Skill 描述从“视频”扩展到“视频与图文” |
| `CHANGELOG.md` | `[Unreleased]` 增加 TikTok 小节：新增 flags、`upload-note`、退出码 `9`；未做真实账号验收的能力必须写“待验收” |
| `GLOSSARY.md` | 新增“设置后回读”“发布结果未知”“Photos tab / 图片帖”三个术语 |
| `examples/upload_video_to_tiktok.py` | 可选：不强制改；如改，只演示新 keyword-only 参数，不破坏旧调用 |

`docs/agents/`、`AGENTS.md` 不需要改。

---

## 10. 部署前提

1. CLI 与 Multilogin 桌面应用在同一台 macOS/Windows 机器，桌面应用已启动。
2. Profile 使用 **Mimic** 内核，已人工登录目标 TikTok 账号，且无待处理验证码/2FA。
3. Profile 界面语言必须为 **English (US)**；MLX 分支跳过 CLI 内语言切换。
4. 图片帖额外要求账号被 Photos tab 灰度覆盖；未覆盖时 `upload-note` 在选文件前退出 `1`。
5. 定时发布要求账号 `schedule_enable` 可用。
6. 冒烟/验收不得与 `SAU_MLX_SMOKE` 并行使用同一 Profile。
7. 无新增运行时依赖；`patchright` 版本不变。

---

## 11. 风险、待实测与回滚

### 11.1 实施时必须先实测的项

| 项 | 影响 | 兜底 |
| --- | --- | --- |
| 图片帖网页端是否渲染 AIGC / 品牌控件 | 显式请求时可能没有容器 | 缺失 → 退出 `1`（与 06 一致），不静默忽略 |
| 图片帖 Title/Description 的精确 DOM 与必填性 | 表单填写失败 | 用可见文案与 `caption-textarea` 候选；冒烟定位 |
| Photos tab 灰度范围 | 目标账号可能无入口 | 选文件前探测，缺失即退出 `1` |
| 私有账号首项文案、`friends` + 品牌组合 | 回读映射可能有变体 | 归一化文本；冒烟/人工记录 |
| 图片帖 `Post now` / 检查弹窗 | 点击后可能不跳成功页 | 兜底点击 `Post now`；否则按 `9` 处理 |
| AIGC `show_aigc_toggle` A/B flag | 容器可能不存在 | 显式请求时退出 `1`；未请求不触碰 |
| 封面预览变化是否等于服务端接受（上游 issue #228） | 可能显示成功但封面未生效 | 发布后人工核验；页面状态断言 |
| 35×50 MB 是否在 15 分钟内完成 | 极端情况超时 | 保留常量，后续单独调；不在本规格预设 |

### 11.2 风险表

| 风险 | 等级 | 处理 |
| --- | --- | --- |
| 选择器漂移（hash class、文案变更） | 高 | `data-e2e` 优先、候选列表、冒烟命名失败、按 8.4 刷新 |
| Photos tab 灰度导致 `upload-note` 不可用 | 高 | 条件可行；明确报错；文档标注 |
| AIGC 容器缺失 | 中高 | 显式请求才失败；不把“缺失”当“关闭” |
| 品牌与 Private 互斥 | 中 | 本地校验 `branded-content + only-me` → `2`；页面仍回读 |
| `--disable-reuse` 影响范围大于 API 两个字段 | 中 | 文档注明 Stickers/Story；不提供独立 duet/stitch |
| 图片帖封面只能第 1 张 | 中 | 不暴露 `--cover-index`；文档说明换封面会改顺序 |
| 发布结果未知（9）被误自动重发 | 中高 | 退出码 + stderr + README/CLI/调度契约；禁止自动重发 |
| 发布后 `read_result` 失败却已发布 → 退出 `1` | 中 | 现状已知风险；文档提示先核查 Content 列表 |
| 内嵌验证码/2FA 不跳 URL → 不识别人工登录 | 中 | 已知盲区；不新增 DOM 检测 |
| 默认 `Allow AI to remix content` 保持开启 | 低 | v1 不暴露；文档记录 |
| 图片帖配乐、草稿不覆盖 | 低 | 明确非目标；Skill 不虚构 |

### 11.3 回滚

- **行为级回滚**：不传新 flag 时行为与当前完全一致，运营侧可直接退回旧命令。
- **代码级回滚顺序**：阶段 6 → 5 → 4 → 3（保留阶段 1/2 的纯重构与错误码，风险最低）；每阶段独立提交，可单独 revert。
- **`upload-note` 紧急下线**：移除 `sau_commands/tiktok.py` 的 subparser 注册与 `TiktokNote` 引用，同步回滚 Skill/README/CLI 文档；视频路径不受影响。
- **退出码 `9` 回滚**：删除 `PublishResultUnknownError` 映射后，未知结果会退回 `1`；调度侧仍按“非零不自动重发”处理，因此回滚安全。
- 无数据迁移、无新增依赖、无配置格式变化。

---

## 附录 A：决策索引

| 决策 | 工单 |
| --- | --- |
| 图片帖入口/限制/封面/字段 | [01](./issues/01-photo-post-feasibility.md) |
| AIGC 与品牌声明 | [02](./issues/02-aigc-brand-disclosure.md) |
| 隐私与互动开关 | [03](./issues/03-privacy-interactions.md) |
| 视频/图片封面 | [04](./issues/04-covers.md) |
| CLI 参数契约 | [05](./issues/05-cli-parameter-contract.md) |
| 设置后回读、退出码 `9`、超时 | [06](./issues/06-preflight-failure-semantics.md) |
| 三层测试与验收 | [07](./issues/07-test-strategy.md) |
| 共用骨架与扩展点 | [09](./issues/09-shared-flow-extension-points.md) |
| 本规格汇总、选择器策略、`--json` 非目标 | [08](./issues/08-assemble-spec.md) |
