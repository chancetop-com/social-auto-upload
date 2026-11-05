# 01 — Multilogin X Launcher API 契约与边界行为（调研结论）

- 调研日期：**2026-11-05**（下文所有来源均在该日检索）
- 调研方式：官方 Postman 文档（含其公开 collection JSON）、multilogin.com/help 各页、release notes、CT 证书日志、公开社区实测记录
- 证据等级标记：
  - **[明说]** 官方文档/官方 collection 明确写出
  - **[暗示]** 官方示例或措辞可推断，但未直接断言
  - **[实测]** 非官方但可复现的社区实测/源码记录（标注仓库）
  - **[未知]** 无可靠证据，禁止在实现中假设

> **更正（2026-11-05，复核官方 Playwright / JS demo）：** 官方示例在 Start 返回 200 后**直接** `connectOverCDP`，没有任何轮询。因此下文“必须做就绪探测、不能拿到 port 就直连”的措辞**过强**。准确结论：**官方 happy path 就是直接连接**；冷启动 / 首次下载 core / Docker 等场景可能出现短暂未监听，防御性重试是**增强**，不是 API 契约要求。

> 一句话结论：**Start 200 返回端口后，官方 demo 直接连接**；**已运行时 Start 会失败（社区实测 500 `can't lock profile`），不会给你旧端口**；**鉴权统一用 `Authorization: Bearer <automation_token>`**；**TLS 用公开 CA 证书，`verify=True` 即可**；**stop 端点就是 `/api/v1/profile/stop/p/{id}`，重复 stop 的 500 `profile already stopped` 可视为成功**。

---

## 0. 事实速查表

| 问题 | 结论 | 等级 |
|---|---|---|
| `launcher.mlx.yt` 是什么 | 公网 DNS 名，A 记录直接指向 `127.0.0.1`；官方同时在排障页教用户写 hosts | [明说]+[实测] |
| TLS 证书 | Sectigo DV 公网证书（CT 日志：2026-03-05 起，2027-04-05 到期）；官方 Python 示例直接 `requests.get` 未关校验 | [实测]+[暗示] |
| `verify` 取值 | **True**（默认）；旧版本/自签证书场景才需要 `verify=False` 逃生开关 | [暗示] |
| Authorization | **`Bearer <token>`**；Docker 页的裸 token 写法是文档不一致 | [明说]+[实测] |
| 普通 API token 能调 launcher 吗 | **不可靠**；官方 Docker FAQ 明说"测试过的 launcher profile 端点不接受" | [明说] |
| Start 同步性 | **官方 demo：200 后直接 connectOverCDP**；冷启动可能短暂不可连，重试是增强不是必需 | [明说]+[实测] |
| 已运行时 Start | HTTP **500**，message `can't lock profile`（可能带 `in use by ...`）；**不返回端口** | [实测] |
| `/profile/statuses` 有端口吗 | **没有**（官方示例无 port 字段），不能用来 attach | [明说] |
| stop 是否同步 | "请求后应停止"，非严格同步；建议轮询状态确认 | [明说]+[暗示] |
| 强制停止 | 无专门端点；只有 `stop_all?type=all|regular|quick` | [明说] |
| 限流 | 按 workspace 共享 RPM（Pro10=50 / Pro20=75 / Pro50=100 / Business=100），**每个请求都计数**（含 start/stop） | [明说] |
| 远程 launcher | 官方不支持；连接固定走本机 `127.0.0.1` | [明说] |
| Mimic vs Stealthfox | `automation_type` 对 Mimic 任意，Stealthfox **仅 selenium**；用 `browser_type` 字段判断 | [明说] |
| headless 限制 | 官方未列专门限制；但 Mimic 在指定 `automation_type` 时 `custom_start_urls` 会失效（官方已知 bug） | [明说] |

---

## 1. 地址、TLS 与拓扑

### 1.1 `launcher.mlx.yt` 的解析

- **[明说]** 官方 API 文档把 Browser profile Launcher 的 Base URL 固定为 `https://launcher.mlx.yt:45001`，并说明"Launcher 端点需要 Multilogin 桌面应用处于运行状态"。[S1]
- **[明说]** 官方排障页《Connection lost》指导用户在 hosts 里加 `127.0.0.1 launcher.mlx.yt`，说明该域名被设计为指向本机回环。[S2]
- **[实测]** 2026-11-05 在本机执行 `dig +short launcher.mlx.yt @8.8.8.8` 返回 `127.0.0.1`。**即公网 DNS 本身就解析到回环**，不只是 hosts 别名。因此：
  - 桌面应用模式下，请求不会出网卡；
  - 在容器内解析同样得到容器自己的 `127.0.0.1`（见 1.4）。

