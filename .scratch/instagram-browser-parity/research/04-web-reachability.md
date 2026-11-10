# 04 — 网页端可达性：每项 API 能力在 instagram.com 是否有入口

- 调研日期：2026-11-10
- 输入：`research/01-business-api-capabilities.md`、`research/02-standalone-api-capabilities.md`、`research/03-current-browser-inventory.md`、`uploader/meta_uploader/insgraph_uploader/main.py`、`docs/CLI.md`（Instagram 节）、`skills/instagram-upload/SKILL.md`
- 方法：**桌面研究 + 代码/文档证据分析**。本轮**没有**可用的已登录账号，**未做任何真实账号点击验证**；文中所有「网页端有入口」均指「有证据表明该入口存在于 instagram.com 的发布界面」，不等于「已在本项目账号上跑通」。
- 本轮额外取到的一手材料：`https://www.instagram.com/` 未登录首页及其公开前端 bundle（2026-11-10 抓取，`static.cdninstagram.com/rsrc.php/v4iAAE4/y0/l/en_US/Fnujficf1P_JDznoiqK_93R6RMnoaIkO0SQBq2K1buRFAhpL0pIQmjk3zle5GgdR-fdmaSKx-ETyE02CjJmzGIDy_jPOCdwWCtYokLbGzA3Ud6.js`，下称 **bundle**）。bundle 里的 i18n 字符串与发布流程 reducer 动作名，是「网页端有该控件/该状态」的强证据，但**不是**该控件在当前账号可见的证明（Instagram 用实验门控，见 §1）。
- 未取得：Instagram Help Center（`help.instagram.com` 在本环境返回 400，无法抓取正文）；因此网页端结论**不引用** help 页面，也不假装有官方网页端文档背书。

## 0. 证据分级说明

ticket 要求四档：`官方文档` / `现有代码实测` / `社区实测` / `仅推断`。本文按此四档标注，另加一档仅用于「公开前端代码」：

| 标记 | 含义 | 强度 |
| --- | --- | --- |
| `官方文档` | Meta 开发者文档明确写出（附 URL）。**只用于 API 侧**，网页端无同类文档可引 | 最强（对 API 侧） |
| `现有代码实测` | 本仓库代码/注释，或 `docs/CLI.md`、`SKILL.md` 记录的**真实账号页面观察**（这两个文档在 2026-11-10 仍随代码更新，见 `git log db329d5`） | 强（对网页端） |
| `官方前端 bundle` | 本轮抓取的 instagram.com 公开前端代码中的 i18n 字符串 / reducer 动作名。证明「该能力在网页端代码里存在」，不证明「当前账号看得到」 | 中强 |
| `社区实测` | 公开社区/第三方实测。**本轮 `websearch` 全程空结果、搜索引擎 RSS 被降级为泛化结果，未能取得可引用 URL**，故本文不使用该档 | — |
| `仅推断` | 由相邻事实、代码缺失或产品常识推导，无直接证据 | 最弱 |

> 凡标 `仅推断` 的行，§5 都给出「必须在真实账号上测什么」。

## 1. 两个必须先说清的前提

### 1.1 网页 composer 是实验门控的，入口会因账号/rollout 不同

bundle 中存在明确的实验开关：

- `PolarisHasFeedCreationV2Dogfooding` / `PolarisHasFeedCreationHEIC`（HEIC 支持由该门控决定，见 `PolarisMediaHelpers`）；
- `PolarisBulkUploadStrings` 这类模块说明存在「批量上传 + 排期」这一整套新界面。

**含义**：本矩阵的「有入口未接入」= 网页端**存在**该入口，但可能在当前账号不可见、或位置与观察时不同。任何自动化实现都必须把「入口找不到」当成一种正常分支，而不是断言平台没有该能力。`docs/CLI.md:634` 自己也写了这个保留：「这不代表所有 Instagram 账号和客户端都没有定时能力」。

### 1.2 现有实现只走过三段式主流程

`main.py` 已实测的 DOM 结构（`现有代码实测`）：

