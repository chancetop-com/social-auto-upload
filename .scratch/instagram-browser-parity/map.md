# Instagram 内容发布能力对齐 — 路线图

## Destination

一份可交给后续会话实施的规格：在不接入官方 API 的前提下，以 Instagram Content Publishing API 的两套变体（Instagram API with Facebook Login / Business，与 Instagram API with Instagram Login / Standalone）为能力参照，用现有 instagram.com 浏览器流程对齐其作者侧内容发布能力。产出包括：能力矩阵（每项能力在两套 API 的支持情况、网页端是否可达、不可达原因）、命令/参数契约、默认值、失败语义、测试与验收策略。

## Notes

### 已确认约束（charter）

- 通道固定：继续用浏览器 + 可选托管 Profile（MLX / AdsPower）；不接官方 API、不做 OAuth、不注册开发者 App、不要求公网媒体 URL。
- 参照系：两套 Content Publishing API 的能力清单；只覆盖内容发布，不覆盖评论、洞察、消息、webhooks 等发布后管理。
- 实现基线：现有 `uploader/meta_uploader/insgraph_uploader/main.py` 与 `sau_commands/instagram.py`；不另起一套架构。
- 现有 `upload-video` / `upload-note` / `verify` / `delete` 的参数、行为、退出码保持向后兼容。**例外（08 修订）**：caption >2200 的退出码由 1 改为 2，与 TikTok / 小红书对齐。
- 先做能力差异分析，再由用户决定基线（并集/交集/以 Business 为主）与逐项取舍。
- 网页端语言按现有实现处理（中英文选择器均已观察）；不新增本地模式。

### 代码事实

- 入口：`sau_cli.py` → `sau_commands/instagram.py` → `uploader/meta_uploader/insgraph_uploader/main.py`。
- 现有能力：Reels（MP4/MOV）、单图、轮播、配文合并（标题+正文+标签，≤2200）、视频自定义封面、立即发布、结果文件、verify/delete。
- 已知缺口（SKILL.md）：无定时、地点、协作者、AI 标识、替代文字、滤镜、裁剪、声音、评论/点赞设置；沿用页面默认值。
- 测试：`tests/test_instagram_uploader.py`；托管模式已有 fake/契约测试。
- 结果语义：`published` / `processing` / `submission_unknown`；禁止把未知当成功或自动重发。

### 参考

- 全量对照表（含已做/未做/API-only）：[`capability-matrix.md`](./capability-matrix.md)。
- Meta 官方文档：Instagram Platform Content Publishing（两套登录变体）。
- 2026 官方文档另列 **Instagram API with Unified Login**（无 Page、支持 product tagging / partnership ads / Audio，新能力只在此变体上线）；它不改变能力基线，只影响账号拓扑说明。
- 研究结论必须标注置信度：官方文档 / 开源实现实测 / 仅推断。

## Decisions so far

<!-- 一条已关闭工单一行，格式：- [标题](链接) — 一句话结论 -->

