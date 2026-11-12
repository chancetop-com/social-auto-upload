# 05 — Instagram 真机验收

**What to build:** 不改生产代码。本地模式真机跑 Instagram 发布（视频 + carousel 图文），同时记录 `HUMANIZE=1` 与 `HUMANIZE=0` 两条路径的墙钟、预算消耗与成败，落 `.scratch/humanize-rollout/acceptance.md`。

规格依据：§6.4、§7.1。

Blocked by: 02

Status: ready-for-human

- [ ] 视频 + 图文各一次成功（退出码 0）
- [ ] 配文 >1000 码点时 `insert_text` 后读回一致；≤1000 时逐字可读回
- [ ] 地点候选逐字后按全等选中；未错选相邻项
- [ ] alt text 逐张写入后失焦保存，读回一致
- [ ] `HUMANIZE=1` / `=0` 双基线已记录（墙钟、差值、成功与否）
- [ ] 风控观测：是否出现验证码 / 滑块 / 限流提示
- [ ] 帖子 URL + 是否已删；结论 pass/fail + 失败字段
- [ ] 若失败且判定为人类化导致 → 回滚 02 的平台提交，不保留双形态

