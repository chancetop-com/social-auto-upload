# 12 — 知乎：视频/文章/定时三表单接入人类化

**What to build:** 视频表单（领域、标记、原创）、文章表单（标题守卫、正文聚焦、发布）、定时表单（日期/时间/确认，16 个点）与两个提交点全部走 `Humanizer`；失焦专用点击与发布后详情跳转保持原生并加标记。本地同名 `select_option` 是终端交互方法，不动。

规格依据：§3.15、§4。波次：W4。

Blocked by: 01

Status: ready-for-agent

- [ ] 视频与文章标题按 §3.15 的守卫形态处理（清零 = none，依赖非空即拒绝）
- [ ] 原创 checkbox 先读状态再点（幂等）；领域/标记下拉按精确文本选
- [ ] 定时表单 16 个点全部接入；日期控件预填场景按需全选
- [ ] 零 `fill(`、零 `el.click()`、无 force；失焦点击带 `# native-click: focus`
- [ ] `tests/test_zhihu_humanize.py` 三条（含定时表单逐步断言）
- [ ] 知乎入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W4 小节加本平台一行

