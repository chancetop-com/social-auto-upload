# 02 — Instagram API with Instagram Login（Standalone）内容发布能力清单与 Business 差异

- 检索日期：2026-11-10
- 文档版本：Graph API `v27.0`（文档页标注 "The latest version is: v27.0"）
- 检索方式：`webfetch` 直取 developers.facebook.com（`/documentation/instagram-platform/**`，含 `.md` 纯文本变体）；本环境 `websearch` 全程返回空结果，故所有结论均来自一手文档页面，未使用二手博客。
- 置信度标记：
  - `官方文档` — 有明确原文 + URL
  - `开源实现实测` — 本轮未执行任何 API 调用或开源实现验证，**本文不使用该标记**
  - `仅推断` — 由参数定义、权限族、账号拓扑推出，官方无直接声明
- 重要背景：Meta 现已有**三套** setup。2026 年新增 **Instagram API with Unified Login**（无 Page、`graph.facebook.com`、`instagram_*` 权限），文档明确"**New Instagram API features are released only for this setup**"，且"Newly created apps can't set up the Instagram API with Instagram Login"。因此 Standalone 处于**维护态**，不是能力增长的方向。

来源页（均于 2026-11-10 访问）：
1. `https://developers.facebook.com/docs/instagram-platform`（Overview）
2. `https://developers.facebook.com/docs/instagram-platform/content-publishing`
3. `https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login`
4. `https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/business-login`
5. `https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media`
6. `https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/media_publish`
7. `https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-container`
8. `https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/ig-user/content_publishing_limit`
9. `https://developers.facebook.com/docs/instagram-platform/instagram-graph-api/reference/error-codes`
10. `https://developers.facebook.com/docs/instagram-platform/reference/instagram-media`
11. `https://developers.facebook.com/docs/instagram-platform/content-publishing/caption-add-ons`
12. `https://developers.facebook.com/docs/instagram-platform/content-publishing/audio-api`
13. `https://developers.facebook.com/docs/instagram-platform/instagram-api-with-facebook-login/product-tagging`
14. `https://developers.facebook.com/docs/instagram-platform/app-review`
15. `https://developers.facebook.com/docs/instagram-platform/changelog`
16. `https://developers.facebook.com/docs/instagram-platform/instagram-api-with-instagram-login/migration-guide`

---

## 0. TL;DR

1. **内容发布能力上，Standalone 是 Business 的严格子集**（扣掉 Story 的账号类型差异后）。没有一项"仅 Standalone 可发布"的内容能力。
2. Standalone 的真正优势是**账号拓扑**：不需要 Facebook Page、不受 PPA / Page 2FA / Page Task 约束、OAuth 只有 Instagram 一跳、token 只有一种。
3. 被砍掉的都是**依赖 Page / 商业资产**的元数据：`location_id`（Page 地点）、`product_tags`（Instagram Shop + 目录 + Business Manager 管理员）、`collaborators`（协作者）、partnership ads label、caption add-ons（投票 / 评论提示）、Audio API（曲库配乐）。
4. **两套都没有原生定时发布**。Content Publishing API 无 `scheduled_publish_time` 类参数；官方只在你"自己排期、到点调用"的语境下提到 scheduling。
5. 容器 24h 过期、媒体必须公网可 cURL、发布上限官方文档自相矛盾（50 vs 100），这三条对浏览器实现有直接对照价值。

---

## 1. 媒体类型与硬限制

