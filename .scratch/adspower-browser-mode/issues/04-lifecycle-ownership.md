# 04 — AdsPower Profile 生命周期与所有权

Status: resolved
Type: grilling
Blocked by: 01, 10
Assignee: LukeChen

## Question

在 AdsPower Local API 的真实行为基础上，定义一次 AdsPower 会话的生命周期、所有权与失败边界。需要确认：

1. 前置探活：是否每次 start 前调用 `/api/v1/browser/status` 或 `/api/v1/version`；失败如何映射。
2. 所有权：AdsPower 的 `start` 对已运行 Profile 返回什么；如果返回既有 `ws`，CLI 是 attach（不 stop）还是拒绝（退出 1）；如果返回错误，是否绝不 stop。
3. “谁启动谁停止”：是否只在 `start` 明确由本次调用创建会话时才 stop；已在运行、非本次启动的 Profile 如何识别与处理。
4. 启动成功但 CDP 连接失败：是否 stop；重试次数、超时、退避；错误里是否附带 status。
5. `contexts` 校验：AdsPower 是否稳定 1 个 context；不为 1 时 fail-fast 还是选第一个。
6. 断开与停止顺序：`browser.close()` 只断开 CDP，随后单独 stop；stop 失败只 warning，不影响已上传结果（退出 0）。
7. 取消/中断：`KeyboardInterrupt` / `CancelledError` 时 stop 是否仍执行；是否用 `asyncio.shield`。
8. 幂等：重复 stop、已停止、Profile 被关闭的响应；哪些可忽略。
9. 并发/锁：Profile 被占用、并发启动同一 Profile 时由谁负责；库内是否加锁（charter 倾向不加）。
10. headless：`--headless` 如何映射到 AdsPower `headless=1`；headed 时是否必须。
11. 页面状态：`open_tabs` / `ip_tab` 是否需要在 start 时固定，避免启动页干扰；是否先关闭多余页面。
12. 日志：记录 `profile_id` / endpoint / 耗时，但不记录 API key；失败信息保留 AdsPower `code` / `msg`。
13. 退出码：上述失败分别落 `1` / `2` / `10` 的哪一类。

## Context

- **ticket 02 已裁决（优先于 research 01 §5.4 / §12.3 的预检建议）**：不做 start 前 `active` 预检；与 MLX 一致直接 start。start 成功即视为本次会话 owned，结束时 stop；start 失败绝不 stop；start 成功但 CDP / `data.ws.puppeteer` 缺失仍 stop。429 统一映射退出码 `11`，stop 阶段的 429 只 warning、不改变已成功结果的退出码。本 ticket 不再重新引入“已运行则拒绝”的预检。
- 依赖 ticket 01 的事实表；如果 01 对“已运行”无定论，本 ticket 按上述已定策略继续，并标注置信度。
- 参考 MLX 的生命周期决策：`.scratch/multilogin-browser-mode/issues/05-profile-lifecycle-edges.md`。
- charter：调度 App 负责并发与人工登录回流；CLI 不自动登录。
- Research 01 §5.4 / §12.3：建议 start 前预检 `active`；`Active` → 拒绝退出 `1`，不 attach、不 stop；`Inactive` → start 并标记 owned。start 失败绝不 stop；start 成功但 CDP 失败 → stop。
- Research 01 §4.6：V2 start 必须显式 `proxy_detection=0`、`last_opened_tabs=0`；`delete_cache=0`；`cdp_mask` 保持默认 1。
- V1 vs V2 端点选择由 ticket 10 决定；本票只定义与端点无关的生命周期语义。
- start 成功但 `data.ws.puppeteer` 缺失 → 视为本次已启动并 stop，退出 1。

## Answer

决议日期：2026-11-09（HITL grilling）。一句话结论：**沿用 02/03/10 已定的统一模板与所有权规则；只新增一条内部信号 `StartIncompleteError`，用于“服务端已启动但响应坏”时先 stop 再失败；其余边界全部与 MLX 对齐。**

### 0. 调用模板

与 ticket 03 §3 一致，顺序固定：

```
probe → start → connect_over_cdp → contexts == 1 → yield → disconnect → shield(stop)
```

`probe` 与 `start` 在 `try` 之外；只有“确认 owned”后才进入必须 stop 的区域。唯一例外见 §3。

### 1. 前置探活

