# 10 — 实测 GoLogin 桌面应用的本地 HTTP API（36912）

Status: resolved
Type: task
Blocked by: —
Assignee: LukeChen

## Question

第三方资料称 GoLogin 桌面应用在本机暴露一个 HTTP API（`http://127.0.0.1:36912`），可启动 Profile 并返回 CDP `wsUrl`。**但没有任何 GoLogin 一手文档，且两份第三方资料端点名不一致**：

- `POST /browser/start`，body `{"profileId": "<id>"}` → `{"status":"success","wsUrl":"ws://localhost:<port>/devtools/browser/<guid>"}`（antidetectreview，2026-05）
- `POST /browser/start-profile`，body `{"profileId": "<id>", "sync": false}`（mmo4me 论坛）

需要用真实安装把契约钉死，供 spec 直接引用。若不存在，也要留下 `ECONNREFUSED` 的证据。

## Method（HITL：需要人在装了 GoLogin 的机器上操作）

1. 安装并登录 GoLogin 桌面应用；确认应用**正在运行**。
2. 在应用设置里找 API / 自动化相关开关与端口显示，截图或记下原文。
3. 创建或导入一个 Profile，记下 profile id（24 位 hex）。
4. 依次执行并记录 **HTTP 状态码 + 完整响应体 + 耗时**：

```bash
# 0. 端口是否存在
nc -z 127.0.0.1 36912 && echo open || echo closed

# 1. 根与健康检查
curl -sS -m 3 -i http://127.0.0.1:36912/
curl -sS -m 3 -i http://127.0.0.1:36912/health

# 2. 两种启动端点（分别试）
curl -sS -m 10 -i -X POST http://127.0.0.1:36912/browser/start \
  -H 'Content-Type: application/json' \
  -d '{"profileId":"<PROFILE_ID>"}'

curl -sS -m 10 -i -X POST http://127.0.0.1:36912/browser/start-profile \
  -H 'Content-Type: application/json' \
  -d '{"profileId":"<PROFILE_ID>","sync":false}'

# 3. 停止端点（分别试）
curl -sS -m 10 -i -X POST http://127.0.0.1:36912/browser/stop \
  -H 'Content-Type: application/json' -d '{"profileId":"<PROFILE_ID>"}'
curl -sS -m 10 -i -X POST http://127.0.0.1:36912/browser/stop-profile \
  -H 'Content-Type: application/json' -d '{"profileId":"<PROFILE_ID>"}'

# 4. 状态/版本
curl -sS -m 3 -i http://127.0.0.1:36912/browser/version
curl -sS -m 3 -i "http://127.0.0.1:36912/browser/status?profileId=<PROFILE_ID>"

# 5. 若返回 wsUrl，验证能否被 Playwright 接管
#    （Python: playwright.chromium.connect_over_cdp(wsUrl)，读 browser.contexts 数量）
```

5. 额外确认：
   - 启动时应用是「最小化/关闭窗口」还是「必须前台」？
   - 是否需要 `sync`、`headless`、`extra_params` 之类字段？
   - Profile 已运行时重复 start 的响应。
   - 停止后 Cookie 是否写回 Profile。
   - 端口是否可配置；应用升级后是否变过。
   - 返回的 `wsUrl` 里 `localhost` 与 `127.0.0.1` 是否都可连。

## Answer

**存在。** 没有走人工 curl，而是直接静态分析本机已安装的 `/Applications/Gologin.app`：其 `app.asar` 内含未压缩的
`src/electron/server/src/` 服务端代码。完整证据见 [`research/01-gologin-api-surfaces.md` §10](../research/01-gologin-api-surfaces.md)。

- **端口**：默认 `36912`，被占用时 `++port` 递增，直到空闲；无固定端口。发现方式 = 从 36912 起逐个 `GET /service/check-server`。
- **启动**：`POST /browser/start-profile`，body `{profileId, sync: true}` → `200 {status:"success", wsUrl:"ws://127.0.0.1:<debugPort>/devtools/browser/<guid>"}`。
  **`sync` 必须为 `true`**；否则不分配调试端口，`wsUrl` 是空串（两份第三方示例都错在这里）。
- **停止**：`POST /browser/stop-profile`，body `{profileId}` → `204`；内部 `killProfile(profileId)`。
- **健康**：`GET /service/check-server` → `{status:true}`。
- **其余**：`/service/credentials`（应用自用）、`/cookies/:id`（走云端 API）、`/close/:id`（macOS SIGTERM）、`/session/ready`、`/timer/update/:id`。
- **鉴权**：本地调用无鉴权；CORS 放开 `origin:/.*`。
- **状态**：没有 status 路由 → provider 的 `status()` 只能返回 `"unknown"`。
- **headless**：本地 API 无此参数，启动的是应用正常（有头）的 Orbita。

## Caveats

- 该 API **没有任何一手文档**，随桌面应用发版；spec 必须写明「按应用版本回归 + 探测失败时给固定排查文案」。
- 仍建议实现阶段做一次 live smoke（`sync:true` 拿到 wsUrl → `connect_over_cdp` → `contexts` 数量），但契约本身已由源码确定。

## Context

- 这是 [02 — 运行时取舍与 SDK 边界](./02-runtime-scope-and-sdk-boundary.md) 的前置证据。
- 若验证失败，本地运行时只剩「Python SDK 启动器」或「自己复现 Orbita」两条路。
- 不要安装 SDK、不要改仓库代码；只做探测与记录。
