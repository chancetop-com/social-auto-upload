# 03 — 协作者的失败与边界语义（两帖型）

**What to build:** 当协作者入口缺失、页面明确禁用或账号不合格、搜索无候选、有候选但无同 username、点击后未选中、创建页被遮挡，或 Reels 的 Collaborators 面板未收起时，命令停在 Share 前，不发布；结果给出对应的 `status` / `reason`，已确认的部分保留在 `applied`，退出 `1`。任何协作者选项失败都不得映射为「发布结果未知」（退出 `9`）。

**Blocked by:** 01 — 图文/轮播：邀请 1–5 个协作者并逐个回读 chip；02 — Reels：在同一面板勾选协作者并逐个回读 checkbox。

**Status:** ready-for-agent

**Resolution:** completed

- [x] 入口缺失：`unsupported` + `entry_missing`，退出 `1`，Share 点击为零。
- [x] 入口禁用或页面明确账号不合格：`unsupported` + `account_ineligible` 或 `control_disabled`，退出 `1`。
- [x] 搜索无候选：`mismatch` + `no_candidates`；有候选但无同 username：`mismatch` + `no_same_username_candidate`。
- [x] 点击后未选中或回读不到：`mismatch` + `selection_failed` 或 `final_mismatch`，`applied` 保留已确认部分。
- [x] 创建页被前台确认框遮挡：`mismatch` + `editor_obscured`，不点 Share，不把读不到控件误报成入口缺失。
- [x] Reels 面板未收起：`mismatch` + `list_not_collapsed`；文档描述同步拓宽为「候选列表或协作者面板未收起」。
- [x] 首个失败即停：后续 username 不再尝试，结果只记一个原因；失败前的 `applied` 按请求顺序保留。
- [x] 两帖型都覆盖上述分支；每个失败分支的 Share 点击为零，退出码为 `1`（静态错误仍为 `2`）。
