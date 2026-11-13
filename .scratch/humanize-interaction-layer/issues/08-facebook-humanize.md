# 08 — Facebook（个人主页）：发布流接入人类化

**What to build:** Facebook composer 的正文与发布点击走 `Humanizer`。正文清空后逐字（>1000 码点一次 bulk），`after_type` 后读回；发布点带 `before_submit`。作品删除/管理路径保持原生并加标记。本票是最小切片，用来先打通平台契约与测试骨架。

规格依据：§3.7、§4。波次：W2。

Blocked by: 01

Status: resolved

- [x] 正文：聚焦 → 全选清空 → 逐字 → 恰一次 `after_type`；读回与输入一致
- [x] 发布点 `before_submit`；发布后读回校验保留
- [x] 删除/管理路径逐条 `# native-click: manage`
- [x] 零 `fill(`、零 `el.click()`、无 force
- [x] `tests/test_facebook_humanize.py` 三条（含 >1000 码点 bulk 断言）
- [x] Facebook 入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W2 小节加本平台一行

## Answer

- 正文：按 page 缓存的 `Humanizer(page, sleep=self._humanize_pause)`（`cached.page is not page` 失效，样板见 playbook §2）；`sel` 形态 = 坐标点击 → `ControlOrMeta+A` → `Delete` → `type_text`，先把 `\r\n` / 孤立 `\r` 归一为 `\n`，>1000 码点由共享层整段 `insert_text`，`after_type` 恰一次，读回比对保留。
- 发布：`before_submit` → 预算复核 → `humanizer.click`（原有的发布后成功文案读回循环未改）。删除/管理 6 处与 file input 1 处保持原生，各带 `# native-click: manage/file；…`。
- 测试：`tests/test_facebook_humanize.py` 6 条 —— 事件序列（`press`/`insert_text`/`Enter`、hit-test 先于 `down`、`before_submit` 在发布 `down` 前、多义硬失败）、字段读回（草稿覆盖 + CRLF 归一 + >1000 bulk）、`HUMANIZE=0`、门 A–E。全量 `pytest -q`：1532 passed / 2 skipped。
- 偏差：规格 §3.7 写「`:198` 之后构造」，实际按 playbook 样板做成首次使用时按 page 缓存（登录流程也会 `new_page()`，发布链路只在发帖 page 上构造）；正文收窄沿用既有 `expect(...).to_have_count(1)`（等待期内恰一个，多义硬失败），未改成一次性 `count()` 判定。
- 未验证：真机（本轮只做离线三条）；发布按钮的坐标点击与 `before_submit` 由离线测试 + 小红书既有真机证据背书。