| 阶段 | 证据 | 说明 |
| --- | --- | --- |
| 创建入口 | `main.py:343-357` | 导航第 2 个弹出入口（`a._a6hd[href="#"]` 且含 `[aria-selected]`），断言恰好 4 个 |
| 选素材 | `main.py:32,358-363` | `input[type="file"][accept*="video/mp4"]`；注释：「创建弹窗实际 accept 同时含照片与 MP4」 |
| 裁剪 | `main.py:371-373` | `._ac76` 标题栏 + 主动作 `[role=button]:not(:has(svg))` |
| 编辑 | `main.py:382-412` | 视频封面独立入口 `input[type=file][accept="image/jpeg,image/png"]`；预览 blob SHA-256 校验 |
| 配文 | `main.py:429-444` | `[contenteditable=true][role=textbox][data-lexical-editor=true]`（Lexical 编辑器） |
| 分享 | `main.py:445-473` | 同一主动作；监听 `POST /api/v1/media/configure`，202→`processing` |
| 结果 | `main.py:504-511` | 校验 `media.user.pk` 与 `media.caption.text` 完全相等；`kind` 取 `reel`（视频）或 `p`（图片） |

**注意**：代码只点「主动作」两次推进裁剪→编辑，**从未打开过任何「高级设置」面板**。所以 03 里「高级设置未接入」是**没点开过**，不是「点开过发现没有」。

## 2. 主矩阵

`Business API` = Instagram API with Facebook Login；`Standalone API` = Instagram API with Instagram Login。API 侧取值以 01/02 为准。

