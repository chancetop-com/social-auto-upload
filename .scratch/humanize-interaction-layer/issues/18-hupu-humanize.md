# 18 — 虎扑：专区/声明链路接入

**What to build:** 标题与简介清空后逐字，专区选择、原创/二创、AI 声明下拉与发布点击接入人类化。AI 声明下拉的裸 `combobox` 先收窄到唯一 Locator。登录与两个文件入口保持原生并加标记。

规格依据：§3.5、§4。波次：W5。

Blocked by: 01

Status: ready-for-agent

- [ ] 标题/简介逐字；简介 >1000 码点一次 bulk
- [ ] `combobox` 收窄到 1；多义即硬错
- [ ] 发布点 `before_submit`；零 `fill(`、零 `el.click()`、无 force
- [ ] `tests/test_hupu_humanize.py` 三条
- [ ] 虎扑入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W5 小节加本平台一行

