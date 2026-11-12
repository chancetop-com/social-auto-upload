# 14 — 视频号：短标题/描述语义拆分与 Locator 化

**What to build:** 发布表单接入人类化，并把三处 `page.click(selector)` 与一处 `ElementHandle` 改成 `Locator` 后交给 `Humanizer`。字段语义按注释修正：大编辑区是「视频描述」，真正短标题是独立 input；描述默认值未知，先读空再写。定时、合集、封面、提交各点接入；登录与错误重传保持原生。

规格依据：§3.10、§4。波次：W4。

Blocked by: 01

Status: ready-for-agent

- [ ] 三处 `page.click(selector)` 与日期格的 `ElementHandle` 全部 Locator 化
- [ ] 短标题与描述分开处理；描述预填未知时先读空
- [ ] 合集项按精确 `.name` 选；`force` 删除（视口问题由 01 解决）
- [ ] 提交点 `before_submit`；JS 兜底删除，失败即 `ElementUnusable`
- [ ] `tests/test_tencent_humanize.py` 三条
- [ ] 视频号入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W4 小节加本平台一行

