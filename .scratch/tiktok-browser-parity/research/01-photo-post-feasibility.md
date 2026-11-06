# TikTok Studio 网页端图片帖（Photo / Carousel）可行性调研

> 调研日期：2026-11-05
> 范围：`https://www.tiktok.com/tiktokstudio/upload`，只讨论 **网页 UI 自动化**（patchright / Playwright / Multilogin X Profile），不涉及官方 Content Posting API。
> 方法：阅读本仓库约定 + 抓取 TikTok Studio 官方前端静态 bundle（未登录、未启动浏览器）+ 公开文档 + 两个已验证的开源实现。**没有**登录、没有点击真实后台、没有修改业务代码。

## 置信度标记说明

| 标记 | 含义 |
| --- | --- |
| **官方文档** | TikTok 帮助中心 / Creator Academy / 开发者文档的公开文字 |
| **官方前端代码** | 从 `www.tiktok.com` 公开静态资源下载的 TikTok Studio 前端 bundle（比“推断”强，但不是公开文档，且随构建变化） |
| **开源实现** | 公开 GitHub 仓库，且作者声明在 2026 年真实账号上跑通过 |
| **仅推断** | 由已知行为推导，尚无直接证据 |

---

## Question

1. 入口在哪里：上传页的 Photo/Images 切换、独立 URL，还是只能走 App？
2. 本地文件选择是否可行，最多多少张，支持哪些格式与大小限制？
3. 标题、正文（description）分别对应页面上的哪个输入框，各自长度上限是多少？
4. 配乐：是否有自动配乐/选择音乐，网页端能否控制？
5. 封面：是否可选第几张图作为封面？
6. 是否支持定时发布、草稿、多图排序？
7. 与视频上传模式相比，哪些字段存在、哪些缺失？

---

## Findings

### 1. 入口：网页端有独立的 Photos 模式，不是只能走 App

| # | 结论 | 置信度 | 证据 |
| --- | --- | --- | --- |
| 1.1 | 上传页存在 **Photos / Videos 两个 tab**，文案分别是 “Photos” 和 “Videos” | **官方前端代码** | i18n：`tiktokStudio_upload_photos_tab:"Photos"`、`tiktokStudio_upload_videos_tab:"Videos"`（bundle `9602.bceb34cf.js`） |
| 1.2 | 点 Photos tab 或带 `?tab=photo` 会进入图片模式 | **官方前端代码** | `"photo"===t.get("tab") ? TIKTOK_PICS : GENERAL`（`9602.bceb34cf.js`）；开源实现直接使用 `.../upload?tab=photo` |
| 1.3 | 图片编辑页有独立路由 `/tiktokstudio/upload/post/photo` | **官方前端代码** | 路由表 `POST_PHOTO:"/tiktokstudio/upload/post/photo"`（`12.ce49fd88.js`、`6240.60d62a9e.js`） |
| 1.4 | 该功能是 2026 年 7 月才开放到桌面 web 的，按账号/地区逐步放量 | **官方文档（间接）** / 行业记录 | Creator Academy 图片帖文章发布于 2026-07-03；SocialBee 2026-07 更新记录：“TikTok now allows users to create photo posts on desktop (web) as well.” |
| 1.5 | 2025 年及更早的“网页只能发视频”说法已过时 | **仅推断（对旧资料的解释）** | HeyMark / Postraid 仍写“Help Center 只描述 App 图片帖”，与 2026-07 后的官方 bundle 行为不一致，属于未更新资料 |

**结论：入口是“同一个上传页的 Photos tab”，同时存在可直接访问的独立 URL，不是只能走 App。**

---

### 2. 本地文件选择：可行；最多 35 张；JPG/JPEG/PNG/WebP；单张 50 MB（网页 UI 常量）

