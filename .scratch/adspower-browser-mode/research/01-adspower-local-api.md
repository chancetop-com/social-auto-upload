# 01 — AdsPower Local API 契约与边界行为（研究结果）

- 检索日期：**2026-11-06**
- 本机状态：未安装 AdsPower（`/Applications` 无匹配），`127.0.0.1:50325` 未监听 → **没有做任何 live smoke test**
- 标注体系：
  - `[官方文档]` AdsPower 官方 Local API 文档 / 官方帮助中心
  - `[官方博客]` AdsPower 官网博客（第一方，但不是 API 参考文档）
  - `[示例暗示]` 只能从官方示例代码/示例响应反推，文档正文没有明说
  - `[社区]` 第三方 SDK / 第三方文章，非 AdsPower 官方
  - `[未知]` 无法从现有资料确认；文末给出验证方式
- 引用编号 `[S#]` 对应第 14 节「来源登记表」，每条来源都带 URL 与检索日期。

---

## 0. 结论摘要（先看这段）

1. **推荐 V2 生命周期三件套**：`POST /api/v2/browser-profile/start`、`POST /api/v2/browser-profile/stop`、`GET /api/v2/browser-profile/active`。理由：官方 Playwright 示例就是 V2；JSON body 比 query string 更适合 `launch_args`；start/stop/status 命名对称；用 `profile_id` 与本仓 `--profile-id` 概念对齐。[S3][S5][S7][S10]
2. **地址默认用 `http://127.0.0.1:50325`**。官方写的是 `local.adspower.net:50325` 或 `localhost:50325`，但官方自己排障时明确说：`local.adspower.net` 出现 502/503 就换成 `127.0.0.1` / `localhost`。用 IP 可以绕开 hosts/DNS/代理。[S1][S17]
3. **鉴权是 `Authorization: Bearer <API Key>`**，需要 AdsPower 付费版 + 账号具备 API 权限（超管默认有，普通成员需被授权）。[S1][S12]
4. **start 成功 = `code: 0` + `data.ws.puppeteer`**（`ws://127.0.0.1:<port>/devtools/browser/<id>`）。官方 Playwright 示例直接 `chromium.connect_over_cdp(...)` 然后 `browser.contexts[0]`。[S2][S3][S10]
5. **默认启动参数会主动打开页面**：V2 的 `proxy_detection` 默认 1（开 IP 检测页）、`last_opened_tabs` 默认 1（恢复上次页面）。规格层必须显式关掉，否则上传逻辑要面对未知的初始标签页。[S3]
6. **Profile 已运行时的 start 行为，官方没有定义**。能确认的是官方 UI 语义：Profile 有锁表示别人正在用；要同时打开必须开 Multi Device Mode，否则报错。[S13][S14] → 规格上应「预检 status，Active 就拒绝」，不要依赖错误文案。
7. **stop 是同步语义的简单接口**（V1 GET，V2 POST JSON），返回 `code: 0` / `msg: success`；**重复 stop 的响应、强制停止、超时参数全部未知**。[S4][S5]
8. **业务错误主要以 JSON `code` 表达**；官方示例只定义了 `0` 与 `-1`，官方博客给出了 `-1` 的具体 `msg`（如 `user account does not exist`）和一个非 -1 的业务码 `8508`（cookie 格式错误）。**HTTP 401/403/429 的真实响应未经官方文档确认。** [S2][S17]
9. **Firefox 只能确定官方给了 Selenium/Marionette 示例**；Playwright 官方文档明确说 `connect_over_cdp` 只支持 Chromium 内核。→ 本仓只支持 Chromium Profile。[S10][S18]
10. **登录态由 AdsPower Profile 持久化，CLI 不应读写 `cookies/*.json`**；但 `clear_cache_after_closing` / `delete_cache=1` 有清掉登录态的风险，必须保持默认 0。[S2][S3][S26]

---

## 1. 地址与传输

### 1.1 官方给出的地址

- 默认访问地址是 `http://local.adspower.net:50325/` 或 `http://localhost:50325/`。[S1]
- 实际地址可从 `local_api` 文件读取：官方正文明确给出 Linux 路径 `~/.config/adspower_global/cwd_global/source/local_api`；Windows / macOS 的路径在官方文档里是**图片**，正文未给出文本。[S1]
- 官方 GitHub README 的说法是：Profile Management → Settings → Cache folder → `local_api` 文件。[S11]
- `[社区]` 第三方指南给出的 macOS 路径是 `~/Library/Application Support/Adspower/local_api`；**该路径未在官方正文中确认，且不同 AdsPower 版本目录名可能不同**（`Adspower` / `adspower_global`）。[S25]

### 1.2 三者关系

- `127.0.0.1` 与 `localhost` 是同一台机器的回环地址；官方排障明确把两者当作 `local.adspower.net` 的替代。[S17]
- `local.adspower.net` 是 AdsPower 提供的**主机名**，解析/映射由 AdsPower 安装环境负责，并不保证在任意机器上可解析。官方排障说它返回 502/503 时改用 `127.0.0.1` 或 `localhost`。[S17]
- → 对 CLI 来说，**默认 `http://127.0.0.1:50325` 最稳**；`local.adspower.net` 只作为用户可覆盖值，不作为默认。

### 1.3 HTTP vs TLS

- 所有官方端点、示例、curl 都是 `http://`；没有任何官方 `https://` 的 Local API 示例。[S1][S2][S3][S10]
- `[未知]` Local API 是否支持 TLS、是否有自签证书模式。**不应假设支持**。

### 1.4 `ADSPOWER_API_BASE` 建议接受形式

建议（设计建议，不是官方事实）：

- 接受 `http://host:port`，默认 `http://127.0.0.1:50325`。
- 允许 `https://` scheme（便于未来反向代理），但不主动使用。
- **拒绝**：带 path / query / fragment / userinfo 的 URL（与本仓 MLX client 的「base URL 固定」思路一致，避免 API key 被发到别的 host）。参考社区 SDK 的同类约束：base_url 必须 HTTP(S)、有 host、不含凭据/query/fragment/base path。[S23]
- 末尾 `/` 统一去掉；端口缺省时不要猜（50325 是默认但可被 `--api-port` 改）。[S12]

---

## 2. 鉴权

### 2.1 格式

