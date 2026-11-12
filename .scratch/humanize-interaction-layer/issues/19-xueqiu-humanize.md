# 19 — 雪球：空守卫样板与预览遮罩

**What to build:** 文章标题依赖平台已有的「非空即拒绝」守卫（清空 = none），正文聚焦、工具栏传图、裁剪、分享范围、预览与关闭遮罩、发布接入人类化。失焦与发布后核对路径保持原生并加标记。

规格依据：§3.13、§2.4、§4。波次：W5。

Blocked by: 01

Status: ready-for-agent

- [ ] 标题守卫保持有效（非空输入就拒绝），不清空
- [ ] 预览遮罩关闭用坐标点击（不删遮罩、不强点）
- [ ] 发布点 `before_submit`；零 `fill(`、零 `el.click()`、无 force
- [ ] `tests/test_xueqiu_humanize.py` 三条（含守卫与遮罩关闭）
- [ ] 雪球入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W5 小节加本平台一行