### 1.2 TLS 证书

- **[实测]** CT 日志（crt.sh / certspotter）显示 `launcher.mlx.yt` 存在公开 CA 证书：
  - Subject: `CN=launcher.mlx.yt`，SAN 含 `www.launcher.mlx.yt`
  - Issuer: `C=GB, O=Sectigo Limited, CN=Sectigo Public Server Authentication CA DV R36`
  - 有效期：**2026-03-05 → 2027-04-05**
  - 这说明当前版本 launcher 服务的是**公网可信 DV 证书**，不是自签。
- **[暗示]** 官方 Playwright Python 示例直接 `requests.get(...)`，**没有** `verify=False`，进一步佐证默认校验可过。[S3]
- **结论/建议：**
  - 默认 `verify=True`。
  - 保留一个显式逃生开关（如 `MLX_INSECURE_TLS=1` → `verify=False`），用于：老版本 launcher、企业 MITM 代理、或用户把 base URL 改成 `https://127.0.0.1:45001`（**证书 SAN 不含 IP，改 IP 必然 hostname 校验失败**）。
  - 不要默认 `verify=False`：既无必要，也会把"连错服务"变成静默成功。
- **[未知]** Docker 镜像内是否内置同一张证书、是否随镜像版本轮换。仅能说"同域名、同端口，预期同一张"。

### 1.3 能否改 base URL

- **[明说]** 官方所有示例、collection、Docker 文档都硬编码 `https://launcher.mlx.yt:45001`；**没有任何环境变量或配置文件约定**用于改 launcher 地址。[S1][S4]
- **[暗示]** 桌面应用实际监听 `127.0.0.1:45001`（官方明说 Selenium/CDP 连接"runs locally through 127.0.0.1"[S5]），所以 `https://127.0.0.1:45001` 在网络上等价，只是证书主机名不匹配。
- **建议：** 把 base URL 做成配置项（默认官方域名），但**不要**把它当"远程 launcher"能力来宣传；改 IP 时必须允许关闭校验。

### 1.4 Docker launcher 的端口

- **[明说]** 官方 compose 只映射两个端口：`45001:45001`（HTTPS REST）和 `45003:45003`（WSS）。镜像 `public.ecr.aws/d3n0b1o9/mlx-launcher:mlx-latest`，**仅 amd64**（Apple Silicon 必须 `platform: linux/amd64`）。[S4]
- **[明说]** 桌面应用与容器不能同时占用 45001；先关应用再起容器。[S4]
- **[未知 / 重要风险]** compose 里**没有映射 CDP 调试端口段**。浏览器在容器内启动，`data.port` 是容器网络命名空间内的端口，宿主机默认**不可达**。官方 Docker 文章只演示了 `Start Quick Profile` + `Stop`，**没有给 Playwright/CDP 连接示例**。
  - 因此"用 Docker launcher + 宿主机 Playwright"这条路径，官方文档**没有闭环**。
  - 可行方向（均未在官方文档中确认）：`network_mode: host`（Linux）、或把 launcher 的调试端口段整体 publish、或在容器内跑 Playwright。**设计上应把 Docker+CDP 标为"需实测验证"**。

### 1.5 `/api/v1/version` 的作用

- **[明说]** `GET /api/v1/version` 返回 `{"data":{"env":"...","version":"..."},"status":{...}}`；Docker 文档用它做健康检查，且**示例未带 Authorization**。[S4][S1]
- **用途：** 启动前探活（区分"launcher 没起"vs"token 错"）；记录 env（EU/US）与版本便于排障。
- **[暗示]** 该端点可能无需鉴权；但实现上仍建议带上 token，避免依赖未文档化的行为。

### 1.6 跨机 / 远程 launcher

- **[明说]** "You don't need another computer to use Remote WebDriver. The connection runs locally through `127.0.0.1`."[S5]
- **[明说]** Local storage 的 profile **只能在创建它的设备上启动**，换机启动会得到 "Profile failed to start"/"Failed to get profile data"。[S6][S7]
- **结论：** 官方**不支持**跨机 launcher，也不支持把 CDP 端口暴露到公网。若 social-auto-upload 与 launcher 不同机：
  - 唯一官方路径是"把程序部署到 launcher 所在机器"；
  - 自己搭隧道（SSH/VPN）属于未文档化用法，需自行承担证书、端口、安全和 Multilogin ToS 风险。
- **建议：** CLI 在启动前做 `GET /api/v1/version` 探活，失败即给出"launcher 未运行/不在本机"的明确提示，而不是笼统的 launch_failed。

---

## 2. 鉴权

### 2.1 `Bearer` 还是裸 token？

