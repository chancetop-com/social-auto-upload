# 10 — 抖音：删除 `_native_click`，全流接入人类化

**What to build:** 删掉平台内手写坐标点击 `_native_click`（含合成 pointer 事件重放），8 个调用点改 `Humanizer.click`，保留既有「点后校验弹窗/弹层状态 → 重试 / 降级 / Esc」循环与全部状态谓词。描述/话题保留现有清空与话题节奏；封面区改 `Humanizer.hover`；BGM「使用」按钮先 hover 卡片显形再点，仍 hidden 则硬失败（不得回退 JS 点击）；声明、合集、商品弹窗等可见点击全量改。

规格依据：§3.4、§4。波次：W3（热点置顶）。

Blocked by: 01

Status: ready-for-agent

- [ ] `_native_click` 函数与全部调用点删除；无合成事件重放
- [ ] 带 `MAYBE_DISPATCHED` 的异常不再二次派发
- [ ] 2FA 路径的 force 保留并带三字段标记；其 JS 三级兜底删除
- [ ] 封面与 BGM 的 hover 路径成立；BGM 仍 hidden → `ElementUnusable`，不回退
- [ ] 定时时间先全选再逐字；地点/配乐搜索逐字 + 有界等待 + 精确候选
- [ ] `tests/test_douyin_humanize.py` 三条
- [ ] 抖音入册门 A–E 并通过；`HUMANIZE=0` 用例同绿
- [ ] `CHANGELOG.md` 的 W3 小节加本平台一行

