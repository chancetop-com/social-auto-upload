# 01 — Multilogin X Launcher API 契约与边界行为

Status: resolved
Type: research
Blocked by: —
Assignee: —

## Question

在**只有官方文档、没有真实账号**的前提下，把 Multilogin X Launcher API 的准确契约整理成事实表，供设计直接引用。需要回答：

1. **地址与 TLS**
   - `https://launcher.mlx.yt:45001` 是本机别名还是公网域名？桌面应用 / Docker launcher 各自如何解析？
   - 证书由谁签发？Python `requests` 是否需要 `verify=False`？有没有官方推荐做法？
   - 是否允许改 base URL（例如远程 launcher 或端口转发）？有没有环境变量或配置文件约定？

2. **鉴权**
   - Launcher 请求头到底是 `Authorization: Bearer <token>` 还是 `Authorization: <token>`？官方两个示例（Playwright 页 vs Docker 页）写法不一致，哪个适用于 `launcher.mlx.yt:45001`？
   - Workspace Automation Token 的生成端点、有效期、权限要求。
   - 普通 API token 是否可用于 launcher？文档说 30 分钟过期，launcher 是否接受？
   - 401 / 403 的响应体结构（`status.error_code` / `message`）。

3. **启动**
   - `GET /api/v2/profile/f/{folder_id}/p/{profile_id}/start` 的完整 query 参数：`automation_type` 允许值、`headless_mode` 默认值、是否有超时参数。
   - 成功响应完整 JSON 结构（`data.port` 之外还有什么：`browser_type`、`core_version`、`is_quick` 等）。
   - 启动是同步还是异步？返回 200 时浏览器一定已可连接吗？需要轮询 `/api/v1/profile/statuses` 吗？
   - **Profile 已在运行时**返回什么（HTTP 码 + `error_code` + message）？会不会仍返回已有端口？
   - `/api/v1/profile/statuses` 的请求方式、响应结构，是否包含端口、是否可用来做 attach。
   - 启动失败（镜像未下载、BROWSER_VERSION_NOT_FOUND、代理不可用）的典型错误码。

4. **停止**
   - `GET /api/v1/profile/stop/p/{profile_id}` 是否同步？返回结构？
   - 已停止时是否稳定返回 500 + `profile already stopped`？应如何判定“可忽略”。
   - 是否存在“强制停止”端点。

5. **限流与重试**
   - RPM 限制、429 响应体；官方建议的重试/退避策略。
   - 启动/停止是否计入 RPM。

6. **拓扑**
   - 本机桌面应用模式下 CDP 是否一定在 `127.0.0.1:{port}`？
   - Docker launcher 模式下，容器内/宿主机的端口如何映射；`/api/v1/version` 的作用。
   - 若 social-auto-upload 跑在另一台机器，官方是否支持远程 launcher / 需要什么网络条件。

7. **内核**
   - Mimic 与 Stealthfox 对 Playwright 的支持差异；如何从 profile 配置或 API 判断内核类型。
   - `headless_mode=true` 的已知限制（登录页、验证码、扩展）。

## Context

官方入口：

- API 文档：<https://documenter.getpostman.com/view/28533318/2s946h9Cv9>
- Start with Postman：<https://multilogin.com/help/en_US/starting-a-profile-with-postman>
- Playwright example：<https://multilogin.com/help/en_US/puppeteer-selenium-and-playwright/playwright-automation-example>
- Headless：<https://multilogin.com/help/en_US/getting-started-with-multilogin-x-automation/how-to-use-headless-mode>
- Docker：<https://multilogin.com/help/en_US/getting-started-with-multilogin-x-automation/run-in-docker>
- Rate limits / codes：<https://multilogin.com/help/en_US/getting-started-with-multilogin-x-automation/automation-faq>

产物写到 `.scratch/multilogin-browser-mode/research/01-mlx-launcher-api.md`，要求：

- 每条事实附来源 URL 与检索日期；
- 明确区分“文档明说”“示例暗示”“未知”；
- 给出建议的错误映射表（HTTP/error_code → 我们 CLI 的失败类别 + 是否可重试）。

## Answer

详见 [research/01-mlx-launcher-api.md](../research/01-mlx-launcher-api.md)。要点：

- `launcher.mlx.yt` 公网 DNS 直接指向 `127.0.0.1`；当前证书是 Sectigo 公网 DV，`verify=True` 可用；桌面应用与 Docker launcher 二选一占用 45001。
- 鉴权以 `Authorization: Bearer <automation_token>` 为准；普通 API token 不可靠，refresh token 完全不能用于 launcher。
- Start 200 返回字符串 `data.port`；**官方 demo 拿到 port 后直接 `connectOverCDP`，不轮询**。冷启动/首次下载 core 可能短暂不可连，超时+少量重试即可，属增强而非契约。
- **Profile 已在运行时 Start 失败**（社区实测 500 `can't lock profile`，官方未文档化），**不返回端口**；`/statuses` 也没有 port，不能 attach。手动打开、无 automation 的 profile 没有调试端口。
- Stop 是 `GET /api/v1/profile/stop/p/{id}`，非严格同步；重复 stop 的 500 `profile already stopped` 视为成功；无 force stop。
- 限流按 workspace 共享 RPM，start/stop/轮询都计数；429 官方只建议等到下一分钟。
- 只有 Mimic 支持 Playwright；Stealthfox 仅 selenium。`headless_mode` 支持，但人工登录/验证码需 headed。
- 远程 launcher 官方不支持；Docker launcher 的 CDP 端口能否从宿主机访问，官方文档未闭环，标为待验证风险。

**对设计的直接影响：**

1. 启动前先 `GET /api/v1/version` 探活，失败提示“launcher 未运行/不在本机”。
2. 官方路径是拿到 port 后**直接连接**；实现可加超时与 2–3 次退避重试作为健壮性兜底，但不要把它写成“必须先轮询状态”的硬要求。
3. 遇到 500 `can't lock profile` **不要自动 stop 别人的 profile**（charter 已定：并发/占用由调度 App 处理）；直接失败并把原始 `error_code`/message 交给调度。
4. 错误映射表见研究文件第 7 节；`login_required` 专指平台登录失效（退出 10），MLX 的 token/权限/锁问题一律退出 1。
5. Docker 拓扑若要采用，必须先做真机验证（见 ticket 08）。
