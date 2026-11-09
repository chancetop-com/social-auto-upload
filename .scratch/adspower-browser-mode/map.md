# AdsPower 浏览器模式 — 路线图

## Destination

一份可直接交给后续会话实施的 AdsPower 浏览器模式设计规格：在不改变本地模式与现有 Multilogin 模式行为的前提下，新增由 `ADSPOWER_API_KEY` 激活的 AdsPower 模式——复用 `--profile-id`（映射 AdsPower `user_id`）启动 Profile、经 CDP 接管现有 Context、复用 Profile 登录态、跑原有上传逻辑、结束时停止 Profile，并保持与 MLX 相同的参数、退出码与登录失效契约。

## Notes

### 本会话已确认的 charter

- 只做 CLI；Flask `sau_backend.py`、`myUtils/` 与 Vue 前端不改。
- 本地模式行为不变；Multilogin 模式仅 429 退出码按下方新契约变更（`1 → 11`），其余行为不变；AdsPower 是新增的 managed browser provider。
- 激活：`ADSPOWER_API_KEY` 非空（去除首尾空白）即进入 AdsPower 模式；未设置、空串或纯空白保持原有模式判定。
- 同时设置非空 `MLX_API_TOKEN` 与 `ADSPOWER_API_KEY` → 直接退出 `1`（本会话确认，不走用法错误 `2`）。
- 429 限流：MLX 与 AdsPower 统一新增退出码 `11`（2026-11-09 批准；MLX 的 429 从 `1` 改为 `11`，这是本 effort 唯一一次对 MLX 可观察行为的变更）。
- 无 key 的 AdsPower 安装（关闭 API 安全校验）不在本 effort 范围。
- Profile 标识：复用 `--profile-id`，内部映射为 AdsPower `user_id`；`--folder-id` 不要求，传了也忽略。
- `--account` 在 AdsPower 模式下可选；ticket 02 裁决它是纯兼容占位，无身份/cookie/输出语义（与 MLX 现状对齐），不承诺日志或结果标签。
- Local API 地址：默认 `http://127.0.0.1:50325`，允许 `ADSPOWER_API_BASE` 覆盖。
- 架构：把 managed browser 分支抽成 provider 接口，MLX 与 AdsPower 各实现一份；本地分支与生命周期实现不复制。
- 平台覆盖：与 MLX 完全对齐；Bilibili（`biliup`）不支持；`verify` / `delete` 仍走本地模式。
- 真实 AdsPower 验证：当前机器未安装 AdsPower（`/Applications` 无匹配、50325 未监听），采用“离线交付 + 外部阻塞冒烟”策略；规格中相关结论标注置信度。

### 代码事实

- CLI 入口 `sau_cli.py` → `sau_commands/<platform>.py` → `uploader/<platform>_uploader/`。
- `utils/browser_session.py` 是唯一浏览器生命周期接缝；当前 managed 分支是 `_multilogin_session`，`BrowserSession.mode` 为 `Literal["local", "multilogin"]`。
- `utils/multilogin.py` 提供 `MultiloginTarget` / `MultiloginClient`（同步 `requests.get`，可注入 `http_get`）。
- `sau_commands/multilogin.py` 提供 flags、激活判定、target 解析、account label、login 拒绝；`add_multilogin_flags` 有 32 个调用点，`resolve_multilogin_target` 有 35 个调用点。
- 各平台 uploader 的上传方法以 keyword-only `multilogin=target` 接收会话目标；uploader 只依赖 `utils/errors.py`。
- 测试全部是 `unittest`；MLX 契约矩阵在 `tests/test_mlx_*.py` 与 `tests/test_multilogin_*.py`，provider 层用 `tests/fakes.py`。
- 仓库根 `GLOSSARY.md` 当前是 Multilogin X 语境，需要补充 AdsPower 术语。

### AdsPower 官方文档已确认（2026-11-06 检索）

