# 10 — AdsPower API 版本与端点选择

Status: resolved
Type: grilling
Blocked by: 01
Assignee: LukeChen

## Question

在 research ticket 01 的事实表基础上，决定 AdsPower client 采用哪套 API 版本与端点，作为 ticket 03/04/08 的共同前提。需要确认：

1. **版本策略**：只做 V2；V2 + V1 fallback；还是只做 V1。research 01 推荐 V2，理由是官方 Playwright 示例即 V2、JSON body 更适合 `launch_args`、start/stop/status 对称、`profile_id` 与 `--profile-id` 对齐。
2. **老客户端处理**：如果 V2 不存在（旧版 AdsPower），是启动前用 `/status` 探活并映射成「请升级 AdsPower」退出 `1`，还是静默回退 V1。charter 倾向不做双栈。
3. **端点集合**：
   - 启动：`POST /api/v2/browser-profile/start`
   - 停止：`POST /api/v2/browser-profile/stop`
   - 状态：`GET /api/v2/browser-profile/active?profile_id=...`
   - 健康检查：`GET /status`
   是否全部采用，还是保留 V1 的 `GET /api/v1/browser/active` 作为 fallback。
4. **字段命名**：V2 用 `profile_id`（不是 `user_id`）；CLI `--profile-id` 是否直接透传，文档是否明确「AdsPower 的 Profile ID 即 V2 profile_id」。
5. **参数类型**：V2 的 `headless` / `last_opened_tabs` / `proxy_detection` / `cdp_mask` / `delete_cache` 都是字符串 `"0"/"1"`；`launch_args` 是 list。是否在 client 内统一转换，避免调用方传错类型。
6. **安全默认值**：start 固定 `proxy_detection=0`、`last_opened_tabs=0`、`delete_cache=0`、`cdp_mask=1`；是否允许用户覆盖（charter 倾向不暴露危险参数）。
7. **响应解析**：以 `code == 0` 为成功；`data.ws.puppeteer` 必填；V2 stop 成功响应没有 `data`；`active` 的 `data.status` 为 `Active` / `Inactive`。缺失字段视为协议漂移，退出 `1`。
8. **错误分层**：同时处理 HTTP 非 2xx、超时、非法 JSON、`code != 0`；不要把 `code != 0` 当成 HTTP 错误，也不要把 HTTP 200 当成业务成功。
9. **V1 的地位**：如果决定只做 V2，是否把 V1 明确写进 Out of scope；如果保留 fallback，触发条件是什么（404？连接失败？特定 error code？）。
10. **最低客户端版本**：官方未给 V2 最低版本，文档是否只要求「最新 patch」；是否需要运行时探测版本并拒绝过旧客户端。
11. **对 ticket 03 的影响**：`AdspowerClient` 是否只实现 V2 四个原语；`connect_url` 是否直接取 `data.ws.puppeteer`。
12. **对 ticket 04 的影响**：预检、start、stop 的端点是否固定；`active` 的 `Active` 判定是否作为所有权依据。

## Context

- Research 01：`.scratch/adspower-browser-mode/research/01-adspower-local-api.md` 的 §3（V1 vs V2）、§4（启动）、§5（已运行）、§6（停止）、§12（对 02/03/04 的影响）。
- 已核对官方文档（2026-11-06）：
  - V2 start `POST /api/v2/browser-profile/start`，JSON body；
  - V2 stop `POST /api/v2/browser-profile/stop`；
  - V2 active `GET /api/v2/browser-profile/active`，`data.status` 为 `Active` / `Inactive`；
  - V2 默认 `proxy_detection=1`、`last_opened_tabs=1`，必须显式关闭；
  - V1 状态路径是 `/api/v1/browser/active`（不是 `/status`）。
- charter：不做无 key 安装；不做 Profile 管理；真实 smoke 外部阻塞。

## Answer

决议日期：2026-11-09（HITL grilling，逐题确认）。一句话结论：**只实现 AdsPower V2；`AdspowerClient` 的公开原语与 `MultiloginClient` 同构（probe / start / stop / status），start 直接返回 `ws.puppeteer`。**

### 1. 版本策略：只做 V2