| # | 结论 | 置信度 | 证据 |
| --- | --- | --- | --- |
| 2.1 | 必须**先切到 Photos tab，再操作 file input**；默认（视频模式）input 的 `accept` 是视频，PNG 会被静默忽略（日志显示 set_files 成功，但表单永远不出现） | **开源实现** | alexsax777 `tiktok_photo_music.py` + `SKILL.md`：“Tab-ul Photos se clickă ÎNAINTE de upload — input-ul default are accept=video/*” |
| 2.2 | 图片页有两个 `input[type=file]`：一个 `multiple`（多图/追加），一个单图（替换某张） | **官方前端代码** | `6240.60d62a9e.js`：`input type="file" accept=c multiple` 与第二个单图 input |
| 2.3 | 默认最多 **35 张/帖** | **官方前端代码** + **官方文档** | bundle 常量 `Gd=35`（`4066.a7ec448b.js`），组件默认 `maxCount=35`；Creator Academy 明确“up to 35 images in a single post” |
| 2.4 | 超过 35 张时的行为：**先上传前 35 张，其余丢弃并 toast** | **官方前端代码** | i18n：`First {s_count} photos uploaded. Additional images were not added.` / `Maximum {s_count} photos per post` |
| 2.5 | 网页端接受格式：`image/jpg, image/jpeg, image/png, image/webp`；UI 推荐 “JPG, JPEG, PNG, and WebP” | **官方前端代码** | 常量 `iP="image/jpg,image/jpeg,image/png,image/webp"`（`4066.a7ec448b.js`）；i18n `Recommended: JPG, JPEG, PNG, and WebP` |
| 2.6 | 网页端单张上限 **50 MB** | **官方前端代码** | 常量 `gc=50`；i18n `Up to {s_count} photos, max {s_size} MB per photo` / `Some files exceed {s_count} MB.` |
| 2.7 | 1 张也可以发（不强制多图） | **开源实现** | alexsax777 的生产脚本就是单图发帖，声明 2026-09-24 成功 |
| 2.8 | 图片尺寸/分辨率在网页端没有发现客户端硬校验；bundle 中只显示 “Recommended: 16:9, 4:3, and 3:4” | **官方前端代码**（负面证据） | 在图片页相关 chunk 中未找到 min/max width/height 校验；只有上面这条推荐文案。**不要据此推断 1080p 是网页上传硬限制** |

> 注意：官方 **Content Posting API** 的限制是 JPEG/WebP、20 MB、最长边 1080p；这与**网页 UI**不是同一套限制。网页 UI 的 bundle 明确允许 PNG、50 MB。若未来改走 API，必须按 API 限制重新校验。

---

### 3. 标题 vs 正文：是两个独立字段

| # | 结论 | 置信度 | 证据 |
| --- | --- | --- | --- |
| 3.1 | **Title** 是图片模式独有的单行 `<input>`，placeholder “Add a catchy title” | **官方前端代码** + **开源实现** | bundle `titleInput-*` + i18n `tiktokStudio_uploadPhotos_title_placeholder:"Add a catchy title"`；nessed 用 `input[placeholder*="catchy"]` |
| 3.2 | Title 上限 **90 字符**，超出会被前端截断并 toast | **官方前端代码** + **官方文档** | bundle 常量 `tS=90`、`maxLength` 默认 90；API 文档 “maximum length for photo posts is 90” |
| 3.3 | **Description** 是 Draft.js 富文本编辑器（不是 textarea），placeholder “Writing a long description can help get 3x more views on average” | **官方前端代码** + **开源实现** | bundle 复用 `.public-DraftEditor-content` / `caption-textarea`；nessed `setTitle()` 等待 `.public-DraftEditor-content` |
| 3.4 | Description 上限 **4000 字符**，超出会截断并提示 “Maximum 4000 characters” | **官方前端代码** + **官方文档** | `captionMaxLength = LONG = 4e3`（`9602.bceb34cf.js`）；Creator Academy “You can have up to 4,000 characters for each post”；API 文档 4000 |
| 3.5 | 话题/提及是 description 里的 chip：最多 50 个 hashtag、50 个 mention | **官方前端代码** | toast 文案：`Add up to 50 hashtags`、`Mention up to 50 users`（`337.cc43c2bc.js`） |
| 3.6 | 标题和正文在提交结构里是两个字段：`image_post_content.title` 与 `single_post_feature_info.text` | **官方前端代码** | `6240.60d62a9e.js` 的 `collectForPost` |

**映射到本仓库的 CLI 语义：**
- `--title` → 页面的 **Title** 输入框（90 字符）
- `--note` / `--desc` → 页面的 **Description**（Draft.js，4000 字符）
- `--tags` → 追加在 description 里的 `#tag`（计入 4000，且总计不超过 50 个）

---

### 4. 配乐：网页端可手动选曲/搜索/收藏/推荐；没有发现“自动配乐”开关

| # | 结论 | 置信度 | 证据 |
| --- | --- | --- | --- |
| 4.1 | 图片模式有 “Add sound” 按钮和 Sound 区块 | **官方前端代码** + **开源实现** | i18n `details_addSound_btn:"Add sound"`、`details_sound_header:"Sound"`；alexsax 实际点击 `button:has-text("Add sound")` |
| 4.2 | 点开后是 TikTok 官方声音选择器（modal），可按关键词搜索、看收藏、看推荐，点 “Use” 应用 | **官方前端代码** + **开源实现** | bundle 推荐接口 `music/recommend/by/video` 且 `content_type:"multi_photo"`；alexsax 搜索后 JS 点击可见的 “Use” |
| 4.3 | 应用成功后页面出现 “Replace”（替换音乐）入口 | **开源实现** | nessed 的 `guardAndSchedule()` 用 `document.body.innerText.includes('Replace')` 判断已挂音乐 |
| 4.4 | 没有发现类似 API `auto_add_music` 的“自动配乐”开关；网页端需要用户/脚本显式选一首 | **官方前端代码**（负面证据） | 图片页插件只有 `music` 状态（选中的 track）；未发现 auto toggle。**不要承诺“自动配乐”** |
| 4.5 | 音乐是**可选**的：可以不加 sound 直接发 | **开源实现** | alexsax 的脚本在选不到音乐时选择 abort；但页面流程本身不要求 sound（无 required 标记）。实际是否强制建议真人复核 |

---

### 5. 封面：没有独立“选第几张作封面”，**第 1 张就是封面**

| # | 结论 | 置信度 | 证据 |
| --- | --- | --- | --- |
| 5.1 | 第一张缩略图显示 “Cover” 角标；`isCover: 0===index` | **官方前端代码** | `6240.60d62a9e.js`：`isCover:0===t` + i18n `details_coverPhoto_label:"Cover"` |
| 5.2 | 提交时 `cover: r[0]`，即图片数组第一张 | **官方前端代码** | `collectForPost`：`image_post_content:{images:r, cover:r[0]}` |
| 5.3 | 改变封面的方式是**拖拽排序**，把想当封面的图拖到第一位 | **官方前端代码** + **开源实现** | 图片网格 `onDragEnd` 重排；i18n “Drag and drop to reorder.”；nessed：“give the file input NN_1.jpg then NN_2.jpg (order matters, slide 1 is the cover)” |
| 5.4 | 没有视频模式那种 “Upload cover / 从视频帧选封面” 的独立封面上传 | **官方前端代码**（负面证据） | 图片页 i18n 只有 Cover 角标，没有 Upload cover 相关 key |

**结论：封面可选，但只能通过“调整图片顺序 + 第一张即封面”间接实现；不存在单独的 `photo_cover_index` UI 控件。**

---

### 6. 定时发布 / 草稿 / 多图排序

| # | 结论 | 置信度 | 证据 |
| --- | --- | --- | --- |
| 6.1 | **多图排序**：支持拖拽重排，文件选择顺序即初始顺序 | **官方前端代码** + **开源实现** | 同上 5.3 |
| 6.2 | **定时发布**：图片帖可使用 Schedule；已验证可成功排期 | **开源实现** + **官方前端代码** | nessed `POSTING.md` 明确“Schedule”流程（2026-10 测试）；bundle `scheduler` 插件 `shouldRun` 只看 `userInfo.schedule_enable`，不区分 photo/video |
| 6.3 | 定时资格不是所有人都有：取决于账号（TikTok 帮助中心：Business 账号或 ≥10k 粉丝；15 分钟–10 天） | **官方文档（间接）** | TikTok Help Center 的 Schedule video 条款被 HeyMark 引用；bundle 用 `schedule_enable` 控制显示。**图片帖是否完全沿用该资格，未能 100% 确认** |
| 6.4 | **草稿**：图片模式有本地草稿自动保存 + 云端草稿路由 `?draft_id=` + “未保存的图片帖”恢复提示 | **官方前端代码** | `localDraft` 插件 `shouldRun` 只对 `TIKTOK_PICS` 启用；路由 `/upload/post/photo?draft_id=` → `PHOTO_DRAFT`；i18n `You have an unsaved photo post. Continue editing?` |
| 6.5 | 草稿数量有上限（每账号），超出时提示 “Manage drafts” | **官方前端代码** | i18n `Each account can only save up to {d_draftCount} drafts.` |
| 6.6 | 图片帖的“手动 Save draft 按钮”具体文案/位置未在 bundle 中定位到 | **仅推断** | 只能确认草稿机制存在，不能确认按钮 selector。需真人登录复核 |

---

### 7. 与视频模式相比的字段差异

| 字段 | 视频上传 | 图片帖 | 置信度 |
| --- | --- | --- | --- |
| Title（90） | 无（视频只有 caption） | **有** | 官方前端代码 |
| Description / Caption（4000） | 有 | 有 | 官方前端代码 + 官方文档 |
| 封面 | 上传自定义图 / 选视频帧 | **只能第一张图，拖拽排序间接选** | 官方前端代码 |
| 音乐 | 用文件自带音轨，网页不提供 TikTok 曲库 | **有 TikTok 声音选择器** | 官方前端代码 + 开源实现 |
| Duet / Stitch | 有 | **不适用（没有）** | 官方文档（间接）/ 行业资料 |
| 定时发布 | 有（符合资格） | 有（符合资格，已验证） | 开源实现 + 官方前端代码 |
| 草稿 | 有 | 有（本地自动草稿 + 云端草稿） | 官方前端代码 |
| 可见性 / 评论 | 有 | 有（“Who can see this post”） | 官方前端代码 |
| AI 生成内容标签 | 有 | **有**（`aigcInfo` 插件无 awemeType 限制） | 官方前端代码 |
| 商品链接 / 合集 / 声明 | 有（`--product-link`、`--collection` 等） | **未发现对应字段** | 仅推断（图片页插件列表无相关项） |
| 图文编辑（发布后） | 视频可编辑 | 有 `PHOTO_EDIT` 路由，但部分状态会显示 “Photo posts cannot be edited.” | 官方前端代码（需复核具体条件） |
| 文件格式 | MP4 / WebM | JPG / JPEG / PNG / WebP | 官方前端代码 |

---

## 可执行 UI 流程（建议实现顺序）

1. **前置**：Multilogin Profile 已登录，界面语言为 English (US)（本仓库 `main_chrome.py` 的部署前提）。
2. `page.goto("https://www.tiktok.com/tiktokstudio/upload?tab=photo")`；若该 URL 没进入图片模式，则回退到 `/tiktokstudio/upload` 后点击 `Photos` tab。
3. **确认已切到图片模式**（关键）：检查页面出现 “Select photos” 或 `input[type=file][accept*="image"]`。**不要**在视频 input 上 `set_input_files`。
4. `set_input_files([p1, p2, ...])`，按期望展示顺序传入；最多 35 张。
5. 等待表单出现：`input[placeholder*="catchy"]`（Title）与 `.public-DraftEditor-content`（Description）。
6. 填 Title（≤90）；填 Description（≤4000），hashtag 逐個输入并等待建议列表后再 Enter（否则会变成纯文本）。
7. 可选：点 `Add sound` → 在 modal 中搜索/选收藏 → 点 `Use`；确认出现 `Replace`。
8. 可选：设置 “Who can see this post”；按需设置 AI 标签/商业内容声明。
9. 可选：点 `Schedule` → 选日期 → 选小时/分钟（`.tiktok-timepicker-option-text...`）。
10. 点 `Post`；若出现 “Post now” 弹窗则点它；成功标志是 URL 跳到 `https://www.tiktok.com/tiktokstudio/content`。
11. 在内容列表复核标题/封面/图片数量；图片帖的列表项 URL 形如 `/tiktokstudio/upload/post/photo?item_id=...`。

### 已验证的实现细节（来自开源生产脚本）

- **Photos tab 必须在文件选择前点击**；否则默认 input 是 `accept=video/*`，PNG 静默失败。
- **Add sound 必须点真实按钮**；对文本 `force=True` 点击不会打开面板。
- 声音搜索框只在 modal 内取：`[role="dialog"] input`；页面第一个 `input[type=text]` 是 Title，写错会污染标题。
- 声音结果的 `Use` 按钮常被建议下拉层遮挡，Playwright 普通 click 会 timeout；开源实现用页面内 JS 点击可见的 `Use`（`offsetParent !== null`）成功。
- **预览切到 “Profile”**：默认 “Feed” 预览会自动播放并抢键盘焦点，导致输入的文字消失（多图/定时场景尤其明显）。
- 图片帖通常**不会**出现视频那种 “Continue to post?” / “Post now” 检查弹窗；但仍建议做兜底。

---

## 候选选择器（Playwright locator，注明来源）

> 类名 hash（`titleInput-JiU8Rn`、`photoItem-UG1zR_`）会随构建变化；优先用文本、placeholder、role 和稳定前缀。以下仅列有来源的写法。

| 目标 | 候选 locator | 来源 | 备注 |
| --- | --- | --- | --- |
| 进入 Photos tab | `page.get_by_text("Photos", exact=True).first` | 开源实现 alexsax | 生产验证；点击前不要碰 file input |
| 直接进入图片页 | `page.goto("https://www.tiktok.com/tiktokstudio/upload?tab=photo")` | 开源实现 nessed | 与 bundle 的 `?tab=photo` 判定一致 |
| 图片页路由 | `https://www.tiktok.com/tiktokstudio/upload/post/photo` | 官方前端代码 | 可用于直接打开/编辑 |
| 文件输入（多图） | `page.locator('input[type="file"][accept*="image"]')` | 官方前端代码 | 图片页 accept 为 image/*；需先切 tab |
| 文件输入（兜底） | `page.locator('input[type="file"]').first` | 开源实现 alexsax | 仅在已确认图片模式后使用 |
| Title | `page.locator('input[placeholder*="catchy"]')` | 开源实现 nessed | “Add a catchy title” |
| Description | `page.locator('.public-DraftEditor-content')` | 开源实现 nessed + 官方前端代码 | Draft.js；与视频 caption 同一编辑器 |
| Description 容器 | `page.locator('.caption-textarea')` | 官方前端代码 | 稳定语义类名 |
| Add sound | `page.get_by_role("button", name="Add sound")` 或 `page.locator('button:has-text("Add sound")')` | 开源实现 alexsax | 必须真实 click，不要 force 文本点击 |
| 声音搜索框 | `page.locator('[role="dialog"] input').first` | 开源实现 alexsax | 不要用页面全局第一个 text input |
| 声音 “Use” | `page.locator('[role="dialog"] button:has-text("Use")')` | 开源实现 alexsax | 普通 click 可能 timeout；建议 JS 点击可见项 |
| 已挂音乐 | `page.get_by_text("Replace")` | 开源实现 nessed | 作为 guard |
| 可见性 | `page.get_by_text("Who can see this post")` 所在区块 | 官方前端代码 | 具体选项文案随语言变化 |
| Schedule | `page.locator('button:has-text("Schedule")').last` | 开源实现 nessed | 需要账号有 `schedule_enable` |
| 日期/时间 | `.tiktok-timepicker-option-text.tiktok-timepicker-left` / `...-right` | 开源实现 nessed | 先打开时间下拉 |
| Post 按钮 | `page.locator('button:has-text("Post")').last` | 开源实现 alexsax | 现有视频代码用 `div.button-group button`，图片页待复核 |
| Post now 弹窗 | `page.locator('button:has-text("Post now")')` | 开源实现 alexsax | 图片帖一般不出，视频常见 |
| 成功标志 | `page.wait_for_url("**/tiktokstudio/content**")` | 开源实现 alexsax + 本仓库视频代码 | 图片与视频一致 |
| 图片卡片 | `page.locator('[class*="photoItem-"]')` | 官方前端代码 | 用于计数/拖拽；hash 会变 |
| 封面角标 | `page.get_by_text("Cover", exact=True)` | 官方前端代码 | 第一张才有 |
| 上传入口（视频） | `button:has-text("Select video")` | 本仓库现有代码 | 图片模式对应 “Select photos” |