- 官方原文：API 授权方式使用 **AUTHORIZATION Bearer Token**，header 为 `header['Authorization']: Bearer xxxxxx`。[S1]
- 所有官方示例都写成 `Authorization: Bearer ${apiKey}`（Python f-string、JS 模板字符串）。[S10]
- 注意：`Bearer` 与 key 之间是**一个空格**；key 不应带前后空白。

### 2.2 Key 的位置与权限要求

- Key 在 AdsPower 客户端 **Automation → API** 页面生成/重置，同时能看到 API 连接状态。[S12]
- 权限：
  - API Overview：**购买付费版**才有 API 权限。[S1]
  - 官方 GitHub README：**Team collaboration version** 可用 API（与「付费版」表述不完全一致）。[S11]
  - 帮助中心：**超级管理员默认有 API 权限**；团队成员需要管理员/负责人分配该权限。[S12]
  - 官方博客补充：给了成员 API 权限 ≈ 给了完整权限（包括能看到平台密码），需要谨慎授权。[S17]
- 重置 key 会让旧 key 立即失效；运行中的服务不能热更新 key，必须停服务后用新 key 重启。[S12]

### 2.3 无 key 模式（本 effort 不支持，仅记录）

- 官方明确支持「关闭接口安全校验、无 API key」启动 Local API 服务，并链接到帮助中心。[S1][S11]
- 头部模式（headless）启动命令本身要求 `--api-key`：`--headless=true --api-key=XXXX --api-port=50325`。[S12]
- `[未知]` 关闭校验时，带一个无效 `Authorization` 头是否被忽略、还是仍报错。**本 effort 不覆盖**，CLI 不应提供半支持开关（与 charter 一致）。

### 2.4 401 / 403 与 key 泄漏

- 官方文档**没有**给出 401/403 的具体响应体或 JSON `code`。[未知]
- `[社区]` 第三方 SDK 把 HTTP 401/403 归类为认证错误、429 归类为限流，其余非 2xx 归类为 API 错误；但它同时说明这是「基于可靠的 HTTP 401/403 信号」，并没有引用官方契约。[S19][S20]
- key 是否会出现在日志/异常中：官方未说明。**设计必须主动保证不出现**：
  - client `__repr__` 脱敏（复用本仓 `MultiloginClient(token=<redacted>)` 的做法）。
  - 异常信息只带 method/path/HTTP status/code/msg，不拼 header。
  - 绝不把 API key 传给 CDP / WebDriver / `/json/version`。社区 SDK 明确做了这条隔离。[S23]

---

## 3. V1 vs V2

### 3.1 端点对照

| 能力 | V1 | V2 | 来源 |
|---|---|---|---|
| 启动 | `GET /api/v1/browser/start?user_id=` | `POST /api/v2/browser-profile/start`（JSON） | [S2][S3] |
| 停止 | `GET /api/v1/browser/stop?user_id=` | `POST /api/v2/browser-profile/stop`（JSON） | [S4][S5] |
| 状态 | `GET /api/v1/browser/active?user_id=` | `GET /api/v2/browser-profile/active?profile_id=` | [S6][S7] |
| 本机所有已开 | `GET /api/v1/browser/local-active` | 官方文档未见 V2 对应页 | [S6] |
| 跨设备状态 | `POST /api/v1/browser/cloud-active`（body `user_ids`，≤100） | 官方文档未见 V2 对应页 | [S8] |
| 健康检查 | `GET /status` | 同左（无版本） | [S9] |

> ⚠️ 修正 map.md 里的一个笔误：V1 状态接口是 **`/api/v1/browser/active`**，不是 `/api/v1/browser/status`。[S6]

### 3.2 参数命名差异

| 概念 | V1 | V2 |
|---|---|---|
| Profile 标识 | `user_id`（必填）/ `serial_number` | `profile_id`（必填）/ `profile_no` |
| 历史页/平台页 | `open_tabs`（0 开 / 1 关） | `last_opened_tabs`（1 继续 / 0 不继续） |
| IP 检测页 | `ip_tab`（1 开 / 0 关） | `proxy_detection`（1 开 / 0 关） |
| 新 IP 检测页 | `new_first_tab` | 无 |
| 密码填充 | `disable_password_filling`（1 禁用） | `password_filling`（1 启用；仅首次打开生效） |
| 密码保存 | `enable_password_saving`（1 允许） | `password_saving`（1 允许；仅 Chrome 内核） |
| 清缓存 | `clear_cache_after_closing` | `delete_cache` |
| headless | `headless` | `headless` |
| CDP 掩蔽 | `cdp_mask` | `cdp_mask` |
| 缩放 | `device_scale` | `device_scale` |

来源：[S2][S3]

> 注意 V1 的 `open_tabs` 语义是反的（0=打开、1=关闭），V2 的 `last_opened_tabs` 是正向的（1=继续）。这是最容易写反的一处。

### 3.3 版本要求

- V1：文档写「确保你的 application 升级到 **3.4.1 或更高**」——这句话在讲 Selenium/Webdriver 的段落里，指代对象有点含糊（大概率指 AdsPower 客户端版本）；各启动参数另有自己的最低版本（见 §4.1）。[S2]
- V2：只写「Please update to the latest patch version to use it」，**没有给最低版本号**。[S3]
- 限流表只适用于 **patch v2.8.2.1 及以上**。[S1]

### 3.4 推荐与理由

**推荐 V2 作为唯一实现**：

1. 官方 Playwright 示例（唯一一个 Playwright + CDP 的官方示例）用的就是 V2 启动。[S10]
2. JSON body 不用对 `launch_args` 做 query 编码，参数类型（bool 用 `"0"/"1"` 字符串）更明确。[S3]
3. stop/status 与 start 对称，错误面更小。[S5][S7]
4. `profile_id` 与本仓 `--profile-id` 的语义直接对齐；V1 的 `user_id` 其实也是同一个值，但命名容易让人以为要额外查询。[S2][S3]

**兼容性风险**：

- V2 最低客户端版本未知；老客户端可能直接 404/未知错误。[S3][未知]
- 缓解：启动前先做一次轻量探活（`GET /status` 或 `GET /api/v2/browser-profile/active`），把「V2 不存在 / 版本过旧」映射成明确的「请升级 AdsPower」文案，而不是静默回退 V1。
- 如果后续必须支持老客户端，再加 V1 fallback；本 effort 不做双栈。

---

## 4. 启动

### 4.1 V1 完整参数表