- 只实现 V2 端点，不做 V1 fallback、不做双栈、不做运行时版本探测。
- V1（`/api/v1/browser/start|stop|active`）明确写入 map 的 Out of scope；以后要支持老客户端是新的 effort。
- V2 端点集合（全部采用，无替代）：

  | 能力 | 端点 | 方法 | 载荷 |
  | --- | --- | --- | --- |
  | 探活 | `/status` | `GET` | 无 |
  | 启动 | `/api/v2/browser-profile/start` | `POST` | JSON `{"profile_id": "...", ...}` |
  | 停止 | `/api/v2/browser-profile/stop` | `POST` | JSON `{"profile_id": "..."}` |
  | 状态 | `/api/v2/browser-profile/active?profile_id=...` | `GET` | query |

- 不做“V2 不存在就静默回退 V1”：老客户端在 start/status 上表现为 404，映射为「AdsPower 版本过旧，请升级到支持 V2 的最新 patch（或确认 Local API 已开启）」，退出 `1`。

### 2. 探活：与 MLX 同构，但带 key

- `probe()` → `GET {ADSPOWER_API_BASE}/status`，`timeout=3s`（对齐 MLX 的 `PROBE_TIMEOUT_SECONDS`），在 `start` 之前调用。
- 与 MLX 的唯一实现差异：MLX 的 probe 不鉴权，AdsPower 的 probe **带 `Authorization: Bearer <key>`**（本模式必有 key；官方未定义 `/status` 是否要求鉴权，带 key 对两种安装都安全，且能让 401/403 正确落到“鉴权失败”而不是误报“不可达”）。
- 失败分类：
  - 连接被拒 / DNS / 超时 → 固定文案（沿用 ticket 02 §6）：`无法连接 AdsPower Local API（{base}）。\n请确认：1) AdsPower 桌面应用已启动；2) 本地 API 已开启；3) CLI 与 AdsPower 在同一台机器且端口未被占用。` → 退出 `1`
  - HTTP 401/403 → 提示检查 `ADSPOWER_API_KEY` 与账号 Local API 权限 → `1`
  - 其它非 2xx → `探活 AdsPower Local API 失败：HTTP <status>…` → `1`
- 探活通过后才 start；probe 失败绝不 start、绝不 stop。

### 3. 公开原语：与 `MultiloginClient` 同名同形

| 职责 | `MultiloginClient`（现状） | `AdspowerClient`（本决议） |
| --- | --- | --- |
| 探活 | `probe() -> None` | `probe() -> None` |
| 启动 | `start(folder_id, profile_id, headless) -> port` | `start(profile_id, headless) -> ws_url` |
| 停止 | `stop(profile_id) -> None` | `stop(profile_id) -> None` |
| 状态 | `status(profile_id) -> str` | `status(profile_id) -> str`（内部打 V2 `/active`，**方法名仍叫 `status`**） |

- 方法名统一为 `probe/start/stop/status`，目的是让 ticket 03 能用一个结构化 Protocol 同时覆盖两个 client，不需要适配器。
- `status()` **只**用于 CDP 连接失败后的诊断信息（与 MLX `utils/browser_session.py:226-239` 的用法一致），**不做 start 前预检**（ticket 02 已裁决）。
- `start` 返回完整 CDP endpoint 字符串（`data.ws.puppeteer`），不返回 port；由 session 层直接 `connect_over_cdp(ws_url)`。

### 4. start 参数与安全默认值

- 签名 `start(profile_id: str, headless: bool) -> str`；除 `headless` 外不暴露任何启动参数。
- 请求体固定：

  ```json
  {
    "profile_id": "<profile_id>",
    "headless": "1" | "0",
    "last_opened_tabs": "0",
    "proxy_detection": "0",
    "delete_cache": "0",
    "cdp_mask": "1"
  }
  ```

  - `last_opened_tabs=0` / `proxy_detection=0`：否则官方默认会恢复历史页并打开 IP 检测页，上传逻辑会继承一个非 `about:blank` 的初始页。
  - `delete_cache=0`：置 1 可能清掉 Profile 登录态，违背“复用登录态”的目标。
  - `cdp_mask=1`：官方默认，与 Playwright `connect_over_cdp` 兼容。
- 不暴露 `launch_args`、`password_filling`、`password_saving`、`device_scale`；这些不是本 effort 的需求面。
- 所有 `"0"/"1"` 的字符串转换在 client 内部完成；调用方只传 `bool`，避免把 `False` 序列化成 `false`。

### 5. 响应契约

