# 05 — Instagram 真机验收（`--no-publish`）

**What to build:** 不改生产代码。本地模式真机用 **`--no-publish` 干跑** Instagram（视频 + carousel 图文各一次），跑到 Share 就绪（窗口 `min(60s, 剩余预算)`）即停，**不点击发布、不上真实帖子**；`--result` 的状态应为 `prepared`，不写 `content_id` / `post_url`。同时记录 `HUMANIZE=1` 与 `HUMANIZE=0` 两条路径的墙钟、预算消耗与成败，落 `.scratch/humanize-rollout/acceptance.md`。

规格依据：§6.4、§7.1；干跑契约见 `docs/CLI.md` 的 `--no-publish` 一节。

Blocked by: 02

Status: ready-for-human

- [ ] 视频 + carousel 各一次跑到 Share 就绪，退出码 0
- [ ] 就绪超时（退出 1）视为失败：记录目标、reason 与预算余量
- [ ] 配文 >1000 码点 `insert_text` 后读回一致；≤1000 时逐字可读回
- [ ] 地点候选逐字后按全等选中；未错选相邻项
- [ ] alt text 逐张写入后失焦保存，读回一致
- [ ] `HUMANIZE=1` / `=0` 双基线已记录（墙钟、差值、成功与否、停止点）
- [ ] 风控观测：是否出现验证码 / 滑块 / 限流提示
- [ ] 发布按钮的真实点击**不验**（§9-28）
- [ ] 若失败且判定为人类化导致 → 回滚 02 的平台提交，不保留双形态