- `provider.probe()` → `GET {base}/status`，`timeout=3s`，带 `Authorization: Bearer <key>`（ticket 10 §2）。
- **不做 `active` 预检**（ticket 02 已裁决，优先于 research 01 §5.4 / §12.3）。
- 探活失败绝不 start、绝不 stop：
  - 连接被拒 / DNS / 超时 → ticket 02 §6 固定“无法连接”文案 → `1`
  - HTTP 401/403 → 提示检查 `ADSPOWER_API_KEY` 与 Local API 权限 → `1`
  - HTTP 429 → `RateLimitedError` → `11`
  - 其它非 2xx → `探活 AdsPower Local API 失败：HTTP <status>…` → `1`

### 2. 所有权与“谁启动谁停止”

- `start` 返回 HTTP 2xx + `code == 0` + 非空 `data.ws.puppeteer` → 本次会话 **owned**，退出时必然 stop。
- `start` 失败（传输错误、超时、非 2xx、`code != 0`、401/403/404/429）→ 一律 **不 stop**。
- 已运行 Profile：不预检；若服务端返回成功（含既有 ws），按 ticket 02 “start 成功即本次 owned”处理，退出时 stop。该响应形状仍是 ticket 09 的未知项。
- 并发由调度 App 串行保证；库内不加锁、不做占用检测。

### 3. start 结果分类与 `StartIncompleteError`（Q1）

`AdspowerClient.start` 的判定：

| 服务端结果 | client 行为 | 会话层行为 | 退出码 |
| --- | --- | --- | --- |
| HTTP 2xx + `code == 0` + ws 非空 | 返回 ws | 正常连接，结束后 stop | `0` / 业务码 |
| HTTP 2xx + `code == 0` + ws 缺失/空 | 抛 `StartIncompleteError` | **best-effort stop**（失败仅 warning）→ 原样抛出 | `1` |
| HTTP 2xx + 非法 JSON / 缺 `code` | 抛 `StartIncompleteError` | 同上（可能已启动，宁可 stop） | `1` |
| HTTP 非 2xx，或 `code != 0` | 抛 `RuntimeError`（429 → `RateLimitedError`） | **不 stop** | `1` / `11` |
| 传输失败 / 超时 | 抛 `RuntimeError` | **不 stop**（见 §14） | `1` |

- `StartIncompleteError(RuntimeError)` 新增于 `utils/errors.py`，只作**内部生命周期信号**，不是新的用户可见错误类别，`sau_cli` 不单独映射。
- 实现形状：`_managed_session` 单独 `except StartIncompleteError:` → 调 stop（warning-only）→ `raise`；其它 start 异常不进入该分支。
- 这是对 ticket 03 §6“错误面只加 `RateLimitedError`”的受控扩展；MLX 的缺失 `data.port` 行为不变（仍抛普通 `RuntimeError`、不 stop），因此不影响本地/MLX 可观察行为。

### 4. 启动成功但 CDP 连接失败

- 3 次尝试，每次 `timeout=10s`，退避 2s / 4s（沿用 MLX `CONNECT_TIMEOUT_MS` / `CONNECT_ATTEMPTS` / `CONNECT_BACKOFF_SECONDS`）。
- 最终失败后调用一次 `provider.status()` 补诊断；`status` 自身失败（含 429）只写“查询失败（…）”，不改变原错误。
- 错误文案 provider 中立，带 `mode`、`profile_id`、endpoint 的 `host:port`、尝试次数与状态。
- 无论连接失败原因，finally 都 stop（此时已确认 owned）→ 退出 `1`。

### 5. `contexts` 校验

- `len(browser.contexts) != 1` → 立即 `RuntimeError`（文案带 mode、profile_id、实际数量），**不选第一个、不尝试修复**。
- 随后 finally 照常 stop → `1`。

### 6. 断开与停止顺序

1. `await browser.close()` 仅断开 CDP；失败只 WARNING，注明“已上传结果不受影响”。
2. 单独 `await asyncio.shield(asyncio.to_thread(provider.stop))`。
3. stop 失败只 WARNING，注明“Profile 可能仍在运行，需调度侧清理”；**不覆盖原异常、不改变退出码**（主操作成功则仍 `0`）。

### 7. 取消 / 中断

- 只要进入 `try`（即确认 owned），普通异常、`KeyboardInterrupt`、`asyncio.CancelledError` 都走 finally。
- stop 用 `asyncio.shield` 保证请求已发出；`CancelledError` 在断开与 stop 后重新抛出。
- `KeyboardInterrupt` 保留 Python 默认 `130`；finally 必须先执行 stop。
- start 阶段被取消/中断属于“start 未确认”，按 §2 不 stop。