- **[明说]** 官方 API collection 总述："Most Multilogin API requests require a **Bearer Token** in the `Authorization` header."[S1]
- **[明说]** Playwright 官方示例（JS 与 Python）都写 `HEADERS["Authorization"] = f"Bearer {API_TOKEN}"`。[S3]
- **[明说]** 但 Docker 文章的所有 cURL 都写 `--header 'Authorization: YOUR_TOKEN'`（裸 token）。[S4]
- **[实测]** 社区项目 `MojoTheApe/adopy-campaing-launcher` 在 launcher 12.13.0 上长期使用 `Authorization: Bearer <automation_token>`，start/stop/statuses 均正常。[S8]
- **判定：**
  - **`Bearer` 是主写法，官方 collection 与 Playwright 示例一致，且有实测。**
  - Docker 页的裸 token 是**该页示例的简化/不一致**，不能据此认为裸 token 是 launcher 的正式契约。
  - **[未知]** launcher 是否"同时接受"裸 token。没有官方说明，也没有可复现实验。
- **建议实现：** 只发 `Bearer`；若返回 401，**最多**用裸 token 重试一次（作为兼容兜底），仍失败则判 `token_invalid`。不要把这个兜底写进主流程文档。

### 2.2 Workspace Automation Token

- **[明说]** 端点：`GET https://api.multilogin.com/workspace/automation_token?expiration_period=...`，用**普通 API token 作为 Bearer** 调用。[S9][S1]
- **[明说]** `expiration_period` 可选：`1h, 3h, 5h, 16h, 24h, 48h, 1w, 2w, 3w, 1mo, no_exp`；默认 `24h`。[S1]
- **[明说]** `no_exp` 表示无计划过期，但**改密码会使现有 automation token 失效**。[S9]
- **[明说]** 需要套餐支持 automation（官方帮助页写 Pro 10 及以上），且受 workspace 角色限制。[S9][S10]
- **[明说]** 必须用"目标 workspace"的普通 token 来生成；跨 workspace 的 token 会 401/403。[S9][S4]
- **建议：** token 缓存到 keyring/环境变量；启动前解析 JWT `exp`（留 60s 余量）做本地预检；收到 401 时刷新一次再重试。

### 2.3 普通 API token / refresh token

- **[明说]** 普通 API token 30 分钟过期，RPM 更低。[S9][S10]
- **[明说]** Docker FAQ："Regular API tokens expire after 30 minutes and **were not accepted by the tested Launcher profile endpoint**."[S4]
- **[明说]** refresh token **不能**用于普通 API 或 launcher 请求，只能换新的普通 token。[S4][S10]
- **结论：** launcher 场景**只支持 automation token**（至少官方不保证普通 token）。refresh token 直接拒绝。

### 2.4 401 / 403 的响应体

- **[明说]** 所有响应统一信封：
  ```json
  {"data": {...}, "status": {"error_code": "...", "http_code": 200, "message": "..."}}
  ```
  错误时 `data` 可能缺失。[S1][S3]
- **[明说]** 401 = 凭据缺失/无效；403 = 无权限；429 = 超限；500 = 服务端错误。[S10]
- **[明说]** 401 的一个已知文案（`api.multilogin.com` 侧）：`401 – Incorrect JWT token`。[S9]
- **[明说]** Docker 排障把 launcher 的 401 描述为 `401 – Authorization error`（通常 = 用了 refresh token / 过期普通 token / 别的 workspace 的 token）。[S4]
- **[实测]** 403 + `error_code = "FORBIDDEN_REQUEST"` + message 含 `restricted permission`：当同一账号的桌面会话被另一台电脑抢占时出现；**token 本身仍有效**。[S8]
- **[未知]** launcher 401 的确切 `error_code` 字符串（是 `UNAUTHORIZED`、`TOKEN_EXPIRED` 还是空）。

---

## 3. 启动（Start Browser Profile）

### 3.1 端点与参数

```
GET https://launcher.mlx.yt:45001/api/v2/profile/f/{folder_id}/p/{profile_id}/start
    ?automation_type=playwright
    &headless_mode=false
```

| 参数 | 必填 | 默认 | 说明 |
|---|---|---|---|
| `folder_id`（path） | 是 | `default folder`* | 文档写 Required，但 value 描述又说默认 default folder，存在措辞矛盾 |
| `profile_id`（path） | 是 | — | profile UUID |
| `automation_type` | 否 | `selenium` | `selenium` / `puppeteer` / `playwright`；**Mimic 全支持，Stealthfox 仅 selenium** |
| `headless_mode` | 否 | `false` | `true/false` |
| 超时参数 | — | — | **不存在**；只能靠 HTTP client 侧超时 |