| 媒体类型 | 上限 / 规格 | Business | Standalone | 置信度 |
|---|---|---|---|---|
| 单图 | JPEG **唯一**格式（MPO/JPS 等扩展 JPEG 不支持）；≤8 MB；宽高比 4:5–1.91:1；宽 ≥320（不足会放大）、≤1440（超出会缩小）；sRGB（其他色彩空间会被转换） | ✅ | ✅ | 官方文档（`ig-user/media` Image Specifications） |
| 轮播 | 2–20 个图片/视频混排；**Reels 不能进轮播**；所有子项按**首图**裁切（默认 1:1）；子项各自建容器（`is_carousel_item=true`），再建 `media_type=CAROUSEL` + `children`；`caption`/`location_id` 只能放父容器 | ✅ | ✅ | 官方文档（content-publishing#create-a-carousel-container / `ig-user/media`） |
| Reels | MOV/MP4（无 edit list、moov atom 前置）；H.264/HEVC、progressive、closed GOP、4:2:0；AAC ≤48 kHz、1–2 声道；23–60 fps；水平像素 ≤1920；宽高比 0.01:1–10:1（建议 9:16）；VBR ≤25 Mbps；**时长 3 s–15 min**；≤300 MB | ✅ | ✅ | 官方文档（`ig-user/media` Reel Specifications） |
| Feed video | **已不是独立类型**：自 2023-11-09 起 `media_type=VIDEO` 不再用于单条视频，改用 `REELS` + `share_to_feed=true`；`VIDEO` 仍用于轮播里的视频子项 | ✅ | ✅ | 官方文档（changelog 2022-06-28 注记；content-publishing Resumable 段仍用 `VIDEO` 建轮播子项） |
| Stories（图） | JPEG；≤8 MB；建议 9:16；sRGB；**24 h 后过期** | ✅（**仅 Business 账号**） | ✅（账号类型限制未在 Standalone 文档中找到） | 官方文档（Story Image Specifications + `instagram-api-with-facebook-login` Limitations："Stories, which are only available to business accounts"） |
| Stories（视频） | MOV/MP4；**时长 3–60 s**；≤100 MB；宽高比 0.1:1–10:1；≤1920 px；≤25 Mbps | 同上 | 同上 | 官方文档（Story Video Specifications） |
| Stories 限制 | 不支持贴纸（link / poll / location）；不支持 product tags；不支持 collaborators；支持 `user_tags`（2025-07-09 起，x/y 可选） | ✅ | ✅ | 官方文档（Story Limitations + `ig-user/media` 顶部 Success 注记） |
| Trial Reels | `media_type=REELS` + `trial_params.graduation_strategy` = `MANUAL` \| `SS_PERFORMANCE`；仅推给非粉丝 | ✅ | ✅ | 官方文档（changelog 2025-12-03："in Facebook Login and Instagram Login"） |
| Live | 只读（`/live_media`），不可发布 | — | — | 官方文档（content-publishing 未列发布入口） |

补充：官方 Limitations 明确 **"Shopping tags are not supported. Filters are not supported."**（content-publishing#limitations）。注意这与下文 product tagging 并存 —— 该限制指"发布时的 shopping 标签不在通用发布路径内"，product tagging 是独立 guide（且只在 Business / Unified 可用）。

---

## 2. 配文与发布元数据

`caption`：≤2200 字符、≤30 个 hashtag、≤20 个 @mention；**不支持写在轮播子项上**（只能写父容器）。URL 只是纯文本，API 不生成可点击链接。置信度：官方文档（`ig-user/media` Query String Parameters）。

| 能力 | 参数 / 端点 | Business | Standalone | 依据与原因 |
|---|---|---|---|---|
| alt text | `alt_text`，≤1000 字符 | ✅ 仅**图片**（单图或轮播中的图片）；Reels/Stories 不支持 | ✅ 同 | 官方文档（`ig-user/media`；2025-03-24 上线，未标注变体限制） |
| 地点 | `location_id`（**Page** 的地点 ID） | ✅ | ❌ | 参数定义为"a Page associated with a location"，发现路径是 Pages Search API；Standalone 无 Page、权限族无 `pages_*` → **仅推断**（官方未给 Standalone 明确否定句） |
| 协作者 | `collaborators`，≤3 个 username；Feed 图 / Reels / 轮播；Stories 不支持 | ✅ | ❌ | 官方文档（Overview#Collaborators："_Facebook Login for Business only._"；IG Media `collaborators` edge 亦标 "Available for Instagram API with Facebook Login only"）。**注意冲突**：`ig-user/media` 参数表未标变体限制 |
| 用户标签 | `user_tags` = `[{username, x, y}]`；图片 x/y 必填、Stories 可选；总 @ 上限 20 | ✅ | ✅ | 官方文档（`ig-user/media`；2025-07-09 Stories 支持）。**注意冲突**：Instagram Login 首页写 "cannot access ads or tagging"（该句疑指 product/shopping tagging，措辞含糊） |
| 商品标签 | `product_tags`（`product_id` + 图片需 x/y） | ✅ | ❌ | 官方文档（Overview 能力矩阵：Product tagging = Unified ✅ / Instagram Login ❌ / Facebook Login ✅；且需 Instagram Shop + 目录 + Business Manager 管理员角色） |
| 数量口径 | 参数表写"最多 5 个"；product-tagging guide 写 Feed 20 / Reels 30 / 轮播 20（每片 ≤5） | — | — | 官方文档，**两处不一致**，实现前需实测 |
| AI 生成标识 | `is_ai_generated=true`；轮播只设在父容器（设在子项会报错） | ✅ | ✅ | 官方文档（content-publishing#ai-content："available to both"；changelog 2026-06-22） |
| 关闭评论 | **不是发布参数**。发布后 `POST /<IG_MEDIA_ID>?comment_enabled=false`；读取用 `is_comment_enabled` | ✅ | ✅ | 官方文档（IG Media#Updating 三列 Requirements 均含 Instagram Login） |
| 分享到 Feed | `share_to_feed`，**仅 Reels** | ✅ | ✅ | 官方文档（`ig-user/media`） |
| 封面 | `cover_url`（公网 JPEG ≤8 MB，9:16 建议）或 `thumb_offset`（毫秒）；两者同时给时 `cover_url` 生效、`thumb_offset` 被忽略 | ✅ | ✅ | 官方文档（`ig-user/media`） |
| 音频重命名 | `audio_name`，仅 Reels，**只能改名一次** | ✅ | ✅ | 官方文档（`ig-user/media`） |
| 曲库配乐 | `audio_configuration` + `GET /ig_audio`（Audio API） | ✅ | ❌ | 官方文档（audio-api#Limitations："It is not supported on the Instagram API with Instagram Login"；且需 Page） |
| 合作广告标 | `branded_content_sponsor_ids`（≤2）/ `is_paid_partnership` | ✅ | ❌ | 官方文档（content-publishing#partnership-ads-label："Available for Instagram API with Facebook Login only"；2026-04-22 上线） |
| 投票 / 评论提示 | `poll_attachment`、`is_poll_duration_extended`、`is_comment_prompt_used` | ✅ | ❌ | 官方文档（caption-add-ons："available only for Instagram API with Facebook Login"） |

