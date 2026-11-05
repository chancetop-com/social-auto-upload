# Multilogin X 浏览器模式 — v1 设计规格

- 状态：设计完成，可进入实施；真实 MLX 验证（ticket 08）尚未执行。
- 来源：ticket [01](./issues/01-mlx-launcher-api.md)–[07](./issues/07-test-strategy.md)、[10](./issues/10-deployment-topology.md)–[13](./issues/13-tiktok-cli-contract.md)。
- 术语以仓库根目录 `GLOSSARY.md` 为准。
- 证据置信度：`[官方]` = Multilogin 官方文档；`[社区]` = 社区实测/issue；`[实测]` = 本项目调研时在本机验证；`[设计]` = 本规格新增决策。除 `[实测]` 外，真实行为仍需 ticket 08 复核。

---

## 0. 摘要

给 `sau` CLI 增加一个由 `MLX_API_TOKEN` 激活的可选浏览器模式：通过本机 Multilogin Launcher 启动指定 Profile，经 CDP 接管其现有 Chromium context，复用 Profile 登录态跑原有上传逻辑，结束时停止由本次调用启动的 Profile。本地模式保持原有行为；接入点只有一个——显式的 `browser_session` 上下文管理器。

## 1. 目标与非目标

### 目标

1. MLX 模式下，Cookie/登录态只来自 Profile；CLI 不读、不写 `cookies/*.json`。
2. 各平台上传与 `check` 复用现有业务代码，不复制一套上传实现。
3. 生命周期、登录失效、参数错误有确定的退出码，调度 App 可依赖。
4. 本地模式（无 token）行为不变。

### 非目标

- 不改 Flask `sau_backend.py`、`myUtils/`、Vue 前端。
- 不做账号↔Profile 映射、Cookie 导入/导出、在 MLX 里创建/修改 Profile。
- 不做调度 App（接单、重试、上报、人工登录回流）。
- 不支持跨机 launcher、Docker launcher、Linux 无桌面拓扑。
- 不支持哔哩哔哩（`biliup` 无浏览器上下文）。
- 不提供 TikTok 本地模式。

## 2. 术语

| 术语 | 含义 |
|---|---|
| Multilogin 模式（MLX） | `MLX_API_TOKEN` 非空时激活；Profile 是唯一事实源 |
| 本地模式（Local） | 原有默认路径：上传器启动浏览器，读写 `cookies/<platform>_<account>.json` |
| Profile / Folder | Multilogin 的浏览器身份容器 / 组织文件夹 |
| Launcher | 本机 Multilogin 服务，`https://launcher.mlx.yt:45001` |
| Browser session | 一次“取得浏览器并交还”的生命周期单元 |
| Owned session | 本次 CLI 启动的 Profile 才由本次 CLI Stop |
| Login required | 平台登录态失效；MLX 下 upload/check 退出 10 |
| Account label | 日志标识；MLX 缺省为 `profile_id`，不代表身份校验 |

## 3. 模式与激活

- 激活条件：`os.environ.get("MLX_API_TOKEN", "").strip() != ""`。
- 空串、纯空白、未设置 → 本地模式；`--folder-id` / `--profile-id` 被**静默忽略**。
- token 只从环境变量读取，**不进入 dataclass、请求对象、日志、异常文本、profile 文件**。
- Launcher 地址固定 `https://launcher.mlx.yt:45001`，`verify=True`，不提供覆盖变量。

## 4. CLI 契约

### 4.1 参数矩阵

| 参数 | 本地模式 | MLX 模式 |
|---|---|---|
| `--account` | 必填；决定 cookie 文件名 | 可选；仅 Account label，缺省 `profile_id` |
| `--folder-id` | 忽略 | 必填 |
| `--profile-id` | 忽略 | 必填 |
| `--headless` / `--headed` | 原有语义 | 直接映射 MLX `headless_mode` |
| `--debug` | 原有语义 | 原有语义 |
| `sau <p> login` | 原有行为（TikTok 除外） | 拒绝，退出 1 |
| `sau tiktok ...`（任何 action） | 拒绝，退出 1 | 仅 `check` / `upload-video` |

