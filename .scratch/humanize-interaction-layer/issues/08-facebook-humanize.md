# 08 — Facebook（个人主页）：发布流接入人类化

**What to build:** Facebook composer 的正文与发布点击走 `Humanizer`。正文清空后逐字（>1000 码点一次 bulk），`after_type` 后读回；发布点带 `before_submit`。作品删除/管理路径保持原生并加标记。本票是最小切片，用来先打通平台契约与测试骨架。

规格依据：§3.7、§4。波次：W2。

Blocked by: 01

Status: ready-for-agent

- [ ] 正文：聚焦 → 全选清空 → 逐字 → 恰一次 `after_type`；读回与输入一致
- [ ] 发布点 `before_submit`；发布后读回校验保留
- [ ] 删除/管理路径逐条 `# native-click: manage`
- [ ] 零 `fill(`、零 `el.click()`、无 force
- [ ] `tests/test_facebook_humanize.py` 三条（含 >1000 码点 bulk 断言）
- [ ] Facebook 入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W2 小节加本平台一行