`GET /api/v1/browser/start`，query 参数，可省略。[S2]

| 参数 | 必填 | 默认 | 说明 | 最低版本 |
|---|---|---|---|---|
| `user_id` | 是 | — | Profile 唯一 ID | — |
| `serial_number` | 否 | — | 填了 `user_id` 时优先 `user_id` | — |
| `open_tabs` | 否 | `0` | 打开平台页或历史页；**0 打开（默认），1 关闭** | ≥2.4.2.9 |
| `ip_tab` | 否 | `1` | 是否打开 IP 检测页；0 不打开，1 打开 | ≥2.5.7.9 |
| `new_first_tab` | 否 | `0` | 新版 IP 检测页；1 新，0 旧 | ≥2.6.6.9 |
| `launch_args` | 否 | — | 浏览器启动参数数组；API 与 Profile 同时设置时 API 优先 | ≥2.4.6.7 |
| `headless` | 否 | `0` | 0 否 / 1 是 | ≥2.4.6.7 |
| `disable_password_filling` | 否 | `0` | 0 否 / 1 禁用填充 | ≥2.4.6.7 |
| `clear_cache_after_closing` | 否 | `0` | 关闭后删缓存 | ≥2.4.7.6 |
| `enable_password_saving` | 否 | `0` | 0 否 / 1 允许保存密码 | ≥2.4.8.7 |
| `cdp_mask` | 否 | `1` | 是否掩蔽 CDP 检测；1 是 / 0 否 | 未标注 |
| `device_scale` | 否 | — | 仅移动 OS；0.1–2，1=100% | 未标注 |

### 4.2 V2 完整参数表

`POST /api/v2/browser-profile/start`，JSON body，可省略。[S3]

| 参数 | 类型 | 必填 | 默认 | 说明 |
|---|---|---|---|---|
| `profile_id` | text | 是 | — | Profile 唯一 ID |
| `profile_no` | text | 否 | — | 填了 `profile_id` 时优先 `profile_id` |
| `launch_args` | list | 否 | — | 同 V1；API 优先于 Profile |
| `headless` | text | 否 | `0` | 1 是 / 0 否 |
| `last_opened_tabs` | text | 否 | `1` | 1 继续上次页面（默认）/ 0 不继续 |
| `proxy_detection` | text | 否 | `1` | 1 打开代理检测页（默认）/ 0 不打开 |
| `password_filling` | text | 否 | `0` | 1 启用 / 0 禁用；**仅 Profile 首次打开生效** |
| `password_saving` | text | 否 | `0` | 1 允许 / 0 不允许；**仅 Chrome 内核** |
| `cdp_mask` | text | 否 | `1` | 1 掩蔽（默认）/ 0 不掩蔽；iOS/Android Profile 强制开启 |
| `delete_cache` | text | 否 | `0` | 关闭后清缓存；磁盘不足建议 1 |
| `device_scale` | text | 否 | — | 仅移动 OS + 128 内核及以上；0.1–2 |

### 4.3 同步还是异步？

- 官方**没有明说**同步/异步，也没有 job id / 轮询接口。[S2][S3]
- `[示例暗示]` 同步：官方三个示例都是 `start` 返回后立刻取 `data.ws.puppeteer` 或 `data.webdriver` 去连接，中间没有任何等待/轮询。[S10]
- 官方帮助存在错误 `100044: Waiting for browser to start timeout, please wait`，说明客户端内部会等待启动并可能超时；但等待时长、超时后浏览器是否仍在后台继续启动，均未知。[S16][未知]
- **对实现的含义**：把 `start` 当成同步调用；HTTP 超时应设得比普通请求长（社区 SDK 单独有 `browser_start_timeout` 和 `browser_probe_timeout` 两个配置，而不是复用普通 HTTP timeout）。[S23]
- **HTTP 200 时浏览器是否一定可连？** 官方不保证；示例暗示可以立即连。建议在 connect 前做一个轻量 `/json/version` 探活，并对 `connect_over_cdp` 做有界重试（本仓 MLX 已有 3 次 + 2s/4s 退避的模式）。[未知][S21][S24]

### 4.4 返回结构

成功：[S2][S3]

```json
{
  "code": 0,
  "data": {
    "ws": {
      "selenium": "127.0.0.1:xxxx",
      "puppeteer": "ws://127.0.0.1:xxxx/devtools/browser/xxxxxx"
    },
    "debug_port": "xxxx",
    "webdriver": "C:\\xxxx\\chromedriver.exe"
  },
  "msg": "success"
}
```

失败：

```json
{ "code": -1, "data": {}, "msg": "failed" }
```

- `ws.puppeteer`：**完整 CDP WebSocket URL**，形如 `ws://127.0.0.1:<port>/devtools/browser/<uuid>`。[S2][S3]
- `ws.selenium`：**只有 `host:port`，没有 scheme**，给 Selenium 的 `debuggerAddress` 用。[S2][S10]
- `debug_port`：**字符串**，调试端口；可以和 `http://127.0.0.1:<port>` 一起作为 `connect_over_cdp` 的 endpoint。[S2][S18]
- `webdriver`：与内核版本匹配的 chromedriver 路径；无需自己下载。[S2][S17]
- Firefox Profile 的返回还会带 `marionette_port`（官方 Firefox Selenium 示例用到）。[S10]

### 4.5 `browser.contexts` 数量

- 官方 Playwright 示例统一用 `browser.contexts[0]`，没有说明数量恒为 1。[S10]
- `[未知]` 是否稳定 1 个 context。**建议与 MLX 分支保持一致：校验 `len(contexts) == 1`，否则 fail-fast**（而不是悄悄取第一个），这样行为可预测、测试可断言。[仓库现状 `utils/browser_session.py:186`]

### 4.6 自动打开的页面

- V1 `ip_tab` 默认 **1** → 默认打开 IP 检测页；`open_tabs` 默认 **0** → 默认打开平台页/历史页。[S2]
- V2 `proxy_detection` 默认 **1** → 默认打开代理检测页；`last_opened_tabs` 默认 **1** → 默认恢复上次页面。[S3]
- 官方 UI 文档也确认：浏览器一打开就是 AdsPower 默认起始页（代理检测页），可以在 Global Settings 关掉。[S13]
- → **规格必须显式传**：V2 `proxy_detection=0`、`last_opened_tabs=0`；V1 `ip_tab=0`、`open_tabs=1`。否则上传逻辑会继承一个非 `about:blank` 的初始页。