| 能力 | Business API | Standalone API | 网页端可达性 | 入口/阶段 | 原因或前提 | 证据等级 |
| --- | --- | --- | --- | --- | --- | --- |
| 1 单图 | ✅ | ✅ | **已覆盖** | 创建弹窗 → 选素材 → 裁剪 → 编辑 → 配文 → 分享 | `upload-note --images 1.jpg`；`docs/CLI.md:632` 记录「单张照片已实测」 | 现有代码实测 |
| 2 轮播（2–20） | ✅ | ✅ | **已覆盖**（机制） | 同上；`set_input_files` 按 `--images` 顺序多选 | 多图顺序已实现，但**只实测过 2 张**；3/10/20/21 张与「逐张裁剪」未测 | 现有代码实测 |
| 3 Reels | ✅ | ✅ | **已覆盖** | 选视频 → 关闭 Reels 介绍弹窗 → 裁剪 → 编辑（封面）→ 配文 → 分享 | `main.py:364-369`；`kind='reel'`（`main.py:508`） | 现有代码实测 |
| 4 Feed video（REELS+share_to_feed） | ⚠️ 独立类型已废弃 | ⚠️ 同 | **未知/需实测** | 视频只能进 Reels 流程（`main.py:508` 无 feed video 分支） | 网页端未观察到「feed video」独立类型；Reels 配文页是否有「同时分享到 Feed」开关未确认 | 仅推断（+现有代码实测：无分支） |
| 5 Stories（图/视频） | ✅ 仅 Business 账号 | ✅（未声明限制） | **有入口未接入** | 创建弹窗的格式选择（Post/Story/Reel）→ Story 画布（文字/贴纸/画笔）→ 分享 | bundle 有完整 `STORY_CREATION_*` 状态机（含 `VIDEO_UPLOAD_REQUESTED`、`SAVE_STORY`、`ADD_STICKER`）；入口位置需实测 | 官方前端 bundle |
| 6 Trial Reels | ✅ | ✅ | **未知/需实测** | Reels 配文页/高级设置中的 Trial 开关（若存在） | bundle 首屏只有 `exclude_active_trial_reels`（查询侧），**没有**创建侧 trial 动作 | 仅推断 |
| 7a 配文 ≤2200 | ✅ | ✅ | **已覆盖** | 配文页 Lexical 编辑器 | `main.py:294-295` 构造时校验；`main.py:442-444` 断言编辑器文本一致 | 现有代码实测 |
| 7b 30 hashtag / 20 @ | ✅ | ✅ | **未知/需实测** | 配文页（无客户端计数器） | 网页端限额由服务端判定；未观察到字符/计数提示 | 仅推断 |
| 8 alt_text（仅图片） | ✅ | ✅ | **有入口未接入** | 照片编辑页或「更多设置」中的「替代文字」 | `docs/CLI.md:634` 明确「照片提供替代文字」；bundle 有 `CREATION_CUSTOM_ACCESSIBILITY_CAPTION_UPDATED` | 现有代码实测 + 官方前端 bundle |
| 9 location_id | ✅ | ❌ | **有入口未接入** | 配文页「添加地点」→ 搜索地点 | `docs/CLI.md:634`「地点」；bundle `CREATION_GEO_TAG_ADDED/REMOVED`、`CREATION_SUGGESTED_GEO_TAGS_LOADED` | 现有代码实测 + 官方前端 bundle |
| 10 collaborators（≤3） | ✅ | ❌ | **有入口未接入** | 配文页「标记用户/邀请协作者」→ 搜索账号 | `docs/CLI.md:634`「协作者」；bundle 首屏无创建侧 collab 动作（弱负面证据） | 现有代码实测 |
| 11 user_tags | ✅ | ✅ | **有入口未接入** | 照片编辑/配文页「标记用户」→ 图上点坐标 | bundle `CREATION_USERTAGS_UPDATED`；坐标点击需实测 | 官方前端 bundle |
| 12 product_tags | ✅ 条件 | ❌ | **未知/需实测** | 配文页「标记商品」（仅 Shop 账号） | `docs/CLI.md:634` 的观察清单**不含**商品标签（该账号可能无 Shop）；bundle 首屏无创建侧 product_tag 动作 | 仅推断 |
| 13 is_ai_generated | ✅ | ✅ | **有入口未接入** | 高级设置/「更多设置」中的 AI 标识 | `docs/CLI.md:634`「AI 标签」；bundle `CREATION_SET_GEN_AI_SELF_DISCLOSURE`（Story 侧也有同名动作） | 现有代码实测 + 官方前端 bundle |
| 14 关闭评论 | ✅ 仅发布后 | ✅ 仅发布后 | **有入口未接入** | 高级设置「关闭评论」（**发布前**） | `docs/CLI.md:634`「关闭评论」；bundle `CREATION_TOGGLE_COMMENTS` + `DISABLE_POST_COMMENTS/ENABLE_POST_COMMENTS` + 文案 `Comments off`。网页端可一步完成，API 需发布后二次调用 | 现有代码实测 + 官方前端 bundle |
| 15 share_to_feed | ✅ | ✅ | **未知/需实测** | Reels 配文页/高级设置 | 同 #4；bundle 首屏只有 FB 交叉发布（`CREATION_TOGGLE_SHARE_TO_FACEBOOK_FEED`），无 IG feed 开关 | 仅推断 |
| 16 cover_url | ✅ | ✅ | **已覆盖** | 视频编辑页「封面」→ 从电脑上传 | `main.py:384-412`（`--thumbnail`，字节级校验）；bundle `CREATION_VIDEO_COVER_PHOTO_UPDATED`、`COVER_UPLOAD` | 现有代码实测 |
| 17 thumb_offset（选帧） | ✅ | ✅ | **有入口未接入** | 视频编辑页「封面」→ 从视频选帧 | 网页端是帧选择器（非毫秒），语义与 `thumb_offset` 不完全等价 | 官方前端 bundle |
| 18a audio_configuration（配乐） | ✅ | ❌ | **有入口未接入** | 视频编辑页「声音/音频」→ 曲库搜索 | `docs/CLI.md:634`「视频提供…声音」；曲库范围与是否含音量混合需实测 | 现有代码实测 |
| 18b audio_name（重命名原声） | ✅ | ✅ | **未知/需实测** | Reels 音频设置（若存在） | bundle 首屏无创建侧 audio_name 动作 | 仅推断 |
| 19 partnership ads label | ✅ | ❌ | **未知/需实测** | 高级设置「品牌内容/付费合作」 | `docs/CLI.md:634` 观察清单不含；需已授权品牌账号 | 仅推断 |
| 20 caption add-ons（poll/评论提示） | ✅ 仅 Business | ❌ | **未知/需实测**（倾向无入口） | 配文页（若存在） | bundle 中的 poll 字符串集中在 Story 投票与媒体字段，未见创建侧 add-on 动作 | 仅推断 |
| 21 定时发布 | ❌ | ❌ | **有入口未接入** | **不在主 composer**：专业账号后台的「Scheduled content」/「Bulk upload」（批量上传后设排期） | bundle `PolarisBulkUploadStrings`：`Schedule all content`、`Choose dates and times`、`Specific date range`、`Only 45 items can be uploaded for scheduling`；导航字符串含 `Scheduled content`。同时 `docs/CLI.md:634` 实测主 composer 及高级设置**无**定时入口。两条并存 → 定时在网页端存在，但在**另一个界面**，且受账号资格/灰度限制 | 官方前端 bundle + 现有代码实测 |
| 22a 图片格式 | JPEG only | JPEG only | **已覆盖（更宽）** | 选素材 | bundle `PolarisMediaHelpers`：`image/avif`、`image/jpeg`、`image/png` + `heic/heif`（受 `PolarisHasFeedCreationHEIC` 灰度）；代码白名单 `main.py:524` 与之一致。**HEIC/HEIF 是有条件的** | 官方前端 bundle + 现有代码实测 |
| 22b 大小/时长/宽高比 | 8MB / 300MB / 4:5–1.91:1 等 | 同 | **未知/需实测** | 平台侧校验（代码无前置校验） | 网页端阈值未测；代码只查后缀与存在性（`main.py:514-526`） | 仅推断 |
| 23 账号拓扑（Business/Standalone/Unified） | 需 Page | 无需 Page | **已覆盖（拓扑无关）** | 登录态即身份 | 网页端只认 cookie `ds_user_id`（`main.py:169-179,186-198`），没有 Page 概念；专业功能（地点/协作者/商品/排期）按账号类型门槛而非 Page 绑定 | 现有代码实测 + 仅推断 |
| 24 配额/限流 | 50 帖/24h（另有 100 说法） | 同 | **未知/需实测** | 无可见配额 UI | bundle 有 `This feature exceeds your upload limit` / `Checking your feature upload limit…`（批量排期上限 45），但没有日发帖配额文案 | 仅推断 |
| 25 部分成功（config_issue） | ✅ 有结构化回执 | ✅ | **无入口**（无等价回执） | — | 网页端无 `config_issue` 字段；只能比对 `POST /api/v1/media/configure` 响应（现有代码已比对配文，`main.py:266-267`）或发布后回读页面 | 官方文档（API 侧）+ 现有代码实测 |