---

## 3. 定时发布

- **两套变体都没有原生定时发布参数。** `POST /<IG_ID>/media` 与 `media_publish` 的参数表里不存在 `scheduled_publish_time` / `publish_at` 一类字段 —— 官方文档中**未找到**任何服务端排期入口。置信度：官方文档（负向证据：参数表穷举 + 全站无该参数）
- 官方唯一涉及排期的表述是建议你自己限流："We recommend that your app also enforce the publishing rate limit, especially if your app allows app users to schedule posts to be published in the future."（content-publishing#rate-limit）→ 即**应用侧定时**，到点再走 create + publish。置信度：官方文档
- 由此产生的硬约束：容器 **24 h 过期**（`EXPIRED`）。所以"提前建容器、到点 publish"最多只能提前 24 h；更长提前量必须到点才建容器。置信度：官方文档（`ig-container` status_code 定义）
- 时区语义：API 无排期字段，故无时区语义；发布时刻即 `media_publish` 调用时刻，`timestamp` 字段为 UTC ISO 8601。置信度：官方文档

---

## 4. 账号 / 权限 / 审核前提

| 项 | Business（Facebook Login） | Standalone（Instagram Login） | 置信度 |
|---|---|---|---|
| 账号类型 | Instagram 专业账号（Business 或 Creator）；个人号不可用 | 同（`account_type` 返回 `Business` \| `Media_Creator`） | 官方文档 |
| Facebook Page | **必需**，且 app user 需能在该 Page 上执行 `MANAGE` 或 `CREATE_CONTENT` | **不需要**（"does not require a Facebook Page to be linked"） | 官方文档 |
| Business portfolio | 取决于 Facebook Login for Business 配置 | 不需要（登录流不要求；Unified 才强制） | 官方文档（Overview 矩阵） |
| 登录流 | Facebook Login for Business，authorization code 1 h → short-lived 1 h → long-lived 60 d | Business Login for Instagram（`instagram.com/oauth/authorize`），code 1 h → short-lived 1 h → long-lived 60 d，可刷新（≥24 h 龄、<60 d） | 官方文档（business-login） |
| 权限 | `instagram_basic`、`instagram_content_publish`、`pages_read_engagement`；若通过 Business Manager 授权还需 `ads_management` / `ads_read` 之一 | `instagram_business_basic`、`instagram_business_content_publish` | 官方文档（content-publishing Requirements 表） |
| Token | Facebook User 或 Page access token | Instagram User access token | 官方文档 |
| Host | `graph.facebook.com`（+ `rupload.facebook.com`） | `graph.instagram.com` | 官方文档 |
| App Review | 仅当服务"你不拥有/不管理"的账号（Advanced Access）才需要；自有账号 Standard Access 即可 | 同 | 官方文档（app-review 场景表） |
| Business Verification | Advanced Access 时必需 | 同 | 官方文档（Overview#business-verification） |
| 额外闸门 | **PPA（Page Publishing Authorization）**、Page 要求 2FA 时 Facebook 用户也必须完成 2FA | 无 | 官方文档（content-publishing / `media_publish` Limitations） |
| 审核特殊性 | 可申请 `instagram_shopping_tag_products`、`catalog_management`、branded content 系列 | 只能申请 4 个 `instagram_business_*` + Human Agent | 官方文档（app-review#available-permissions） |