- 所有可在 MLX 运行的 action（`check`、`upload-*`）都注册 `--folder-id` / `--profile-id`；`login` 不注册。
- 条件必填在 `run()` 层校验，失败抛 `UsageError` → 退出 **2**（与 argparse 参数错误一致）。
- `--account` 由 `required=True` 改为 `required=False`；本地缺省仍退出 2。

### 4.2 退出码

| 码 | 含义 | 示例 |
|---|---|---|
| `0` | 成功 | 上传已提交；check 已登录；Stop 失败但上传成功（仅 warning） |
| `1` | 运行失败 | Launcher 不可达、token 无效、Profile 被占用、CDP 连不上、上传失败、网络错误、TikTok 本地调用、MLX 下 login |
| `2` | 用法错误 | 未知子命令、缺必填参数、缺 `--folder-id/--profile-id`、本地缺 `--account` |
| `10` | Login required | 登录页/登录表单/验证码/2FA |
| `130` | 用户中断 | `KeyboardInterrupt`，不属于调度契约；Stop 仍会执行 |

- `argparse` 自身错误由 argparse 退出 2；`sau_cli.main` 不捕获 `SystemExit`。
- 10 的唯一来源是 `LoginRequiredError`。

### 4.3 示例

```bash
# 本地模式（完全不变）
sau douyin upload-video --account creator --file demo.mp4 --title "标题"

# MLX：检查登录态（0=已登录，10=需人工登录）
MLX_API_TOKEN="$TOKEN" sau douyin check --folder-id "$FOLDER" --profile-id "$PROFILE"

# MLX：上传，账号标签缺省为 profile_id
MLX_API_TOKEN="$TOKEN" sau douyin upload-video \
  --folder-id "$FOLDER" --profile-id "$PROFILE" \
  --file demo.mp4 --title "标题" --tags tag1,tag2

# MLX：强制有头（人工处理验证码时使用）
MLX_API_TOKEN="$TOKEN" sau xiaohongshu check --folder-id "$FOLDER" --profile-id "$PROFILE" --headed

# MLX：login 不接受，退出 1
MLX_API_TOKEN="$TOKEN" sau douyin login --account creator   # 提示去 Multilogin 登录
```

## 5. 运行时架构

### 5.1 模块图

```
sau_cli.py
  └─ sau_commands/*.py            # 参数、模式判定、把 session 交给 uploader
       ├─ sau_commands/multilogin.py   # flags / target / account label / login 拒绝
       ├─ utils/browser_session.py     # 唯一 lifecycle seam（local + MLX）
       │    ├─ utils/multilogin.py     # MultiloginTarget / MultiloginClient（HTTP+token）
       │    └─ utils/errors.py         # LoginRequiredError / UsageError
       └─ uploader/*/main.py           # 业务主体 upload_in(session)
```

依赖方向：`sau_cli → sau_commands → utils`；uploader 只依赖 `utils/errors.py`（以及类型注解），**不 import `sau_commands`**。

### 5.2 MultiloginTarget / Client

```python
@dataclass(frozen=True, slots=True)
class MultiloginTarget:
    folder_id: str
    profile_id: str
    # 没有 api_token / headless 字段
```

- `MultiloginClient(token, http_get=None)`：`token` 只存在实例内；`http_get` 可注入，默认 `requests.get`。
- 方法：
  - `probe()` → `GET /api/v1/version`（无鉴权，3s），失败抛 `RuntimeError`；
  - `start(folder_id, profile_id, headless)` → `GET /api/v2/profile/f/{f}/p/{p}/start?automation_type=playwright&headless_mode={true|false}`，取 `data.port`；
  - `stop(profile_id)` → `GET /api/v1/profile/stop/p/{id}`；200 或 500 `profile already stopped` 视为成功；
  - `status(profile_id)` → 仅连接 3 次失败后调用一次，用于错误消息。