---

## 5. Profile 已运行

### 5.1 官方能确认的部分

- 官方 UI 文档：Profile 旁的**锁图标**表示有人正在使用该 Profile；如果仍需打开，必须开启 **Multi Device Mode**。[S13]
- 官方排障页：看到「Please contact the administrator to enable Multi Device mode」时，两个选项是 (1) 让正在使用的人关闭，(2) 开启 Multi Device Mode 让两人同时使用。[S14]
- 跨设备状态接口的说明里有一句关键限制：**如果开了 Multi Device mode，就无法查到具体状态**，返回内容与「Profile 未打开」相同。[S8]

### 5.2 未能确认的部分（重要）

- `[未知]` Profile 已运行时调用 `start` 的**确切 HTTP 状态、JSON `code`、`msg`**。
- `[未知]` 是否会返回**既有的 `ws`**（可 attach），还是会新建第二个实例（Multi Device Mode 下），还是直接报错。
- `[未知]` 错误文案是否包含 "already open" / "in use" / "Multi Device" 等可识别关键词。
- 没有任何官方文档或高可信社区资料给出这三点的确定答案；本机也无法实测。

### 5.3 status 能否可靠判断

- V1 `GET /api/v1/browser/active`：`data.status` 只有两个值 `"Active"` / `"Inactive"`；Active 时同时返回 `ws`。[S6]
- V2 `GET /api/v2/browser-profile/active`：同样 `"Active"` / `"Inactive"`，Active 时返回 `ws` / `debug_port` / `webdriver`。[S7]
- `GET /api/v1/browser/local-active`：列出**当前设备**所有已开浏览器，每项含 `user_id` / `ws` / `debug_port` / `webdriver`。[S6]
- → 对「本机是否已开」的判断，`active` 是官方定义的、可靠的；但**在 Multi Device Mode 下跨设备状态不可靠**（见 §5.1）。[S8]

### 5.4 建议策略（设计决策，非事实）

采用「**预检 + 谁启动谁停止**」：

1. start 前先 `GET .../active?profile_id=...`。
2. `Inactive` → 本次调用 start，标记 `owned=True`，结束时 stop。
3. `Active` → **不 start、不 attach、不 stop**，直接失败退出 `1`，文案提示「Profile 正在被占用，请在 AdsPower 中关闭或等待对方释放」。
   - 理由：无法证明现有 `ws` 属于本进程/本账号；attach 会让「谁停止」失控，stop 会打断别人的会话。
4. status 查询本身失败（网络/鉴权）→ 退出 `1`，不要「猜一个」继续 start。
5. 若未来确认 start 在已运行时返回既有 `ws`，再考虑可选的 `--attach` 模式；本 effort 不做。

> 置信度：策略本身是保守且正确的；但「Active 就拒绝」这个选择建立在「start 行为未知」之上，需要在真实环境用一次 smoke 验证（见 §13）。

---

## 6. 停止

### 6.1 接口与返回

- V1：`GET /api/v1/browser/stop?user_id=<id>`，成功 `{"code":0,"data":{},"msg":"success"}`，失败 `{"code":-1,"data":{},"msg":"failed"}`。[S4]
- V2：`POST /api/v2/browser-profile/stop`，body 为 `{"profile_id": "..."}`（或 `profile_no`），成功 `{"code":0,"msg":"success"}`，失败 `{"code":-1,"msg":"failed"}`；**V2 成功响应没有 `data`**。[S5]
- 官方示例是 `start` → 操作 → `stop` 顺序调用，没有轮询确认；`[示例暗示]` 同步。[S10]

### 6.2 重复 stop / 幂等

- `[未知]` 已停止时再次 stop 的响应（是 `code: 0`，还是 `code: -1` + 某个 msg）。
- 官方没有幂等声明；也没有「profile already stopped」这类文案的文档。
- **建议**：stop 视为 best-effort；无论返回什么，都只记 warning，不影响已上传结果（与 ticket 04 的既定方向一致）。不要因为 stop 失败把退出码从 `0` 改成 `1`。

### 6.3 强制停止 / 超时

- 官方 stop 接口**没有** `force` / `timeout` / `wait` 参数。[S4][S5]
- `[社区]` 第三方 SDK 暴露了 `POST /api/v2/browser-profile/stop-all`（停止本机全部 Profile）；官方 V2 文档导航里没有这一页，按社区来源对待，本仓不应使用（会误杀别的 Profile）。[S19][S22]
- → 规格里不要设计「强制停止」；stop 失败就交给调度侧清理（与本仓 MLX 的 warning 语义一致）。

---

## 7. 错误与限流

### 7.1 是否始终 HTTP 200？

- 官方文档的「Operation failed」示例只有 JSON body，没有给 HTTP status。[S2][S3][S4][S5]
- 官方博客把业务错误写成 `{ code: -1, msg: ... }` 的形状，也没有提 HTTP 状态。[S17]
- `[未知]` 是否「业务错误永远 HTTP 200」。**不能假设**。
- 实现上应同时处理两层：
  1. HTTP 层：连接失败 / 超时 / 非 2xx；
  2. 业务层：HTTP 2xx 但 `code != 0`。
  社区 SDK 就是这么做的（先看 status，再解析 envelope 的 `code`）。[S20]

### 7.2 已能确认的 code / msg

| 来源 | 形状 | 含义 |
|---|---|---|
| 官方所有失败示例 | `code: -1`, `msg: "failed"` | 通用失败，**没有细分原因** |
| 官方博客 | `{"code":-1,"msg":"group_id is required"}` | 创建 Profile 缺必填参数 |
| 官方博客 | `{ code: -1, msg: 'user account does not exist' }` | **Profile 不存在 / ID 错误** |
| 官方博客 | `{ data: {}, msg: 'cookie format error.', code: 8508 }` | Cookie 格式错误（非 -1 的业务码确实存在） |

来源：[S2][S3][S17]

> 结论：`code` 不只有 `0/-1`，至少还存在 `8508` 这类业务码；但官方没有发布完整的错误码表。

### 7.3 各类失败的可识别特征