> 关键点：**App Review 不是"发布能力"的门槛，而是"服务他人账号"的门槛**。自有账号用 Standard Access 即可发布 —— 这与浏览器方案"只服务自己的号"的定位同构。

---

## 5. 发布流程约束

1. `POST /<IG_ID>/media` → 返回 container id。媒体由 Meta **在创建容器时 cURL 抓取**，必须公网可访问（"must be hosted on a publicly accessible server at the time of the attempt"）。置信度：官方文档
2. 视频异步：拿到 container id ≠ 上传成功。轮询 `GET /<IG_CONTAINER_ID>?fields=status_code`，取值 `IN_PROGRESS` / `FINISHED` / `ERROR` / `EXPIRED` / `PUBLISHED`；官方建议"**once per minute, for no more than 5 minutes**"。置信度：官方文档（content-publishing#container-publishing-status）
3. `POST /<IG_ID>/media_publish?creation_id=<container>` → 返回 media id。
4. **部分成功语义（容易漏）**：publish 响应可能同时带
   - `config_issue`：`CAPTION_NOT_ATTACHED`（发出去了但没带配文）/ `USER_TAGGING_FAILURE`（发出去了但没带上标签）
   - `caption_add_on_attachment_status`：`POLL_CREATION_FAILURE` / `PROMPT_CREATION_FAILURE`
   官方原文："Both fields report a partial success. The publish itself succeeded and the media ID is valid, so treat them as a signal to reconcile rather than as an error." 置信度：官方文档（`ig-user/media_publish` Response Fields）
5. 速率限制（**官方文档内部冲突，必须标注**）：
   - content-publishing#rate-limit：**100** API-published posts / 24 h 滚动窗口；轮播计 1 条；在 `media_publish` 上强制
   - `media_publish` Limitations：**50** posts / 24 h
   - `content_publishing_limit`：`config.quota_total` "currently **50**"，`quota_duration` 86400
   - 容器：**400** containers / 24 h 滚动窗口（`ig-user/media` General Limitations）
   - product tagging：**25** tagged media / 24 h（Business 专属）
   → 建议实现按 **50** 保守取值，并注明"100"来自 guide 页。
6. 错误语义（`error-codes`，均带 `code` + `error_subcode` + `is_transient`）：
   - `2207003` 下载媒体超时 → 可重试
   - `2207004` 图片 >8 MiB；`2207009` 宽高比越界；`2207010` caption 超长
   - `2207026` 视频格式不支持；`2207057` `thumb_offset` 超出视频时长
   - `2207027` 媒体未就绪（应轮询到 `FINISHED` 再 publish）
   - `2207028` 轮播数量不合法（**错误文案仍写"2–10"，与 20 的实际上限不一致**）
   - `2207042` 触发日发布上限
   - `2207050` 账号被限制/checkpoint；`2207051` 判定为 spam（风控）
   - `2207052` 媒体 URL 抓不到；`2207008` creation id 不存在或已过期
   - `2207020` 媒体已过期
7. `upload_type=resumable`：content-publishing 写"**Only for apps that have implemented Facebook Login for Business**"，但 llms.txt 索引里存在 Instagram Login 专属的 "Upload Media" 页（本次抓取该页返回空/追踪像素，**未取得正文**）→ 记为**冲突 + 未确认**，不要据此假设 Standalone 支持可恢复上传。

---

## 6. 差异表（capability | Business | Standalone | 原因）

