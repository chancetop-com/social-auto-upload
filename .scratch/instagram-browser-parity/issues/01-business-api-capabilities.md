# 01 — Instagram API with Facebook Login（Business）内容发布能力清单

Status: resolved
Type: research
Blocked by: 无

## Question

梳理 Instagram API with Facebook Login（原 Instagram Graph API，Business/Creator 账号经 Facebook Page 授权）的 Content Publishing 能力，作为浏览器对齐的参照基线。至少覆盖：

- 支持的媒体类型与限制：单图、轮播、Reels、feed video、Stories；数量、格式、大小、时长、宽高比。
- 配文与文本：长度上限、hashtags、mentions、链接。
- 发布元数据：alt text、location、collaborators、user tags、product tags、AI-generated 标识、comments disabled、share to feed、cover/thumb offset、audio。
- 定时发布：是否支持、时间范围、时区语义。
- 账号与权限前提：专业账号类型、Page 绑定、所需权限、App 审核。
- 发布流程约束：容器创建/轮询、媒体 URL 要求、速率限制、错误语义。

每项标注官方文档出处与置信度（官方文档 / 开源实现实测 / 仅推断）。产出写入 `research/01-business-api-capabilities.md`，并在本文件 `## Answer` 下给出摘要与关键链接。

## Answer

完整清单见 [`research/01-business-api-capabilities.md`](../research/01-business-api-capabilities.md)（含逐行置信度与出处）。要点：

- **媒体类型**：单图 / 轮播 / Reels / Stories 四种；`media_type=VIDEO`（独立 feed video）自 2023-11-09 停用，视频发 feed 只能用 `REELS` + `share_to_feed=true`。
- **硬限制**：图片**仅 JPEG**、≤8 MB、宽高比 4:5–1.91:1、宽 320–1440；Reels 3 s–15 min、≤300 MB、≤1920px、0.01:1–10:1；Story 视频 3–60 s、≤100 MB。轮播 2–20 项，Reels 不可入轮播，所有图片按首图裁切（默认 1:1）。
- **配文**：≤2200 字符、≤30 hashtag、≤20 @ 提及；轮播子项不支持配文。配文内链接是否可点击**未在官方文档中找到**。
- **元数据**：alt_text（仅图片，≤1000 字符）；location_id（Page ID）；collaborators ≤3（不支持 Stories）；user_tags（图/视频/Stories）；product_tags（需 Shop）；`is_ai_generated`（2026-06-22 新增）；`share_to_feed`；`cover_url`/`thumb_offset`；`audio_name`/`audio_configuration`；付费合作标签（≤2 赞助方）；caption add-ons 投票/评论提示（2026 新增，Facebook Login 专属）。
- **评论关闭不是发布参数**：只能发布后 `POST /{ig_media_id}?comment_enabled=false`。
- **定时发布：不支持**。无 `scheduled_publish_time`，`media_publish` 同步立即发布，容器 24 h 过期；官方明确建议由 app 自行调度并限流。时区语义不适用（读取侧 `timestamp` 为 UTC）。
- **账号前提**：IG 专业账号 + 绑定 Facebook Page + Page 的 `MANAGE`/`CREATE_CONTENT` 任务；权限 `instagram_basic` + `instagram_content_publish` + `pages_read_engagement`（Business Manager 场景加 `ads_management`/`ads_read`）；Advanced Access 需 App Review + Business Verification；Page 若要求 PPA 或 2FA 未完成则发布失败。**Stories 仅 Business 账号**。
- **流程**：建容器 → （视频 resumable 上传）→ 轮询 `status_code=FINISHED`（建议每分钟 1 次、≤5 分钟）→ `media_publish`。媒体**必须公网可访问**（ASCII URL）；仅 resumable 视频支持本地文件。
- **配额**：50 帖/24h、400 容器/24h、25 个带商品标签帖/24h；调用配额 `4800 × 曝光数`。
- **错误语义**：`config_issue`（`CAPTION_NOT_ATTACHED` / `USER_TAGGING_FAILURE`）与 `caption_add_on_attachment_status` 表示**发布成功但元数据丢失**，须按部分成功处理。
- **文档自相矛盾 3 处**（发布配额 50 vs 100、轮播 20 vs 10、商品标签 5 vs 20/30），已在研究文件 §7 列明采信建议。
- **时效风险**：2025-03 至 2026-07 密集新增能力；Facebook Login 变体已被官方定位为「存量 Page 绑定集成」，新集成推荐 Unified Login。

关键链接：[Content Publishing](https://developers.facebook.com/documentation/instagram-platform/content-publishing) · [IG User Media](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media) · [media_publish](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/ig-user/media_publish) · [Error Codes](https://developers.facebook.com/documentation/instagram-platform/instagram-graph-api/reference/error-codes) · [Changelog](https://developers.facebook.com/documentation/instagram-platform/changelog)