| 场景 | 可识别特征 | 置信度 |
|---|---|---|
| Profile 不存在 | `msg` 含 `user account does not exist`（官方博客原文） | 高（官方博客） |
| 缺参数 | `msg` 含 `xxx is required` | 中（官方博客举例） |
| API 未开启 / 服务未启动 | 连接被拒 / 超时；`/status` 也失败 | 高（网络层推断） |
| API key 无效 / 无权限 | `[未知]`：可能 HTTP 401/403，也可能 200 + `code != 0` | 低 |
| 限流 | `[未知]`：官方只给频率表，没给超限响应 | 低 |
| Profile 被占用 | `[未知]`：官方只给 UI 的锁 + Multi Device Mode 文案 | 低 |
| 内核未下载 / 内核版本不匹配 | `[未知]`（API 层）；UI 侧有 `100001 Failed to start browser`、`100044 Waiting for browser to start timeout` 两个错误页，但它们是客户端错误码，不保证原样出现在 API `code` 里 | 低 |

来源：[S1][S15][S16][S17]

### 7.4 限流

- 官方频率限制（仅 patch v2.8.2.1+）：
  - Profile 数 0–200：**2 次/秒**
  - 200–5000：**5 次/秒**
  - >5000：**10 次/秒**
- 另有部分接口限制 **1 次/秒**（官方用图片列出，正文不可读，无法确认具体是哪几个）。[S1]
- `[未知]` 超限时是 HTTP 429、还是 200 + 某个 code/msg；是否带 `Retry-After`。
- **建议**：
  - 本仓一次 CLI 调用只会打 3–4 个请求（status → start → status? → stop），正常不可能触发限流。
  - 仍然对 429 做「有界退避 + 少量重试」（例如 1s/2s，最多 2 次），只对**幂等读**重试；start/stop 这种有副作用的不要自动重试，先查 status 再决定。
  - 不实现客户端限流器（过度设计）；社区 SDK 的 `AdsPowerRatePolicy` 是给批量管理 Profile 的场景用的。[S23]

---

## 8. 内核与自动化

### 8.1 Chromium vs Firefox

- 官方 Code Samples 分两节：**Chrome**（Selenium / Playwright / Puppeteer）与 **Firefox**（只有 Selenium）。[S10]
- Firefox 示例要求 **patch 2.6.9.4+、Firefox 123+**，用 `data.webdriver` + `data.marionette_port`，以 `--connect-existing` 方式接入。[S10]
- Firefox 章节**没有** Playwright / Puppeteer / `ws.puppeteer` 示例。
- Playwright 官方文档明确：`connect_over_cdp` **只支持 Chromium 内核的浏览器**。[S18]
- → **对 AdsPower Firefox Profile，Playwright/CDP 路线不支持**。本仓应只支持 Chromium 内核 Profile；Firefox Profile 直接报「不支持的内核」并退出 `1`（或按 ticket 07 的平台策略处理）。
- `[未知]` 如何通过 API 判断某个 Profile 是 Chromium 还是 Firefox 内核（可能需要 Query Profile，本 effort 不做 Profile 管理，建议运行期靠 start 返回里有没有 `ws.puppeteer` 判断）。

### 8.2 `cdp_mask` 的影响

- 官方定义只有一句：「是否掩蔽 CDP 检测。1 是（默认），0 否。」[S2][S3]
- `[未知]` 具体掩蔽了什么（`navigator.webdriver`？CDP 相关 header？Runtime.enable 检测？），以及是否会影响 Playwright/patchright 的 `connect_over_cdp`。
- 官方示例 `connect_over_cdp` 时**没有**把 `cdp_mask` 设为 0，说明默认 1 与 Playwright 连接是兼容的。[S10]
- **建议**：保持默认 `1`，不要为了「更隐蔽」去调它；在 smoke 里验证 `connect_over_cdp` 能成功即可。

### 8.3 与 patchright 的兼容性

- 本仓已依赖 `patchright==1.64.4`（`pyproject.toml:14`），其 Playwright 版本 ≥1.60，因此 `connect_over_cdp(..., no_defaults=True)` 可用。[S18]
- 本仓 MLX 分支已经在用 `no_defaults=True`（`utils/browser_session.py:214-218`），AdsPower 可以复用同一套连接逻辑。
- 官方示例用的是 stock Playwright 的 `connect_over_cdp(ws.puppeteer)`，没有 `no_defaults`；`[示例暗示]` 说明基本连接可行，但**没有 patchright 的官方验证**。
- Playwright 文档的警告值得记录：如果浏览器不是用 Playwright 的同一组启动参数启动的，连接后部分 Playwright 功能可能不工作；`no_defaults=True` 的作用是**不要覆盖已有默认 context 的 accept_downloads / 字体 / focus / media 等设置**，正好适合接管「用户已有的浏览器」。[S18]
- → 推荐：`playwright.chromium.connect_over_cdp(ws_puppeteer, timeout=10_000, no_defaults=True)`，然后 `contexts[0]`。

### 8.4 ws URL vs http port

- `connect_over_cdp` 的 `endpoint_url` **同时接受** `ws://.../devtools/browser/<id>` 和 `http://host:port/`。[S18]
- AdsPower 直接给了 `ws.puppeteer`，优先用它，避免自己拼 `http://127.0.0.1:<debug_port>` 时把端口类型/主机搞错。
- 在 Docker/远程拓扑下，返回的 `ws` 里通常是 `127.0.0.1`，容器内不可达；社区 SDK 提供 `rewrite_loopback_to_api_host` 选项来改写 host，并警告默认不要改写（会触发 CDP WebSocket host-header 校验失败）。[S23]
- `[未知]` AdsPower 的 CDP WebSocket 是否校验 `Host` header。本仓 v1 在本地跑，直接用原样 `ws` 即可。

---

## 9. 拓扑

- Local API 是**本机**服务：默认 `127.0.0.1:50325`，由本机 AdsPower 客户端提供。[S1][S17]
- `local.adspower.net` 只是给本机回环起的主机名；官方排障建议在异常时换成 `127.0.0.1`/`localhost`。[S17]
- **跨机**：
  - 官方有 `/api/v1/browser/cloud-active` 用于**跨设备查询 Profile 是否打开**，单次最多 100 个；但这不等于「可以远程调用另一台机器的 Local API」。[S8]
  - `[未知]` Local API 是否监听 `0.0.0.0`、是否支持被远程访问。官方没有文档。
