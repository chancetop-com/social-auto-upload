# 09 — Facebook Page：Reel 与定时表单接入人类化

**What to build:** Business Suite 的正文、Reel 向导、Page 选择、定时表单与发布点击走 `Humanizer`。按序号取的按钮（`.nth` / `.last`）先按文本或 aria 收窄到唯一 `Locator`；「同时发快拍」先读 `is_checked` 再决定是否点。引导卡与删除路径保持原生并加标记。

规格依据：§3.8、§4。波次：W2。

Blocked by: 01

Status: ready-for-agent

- [ ] 正文与 Reel 独立标题逐字；>1000 码点一次 bulk
- [ ] 序号定位全部改为文本/aria 收窄；收窄后仍多义即硬错
- [ ] 小时/分钟 spinbutton 点击人类化，后续逐键输入保留
- [ ] 发布点 `before_submit`；零 `fill(`、零 `el.click()`、无 force
- [ ] `tests/test_facebook_page_humanize.py` 三条
- [ ] Facebook Page 入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W2 小节加本平台一行