- Local API 需要 AdsPower 付费版；桌面应用需运行且开启 API。
- 默认地址 `http://local.adspower.net:50325/` 或 `http://localhost:50325/`；实际地址可从 `local_api` 文件读取。
- 开启安全校验时使用 `Authorization: Bearer <API Key>`；官方说明也支持关闭校验的无 key 模式。
- V1 启动：`GET /api/v1/browser/start?user_id=<id>`；成功返回 `code: 0`，`data.ws.puppeteer` 为 `ws://127.0.0.1:.../devtools/browser/...`，另有 `data.ws.selenium`、`data.debug_port`、`data.webdriver`；失败返回 `code: -1` 与 `msg`。
- V2 启动：`POST /api/v2/browser-profile/start`，JSON 含 `profile_id`、`last_opened_tabs`、`proxy_detection`；返回同样的 `data.ws.puppeteer`。
- 推荐端点：V2 `POST /api/v2/browser-profile/start|stop`、`GET /api/v2/browser-profile/active`；官方 Playwright 示例即 V2。V1 已由 ticket 10 排除（只做 V2，不做回退）。
- 关闭：V1 `GET /api/v1/browser/stop?user_id=...`；V2 `POST /api/v2/browser-profile/stop`。
- 状态：V1 `GET /api/v1/browser/active?user_id=...`；V2 `GET /api/v2/browser-profile/active?profile_id=...`；`data.status` 为 `Active` / `Inactive`，Active 时返回 `ws`。
- 启动参数含 `headless`、`launch_args`、`cdp_mask`（默认 1）等；**V2 默认 `proxy_detection=1`（开 IP 检测页）与 `last_opened_tabs=1`（恢复上次页面），规格必须显式传 `0/0`**。V1 对应 `ip_tab=1` / `open_tabs=0`（注意 V1 的 `open_tabs` 语义相反）。
- 官方 Playwright 示例：`chromium.connect_over_cdp(data['data']['ws']['puppeteer'])`，使用 `browser.contexts[0]`。
- 频率限制：0–200 Profile 2 次/秒，200–5000 5 次/秒，>5000 10 次/秒；部分接口 1 次/秒。
- Playwright `connect_over_cdp` 仅支持 Chromium；AdsPower 的 Firefox 示例只给 Selenium/Marionette，因此本仓只支持 Chromium 内核 Profile。

### 参考技能

- `/research`：外部事实调研。
- `/grilling`、`/domain-modeling`：决策与术语。
- `/codebase-design`：provider 接口与深模块设计。

## Decisions so far

<!-- 已解决的 ticket 会在这里追加一行：链接 + 一句话结论。 -->