- **[明说]** "The endpoint will return a port for automation in the response message **if the automation type parameter is passed**." → **不传 `automation_type` 就没有端口**。[S1]
- **[明说]** 可选 header `X-Strict-Mode: true`，要求所有必填参数显式给出；默认 false。[S1]
- **建议：** 永远显式传 `automation_type=playwright&headless_mode=<bool>`。

### 3.2 成功响应结构

**[明说]** 官方示例（200）：[S1]

```json
{
  "data": {
    "browser_type": "mimic",
    "core_version": 132,
    "id": "81b5627a-...",
    "is_quick": false,
    "port": "55513"
  },
  "status": {
    "error_code": "",
    "http_code": 200,
    "message": "Profile started successfully"
  }
}
```

要点：
- `port` 是**字符串**（不是 int），拼 URL 时不要做算术。
- 除 `port` 外还有 `browser_type`、`core_version`、`id`、`is_quick`；**没有** `wsEndpoint` / `webSocketDebuggerUrl` 的官方字段。
- `data.port` 只保证"自动化端口"，不保证此刻已 accept 连接。

### 3.3 Start 是同步还是异步？

证据是分层且略有冲突的：

- **[明说]** 成功响应 message 是 `Profile started successfully`，且帮助页说"连接要在 API 确认 start 成功之后"。[S1][S5]
- **[明说]** 但同一批官方文档的 Docker 排障明确写："**The start request returns `200`, but the profile isn't running** → Check `/api/v1/profile/statuses`."[S4]
- **[明说]** 状态机包含明显的前置阶段：`download_browser_profile_metadata` → `download_browser_profile_data` → `download_browser_core` → `validate_proxy` → `start_browser` → `browser_running`（以及对应 `*_error`）。[S1]
- **[实测]** 冷启动后立刻 `connectOverCDP` 会 `ECONNREFUSED`；社区实现按 1s/2s/3s/3s 退避等待端口可用。[S8]

**结论：官方契约是“200 即可连”。** 官方 Python 与 JS Playwright 示例都在拿到 `data.port` 后**立即** `connectOverCDP`，没有轮询；JS 示例仅设置 `timeout: 10000`。因此：
- **不要**把“先轮询 `browser_running` 再连接”写成必需步骤；
- 冷启动 / 首次下载 core / Docker 等边界可能出现 `ECONNREFUSED`，此时做**少量退避重试**即可，属于健壮性增强；
- 若重试仍失败，再查 `/api/v1/profile/status/p/{id}` 区分 `download_*` 阶段与 `*_error`，用于错误提示。

### 3.4 可选的防御性重试（非官方要求）

官方 demo 不重试也能工作。实现上可选择：

1. **直接连接 + 超时**（最贴近官方）：`connect_over_cdp(url, timeout=10000)`；失败后按 1s/2s/3s 重试 2–3 次。
2. **失败后再查状态**（诊断用）：`GET /api/v1/profile/status/p/{profile_id}`
   - `browser_running` → 继续重试端口；
   - `*_error`（`download_meta_error` / `download_data_error` / `download_core_error` / `validate_proxy_error` / `start_browser_error`）→ 立即失败；
   - `download_*` → 首次启动可能在下载 core，放宽预算。

建议预算：连接超时 10s，重试 2–3 次；总预算 30–60s（首次可放宽）。轮询/重试也计入 RPM，不要 100ms 级频率。

### 3.5 Profile 已在运行时 Start 会怎样

- **[未知-文档]** 官方文档**完全没有写**"已运行时再 Start"的返回。
- **[实测]** 社区在 launcher 12.13.0 / 2026-10-29 的现场记录：
  - HTTP **500**
  - message：`can't lock profile`（社区测试里还出现过 `can't lock profile, in use by another device` 的变体，未在真实环境确认）
  - `error_code`：**未知**（日志只留了 message）
  - **没有拿到端口**
  - 该记录同时说明：手动 Stop 后 profile 在 Multilogin 里会显示 "Locked"，此时 Start 也是同样的 500 `can't lock profile`。[S8]
- **[实测]** 对"被用户手动打开、无 automation 的 profile"，社区日志是 "profile is running but no CDP debug port found"——即**手动打开的 profile 根本没有调试端口**，不能 attach。[S8]
- **[未知]** 是否存在 409 分支。社区代码把 409 也归为 already-running，但**没有实测证据**；另有记录把 409 列为"并发启动被拒"的候选之一。**不要把 409 当稳定的 profile_busy 信号。**
- **[未知]** 500 的响应 `data` 里是否带 `port`。社区代码"尝试复用错误响应里的 port"，但注释是假设，且随后还有"从 running 列表取 port"的兜底——说明**并未证实**。

