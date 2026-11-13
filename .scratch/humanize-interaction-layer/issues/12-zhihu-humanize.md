# 12 — 知乎：视频/文章/定时三表单接入人类化

**What to build:** 视频表单（领域、标记、原创）、文章表单（标题守卫、正文聚焦、发布）、定时表单（日期/时间/确认，16 个点）与两个提交点全部走 `Humanizer`；失焦专用点击与发布后详情跳转保持原生并加标记。本地同名 `select_option` 是终端交互方法，不动。

规格依据：§3.15、§4。波次：W4。

Blocked by: 01

Status: resolved

- [x] 视频与文章标题按 §3.15 的守卫形态处理（清零 = none，依赖非空即拒绝）
- [x] 原创 checkbox 先读状态再点（幂等）；领域/标记下拉按精确文本选
- [x] 定时表单 16 个点全部接入；日期控件预填场景按需全选
- [x] 零 `fill(`、零 `el.click()`、无 force；失焦点击带 `# native-click: focus`
- [x] `tests/test_zhihu_humanize.py` 三条（含定时表单逐步断言）
- [x] 知乎入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W4 小节加本平台一行

## Answer

- 视频 13 点（标题/介绍 `sel` 清空后逐字，介绍 >1000 码点一次 bulk；领域下拉开/关、标记弹窗开/取消、领域下拉与精确选项、标记弹窗/精确标记/确认、原创先读 `is_checked`、发布 `before_submit`）、文章 3 点（标题 `none` 不清空、正文坐标聚焦、发布 `before_submit`）、定时 17 点全部走 `Humanizer`；本地 `select_option` 终端交互方法未动。
- 定时实际 17 个点击点（文章 9 + 视频 8），与规格行号表列的 8+7+1=16 差 1：现源码视频定时区还有一次 `toggle.check()`（改为先读 `is_checked` 再点）与两个时间下拉的独立点击，规格表按旧版行号少计一处。日期/小时/分钟全部是日历格与下拉选项，没有文本输入，因此「预填全选」在本平台无适用点（`HUMANIZE=0` 下的清空键只保留在文本字段）。
- 保留原生并逐条标记：文章失焦标题 ×2 `# native-click: focus`、视频发布后「查看详情」`# native-click: read`；文件输入仍 `set_input_files`（spec `N/file`）。包内门 A–E 全绿，零 `fill(`、零 `el.click()`、零 `force`。
- `tests/test_zhihu_humanize.py`（12 例）：视频/文章表单事件序列（`press` vs `insert_text`、恰两次 `after_type`、hit-test 先于 `down`、零原生 click、bulk 一次 insert）、两个发布点的 `before_submit` 顺序、文章/视频定时逐步点击（9 / 8 次 `down`）、字段读回（标题 `none` 不清空、介绍 CRLF 归一、旧值替换）、标题守卫「已有草稿」停工、静态门与 `HUMANIZE=0` 快路径。
- 偏差/未验证：真机未跑（W4 只做离线门与单测）；`HUMANIZE=0` 时清空键仍由共享层 `press` 派发（与其它平台一致），仅输入与点击回原生；视频介绍换行做了 `\r\n`→`\n` 归一，属规格 §2.4 硬规则。
