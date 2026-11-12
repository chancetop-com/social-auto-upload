# 11 — 微博：双实例 + 发布按钮比例落点

**What to build:** 首页 page 与 `expect_popup()` 得到的发布 page 各持一个 `Humanizer`（后者承担其余全部交互）。发布按钮用比例落点 `(0.65, 0.5)`，失败且确认未派发时换 `(0.35, 0.5)` 再试一次，仍失败即 `ElementUnusable`。三处 JS 点击清零：新建合集点行内文字 span、确认框直接坐标点击；合集开关点 `span[role=switch]`。

规格依据：§3.11、§4。波次：W3（热点置顶）。

Blocked by: 01

Status: ready-for-agent

- [x] 两个实例的构造点正确；跨 page 不复用；popup 之后重建
- [x] `el.click()` 三处清零，`force` 两处删除（改点装饰层 / 文字 span）
- [x] 发布按钮落点按 `(0.65,0.5)` → `(0.35,0.5)` 顺序；失败语义与日志正确
- [x] 封面「完成」改为点一次 + 等状态，不再 4s 周期重复点
- [x] `tests/test_weibo_humanize.py` 三条（含双实例与落点顺序）
- [x] 微博入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W3 小节加本平台一行

## Answer

- 两个实例：`_open_video_publish_page` 用首页实例（click → `after_navigate`），`upload_in` 在 popup 返回后 `self._humanizer(publish_page)` 重建，后续全部交互只走发布页实例。
- 文本 3 处（标题 ≤30 / 描述 + `#tag#` / 新建合集名 ≤12）统一 `sel`（click → ControlOrMeta+A → Delete → `type_text`），>1000 码点由共享层整段 `insert_text`；聚焦点击合并进输入序列。
- 点击全走 `Humanizer.click`：类型、声明三步、封面入口/完成、合集开关（`span[role=switch]`）、已有合集复选框、`＋新建合集` 的文字 span、发布、二次确认。包内 `el.click()` 与 `force=True` 均归零。
- 发布按钮 `(0.65,0.5)` 未派发失败时换 `(0.35,0.5)` 单次重试；`click_dispatched="maybe"` 或 `publish_clicked=True` 直接上抛，不二次派发，无 JS 兜底。
- 验证：`tests/test_weibo_humanize.py` 15 条（事件序列 / 字段读回 / 双实例 / 落点顺序与不重试 / 封面只点一次 / `HUMANIZE=0` / 门 A–E）；全量 `pytest -q` 1574 passed, 2 skipped。唯一范围外改动：`tests/test_mlx_alipay_weibo.py` 里三条断言旧的 JS 发布点击 / `_submit_publish` 签名的用例改为断言新契约。