**实现结论：**
> 已运行时 **不要指望 Start 返回端口**。正确流程是：先查状态 → 若 `browser_running`，先 stop → 等 `stopped` → 再 start。若 Start 返回 500 且 message 含 `can't lock`，先 stop 一次再 start 一次，**最多一次**，不要循环。

### 3.6 `/api/v1/profile/statuses` 的结构与端口

**[明说]** 官方示例（200）：[S1]

```json
{
  "data": {
    "active_counter": {"cloud": 2, "local": 0, "quick": 1},
    "states": {
      "<profile_id>": {
        "browser_type": "mimic",
        "core_version": 137,
        "folder_id": "...",
        "in_use_by": "user@multilogin.com",
        "is_quick": false,
        "last_launched_at": "...",
        "last_launched_by": "...",
        "last_launched_on": "...",
        "message": "",
        "name": "...",
        "profile_id": "...",
        "status": "browser_running",
        "timestamp": 1750946194258,
        "workspace_id": "..."
      }
    }
  },
  "status": {"error_code": "", "http_code": 200, "message": ""}
}
```

- **没有 `port` 字段** → **不能用 statuses 做 attach**。
- **[实测]** `states` 会包含**未运行**的 profile（`status: "stopped"`），所以必须看 `status` 值，不能"出现在 states 里就算在跑"。[S8]
- **[明说]** 单 profile 版本：`GET /api/v1/profile/status/p/{profile_id}`，`data` 是单个对象（字段同上）。[S1]
- **[明说]** 数据只反映"上一次 Agent 会话"；**Agent 重启后可能查不到**。[S1] → 状态查不到时应回退到"端口探活/直接尝试 start"，不要直接判死。

### 3.7 启动失败的典型错误

| 场景 | 表现 | 等级 |
|---|---|---|
| Mimic core 未下载完 | `BROWSER_VERSION_NOT_FOUND`；查 `/api/v1/loaded_browser_cores`，等 core 出现后重试 | [明说][S4] |
| 代理不可用/认证失败 | UI 文案 "Wrong proxy data"；API 侧确切 message/error_code **未知**；CDP 首次导航可能报 `net::ERR_INVALID_AUTH_CREDENTIALS` | [明说]+[实测][S11][S8] |
| 桌面会话被其他机器抢占 | 403 `FORBIDDEN_REQUEST` / `restricted permission` | [实测][S8] |
| token 过期/被吊销 | 401（message 可能 `Authorization error`） | [明说]+[实测][S4][S8] |
| profile 被锁/已在运行 | 500 `can't lock profile` | [实测][S8] |
| 浏览器进程起来但 CDP 拒连 | start 200 后 `ECONNREFUSED` | [实测][S8] |
| 并对并发过高 | `ConnectionAborted` / 可能的 409 / 超时 | [实测][S8] |

---

## 4. 停止（Stop Browser Profile）

### 4.1 端点与响应

```
GET https://launcher.mlx.yt:45001/api/v1/profile/stop/p/{profile_id}
```

**[明说]** 成功（200）：[S1]

```json
{"status": {"error_code": "", "http_code": 200, "message": ""}}
```

注意：**没有 `data`，`message` 为空**。判定成功只能看 `status.http_code == 200` / HTTP 200。

- **[明说]** 路径里**没有 folder_id**（与 start 不同）。[S1]
- **[实测]** 该地址在 launcher 12.13.0 上确认可用；`/api/v2/.../stop`、`/api/v1/profile/stop`（query 形式）均 404。[S8]

### 4.2 是否同步

- **[明说]** "The profile **should** stop after the request."——措辞是"应该"，不是"已停止"。[S4]
- **[明说]** 状态机里有 `stopped`，但没有 stop 的同步保证。[S1]
- **[实测]** 社区对 stop 的实现是：主地址最多重试 3 次（间隔 2s），只对"连接断开或 5xx"重试；4xx 立即停。[S8]
- **建议：** stop 后再轮询 `status == "stopped"`（或端口不可连）最多 ~30s；超时则判 `stop_failed`，不要无限等。

### 4.3 "已经停止"

- **[明说]** 稳定返回 **HTTP 500** + `{"status":{"error_code":"INTERNAL_SERVER_ERROR","http_code":500,"message":"profile already stopped"}}`；官方明确说"**you're good**"，可忽略。[S4]
- **[实测]** 同一行为在 12.13.0 复现。[S8]
- **判定规则（建议）：** `http_code == 500 && message.lower().contains("already stopped")` → **视为成功**（幂等）。不要按 5xx 一律重试。

### 4.4 强制停止

