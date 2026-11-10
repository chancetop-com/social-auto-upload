# 04 — 网页端可达性：每项 API 能力在 instagram.com 是否有入口

Status: resolved
Type: research
Blocked by: 01, 02, 03

## Question

以 01/02 的能力清单为输入，逐项判断 instagram.com 网页 composer 是否能表达该能力：

- 有入口：入口在哪（创建流程的哪个阶段、哪个控件），现有代码是否已覆盖。
- 无入口：原因是什么（API-only、账号类型限制、地区/账号灰度、网页端未提供、需要移动端）。
- 有条件：需要什么前提（专业账号、链接 Page、店铺、创作者账号等）。

对每项给出证据等级（官方文档 / 现有代码与注释实测 / 社区实测 / 仅推断），并明确哪些结论必须在真实账号上复核。

产出写入 `research/04-web-reachability.md`，并在本文件 `## Answer` 下给出矩阵：能力 | Business API | Standalone API | 网页端 | 原因/前提 | 证据等级。

## Answer

桌面研究，无真实账号点击。B = Business API，S = Standalone API。完整矩阵、入口细节与 18 项复核清单见 `research/04-web-reachability.md`。

| 能力 | B | S | 网页端 | 入口/前提 | 证据等级 |
| --- | --- | --- | --- | --- | --- |
| 单图 / 轮播 / Reels / 视频封面 / 配文 2200 | ✅ | ✅ | 已覆盖 | 创建弹窗→裁剪→编辑→配文→分享 | 现有代码实测 |
| Stories（图/视频） | ✅仅B | ✅ | 有入口未接入 | 创建弹窗格式选择→Story 画布 | 官方前端 bundle |
| alt_text | ✅ | ✅ | 有入口未接入 | 照片编辑/更多设置「替代文字」 | 现有代码实测+bundle |
| location | ✅ | ❌ | 有入口未接入 | 配文页「添加地点」 | 现有代码实测+bundle |
| collaborators | ✅ | ❌ | 有入口未接入 | 配文页「邀请协作者」 | 现有代码实测 |
| user_tags / AI 标识 / 关评论 | ✅ | ✅ | 有入口未接入 | 配文页标记 + 高级设置 | 官方前端 bundle+现有代码实测 |
| 配乐（曲库） | ✅ | ❌ | 有入口未接入 | 视频编辑页「声音」 | 现有代码实测 |
| 选帧封面 / 滤镜 / 隐藏点赞 | — | — | 有入口未接入 | 编辑页/高级设置（API 无对应） | 官方前端 bundle+现有代码实测 |
| 定时发布 | ❌ | ❌ | 有入口未接入 | **专业后台** Scheduled content / 批量排期（≤45） | 官方前端 bundle+现有代码实测 |
| feed video / share_to_feed | ⚠️ | ⚠️ | 未知/需实测 | Reels 流程内是否有「分享到 Feed」 | 仅推断 |
| Trial Reels / 商品标签 / 品牌内容 / caption add-ons | ✅ | 部分 | 未知/需实测 | 高级设置/配文页，受账号资格 | 仅推断 |
| 30 hashtag / 20 @ / 媒体阈值 / 配额 | ✅ | ✅ | 未知/需实测 | 服务端判定，无客户端计数器 | 仅推断 |
| config_issue 部分成功 | ✅ | ✅ | 无入口 | 无等价回执，需发布后回读对账 | 官方文档+现有代码实测 |

关键结论：

1. 网页端比 API 宽：PNG/AVIF（HEIC 灰度）、完整曲库、Story 贴纸、滤镜、隐藏点赞、发布前关评论、独立专业号可用地点/协作者、本地文件直传。
2. **定时发布需修正**：主 composer 与高级设置无入口（真实账号实测），但专业后台有 `Scheduled content` / 批量上传排期（≤45 条，前端 bundle 证据）。map.md 的「网页端同样没有定时入口」应改为「入口在另一界面，需实测资格」。
3. Stories 有完整 `STORY_CREATION_*` 前端状态机（含视频与贴纸），但创建弹窗的格式入口未实测；入口受实验门控（`PolarisHasFeedCreationV2Dogfooding`、HEIC 门控），规格须把「入口缺失」当显式 `unsupported` 分支。
4. 搜索型控件（地点/协作者/商品/曲库）的成本在选择器与重试，不在参数解析；`config_issue` 无网页等价物，标签类元数据需发布后回读对账。复核清单见 research §5（#1 格式入口、#11 share_to_feed、#13 定时入口决定三条路线可行性）。