## 2.2 网页独有 / 超出 API 的能力（无 API 对照项）

| 网页能力 | 网页端可达性 | 入口 | API 侧 | 证据等级 |
| --- | --- | --- | --- | --- |
| 滤镜 | 有入口未接入 | 照片裁剪/编辑页 | ❌「Filters are not supported」 | 现有代码实测（`docs/CLI.md:634`「滤镜」）+ bundle `CREATION_SET_FILTER_NAME` |
| 隐藏点赞/播放数 | 有入口未接入 | 高级设置 | ❌ 无参数 | 现有代码实测 + bundle `CREATION_TOGGLE_LIKE_VIEW_COUNTS` |
| Story 贴纸/文字/画笔 | 有入口未接入 | Story 画布 | ❌「Publishing stickers … is not supported」 | 官方前端 bundle（`STORY_CREATION_ADD_STICKER/CHANGE_TEXT/DRAW_LINE`） |
| 轮播逐张裁剪 | 有入口未接入 | 裁剪页（多图逐张） | ❌ 全部按首图裁切 | 仅推断（bundle 有 `CREATION_PHOTO_CROP_CHANGED`，但未证明逐张） |
| 批量上传（≤45） | 有入口未接入 | 专业后台 Bulk upload | ❌ 无批量概念 | 官方前端 bundle |
| FB 交叉发布 | 有入口未接入 | 配文页/高级设置 | ❌ 无参数 | 官方前端 bundle（`CREATION_TOGGLE_SHARE_TO_FACEBOOK_FEED`、`STORY_CREATION_TOGGLE_SHARE_TO_FACEBOOK_STORY`） |
| 本地文件直传 | 已覆盖 | 选素材 | 图片必须公网 URL | 现有代码实测 |
| 发布前关评论 | 有入口未接入 | 高级设置 | ❌ 只能发布后改 | 现有代码实测 + 官方前端 bundle |

## 3. 浏览器优于 API 的地方

