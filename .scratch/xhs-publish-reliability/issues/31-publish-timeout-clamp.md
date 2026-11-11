# 31 — 预算 clamp：小红书全链路无裸超时

**What to build:** 一次小红书发布从打开发布页到等结果，共用同一个 15 分钟 deadline。任何一处等待都按剩余预算收缩；预算在点击前耗尽就确定未发布（`1`），点击后耗尽就是结果未知（`9`）。不会再出现"页面卡住 → 每次等待各等 30 秒 → 总耗时远超 15 分钟"。

**Blocked by:** 28（需要虚拟时钟断言剩余预算收缩）.

Status: resolved

- [x] 发布链路内零裸 `timeout=<数字>` 字面量（含导航、`wait_for_url`、`wait_for_selector`、元素 `wait_for`、上传等待与观察窗）
- [x] 每次等待前先查预算；`clamp` 返回 ≤0 时按点击前超时处理
- [x] 点击前预算耗尽 → `1`，文案为"发布超时（15 分钟）：尚未点击发布，未发布任何内容"
- [x] 点击后预算耗尽 → `9`（`PublishResultUnknownError`）
- [x] 这两个出口只能由预算模块产生；业务代码不得自定义"处理超时"
- [x] 不新增错误类、不新增退出码；单次等待用尽由该环节按普通失败处理
- [x] `--not-before` 顺延后剩余预算正确（顺延部分不计入 15 分钟）
- [x] 登录/会话预检不计入 15 分钟预算
- [x] 预算模块既有 10 条用例只加不改，全绿

## Comments

- 实现：`uploader/xiaohongshu_uploader/main.py` 新增承担单一时间来源的两个 helper
  `_wait_ms()` / `_sleep()` 与固定静置 `_settle()`；导航、URL 守卫、上传输入、
  话题/声明/封面等待、点击发布与观察窗全部经 `PublishTimeoutBudget` 收缩。
  新增 `tests/test_xhs_budget.py`（11 条，含静态断言与虚拟时钟），未改动
  `uploader/publish_timeout.py` 与既有 10 条预算用例。
- 真机未验证（无真机环境）：15 分钟总预算在真实"页面卡住"场景下的端到端耗时、
  收缩后的 Playwright timeout 在慢网络下的实际表现、点击后预算耗尽落到真实
  `/publish/publish` 页面的退出码 9 —— 均需真机观察，离线仅有虚拟时钟断言。
