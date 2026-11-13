# GoLogin 浏览器模式 — 路线图

## Destination

一份可直接交给后续会话实施的 GoLogin 浏览器模式设计规格：在不改变本地模式与现有 MLX / AdsPower 可观察行为的前提下，新增由 `GOLOGIN_API_TOKEN` 激活的 GoLogin managed provider，由 `GOLOGIN_RUNTIME` 选择**本地运行时**（浏览器跑在本机，默认）或**云端运行时**（浏览器跑在 GoLogin 云端），经 CDP 复用 Profile 登录态跑原有上传逻辑，并尽可能不引入 `gologin` SDK。本轮**只交规格，不实现**。

## Notes

### 本会话已确认的 charter

- **产物**：只交 `.scratch/gologin-browser-mode/spec.md`；实现不在本轮范围，后续另开 effort。
- **两种运行时都要覆盖**：本地 = 本机浏览器（GoLogin 桌面应用的本地 HTTP API）；云端 = GoLogin 云端浏览器。两者是 GoLogin 侧的运行时选择，不是仓库的「本地模式」。**本地 API 已由 ticket 10 从安装包源码确认存在**（默认 36912、被占则递增；`POST /browser/start-profile {profileId, sync:true}` → `wsUrl`）。
- **激活**：`GOLOGIN_API_TOKEN` 非空（strip 后）即进入 GoLogin 模式；未设置、空串或纯空白不激活。
- **运行时选择**：`GOLOGIN_RUNTIME`，`0` = 本地（缺省/空也是本地），`1` = 云端。该变量单独存在不激活任何模式，与 `ADSPOWER_API_BASE` 同类：只做配置，激活只看凭据。
- **三方冲突**：`MLX_API_TOKEN` / `ADSPOWER_API_KEY` / `GOLOGIN_API_TOKEN` 中任意两个及以上非空 → 退出 `1`，文案点名所有冲突变量；沿用现有 `credentials_conflict()` 的位置与语义。
- **平台覆盖**：与 MLX / AdsPower 完全对齐——16 个托管平台全部可用；Bilibili（`biliup` 子进程）直接拒绝；`verify` / `delete` 仍走本地 cookie 模式。
- **不引入 SDK（硬约束，已确认可行）**：`pyproject.toml` 不新增任何 GoLogin 相关依赖。**本地与云端都是纯 HTTP + `connect_over_cdp`**：本地走桌面应用本地 API，云端走 Cloud Browser 连接 URL。`gologin` SDK 完全不需要。

### 代码事实

- 唯一浏览器生命周期接缝：`utils/browser_session.py::browser_session`；托管分支 `_managed_session` 负责 probe → start → `connect_over_cdp`（3 次 × 10s，退避 2s→4s）→ 要求 `contexts` 恰好 1 个 → 断开 → shield stop。
- Provider 结构契约：`utils/managed_browser.py::ManagedBrowserProvider`（`mode`、`profile_id`、`probe`、`start(headless) -> connect_url`、`stop`、`status`）；`ProviderMode = Literal["multilogin", "adspower"]`。
- `BrowserSession.mode` 另有一份手写 `Literal["local", "multilogin", "adspower"]`（`utils/browser_session.py:190`），扩展时要同步。
- 选择与激活集中在 `sau_commands/browser.py`：`active_mode()`、`credentials_conflict()`、`resolve_managed_provider()`、`_PROVIDER_WORDINGS`、`add_browser_flags()`（`--folder-id` / `--profile-id`）。
- 实测调用面（2026-11-13）：`browser_session(` 38 处、`.mode ==/!=` 25 处、`.managed` 29 处，全部在 `uploader/` 与 `sau_commands/`。
- 退出码：`0` 成功、`1` 运行失败、`2` 用法错误、`9` 发布结果未知、`10` 需登录/人机验证、`11` 429、`130` 用户中断。`10` 只在 `sau_cli.main` 由 `LoginRequiredError` 映射。
- 依赖：`requests==2.32.3`、`patchright==1.64.4`；测试全为 `unittest`，provider 层用 `tests/fakes.py` 手写 fake，不启真实浏览器。
- 现有托管模式文档锚点：`docs/CLI.md#托管浏览器模式通用`、`#multilogin-x-模式`、`#adspower-模式`；`GLOSSARY.md` 已把「托管浏览器模式」泛化。

### GoLogin 云端运行时已确认（2026-11-13，官方文档）

来源：<https://gologin.com/docs/api-reference/cloud-browser/getting-started>