- **[明说]** **没有**"force stop"端点。[S1]
- **[明说]** 有批量停止：`GET /api/v1/profile/stop_all?type=all|regular|quick`（默认 all），返回同样的 status 信封。[S1]
- **[明说]** 另有云侧"解锁"端点 `GET https://api.multilogin.com/bpds/profile/unlock_profiles`（可传 ids，或不传 body 解锁全部），但文档要求"**先关闭所有被锁的 profile**"再调用；它解决的是存储锁/占用锁，不是"杀进程"。[S1]
- **建议：** CLI 只暴露单 profile stop + 可选 `stop_all`；不要用 kill 进程作为常规路径（会留下 Multilogin 侧 "in use by" 状态，需等超时）。

---

## 5. 限流与重试

- **[明说]** 单位是 **RPM**，**按 workspace 共享**（团队成员共用一份额度）。[S10]
- **[明说]** 额度：Pro 10 = 50，Pro 20 = 75，Pro 50 = 100，Business = 100（更高 Business 可定制）。[S10]
- **[明说]** "**Each API request counts toward your limit**"，无论管的是云手机还是浏览器 profile → **start / stop / status 轮询全都计数**。[S10]
- **[明说]** 超限返回 `429 – Too Many Requests`。[S10]
- **[明说]** 官方重试建议：**等到下一分钟再发**；不要连续猛冲；官方**没有**给出指数退避或 `Retry-After` 的说明。[S10][S12]
- **[未知]** 429 响应是否带 `Retry-After` 头、429 的 `error_code` 字符串。
- **建议实现：**
  - 客户端做本地令牌桶（按套餐 RPM 的 80% 设上限），start/stop 也计入；
  - 429 → 指数退避 + 抖动（1s、2s、4s…上限 60s），最多 3 次；优先对齐到"下一分钟"；
  - 状态轮询频率控制在 1s 级，不要 100ms；
  - 批量启动时串行/小并发（社区实测并发过高会 `ConnectionAborted`/超时）。[S8]

---

## 6. 内核：Mimic vs Stealthfox，以及 headless

### 6.1 Playwright 支持差异

- **[明说]** API 文档对 `automation_type` 的描述："**Mimic can work with any of the types. Stealthfox can only work with `selenium`.**"[S1]
- **[明说]** 帮助页："Playwright works with Mimic browser profiles; legacy Stealthfox profiles **don't support Playwright**."[S3]
- **[明说]** 只有 Mimic 是 Chromium 系；Stealthfox 是 Firefox 系（因此 CDP 也不适用）。[S5][S13]
- **结论：** `automation_type=playwright` + Stealthfox = 必然失败；设计上应在启动前就拒绝，而不是等 500。

### 6.2 如何判断内核类型

三条路，按代价从低到高：

1. **启动前（推荐）**：`POST https://api.multilogin.com/profile/search`，请求体可带 `browser_type: "mimic"|"stealthfox"` 过滤；响应 `data.profiles[].browser_type` 即内核类型（同时有 `folder_id`、`in_use_by`、`is_local`）。[S1]
2. **启动前（单条）**：`GET https://api.multilogin.com/profile/summary?meta_id=...`（collection 中存在该端点）。[S1]
3. **运行时**：`GET /api/v1/profile/status/p/{id}` 或 `/statuses` 的 `browser_type` 字段。[S1]

- **[明说]** 创建 profile 时 `browser_type` 只接受 `"mimic"` / `"stealthfox"`。[S1]
- **建议：** CLI 缓存 `profile_id → browser_type`；遇到 `stealthfox` 直接报 `unsupported_core`（或归入 `launch_failed` 并给明确文案），不要发 start。

### 6.3 headless_mode 的已知限制

- **[明说]** `headless_mode` 默认 `false`；置 `true` 即无可见窗口。[S1][S14]
- **[明说]** Docker 场景下，排障要求 quick profile 请求体里必须 `"is_headless": true`，并且无代理时 `"proxy_masking": "disabled"`，还要带 `no-sandbox` / `disable-dev-shm-usage` 参数。[S4]
- **[明说]** **已知 bug（与 headless 无关但影响自动化启动）**：Mimic profile 只有在**不传 `automation_type`** 时 `custom_start_urls` 才生效；传了自动化类型会被忽略（官方称"to be fixed soon"）。Stealthfox 正常。[S1]
- **[未知]** 官方**没有**列出 headless 在登录页、验证码、扩展方面的专门限制。可确认的只有"没有可见窗口，人工介入需另想办法"。
- **实践建议（非文档）：**
  - 首次登录/过验证码建议先用 `headless_mode=false` 人工完成，再切 headless；
  - headless 下若页面依赖扩展/通知/窗口焦点，需实测；
  - 不要依赖 `custom_start_urls` 做导航，启动后自己 `page.goto()` 更稳。

