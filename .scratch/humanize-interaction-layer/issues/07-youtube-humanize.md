# 07 — YouTube：标题/简介逐字 + `#` 候选点选

**What to build:** YouTube 发布路径接入人类化。标题/简介改为逐字（含 `#` 字符），每段 `#tag` 后等 `tp-yt-iron-dropdown` 候选项，在自动补全容器内按文本全等点选；匹配不到则保留纯文本、关闭联想、继续流程。`_click_if_present` 接收并转发 `Humanizer`，20+ 调用点统一改；`_fill_editable` 的「不要逐字」docstring 作废并改写。

规格依据：§3.14、§2.4、§4。波次：W2（本波热点，先做——候选点选最可能推翻既定路径）。

Blocked by: 01

Status: ready-for-agent

- [ ] 标题/简介清空后逐字；>1000 码点仍走一次 bulk
- [ ] `#` 候选按文本全等点选；失败降级纯文本 + 关闭浮层，不中止发布
- [ ] 多个 `#tag` 逐个处理，不整段批量插入
- [ ] `_click_if_present` 的「可缺席」语义保留（找不到 → 返回 False，不抛）
- [ ] 零 `fill(`、零 `el.click()`；无 force
- [ ] `tests/test_youtube_humanize.py` 三条（含候选全等命中与降级两条用例）
- [ ] YouTube 入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W2 小节加本平台一行