- **Docker**：官方没有 Docker 拓扑文档；`[社区]` 第三方 SDK 给出 `http://host.docker.internal:50325`（Docker Desktop）和 Linux 下 host-gateway 映射，并提醒返回的 `127.0.0.1` CDP 端点需要改写。[S23]
- **无桌面 Linux / headless**：官方**支持**。前置条件：AdsPower 客户端 **v3.3.2+**、内核 **v2.4.2.8+**、有 Local API 权限。启动方式：
  - Windows: `"AdsPower Global.exe" --headless=true --api-key=XXXX --api-port=50325`
  - macOS: `"/Applications/AdsPower Global.app/Contents/MacOS/AdsPower Global" --args --headless=true --api-key=XXXX --api-port=50325`
  - Linux: `adspower_global --headless=true --api-key=XXX --api-port=50325`
  - 启动后 CLI 会打印返回地址；GUI 模式与 headless 模式**不能同时**运行；停止服务用 Ctrl+C。[S12]
- 与本 effort 的关系：charter 已把跨机 / Docker / 无桌面 Linux 列入 out of scope；本节的结论是「官方只保证本机 + headless CLI，Docker 属社区经验」。

---

## 10. 登录态与页面

### 10.1 Profile 持久化

- AdsPower 的 Profile 本身就是持久化容器（cookie / localStorage / IndexedDB / 扩展数据 / 历史等），关闭浏览器不会丢失登录态，除非主动清缓存。[S26]
- 官方「Cache Data」页明确：清理缓存「may clear all info in the profile, such as the login status of websites」。[S26]
- → CLI **不需要也不应该**读写 `cookies/*.json`。登录态完全由 AdsPower 管理；`--account` 只作为日志标签（与 charter 一致）。
- `[未知]` 关闭浏览器时是否有「未 flush 的 session cookie」丢失风险；官方没有这类说明。

### 10.2 清缓存参数的风险

- `clear_cache_after_closing`（V1）/ `delete_cache`（V2）默认都是 `0`。[S2][S3]
- 官方建议「磁盘空间不足时才设为 1」。[S2][S3]
- 一旦设为 1，可能清掉 cookie / 登录态（与 §10.1 的缓存清理语义一致）。[S26]
- **规格必须固定为 0**，且不暴露成 CLI flag；否则一次上传后账号掉登录，违背「复用 Profile 登录态」的目标。

### 10.3 页面初始状态

- 见 §4.6：默认会开 IP 检测页 / 历史页。
- 建议：start 时显式关闭；如果仍有残留页面，**不要**盲目 `pages[0]`，而是复用 uploader 现有的「新建 page / 选 page」逻辑（ticket 03/04 决策）。

---

## 11. 错误映射表（建议）

退出码语义沿用本仓：`0` 成功、`1` 运行失败、`2` 用法错误、`10` 需登录、`130` 用户中断。

| 触发条件 | HTTP / `code` / `msg` 特征 | CLI 失败类别 | 退出码 | 可重试？ | 应 stop？ |
|---|---|---|---|---|---|
| AdsPower 未启动 / 端口未监听 | 连接拒绝、`ConnectionError` | 运行失败：Local API 不可达 | 1 | 否（提示启动 AdsPower） | 否 |
| `local.adspower.net` 解析/代理异常 | HTTP 502/503、代理错误 | 运行失败：地址不可达 | 1 | 可换 `127.0.0.1` 后重试 | 否 |
| 请求超时（探活/状态） | timeout | 运行失败：Local API 超时 | 1 | 是（1 次） | 否 |
| key 无效 / 无 API 权限 | `[未知]` HTTP 401/403 或 `code != 0` | 运行失败：鉴权失败 | 1 | 否 | 否 |
| API 未开启 / 非付费版 | `[未知]`（可能连接成功但 `code != 0`，或 401/403） | 运行失败：API 未启用 | 1 | 否 | 否 |
| 限流 | `[未知]` HTTP 429 / 特定 `code` | 运行失败：请求过快 | 1 | 是（有界退避，仅读） | 否 |
| 服务端 5xx | HTTP 5xx | 运行失败：AdsPower 内部错误 | 1 | 是（1 次） | 否 |
| Profile 不存在 | `code: -1`, `msg: "user account does not exist"` | 运行失败：Profile 不存在 | 1 | 否 | 否 |
| 缺少 `--profile-id` | 本地校验 | **用法错误** | 2 | 否 | 否 |
| `ADSPOWER_API_BASE` 格式非法 | 本地校验 | **用法错误** | 2 | 否 | 否 |
| Profile 已运行（预检 Active） | `data.status == "Active"` | 运行失败：Profile 被占用 | 1 | 否（需人工释放） | **否**（不是本次启动） |
| start 返回 `code != 0`、msg 含 "Multi Device" / "already open" | `[未知]` 具体字节 | 运行失败：Profile 被占用 | 1 | 否 | **否**（start 未成功，可能属于别人） |
| start 成功但缺少 `data.ws.puppeteer` | `code: 0`，字段缺失 | 运行失败：协议异常 | 1 | 否 | **是**（本次已启动） |
| start 成功但 CDP 连不上 | `code: 0`，`connect_over_cdp` 失败 | 运行失败：CDP 连接失败 | 1 | 有界重试后失败 | **是**（本次已启动） |
| `contexts` 数量 ≠ 1 | 断言失败 | 运行失败：上下文异常 | 1 | 否 | **是** |
| 内核未下载 / 启动超时 | `[未知]`（UI 侧 100001 / 100044） | 运行失败：Profile 无法启动 | 1 | 启动超时可在确认 Inactive 后重试 1 次 | 视 start 是否返回成功 |
| 返回不是合法 JSON / 缺 `code` | 解析失败 | 运行失败：协议漂移 | 1 | 否 | 否 |
| stop 失败 | 任意 | **只 warning**，不改退出码 | 保持原退出码 | 否 | —（已尝试） |
| 用户 Ctrl+C | `KeyboardInterrupt` / `CancelledError` | 用户中断 | 130 | 否 | 是（shield 后尽力 stop） |
| 上传阶段登录失效 | uploader 的 `LoginRequiredError` | 需登录 | 10 | 否 | 是（正常退出路径） |

说明：

- 「应 stop」列严格遵循「谁启动谁停止」。只有 `start` 明确返回成功、本次调用创建/接管了浏览器时，才 stop。
- `Profile 不存在` 映射为 `1` 而不是 `2`：它是运行期环境状态，不是命令行语法错误；与 MLX 现有行为（start 失败 → RuntimeError → 1）一致。这一点留给 ticket 02 最终确认。
- 所有 `[未知]` 行在实现时必须按「保守分支」处理：不重试有副作用的请求，不 stop 非本次启动的 Profile。