- 通用 envelope：`{"code": <int>, "data": <object|absent>, "msg": <str>}`。
- `start`：要求 HTTP 2xx **且** `code == 0` **且** `data.ws.puppeteer` 为非空字符串；返回该字符串。缺字段 = 协议漂移 → `RuntimeError` → `1`（此时本次已启动，session 层负责 stop）。
- `stop`：要求 HTTP 2xx **且** `code == 0`；V2 成功响应**没有 `data`**，不得要求 `data` 存在。
- `status`：读 `data.status`，值为 `"Active"` / `"Inactive"`；`data` 缺失或字段异常时返回 `"unknown"`（诊断用途，不因为诊断失败而让会话失败）；传输/HTTP 错误仍抛 `RuntimeError`，由 session 层降级为“查询失败”。
- 非法 JSON / 缺 `code` → 协议漂移 `RuntimeError` → `1`。

### 6. 错误分层

- 沿用 MLX 的单一 `RuntimeError` 风格，消息里显式区分来源：
  - HTTP 层：`<动作>失败：HTTP <status>；code=<code>；msg=<msg>`；无 msg 时截取响应体前 500 字符。
  - 业务层（HTTP 2xx 但 `code != 0`）：`<动作>失败：code=<code>；msg=<msg>`。
  - 协议层（非法 JSON / 缺字段）：`<动作>失败：响应协议异常（缺少 <字段>）`。
- 唯一例外是 ticket 02 §5 已定的 `RateLimitedError`（`utils/errors.py`）：**HTTP 429 抛 `RateLimitedError`**，由 `sau_cli.main()` 映射为退出码 `11`；其余全部 `RuntimeError` → `1`。
- 异常消息、`repr`、日志中绝不出现 API key；`AdspowerClient.__repr__` 与 MLX 一致输出 `token=<redacted>`。
- `code != 0` 不当作 HTTP 错误，HTTP 200 不当作业务成功（两层都过才算成功）。

### 7. 限流与重试

- client 层**不做任何重试**（与 MLX 一致）。
- 只有 HTTP 429 → `RateLimitedError` → 退出 `11`；HTTP 200 + 业务 code 表示限流的情况官方未定义，暂按 `1` 处理，待 ticket 09 的 smoke 拿到真实形状再扩展。
- stop 阶段的 429 只 warning，不改变已成功结果的退出码（ticket 02 §5 / ticket 04）。
- 429 的传输层判定只看 HTTP 状态码；不猜 msg 关键词。

### 8. stop 语义

- `stop()` 仅在 HTTP 2xx 且 `code == 0` 时返回成功；其余（含疑似“已经停止”）一律抛 `RuntimeError`。
- 不预置“已停止文案”特例：重复 stop 的响应官方未定义，等 ticket 09 实测后再决定是否加特例；当前幂等性由 session 层“只 warning”兑现。
- stop 不做重试。

### 9. Profile 标识

- CLI `--profile-id`（strip 后非空）**直接透传**为 V2 `profile_id`；不引入 `user_id` 作为表面命名。
- 文档必须写明「AdsPower 的 Profile ID 即 V2 `profile_id`」，避免用户去找额外的 `user_id`。
- Profile 不存在（`msg` 含 `user account does not exist`）→ `1`，保留原始 `msg`（ticket 02 已定）。

### 10. 对 ticket 03 / 04 的输入

- **03（provider 接缝）**：`AdspowerClient` 实现 `probe/start/stop/status` 四个同步方法，`start` 返回 `ws_url`；MLX 的 `start` 返回 `port`。两边的“可连接端点”形态不同，03 决定是让 client 统一返回 endpoint（AdsPower 直接返回、MLX 由 port 拼 `http://127.0.0.1:{port}`），还是让 layer 知道 provider 类型。本 ticket 不预设。
- **04（生命周期）**：`start` 成功即本次会话 owned，结束时 stop；`start` 失败绝不 stop；`status` 只填诊断。`contexts` 数量校验、CDP 连接重试（3 次 / 2s / 4s）、`asyncio.shield` 的 stop 全部沿用 MLX 现成实现。

### 11. 留给 ticket 09（真实 smoke）验证的未知

- `/status` 是否要求鉴权、返回体是否含版本字段。
- V2 路径在旧客户端上的真实状态码（404？还是 200 + `code != 0`）。
- 429 的真实形状（HTTP 429 还是 200 + code）与是否带 `Retry-After`。
- `active` 在 Inactive / 多设备模式下的 `data` 形状。
- 重复 stop 的 `code` / `msg`。
