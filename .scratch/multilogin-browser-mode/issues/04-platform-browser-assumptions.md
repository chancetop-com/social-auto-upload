# 04 — 平台特有的浏览器假设在 MLX 模式下的取舍

Status: resolved
Type: grilling
Blocked by: 01, 02
Assignee: —

## Question

各平台现在的 launch / context 配置带有平台特有假设。MLX 模式下必须统一成 “连接一个已存在的 Mimic Chromium context”，需要逐项决定“透传、忽略、改写还是拒绝”：

1. **TikTok**：`uploader/tk_uploader/main.py` 用 `playwright.firefox.launch()`；`main_chrome.py` 用 Chromium。MLX 只有 Chromium/Mimic。
   - MLX 模式强制走 `main_chrome.py` 的逻辑，还是给 `main.py` 加分支？
   - 现有 TikTok 上传流程在 Chromium 下是否等价？有无 Firefox 专属行为？

2. **YouTube**：`youtube_setup` 与上传使用 `channel="chrome"`，并支持 `YT_PROXY`。
   - MLX 模式是否忽略 `YT_PROXY` / `channel` / `executable_path`？
   - Profile 代理已是出口 IP，若用户同时设了 `YT_PROXY`，是报错还是忽略？

3. **Meta（facebook / facebook-page / instagram）**：有独立 proxy 参数与 launch kwargs。
   - MLX 模式下代理参数是否一律忽略并告警？
   - 是否有依赖 Chrome channel 的行为？

4. **知乎**：`new_context(..., timezone_id="Asia/Shanghai")`，还有 verification / session 两套检测。
   - MLX 模式不能设置 timezone，是否接受 Profile 自身时区？
   - 需要校验 Profile 时区吗，还是文档提示即可？

5. **微博 / 虎扑 / 快手 / 小红书 / 抖音 / 视频号**：`LOCAL_CHROME_PATH`、`channel="chromium"`、`executable_path` 等。
   - 统一策略：MLX 模式全部忽略，还是保留某些 args？

6. **旧版 `xhs_uploader` 签名器**：`sign_local` 自己 launch 同步 Playwright 只为算 `x-s`。
   - 确认它只被 legacy `myUtils/auth.py` 使用，不属于 CLI 上传路径；若 CLI 某平台也依赖它，需要单独处理。

7. **验证码 / 2FA**：各平台登录后二次验证在 Profile 里的责任边界。
   - CLI 是否只负责“检测到未登录 → 退出 10”，不做任何验证码处理？

## Context

- 已确认：`--headless` 透传为 `headless_mode`；不 new_context、不写 cookie。
- 需要产出“平台 × 假设 × MLX 处理方式”的决策表，作为设计规格的一节。
- 先读 01 / 02 的事实，再决定；不要凭猜测。

## Answer

### 总策略：Profile 是唯一事实源（Q1 / Q2）

MLX 模式下，所有平台特有的 **launch / context 假设一律忽略，且不打印告警**。`browser_session` 的 MLX 分支丢弃 `launch_kwargs`（`channel`、`executable_path`、`args`、`proxy`、`headless` 启动参数等），平台代码在 MLX 分支也不得对已连接 context 做后处理（`set_init_script`、`storage_state`、`grant_permissions`、视口/时区设置）。

- 忽略清单：`channel="chrome"/"chromium"`、`LOCAL_CHROME_PATH` / `executable_path`、`--no-sandbox` / `--disable-blink-features=AutomationControlled` / `--start-maximized` / `--lang`、`proxy`（含 `YT_PROXY`、`FACEBOOK_PROXY`、`INSTAGRAM_PROXY`、Meta `--proxy`）、`timezone_id`、`viewport` / `no_viewport`、`user_agent`、`permissions` / `grant_permissions`、stealth init script、`storage_state` 读取与写入。
- 唯一透传项：`--headless` / `--headed` → MLX `headless_mode`（charter 已定）。
- 代理冲突（Q2）：`YT_PROXY` / `FACEBOOK_PROXY` / `INSTAGRAM_PROXY` / `--proxy` 全部**静默丢弃**，Profile 代理是唯一出口；设计文档需写明“设置本地代理不会影响 MLX 模式”，避免误以为流量走本地代理。
- 不告警、不报错、不回退到本地浏览器。契约层把“忽略”做成显式行为（MLX 分支不构造这些参数），避免依赖“传了但没生效”的隐式行为。

### 平台 × 假设 × MLX 处理（决策表）