- [01 — AdsPower Local API 契约与边界行为](./issues/01-adspower-local-api.md) — 推荐 V2 生命周期端点与默认 `127.0.0.1:50325`，start 前预检 `active` 并坚持“谁启动谁停止”；已运行/重复 stop/401/429 仍属未知，需真实 smoke。
- [02 — AdsPower 模式的 CLI 契约与激活规则](./issues/02-cli-contract.md) — env-only 激活、`main()` 层冲突判定、`--profile-id` 必填而 `--folder-id` 忽略、`--account` 纯占位、login 拒绝；退出码继承 MLX 并新增双方共用的 `11`（429）；不预检 `active`（与 MLX 一致，ticket 01 的预检建议被本裁决覆盖）。
- [10 — AdsPower API 版本与端点选择](./issues/10-api-version-endpoints.md) — 只做 V2；client 四原语 `probe/start/stop/status` 与 MLX 同构（`status` 打 V2 `/active`、仅用于诊断）；`start` 返回 `ws.puppeteer` 并固定 `last_opened_tabs/proxy_detection/delete_cache/cdp_mask`；探活照 MLX（3s，带 key）；不重试，仅 HTTP 429 抛 `RateLimitedError` → `11`；stop 严格判定、异常交会话层降级。
- [03 — Provider 抽象与 uploader 接缝](./issues/03-provider-seam.md) — `ManagedBrowserProvider` Protocol 组合 target+client，`start(headless)` 返回归一化 `connect_url`（MLX 拼 http、AdsPower 直用 ws）；`browser_session(managed=)` 保留唯一生命周期模板，provider 只做原语；新增 `BrowserSession.managed`，上传器看它而非 provider 名；选择与环境解析上移 `sau_commands/browser.py`，`multilogin.py` 降为 shim；`multilogin=` 一次改名、两阶段迁移；错误面加 `RateLimitedError`（04 补充：另加内部信号 `StartIncompleteError`）。
- [04 — AdsPower Profile 生命周期与所有权](./issues/04-lifecycle-ownership.md) — 生命周期沿用 02/03/10：无 active 预检、start 成功即 owned、start 失败不 stop、CDP 3×10s/2s→4s、contexts 必须为 1、断开后 shield stop、stop 失败只 warning；新增 `StartIncompleteError` 让“2xx 已启动但响应坏”先 stop 再退出 `1`；超时 3/30s；start 传输歧义不 stop；日志照 MLX。
- [05 — AdsPower 模式的测试策略](./issues/05-test-strategy.md) — 新增 4 个全离线测试文件（client / browser-session / CLI / 平台守卫），不写冒烟、真机验证全归 09；client 注入 `http_get`+`http_post` 并共享 fake；模板只测一次、AdsPower 只测组合与 `StartIncompleteError`；平台回归 = 8 个 `test_mlx_*` 零改动 + `managed` 真值表 + 禁 `mode == "multilogin"` 的静态守卫（实测 28 处，全在 `uploader/`）；`130` 不测；不设覆盖率数字、不加网络护栏。
- [06 — AdsPower 模式的文档、术语与部署前提](./issues/06-docs-glossary-deployment.md) — 统一称“托管浏览器模式（managed browser mode）”；GLOSSARY 泛化+分层；CLI/README 三层结构并保留旧锚点 `#multilogin-x-模式`；18 个 Skill 全量加统一模板；部署/安全/调度沿用 MLX 口径；文档验收走人工核对+文件清单，真实冒烟仍待 09。
- [07 — 逐平台迁移清单与能力对齐](./issues/07-platform-inventory.md) — 实测 17 个模块 import、41/16/17/33/7/17/1/14 个 helper 调用点、36 个 `browser_session` 调用点、28 处 `session.mode` 判定（含 insgraph 两处单引号）；16 个托管平台 + article/bilibili；发现 bilibili 在 AdsPower 下会静默回退本地的缺口，以及 2 个 `test_mlx_*` 直接调用 `browser_session(multilogin=)` 与“零改动”裁决的冲突。
- [08 — 汇总 AdsPower 模式设计规格](./issues/08-assemble-spec.md) — 最终交付物 [spec.md](./spec.md) 完成：15 节覆盖激活/CLI/Provider 架构/V2 client/生命周期/逐平台/身份/安全/部署/测试/三阶段实施/风险/兼容性；吸收 07 的实测迁移规模、bilibili 缺口与测试豁免；真实冒烟仍归 09 外部阻塞，不阻塞离线实现。

## Not yet specified

<!-- 当前没有未成形的 fog：已知问题都已进入 decision ticket。若后续 smoke 暴露新的未知，再在这里登记。 -->

## Out of scope

- AdsPower 无 key 安装（关闭 API 安全校验）；本 effort 只支持 `ADSPOWER_API_KEY` 激活。
- AdsPower V1 Local API（`/api/v1/browser/start|stop|active`）：只做 V2，不做 fallback 或双栈（[10 — AdsPower API 版本与端点选择](./issues/10-api-version-endpoints.md)）。
- AdsPower Firefox Profile（Playwright/CDP 仅支持 Chromium；运行期没有 `ws.puppeteer` 直接失败）。
- 在 AdsPower 中创建/修改 Profile、管理代理、导入/导出 Cookie。
- 账号 ↔ Profile 映射文件；每次调用显式传 `--profile-id`。
- 跨机 AdsPower、Docker AdsPower、无桌面 Linux 拓扑。
- Bilibili（`biliup` 子进程，无浏览器上下文）。
- Flask 后台 `sau_backend.py`、`myUtils/` 与 Vue 前端。
- 调度 App 本身（接单、分配、重试、上报、人工登录回流）。
- 本地模式与现有 Multilogin 模式的行为变更（只允许内部重构，不改变可观察行为）。
- 除 AdsPower 之外的第三个 provider（BitBrowser 等）；本 effort 只把接缝做成可扩展。