---

## 12. 对 ticket 02 / 03 / 04 的直接影响

### 12.1 ticket 02（CLI 契约）

1. **`--profile-id` → AdsPower `profile_id`**（V2 命名），不要叫 `user_id`；内部可以保留 `user_id` 作为 V1 兼容别名，但 CLI 表面只暴露 `profile_id`。[S3]
2. **`ADSPOWER_API_BASE` 的校验规则要写进用法错误**（非法 URL → 退出 `2`）。[S23]
3. **新增错误文案**：Local API 不可达、鉴权失败、API 未启用、Profile 不存在、Profile 被占用、内核/启动失败、CDP 连接失败、上下文异常。后三者建议保留 AdsPower 原始 `code`/`msg`。
4. **`--headless` 映射为 `headless: "1"`**（V2 是字符串 `"0"/"1"`，不是 JSON bool）。[S3]
5. **不要暴露** `clear_cache_after_closing` / `delete_cache` / `cdp_mask` / `launch_args` 等危险参数；由 provider 固定为安全值。
6. **退出码**：本文 §11 可直接作为 ticket 02 的候选表；需要 ticket 02 最终裁决「Profile 不存在 = 1」和「stop 失败不影响退出码」。

### 12.2 ticket 03（provider 接缝）

1. **endpoint 类型不统一**：MLX 返回 `port`，AdsPower 返回 `ws.puppeteer`。建议 target/client 暴露一个 `connect_url: str`（MLX 拼 `http://127.0.0.1:{port}`，AdsPower 原样用 `ws://...`），`BrowserSession.mode` 只做标签，不参与连接分支。[S2][S3]
2. **`connect_over_cdp` 的 kwargs 可以共用**：`timeout=10_000`、`no_defaults=True`；patchright 1.64.4 支持。[S18]
3. **探活/start/stop 的 HTTP 细节留在各自 client**：AdsPower 的 `code`/`msg` 解析、`data.ws.puppeteer` 提取、`profile_id` 选择器都封装在 `AdspowerClient`，不泄漏到 `browser_session`。
4. **不要为 AdsPower 复制 `_multilogin_session`**：建议模板方法固定顺序为 `probe → status(optional) → start → connect(retry) → contexts==1 → yield → disconnect → stop(shield)`；provider 只实现 4 个原语（probe/status/start/stop）和错误映射。
5. **测试注入**：沿用 `http_get` 风格；AdsPower client 建议注入 `http_get` / `http_post`，不要引入 `requests.Session` 单例。`tests/fakes.py` 增加一个可按顺序返回 status/start/stop JSON 的 fake。
6. **API key 脱敏**：client `__repr__` 必须 redact；测试里断言异常字符串不含 key（可参考 MLX 的测试）。

### 12.3 ticket 04（生命周期与所有权）

1. **预检 `active`**：`Active` → 拒绝（退出 1），不 attach、不 stop；`Inactive` → start 并标记 owned。[S6][S7]
2. **start 失败绝不 stop**（与 MLX 现有「Start 在 try 之外」的设计一致，`utils/browser_session.py:166-174`）。
3. **start 成功但 CDP 失败 → 要 stop**（本次已创建会话），并附上 status 查询结果作为诊断。
4. **`contexts` 严格 == 1**，否则 fail-fast 并 stop。[S10]
5. **stop 用 `asyncio.shield` + `to_thread`**（AdsPower client 是同步 `requests`），失败只 warning；不引入 `stop-all`。
6. **并发/锁**：不加库内锁；Profile 占用由预检 + 服务端行为兜底（charter 倾向不加锁）。
7. **重复 stop / 强制 stop**：按 §6 的未知处理——忽略结果、只 warning，不重试。
8. **页面固定**：start 时 `proxy_detection=0`、`last_opened_tabs=0`；不要依赖默认值。[S3]
9. **日志**：`profile_id`、endpoint host/port、耗时、`code`/`msg`；不记录 key；`ws` 只记录 host:port 或脱敏后的 URL（如果 `ws` 里含 token 才需要脱敏——当前格式没有 token）。

---

## 13. 置信度与未知

### 13.1 高置信度（官方正文直述）

- 默认地址、`local_api` 文件、Bearer 鉴权、付费/权限要求。[S1][S11][S12]
- V1/V2 的路径、方法、参数、默认值、响应结构。[S2][S3][S4][S5][S6][S7]
- `ws.puppeteer` 的格式、`ws.selenium` 没有 scheme、`debug_port` 是字符串。[S2][S3]
- V2 官方 Playwright 示例用 `connect_over_cdp` + `contexts[0]`。[S10]
- Playwright `connect_over_cdp` 只支持 Chromium。[S18]
- headless CLI 的三平台命令与前置版本。[S12]
- Profile 有锁 + Multi Device Mode 的 UI 语义。[S13][S14]
- `user account does not exist` / `8508` 两个具体错误。[S17]

### 13.2 中等置信度（示例暗示 / 官方博客）

- start 是同步调用、返回即可连接。[S10]
- `contexts` 通常为 1。[S10]
- 业务错误以 `code != 0` 表达、HTTP 状态不保证 200。[S2][S17]
- 频率限制的实际执行方式。[S1]

### 13.3 未知（必须在 smoke 中验证）