**未能确认、不要编造的选择器：**
- 图片页 “Save draft” 按钮的精确 selector/文案；
- 图片页 “Select photos” 按钮的精确 DOM（bundle 有文案，但开源实现直接操作 file input）；
- 封面设置的独立按钮（不存在，只有拖拽）；
- 定时发布的日期日历内部结构（只有时间轮的 selector 有开源证据）。

---

## 限制与风险

1. **放量/账号资格风险（最高）**：图片帖 web 入口 2026-07 才上线，按账号/地区灰度。目标 Profile 可能完全没有 `Photos` tab。实现必须先探测，探测失败要明确报“该账号未开放图片帖”，而不是继续走视频 input。
2. **默认 input 是视频 input**：不先切 tab 就 `set_input_files`，日志会显示成功但页面不进入表单（开源实现已踩坑）。
3. **选择器文本依赖英文 UI**：本仓库要求 Multilogin Profile 为 English (US)；若被改成中文/罗马尼亚语，`Photos` / `Add sound` / `Post` / `Schedule` 全部失效。
4. **类名 hash 不稳定**：`titleInput-*`、`photoItem-*`、`caption-*` 的 hash 会随构建变化；不要硬编码完整类名。
5. **声音选择器遮挡**：`Use` 按钮常被建议层覆盖，普通 click timeout；需要 JS 点击或先关闭建议层。选不到音乐时应 abort，避免“以为加了音乐其实没加”。
6. **自动预览抢焦点**：Feed 预览自动播放会让输入丢失；多图/定时前切到 Profile 预览，或输入后校验。
7. **封面不可独立指定**：业务上如果要求“第 N 张作封面”，只能通过重排文件顺序实现；重排后要复核第一张的 Cover 角标。
8. **网页限制与 API 限制不同**：网页允许 PNG/50MB；API 只允许 JPEG/WebP/20MB/1080p。不要把 API 文档的限制硬编码到网页路径，也不要把网页限制当成 API 承诺。
9. **定时资格与可编辑性**：`schedule_enable` 由账号决定；定时帖通常不可再编辑，只能删除重发（TikTok 帮助中心口径）。图片帖发布后的编辑能力存在路由，但部分状态显示 “Photo posts cannot be edited.”，需真人复核。
10. **草稿数量上限**：每账号草稿数有限；批量失败重试可能把草稿槽位打满。
11. **风控**：网页自动化发图片帖仍是浏览器行为；高频批量、重复文案、相同封面会触发限流/审核。仓库现有 15 分钟发布超时与登录失效映射仍然适用。
12. **图片帖与视频的“成功判定”不同**：图片帖通常没有 “Post now” 弹窗；若照搬视频代码等待该弹窗，会误判超时。应以 `/tiktokstudio/content` + 内容列表复核为准。