- 鉴权：`Authorization: Bearer <token>`；429 不在 CLI 内等待。

### 5.3 BrowserSession

```python
@dataclass(slots=True)
class BrowserSession:
    browser: Browser
    context: BrowserContext
    mode: Literal["local", "multilogin"]

async def browser_session(
    playwright: Playwright,
    *,
    headless: bool,
    account_file: str | Path | None = None,
    multilogin: MultiloginTarget | None = None,
    launch_kwargs: Mapping[str, Any] | None = None,
    context_kwargs: Mapping[str, Any] | None = None,
    init_script: bool = False,
    context_setup: Callable[[BrowserContext], Awaitable[BrowserContext | None]] | None = None,
) -> AsyncIterator[BrowserSession]
```

- 不暴露 `owned` / `stop()`；teardown 只由 `async with` 执行，防止重复或提前 Stop。
- `mode` 只允许 ticket 04 列出的平台特例读取。

### 5.4 时序

**MLX 分支**

```
probe(/version)
→ start(folder, profile, headless)
→ connect_over_cdp("http://127.0.0.1:{port}", no_defaults=True)
     超时 10s × 3 次，退避 2s → 4s
→ len(browser.contexts) == 1 ? 取 contexts[0] : fail-fast
→ yield session
      check:  is_logged_in(context) → 0 / 10 / 1
      upload: is_logged_in(context) → False 则 10；否则 upload_in(session)
→ browser.close()（只断开，不关闭浏览器）
→ stop(profile)（finally；取消路径 asyncio.shield）
```

**本地分支**

```
launch(headless, **launch_kwargs)
→ new_context(storage_state=account_file, **context_kwargs)
→ init_script ? set_init_script(context) : context
→ context_setup ? await context_setup(context) : context
→ yield session
→ 正常退出：context.storage_state(path=account_file)
→ context.close() → browser.close()
```

### 5.5 失败路径

| 阶段 | 行为 |
|---|---|
| probe 失败 | `RuntimeError` → 1；固定文案（桌面应用/同机/45001）；不 Start |
| Start 失败（401/403/404/429/5xx/lock） | `RuntimeError` → 1；保留 MLX `error_code`/message；**不 Stop 别人的 Profile** |
| Start 成功，connect 3 次失败 | 查一次 status 并入错误；finally Stop；→ 1 |
| `contexts` 数量 ≠ 1 | fail-fast；finally Stop；→ 1 |
| 登录页/验证码/2FA | `LoginRequiredError` → 10；finally Stop |
| 上传异常 | 原异常 → 1；finally Stop |
| **Stop 失败** | 上传成功时仍 → 0，stderr warning；不覆盖原异常 |
| 取消 / `KeyboardInterrupt` | `finally` 用 `asyncio.shield` 发 Stop；退出码保持 130 |
| Context 关闭/断开失败（MLX） | warning，不影响已上传结果；仍尝试 Stop |

日志（复用平台 loguru）：启动成功记录 `profile_id` / `folder_id` / `port`；开始停止记录一条；**不记录 token 与 Authorization 头**；不加耗时字段。

## 6. 上传器改造契约

### 6.1 seam

- 每个上传入口新增 keyword-only `session: BrowserSession | None = None`：

```python
async def douyin_upload_video(self, *, session: BrowserSession | None = None):
    if session is not None:
        await self.upload(None, session=session)
        return
    async with async_playwright() as playwright:     # legacy：Flask / 本地登录路径，原样保留
        await self.upload(playwright)

async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None):
    ...
```

- `session is None` → 完全走旧代码（Flask 兼容）。
- `session is not None` → 只执行 `upload_in(session)` 的业务主体；不 launch / new_context / set_init_script / storage_state / close。
- cookie 存在性校验、内容校验、cookie 读写、身份绑定全部留在本地分支；MLX 传 `account_file=None`。
- 构造函数与 positional 参数不变；新增参数一律 keyword-only。

