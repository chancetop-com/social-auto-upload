# 01 — AdsPower Local API 契约与边界行为

Status: resolved
Type: research
Blocked by: —
Assignee: —

## Question

在**只有官方文档、当前机器未安装 AdsPower** 的前提下，把 AdsPower Local API 的准确契约整理成事实表，供设计直接引用。需要回答：

1. **地址与传输**
   - `http://local.adspower.net:50325`、`http://localhost:50325`、`http://127.0.0.1:50325` 三者关系；是否等价。
   - `local_api` 文件的位置与内容；自定义端口的发现方式。
   - 是否只有 HTTP（无 TLS）；`ADSPOWER_API_BASE` 覆盖时应接受哪些形式。
2. **鉴权**
   - `Authorization: Bearer <API Key>` 的准确格式；API Key 在 AdsPower 客户端中的位置与权限要求。
   - 关闭安全校验（无 key）时的行为；本 effort 明确不支持，但需要知道失败/成功的响应差异。
   - 401 / 403 / `code` 的具体表现；key 是否会出现在日志/异常中。
3. **V1 vs V2**
   - `/api/v1/browser/start?user_id=` 与 `/api/v2/browser-profile/start` 的差异、最低客户端版本、参数命名、响应结构。
   - 关闭/状态接口的 V1/V2 对应关系。
   - 推荐本仓采用哪一版；给出理由与兼容性风险。
4. **启动**
   - 完整参数表：`headless`、`open_tabs`、`ip_tab`、`new_first_tab`、`launch_args`、`disable_password_filling`、`clear_cache_after_closing`、`enable_password_saving`、`cdp_mask`、`device_scale`；各自默认值与版本要求。
   - 启动是同步还是异步；返回 200 时浏览器是否一定可连。
   - `data.ws.puppeteer` 的准确格式；`data.debug_port` 与 `ws.selenium` 的用途。
   - `browser.contexts` 的数量是否稳定为 1；页面/Context 选择建议。
   - 启动后是否会自动打开 IP 检测页或历史标签页；`open_tabs` / `ip_tab` 如何影响。
5. **已运行**
   - Profile 已运行时 `start` 的 HTTP 状态与 JSON `code` / `msg`；是否返回既有 `ws`。
   - 能否通过 `status` 可靠判断 Active / Inactive；状态值有哪些。
   - 若已运行，正确策略是 attach、拒绝，还是 stop 后重启；对“谁启动谁停止”的影响。
6. **停止**
   - `/api/v1/browser/stop?user_id=` 是否同步；返回结构。
   - 已停止时重复 stop 的响应；是否可幂等忽略。
   - 强制停止/超时行为。
7. **错误与限流**
   - AdsPower 是否始终 HTTP 200、用 JSON `code` 表达业务错误；列出常见 `code` / `msg`。
   - Profile 不存在、API 未开启、key 无效、限流、Profile 被占用、core 未下载等错误的可识别特征。
   - 429 / 限流响应；建议的重试/退避。
8. **内核与自动化**
   - Chromium 与 Firefox 内核分别支持哪些自动化方式；CDP / Playwright 是否只支持 Chromium。
   - `cdp_mask` 是否影响 Playwright / patchright 接管。
   - 与 `patchright.connect_over_cdp(..., no_defaults=True)` 的兼容性；`ws.puppeteer` 与 `http://127.0.0.1:{port}` 两种连接方式。
9. **拓扑**
   - 是否只支持本机；跨机、Docker、无桌面 Linux 的官方支持情况。
10. **登录态与页面**
    - Profile 登录态是否完全由 AdsPower 持久化；CLI 是否需要/是否应该读写 `cookies/*.json`。
    - 关闭浏览器时是否有会话/Cookie 丢失风险；`clear_cache_after_closing` 的影响。

## Context

官方入口：

- API Overview：<https://localapi-doc-en.adspower.com/docs/Rdw7Iu>
- Open Browser (V1)：<https://localapi-doc-en.adspower.com/docs/FFMFMf>
- Open Browser V2：<https://localapi-doc-en.adspower.com/docs/Open-Browser-V2>
- Close Browser：<https://localapi-doc-en.adspower.com/docs/DXam94>
- Check Browser Status：<https://localapi-doc-en.adspower.com/docs/YjFggL>
- Code Samples：<https://localapi-doc-en.adspower.com/docs/K4IsTq>
- GitHub：<https://github.com/AdsPower/localAPI>

产物写到 `.scratch/adspower-browser-mode/research/01-adspower-local-api.md`，要求：

- 每条事实附来源 URL 与检索日期；
- 明确区分「文档明说」「示例暗示」「社区实测」「未知」；
- 给出建议的错误映射表（HTTP / `code` → CLI 失败类别 + 是否可重试 + 是否应 stop）；
- 给出对 ticket 02–04 的直接影响清单。

## Answer

完整事实表、错误映射表与置信度见 [research/01-adspower-local-api.md](../research/01-adspower-local-api.md)（检索日期 2026-11-06；本机未装 AdsPower，无 live smoke）。

要点：

- **推荐 V2**：`POST /api/v2/browser-profile/start|stop`、`GET /api/v2/browser-profile/active`；官方 Playwright 示例即 V2，JSON body 更好处理 `launch_args`。V1 作为兼容备选。注意 V1 状态路径是 `/api/v1/browser/active`，不是 `/status`。
- **地址**：默认 `http://127.0.0.1:50325`（官方写 `local.adspower.net:50325` / `localhost:50325`，但官方排障建议 502/503 时换 `127.0.0.1`）。`local_api` 文件可发现自定义端口；官方正文只给了 Linux 路径，macOS/Windows 路径在图片里。
- **鉴权**：`Authorization: Bearer <API Key>`；需付费版 + 账号 API 权限（超管默认有，成员需授权）。无 key 安装不在范围。
- **启动**：成功 `code: 0`，`data.ws.puppeteer` 为 `ws://127.0.0.1:<port>/devtools/browser/<id>`，官方示例直接 `connect_over_cdp` 后取 `browser.contexts[0]`。默认参数会自动打开 IP 检测页（`proxy_detection=1` / V1 `ip_tab=1`）与历史页（`last_opened_tabs=1` / V1 `open_tabs=0`），规格必须显式关闭。
- **已运行**：官方只定义了 UI 语义（Profile 有锁，需开 Multi Device Mode），**start 的确切响应/是否返回既有 ws 未知**。建议 start 前预检 `active`：`Active` 就拒绝退出 `1`，不 attach、不 stop（谁启动谁停止）。
- **停止**：V1 GET / V2 POST，返回 `code: 0` + `success`；重复 stop、强制停止、超时均无官方定义，按 best-effort + warning 处理。
- **错误**：官方只定义 `0` / `-1`，博客另有 `8508`（cookie 格式）与 `user account does not exist`（Profile 不存在）。HTTP 401/403/429 的真实行为未知，不能假设「业务错误永远 HTTP 200」。
- **内核**：Playwright/CDP 仅 Chromium；Firefox 官方只给 Selenium/Marionette 示例。`cdp_mask` 默认 1，与官方 Playwright 示例兼容；本仓 patchright 1.64.4 支持 `no_defaults=True`。
- **登录态**：完全由 Profile 持久化，CLI 不读写 `cookies/*.json`；`clear_cache_after_closing` / `delete_cache` 必须保持 0，否则有掉登录风险。
- **主要未知**（需真实 smoke）：已运行 start / Multi Device 行为、重复 stop、401/403/429 响应、V2 最低版本、`contexts` 是否恒为 1、macOS `local_api` 路径。