---

## 7. 建议的错误映射表

> 目标：把 launcher 的 HTTP/`error_code`/message 映射到 CLI 的失败类别，并决定是否可重试。
> 原则：**先看 HTTP，再看 `status.error_code`，最后看 message 关键字**（因为 launcher 的 error_code 覆盖不全）。

| HTTP | error_code（已知/推测） | message 关键字 | CLI 类别 | 可重试 | 处理建议 |
|---|---|---|---|---|---|
| — | — | 连接被拒 / DNS / timeout（无 HTTP） | `launch_failed`（launcher 不可用） | 是（1–2 次，短退避） | 先 `GET /api/v1/version` 探活；提示"启动 Multilogin 桌面应用或检查 45001" |
| 401 | 未知（可能空/UNAUTHORIZED） | `Authorization error` / `Incorrect JWT token` / `Unauthorized` | `token_invalid` | 否（刷新 token 后可重试 1 次） | 用 automation token；检查 workspace；`Bearer` 写法 |
| 403 | `FORBIDDEN_REQUEST` | `restricted permission` / `forbidden` | `login_required` | 否 | 桌面会话被别的机器抢占/未登录 → 需人工在 Multilogin 重新登录 |
| 403 | 其他 | 权限/角色/套餐 | `login_required` | 否 | 检查 workspace 角色与套餐 automation 权限 |
| 400 | 未知 | 参数缺失/非法 | `unknown`（配置错误） | 否 | 校验 folder_id/profile_id/automation_type |
| 404 | 未知 | `404 page not found` | `unknown`（端点/ID 错） | 否 | 检查路径（stop 用 `/p/{id}`）与 ID |
| 409 | 未知 | 任意 | `profile_busy`（**低置信**） | 条件式：仅当状态确认为 running 时 stop→start 一次 | 不要把 409 单独当 busy 证据 |
| 429 | 未知 | `Too Many Requests` | `rate_limited` | 是（退避到下一分钟） | 本地限流；最多 3 次 |
| 500 | `INTERNAL_SERVER_ERROR` | `profile already stopped`（**stop 场景**） | **成功**（不算失败） | — | 幂等忽略 |
| 500 | 未知 | `can't lock profile` / `in use by`（**start 场景**） | `profile_busy` | 条件式：stop 一次→等 stopped→start 一次；不循环 | 若仍失败，提示"在 Multilogin 里点 Locked 解锁或关闭占用窗口" |
| 500 | `BROWSER_VERSION_NOT_FOUND`（或同义） | core 未下载 | `launch_failed` | 是（延迟 30–60s，最多数次） | 查 `/api/v1/loaded_browser_cores`；首次启动耐心等 |
| 500 | 未知 | proxy / `ERR_INVALID_AUTH_CREDENTIALS` | `launch_failed` | 否（配置问题） | 提示检查代理账号密码/流量；修正后重试 |
| 500 | 未知 | 其他 | `launch_failed` | 是（1 次） | 记录原始 body，便于排障 |
| 200 | — | `data.port` 缺失 | `launch_failed` | 否（或重试 1 次） | 视为契约异常；查 status |
| 200 | — | 有 port 但 CDP `ECONNREFUSED` | `launch_failed` | 是（按 1/2/3/3s 退避，总 10–30s） | 冷启动竞态；超时后建议 stop→start 一次 |
| 200（stop） | — | 任意 | 成功 | — | — |
| 5xx（stop） | 非 already stopped | 任意 | `stop_failed` | 是（最多 3 次，间隔 2s） | 4xx 不重试；超时后提示人工关闭 |

**补充：**
- `login_required` 与 `token_invalid` 要分开：前者要人重新登录 Multilogin 桌面端，后者换 token 即可。
- `profile_busy` **永远不要盲重试**：必须先确认状态并 stop，否则会陷入 500 循环。
- 所有失败都应把原始 `status.error_code` / `status.message` / HTTP 码落盘，未知分支才有机会事后归类。

---

## 8. 明确的"未知项"清单（设计不要假设）

1. 已运行时 Start 的 `error_code` 精确值；响应体是否包含 `data.port`。
2. 409 在 launcher 的语义（是否等同 busy，还是并发/资源拒绝）。
3. launcher 401 的 `error_code` 字符串与响应体样例。
4. 429 是否带 `Retry-After`；429 的 `error_code`。
5. Docker 模式下 CDP 端口如何从宿主机访问（官方 compose 未映射端口段）。
6. 普通 API token 是否在**所有** launcher 端点都不可用（官方只说"tested endpoint"不接受）。
7. Stealthfox 用 `automation_type=playwright` 的具体报错（是 400、500 还是静默降级）。
8. headless 下登录页/验证码/扩展的官方限制。
9. `/api/v1/profile/statuses` 在 Agent 重启后的完整行为（官方说"可能没有数据"）。
10. 多 workspace / 多账号并发时 launcher 的端口分配与冲突行为。