### 6.2 禁止 API（MLX 分支）

`browser.new_context`、`browser.new_page`、`context.storage_state`、`context.add_cookies`、`context.clear_cookies`、`context.add_init_script`、`context.route`、`context.grant_permissions`、`context.set_geolocation`、`context.set_extra_http_headers`、`context.emulate_media`、`context.set_viewport_size`、`page.clock`。

允许：`context.new_page()`、`context.pages`、`page.goto/click/fill/...`、`browser.contexts`（只读）。

### 6.3 平台迁移表

`launch_kwargs` 不含 `headless`；`context_kwargs` 不含 `storage_state`。所有字面量从现有 `upload()` 原样搬运，实现时以代码为准并写入 golden test。

| 平台 | 上传入口 | launch_kwargs（要点） | context_kwargs（要点） | init_script | context_setup |
|---|---|---|---|---|---|
| douyin | `douyin_uploader/main.py` 视频/图文 `upload` | `channel="chromium"`、`args=["--no-sandbox","--disable-blink-features=AutomationControlled"]` | `permissions=["geolocation"]` | 是 | — |
| kuaishou | `ks_uploader/main.py` 视频/图文 `upload` | `executable_path=LOCAL_CHROME_PATH`（有值时）或 `channel="chromium"` | — | 是 | — |
| xiaohongshu | `xiaohongshu_uploader/main.py` 视频/图文 `upload` | `channel="chromium"` | `permissions=["geolocation"]` | 是 | — |
| tencent | `tencent_uploader/main.py` 视频/图文 `upload` | `_build_launch_kwargs()`（AutomationControlled + `LOCAL_CHROME_PATH`） | — | 是 | — |
| alipay | `alipay_uploader/main.py` `upload` | `_build_launch_kwargs()` | `permissions=["geolocation"]` | 否（刻意不用 stealth） | — |
| weibo | `weibo_uploader/main.py` `upload` | `_build_launch_kwargs()` | `viewport={"width":1280,"height":2000}` | 否 | — |
| hupu | `hupu_uploader/main.py` `upload` | `_build_launch_kwargs()` | — | 否 | `prepare_local_context`（UA + 1920×1080 + `_STEALTH_SCRIPT`） |
| facebook | `meta_uploader/facebook_uploader/main.py` `upload` | `channel="chrome"`、`proxy=_proxy_options(...)` | — | 否 | — |
| facebook-page | `meta_uploader/facebook_page_uploader/main.py` `upload` | 同上 | — | 否 | — |
| instagram | `meta_uploader/insgraph_uploader/main.py` `upload` | `channel="chrome"`、`proxy=_proxy_options(...)` | — | 否 | — |
| youtube | `youtube_uploader/main.py` `upload` | `channel="chrome"`、`proxy={"server": YT_PROXY}`（有值时） | — | 是 | — |
| baijiahao | `baijiahao_uploader/main.py` `upload` | `_build_launch_kwargs()` | `permissions=["geolocation"]` | 否 | — |
| dayu | `dayu_uploader/main.py` `main` | `executable_path=LOCAL_CHROME_PATH or None`、`channel="chrome"` | `timezone_id="Asia/Shanghai"` | 否 | — |
| xueqiu | `xueqiu_uploader/article.py` 上传 | `executable_path=LOCAL_CHROME_PATH or None`、`channel="chrome"` | — | 否 | — |
| zhihu | `zhihu_uploader/article.py` / `video.py` | `executable_path=LOCAL_CHROME_PATH or None`、`channel="chrome"` | `timezone_id="Asia/Shanghai"` | 否 | — |
| tiktok | `tk_uploader/main_chrome.py` `upload` | `executable_path=LOCAL_CHROME_PATH`（仅 legacy） | `permissions` 无 | 是（legacy） | — |

MLX 分支：以上 `launch_kwargs` / `context_kwargs` / `init_script` / `context_setup` 全部**静默忽略**；`account_file` 必须是 `None`。

## 7. 登录检测与身份

