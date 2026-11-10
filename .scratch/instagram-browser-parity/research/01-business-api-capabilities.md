# 01 — Instagram API with Facebook Login（Business）内容发布能力清单

- **调研对象**：Instagram API with Facebook Login（原 Instagram Graph API；IG 专业账号 + Facebook Page 绑定）
- **主源**：`developers.facebook.com/documentation/instagram-platform/*`
- **抓取日期**：2026-11-10
- **文档版本**：示例与路径参数中标注 **v27.0**（"The latest API version is: v27.0"）；Changelog 最新条目 **2026-07-30**
- **置信度标记**
  - `官方文档` — 有官方页面明确写出，附 URL
  - `开源实现实测` — 来自公开开源实现/社区实测观察（本文件仅在官方文档冲突时用于旁证）
  - `仅推断` — 由官方文档的缺失、措辞或相邻事实推导，无直接文档

> 说明：本文件是**能力参照基线**，不涉及任何实现。凡官方文档未写明者一律标注「未在官方文档中找到」，不做数字臆测。

---

## 0. TL;DR（对浏览器对齐最关键的 8 条）

1. **图片只支持 JPEG**，不接受 PNG/WebP；上限 8 MB，宽高比必须落在 4:5–1.91:1。
2. **"feed video" 作为独立类型已不存在**：`media_type=VIDEO` 自 2023-11-09 起不再支持，视频要发到 feed 只能用 `media_type=REELS` + `share_to_feed=true`。
3. **没有原生定时发布**。`media_publish` 是同步立即发布；容器 24 小时过期。文档明确建议「若你的 app 允许用户预约发布，请自行限流」——即调度在客户端。
4. **评论开关不是发布参数**。只能发布后再 `POST /{ig_media_id}?comment_enabled=false`（需 `instagram_manage_comments`）。
5. **alt_text 仅图片**（≤1000 字符），Reels/Stories 不支持；协作者最多 3 人且不支持 Stories。
6. **Stories 仅 Business 账号可用**，Creator 账号不可发 Stories（其余类型 Creator 可用）。
7. **官方文档自身有 3 处数字冲突**（发布配额 50 vs 100、轮播 20 vs 10、商品标签 5 vs 20/30），见 §5。取数时必须以**引用页**为准并留证。
8. **2026 年新增了 3 组能力**：`is_ai_generated`（6/22）、Audio API（6/1）、caption add-ons 投票/评论提示（Facebook Login 专属）。这些在多数第三方文章与旧版 SDK 中缺失。

---

## 1. 支持的媒体类型与硬限制