---

## 可行性结论

**条件可行（Conditionally feasible）。**

- **技术路径已成立**：网页端确实有 Photos 模式、独立 URL、35 张多图、标题/正文分离、TikTok 曲库、第一张即封面、拖拽排序、定时、草稿。官方前端 bundle 与两个 2026 年生产验证的开源实现互相印证。
- **可以落地的范围**：
  - 单图/多图本地上传（顺序即展示顺序，第一张即封面）；
  - Title ≤90、Description ≤4000、hashtags（≤50）；
  - 手动选曲（搜索/收藏/推荐）+ 校验 `Replace`；
  - 可见性、AI 标签（共享插件）；
  - 定时（仅当账号有 `schedule_enable`）；
  - 草稿（机制存在，按钮待复核）。
- **不能直接承诺的范围**：
  - 所有账号都有 Photos tab；
  - “自动配乐”；
  - 独立选择第 N 张作封面（只能重排）；
  - 图片帖发布后一定可编辑；
  - 商品链接/合集/声明等视频专属字段。

### 还缺哪些证据才能从“条件可行”升级为“确定可行”

1. **真人登录目标 Multilogin Profile**，确认 `Photos` tab 是否出现、文案是否 exact “Photos”。
2. 在图片页实际 `set_input_files` 2–3 张，确认：input accept、顺序、Cover 角标、35 张上限提示。
3. 确认 Title 是否必填、90 截断行为；Description 4000 截断行为；空标题能否 Post。
4. 确认 “Add sound” 是否可选、搜索/收藏/推荐的实际 modal DOM，以及 `Use` 的稳定点击方式。
5. 确认 `Schedule` 是否对该账号出现，并成功排期 1 条；在 `/tiktokstudio/content` 复核。
6. 确认草稿入口（手动 Save draft）与草稿恢复流程。
7. 确认图片帖发布后是否可编辑，以及 “Photo posts cannot be edited.” 的触发条件。
8. 用目标账号跑一次完整的“图片帖发布 → 内容列表复核 → 删除/清理”，记录实际耗时与失败点。

