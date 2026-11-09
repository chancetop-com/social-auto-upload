# 12 — AdsPower V2 client 与共享错误类型

Status: resolved
Type: task
Blocked by: 11（provider 协议由 11 提供）
Assignee: —

## What to build

交付一个可离线验证的 AdsPower Local API V2 客户端与 provider，不接 CLI：

- `AdspowerClient(key, base, http_get=None, http_post=None)`：`probe` / `start` / `stop` / `status` 四原语，只做 V2。
- `start` 固定 body：`profile_id`、`headless`（`"1"/"0"`）、`last_opened_tabs="0"`、`proxy_detection="0"`、`delete_cache="0"`、`cdp_mask="1"`；原样返回 `data.ws.puppeteer`。
- envelope 解析、超时（probe 3s，其余 30s）、不重试；HTTP 429 抛 `RateLimitedError`。
- HTTP 2xx + `code == 0` 但 ws 缺失/响应非法时抛 `StartIncompleteError`；非 2xx、`code != 0`、传输失败抛 `RuntimeError`。
- `AdspowerProvider` 组合 target + client，`start()` 原样返回 ws URL；`__repr__` 与所有异常不含 key。
- `utils/errors.py` 新增 `RateLimitedError` / `StartIncompleteError`；MLX client 的 429 改抛共享 `RateLimitedError`。
- 新增 `tests/test_adspower_client.py` 与共享 fake；本 ticket 不改变 CLI 退出码映射。

## Acceptance criteria

- [ ] 探活打 `GET /status`、带 Bearer、3s 超时；连不上给出 AdsPower 桌面应用/Local API/同机端口提示。
- [ ] start/stop 方法、URL、JSON body 与 Authorization 头逐项被测试锁住。
- [ ] `headless=True/False` 编码为 `"1"/"0"`；其余固定字段不可被调用方覆盖。
- [ ] 401/403 错误提示检查 `ADSPOWER_API_KEY` 与 Local API 权限；429 抛 `RateLimitedError` 且不重试、不 sleep。
- [ ] start 的非法 JSON / 缺 `code` / 缺 ws 均抛 `StartIncompleteError`，且不自动 stop。
- [ ] key 不出现在 `repr`、异常文本或测试输出中。

## Context

- 规格：§5.4（client 契约）、§5.5（错误分层）、§6.4（幂等）、§9（安全）。
- 设计裁决：ticket 04（`StartIncompleteError`）、ticket 10（只做 V2、四原语、429）。
- 现有 MLX client 是结构参照：`utils/multilogin.py`。

## Answer

已实现并合并（merge `779066b`）。新增 `utils/adspower.py`（`AdspowerTarget` / `AdspowerClient` / `AdspowerProvider`）与 `RateLimitedError` / `StartIncompleteError`；V2 端点、固定 start body、envelope、3s/30s 超时、429 不重试、ws 原样返回与 key 脱敏均由 `tests/test_adspower_client.py` 锁定。
