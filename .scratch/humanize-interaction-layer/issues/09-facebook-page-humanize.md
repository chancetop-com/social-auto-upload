# 09 — Facebook Page：Reel 与定时表单接入人类化

**What to build:** Business Suite 的正文、Reel 向导、Page 选择、定时表单与发布点击走 `Humanizer`。按序号取的按钮（`.nth` / `.last`）先按文本或 aria 收窄到唯一 `Locator`；「同时发快拍」先读 `is_checked` 再决定是否点。引导卡与删除路径保持原生并加标记。

规格依据：§3.8、§4。波次：W2。

Blocked by: 01

Status: resolved

- [x] 正文与 Reel 独立标题逐字；>1000 码点一次 bulk
- [x] 序号定位全部改为文本/aria 收窄；收窄后仍多义即硬错
- [x] 小时/分钟 spinbutton 点击人类化，后续逐键输入保留
- [x] 发布点 `before_submit`；零 `fill(`、零 `el.click()`、无 force
- [x] `tests/test_facebook_page_humanize.py` 三条
- [x] Facebook Page 入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W2 小节加本平台一行

## Answer

- 14 个改 Humanizer 的点全部接线：Reel 标题/正文 `sel` 清空后逐字（正文 >1000 码点整段 `insert_text`），Page 下拉与选项、Reel 下一步 ×2、快拍开关（先 `is_checked`）、快拍弹窗主动作、定时模式/日期/上下一月/日/小时/分钟、发布（`before_submit`）与完成框关闭均走 `Humanizer.click`；小时/分钟打开后仍用 `locator.press` 逐键覆盖预填值。
- 原先按序号的发布按钮、快拍弹窗动作、定时模式、月切换、完成框关闭全部改为可访问名称收窄；收窄后 `count() > 1` 抛 `ElementUnusableError(reason="ambiguous:N")`，不静默取 `.first`。`entries.nth(0)`（文件触发，规格 `N/file`）、步骤态 `steps.nth(index)`（只读状态不点击）与 `posts.py` 删除路径（规格 `N/manage`）保留序号。
- 引导卡 `# native-click: chrome`、文件触发 `# native-click: file`、列表/删除 6 处 `# native-click: manage`；包内门 A–E 全绿，零 `fill(`、零 `el.click()`、零 `force`。
- 新增 `tests/test_facebook_page_humanize.py`：事件序列（含 stillOn 先于 down、恰两次 `after_type`、bulk 一次 `insert_text`）、字段值读回（预填清空、CRLF 归一）、静态门，另含 `HUMANIZE=0` 与 `ambiguous:2` 用例。
- 偏差：可访问名称集合按中/英/日三种实测语言编写，真机标签若不同会在收窄处硬错（statically unverified，需真机确认「定时」「下一月」「完成」等实际文案）；`HUMANIZE=0` 下清空仍走 `ControlOrMeta+A`/`Delete`，仅输入与点击切回原生。
