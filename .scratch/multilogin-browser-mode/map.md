# Multilogin X 浏览器模式 — 路线图

## Destination

一份可直接交给后续会话实施的设计规格：在不改变本地浏览器模式的前提下，为 `sau` CLI 增加由 `MLX_API_TOKEN` 激活的 Multilogin X 浏览器模式——按 `--folder-id` / `--profile-id` 启动 Profile、经 CDP 接管现有 Context、复用 Profile 登录态、跑原有上传逻辑、结束时停止 Profile，并定义调度 App 可依赖的退出码契约。

## Notes

### 已确认约束（charter）

- 只做 CLI；Flask `sau_backend.py`、`myUtils/` 与 Vue 前端不改。
- 本地模式行为不变，默认路径不删除。
- 模式激活：环境变量 `MLX_API_TOKEN` 存在 → Multilogin 模式；不存在 → 本地模式（`--profile-id` / `--folder-id` 被忽略）。
- Multilogin 模式参数：`--folder-id`、`--profile-id` 必填；`--account` 不必填，缺省以 `profile_id` 作为日志标签。
- 不建账号↔Profile 映射文件；每次调用显式传入。
- Cookie：Profile 是唯一存储；不读/写 `cookies/<platform>_<account>.json`，不 `new_context`，不覆盖 Profile cookie。
- 登录失效：不自动登录，直接失败；upload 与 check 在 MLX 模式返回退出码 `10`；本地模式 check 仍返回 `1`。
- 其他失败退出码 `1`；`argparse` 参数错误保持 `2`；成功 `0`。
- `--headless` / `--headed` 直接透传为 MLX `headless_mode`。
- 生命周期：谁启动谁停止；已在运行、并发串行由调度 App 负责，库内不加锁。
- 接入方式：显式 `browser_session` 上下文管理器（方案 A），不做运行时 facade。
- 哔哩哔哩走 `biliup`，本次 Out of scope；MLX 模式下直接报错。
- 范围变更：TikTok 纳入 CLI，但**仅 MLX 模式**（本地模式报错退出 1）；实现只用 Chromium 版 `main_chrome.py`，Firefox 版不接入。

### 代码事实

- CLI 入口 `sau_cli.py` → `sau_commands/<platform>.py` → `uploader/<platform>_uploader/`。
- 本地 cookie 路径由 `sau_commands/arguments.py::resolve_account_file` 生成。
- 现有 upload 流程：`async_playwright()` → `launch()` → `new_context(storage_state=...)` → 业务 → `storage_state(path=...)` → `close()`。
- 只有 douyin / ks 的登录流程已有可选 `cdp_url`；upload 没有。
- 测试用 `unittest`（`tests/`），无 pytest 配置。
- `conf.py` 由 `conf.example.py` 复制生成，已被 gitignore；设计不应依赖修改它。
- Legacy positional args 被测试固定（见 `tests/test_douyin_declaration.py`），新增字段必须用 keyword-only。

### 官方文档已确认（2026-11 检索）

- Start：`GET https://launcher.mlx.yt:45001/api/v2/profile/f/{folder_id}/p/{profile_id}/start?automation_type=playwright&headless_mode=...`，响应含 `data.port`。
- 连接：`chromium.connectOverCDP("http://127.0.0.1:{port}")` → `browser.contexts[0]`。
- Stop：`GET https://launcher.mlx.yt:45001/api/v1/profile/stop/p/{profile_id}`；已停止可能返回 500 `profile already stopped`。
- 只有 Mimic 内核支持 Playwright；Stealthfox 不支持。
- 需要本机运行 Multilogin 桌面应用或 launcher 容器（45001 / 45003）。
- 推荐 Workspace Automation Token；普通 token 30 分钟过期。
- 官方明确要求：Playwright 侧只使用 `contexts[0]` 与 `newPage()`；断开用 `browser.close()`，随后单独调 Stop。

### 参考技能

- `/research`：事实调研。
- `/grilling`、`/domain-modeling`：决策与术语。
- `/codebase-design`：provider 接口设计。

## Decisions so far

