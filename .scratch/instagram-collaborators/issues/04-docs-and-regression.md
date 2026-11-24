# 04 — 文档、结果契约与既有选项回归

**What to build:** 把已实现的行为写进用户文档与 Instagram Skill：`--collaborator` 的形态、归一化与上限 5；`options.collaborators` 的字段与 `status` / `reason`；`set` 只表示「创建页已选中」，不代表邀请已送达或已被接受；网页上限 5 与 Meta API 文档 3 的差异；本地模式保留 Profile 语言、托管模式要求人工 English。更新 CHANGELOG。运行既有 Instagram 选项与 `--no-publish` 回归，确保新增第五个 `options` 键不破坏旧行为。

**Blocked by:** 01 — 图文/轮播：邀请 1–5 个协作者并逐个回读 chip；02 — Reels：在同一面板勾选协作者并逐个回读 checkbox；03 — 协作者的失败与边界语义（两帖型）。

**Status:** ready-for-agent

**Resolution:** completed

- [x] CLI 文档包含 `--collaborator` 示例、五个 `options` 键、失败原因与退出码，并明确 `set` 不代表接受。
- [x] Instagram Skill 从「协作者未接入」改为已接入，说明上限 5、逐个回读、语言/选择器策略与接受状态边界。
- [x] CHANGELOG 的 Unreleased 条目记录能力、上限证据日期与账号、以及「不验证接受状态」。
- [x] 文档明确 `no_same_username_candidate` 为新增原因值，`list_not_collapsed` 的描述已拓宽。
- [x] 既有 location / alt_text / comments / ai_generated 与 `--no-publish` 回归全绿；未传 `--collaborator` 时零控件交互。
- [x] `options` 始终包含五个键；旧消费方忽略新键即可，既有字段与取值不变。
- [x] 文档记录已知限制：图文/Reels 的 UI 差异、网页上限可能漂移、未来 user tags 需要区分 chip。