**建议的最小验证实验（有账号后按序做）：**
1. 正常 start（playwright）→ 记录 body、端口、从 200 到 `/json/version` 可用的耗时。
2. 同一 profile 再 start 一次 → 记录 HTTP/`error_code`/message/`data`。
3. 手动在 UI 打开 profile → 再 start → 记录差异（预期 `can't lock`）。
4. stop 两次 → 记录第二次的 500 body。
5. 用过期 token / 别的 workspace token 各打一次 → 记录 401/403 body。
6. 用 Stealthfox profile + playwright 打一次 → 记录报错。
7. Docker 起 launcher，从宿主机尝试连 CDP → 确认端口可达性。

---

## 9. 来源

| ID | URL | 内容 | 检索日期 |
|---|---|---|---|
| S1 | https://documenter.getpostman.com/view/28533318/2s946h9Cv9 （及其公开 collection JSON `https://documenter.gw.postman.com/api/collections/28533318/2s946h9Cv9?segregateAuth=true&versionTag=latest`） | Base URL、鉴权、Start/Stop/Status/Version、参数默认值、响应示例、错误码总述、automation_token | 2026-11-05 |
| S2 | https://multilogin.com/help/en_US/connection-lost-error | `127.0.0.1 launcher.mlx.yt` hosts 修复 | 2026-11-05 |
| S3 | https://multilogin.com/help/en_US/puppeteer-selenium-and-playwright/playwright-automation-example | Playwright 示例（Bearer）、Mimic only、Stealthfox 不支持 | 2026-11-05 |
| S4 | https://multilogin.com/help/en_US/getting-started-with-multilogin-x-automation/run-in-docker | 镜像、端口 45001/45003、裸 token 示例、automation token 要求、`profile already stopped`、`BROWSER_VERSION_NOT_FOUND`、200 但未运行查 statuses、amd64 | 2026-11-05 |
| S5 | https://multilogin.com/help/en_US/troubleshooting-webdriver-connection-issues-with-multilogin-api | 本地 `127.0.0.1`、data.port、端口会变、确认成功后再连 | 2026-11-05 |
| S6 | https://multilogin.com/help/en_US/common-errors/error-profile-failed-to-start | local storage 不能换机启动 | 2026-11-05 |
| S7 | https://multilogin.com/help/en_US/troubleshooting/failed-to-get-profile-data | 同上（换机启动失败） | 2026-11-05 |
| S8 | https://github.com/MojoTheApe/adopy-campaing-launcher （issues #203/#1040/#1300/#200/#642、PR #973、`src/meta_campaign_agent/multilogin_launcher.py`、`src/fb_api/mlx_session.py`） | 社区实测：stop 地址、`can't lock profile`、`already stopped`、403 `FORBIDDEN_REQUEST`、401=token、CDP 冷启动竞态、statuses 含 stopped | 2026-11-05 |
| S9 | https://multilogin.com/help/en_US/automation-token | automation token 生成、过期、改密失效、401 `Incorrect JWT token`、403 | 2026-11-05 |
| S10 | https://multilogin.com/help/en_US/getting-started-with-multilogin-x-automation/automation-faq | RPM 档位、workspace 共享、每请求计数、429 与响应码含义 | 2026-11-05 |
| S11 | https://multilogin.com/help/en_US/common-errors/wrong-proxy-data-error | 代理失败的 UI 文案与排查 | 2026-11-05 |
| S12 | https://multilogin.com/help/en_US/common-errors/how-to-fix-too-many-requests-error | 429 后"等到下一分钟" | 2026-11-05 |
| S13 | https://multilogin.com/help/en_US/how-to-manage-running-profiles | 运行中 profile 管理、quick profile | 2026-11-05 |
| S14 | https://multilogin.com/help/en_US/getting-started-with-multilogin-x-automation/how-to-use-headless-mode | headless_mode / is_headless 用法 | 2026-11-05 |
| S15 | https://crt.sh/?q=launcher.mlx.yt 、https://api.certspotter.com/v1/issuances?domain=launcher.mlx.yt | 证书主体/签发者/有效期（Sectigo DV） | 2026-11-05 |
| S16 | https://multilogin.com/release-notes/ | Docker/headless 支持、Mimic 核心与 Playwright 反检测更新 | 2026-11-05 |