---

## Sources

### 官方文档 / 官方内容
- TikTok Creator Academy — *Unleash Your Creativity: Tell Stories with Photos on TikTok*（2026-07-03；35 张、4000 字符、封面/描述/话题/音乐/草稿）
  https://www.tiktok.com/creator-academy/en/article/photo-posting
- TikTok Creator Academy 中文版
  https://www.tiktok.com/creator-academy/zh-Hans/article/photo-posting
- TikTok for Developers — *Photo Post*（title 90、description 4000、35 张、cover index、auto_add_music）
  https://developers.tiktok.com/doc/content-posting-api-reference-photo-post
- TikTok for Developers — *Media Transfer Guide / Image restrictions*（WebP/JPEG、20 MB、1080p）
  https://developers.tiktok.com/doc/content-posting-api-media-transfer-guide
- TikTok Support — *Editing TikTok videos and photos*（单次编辑最多 35 个 item）
  https://support.tiktok.com/en/using-tiktok/creating-videos/editing-tiktok-videos-and-photos

### 官方前端代码（公开静态 bundle，2026-11-05 抓取）
- 上传页入口/路由：
  https://www.tiktok.com/tiktokstudio/upload
- UploadPage chunk：
  https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/async/UploadPage.0f2b8582.js
- 图片页核心（标题、35/50/格式、封面=第一张、草稿、音乐、调度插件）：
  https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/6240.60d62a9e.js