- 接入点是一个连接 URL：`wss://cloudbrowser.gologin.com/connect?token=<dev token>&profile=<profileId>`；官方 Python 示例直接 `p.chromium.connect_over_cdp(CLOUD_BROWSER_URL)`。
- `profile` 可选：给了就在云端跑该 Profile，不给则新建一个 Profile。
- 预检：把 `wss://` 换成 `https://` 发 `GET`；失败读响应头 `X-Error-Reason`。
- 停止：`DELETE https://api.gologin.com/browser/{profileId}/web`，`Authorization: Bearer <token>`。
- token 是 GoLogin 应用里创建的 **dev token**（API & MCP → API → New Token）。
- **安全含义**：token 出现在连接 URL 的 query 里，现有「token 永不落日志」的规则必须扩展到 connect URL 的脱敏（启动行 `endpoint=`、异常文本、`last_error`）。
- 本地运行时已确认：桌面应用本地 HTTP API 默认 `36912`、被占则递增；`POST /browser/start-profile {profileId, sync:true}` → `{status, wsUrl}`；`POST /browser/stop-profile` → 204（详见 ticket 10 与 research §10）。
- 云端的硬限制已确认：会话默认 15 分钟寿命 + 15 分钟空闲回收、并发 1–4、仅付费版、仅 Chromium、Profile id 24 位 hex。
- 本地启动不受套餐限制（"Local launches are not limited by your plan"）；云端需付费版。
- HTTP 429 **永久吊销 token**（不是冷却）：provider 绝不能盲目重试，且需要独立的「token 已吊销」文案。

### 参考技能

- `/research`：外部事实调研（GoLogin API 面）。
- `/grilling`、`/domain-modeling`：决策与术语。
- `/codebase-design`：provider 接缝与 runtime 维度设计。

## Decisions so far

<!-- 已解决的 ticket 会在这里追加一行：链接 + 一句话结论。 -->

- [01 — GoLogin 的 API 面：Local API、云端运行时与 SDK 行为](./issues/01-gologin-api-surfaces.md) — **云端有、本地 API 未文档化**：Cloud Browser 是标准 CDP（`wss://cloudbrowser.gologin.com/connect?token=&profile=`），官方 Playwright 示例可零 SDK 直接 `connect_over_cdp`；桌面应用的本地 API 不在一手文档里（后由 ticket 10 从安装包源码确认存在）。429 永久吊销 token；云会话默认 15 分钟、并发 1–4、仅付费版、仅 Chromium。
- [10 — 实测 GoLogin 桌面应用的本地 HTTP API（36912）](./issues/10-verify-gologin-local-api.md) — **存在，已从 `Gologin.app` 的 asar 源码确认**：端口从 36912 起被占则递增；`GET /service/check-server`；`POST /browser/start-profile {profileId, sync:true}` → `{status, wsUrl}`（**`sync` 必须 true**，否则 wsUrl 为空）；`POST /browser/stop-profile` → 204；无 status 路由、无 headless 参数、本地调用无鉴权。两运行时均零依赖，SDK 不需要。
- [02 — 运行时收口](./issues/02-runtime-scope-and-sdk-boundary.md) — 本地走桌面应用本地 API（36912 起扫 16 个、0.2s 超时、fail-fast、启动行打 `port`）；`--headless` 本地静默忽略并进 `ignored=`，云端用 `isHeadless`；云端先 `POST /browser/{id}/web`（`maxLifeTimeMinutes=120`）再走 `remoteOrbitaUrl` → `/json/version`，缺失则回退 `/connect`；会话丢失不重连、退出 `1`；不引入 SDK。

## Not yet specified

- 云端运行时的网络拓扑与合规边界（跨机、出口 IP、数据驻留、跨境延迟对上传/视频传输的影响）。
- 运行时是 `ProviderMode` 之外的第二个维度，还是把 GoLogin 拆成 `gologin-local` / `gologin-cloud` 两个 mode——等 ticket 05。
- 真实 GoLogin 账号与真机验收（外部阻塞；spec 内相关结论只标置信度）。

## Out of scope

- 引入 `gologin` SDK、Orbita 二进制下载链路，以及其 Selenium 依赖（硬约束，见 map Notes）。
- 实现代码：本轮只交规格，不改 `utils/`、`sau_commands/`、`uploader/`。
- 在 GoLogin 中创建/修改 Profile、管理代理、导入/导出 Cookie。
- Flask 后台 `sau_backend.py`、`myUtils/` 与 Vue 前端。
- 调度 App 本身（接单、分配、重试、上报、人工登录回流）。
- 本地模式与现有 MLX / AdsPower 的可观察行为变更（只允许内部重构）。
- 除 GoLogin 之外的第四个 provider（BitBrowser 等）。
- Bilibili（`biliup` 子进程，没有浏览器上下文）。
- 账号 ↔ Profile 映射文件；每次调用显式传 `--profile-id`。