| 能力 | Business（FB Login） | Standalone（IG Login） | 原因 |
|---|---|---|---|
| 单图发布 | ✅ | ✅ | 共用 Content Publishing |
| 轮播（2–20） | ✅ | ✅ | 共用 |
| Reels（≤15 min / ≤300 MB） | ✅ | ✅ | 共用 |
| Feed video | ✅（= REELS + share_to_feed） | ✅（同） | `VIDEO` 类型已废弃 |
| Stories | ✅（仅 Business 账号） | ✅（账号类型限制未在文档中声明） | Business 侧有明确账号类型限制 |
| Trial Reels | ✅ | ✅ | 2025-12-03 起两套均支持 |
| caption（2200 / 30 / 20） | ✅ | ✅ | 共用 |
| alt_text（≤1000，仅图片） | ✅ | ✅ | 2025-03-24 起，无变体限制 |
| user_tags（≤20 @） | ✅ | ✅ | 2025-07-09 起支持 Stories |
| is_ai_generated | ✅ | ✅ | 2026-06-22 起两套均支持 |
| share_to_feed | ✅ | ✅ | Reels 参数 |
| cover_url / thumb_offset | ✅ | ✅ | 共用 |
| audio_name（重命名） | ✅ | ✅ | 共用 |
| comment_enabled（发布后关评论） | ✅ | ✅ | IG Media#Updating 三列均支持 |
| **location_id** | ✅ | ❌ | 参数是 **Page 地点 ID**；Standalone 无 Page、无 `pages_*`（仅推断） |
| **collaborators（≤3）** | ✅ | ❌ | Overview 明标 Facebook Login only；`collaborators` edge 同 |
| **product_tags** | ✅ | ❌ | 需 Instagram Shop + 目录 + Business Manager 管理员 |
| **Audio API（曲库配乐）** | ✅ | ❌ | audio-api 明标 not supported on IG Login；且需 Page |
| **partnership ads label** | ✅ | ❌ | 明标 Facebook Login only |
| **caption add-ons（投票/评论提示）** | ✅ | ❌ | 明标 Facebook Login only |
| **resumable upload** | ✅ | ⚠️ 未确认 | guide 写仅 FB Login；另有 IG Login 上传页但未取到正文 |
| **PPA / Page 2FA 闸门** | 有 | 无 | 无 Page 即无此闸门 |
| **API 删除媒体** | ✅ | ❌ | IG Media#Deleting 仅 Facebook Login（另需 `instagram_manage_contents`） |
| **原生定时发布** | ❌ | ❌ | 两套都无排期参数 |
| 容器 24 h / 400 个 | ✅ | ✅ | 共用 |
| 发布上限 | 50（或 100，文档冲突） | 同 | 共用 `content_publishing_limit` |

---

## 7. 四个显式回答

### 7.1 两者都支持

单图、轮播、Reels、feed video（作为 Reels）、Stories（Business 侧限 Business 账号）、Trial Reels；caption 全量规则；`alt_text`（图片）；`user_tags`；`is_ai_generated`；`share_to_feed`；`cover_url` / `thumb_offset`；`audio_name`；发布后 `comment_enabled`；容器状态轮询；`content_publishing_limit` 查询；部分成功语义（`config_issue`）。

### 7.2 仅 Business 支持，及原因

| 能力 | 原因（结构性，不是策略性） |
|---|---|
| `location_id` | 地点在 Meta 的模型里就是 **Facebook Page**。Standalone 没有 Page，也就没有地点实体可引用 |
| `collaborators` | 协作者读取走 `IG Media → collaborators` edge，官方标 FB Login only；协作者涉及跨账号授权，Meta 把它挂在 Page/商业关系上 |
| `product_tags` | 需要 Instagram Shop → 商品目录 → Business Manager 管理员角色，这条链完全在 Facebook 商业资产侧 |
| Audio API 配乐 | 曲库授权按"商业账号 + Page"签约；且 `ig_audio` 用 `graph.facebook.com` |
| partnership ads label | 合作广告是 Ads 体系的一部分；Instagram Login 首页直接写 "cannot access ads" |
| caption add-ons | 新互动形态只在 FB Login / Unified 放量 |
| 删除媒体 | 依赖 Page 侧权限模型（`instagram_manage_contents` + Page 访问） |
| PPA / Page 2FA | 反过来是"Business 多出来的闸门"，不是能力 |

### 7.3 仅 Standalone 支持

**内容发布能力上：没有。** 逐项比对后，Standalone 没有任何 Business 缺失的发布能力。

它的优势全在**运行前提**，而这些恰恰是浏览器方案最关心的：
- 不需要 Facebook Page → 不需要 Page 管理员角色、不需要 PPA、不受 Page 2FA 牵连
- 不需要 Business portfolio（登录流层面）
- OAuth 只有 Instagram 一跳，token 只有 Instagram User access token 一种
- 权限面只有 4 个 `instagram_business_*`，App Review 材料最薄

