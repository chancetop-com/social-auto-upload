# 01 — GoLogin 的 API 面：Local API、云端运行时与 SDK 行为

Status: resolved
Type: research
Blocked by: —
Assignee: LukeChen

## Question

在**只有官方文档与官方 SDK 源码、当前机器未安装 GoLogin** 的前提下，把 GoLogin 的事实面整理成可直接引用的表。必须回答：

1. **Local API**
   - 基址与端口（是否固定、是否可配置）；是否需要 API token，header 还是 query。
   - 启动/停止/状态/健康检查的准确端点、方法、请求字段（profile id 字段名、headless/sync 开关）与响应结构（CDP `wsUrl` 在哪个字段）。
   - 错误信封、HTTP 状态码、429 限流、常见失败（Profile 已运行、不存在、token 无效）。
   - 是否支持 headless；支持哪些浏览器内核（CDP 需要 Chromium）。
2. **云端运行时（关键）**
   - GoLogin 是否真的提供「浏览器进程跑在云端」的产品？官方名称与文档地址。
   - 客户端如何接入：是否有公开端点启动云端浏览器并返回远程 CDP WebSocket？还是只有 Web UI / 桌面客户端 / 专有隧道？
   - 若存在远程 CDP：URL scheme、鉴权方式（bearer / 签名短链 / session cookie）、是否被官方文档明确为可直接交给 Playwright `connect_over_cdp`。
   - 明确区分三种情况：(a) Profile 存云端 + 浏览器本地；(b) 浏览器云端 + 远程接入；(c) 云手机等其他产品。
3. **官方 SDK（`github.com/gologinapp/pygologin`，PyPI `gologin`）**
   - `start()` 的逐步行为：先调 Local API 再回退下载 Orbita？下载什么、从哪下？
   - SDK 是否存在云端浏览器代码路径，还是永远启动本地进程？
   - 依赖清单；`create()` / `getProfile` 对 `api.gologin.com` 做什么、用什么鉴权。
   - 有没有「纯 HTTP + Playwright 复现不了」的能力；若有，具体是哪一项。
4. **Cloud API（`api.gologin.com`）**
   - 基址、鉴权、与启动相关的端点（profile get、profile token、start/stop 若有）。
   - Profile id 格式；限流与错误结构。
5. **运行时与内核**
   - 官方对 CDP / Playwright / Puppeteer 的支持声明，按运行时（本地/云端）与内核（Chrome/Orbita vs Firefox）分开。

## Context

- charter 见 [map.md](../map.md)。
- 现有 provider 形状参照 `utils/adspower.py` 与 `utils/managed_browser.py`。
- 结论写入 [`research/01-gologin-api-surfaces.md`](../research/01-gologin-api-surfaces.md)，每条事实带来源 URL，并单列 **Confidence & gaps**。

## Answer

完整事实表见 [`research/01-gologin-api-surfaces.md`](../research/01-gologin-api-surfaces.md)（649 行，逐条带来源）。一句话结论：**云端有、本地无。**

- **云端**：Cloud Browser 是真实的云托管 Chromium/Orbita。接入点是 `wss://cloudbrowser.gologin.com/connect?token=<dev token>&profile=<id>`，官方 Playwright 示例只用 `aiohttp` + `playwright` 直接 `connect_over_cdp`；文档明确写「standard CDP endpoint… no proprietary SDK」。停止 `DELETE https://api.gologin.com/browser/{id}/web`（204）；启动 `POST /browser/{id}/web`（202，`isHeadless` 默认 false、`maxLifeTimeMinutes` 默认 15）。鉴权：connect 用 `?token=`，REST 用 `Authorization: Bearer`。
- **本地**：不存在本地 HTTP API。docs 索引无 Local API 页、OpenAPI 57 条路径全在 `api.gologin.com`、两套官方 SDK 都不调 localhost HTTP。`36912` 端口无任何一手来源。本地运行 = 自己下载 Orbita（`orbita-browser-{mac,linux,windows}.gologin.com/orbita-browser-latest-{major}.*`）、生成 `Default/Preferences` + `orbita.config`、调私有端点 `/browser/features/{id}/info-for-run` 与 `profile-params-for-orbita-token`、`Popen --remote-debugging-port`。
- **硬限制**：HTTP 429 **永久吊销 token**（不是冷却）；云会话默认 15 分钟寿命 + 15 分钟空闲回收、并发 1–4、仅付费版；仅 Chromium；Profile id 是 24 位 hex。
- **SDK 代价**：`gologin` 依赖 `selenium`、`webdriver_manager`、`sentry-sdk`，默认开遥测。
- **补充（用户质疑后复核）**：存在一个文档化的本地 HTTP 面，但它属于 **Agent Browser CLI 的 daemon**（`gologin-agent-browser-cli`，Node 20+，`127.0.0.1:44778`），不是桌面应用的 API。它是**命令面**（`open`/`snapshot`/`click`/`upload`），内部自己持有 Playwright `connectOverCDP`，**不暴露底层 CDP 端点**；且本地起 Orbita 仍走 Node SDK。对以 Playwright 为基础的本仓库不可用。详见 research 文件 §9。

## Resolution

云端运行时可以零 SDK 实现；本地运行时在「零依赖」约束下等于重写 SDK。取舍移交 [02 — 运行时取舍与 SDK 边界](./02-runtime-scope-and-sdk-boundary.md)。
