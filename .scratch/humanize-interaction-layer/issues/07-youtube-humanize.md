# 07 — YouTube：标题/简介逐字 + `#` 候选点选

**What to build:** YouTube 发布路径接入人类化。标题/简介改为逐字（含 `#` 字符），每段 `#tag` 后等 `tp-yt-iron-dropdown` 候选项，在自动补全容器内按文本全等点选；匹配不到则保留纯文本、关闭联想、继续流程。`_click_if_present` 接收并转发 `Humanizer`，20+ 调用点统一改；`_fill_editable` 的「不要逐字」docstring 作废并改写。

规格依据：§3.14、§2.4、§4。波次：W2（本波热点，先做——候选点选最可能推翻既定路径）。

Blocked by: 01

Status: ready-for-agent

- [x] 标题/简介清空后逐字；>1000 码点仍走一次 bulk
- [x] `#` 候选按文本全等点选；失败降级纯文本 + 关闭浮层，不中止发布
- [x] 多个 `#tag` 逐个处理，不整段批量插入
- [x] `_click_if_present` 的「可缺席」语义保留（找不到 → 返回 False，不抛）
- [x] 零 `fill(`、零 `el.click()`；无 force
- [x] `tests/test_youtube_humanize.py` 三条（含候选全等命中与降级两条用例）
- [x] YouTube 入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W2 小节加本平台一行

## Answer

- 标题/简介改 `Humanizer`：`click` 聚焦 → `ControlOrMeta+A` → `Delete` → 逐段逐字；每段 `#tag` 等 `ytcp-hashtag-autocomplete`，`get_by_text(..., exact=True)` 全等点选，未命中则 `_dismiss_autocomplete(blur=False)` 保留纯文本继续；>1000 码点由 `type_text` 整段 bulk（无第二阈值）。
- `_click_if_present` 签名加必传 `humanizer`，12 个调用点全部转发；保留「缺席 → False」，仅 `click_dispatched="maybe"` 原样上抛以免二次派发。播放列表复选框/新建名、标签输入、发布前 `before_submit` 均走人类化；`type(delay=6/4)` 与 `fill()` 已删除。
- 测试 `tests/test_youtube_humanize.py`（16 条）：事件序列（逐字原语、after_type=2、stillOn 先于 down、零 `el.click`/`fill`）、字段读回（标题/简介/合集名/标签，先清空再写）、静态门 A–E、`HUMANIZE=0`（零停顿、一次 `insert_text`、原生 click）与实例缓存。
- 偏差：>1000 码点且含 `#tag` 的字段按 `#` 分段（长段落仍各自 bulk），以便候选点选仍可执行；未加 `after_navigate`（§3.14 未列）；候选点选与浮层行为无真机验证（本仓无浏览器）。