| 能力 | 支持 | 关键限制 | 置信度 | 来源 |
|---|---|---|---|---|
| 单图（Feed image） | ✅ | JPEG only；≤8 MB；宽高比 4:5–1.91:1；最小宽 320、最大宽 1440（自动缩放）；sRGB | 官方文档 | [IG User Media · Image Specifications](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#image-specifications) |
| 图片格式 PNG / WebP / GIF | ❌ | "JPEG is the only image format supported"；扩展 JPEG（MPO/JPS）亦不支持 | 官方文档 | [Content Publishing · Limitations](https://developers.facebook.com/documentation/instagram-platform/content-publishing#limitations) |
| 轮播（Carousel） | ✅ | 2–20 个图片/视频/混合；Reels 不可入轮播；所有图片按**第一张**裁切，默认 1:1 | 官方文档 | [Content Publishing · Create a carousel container](https://developers.facebook.com/documentation/instagram-platform/content-publishing#create-a-carousel-container)；下限 2 见 [Error 2207028](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes) |
| 轮播子项（image） | ✅ | 同单图规格；需先以 `is_carousel_item=true` 建容器 | 官方文档 | 同上 |
| 轮播子项（video） | ✅ | 走 resumable，`media_type=VIDEO` + `is_carousel_item=true` | 官方文档 | [Resumable Uploads](https://developers.facebook.com/documentation/instagram-platform/content-publishing/resumable-uploads) |
| Reels | ✅ | 见 §1.1 | 官方文档 | [Reel Specifications](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#reels-specs) |
| Feed video（独立类型） | ⚠️ 已废弃 | `media_type=VIDEO` 自 **2023-11-09** 起不再支持；"Use the `REELS` media type to publish a video to your feed" | 官方文档 | [Changelog 2022-06-28](https://developers.facebook.com/documentation/instagram-platform/changelog) |
| Stories（图片） | ✅ 仅 Business | JPEG；≤8 MB；建议 9:16；sRGB | 官方文档 | [Story Image Specifications](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#story-image-specifications) |
| Stories（视频） | ✅ 仅 Business | 3–60 s；≤100 MB；其余见 §1.2 | 官方文档 | [Story Video Specifications](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#story-video-specifications) |
| Stories 轮播 | ❌ | 单次发布仅一个媒体对象 | 官方文档 | 同上（无 carousel 入口） |
| Stories 贴纸（link/poll/location） | ❌ | "Publishing stickers … is not supported"；仅支持无贴纸的 @ 提及 | 官方文档 | [Story Limitations](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#story-limitations) |
| Live / IGTV 发布 | ❌ | 无发布入口（仅读取） | 官方文档 | [IG User Media](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media) |
| Trial Reels | ✅ | `trial_params.graduation_strategy` = `MANUAL` \| `SS_PERFORMANCE`；仅分享给非粉丝 | 官方文档 | [Trial Reels](https://developers.facebook.com/documentation/instagram-platform/content-publishing#trial-reels-posts) |

### 1.1 Reels 硬规格

| 项 | 值 | 置信度 |
|---|---|---|
| 容器 | MOV 或 MP4 (MPEG-4 Part 14)，无 edit lists，moov atom 前置 | 官方文档 |
| 视频编码 | HEVC 或 H264，progressive scan，closed GOP，4:2:0 | 官方文档 |
| 音频编码 | AAC，≤48 kHz，1–2 声道 | 官方文档 |
| 帧率 | 23–60 FPS | 官方文档 |
| 最大横向像素 | 1920 | 官方文档 |
| 宽高比 | 0.01:1 – 10:1（建议 9:16） | 官方文档 |
| 视频码率 | VBR，≤25 Mbps | 官方文档 |
| 音频码率 | 128 kbps | 官方文档 |
| 时长 | **3 秒 – 15 分钟** | 官方文档 |
| 文件大小 | **≤300 MB** | 官方文档 |
| 封面图 | JPEG，≤8 MB，sRGB，建议 9:16；非 9:16 时取中间 9:16 矩形；分享到 feed 时取中间 1:1 | 官方文档 |

来源：[Reel Specifications](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#reels-specs)

### 1.2 Stories 视频硬规格

| 项 | 值 | 置信度 |
|---|---|---|
| 容器/编码 | MOV/MP4，AAC ≤48 kHz，HEVC/H264，progressive，closed GOP，4:2:0 | 官方文档 |
| 帧率 | 23–60 FPS | 官方文档 |
| 最大横向像素 | 1920 | 官方文档 |
| 宽高比 | 0.1:1 – 10:1（建议 9:16） | 官方文档 |
| 码率 | 视频 ≤25 Mbps VBR；音频 128 kbps | 官方文档 |
| 时长 | **3 – 60 秒** | 官方文档 |
| 文件大小 | **≤100 MB** | 官方文档 |

来源：[Story Video Specifications](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#story-video-specifications)

> **Feed video 规格**：当前文档已无独立的 feed video 规格章节。错误码文档仍引用 `#video-specifications` 锚点，但该锚点在 IG User Media 页面已不存在（仅剩 Reels/Story 两节）。→ 结论：**feed video 规格未在官方文档中找到**，唯一路径是 Reels 规格 + `share_to_feed`。

---

## 2. 配文与文本

| 能力 | 支持 | 关键限制 | 置信度 | 来源 |
|---|---|---|---|---|
| 配文长度 | ✅ | **≤2200 字符** | 官方文档 | [IG User Media · caption](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#query-string-parameters)；[Error 36004](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes) |
| Hashtag | ✅ | **≤30 个** | 官方文档 | 同上 |
| @ 提及（mentions） | ✅ | **≤20 个**；被提及用户会在容器发布时收到通知 | 官方文档 | 同上；[Error 2207040](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes) |
| 轮播子项配文 | ❌ | "Not supported on images or videos in carousels"——配文只能挂在轮播容器上 | 官方文档 | 同上 |
| 配文中的可点击链接 | — | **未在官方文档中找到**。文档只说明可含 hashtag 与用户名，未提及 URL 渲染/可点击性 | 仅推断 | — |
| Emoji | — | **未在官方文档中找到**（仅 caption add-on 选项处提到 emoji 计 1 字符） | 仅推断 | [Caption Add-ons](https://developers.facebook.com/documentation/instagram-platform/content-publishing/caption-add-ons) |
| 配文丢失的部分成功 | ⚠️ | 发布成功但配文未附上时返回 `config_issue: CAPTION_NOT_ATTACHED`，media ID 仍有效 | 官方文档 | [IG User Media Publish · Response Fields](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish) |

---

## 3. 发布元数据 / 选项

| 能力 | 支持 | 关键限制与语义 | 置信度 | 来源 |
|---|---|---|---|---|
| **alt text**（替代文字） | ✅ 仅图片 | ≤**1000 字符**；支持单图或轮播中的图片；**Reels 与 Stories 不支持**；2025-03-24 新增 | 官方文档 | [IG User Media · alt_text](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#query-string-parameters)；[Changelog 2025-03-24](https://developers.facebook.com/documentation/instagram-platform/changelog) |
| **location**（地点） | ✅ | 传 `location_id` = 带 location 数据的 **Page ID**；需先 Pages Search API 查；无 location 数据的 Page 会报 `INSTAGRAM_PLATFORM_API__INVALID_LOCATION_ID`；**轮播子项不支持** | 官方文档 | 同上 |
| **collaborators**（协作者） | ✅ | 最多 **3** 个用户名；支持 Feed 图片 / Reels / 轮播；**Stories 不支持**；该能力为 Facebook Login 专属 | 官方文档 | 同上；[Overview · Collaborators](https://developers.facebook.com/documentation/instagram-platform/overview#collaborators) |
| **user tags**（@ 标记 + 坐标） | ✅ | 数组 `{username, x, y}`；x/y ∈ 0.0–1.0；**图片必填坐标，Stories 可选**；2025-07-09 起支持 Stories | 官方文档 | [IG User Media · user_tags](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#query-string-parameters) |
| **product tags**（商品标签） | ✅ 有条件 | 需 Instagram Shop + 已审核目录 + Business Manager admin 角色；**Stories/Live 不支持**；**Creator 账号不支持**；坐标仅图片必填；仅 `review_status=approved` 的商品会显示 | 官方文档 | [Product Tagging](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging) |
| product tags 数量 | ⚠️ 冲突 | 媒体参考页写「max 5」；Product Tagging 指南写「feed 20 / Reels 30 / 轮播总计 20、每页 5」 | 官方文档（自相矛盾） | 见 §5 |
| **AI-generated 标识** | ✅ | `is_ai_generated=true`；轮播**只能设在容器上**，设在子项会报错；2026-06-22 新增 | 官方文档 | [AI Content](https://developers.facebook.com/documentation/instagram-platform/content-publishing#ai-content)；[Changelog 2026-06-22](https://developers.facebook.com/documentation/instagram-platform/changelog) |
| **comments disabled**（发布时关闭评论） | ❌ 非发布参数 | **无容器级参数**。只能发布后 `POST /{ig_media_id}?comment_enabled=false`，需 `instagram_manage_comments` | 官方文档 | [IG Media · Updating](https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media#updating) |
| **share to feed**（Reels） | ✅ | `share_to_feed=true/false`；文档明确警告：**两个值都不保证**内容真的出现在 Reels tab（取决于算法与资格） | 官方文档 | [IG User Media · share_to_feed](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#query-string-parameters) |
| **cover / thumb offset** | ✅ | `thumb_offset` 毫秒，默认 0；Reels 另有 `cover_url`（JPEG ≤8 MB）；**两者同时给时 `cover_url` 优先，`thumb_offset` 被忽略** | 官方文档 | 同上 |
| **audio（重命名原声）** | ✅ | `audio_name`，仅 Reels，**只能重命名一次** | 官方文档 | 同上 |
| **audio（附加音乐/原声）** | ✅ | `audio_configuration = {audio_id, audio_volume 1–100, video_volume 1–100}`，仅 Reels；需先 `GET /ig_audio` 搜索；**不支持预览**；Instagram Login 变体不支持 | 官方文档 | [Instagram Audio API](https://developers.facebook.com/documentation/instagram-platform/content-publishing/audio-api) |
| 音乐曲库差异 | ⚠️ | "the available selection may vary from what appears in the native app" | 官方文档 | 同上 |
| **partnership ads label** | ✅ Facebook Login 专属 | `branded_content_sponsor_ids`（≤2 个）+ `is_paid_partnership`；赞助方须为专业账号；不支持 close-friends-only / remixed | 官方文档 | [Partnership ads label](https://developers.facebook.com/documentation/instagram-platform/content-publishing#partnership-ads-label) |
| **caption add-ons：poll** | ✅ Facebook Login 专属 | 2–4 个选项，每个 1–25 字符，序列化 ≤200 字符；需非空 caption（caption 即问题）；默认 3 天，`is_poll_duration_extended` 可无限期 | 官方文档 | [Caption Add-ons](https://developers.facebook.com/documentation/instagram-platform/content-publishing/caption-add-ons) |
| **caption add-ons：comment prompt** | ✅ Facebook Login 专属 | `is_comment_prompt_used=true`；需非空 caption；不能与 poll 并用 | 官方文档 | 同上 |
| add-on 适用范围 | ⚠️ | 仅 feed 图片 / 轮播 / Reels；**Stories 不支持**；轮播设在容器上；**发布后不可增删改**（write-once） | 官方文档 | 同上 |
| **filters**（滤镜） | ❌ | "Filters are not supported" | 官方文档 | [Content Publishing · Limitations](https://developers.facebook.com/documentation/instagram-platform/content-publishing#limitations) |
| **shopping tags** | ❌ | "Shopping tags are not supported"（与 product tags 不同，指旧版 shopping 标签） | 官方文档 | 同上 |
| **裁剪/编辑** | ❌ | 无裁剪、无滤镜、无 edit list；图片裁切规则固定（轮播按首图） | 官方文档 | 同上 |

---

## 4. 定时发布

| 项 | 结论 | 置信度 | 依据 |
|---|---|---|---|
| 原生定时发布（provider-side scheduling） | **不支持** | 仅推断（文档缺失 + 官方措辞） | 发布流程只有 `media` → `media_publish`，`media_publish` 同步立即返回 media ID；文档中**不存在** `scheduled_publish_time` / `published=false` 参数 |
| 官方对「预约」的表述 | 由 **app 自行调度** | 官方文档 | "We recommend that your app also enforce the publishing rate limit, **especially if your app allows app users to schedule posts to be published in the future**." —— [Content Publishing · Rate Limit](https://developers.facebook.com/documentation/instagram-platform/content-publishing#rate-limit) |
| 可预约时间窗口 | **不适用** | 仅推断 | 无调度参数，故无窗口语义。注意：容器创建后 **24 小时内**必须发布，否则 `EXPIRED` |
| 时区语义 | **不适用**（发布侧） | 仅推断 | 无调度字段。读取侧 `timestamp` 为 ISO 8601 **UTC**（默认 UTC±00:00） |
| 与 Facebook Page 的差异 | Page feed 支持 `published=false` + `scheduled_publish_time`（10 分钟–30 天） | 官方文档 | [Pages API · Posts](https://developers.facebook.com/documentation/pages-api/posts)（对照项，非 Instagram） |
| 社区实测：给 IG 容器传 `scheduled_publish_time` | 报错或直接立即发布 | 开源实现实测 | Meta 开发者社区帖 [thread 4146093602341676](https://developers.facebook.com/community/threads/4146093602341676)；Stack Overflow 66352362 |

> 对浏览器对齐的含义：网页端同样没有「定时」入口；若要支持定时，只有两条路——(a) 本地队列在目标时刻执行浏览器流程，或 (b) 走 Meta Business Suite（网页端有，但属于另一产品面）。这与 map.md 的 "Not yet specified" 第 2 条一致。

---

## 5. 账号与权限前提

| 前提 | 要求 | 置信度 | 来源 |
|---|---|---|---|
| 账号类型 | Instagram **专业账号**（Business 或 Creator）；个人号不可用 | 官方文档 | [Instagram API with Facebook Login · Limitations](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login) |
| Page 绑定 | **必须**绑定一个 Facebook Page | 官方文档 | [Overview · Facebook Pages](https://developers.facebook.com/documentation/instagram-platform/overview#pages) |
| Page 任务 | 用户须能执行 Page 的 `MANAGE` 或 `CREATE_CONTENT` 任务（UI 名：Content / Full control） | 官方文档 | [IG User Media · Requirements](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#requirements) |
| 必需权限 | `instagram_basic`、`instagram_content_publish`、`pages_read_engagement` | 官方文档 | 同上 |
| 额外权限（Business Manager 授予 Page 角色时） | `ads_management` 或 `ads_read` | 官方文档 | 同上 |
| 商品标签额外权限 | `catalog_management`、`instagram_shopping_tag_products`；申请 App Review 需已验证企业 | 官方文档 | [Product Tagging · Requirements](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging#requirements) |
| 访问级别 | **Standard**（仅 app 角色用户）或 **Advanced**（服务他人账号） | 官方文档 | [Content Publishing · Requirements](https://developers.facebook.com/documentation/instagram-platform/content-publishing#requirements) |
| App Review | Advanced Access 必须通过 App Review | 官方文档 | [Overview · App Review](https://developers.facebook.com/documentation/instagram-platform/overview#app-review) |
| Business Verification | Advanced Access / 无 app 角色用户时必须 | 官方文档 | [Overview · Business verification](https://developers.facebook.com/documentation/instagram-platform/overview#business-verification) |
| Page Publishing Authorization (PPA) | Page 若要求 PPA，未完成则**所有发布失败**；且**无法通过 API 判断** Page 是否要求 PPA | 官方文档 | [Content Publishing · Page Publishing Authorization](https://developers.facebook.com/documentation/instagram-platform/content-publishing#page-publishing-authorization) |
| Page 双重验证 | Page 要求 2FA 时，Facebook 用户也必须完成 2FA，否则失败 | 官方文档 | [IG User Media · General Limitations](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#limitations-general) |
| 账号状态 | 账号 inactive/checkpointed/restricted 时发布失败（error 25 / 2207050） | 官方文档 | [Error Codes](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes) |
| Stories 额外限制 | Stories **仅 Business 账号**；Creator 不可发 Stories | 官方文档 | [Instagram API with Facebook Login · Limitations](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login) |
| Token 类型 | Facebook **User** access token（非 Page token，尽管 Requirements 表在别处提到 Page token） | 官方文档 | [IG User Media · Requirements](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#requirements) |
| Token 生命周期 | 授权码 1 小时；短期 token 1 小时；长期 token **60 天**，可续期 | 官方文档 | [Overview · Authentication](https://developers.facebook.com/documentation/instagram-platform/overview#authentication-and-authorization) |
| Host | `graph.facebook.com`（视频 resumable 走 `rupload.facebook.com`） | 官方文档 | [Overview · Base URLs](https://developers.facebook.com/documentation/instagram-platform/overview#base-urls) |
| 账号拓扑注意 | Facebook Login 变体已被官方标为 **"Existing Page-linked integrations"**，新集成推荐 Unified Login | 官方文档 | [Overview · Which API setup is right](https://developers.facebook.com/documentation/instagram-platform/overview#which-api-is-right-for-my-app) |

---

## 6. 发布流程约束

### 6.1 三步流程

| 步骤 | 调用 | 要点 | 置信度 |
|---|---|---|---|
| 1. 建容器 | `POST /{ig-id}/media` | 返回 `{id}`；视频异步，拿到 ID **不代表**上传成功 | 官方文档 |
| 2. （视频）上传 | `POST rupload.facebook.com/ig-api-upload/{container-id}` | 仅 Facebook Login for Business 可用；`offset`、`file_size`；支持本地文件或公网 URL | 官方文档 |
| 3. 轮询 | `GET /{container-id}?fields=status_code` | `FINISHED` 才可发布；官方建议 **每分钟 1 次、最多 5 分钟** | 官方文档 |
| 4. 发布 | `POST /{ig-id}/media_publish?creation_id=…` | 返回 media ID；可能带 `config_issue` 部分成功 | 官方文档 |

来源：[Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing)；[Resumable Uploads](https://developers.facebook.com/documentation/instagram-platform/content-publishing/resumable-uploads)

### 6.2 容器状态机

`IN_PROGRESS` → `FINISHED` → `PUBLISHED`；异常分支 `ERROR`（`status` 字段回具体 error subcode）、`EXPIRED`（超 24h 未发布）。

来源：[IG Container · status_code](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container#fields)

### 6.3 媒体 URL 要求

| 项 | 结论 | 置信度 |
|---|---|---|
| 公网可访问 | **必须**。Meta 会以 cURL 抓取 `image_url` / `video_url` | 官方文档 |
| URL 字符集 | 强烈建议 IETF 标准 / 纯 US-ASCII，否则请求失败 | 官方文档 |
| 本地文件 | 仅 `upload_type=resumable` 的**视频**支持本地文件直传；图片无此路径 | 官方文档 |
| 抓取失败 | `error 9004 / 2207052`："The media could not be fetched from this uri" | 官方文档 |

来源：[Content Publishing · Media on a public server](https://developers.facebook.com/documentation/instagram-platform/content-publishing#media-on-a-public-server)

### 6.4 速率限制

| 限制 | 值 | 置信度 | 来源 |
|---|---|---|---|
| 发布帖子数 | **50 次 / 24h 滚动窗口**（轮播计 1 次） | 官方文档（权威页） | [IG User Media Publish · Limitations](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish#limitations) |
| 配额查询 | `GET /{ig-id}/content_publishing_limit`，`quota_total=50`，`quota_duration=86400` | 官方文档 | [Content Publishing Limit](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit) |
| 容器创建数 | **400 个 / 24h 滚动窗口** | 官方文档 | [IG User Media · General Limitations](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media#limitations-general) |
| 商品标签帖子数 | **25 个 / 24h**（轮播计 1） | 官方文档 | [Product Tagging · Limitations](https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging#limitations) |
| API 调用配额 | `4800 × 24h 内内容曝光数`（app × user 维度） | 官方文档 | [Overview · Rate Limiting](https://developers.facebook.com/documentation/instagram-platform/overview#rate-limiting) |
| 配额超限错误 | `code 9 / subcode 2207042` | 官方文档 | [Error Codes](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes) |

### 6.5 错误语义（发布相关，节选）

| Code | Subcode | 语义 | 建议处置 | 置信度 |
|---|---|---|---|---|
| -2 | 2207003 | 下载媒体超时 | 重试 | 官方文档 |
| -2 | 2207020 | 媒体已过期 | 重建容器 | 官方文档 |
| 1 | 2207057 | `thumb_offset` 越界 | 修正毫秒值 | 官方文档 |
| 4 | 2207051 | 疑似 spam，被限制活动 | 人工介入 | 官方文档 |
| 9 | 2207042 | 达到每日发布上限 | 次日重试 | 官方文档 |
| 24 | 2207006 | 媒体找不到（权限/过期 token） | 重建容器 | 官方文档 |
| 24 | 2207008 | 容器不存在或已过期 | 30 s–2 min 内重试 1–2 次，再重建 | 官方文档 |
| 25 | 2207050 | 账号被限制 | 让用户回 App 处理 | 官方文档 |
| 100 | 2207028 | 轮播数量非法（文案写 2–10，与 20 冲突） | 见 §7 | 官方文档 |
| 352 | 2207026 | 视频格式不支持 | 转 MOV/MP4 | 官方文档 |
| 9004 | 2207052 | 媒体 URL 抓取失败 | 检查公网可达性 | 官方文档 |
| 9007 | 2207027 | 媒体未就绪 | 轮询到 `FINISHED` | 官方文档 |
| 36000 | 2207004 | 图片超过 8 MiB | 压缩 | 官方文档 |
| 36001 | 2207005 | 图片格式不支持 | 转 JPEG | 官方文档 |
| 36003 | 2207009 | 宽高比非法 | 调整到 4:5–1.91:1 | 官方文档 |
| 36004 | 2207010 | 配文超长 | 截断到 2200 | 官方文档 |

来源：[Instagram Platform error codes](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes)

### 6.6 部分成功语义（重要）

`media_publish` 可以在**发布成功**的同时丢弃部分元数据，返回体仍含有效 media ID：

| 字段 | 值 | 含义 |
|---|---|---|
| `config_issue` | `CAPTION_NOT_ATTACHED` | 配文没附上 |
| `config_issue` | `USER_TAGGING_FAILURE` | @ 标记没附上 |
| `caption_add_on_attachment_status` | `POLL_CREATION_FAILURE` / `PROMPT_CREATION_FAILURE` | 投票/评论提示没挂上 |

官方措辞："treat them as a signal to reconcile rather than as an error."

来源：[IG User Media Publish · Response Fields](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish)

---

## 7. 官方文档内部矛盾清单（取数时必须留证）

| # | 冲突点 | 说法 A | 说法 B | 采信建议 |
|---|---|---|---|---|
| 1 | 24h 发布配额 | Content Publishing 指南 "Rate Limit" 节：**100** | media_publish 参考、content_publishing_limit、轮播限制节：**50** | 取 **50**（3 处一致，且 `quota_total` 实测值为 50）；A 疑似旧版遗留（2021 年博文曾写 25） |
| 2 | 轮播数量 | 正文/参数表：**最多 20** | 错误码 2207028 文案：**2–10** | 取 **2–20**；错误文案为旧版遗留 |
| 3 | 商品标签数量 | IG User Media 参数表：**max 5** | Product Tagging 指南：feed **20**、Reels **30**、轮播总计 20 / 每页 5 | 无定论；按「按媒体类型分档」理解，**建议以 Product Tagging 指南为准并运行时校验** |
| 4 | Token 类型 | Content Publishing 要求表：**Facebook Page access token** | 各端点 Requirements：**Facebook User access token** | 取 **User token**（端点级文档更具体） |
| 5 | Creator 账号能否发布 | 2019-05-22 changelog："Content Publishing API cannot be used by Instagram Creators" | 当前 Overview / Facebook Login 页：所有专业账号可用（Stories 除外） | 取**当前**说法；旧条目为历史状态 |

---

## 8. 2025–2026 变更时间线（可能已变，需复核）

| 日期 | 变更 | 对本项目的影响 |
|---|---|---|
| 2026-07-30 | `media_url` 在含版权音乐/关闭下载时被省略 | 读取侧，不影响发布 |
| 2026-06-22 | 新增 `is_ai_generated`（发布时自披露 AI） | 新增可选参数 |
| 2026-06-01 | 新增 **Instagram Audio API**（`/ig_audio`、`audio_configuration`） | 新增音乐能力 |
| 2026-05-15 | 新增 `branded_content_sponsor_ids` / `is_paid_partnership` | 新增付费合作标签 |
| 2026-04-22 | 新增 reposts/saved/shares 等洞察字段 | 读取侧 |
| 2025-12-03 | Trial Reels 支持（`trial_params`） | 新增 |
| 2025-12-03 | 新增 `DELETE /{ig_media_id}`（`instagram_manage_contents`） | 删除能力（现有实现已有 delete） |
| 2025-07-09 | `user_tags` 支持 Stories | Stories 可 @ 人 |
| 2025-03-24 | 新增 `alt_text`（仅图片） | 新增可选参数 |
| 2023-11-09 | `media_type=VIDEO` 停用，视频统一走 `REELS` | 关键：无独立 feed video |

来源：[Instagram Platform Changelog](https://developers.facebook.com/documentation/instagram-platform/changelog)

---

## 9. 对浏览器实现的能力差距（Top 5）

> 仅列「API 有、网页端可能没有入口」或「API 语义与网页端不同」的项；具体网页可达性由 ticket 04 判定。

1. **定时发布**：API 侧本就无原生调度，网页端同样无入口。要支持只能本地队列 + 到点执行浏览器流程，或改用 Meta Business Suite。这是最大结构性缺口，不是选择器问题。
2. **发布时的评论开关**：API 也是「先发布、再 `comment_enabled=false`」两步。浏览器端若在发布前找不到开关，可对齐为「发布后立即切换」，但会存在短暂窗口期。
3. **商品标签 / 付费合作标签**：需要 Instagram Shop、已审核目录、Business Manager admin、品牌预授权。网页端入口存在但账号资格门槛高，无法在自动化里可靠断言成功。
4. **音乐 / 原声**：网页端是完整曲库，API 只返回「已授权第三方使用」的子集且不支持预览。浏览器端能选到的音乐比 API 更多，属于**浏览器优于 API**的项，不应按 API 子集做限制。
5. **元数据丢失的部分成功**：API 用 `config_issue` 表达「发出去了但配文/@ 没附上」。浏览器端没有等价回执，需要自行在发布后回读页面状态来判定，否则会把「配文丢失」误判为完全成功。

补充两个次级差距：
- **图片格式**：API 只吃 JPEG；网页端接受 JPEG/PNG 等。浏览器实现不必照搬 JPEG-only 限制，但若要「对齐 API」，需明确这是**放宽**而非缺失。
- **Stories 账号类型**：API 仅 Business 可发 Stories；网页端 Creator 也能发。同样是浏览器能力更宽。

---

## 10. 来源清单

| # | 页面 | URL |
|---|---|---|
| 1 | Content Publishing（指南） | https://developers.facebook.com/documentation/instagram-platform/content-publishing |
| 2 | Instagram Platform Overview | https://developers.facebook.com/documentation/instagram-platform/overview |
| 3 | IG User Media（端点参考） | https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media |
| 4 | IG User Media Publish | https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish |
| 5 | IG Container | https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-container |
| 6 | IG User Content Publishing Limit | https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit |
| 7 | IG Media（读写/评论开关/删除） | https://developers.facebook.com/documentation/instagram-platform/reference/instagram-media |
| 8 | Error Codes | https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes |
| 9 | Resumable Uploads | https://developers.facebook.com/documentation/instagram-platform/content-publishing/resumable-uploads |
| 10 | Instagram Audio API | https://developers.facebook.com/documentation/instagram-platform/content-publishing/audio-api |
| 11 | Caption Add-ons | https://developers.facebook.com/documentation/instagram-platform/content-publishing/caption-add-ons |
| 12 | Product Tagging | https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login/product-tagging |
| 13 | Instagram API with Facebook Login（限制） | https://developers.facebook.com/documentation/instagram-platform/instagram-api-with-facebook-login |
| 14 | Changelog | https://developers.facebook.com/documentation/instagram-platform/changelog |
| 15 | Pages API · Posts（调度对照） | https://developers.facebook.com/documentation/pages-api/posts |
| 16 | Meta 开发者社区：IG 调度问询 | https://developers.facebook.com/community/threads/4146093602341676 |