- 常量（accept/50MB/35/90）：
  https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/4066.a7ec448b.js
- i18n 文案（Photos/Videos、Select photos、Add sound、Cover、4000 等）：
  https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/9602.bceb34cf.js
- 路由常量（`/tiktokstudio/upload/post/photo`）：
  https://lf16-tiktok-web.tiktokcdn-us.com/obj/tiktok-web-tx/ies/creator_center/static/js/12.ce49fd88.js

### 开源实现
- alexsax777/tiktok-publish-flow —— 图片帖 + TikTok 音乐，Playwright，声明 2026-09-24 生产成功
  https://github.com/alexsax777/tiktok-publish-flow
  https://raw.githubusercontent.com/alexsax777/tiktok-publish-flow/main/scripts/tiktok_photo_music.py
  https://raw.githubusercontent.com/alexsax777/tiktok-publish-flow/main/SKILL.md
- nessed/tiktok-musician-promo-automation —— 多图 + 标题 + 话题 chip + 音乐 + 定时，2026-10 测试
  https://github.com/nessed/tiktok-musician-promo-automation
  https://raw.githubusercontent.com/nessed/tiktok-musician-promo-automation/main/docs/POSTING.md
  https://raw.githubusercontent.com/nessed/tiktok-musician-promo-automation/main/browser/studio-snippets.js
