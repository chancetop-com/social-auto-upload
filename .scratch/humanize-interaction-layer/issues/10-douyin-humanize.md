# 10 — 抖音：删除 `_native_click`，全流接入人类化

**What to build:** 删掉平台内手写坐标点击 `_native_click`（含合成 pointer 事件重放），8 个调用点改 `Humanizer.click`，保留既有「点后校验弹窗/弹层状态 → 重试 / 降级 / Esc」循环与全部状态谓词。描述/话题保留现有清空与话题节奏；封面区改 `Humanizer.hover`；BGM「使用」按钮先 hover 卡片显形再点，仍 hidden 则硬失败（不得回退 JS 点击）；声明、合集、商品弹窗等可见点击全量改。

规格依据：§3.4、§4。波次：W3（热点置顶）。

Blocked by: 01

Status: ready-for-agent

- [x] `_native_click` 函数与全部调用点删除；无合成事件重放
- [x] 带 `MAYBE_DISPATCHED` 的异常不再二次派发
- [x] 2FA 路径的 force 保留并带三字段标记；其 JS 三级兜底删除
- [x] 封面与 BGM 的 hover 路径成立；BGM 仍 hidden → `ElementUnusable`，不回退
- [x] 定时时间先全选再逐字；地点/配乐搜索逐字 + 有界等待 + 精确候选
- [x] `tests/test_douyin_humanize.py` 三条
- [x] 抖音入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [x] `CHANGELOG.md` 的 W3 小节加本平台一行

## Answer

删除 `_native_click`（连同合成 pointer/mouse 重放）与全部 8 个调用点，统一改 `Humanizer.click`；每条「点后校验状态 → 重试 / 降级 / Esc」循环原样保留，`click_dispatched="maybe"` 直接上抛、永不补点。标题/定时/商品短标题/商品链接/配乐走 `sel` 全选覆盖后逐字，描述保留 `Control+KeyA`+`Delete` 的 `seq`，话题逐字 ` #tag` 后按 Space；地点/商品链接/配乐搜索改为逐字 + 有界等待 + 精确候选。BGM「使用」先 `hover` 卡片显形；仍 hidden 抛 `ElementUnusableError(hidden-after-hover)`，不再 `el.click`。2FA 两处 `force=True` 保留并带 `humanize-impossible` + `native-click: verify` 标记，短信 `fill` 带 `native-fill`，JS 三级兜底与 `count()==0` 死分支删除；`HUMANIZE=0` 与 maybe 不二次派发均有离线用例。门 A–E 在 `uploader/douyin_uploader/` 上通过；真机未验证（无抖音真机环境）。