| # | 未知项 | 验证方式 |
|---|---|---|
| U1 | Profile 已运行时 start 的 HTTP/`code`/`msg`，是否返回既有 `ws` | 真实环境：先 start 一次，再 start 同一 Profile，记录完整响应 |
| U2 | Multi Device Mode 开启时 start 的行为（新实例？复用？） | 开/关 Multi Device 各跑一次 U1 |
| U3 | 重复 stop 的响应 | 连续 stop 同一 Profile 两次，记录第二次 |
| U4 | 401/403 的真实响应（HTTP 状态与 body） | 用错误 key 调 `/status` 和 `start` |
| U5 | 429 / 限流的真实响应与 `Retry-After` | 脚本快速打 10+ 次 `/status`（只读） |
| U6 | API 未开启 / 非付费版 / 无权限的响应差异 | 分别用未开 API、普通成员、无权限账号调一次 |
| U7 | Profile 不存在时 V2 的 `code`/`msg`（是否仍是 `user account does not exist`） | 用不存在的 `profile_id` 调 V2 start |
| U8 | `contexts` 是否恒为 1 | 对同一 Profile 连续启动 10 次，断言 |
| U9 | `cdp_mask=1` 是否影响 patchright | 用 patchright 连一次，跑一个 `Runtime.evaluate` + `navigator.webdriver` 检查 |
| U10 | V2 的最低客户端版本 | 在旧版 AdsPower 上调 V2，记录 404/错误 |
| U11 | 内核未下载时 API 的 `code`/`msg` | 用一个未下载内核的 Profile start |
| U12 | macOS `local_api` 的准确路径 | 装 AdsPower 后找 `~/Library/Application Support/**/local_api` |
| U13 | Local API 是否可被远程访问 / Docker 可达 | 从另一台机器/容器访问 `host:50325` |
| U14 | stop 是否等待浏览器真正退出（同步性） | stop 后立即 status，看是否已 Inactive |
| U15 | Firefox Profile 在 V2 的返回（是否有 `ws.puppeteer`） | 用一个 Firefox Profile start |

### 13.4 本机限制

- 没有安装 AdsPower，无法做任何 live 验证；`/Applications` 无匹配、`50325` 未监听。
- 因此本文的「推荐」都按**保守分支**设计：不依赖未证实的错误文案、不 attach 未知会话、不重试有副作用的请求。

---

## 14. 来源登记表

> 所有 URL 的检索日期均为 **2026-11-06**。

| ID | 类型 | URL | 用途 |
|---|---|---|---|
| S1 | 官方文档 | https://localapi-doc-en.adspower.com/docs/Rdw7Iu | API Overview：地址、`local_api`、付费版、限流、Bearer、无 key 模式 |
| S2 | 官方文档 | https://localapi-doc-en.adspower.com/docs/FFMFMf | Open Browser V1：路径、参数、默认值、版本、响应 |
| S3 | 官方文档 | https://localapi-doc-en.adspower.com/docs/Open-Browser-V2 | Open Browser V2：路径、参数、默认值、响应 |
| S4 | 官方文档 | https://localapi-doc-en.adspower.com/docs/DXam94 | Close Browser V1 |
| S5 | 官方文档 | https://localapi-doc-en.adspower.com/docs/Close-Browser-V2 | Close Browser V2 |
| S6 | 官方文档 | https://localapi-doc-en.adspower.com/docs/YjFggL | Check Browser Status V1（`/api/v1/browser/active`、`local-active`） |
| S7 | 官方文档 | https://localapi-doc-en.adspower.com/docs/Check-Browser-Status-V2 | Check Browser Status V2 |
| S8 | 官方文档 | https://localapi-doc-en.adspower.com/docs/Check-Browser-Status-crossdevices | 跨设备状态、Multi Device 限制 |
| S9 | 官方文档 | https://localapi-doc-en.adspower.com/docs/6DSiws | `GET /status` 健康检查 |
| S10 | 官方文档 | https://localapi-doc-en.adspower.com/docs/K4IsTq | 官方 Selenium / Playwright / Puppeteer / Firefox 示例 |
| S11 | 官方仓库 | https://github.com/AdsPower/localAPI | README：权限、`local_api` 获取方式、无 key 模式 |
| S12 | 官方帮助 | https://help.adspower.com/docs/api | API key 生成、headless 启动命令、版本要求、GUI/headless 互斥 |
| S13 | 官方帮助 | https://help.adspower.com/docs/opening_closing_browser_profiles | Profile 锁、Multi Device Mode、默认 IP 检测页 |
| S14 | 官方帮助 | https://help.adspower.com/docs/Please-contact-the-administrator-to-enable-Multi-Device-mode-in-the-Global-Settings-section | 已运行 Profile 的 UI 错误与两种处理 |
| S15 | 官方帮助 | https://help.adspower.com/docs/Error-100001-Failed-to-start-browser | 客户端错误 100001 |
| S16 | 官方帮助 | https://help.adspower.com/docs/Error-100044-Waiting-for-browser-to-start-timeout-please-wait | 客户端错误 100044（启动等待超时） |
| S17 | 官方博客 | https://www.adspower.com/blog/troubleshooting-common-issues-with-adspower-api-a-complete-guide | 502/503 换 127.0.0.1/localhost、`user account does not exist`、`8508`、无 driver 下载 |
| S18 | 第三方官方文档 | https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp | `connect_over_cdp` Chromium-only、`no_defaults`、ws/http endpoint |
| S19 | 社区 | https://github.com/CrocoFactory/adspower/blob/main/docs/errors.md | 第三方 SDK 的错误分类（401/403→auth，429→rate limit） |
| S20 | 社区 | https://github.com/CrocoFactory/adspower/blob/main/adspower/protocol.py | 第三方 SDK 如何同时处理 HTTP 状态与 `code` envelope |
| S21 | 社区 | https://github.com/CrocoFactory/adspower/blob/main/adspower/automation/playwright.py | 第三方 SDK 的 `connect_over_cdp(..., no_defaults=True)` 用法 |
| S22 | 社区 | https://github.com/CrocoFactory/adspower/blob/main/adspower/resources/browsers.py | 第三方 SDK 的 start/stop/status 实现与 `stop-all` |
| S23 | 社区 | https://github.com/CrocoFactory/adspower/blob/main/docs/configuration.md | base_url 约束、Docker 拓扑、CDP endpoint 改写、key 不转发 |
| S24 | 社区 | https://github.com/CrocoFactory/adspower/blob/main/skills/adspower-python/references/troubleshooting.md | 分层排障建议（不可达 / 认证 / 限流 / CDP 不可达） |
| S25 | 社区 | https://webscrape.dev/guides/antidetect-browser-automation | macOS `local_api` 路径（未官方确认） |
| S26 | 官方帮助 | https://help.adspower.com/docs/Cache-Data | 缓存/登录态清理风险 |

---

## 15. 一句话给规格

> AdsPower 模式 = 「预检 `active` → V2 `start`（headless 按 CLI，关掉 IP 检测与历史页，不动清缓存）→ `connect_over_cdp(ws.puppeteer, no_defaults=True)` → `contexts[0]` → 上传 → disconnect → 仅当本次启动时 `stop`」；所有无法证实的错误分支按「不重试、不乱 stop」处理。