### 7.1 `is_logged_in`

```python
async def is_logged_in(context: BrowserContext) -> bool
```

- 位置：平台 uploader 模块（zhihu/xueqiu/dayu 放 `session.py`）。
- 明确登录页/登录表单/未登录锚点 → `False`；网络错误/5xx/超时/结构异常 → **抛异常**（→ 1）。
- 只用 `context.new_page()` / `goto` / `close`；总预算 15–30s（TikTok 20s）。
- MLX 调用点：
  - `check`：False → `LoginRequiredError`（10）；True → 0。
  - `upload`：上传前一次；False → 10。
- 本地模式不调用；继续用现有 `*_setup` / `check_*_account`。
- 上传中途遇到登录页/验证码/2FA → 上传器抛 `LoginRequiredError`（10）。

### 7.2 平台检测状态

| 平台 | 现有检测 | MLX 方案 |
|---|---|---|
| douyin | 可抽页面级判断 | 新增 `is_logged_in` |
| xiaohongshu | 可抽 | 新增 |
| kuaishou | 可抽 | 新增 |
| tencent | 可抽，需补正向信号 | 新增 |
| alipay | 不可直接复用 | 新写 |
| weibo | 需补正向信号 | 新写/加强 |
| hupu | 需补正向信号 | 新写/加强 |
| baijiahao | 需新写 | 新写 |
| dayu / xueqiu / zhihu | 可抽，但有身份绑定 | 新增，移除身份比对 |
| youtube / facebook / facebook-page / instagram | 可抽 | 新增 |
| tiktok | select 反推不可靠 | 新写（见 §9） |

### 7.3 身份一致性

- MLX 模式**只验证已登录**，Profile 即身份。
- 知乎/雪球/大鱼号/Instagram 的 `.identity.json` / 用户 ID 比对只在本地模式执行；MLX 分支跳过。
- 会话建立后打一条 INFO：`账号一致性未校验：以 Multilogin Profile 为身份（profile_id=...）`。
- 风险由调度 App 承担；CLI 不提供 `--account` 身份语义。

## 8. 平台特殊行为

| 平台 | MLX 差异 |
|---|---|
| 微博 | 不假设 2000px 高视口；发布按钮改用 `scroll_into_view_if_needed()` |
| 虎扑 | 不设置自定义 UA / stealth；若布局变化只改选择器，不改 Profile |
| 小红书 / 百家号 | 不 `grant_permissions`；若发布依赖定位，验收时确认 |
| 抖音 / 快手 / 小红书 | 最依赖 stealth；patchright 升级只跑测试用例，stealth 差异不做真实回归 |
| 知乎 / 大鱼号 | 不写 `timezone_id`；文档建议 Profile 时区设为 `Asia/Shanghai` |
| YouTube | `YT_PROXY` 静默丢弃；出口 IP 由 Profile 决定 |
| Facebook / Facebook Page / Instagram | `*_PROXY` / `--proxy` 静默丢弃 |
| 所有平台 | MLX 下 `login` 一律拒绝；验证码/2FA 一律 10 |

## 9. TikTok（仅 MLX）

- 平台名 `tiktok`；actions：`check`、`upload-video`、`login`（拒绝）。
- 参数与仓库对齐：`--file`、`--title`、`--tags`、`--schedule`、`--thumbnail`、`--account`（可选）、`--headless/--headed`、`--debug`；无 `--video-file` / `--publish-date` / `upload-note`。
- `TiktokVideo.__init__(title, file_path, tags, publish_date, account_file, thumbnail_path=None)` 不变；`account_file` 允许 `None`。
- `main_chrome.py` 改用 `patchright.async_api`；`main.py` 不接入。
- MLX 跳过 `change_language`；部署前提要求 Profile 界面为 English (US)。
- 发布循环总超时 15 分钟；验证码/登录页 → 10。
- `is_logged_in`：`https://www.tiktok.com/tiktokstudio/upload?lang=en`，20s，只开 1 个 page；上传入口 → True；`/login`/登录表单 → False；网络错误 → 抛异常。
- 本地模式任何 action、MLX 下 `login` → 1；未注册子命令 → 2。