1. **图片格式更宽**：网页接受 PNG/AVIF，HEIC/HEIF 在灰度中；API 只吃 JPEG（`官方前端 bundle` + `官方文档`）。现有代码白名单已经是网页口径，不必回退到 JPEG-only。
2. **配乐曲库更全**：网页是完整曲库且可试听；API 只返回「已授权第三方使用」的子集且不支持预览（`官方文档` Audio API；`docs/CLI.md:634` 观察到「声音」入口）。**细节需实测**。
3. **Stories 不限 Business 账号**：API 的 Stories 仅 Business 账号可用；网页端任何账号都能发 Story（`官方前端 bundle` + `仅推断`：需 Creator/个人号实测）。
4. **独立专业号也能用地点/协作者**：API 里这两项锚定 Facebook Page，Standalone 不可用；网页端没有 Page 概念（`现有代码实测` 身份模型 + `docs/CLI.md:634` 观察）。
5. **关评论可一步完成**：API 必须发布后再 `comment_enabled=false`，存在窗口期；网页端在发布前设置（`官方前端 bundle`）。
6. **有 API 完全没有的发布选项**：隐藏点赞数、滤镜、Story 贴纸、FB 交叉发布、批量上传（`官方前端 bundle`）。
7. **定时发布在网页端存在**：API 两套都没有原生排期；网页专业后台有 `Scheduled content`/批量排期（`官方前端 bundle`，入口需实测）。这是对 map.md「网页端同样没有定时入口」的**修正**。
8. **无公网媒体 URL、无 Page/PPA/2FA 闸门、无 24h 容器寿命**：浏览器只需本地文件与登录态（`现有代码实测`）。

## 4. 疑似 API-only / 网页端很可能没有的能力

| 能力 | 判断 | 依据 | 需要测什么 |
| --- | --- | --- | --- |
| Trial Reels | 可能 API-only 或仅 App | bundle 无创建侧动作；Reels 高级设置未见 | Reels 配文页/高级设置是否有 Trial 开关；账号是否满足资格 |
| caption add-ons（poll/评论提示） | 很可能 API-only | 2026 新能力，文档标 Facebook Login 专属；bundle 无创建侧动作 | 配文页是否有「投票/评论提示」入口 |
| partnership ads label | 不确定（可能网页有） | 品牌内容属商业工具，网页端通常有入口 | 高级设置是否有「品牌内容/付费合作」+ 赞助方选择 |
| product_tags | 不确定（资格问题，不是入口问题） | 需 Instagram Shop + 已审核目录 + BM 管理员 | Shop 账号下配文页是否有「标记商品」 |
| `thumb_offset`（毫秒级） | 语义上 API-only | 网页只有选帧 | 选帧能否稳定映射到目标毫秒 |
| `audio_configuration` 音量混合 | 部分 API-only | 网页音量控制范围未知 | 网页是否能分别设原声/配乐音量 |
| `config_issue` 结构化降级回执 | API-only | 网页无等价字段 | 只能自建「发布后回读对账」 |
| `content_publishing_limit` 查询 | API-only | 网页无配额查询 | 只能靠实测撞限流 |
| 容器状态机 / 24h 过期 / 400 容器 | API-only 概念 | 网页无容器抽象 | 不适用 |

## 5. 必须在真实账号上复核的清单

按「影响实现决策的程度」排序。每条都写明**具体动作**与**判定标准**。