- [01 — Multilogin X Launcher API 契约与边界行为](./issues/01-mlx-launcher-api.md) — **官方 demo 在 Start 200 后直接连 CDP**（重试仅为健壮性增强）；已运行会 500 `can't lock profile` 且无端口；Bearer + automation token；Stop 幂等（`already stopped` 视为成功）；Docker+CDP 未闭环。
- [02 — patchright 1.58.2 与 Mimic CDP 的兼容性](./issues/02-patchright-mimic-cdp.md) — 可连接；`contexts[0]` 仅单 context 时可靠，空则 fail-fast；`browser.close()` 只断开；MLX 必须跳过 `set_init_script`，禁用 new_context/storage_state/cookie 写入；1.58.2 落后 Mimic 156。
- [03 — 各平台登录态检测清单（MLX 模式）](./issues/03-login-detection-inventory.md) — 现有检测都不能接收外部 context；多数可抽 `is_logged_in(context)`；TikTok/支付宝/百家号须重写；知乎/雪球/大鱼号/Instagram 有身份绑定缺口；网络错误必须与未登录区分。
- [04 — 平台特有的浏览器假设在 MLX 模式下的取舍](./issues/04-platform-browser-assumptions.md) — MLX 模式静默忽略所有本地 launch/context 假设（channel、executable_path、args、proxy、timezone、viewport、UA、permissions、stealth、storage_state），Profile 是唯一事实源；`YT_PROXY`/Meta 代理静默丢弃；知乎时区只写文档不校验；验证码/2FA 一律退出 10；TikTok 接入 CLI 但仅 MLX 模式（细节见 ticket 13）；旧版 `sign_local` 不动。
- [05 — Profile 生命周期与失败边界](./issues/05-profile-lifecycle-edges.md) — 连接超时 10s × 3 次、退避 2s→4s；失败统一走异常→stderr→1，不加结构化字段；锁冲突不查 statuses、绝不 stop 别人的 Profile；Stop 失败仍退出 0 + 警告；finally 必 Stop（取消路径用 shield）；check = start→检测→stop（0/10/1）；Stop fire-and-forget；复用平台 loguru，token 永不记录。
- [06 — Provider 接口与 uploader 改造契约](./issues/06-provider-contract.md) — 新增 `utils/multilogin.py`（Target/Client）、`utils/browser_session.py`（唯一 lifecycle seam）、`utils/errors.py`（`LoginRequiredError`/`UsageError`）与 `sau_commands/multilogin.py`（参数与激活）；CM 返回 `BrowserSession(browser, context, mode)`，不暴露 `owned`/`stop()`；Start/Stop 全在 CM 内；本地分支按 `launch_kwargs` / `context_kwargs` / `init_script` 三拆原样复刻，MLX 分支静默忽略；target 不进 request dataclass，session 以 keyword-only 下传上传方法；`is_logged_in(context) -> bool` 只判显式未登录，网络错误抛异常；10 只由 `LoginRequiredError` 在 `sau_cli.main` 映射，缺参仍为 2；MLX 下 `login` 保留注册但运行时拒绝（1）；`--account` 改可选，MLX 缺省标签 = `profile_id`。
- [07 — 没有真实 MLX 时的测试策略](./issues/07-test-strategy.md) — 默认 `unittest` 套件离线、不启浏览器；Launcher 在 `MultiloginClient` 注入 `http_get` 打桩（不起 http.server，因 TLS/端口不稳定）；Provider 层用手写 `tests/fakes.py`（可控 `contexts` 长度、close 顺序、非法调用直接 AssertionError），不用真实 CDP；契约矩阵 5 个文件覆盖生命周期/参数/退出码/禁止调用/登录检测；本地回归双层（CLI fake playwright + uploader 不传 session 的 legacy 路径），每平台 golden dict 防漂移；真实 MLX 冒烟 `SAU_MLX_SMOKE=1` opt-in 只读；响应样本放 `tests/fixtures/multilogin/` 并脱敏；真实发布/风控/验证码/代理指纹不自动化。
- [09 — 汇总设计规格](./issues/09-assemble-spec.md) — 产出 [`spec.md`](./spec.md)：目标/术语/模式激活、CLI 参数与退出码、模块与运行时时序、上传器 seam 与逐平台迁移表、登录检测与身份规则、TikTok 契约、部署前提、调度责任、依赖（patchright 1.64.4，仅测试用例回归）、测试矩阵、实施阶段拆分、验收清单与风险。ticket 08 仍为外部阻塞，spec 内已标置信度。
- [10 — 部署拓扑：桌面应用、Docker launcher，还是跨机](./issues/10-deployment-topology.md) — v1 唯一支持“同机 + Multilogin 桌面应用”；Docker launcher（CDP 端口未映射）、跨机（官方仅 127.0.0.1）、Linux 无桌面均不支持，也不引导 SSH 隧道；每次 MLX 会话 Start 前强制 `GET /api/v1/version` 探活（无鉴权、3s、verify=True），失败退出 1 并给固定三项排查文案；固定 base URL、不提供覆盖变量；Start 成功但 CDP 连不上时追加 Docker 提示，不改退出码。
- [11 — patchright 版本策略](./issues/11-patchright-version.md) — 用户批准升级到 `patchright==1.64.4`（精确 pin）；实测 Chromium 145→156、requires_python 3.10、所 API 只增不改、代码破坏风险低；作为独立提交（个人 fork，不走 PR），更新 `pyproject.toml`/`uv.lock`、重装 Chromium；本地模式**只做测试用例回归，不做真实账号完整验证回归**（stealth 差异为已知未验证风险）；MLX 用 `connect_over_cdp(..., no_defaults=True)`（可按 ticket 08 回退）；`requirements.txt` 旧 Web 环境不动；回滚条件与步骤已写。
- [12 — 身份绑定平台在 MLX 模式下的账号一致性](./issues/12-identity-binding.md) — 采用“只验证已登录”：Profile 即身份，MLX 从不调用 `.identity.json` / 用户 ID 比对，`--account` 仅日志标签；会话建立后打一条 INFO 声明“账号一致性未校验”，风险归调度侧；本地身份逻辑不动；未来若要校验另开 `--expect-account` ticket。
- [13 — TikTok CLI 接入契约（仅 MLX 模式）](./issues/13-tiktok-cli-contract.md) — 注册 `tiktok` 的 `check` / `upload-video` / `login`；参数对齐仓库命名（`--file`/`--schedule`/`--thumbnail`，弃用草稿的 `--video-file`）；`TiktokVideo.__init__` positional 不变、`account_file` 放宽为 `None`；`main_chrome.py` 改 import patchright；MLX 跳过 `change_language`（Profile 需英文界面）；发布循环总超时 15min，验证码/登录页 → 10；`is_logged_in` 20s、只开 1 个 page、网络错误抛异常；本地模式入口直接退出 1；未注册子命令仍 2。

## Not yet specified

- 调度 App 的失败重试与人工登录回流流程（调度侧，但会影响 CLI 文案）。
- 是否保留 `--json` 作为未来增强。
- 真实 MLX 验证（ticket 08）当前因无账号不可执行；它是**外部依赖阻塞**，frontier 跳过它继续 10/11/12/13/09，但 09 的规格必须给相关结论标注“文档 + 社区实测”置信度，拿到账号后按 08 的结果回填。

## Out of scope

- 哔哩哔哩（`biliup` 子进程，无浏览器上下文）；MLX 模式调用直接报错。
- TikTok 本地模式（Firefox/Chromium 本地登录与上传）；TikTok 只做 MLX 模式。
- Flask 后台 `sau_backend.py`、`myUtils/` 与 Vue 前端。
- 调度 App 本身（接单、分配、重试、上报）。
- 账号↔Profile 映射文件、cookie 迁移/导出工具。
- 在 MLX 里创建/修改 Profile、管理代理（由用户在 Multilogin 侧完成）。
- 旧版 `uploader/xhs_uploader` 的签名浏览器（只算 `x-s`，不是上传会话）。
- 本地模式的任何行为变更。