## 10. 部署拓扑与前提

**v1 唯一支持：CLI 与 Multilogin 桌面应用在同一台 macOS/Windows 机器。**

| 拓扑 | v1 | 原因 |
|---|---|---|
| 本机桌面应用 | 支持 | 官方唯一闭环；`launcher.mlx.yt` → `127.0.0.1` |
| 本机 Docker launcher | 不支持 | CDP 端口段未映射；无官方 Playwright 示例；amd64 only |
| 跨机 | 不支持 | 官方只支持 `127.0.0.1`；不引导 SSH 隧道 |
| Linux 无桌面 | 不纳入 | 属于另一套部署形态 |

前置条件：

1. 桌面应用已启动，45001/45003 未被占用；
2. Profile 使用 Mimic 内核（Stealthfox 不支持 Playwright）；
3. Profile 已人工登录目标平台，且无待处理验证码/2FA；
4. CLI 与 Multilogin 同机；
5. TikTok 额外要求 Profile 界面为 English (US)。

探活：每次 MLX 会话 Start 前 `GET /api/v1/version`（无鉴权、3s、`verify=True`）。失败退出 1，文案：

```
无法连接 Multilogin Launcher（https://launcher.mlx.yt:45001）。
请确认：1) Multilogin 桌面应用已启动；2) CLI 与 Multilogin 在同一台机器；
3) 45001 端口未被占用或被防火墙拦截。
```

Start 成功但 CDP 3 次重试失败时，追加：`若你使用 Docker launcher，CDP 端口默认未映射到宿主机；v1 请改用 Multilogin 桌面应用。`

## 11. 调度侧责任

- 保证同一 Profile 不并发；CLI 不加锁。
- 传错 `profile_id` 导致发到别的账号：CLI 不校验，调度承担。
- 收到 10 时安排人工登录；收到 1 时按错误文本决定重试。
- Stop 失败（上传仍为 0）时负责清理残留 Profile。
- 跨机调度：在“MLX 那台机器”上远程执行 CLI，而不是把 CLI 指向远程 launcher。

## 12. 依赖与升级

- `patchright==1.64.4`（精确 pin）；Chromium 156 与 Mimic 156 对齐；Python 3.10–3.12。
- 作为独立提交先落地：更新 `pyproject.toml` + `uv.lock`，重新 `patchright install chromium`，只跑现有测试用例回归（**不做真实账号的完整验证回归**）。
- MLX 使用 `connect_over_cdp(..., no_defaults=True)`；ticket 08 若发现异常可回退为不传。
- `requirements.txt`（旧 Web 环境，`playwright==1.52.0`）不动。
- 回滚：恢复 `1.58.2` + lock + 重装浏览器；同步删除 `no_defaults`。

## 13. 测试策略

默认命令：`python -m unittest discover -s tests`；离线、不启浏览器、不访问网络。

| 层 | 替身 | 覆盖 |
|---|---|---|
| Client | 注入 `http_get`（不起 http.server） | Start/Stop URL、Bearer、`verify=True`、超时、错误码、Stop 幂等、token 卫生（测试注入 `http_get`，不发真实 TLS 请求） |
| Session | `tests/fakes.py` 手写 FakePlaywright/Browser/Context | 本地参数等价；MLX 生命周期；重试/退避；`contexts` 数量；finally Stop；shield；Stop 失败 warning |
| CLI | `AsyncMock` + fake playwright | 模式判定、缺参 2、`--account` 可省略、10/1/2/0、login 拒绝、本地忽略 MLX 参数 |
| 平台 | 表驱动 + 负向断言 | MLX 禁止 API；`is_logged_in` True/False/抛异常；`account_file=None` 不碰 cookie；身份 reader 未被调用 |
| 冒烟 | `SAU_MLX_SMOKE=1` opt-in | start → connect（恰好 1 context）→ close → stop；不上传 |

