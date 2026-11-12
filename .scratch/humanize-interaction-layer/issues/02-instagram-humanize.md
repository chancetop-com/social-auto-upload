# 02 — Instagram：发布流接入人类化

**What to build:** Instagram 发布路径的文本与可见点击全部走 `Humanizer`：配文（Lexical）清空后逐字、地点逐字 + 有界等待 + 候选全等、alt text 逐张清空后逐字；`_rows.activate` / `click_control` 的两级 JS 兜底删除，改为键盘/坐标点击，失败即硬错。文件选择器与作品管理路径保持原生，逐条加 `# native-click` 标记。

规格依据：§3.9、§2.4、§4。波次：W1（真机探针）。

Blocked by: 01

Status: ready-for-agent

- [x] 先改公共底座 `activate` / `click_control`：零 `el.click()`，保留原键盘优先顺序
- [x] 每个文本点先收窄到 `count()==1`；清空按 §3.9 的形态手写；每次输入恰一次 `after_type`
- [x] 分享点带 `before_submit`；零 `force`、零 JS 点击、零 `fill(`（清空动作改键）
- [x] 地点候选逐字节奏不快于原有 `TYPE_DELAY_MS`，debounce 期间不重复输入
- [x] `tests/test_instagram_humanize.py` 三条：事件序列、字段值读回、平台静态门
- [x] IG 入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W1 小节加本平台一行

## Answer

- 公共底座已归零：`_rows.activate` 保留 `focus` + Enter，最后一级只做一次 `Humanizer.click`；`click_control` 直接坐标点击；两处 `el.click()` 删除，点击失败原样上抛。
- 三个文本点：配文与 Alt text 用 `sel`（聚焦 → `ControlOrMeta+A` → `Delete` → `type_text`），地点首次只聚焦、重试用全选 + `Backspace`；每点先 `count()==1`（多义 `ambiguous:N`），Alt text 逐张显式清空并保留 blur。
- 可见点击：创建入口、裁剪下一步走 `Humanizer.click` + `after_navigate`；Share 先 `before_submit`；提示关闭、折叠行与开关、地点候选全部坐标点击；候选经一次性属性戳转成 `Locator`（无 `ElementHandle` 点击、无 JS 点击）。
- 地点节奏：逐字由 `Humanizer.type_text` 派发（均值 136ms），整段不足 `TYPE_DELAY_MS × 字数` 时补一次预算内停顿；debounce 期间不重复输入。
- 测试：`tests/test_instagram_humanize.py` 22 条（事件序列 / 字段读回 / 门 A–E / `HUMANIZE=0`）；合并 `humanize-interaction-layer` 后全量 `1581 passed, 2 skipped`。真机探针仍属 05（本轮离线 + 既有真实 Chrome DOM 回归，未跑真机）。
