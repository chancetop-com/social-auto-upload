# 16 — 支付宝生活号：合集合并与发布接入

**What to build:** 生活号视频发布表单接入人类化：标题与描述清空后逐字，封面弹窗、合集下拉、质量提示与两次发布点击全量改；合集选择的两级点击（force 首选 + 无 force 重试）合并为一次坐标点击。登录扫码与文件入口保持原生并加标记。

规格依据：§3.1、§4。波次：W5。

Blocked by: 01

Status: ready-for-agent

- [ ] 合集选择合并为一次 `Humanizer.click`，force 首选删除
- [ ] 合集下拉先收窄两个候选分支到唯一 Locator
- [ ] 两次发布点击都带 `before_submit`；发布入口带 `after_navigate`
- [ ] 零 `fill(`、零 `el.click()`、无 force
- [ ] `tests/test_alipay_humanize.py` 三条
- [ ] 支付宝入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W5 小节加本平台一行