| 平台 | 现有 launch / context 假设 | MLX 处理 | 风险与备注 |
|---|---|---|---|
| douyin | `channel="chromium"`、`args=["--no-sandbox", "--disable-blink-features=AutomationControlled"]`、`set_init_script`、`storage_state` 读写 | 全部忽略；跳过 stealth 与 cookie 写入 | 反检测脚本与 Mimic 指纹冲突（ticket 02） |
| kuaishou | `LOCAL_CHROME_PATH` 或 `channel="chromium"`、`set_init_script`、`storage_state` | 全部忽略 | 登录流程已有可选 `cdp_url`，upload 没有；MLX 统一走 `browser_session` |
| xiaohongshu | `channel="chromium"`、`permissions=["geolocation"]`、`set_init_script`、`storage_state` | 全部忽略 | 位置权限缺失；如发布需要定位，验收时确认，不改 Profile 权限 |
| tencent（视频号） | `_build_launch_kwargs`（AutomationControlled + `LOCAL_CHROME_PATH`）、`set_init_script`、`storage_state` | 全部忽略 | — |
| alipay | `_build_launch_kwargs`（AutomationControlled + `LOCAL_CHROME_PATH`）、`storage_state`；刻意不用 stealth | 全部忽略 | 现有注释：stealth 会阻断支付宝 iframe；MLX 同样不加 stealth |
| weibo | `_build_launch_kwargs`、`viewport={"width":1280,"height":2000}`、`storage_state` | 全部忽略 | 视口依赖是功能性的（发布按钮需在可视区）；MLX 分支改用 `scroll_into_view_if_needed()` / 定位滚动，不假设高视口 |
| hupu | `_build_launch_kwargs`、自定义 UA（`_CHROME_UA`）、`viewport=1920×1080`、`_STEALTH_SCRIPT`（`add_init_script`）、`storage_state` | 全部忽略 | 自定义 UA 与 stealth 均与 Mimic 冲突；若页面布局因 UA 变化，只能改流程选择器，不能改 Profile |
| facebook | `channel="chrome"`、`proxy=_proxy_options(...)`、`storage_state` | 全部忽略 | 代理静默丢弃（Q2） |
| facebook-page | 同 facebook | 全部忽略 | — |
| instagram | `channel="chrome"`、`proxy`、登录时 `args=["--start-maximized"]` / `no_viewport=not headless`、`storage_state` | 全部忽略 | 登录命令在 MLX 模式拒绝（ticket 06），这些参数只影响本地登录 |
| youtube | `channel="chrome"`、`YT_PROXY`、`set_init_script`、`storage_state` | 全部忽略 | `YT_PROXY` 静默丢弃；如出口 IP 不符，是 Profile 配置问题 |
| baijiahao | `_build_launch_kwargs`、`context.grant_permissions(["geolocation"])`、`storage_state` | 全部忽略 | 位置权限缺失；发布流程若依赖定位，验收时确认 |
| dayu（大鱼号） | `channel="chrome"`、`LOCAL_CHROME_PATH`、`timezone_id="Asia/Shanghai"`、`storage_state` | 全部忽略 | 时区随 Profile；身份绑定风险见 ticket 12 |
| xueqiu | `channel="chrome"`、`LOCAL_CHROME_PATH`、`storage_state` | 全部忽略 | 身份绑定风险见 ticket 12 |
| zhihu | `channel="chrome"`、`LOCAL_CHROME_PATH`、`timezone_id="Asia/Shanghai"`（login/verification/article/video 四处）、`storage_state` | 全部忽略 | **时区（Q3）：接受 Profile 自身时区，CLI 不校验、不提示**；设计规格“部署前提”写明建议把 Profile 时区设为 Asia/Shanghai |
| tiktok（新增） | `main_chrome.py`：`LOCAL_CHROME_PATH`、`storage_state`；`main.py`：Firefox | **接入 CLI，但仅 MLX 模式**；本地模式直接报错退出 1。只用 Chromium 实现，Firefox 不接入 | 命令集、登录命令、账号标签等细节另开 ticket 13 |
| article | 无浏览器，只做本地文章渲染 | 不适用 | 不参与 MLX 迁移 |
| bilibili | `biliup` 子进程，无浏览器 | 维持 Out of scope | MLX 模式调用直接报错 |

### 验证码 / 2FA 责任边界（Q4）

- 登录、扫码、短信 2FA、验证码**全部由人工在 Multilogin Profile 内完成**；CLI 不自动登录、不等待人工、不处理验证码。
- 退出码语义扩大：**明确的登录页/登录表单 → 10；上传或 check 过程中遇到验证码 / 二次验证 / “需要人工验证”页面 → 同样退出 10**。实现上抛统一的 `LoginRequiredError`，由 `sau_cli.main` 映射到 10。
- 网络错误、HTTP 4xx/5xx、超时仍走退出 1（与 ticket 03 的错误分类一致），不得混入 10。
- 文档必须写清：MLX 模式要求 Profile 处于“已登录且无待处理验证”的状态；否则调度侧会收到 10。

### 范围确认（Q5 / Q6）

- **TikTok 纳入 CLI**：`sau_cli.PLATFORMS` 新增 `tiktok`，只使用 `uploader/tk_uploader/main_chrome.py`（Chromium/Mimic 兼容）；`main.py` 的 Firefox 实现不接入。**仅 MLX 模式可用**，不提供本地模式；无 `MLX_API_TOKEN` 时 `sau tiktok ...` 报错退出 1。具体命令集与登录命令行为见 ticket 13。
- **旧版 `xhs_uploader::sign_local` 不动**：只被 `myUtils/auth.py`（Flask）与 `examples/` 使用，CLI 的小红书走 `xiaohongshu_uploader`，属于既有 Out of scope，不新增适配。
- `article` 平台无浏览器，不纳入 MLX 平台表。

### 对下游 ticket 的约束

- ticket 06：`browser_session` 的 MLX 分支静默忽略 `launch_kwargs`，平台代码负责跳过 `set_init_script` / `storage_state` / 权限设置；不得提供“部分透传”开关。
- ticket 09：平台迁移清单按上表写；微博视口、百家号/小红书位置权限、虎扑 UA 作为验收风险列出；TikTok 依赖 ticket 13 的结论。
- ticket 05：验证码导致的 10 仍必须在 `finally` 中 Stop Profile。

