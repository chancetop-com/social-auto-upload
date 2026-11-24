# Instagram 协作者（Collaborators）发布时邀请

Label: wayfinder:map

## Destination

给 `sau instagram upload-video` / `upload-note` 增加发布前邀请协作者的能力：在创建页逐个选中请求的 username，回读确认，停在 Share 前；结果写入既有 `options.collaborators`。只做发布时邀请，不追踪对方是否接受。

## Notes

- 依据：2026-11-24 对 `luke` / `lukechen918` 的实测（中文图文 + 英文 Reels + Done 重开）。全程未点 Share。
- 本能力反转 `.scratch/instagram-browser-parity/issues/08-test-strategy.md` / `spec.md §1.3` 的「collaborators 不做」决定；反转理由与新的验收边界写在 [spec.md](./spec.md)。
- 术语「协作者」「协作者邀请」已写入 [GLOSSARY.md](../../GLOSSARY.md)。
- 语言：本地模式保留 Profile/账号语言（`178f442` 之后的行为）；选择器必须结构优先、中英文回退。旧 CHANGELOG / issue 17 的「本地固定英文」说法已过时，另记清理。
- 2026-11-24：证据清理完成（`evidence/` 保留 4 张关键截图）；`issues/01–05` 由后续 `/to-tickets` 生成，取代此前按层拆的 9 项任务。

## Decisions so far

- [规格](./spec.md) — `Status: ready-for-agent`；`--collaborator` 可重复；trim / 去一个前导 `@` / 转小写；重复与空值退出 `2`；上限 5；只按 username 精确匹配；逐次回读、首个失败即停；结果只记 `options.collaborators`，不记邀请状态。
- [实测](./findings.md) — 两帖型都有入口；都走 Collaborators 面板 + Done，图文另有预览图 chip 可逐个回读，Reels 只能读面板 checkbox；Done 保留已选；网页上限 5；`nike` 子串会误选 `_nikeza5`。
- 2026-11-24：Reels 面板收不起来复用 `list_not_collapsed`；文档描述拓宽为「候选列表或协作者面板未收起」，不新增原因值。

## Not yet specified

- 未来同时支持 `user_tags` 时，如何区分协作者 chip 与用户标签。

## Out of scope

- 接受/拒绝邀请、邀请状态、发布后回读与增删协作者。
- 第二账号的「邀请 → 接受」真发验收。
- Stories、官方 API、OAuth、公网媒体。
- 托管模式的真实账号验收。
- 固定本地模式 locale 或修正历史文档。

## Tickets

以下 5 张纵向票由 `/to-tickets` 生成，取代此前按层拆的 9 项任务：

- [01 — 图文/轮播：邀请 1–5 个协作者并逐个回读 chip](./issues/01-note-collaborator-invite.md) — 无阻塞，可立即开始。
- [02 — Reels：在同一面板勾选协作者并逐个回读 checkbox](./issues/02-reels-collaborator-invite.md) — 阻塞于 01。
- [03 — 协作者的失败与边界语义（两帖型）](./issues/03-collaborator-failure-semantics.md) — 阻塞于 01、02。
- [04 — 文档、结果契约与既有选项回归](./issues/04-docs-and-regression.md) — 阻塞于 01–03。
- [05 — 真实账号 `--no-publish` 协作者验收](./issues/05-real-account-acceptance.md) — 阻塞于 01–03；`ready-for-agent`，登录前置。
