# 06 — TikTok 真机验收

**What to build:** 不改生产代码。本地模式真机跑 TikTok 视频 + 图文发布，记录双基线（`HUMANIZE=1` / `=0`）、预算消耗与风控观测，落 `.scratch/humanize-rollout/acceptance.md`。

规格依据：§6.4、§7.1。

Blocked by: 03

Status: ready-for-human

- [ ] 视频 + 图文各一次成功（退出码 0）
- [ ] 配文清空干净（无旧文案残留）；>1000 码点读回一致
- [ ] 话题候选全等选中；未选中时保留纯文本且发布继续
- [ ] 定时/隐私/开关等选项状态与设置一致（点后读回）
- [ ] `HUMANIZE=1` / `=0` 双基线已记录
- [ ] 风控观测 + 帖子 URL + 是否已删；结论 pass/fail
- [ ] 若失败且判定为人类化导致 → 回滚 03 的平台提交