- [01 — Instagram API with Facebook Login（Business）内容发布能力清单](./issues/01-business-api-capabilities.md) — 四种媒体（单图/轮播/Reels/Stories）；独立 feed video 已停用，改 `REELS`+`share_to_feed`；配文 2200/30 hashtag/20 @；元数据含 alt_text/location/collaborators/user_tags/product_tags/AI 标识/share_to_feed/cover/audio；**无原生定时**；媒体需公网 URL；50 帖/24h；`config_issue` 表示“发布成功但元数据降级”。
- [02 — Instagram API with Instagram Login（Standalone）能力清单与差异](./issues/02-standalone-api-capabilities.md) — Standalone 是 Business 的严格子集，无“仅 Standalone”发布能力；仅 Business 有 location/collaborators/product_tags/Audio/partnership ads/caption add-ons/删除；2026 新增 Unified Login，Standalone 进入维护态。
- [03 — 现有 instagram.com 浏览器实现能力清单](./issues/03-current-browser-inventory.md) — 已实现 Reels/单图/轮播/配文合并/自定义封面/立即发布/结果三态/verify-delete；未接入全部发布元数据、Stories、feed video、定时；无媒体尺寸/时长/宽高比校验；无真实账号 e2e。
- [04 — 网页端可达性矩阵](./issues/04-web-reachability.md) — 网页端比 API 宽：PNG/AVIF、完整曲库、Story 贴纸、滤镜、发布前关评论、独立专业号可用地点/协作者、本地文件直传；alt_text/location/collaborators/user_tags/AI 标识/Stories 均“有入口未接入”；**定时入口在专业后台 Scheduled content，不在主 composer**；Trial Reels/商品标签/品牌内容/caption add-ons 很可能 API-only。
- [05 — 目标能力基线与逐项取舍](./issues/05-capability-baseline.md) — 基线取“网页可达并集”；第一波做价值排序 1–10 但排除 #3 媒体校验：Stories、定时、location、关评论、配乐、选帧封面、user_tags、alt_text、AI 标识；媒体校验本轮不做。
- [06 — 第一波能力的真实账号入口实测](./issues/06-entry-probe.md) — Personal 账号 + English UI：location/collaborators/user_tags/alt_text/关评论/AI 标识/滤镜/隐藏点赞/上传封面确认有入口；Stories/定时/配乐在该账号网页端不可用（定时需专业后台）；选帧封面与搜索联想待实测。
- [07 — 第一波 9 项的参数契约与默认值](./issues/07-parameter-contract.md) — 独立 flag 镜像 TikTok；第一波注册 `--location`、`--alt-text`（可重复，仅 note）、`--no-comments`、`--ai-generated/--no-ai-generated`（**collaborators 经 08 移除**）；未传不动默认；on/值请求入口缺失或回读不一致 → exit 1，off 请求入口缺失 → 视为满足 exit 0；`--user-tags/--story/--schedule/--audio/--cover-frame-ms` 不纳入。
- [08 — 第一波参数契约的测试与验收策略](./issues/08-test-strategy.md) — 第一波缩为 4 项；三层测试（`options.py` 纯逻辑 + fake 控制件 + 真实 DOM happy path）；静态输入错误统一 exit 2（**caption 超长改为 2，破坏性变更**）；`options` 保留 5 status 并加 `reason=entry_missing|account_ineligible`；真发验收本轮不做，作为 09 的独立附录且不写账号；漂移靠 4 条真实 DOM 用例当哨兵，不引入 manifest。
- [09 — 汇总第一波实施规格](./issues/09-assemble-spec.md) — 产出 [`spec.md`](./spec.md)：4 项参数契约、配文页 UI 路径与双语选择器、`resolve/read/set` 回读协议、5 status + 2 reason 失败语义、三层测试与退出码矩阵、独立真发验收附录、部署/回滚；collaborators 不实现，caption 超长 exit 2。

- [10 — 共用选项管线与静态校验](./issues/10-options-pipeline-prefactor.md) — `options.py`（三态数据类 + 5 status 纯函数 + 控件协议）、`_apply_options` 通用管线、`options` 结果骨架、CLI 透传与静态校验落地；caption 超长改 `UsageError → 2`。
- [11 — 关闭评论端到端](./issues/11-disable-comments.md) — `SwitchControl` + `disclosure_panel` 复用件；`--no-comments` 语义反转（checked = 已关闭），高级设置展开幂等；入口缺失/disabled 且请求关闭记 `default_off`。
- [12 — AI 生成标识端到端](./issues/12-ai-generated-label.md) — `--ai-generated/--no-ai-generated` 互斥组；复用 `SwitchControl` 不反转；on + 入口缺失 → exit 1，off 已满足 → exit 0。
- [13 — Location 端到端](./issues/13-location.md) — 输入 → 联想 → 规范化精确匹配 → 回读；空白候选保留原始下标避免点错；无匹配列候选并 exit 1，绝不点模糊候选。
- [14 — Alt text 端到端](./issues/14-alt-text.md) — Accessibility 模态框逐张填写、关闭后重开回读；数量 0 → `unsupported(entry_missing)`，1..N-1 → `mismatch` 并保留部分回读。
- [15 — 文档与回归收口](./issues/15-docs-and-regression.md) — `docs/CLI.md` / `CHANGELOG.md` / `GLOSSARY.md` / Instagram Skill 与实现对齐；A/B/C/D 全绿；四项标 `offline-verified / post-publish unverified`，真发验收见 [16](./issues/16-real-account-acceptance.md)（非阻塞、待人工）。

## Not yet specified

<!-- 第一波规格已交付；本 effort 的目的地已到达。以下未决项属于后续第二波的新 effort，不在此地图继续展开。 -->

## Out of scope

- 官方 Content Publishing API 接入、OAuth、开发者 App 审核、token 管理、公网可访问媒体 URL、容器轮询。
- 评论、洞察、消息、webhooks 等发布后管理能力。
- Flask 后端 `sau_backend.py`、Vue 前端、调度 App 本身。
- 账号↔Profile 映射与身份校验。
- Stories / 定时发布 / 配乐：当前 Personal 账号网页端不可用，需 Creator/Business 账号复核；本轮明确延后（见 [05](./issues/05-capability-baseline.md)、[06](./issues/06-entry-probe.md)）。
- 选帧封面：上传封面已确认，从视频选帧未观察到；本轮延后。
- 协作帖（collaborators）：[08](./issues/08-test-strategy.md) 从第一波移除，本轮不实现；等有第二账号可做“邀请 → 接受”验收时另起 effort。
- 媒体大小/时长/宽高比校验、滤镜、隐藏点赞、user_tags、商品标签、品牌内容、caption add-ons：本轮不做，已在规格 §1.3 与能力矩阵中记录。