### 8. 幂等

- stop 仅在 HTTP 2xx 且 `code == 0` 时算成功；其余一律抛 `RuntimeError`。
- **暂不加“已经停止”特例**（ticket 10 §8）；重复 stop 的真实响应交 ticket 09 验证，之后如需再加。
- stop 不重试；幂等性由会话层“只 warning”兑现。

### 9. 并发 / 锁

- 库内不加锁，不做 Profile 占用检测；同一 Profile 的并发由调度 App 负责。
- start 撞锁/被占用 → 服务端错误原样保留 → `1`；绝不自动 stop 别人的 Profile。

### 10. headless

- `--headless` 默认 `True`，`--headed` → `False`；provider 只接收 `bool`。
- client 内部编码为 V2 字符串 `"1"` / `"0"`；不把 `False` 序列化成 `false`。
- headless 模式仍走同一生命周期；不做“headed 才能上传”之类的额外限制。

### 11. 页面状态

- start 请求体固定：`last_opened_tabs=0`、`proxy_detection=0`、`delete_cache=0`、`cdp_mask=1`（ticket 10 §4）。
- 不主动关闭/切换页面；上传器自己负责导航。
- `contexts` 恒按 1 校验（§5）；真实数量交 ticket 09。

### 12. 日志

完全镜像 MLX：

| 事件 | 级别 | 内容 |
| --- | --- | --- |
| start 成功 | INFO | `AdsPower Profile 已启动：profile_id={} endpoint={host}:{port}` |
| stop 开始 | INFO | `正在停止 AdsPower Profile：profile_id={}` |
| 断开 CDP 失败 | WARNING | 原始异常；注明“已上传结果不受影响” |
| stop 失败 | WARNING | 原始异常；注明“Profile 可能仍在运行，需调度侧清理” |
| 失败 | stderr（`sau_cli`） | 保留 HTTP status / `code` / `msg`；不含 key |

- endpoint 只打 `host:port`，**不打完整 ws 路径**。
- 不记耗时（与 MLX 一致）。
- `Authorization` 与 key 永不记录，连截断也不打。
- `--debug` 不改变生命周期日志，也不传给 AdsPower。

### 13. 退出码

全量沿用 ticket 02 §5，本 ticket 只确认归位：

| 场景 | 退出码 |
| --- | --- |
| 上传已提交 / check 已登录 / stop 失败但主操作成功 | `0` |
| probe 失败、key 无效、Profile 不存在/被占用、CDP 连不上、`StartIncompleteError`、上传失败 | `1` |
| 缺 `--profile-id`、`ADSPOWER_API_BASE` 非法 | `2` |
| 发布结果未知 | `9` |
| 登录页/验证码/2FA | `10` |
| probe/start 阶段 HTTP 429 | `11` |
| `Ctrl-C` | `130` |

- stop 阶段 429 → warning，退出码保持主操作结果（通常 `0`）。

### 14. 超时（Q2）

`utils/adspower.py` 常量，不做环境变量覆盖：

| 原语 | 超时 |
| --- | --- |
| `probe` | 3s |
| `start` | 30s |
| `stop` | 30s |
| `status` | 30s |

对齐 MLX 的 `PROBE_TIMEOUT_SECONDS=3` / `REQUEST_TIMEOUT_SECONDS=30`，不按端点分级。

### 15. start 传输歧义（Q3）

- 30s 超时、连接重置等“请求可能已到达服务端”的失败：**不 stop**，保留原始异常 → `1`。
- 只有 HTTP 层确认 2xx（`StartIncompleteError`）才认定为“已启动”，才做 best-effort stop。
- 残留风险：极少数超时可能留下运行中的 Profile，由调度层清理；写入 ticket 09 的 smoke 观察项。

### 留给 ticket 09 的未知

1. 已运行 Profile 的 start 返回形状：成功 + 既有 ws，还是错误。
2. 重复 stop / 已停止的 `code` / `msg`，是否值得加特例。
3. 429 的真实形状（HTTP 429 还是 200 + code）与 `Retry-After`。
4. `contexts` 是否恒为 1（含 `last_opened_tabs=0`）。
5. 冷启动是否可能超过 30s；超时后不 stop 是否真的留下 Profile。
