# 02 — Instagram API with Instagram Login（Standalone）内容发布能力清单与差异

Status: resolved
Type: research
Blocked by: 无

## Question

梳理 Instagram API with Instagram Login（Standalone，专业账号不依赖 Facebook Page）的 Content Publishing 能力，并与 01 的 Business 变体逐项 diff。至少回答：

- 两者都支持的能力。
- 仅 Business 支持的能力及原因。
- 仅 Standalone 支持的能力及原因。
- 账号拓扑（链接 Page vs 独立专业号）对能力的影响。
- 权限、App 审核、媒体 URL、速率限制的差异。

每项标注官方文档出处与置信度。产出写入 `research/02-standalone-api-capabilities.md`，并在本文件 `## Answer` 下给出摘要与差异表。

## Answer

结论：**内容发布能力上 Standalone 是 Business 的严格子集**，没有任何"仅 Standalone 可发布"的能力；它的优势全在账号拓扑（无 Page → 无 PPA、无 Page 2FA、无 Page Task、OAuth 一跳）。详见 `research/02-standalone-api-capabilities.md`（检索 2026-11-10，v27.0）。

- 两者都支持：单图 / 轮播 2–20 / Reels（≤15 min、≤300 MB）/ feed video（= REELS + `share_to_feed`）/ Stories / Trial Reels；caption 2200+30+20；`alt_text`（仅图片）；`user_tags`；`is_ai_generated`；`cover_url` / `thumb_offset`；`audio_name`；发布后 `comment_enabled`。
- 仅 Business：`location_id`（Page 地点实体）、`collaborators`（≤3）、`product_tags`（Shop+目录+BM 管理员）、Audio API 配乐、partnership ads label、caption add-ons（投票/评论提示）、删除媒体。原因统一：**这些元数据必须锚定 Page 或 Facebook 商业资产**。
- 仅 Standalone：无。只有运行前提优势。
- 定时发布：**两套都没有** `scheduled_publish_time`；官方只建议应用侧排期，容器 24 h 过期 → 提前量上限 24 h。
- 硬约束：媒体必须公网可 cURL；容器 400/24 h；发布上限文档冲突（guide 100 vs `media_publish` / `content_publishing_limit` 50），按 50 保守取值。
- 必须建模的语义：`config_issue`（`CAPTION_NOT_ATTACHED` / `USER_TAGGING_FAILURE`）= **发布成功但降级**，现有三态无此位。
- 战略事实：2026 年新增 Unified Login（无 Page 但支持 product tagging / partnership ads / Audio），"New features ship only on Unified Login"，且新 App 已无法接入 Instagram Login → Standalone 处于维护态。
- 对浏览器实现的取舍提示：网页端对独立专业号也提供地点/协作者/商品标签，**对齐 Standalone 会主动放弃网页已有能力**；基线选择仍需用户拍板。
- 未确认项 10 条已单列（含 50 vs 100、product_tags 5 vs 20/30、Standalone 的 location/collaborators、resumable upload）。全部结论为文档阅读，**零实测**。

