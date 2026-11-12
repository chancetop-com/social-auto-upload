# 14 — 视频号：短标题/描述语义拆分与 Locator 化

**What to build:** 发布表单接入人类化，并把三处 `page.click(selector)` 与一处 `ElementHandle` 改成 `Locator` 后交给 `Humanizer`。字段语义按注释修正：大编辑区是「视频描述」，真正短标题是独立 input；描述默认值未知，先读空再写。定时、合集、封面、提交各点接入；登录与错误重传保持原生。

规格依据：§3.10、§4。波次：W4。

Blocked by: 01

Status: ready-for-agent

- [x] 三处 `page.click(selector)` 与日期格的 `ElementHandle` 全部 Locator 化
- [x] 短标题与描述分开处理；描述预填未知时先读空
- [x] 合集项按精确 `.name` 选；`force` 删除（视口问题由 01 解决）
- [x] 提交点 `before_submit`；JS 兜底删除，失败即 `ElementUnusable`
- [x] `tests/test_tencent_humanize.py` 三条
- [x] 视频号入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W4 小节加本平台一行

## Answer

- 视频号包内全部可见点击改为 `Humanizer.click`（定时开关收窄 `.nth(1)`、日期格由 `ElementHandle` 改 `Locator.nth`、合集项精确 `.name` 且删 force/dispatch_event）；登录二维码刷新、失败素材删除、时间浮层焦点点击保留原生并带 `# native-click:` 标记。
- 短标题（独立 `input`，`sel` 全选覆盖）与视频描述（`div.input-editor`）分开：描述默认值未知，先用 `_guard_description` 读值，预填则覆盖；话题与正文以“已写入前缀”为 guard 追加，>1000 字由 `type_text` 整段 `insert_text`。
- 定时小时 picker 预填值改为 `ControlOrMeta+A` → `Delete` → 逐字 `type_text` → `Enter`；发布点击补 `before_submit`，删除 `evaluate("el => el.click()")` 兜底，`mouse.down` 后失败不再二次派发（`click_dispatched="maybe"`）。
- 测试 `tests/test_tencent_humanize.py` 9 条（事件序列 / 字段读回 / 静态门 / `HUMANIZE=0`）全绿；全量 `pytest -q` 1568 passed, 2 skipped；门 A–E `assert_clean` 通过。
- 未验证项：发布按钮真实点击与提交后行为（本轮按规格只做离线验证，见 spec §9 #28）；描述编辑器预填在真机的具体形态（§9 #19）仍为「先读再定」的运行时判断。