- wkaisertexas/tiktok-uploader —— 仅视频，可确认“传统开源上传器尚未覆盖图片帖”
  https://github.com/wkaisertexas/tiktok-uploader
- 本仓库上游 social-auto-upload —— TikTok 仅有 `upload-video`，无 `upload-photo/note`
  `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/sau_commands/tiktok.py`

### 行业资料（用于时间线/交叉验证，非官方）
- SocialBee — *November 2026 TikTok updates*：2026-07 “photo posts on desktop (web)”
  https://socialbee.com/blog/tiktok-updates-news-features/
- HeyMark — *Schedule TikTok on desktop*（仍写网页只支持视频，已过时；其 Help Center 引用可用于定时资格）
  https://heymark.ai/en/solutions/schedule-tiktok-on-desktop/
- Postraid — *Can you post a slideshow on TikTok from a PC?*（旧结论，已过时；其 API 限制梳理可参考）
  https://www.postraid.com/blog/post-tiktok-slideshow-from-pc

---

## 需要真人登录后复核的点

1. 目标 Multilogin Profile 是否出现 `Photos` tab；`?tab=photo` 是否直接进入图片表单。
2. 图片页 file input 的实际 `accept` 值和 `multiple` 属性；默认（视频）input 是否仍是 `video/*`。
3. `Select photos` 按钮与 file input 的对应关系；拖拽上传是否也可用。
4. Title 是否必填、空标题是否能 Post；90 字符截断是硬截断还是 toast。
5. Description 的 4000 字符上限是否对所有账号一致；hashtag/mention 50 上限是否仍生效。
6. “Add sound” 是否为可选；modal 的搜索框、收藏 tab、推荐列表、`Use` 按钮的真实 DOM 与可点击性。
7. 封面是否只能靠第一张；拖拽重排后 Cover 角标是否立即跟随。
8. `Schedule` 是否对该账号显示；日期/时间控件的真实结构；排期后是否出现在 `/tiktokstudio/content`。
9. 草稿：是否有手动 “Save draft” 按钮；草稿数量上限；从草稿恢复后图片顺序/封面/音乐是否保留。
10. 发布后能否编辑（`/upload/post/photo?item_id=`）；“Photo posts cannot be edited.” 的触发条件。
11. 图片帖是否支持商品链接/合集/商业内容声明/AI 标签；这些字段在图片页是否真的渲染。
12. 图片帖成功后的内容列表项 URL/ID 形态（`item_id` vs `video_id`），以及现有 `get_last_video_id()` 是否需要改为图片 ID 解析。