- 每个平台用 golden dict 锁定 `launch_kwargs` / `context_kwargs` / `init_script`，防止迁移时丢参数。
- 现有 `tests/test_sau_browser_cli.py` / `test_douyin_declaration.py` 保留为回归基线。
- 不自动化：平台真实发布、风控、验证码、代理指纹、Docker/跨机、前端。

## 14. 实施顺序（直接在当前分支落地，不建 PR）

1. **阶段 1 依赖**：patchright 1.64.4 + lock + 文档 + 现有测试用例回归（不做真实账号完整回归）。
2. **阶段 2 基础设施**：`utils/errors.py`、`utils/multilogin.py`、`utils/browser_session.py` + 单元测试（不接 CLI）。
3. **阶段 3 CLI 接线**：`sau_commands/multilogin.py`、flags、`sau_cli.main` 退出码映射、测试。
4. **阶段 4 平台批次 1**：douyin、xiaohongshu、kuaishou、tencent（含 `is_logged_in`）。
5. **阶段 5 平台批次 2**：alipay、weibo、hupu、baijiahao、dayu。
6. **阶段 6 平台批次 3**：youtube、facebook、facebook-page、instagram、zhihu、xueqiu。
7. **阶段 7 TikTok**：`sau_commands/tiktok.py` + `main_chrome.py` 改造 + 文档/skill。
8. **阶段 8 文档与验收**：README、`docs/CLI.md`、部署前提、调度侧责任。
9. **ticket 08**：真实 MLX 冒烟（外部依赖，可并行等待账号）。

## 15. 验收清单

- [ ] 无 token 时，所有平台旧命令解析与行为不变；无新增失败；基线本身有 5F/1E（与本 feature 无关）。
- [ ] MLX 下 check：已登录 0、未登录 10、Launcher 故障 1、缺参 2。
- [ ] MLX 下 upload：成功 0、登录失效 10、上传失败 1；成功后 Stop 被调用一次。
- [ ] Start 成功但 connect 失败：退出 1，且 Profile 被 Stop。
- [ ] 取消/KeyboardInterrupt：Stop 已发出（shield）。
- [ ] MLX 全程未调用 `new_context` / `storage_state` / `add_init_script` / `grant_permissions`。
- [ ] MLX 未读写任何 `cookies/*.json`；token 未出现在日志/异常。
- [ ] Profile 已运行时：退出 1，原始 lock 错误可见，且未 Stop 该 Profile。
- [ ] TikTok：无 token 退出 1；MLX check/upload 可用；验证码 10。
- [ ] `patchright==1.64.4` 现有测试用例回归通过（本地模式不做真实账号完整验证）。
- [ ] 文档包含部署前提、调度责任、账号一致性风险。

## 16. 风险与未决

| 项 | 状态 | 处理 |
|---|---|---|
| 真实 MLX 未验证（ticket 08） | 阻塞外部依赖 | 所有 Launcher 结论按 `[官方]/[社区]` 置信度实施；拿到账号后回填 |
| Docker launcher CDP 端口 | 未闭环 | v1 不支持；仅错误提示 |
| patchright 升级后的平台风控 | 未验证（接受） | 阶段 1 只跑测试用例；真实使用暴露后再评估/回滚 |
| 虎扑 UA 依赖 | 中 | MLX 使用 Profile 默认 UA；布局异常只改选择器 |
| 微博高视口依赖 | 中 | 改用滚动到可视区 |
| 小红书/百家号定位权限 | 中 | MLX 不授予；验收确认发布是否依赖 |
| 身份错配风险 | 接受 | 调度侧负责；CLI 打 INFO 声明 |
| 无头模式下人工验证 | 已知 | 文档建议先 `--headed` 人工处理，再切 headless |
| `no_defaults=True` 与 Mimic | 待验证 | ticket 08 决定是否保留 |
| MLX 限流（429） | 已知 | CLI 不等待；由调度侧重试 |