| # | 待测项 | 具体动作 | 判定标准 |
| --- | --- | --- | --- |
| 1 | 创建弹窗是否有格式选择（Post/Story/Reel） | 打开创建弹窗，看左上角是否有可展开的格式下拉 | 有 → Stories 可实现；无 → Stories 需另找入口（如 `/create/story/`） |
| 2 | Stories 图/视频 | 用同一账号发 1 张图 Story + 1 条 ≤60s 视频 Story | 成功且能拿到 `configure` 响应中的 media id/code |
| 3 | 地点 | 配文页「添加地点」搜一个地点并发布 | 发布后作品页显示地点；记录 DOM 与请求字段 |
| 4 | 协作者 | 邀请 1 个账号（≤3） | 对方收到邀请；作品显示共同作者；记录是否需要对方接受 |
| 5 | alt text | 照片编辑/更多设置里填写替代文字 | 发布后能读回 alt 文本；确认单图 vs 轮播逐张 |
| 6 | 关闭评论 | 高级设置关闭评论后发布 | 发布后立即生效（不需要二次操作） |
| 7 | 用户标签 | 图上点坐标标记 1 个账号 | 作品显示标签且坐标正确；Stories 是否支持 |
| 8 | AI 标识 | 打开 AI 标识后发布 | 作品显示 AI 标签；轮播是整帖级还是逐张 |
| 9 | 隐藏点赞数 | 打开后发布 | 作品隐藏点赞数 |
| 10 | 配乐/原声 | 视频编辑页选一首曲库音乐；另测重命名原声 | 记录可选曲库、音量控件、`audio_name` 是否有入口 |
| 11 | share_to_feed | Reels 配文页/高级设置找「同时分享到 Feed」 | 有开关 → 可表达；无 → feed video 只能靠默认行为 |
| 12 | Trial Reels | Reels 流程找 Trial 开关 | 有 → 记录入口与毕业后策略选项 |
| 13 | 定时（专业后台） | 专业账号后台找 `Scheduled content` / Bulk upload | 记录入口路径、单帖能否排期、时区、45 条上限、账号资格 |
| 14 | 商品标签/品牌内容 | Shop/品牌账号下找对应入口 | 有 → 记录资格门槛与控件 |
| 15 | 轮播上限 | 依次试 3、10、20、21 张 | 记录首次被拒的张数与报错文案 |
| 16 | 媒体阈值 | PNG/AVIF/HEIC 各 1 张；>8MB 图；9:16 与 1.91:1 图；>15min 或 >300MB 视频 | 记录接受/拒绝与提示文案 |
| 17 | 配额 | 连续发布直到被拒（谨慎，用测试号） | 记录日上限与错误文案 |
| 18 | 配文限额 | 2201 字符、31 个 hashtag、21 个 @ | 记录客户端是否拦截、服务端报错形态 |

## 6. 对 05（基线取舍）的直接影响

1. **「网页端没有定时」需要修正**：主 composer 没有，但专业后台的 `Scheduled content`/批量上传有。若用户要定时，路径是「另一个网页界面」，不是 Business Suite 唯一解。
2. **对齐 Standalone 会主动放弃网页已有能力**：地点、协作者在网页端对独立专业号可用（无 Page 概念）。基线若取 Standalone 交集，等于砍掉这些入口。
3. **`config_issue` 没有网页等价物**：任何「发布成功」判定都必须包含「配文/标签是否真的带上」的回读对账，否则会把降级当成功。现有代码只对配文做了严格比对（`main.py:266-267`），标签类没有。
4. **入口存在 ≠ 可自动化**：地点/协作者/商品都是「搜索 + 联想列表」控件，稳定性远低于现有 `set_input_files`。这类能力的成本主要在**选择器与重试语义**，不在参数解析。
5. **实验门控意味着必须有「入口缺失」分支**：同一份代码在不同账号上可能看到不同 composer。规格里要把「入口不存在」定义成显式的 `unsupported`/`skipped` 结果，而不是失败。

## 7. 来源

| # | 来源 | 用途 |
| --- | --- | --- |
| 1 | `research/01-business-api-capabilities.md`（Meta 官方文档 v27.0，2026-11-10） | Business API 列 |
| 2 | `research/02-standalone-api-capabilities.md`（同上） | Standalone API 列 |
| 3 | `research/03-current-browser-inventory.md` | 现有实现盘点 |
| 4 | `uploader/meta_uploader/insgraph_uploader/main.py` | DOM 阶段、封面、配文、结果校验 |
| 5 | `docs/CLI.md:632-634`（2026-11-10 提交 `db329d5`） | 真实账号页面观察：地点/协作者/AI 标签/隐藏点赞/关闭评论/替代文字/滤镜/声音；主 composer 无定时 |
| 6 | `skills/instagram-upload/SKILL.md:26` | 同上（简版） |
| 7 | `https://www.instagram.com/` 公开前端 bundle（2026-11-10 未登录抓取） | `PolarisMediaHelpers`（MIME 白名单）、`CREATION_*`/`STORY_CREATION_*` reducer、`PolarisBulkUploadStrings`（批量+排期）、`PolarisHasFeedCreationHEIC`（灰度门控） |
| 8 | Meta 官方文档 URL（见 01 §10、02 来源页） | API 侧能力与限制 |
