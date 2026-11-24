# 05 — 真实账号 `--no-publish` 协作者验收

**What to build:** 用已登录的本地 Instagram Profile，在图文/轮播与 Reels 各跑一次真实的 `--no-publish` 命令：1–5 个协作者、停在 Share 前、结果为 `prepared`，逐个回读通过。记录账号别名、界面语言、帖型、请求/已选列表与停止点。若运行中登录失效，停止并报告 `blocked: login required`，不自行登录，不把登录问题当成代码失败。不要求第二账号接受邀请。

**Blocked by:** 01 — 图文/轮播：邀请 1–5 个协作者并逐个回读 chip；02 — Reels：在同一面板勾选协作者并逐个回读 checkbox；03 — 协作者的失败与边界语义（两帖型）。

**Status:** ready-for-agent

- [ ] 图文/轮播与 Reels 各完成一次 `--no-publish`，结果为 `prepared`，`options.collaborators.status=set`，`applied` 与请求一致。
- [ ] Share 点击为零；未发出任何邀请。
- [ ] 记录账号别名、界面语言、帖型、请求/已选列表与停止点，作为验收证据。
- [ ] 覆盖至少一个 1 人请求和一个多人（2–5 人）请求；两帖型都能逐个回读。
- [ ] 登录失效时明确报告 `blocked: login required`，不尝试自动登录，不把该情况记为代码失败。
- [ ] 不要求第二账号接受邀请；接受状态不影响本次验收结论。
