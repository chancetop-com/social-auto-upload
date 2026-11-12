# 02 — Instagram：发布流接入人类化

**What to build:** Instagram 发布路径的文本与可见点击全部走 `Humanizer`：配文（Lexical）清空后逐字、地点逐字 + 有界等待 + 候选全等、alt text 逐张清空后逐字；`_rows.activate` / `click_control` 的两级 JS 兜底删除，改为键盘/坐标点击，失败即硬错。文件选择器与作品管理路径保持原生，逐条加 `# native-click` 标记。

规格依据：§3.9、§2.4、§4。波次：W1（真机探针）。

Blocked by: 01

Status: ready-for-agent

- [ ] 先改公共底座 `activate` / `click_control`：零 `el.click()`，保留原键盘优先顺序
- [ ] 每个文本点先收窄到 `count()==1`；清空按 §3.9 的形态手写；每次输入恰一次 `after_type`
- [ ] 分享点带 `before_submit`；零 `force`、零 JS 点击、零 `fill(`（清空动作改键）
- [ ] 地点候选逐字节奏不快于原有 `TYPE_DELAY_MS`，debounce 期间不重复输入
- [ ] `tests/test_instagram_humanize.py` 三条：事件序列、字段值读回、平台静态门
- [ ] IG 入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W1 小节加本平台一行

