# 11 — 微博：双实例 + 发布按钮比例落点

**What to build:** 首页 page 与 `expect_popup()` 得到的发布 page 各持一个 `Humanizer`（后者承担其余全部交互）。发布按钮用比例落点 `(0.65, 0.5)`，失败且确认未派发时换 `(0.35, 0.5)` 再试一次，仍失败即 `ElementUnusable`。三处 JS 点击清零：新建合集点行内文字 span、确认框直接坐标点击；合集开关点 `span[role=switch]`。

规格依据：§3.11、§4。波次：W3（热点置顶）。

Blocked by: 01

Status: ready-for-agent

- [ ] 两个实例的构造点正确；跨 page 不复用；popup 之后重建
- [ ] `el.click()` 三处清零，`force` 两处删除（改点装饰层 / 文字 span）
- [ ] 发布按钮落点按 `(0.65,0.5)` → `(0.35,0.5)` 顺序；失败语义与日志正确
- [ ] 封面「完成」改为点一次 + 等状态，不再 4s 周期重复点
- [ ] `tests/test_weibo_humanize.py` 三条（含双实例与落点顺序）
- [ ] 微博入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W3 小节加本平台一行