代价是：**它不会再长出新能力**（"New Instagram API features are released only for [Unified Login]"），且**新 App 已经无法再接入**（"Newly created apps can't set up the Instagram API with Instagram Login"）。

### 7.4 账号拓扑如何改变能力集

```
Page-linked 专业号 ──► Facebook Login ──► 拿到 Page token + pages_* 权限
                                        └─► 解锁：location / collaborators / product tags /
                                            partnership ads / Audio API / 删除媒体
                                        └─► 承担：PPA、Page 2FA、Page Task(MANAGE|CREATE_CONTENT)

独立专业号 ─────────► Instagram Login ──► 只有 Instagram User token
                                        └─► 发布能力 = 上述集合的补集（纯内容 + 用户标签 + AI 标 + alt text）
                                        └─► 零 Page 闸门
```

一句话：**Page 不是"多一个登录步骤"，它是 Meta 内容图谱里的一个实体**。凡是需要引用"地点 / 商品 / 品牌 / 协作者授权 / 曲库"的元数据，都必须锚定到 Page 或商业资产；独立专业号没有这个锚点，所以这些参数不是"没实现"，而是"无处指向"。

注意 Unified Login 打破了这个二分：它无 Page 却支持 product tagging / partnership ads（靠 business portfolio + `instagram_*` 权限）。也就是说，**"无 Page"不再等于"能力子集"**，只是 Standalone 这一套仍停留在旧模型里。

---

## 8. 对浏览器实现（参照用）的含义

> 本节只做映射提示，不实现、不设计参数契约（那是 03/04/05 的职责）。

1. **网页端能做到的比 Standalone API 多。** instagram.com 的发布器对独立专业号也提供地点、协作者、商品标签等入口。所以"对齐 Standalone"会**主动放弃**网页已有的能力；对齐 Business 更接近网页真实上限。这个取舍必须由用户拍板（map.md 的 Not yet specified 已列出）。
2. **定时发布在两端都不存在参照实现。** API 侧是"应用自己排期 + 24 h 容器寿命"，网页端无入口 → 若引入 `--not-before`，它属于**超出官方参照系**的自研语义，需要单独定义失败/时区/幂等。
3. **"部分成功"必须建模。** API 明确允许"发出去了但配文没带上 / 标签没带上"。现有 `published / processing / submission_unknown` 三态里没有"成功但降级"，这是参照集暴露的真实语义缺口。
4. **限流要按 50/24h 保守实现。** 文档自相矛盾（50 vs 100），网页端还有额外风控（`2207051` spam、`2207050` 账号受限），二者叠加时不要以 100 为预算。
5. **元数据字段的"容器 vs 子项"规则要照抄。** caption / location / product_tags / is_ai_generated 只能设在轮播父容器；user_tags 设在子项。网页端也是逐张打标签，但 AI 标识是整帖级 —— 这条对齐关系值得在 04 里逐项核对。

---

## 9. 未确认 / 冲突清单（不要当成事实用）

| # | 项 | 状态 |
|---|---|---|
| 1 | 发布上限 50 vs 100 | 官方两处冲突；`content_publishing_limit` 返回 `quota_total: 50` |
| 2 | `product_tags` 单帖上限 5 vs 20/30 | 参数表与 product-tagging guide 冲突 |
| 3 | 轮播上限 20，但错误文案写 2–10 | 文档陈旧 |
| 4 | Standalone 是否支持 Stories 给 Creator 账号 | 未找到 Standalone 侧的账号类型限制声明 |
| 5 | Standalone 的 `location_id` | 官方无明确否定句，按 Page 依赖推断为不支持 |
| 6 | Standalone 的 `collaborators` | Overview 明标 only，但参数表未标 → 冲突 |
| 7 | `upload_type=resumable` 在 Standalone | guide 写仅 FB Login；IG Login 上传页正文未取到 |
| 8 | Instagram Login 首页 "cannot access ads or tagging" 的 "tagging" 指什么 | 措辞含糊；疑指 product/shopping tagging |
| 9 | Unified Login 的正式发布日期 | 未在 changelog 中找到单独条目 |
| 10 | 本文全部结论 | 均为文档阅读，**零实测**；落地前建议用自有 Standalone 账号跑一次最小用例（单图 / 轮播 / Reel / Story 各一条） |
