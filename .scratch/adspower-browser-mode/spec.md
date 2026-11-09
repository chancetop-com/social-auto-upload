# AdsPower 浏览器模式 — 设计规格

状态：设计完成，待实现。汇总自 01–07、10 号 ticket；真实 AdsPower 冒烟（09）因本机未安装而外部阻塞。
基线：`ee79dec`（2026-11-06）。置信度标注沿用 `.scratch/multilogin-browser-mode/spec.md`：`[官方]` / `[社区]` / `[实测]` / `[设计]`。

---

## 0. 摘要

在**不改变本地模式**、**除 429 外不改变 Multilogin X（MLX）可观察行为**的前提下，新增由 `ADSPOWER_API_KEY` 激活的 AdsPower 托管浏览器模式：

- 复用 `--profile-id`（映射 AdsPower `user_id` / V2 `profile_id`）启动 Profile；
- 通过 `data.ws.puppeteer` 的 CDP WebSocket 接管现有 `BrowserContext`；
- 复用 Profile 已保存的登录态，跑现有上传逻辑；
- 结束时停止 Profile（谁启动谁停止）；
- 与 MLX 共享参数矩阵、退出码、登录失效契约与平台覆盖。

实现上把 managed 分支抽成 provider 接口，MLX 与 AdsPower 各实现一份；`browser_session` 保留唯一生命周期模板，本地分支与生命周期实现不复制。

---

## 1. 目标与非目标

### 目标

1. `ADSPOWER_API_KEY` 非空即进入 AdsPower 模式；本地与 MLX 的激活规则不变。
2. `sau <platform> check|upload-*` 在 AdsPower 模式下复用 Profile 登录态，不读写 `cookies/*.json`。
3. 新增 `AdspowerClient`（V2 Local API）与 `AdspowerProvider`，与 MLX 同构。
4. 生命周期、CDP 重试、contexts 校验、取消时 stop、stop 失败降级全部与 MLX 一致。
5. 新增双方共用的退出码 `11`（HTTP 429）；MLX 的 429 由 `1` 改为 `11`，这是本 effort 唯一一次 MLX 可观察行为变更。
6. 全离线测试可证明 AdsPower 接线正确，且默认套件不依赖真实 AdsPower。

### 非目标

- Flask `sau_backend.py`、`myUtils/`、Vue 前端。
- 本地模式行为变更。
- MLX 除 429 外的行为变更。
- AdsPower 无 key 安装（关闭 API 安全校验）。
- AdsPower V1 Local API / 双栈 / fallback。
- AdsPower Firefox Profile（Playwright/CDP 仅 Chromium）。
- 在 AdsPower 中创建/修改 Profile、管理代理、导入/导出 Cookie。
- 账号 ↔ Profile 映射文件。
- 跨机 AdsPower、Docker AdsPower、无桌面 Linux。
- Bilibili（`biliup` 子进程，无浏览器上下文）。
- 调度 App 本身（接单、分配、重试、上报、人工登录回流）。
- 第三个 provider（BitBrowser 等）；只把接缝做成可扩展。

---

## 2. 术语

完整定义见 ticket 06 与 `GLOSSARY.md`，这里是规格内固定用法：

| 术语 | 含义 |
|---|---|
| 托管浏览器模式（managed browser mode） | 由桌面应用提供 Profile、CLI 通过 CDP 接管的统一模式；下分 MLX / AdsPower |
| Multilogin X 模式（MLX） | 由 `MLX_API_TOKEN` 激活的子模式 |
| AdsPower 模式 | 由 `ADSPOWER_API_KEY` 激活的子模式 |
| Profile | 桌面应用里的隔离浏览器身份；登录态、代理、指纹由它持有 |
| `profile_id` | CLI `--profile-id` 的值；AdsPower V2 请求体字段；等价于 AdsPower 的 `user_id` |
| `folder_id` | MLX 必填；AdsPower 注册但忽略 |
| Local API | AdsPower 桌面应用在本机暴露的 HTTP 接口，默认 `http://127.0.0.1:50325`，本规格只用 V2 |
| API Key | AdsPower Automation → API 生成的凭据，以 `Authorization: Bearer <API Key>` 发送 |
| managed | `BrowserSession.managed`，`mode != "local"` 的同义属性 |

书写规范：产品名 `AdsPower`；代码标识 `AdspowerProvider` / `AdspowerClient` / `utils/adspower.py`；环境变量 `ADSPOWER_API_KEY` / `ADSPOWER_API_BASE`；字段名用反引号小写蛇形。

---

## 3. 模式与激活

### 3.1 优先级

| `MLX_API_TOKEN`（strip） | `ADSPOWER_API_KEY`（strip） | 模式 |
|---|---|---|
| 空 / 未设置 | 空 / 未设置 | 本地 |
| 非空 | 空 / 未设置 | MLX |
| 空 / 未设置 | 非空 | AdsPower |
| 非空 | 非空 | 冲突：`RuntimeError` → 退出 `1` |

- 只按环境变量选择，不新增 `--browser-provider` 之类 flag。
- `ADSPOWER_API_BASE` **不参与激活**；单独存在不改变模式、不告警。
- 使用 strip 后的值；key 只存在 client 实例内。
- 无 key 的 AdsPower 安装不探测、不警告，静默按本地 / MLX 原逻辑运行。

### 3.2 双模式冲突

- 判定位置：`sau_cli.main()` 内，`parse_args()` 之后、`dispatch()` 之前，位于现有 `try` 块中。
- 因此 `--help`、未知子命令、缺必填参数仍保持 argparse 原语义；冲突优先于命令级 `login` 拒绝。
- 固定文案：`MLX_API_TOKEN 与 ADSPOWER_API_KEY 不能同时设置；请只保留一个。`
- 退出码 `1`，不是用法错误 `2`。
- 直接调用 `sau_commands.<platform>.run()` 的内部调用方不经过该检查。

### 3.3 `ADSPOWER_API_BASE`

- 仅在 AdsPower 激活后、发第一个请求前解析。
- 合法：`http` / `https`；必须有 host；端口可选；禁止 userinfo、path、query、fragment；末尾 `/` 归一化去掉。
- 默认 `http://127.0.0.1:50325`；允许 `http://local.adspower.net:50325` 等官方地址。
- 非法 → `UsageError` → `2`，且**不发任何请求**。
- 合法但连不上 → 运行期 `1`。

---

## 4. CLI 契约

### 4.1 参数矩阵

| 参数 / 行为 | 本地 | MLX | AdsPower |
|---|---|---|---|
| `--account` | login/check/upload-* 必填；verify/delete 必填 | 可选；无身份/cookie/输出语义 | 可选；纯兼容占位，无身份/cookie/输出语义 |
| `--folder-id` | 静默忽略 | 必填 | 注册但静默忽略；传值不报错、不告警 |
| `--profile-id` | 静默忽略 | 必填 | 必填；strip 后映射 AdsPower `user_id`（V2 `profile_id`） |
| 缺 `--profile-id` | 不适用 | `2` | `2` |
| 缺 `--folder-id` | 不适用 | `2` | 不适用 |
| `--headless` | 默认 True | 默认 True，传给 start | 默认 True，V2 编码 `"1"` |
| `--headed` | False | False | False，V2 编码 `"0"` |
| `--debug` | uploader 行为 | uploader 行为 | uploader 行为；不传给 AdsPower |
| `login` | 允许 | `1` | `1` |
| `verify` / `delete` | 本地执行 | 本地执行 | 本地执行 |
| `check` 未登录 | `invalid` + `1` | `10` | `10` |
| Bilibili | 允许 | `1` | `1` |
| `article` | 本地工具 | 本地工具 | 本地工具 |

- `--profile-id` 只校验 strip 后非空；不猜格式。Profile 不存在/被占用/内核未就绪交给服务端 → `1`。
- `--account` 纯空白不做特殊处理。
- 共享旗标 help 用中性文案：`--profile-id` 标注“MLX / AdsPower 模式必填”；`--folder-id` 标注“MLX 模式必填；AdsPower 模式忽略”。
- 注册范围：除 `bilibili` 外，所有 `check` 与 `upload-*` 注册；`login`、`verify`、`delete`、`article` 不注册。
- `AdsPower 激活时 sau <p> login`：不带 flag 进入 `run()` 后拒绝 → `1`；显式带 `--profile-id` 时因 login 解析器未注册该 flag，argparse 退出 `2`（与 MLX 一致）。
- 不打印模式 banner；`check` 成功只输出 `valid`，保持 stdout 可解析。

### 4.2 退出码

| 码 | 含义 | 典型场景 |
|---|---|---|
| `0` | 成功 | 上传已提交；check 已登录；stop 失败但主操作成功 |
| `1` | 运行失败 | API 不可达、key 无效、Profile 不存在/被占用、CDP 连不上、上传失败、网络错误、双模式冲突、login/平台拒绝 |
| `2` | 用法错误 | 缺 `--profile-id`、`ADSPOWER_API_BASE` 非法、本地缺 `--account`、未知子命令 |
| `9` | 发布结果未知 | 发布点击已发出但未观察到成功页；禁止自动重发 |
| `10` | 需要登录 | 登录页、登录表单、验证码、2FA |
| `11` | 请求过于频繁（429） | MLX Launcher 或 AdsPower Local API 返回 HTTP 429；调度层退避重试 |
| `130` | 用户中断 | `Ctrl-C`，不捕获 |

- `11` 是 MLX 与 AdsPower 共用契约；MLX 行为变更已批准，需在 `docs/CLI.md`、README、CHANGELOG 同步。
- `sau_cli.main()` 的 `except RateLimitedError` 必须排在 `except Exception` 之前，返回 `11`。
- 已成功操作仅在 stop 阶段遇到 429 → 只 warning，保持原退出码（通常 `0`）。
- HTTP 200 + 业务 `code` 表示限流的情况官方未定义，暂按 `1`；待 09 smoke 再扩展。
- 不预检 `active`；start 成功即本次 owned，结束时 stop；并发同 Profile 由调度层保证。

### 4.3 示例

```bash
# 本地模式（完全不变）
sau douyin check --account creator

# MLX：检查登录态
MLX_API_TOKEN="$TOKEN" sau douyin check --folder-id "$FOLDER" --profile-id "$PROFILE"

# AdsPower：检查登录态（--folder-id 可省略；传了也忽略）
ADSPOWER_API_KEY="$KEY" sau douyin check --profile-id "$PROFILE"

# AdsPower：上传，账号标签缺省为 profile_id
ADSPOWER_API_KEY="$KEY" sau douyin upload-video \
  --profile-id "$PROFILE" --file ./demo.mp4 --title "标题"

# AdsPower：强制有头（人工处理验证码）
ADSPOWER_API_KEY="$KEY" sau douyin upload-video --headed \
  --profile-id "$PROFILE" --file ./demo.mp4 --title "标题"

# AdsPower：login 拒绝 → 1
ADSPOWER_API_KEY="$KEY" sau douyin login --account creator

# AdsPower：bilibili 拒绝 → 1
ADSPOWER_API_KEY="$KEY" sau bilibili check --account creator

# 自定义 Local API 地址
ADSPOWER_API_KEY="$KEY" ADSPOWER_API_BASE="http://127.0.0.1:50326" sau douyin check --profile-id "$PROFILE"
```

### 4.4 `login` 拒绝文案

- AdsPower：`AdsPower 模式不支持 CLI 登录；请在 AdsPower 中登录 Profile {profile} 后重试。`
- MLX：保持现有 `Multilogin 模式不支持 CLI 登录；请在 Multilogin 应用中登录 {profile} 后重试。`
- 未提供 `--profile-id` 时占位为 `指定 Profile`。

---

## 5. 运行时架构

### 5.1 模块图

```
sau_cli.py
  └─ sau_commands/*.py                 # 参数、provider 选择、把 session 交给 uploader
       ├─ sau_commands/browser.py      # 激活判定、flags、provider 构造、label、拒绝、错误文案
       ├─ sau_commands/multilogin.py   # 兼容 shim：re-export 旧符号
       ├─ utils/browser_session.py     # 唯一 lifecycle seam（local + managed）
       │    ├─ utils/managed_browser.py  # ManagedBrowserProvider Protocol / ProviderMode（叶子）
       │    ├─ utils/multilogin.py       # MultiloginTarget / MultiloginClient / MultiloginProvider
       │    └─ utils/adspower.py         # AdspowerTarget / AdspowerClient / AdspowerProvider
       ├─ utils/errors.py              # LoginRequiredError / UsageError / PublishResultUnknownError
       │                               # + RateLimitedError + StartIncompleteError
       └─ uploader/*/main.py           # 业务主体 upload_in(session)
```

依赖方向：`sau_cli → sau_commands → utils`。`utils/managed_browser.py` 只依赖 `typing`；uploader 只依赖 `utils.browser_session.BrowserSession` 与 `utils.errors`，不 import provider。

### 5.2 Provider Protocol（`utils/managed_browser.py`）

```python
ProviderMode = Literal["multilogin", "adspower"]

class ManagedBrowserProvider(Protocol):
    mode: ProviderMode
    profile_id: str

    def probe(self) -> None: ...
    def start(self, headless: bool) -> str: ...   # 返回可直接 connect_over_cdp 的 URL
    def stop(self) -> None: ...
    def status(self) -> str: ...                  # 仅诊断
```

- 结构化 Protocol，不用 ABC、不加 `@runtime_checkable`；`browser_session` 永不做 `isinstance`。
- `start` 是端点归一化的唯一出口：
  - `MultiloginProvider.start` 调 `client.start(folder_id, profile_id, headless)` 得 port，返回 `f"http://127.0.0.1:{port}"`；
  - `AdspowerProvider.start` 调 `client.start(profile_id, headless)`，**原样**返回 `data.ws.puppeteer`（`ws://...`）；不反推 http（`cdp_mask=1` 下 http 入口可能落到另一个实例）。
- `stop()` / `status()` 无参；provider 自己持有 `profile_id`。

### 5.3 `BrowserSession` 与 `browser_session`

```python
@dataclass(slots=True)
class BrowserSession:
    browser: Browser
    context: BrowserContext
    mode: Literal["local", "multilogin", "adspower"]

    @property
    def managed(self) -> bool:
        return self.mode != "local"


async def browser_session(
    playwright: Playwright,
    *,
    headless: bool,
    account_file: str | Path | None = None,
    managed: ManagedBrowserProvider | None = None,
    launch_kwargs: Mapping[str, Any] | None = None,
    context_kwargs: Mapping[str, Any] | None = None,
    init_script: bool = False,
    context_setup: Callable[["BrowserContext"], Awaitable["BrowserContext | None"]] | None = None,
) -> AsyncIterator[BrowserSession]:
```

- `managed is None` → 本地分支；否则走通用 `_managed_session` 模板。
- `_local_session`、`launch_kwargs`、`context_kwargs`、`init_script`、`context_setup` 语义逐字冻结；唯一改动是分发条件从 `multilogin is None` 改为 `managed is None`。
- `browser_session` 不再读环境变量；“未设置 token”的防御检查搬进 `resolve_managed_provider()`，用户可观察行为不变（仍退出 `1`）。
- 不暴露 `owned` / `stop()`；teardown 只由 `async with` 执行。

### 5.4 `AdspowerClient`（`utils/adspower.py`）

**端点** `[官方]`：

| 能力 | 端点 | 方法 | 载荷 |
|---|---|---|---|
| 探活 | `/status` | `GET` | 无（带 Bearer） |
| 启动 | `/api/v2/browser-profile/start` | `POST` | JSON |
| 停止 | `/api/v2/browser-profile/stop` | `POST` | JSON `{"profile_id": "..."}` |
| 状态 | `/api/v2/browser-profile/active?profile_id=...` | `GET` | query |

- 只做 V2；不做 V1 fallback / 双栈 / 运行时版本探测。老客户端 404 → “AdsPower 版本过旧或 Local API 未开启” → `1`。
- 公开原语与 `MultiloginClient` 同构：

| 职责 | `MultiloginClient` | `AdspowerClient` |
|---|---|---|
| 探活 | `probe() -> None` | `probe() -> None` |
| 启动 | `start(folder_id, profile_id, headless) -> port` | `start(profile_id, headless) -> ws_url` |
| 停止 | `stop(profile_id) -> None` | `stop(profile_id) -> None` |
| 状态 | `status(profile_id) -> str` | `status(profile_id) -> str`（打 V2 `/active`，方法名仍叫 `status`） |

- 构造：`AdspowerClient(key, base, http_get=None, http_post=None)`；`__repr__` 输出 `token=<redacted>`。
- 固定 start 请求体 `[官方]`：

```json
{
  "profile_id": "<profile_id>",
  "headless": "1",
  "last_opened_tabs": "0",
  "proxy_detection": "0",
  "delete_cache": "0",
  "cdp_mask": "1"
}
```

  - `last_opened_tabs=0` / `proxy_detection=0`：避免继承历史页与 IP 检测页。
  - `delete_cache=0`：避免清掉 Profile 登录态。
  - `cdp_mask=1`：官方默认，与 Playwright `connect_over_cdp` 兼容。
  - 所有 `"0"/"1"` 转换在 client 内完成；调用方只传 `bool`。
- 响应：通用 envelope `{"code": int, "data": object|absent, "msg": str}`。
  - `start`：要求 HTTP 2xx + `code == 0` + `data.ws.puppeteer` 非空；见 §6.2 的 `StartIncompleteError`。
  - `stop`：要求 HTTP 2xx + `code == 0`；成功响应可无 `data`。
  - `status`：读 `data.status`（`Active` / `Inactive`）；缺字段返回 `"unknown"`；传输/HTTP 错误抛 `RuntimeError`，由 session 层降级为“查询失败”。
- 超时（不做环境变量覆盖）：probe 3s；start 30s；stop 30s；status 30s。
- 不重试；仅 HTTP 429 抛 `RateLimitedError`。

### 5.5 错误分层

| 类型 | 触发 | 退出码 |
|---|---|---|
| `RateLimitedError` | HTTP 429（MLX 与 AdsPower client） | `11` |
| `StartIncompleteError(RuntimeError)` | AdsPower start 返回 HTTP 2xx + `code == 0` 但 ws 缺失/空，或 2xx 但非法 JSON / 缺 `code` | `1` |
| `RuntimeError` | 传输、非 2xx、业务 `code != 0`、协议漂移、CDP 连接失败、contexts 异常 | `1` |
| `LoginRequiredError` | 登录页/验证码/2FA | `10` |
| `UsageError` | 缺 `--profile-id`、base 非法、本地缺 `--account` | `2` |
| `PublishResultUnknownError` | 发布点击已发出但未观察到成功 | `9` |

- 错误文案：`<动作>失败：HTTP <status>；code=<code>；msg=<msg>`；无 msg 时截取响应体前 500 字符。
- 连不上：`无法连接 AdsPower Local API（{base}）。\n请确认：1) AdsPower 桌面应用已启动；2) 本地 API 已开启；3) CLI 与 AdsPower 在同一台机器且端口未被占用。`
- 401/403：提示检查 `ADSPOWER_API_KEY` 与账号 Local API 权限。
- 429：点明“请求过于频繁”，不重试。
- Profile 不存在/被占用/内核未就绪：保留原始 `msg`。
- 所有异常、`repr`、日志中绝不出现 key / `Authorization`。

---

## 6. 生命周期与所有权

### 6.1 `_managed_session` 模板

顺序固定：

1. `await asyncio.to_thread(provider.probe)`
2. `connect_url = await asyncio.to_thread(provider.start, headless)`
3. 日志只打 `provider.mode`、`profile_id`、endpoint 的 `host:port`（不打 token，不打完整 ws 路径）
4. `_connect_over_cdp(playwright, provider, connect_url)`：3 次尝试，每次 10s，退避 2s / 4s；最终失败调一次 `provider.status()` 补诊断，然后抛 `RuntimeError`
5. `len(browser.contexts) != 1` → `RuntimeError`，文案 provider 中立（带 `mode` 与 `profile_id`，不选第一个、不修复）
6. `yield BrowserSession(browser=..., context=browser.contexts[0], mode=provider.mode)`
7. `finally`：`_disconnect(browser)`（失败仅 warning）→ `asyncio.shield(asyncio.to_thread(provider.stop))`（失败仅 warning）

### 6.2 所有权与 `StartIncompleteError`

| 服务端结果 | client 行为 | 会话层行为 | 退出码 |
|---|---|---|---|
| HTTP 2xx + `code == 0` + ws 非空 | 返回 ws | 正常连接，结束后 stop | `0` / 业务码 |
| HTTP 2xx + `code == 0` + ws 缺失/空 | 抛 `StartIncompleteError` | **best-effort stop**（失败仅 warning）→ 原样抛出 | `1` |
| HTTP 2xx + 非法 JSON / 缺 `code` | 抛 `StartIncompleteError` | 同上（可能已启动，宁可 stop） | `1` |
| HTTP 非 2xx，或 `code != 0` | `RuntimeError`（429 → `RateLimitedError`） | **不 stop** | `1` / `11` |
| 传输失败 / 超时 / 连接重置 | `RuntimeError` | **不 stop** | `1` |

- `start` 成功即本次会话 owned，退出时必然 stop。
- `start` 失败绝不停 Profile（“谁启动谁停止”）。
- `StartIncompleteError` 只作内部生命周期信号；`sau_cli` 不单独映射。
- 已运行 Profile 不预检：直接 start；服务端返回成功（含既有 ws）按 owned 处理；该响应形状仍是 09 的未知项。
- 库内不加锁、不做占用检测；同一 Profile 的并发由调度 App 串行保证。

### 6.3 连接失败 / contexts / 断开 / 停止

- 连接失败：3 次 × 10s，退避 2s/4s；最终失败查一次 status 并写入错误；finally stop → `1`。
- contexts ≠ 1：立即失败 → finally stop → `1`。
- 断开：`await browser.close()` 仅断开 CDP；失败只 WARNING（“已上传结果不受影响”）。
- 停止：单独 `await asyncio.shield(asyncio.to_thread(provider.stop))`；失败只 WARNING（“Profile 可能仍在运行，需调度侧清理”），不覆盖原异常、不改变退出码。
- 取消/中断：进入 `try`（已确认 owned）后，普通异常、`KeyboardInterrupt`、`CancelledError` 都走 finally；stop 用 shield 保证请求已发出；`CancelledError` 在断开与 stop 后重新抛出；`KeyboardInterrupt` 保持 `130`。

### 6.4 幂等与重试

- stop 仅在 HTTP 2xx + `code == 0` 时算成功；其余抛 `RuntimeError`。
- 不加“已经停止”特例；重复 stop 的真实响应交 09 实测后再决定。
- stop 不重试；幂等性由会话层“只 warning”兑现。
- client 层不重试；只有 HTTP 429 抛 `RateLimitedError`。

### 6.5 页面与 headless

- start 固定 `last_opened_tabs=0`、`proxy_detection=0`、`delete_cache=0`、`cdp_mask=1`。
- 不主动关闭/切换页面；上传器自己导航。
- headless 默认 True；`--headed` → False；V2 编码 `"1"/"0"`；不做“headed 才能上传”的额外限制。

### 6.6 日志

| 事件 | 级别 | 内容 |
|---|---|---|
| start 成功 | INFO | `AdsPower Profile 已启动：profile_id={} endpoint={host}:{port}` |
| stop 开始 | INFO | `正在停止 AdsPower Profile：profile_id={}` |
| 断开 CDP 失败 | WARNING | 原始异常；注明“已上传结果不受影响” |
| stop 失败 | WARNING | 原始异常；注明“Profile 可能仍在运行，需调度侧清理” |
| 失败 | stderr | 保留 HTTP status / `code` / `msg`；不含 key |

- endpoint 只打 `host:port`，不打完整 ws 路径。
- 不记耗时；`--debug` 不改变生命周期日志，也不传给 AdsPower。
- `Authorization` 与 key 永不记录，连截断也不打。

---

## 7. 逐平台表

完整事实清点见 [07 — 逐平台迁移清单](./research/07-platform-inventory.md)。本规格采用其矩阵：

### 7.1 支持范围

- **16 个托管浏览器平台**：alipay、baijiahao、dayu、douyin、facebook、facebook-page、hupu、instagram、kuaishou、tencent、tiktok、weibo、xiaohongshu、xueqiu、youtube、zhihu。
- **Bilibili 不支持**（`biliup` 子进程，无浏览器上下文）。
- **`article`** 是本地工具命令，不受模式影响。
- **`verify` / `delete`** 始终本地执行（dayu、facebook、facebook-page、instagram、xueqiu、zhihu 共 6 个命令对象、9 个 action）。

### 7.2 action 矩阵

| 平台 | login | check | upload-video | upload-note | upload-article | verify | delete |
|---|:--:|:--:|:--:|:--:|:--:|:--:|:--:|
| alipay | 本地 | 托管 | 托管 | — | — | — | — |
| baijiahao | 本地 | 托管 | 托管 | — | — | — | — |
| bilibili | 本地 | ✗ | ✗ | — | — | — | — |
| dayu | 本地 | 托管 | 托管 | — | 托管 | 本地 | — |
| douyin | 本地 | 托管 | 托管 | 托管 | — | — | — |
| facebook | 本地 | 托管 | 托管 | 托管 | — | 本地 | 本地 |
| facebook-page | 本地 | 托管 | 托管 | 托管 | — | 本地 | 本地 |
| hupu | 本地 | 托管 | 托管 | — | — | — | — |
| instagram | 本地 | 托管 | 托管 | 托管 | — | 本地 | 本地 |
| kuaishou | 本地 | 托管 | 托管 | 托管 | — | — | — |
| tencent | 本地 | 托管 | 托管 | — | — | — | — |
| tiktok | 本地 | 托管 | 托管 | 托管 | — | — | — |
| weibo | 本地 | 托管 | 托管 | — | — | — | — |
| xiaohongshu | 本地 | 托管 | 托管 | 托管 | — | — | — |
| xueqiu | 本地 | 托管 | — | — | 托管 | 本地 | — |
| youtube | 本地 | 托管 | 托管 | — | — | — | — |
| zhihu | 本地 | 托管 | 托管 | — | 托管 | 本地 | — |

图例：“托管” = MLX 与 AdsPower 都支持；“本地” = 该模式下仍走本地分支；“—” = 无此 action；“✗” = 拒绝。

### 7.3 迁移规模（实测）

- 17 个平台模块 import `sau_commands.multilogin`。
- 36 个 `browser_session(...)` 调用点（16 个模块）。
- 16 个 `resolve_multilogin_target(...)` 调用点。
- 41 个 `add_multilogin_flags(...)` 落点。
- 28 处 `session.mode == "multilogin"`（18 个 uploader 文件；含 `insgraph_uploader/main.py:446,456` 两处单引号）。
- 26 个内部 `multilogin: bool` 参数（阶段 1 不改名）。

### 7.4 平台特有约束（由 `session.managed` 继承 MLX 分支）

- **TikTok**：Profile 必须已设置 English (US)；托管分支跳过 `change_language`；图文发布依赖 Photos tab 灰度，缺入口时在选文件前失败。
- **Meta（facebook / facebook-page / instagram）**：`--proxy` / `SAU_FACEBOOK_PROXY` / `INSTAGRAM_PROXY` 不转发；Profile 拥有出口 IP、指纹与身份。
- **YouTube**：本地 `conf.YT_PROXY` 不转发；托管分支忽略 `launch_kwargs`。
- **身份绑定**：dayu / zhihu / xueqiu / instagram 在托管分支不读 cookie / `.identity.json`、不做 account-id 比对；Profile 即身份。
- **时区**：dayu 托管分支不写 `timezone_id`；建议在 Profile 中设为 `Asia/Shanghai`。
- **剪贴板**：zhihu / xueqiu 托管分支跳过 `context.grant_permissions`。
- **图文/视频差异**：douyin、facebook、facebook-page、instagram、kuaishou、tencent、tiktok、xiaohongshu、dayu、zhihu 同时有视频与图文/文章 action；alipay、baijiahao、hupu、weibo、youtube 仅视频；xueqiu 仅文章。
- **`--schedule`**：支持 bilibili、dayu、douyin、facebook-page、kuaishou、tencent、tiktok、xiaohongshu、youtube、zhihu；不支持 alipay、baijiahao、facebook 个人主页、hupu、instagram、weibo、xueqiu。

---

## 8. 登录检测与身份

- Profile 即身份：托管模式不读 `cookies/*.json`、不写 cookie、不比较本地 identity 文件。
- `check`：调用平台自己的 `is_logged_in(context)`；已登录 → `0` 并输出 `valid`；登录页/验证码/2FA → `10`。
- `upload-*`：上传前检测一次；未登录 → `10` 且不执行上传。
- 上传过程中遇到登录页/验证码/2FA → `LoginRequiredError` → `10`。
- 日志可打“账号一致性未校验：以 <mode> Profile 为身份”，但不得宣称已核对身份。
- `--account` 仅日志标签，缺省为 `profile_id`；本地模式保持原 cookie 路径语义。

---

## 9. 安全

- API key / token 只从环境变量读取；不写入命令行、日志、异常文本、`repr`、测试输出。
- `AdspowerClient.__repr__` 输出 `token=<redacted>`；`Authorization` 永不记录。
- 文档示例不把 key 放进命令行（用 `ADSPOWER_API_KEY="$KEY"`）。
- `ADSPOWER_API_BASE` 只允许 `http/https` + host + 可选端口；禁止 userinfo/path/query/fragment；末尾 `/` 归一化；非法 `2`。
- 禁止远程/跨机 base；默认只连本机。
- 不暴露 `delete_cache` / `cdp_mask` / `launch_args` 等危险参数；由 provider 固定安全值。
- 失败诊断脱敏：不含 API key、不含真实账号/Profile 名称（09 的 smoke 同要求）。

---

## 10. 部署前提与调度责任

### 10.1 硬前提

1. AdsPower 付费版（Local API 仅付费版提供）`[官方]`。
2. 桌面应用与 CLI 同一台 macOS/Windows 机器；应用已启动；Local API 已开启；`50325` 未被占用。
3. `ADSPOWER_API_KEY` 有效；请求带 `Authorization: Bearer`。
4. Profile 为 Chromium 内核；Firefox 不支持。
5. Profile 已人工登录目标平台，无待处理验证码/2FA；TikTok Profile 界面 English (US)。
6. AdsPower 客户端升级到最新 patch（官方未给最低版本）。
7. `ADSPOWER_API_BASE` 默认 `http://127.0.0.1:50325`；仅在改端口或使用官方地址时设置。
8. 同一 Profile 串行使用；CLI 不加锁、不做 active 预检。

### 10.2 明确不支持

无 key 安装、V1 API、Firefox Profile、Docker/跨机/无桌面 Linux、Bilibili、通过 CLI 登录、在 AdsPower 中创建/修改 Profile 或管理代理/Cookie。

### 10.3 调度侧责任

- Profile 即身份；同一 Profile 串行。
- `10` → 安排人工登录。
- `9` → 禁止自动重发，先核对平台侧是否已发布。
- `11` → 退避重试。
- `1` → 运行失败，不与登录失效混淆。
- stop 失败只 warning；主操作成功仍 `0`；调度侧负责清理残留 Profile。

### 10.4 排查

连不上时依次检查：桌面应用是否启动 → Local API 是否开启 → 端口是否被占用。

---

## 11. 测试矩阵与验收

### 11.1 测试层级

全部纯离线 `unittest`；不启动真实浏览器、不访问网络。所有 HTTP 走注入的 `http_get` / `http_post`；所有 CDP 走 `FakePlaywright`。

新增 4 个文件（ticket 05）：

| 文件 | 覆盖 |
|---|---|
| `tests/test_adspower_client.py` | V2 端点、固定 body、envelope、超时、429 → `RateLimitedError`、`StartIncompleteError`、脱敏 |
| `tests/test_adspower_browser_session.py` | `managed` 真值表、`probe → start → connect → stop` 顺序、`StartIncompleteError` 先 stop、ws 原样传入、contexts、取消、stop 失败 |
| `tests/test_adspower_cli.py` | 激活矩阵、双模式冲突、base 校验、参数矩阵、注册范围、退出码、key 脱敏 |
| `tests/test_adspower_platform_contract.py` | 静态守卫：`uploader/` 与 `sau_commands/` 不得残留 `.mode == "multilogin"` |

### 11.2 阶段 1 回归

- 允许改动：`test_browser_session.py` 的 `multilogin=` → `managed=` 迁移与 `managed` 真值表；`test_multilogin_client.py` 改用共享 fake。
- 必须零业务断言改动：其余 `test_mlx_*.py`、`test_douyin_upload_seam.py`、`test_tiktok_*`、`test_sau_browser_cli.py`。
- **例外（07 发现）**：`tests/test_mlx_smoke.py:377` 与 `tests/test_mlx_hupu_dayu.py:405` 直接调用 `browser_session(multilogin=...)`；若签名改为 `managed=`，这两处各改 1 行。规格采用“允许各改 1 行”，而不是声称 8 个 `test_mlx_*.py` 绝对零改动。`test_multilogin_cli.py` 仅允许新增 429→11 与 shim 符号清单两处。

### 11.3 不测

- 真实发布成功、平台风控、验证码/扫码/短信 2FA、地区跳转、Profile 指纹、代理出口 IP。
- 真实 AdsPower 进程、V2 在旧客户端的真实状态码、429 真实形状、重复 stop、真实 contexts 数量、冷启动耗时（全部归 09）。
- V1、无 key 安装、Firefox、Profile 创建/代理/Cookie 管理。
- `sau_backend.py`、`myUtils/`、Vue。
- 真实桌面应用 / 50325 / 跨机 / Docker。
- 覆盖率数字；不设全局网络护栏；不真睡（`asyncio.sleep` 用 patch）。

### 11.4 默认验收

```bash
python -m unittest discover -s tests
```

必须全绿；默认套件不依赖真实 AdsPower。真实冒烟是 09 的独立 opt-in 入口，不是默认验收前提。

### 11.5 文档验收

人工核对 + 文件清单（ticket 06）：

| 文件 | 必须存在 |
|---|---|
| `GLOSSARY.md` | 分层术语；Profile 泛化；AdsPower Local API / API Key / `user_id`；MLX 专属词标注 |
| `docs/CLI.md` | 三个章节；旧锚点 `#multilogin-x-模式` 可用；参数矩阵；退出码含 `11`；平台表；部署前提；调度责任；身份风险；安全；Bearer/重置；不支持清单 |
| `README.md` | `#### 托管浏览器模式（可选）` + MLX/AdsPower 两个子节；两套示例；退出码含 `11` 与 MLX 429 提示 |
| `docs/skill-distribution.md` | TikTok 模式说明与表格条目 |
| `skills/social-auto-upload/SKILL.md` | 总入口模式说明 |
| `skills/<17 个平台>/SKILL.md` | 统一模板；Bilibili 为“不支持”特例 |
| `CHANGELOG.md` | `[Unreleased]` 的 `### 托管浏览器（AdsPower）` |
| `.scratch/adspower-browser-mode/acceptance.md` | 文件清单逐项核对；写明“真实 AdsPower 冒烟未执行（ticket 09）” |

---

## 12. 实施阶段拆分

### 阶段 1：纯重构（可观察行为不变）

1. 新增 `utils/managed_browser.py`（Protocol / ProviderMode）与 `MultiloginProvider`。
2. `browser_session(managed=...)`；`BrowserSession.managed`；通用 `_managed_session`。
3. 16 个平台模块的 36 个 `browser_session(...)` 调用点改 `managed=`；16 个 `resolve_multilogin_target(...)` 改 `resolve_managed_provider(...)`。
4. 28 处 `session.mode == "multilogin"` 改 `session.managed`（含 insgraph 单引号两处）。
5. `sau_commands/browser.py` 接管激活、flags、provider 构造、label、login/platform 拒绝、`login_required_error`；`sau_commands/multilogin.py` 降为 shim。
6. 全套 `unittest` 绿；MLX 行为不变；静态守卫绿。

**阶段 1 的命名决议（07 的建议，供实现采用）：**

- `sau_commands/browser.py` 是 canonical 实现，提供 `add_browser_flags`、`resolve_managed_provider`、`resolve_account_label`、`require_local_account`、`require_account`、`reject_managed_login`、`reject_managed_platform`、`login_required_error`、`managed_enabled`。
- `sau_commands/multilogin.py` re-export 旧符号；`add_multilogin_flags` 是 `add_browser_flags` 的别名；`resolve_multilogin_target` 保留 MLX-only 旧语义，供 `tests/test_multilogin_cli.py` 与外部调用方使用。
- 16 个平台模块把 `resolve_multilogin_target` 调用改为 `resolve_managed_provider`，把 `reject_multilogin_login/platform` 改为 `reject_managed_*`；import 可继续来自 `sau_commands.multilogin`（shim 同步 re-export 新名字）或迁到 `sau_commands.browser`。
- 这样既满足“17 个模块 import 不必全改”，又不会让 AdsPower 落回本地分支。

### 阶段 2：新增能力

1. 新增 `utils/adspower.py`（V2 client + provider + `StartIncompleteError`）。
2. `utils/errors.py` 加 `RateLimitedError` / `StartIncompleteError`。
3. `sau_commands/browser.py` 加 AdsPower 激活、冲突判定、base 校验、文案。
4. `sau_cli.main()` 加冲突检查与 `RateLimitedError → 11`。
5. **`sau_commands/bilibili.py:121,123` 改 `reject_managed_*`**（否则只设 AdsPower key 时会静默走本地 login/biliup）。
6. 新增 4 个离线测试文件；`test_multilogin_cli.py` 加 429→11 与 shim 符号。
7. 文档/术语（ticket 06）。

### 阶段 3：外部验证（09）

- 提供 opt-in smoke（`SAU_ADSPOWER_SMOKE=1`），默认 skip。
- 只验证生命周期：probe → start → `connect_over_cdp` → 读 URL/title → disconnect → stop。
- 结果写 `research/09-smoke-findings.md`，回填 01/04/08。
- 本机未安装 AdsPower，保持 open，不得用 mock 冒充实测。

---

## 13. 风险、置信度与外部阻塞

### 13.1 已识别的实现风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| `resolve_multilogin_target` 只改签名不改激活 | AdsPower 全部落回本地 | 阶段 1 明确迁移到 `resolve_managed_provider` |
| `require_local_account` 只认 MLX | AdsPower 下错误要求 `--account` → `2` | managed-aware |
| bilibili 只调 `reject_multilogin_*` | AdsPower key + bilibili 静默本地执行 | 阶段 2 改 `reject_managed_*` |
| insgraph 两处单引号 | 漏改 → Instagram 落回本地分支 | 静态守卫同时匹配单双引号 |
| 测试“8 个零改动”与 2 处直接 `browser_session(multilogin=)` 冲突 | 阶段 1 无法既改名又零改动 | 允许 `test_mlx_smoke.py:377`、`test_mlx_hupu_dayu.py:405` 各改 1 行 |
| `login_required_error` 文案写死 Multilogin | AdsPower 下文案错误 | provider-aware 文案 |
| `_log_identity_unverified` 写死 Multilogin | 术语不一致 | 泛化 |
| map 的 32/35 调用点与实际 41/16 不一致 | 实施范围估算错误 | 以 07 清单为准 |

### 13.2 真实 AdsPower 未知项（`[未知]`，归 09）

1. 已运行 Profile 的 start 返回形状：成功 + 既有 ws，还是错误。
2. 重复 stop / 已停止的 `code` / `msg`，是否值得加特例。
3. 429 的真实形状（HTTP 429 还是 200 + code）与 `Retry-After`。
4. `contexts` 是否恒为 1（含 `last_opened_tabs=0`）。
5. 冷启动是否可能超过 30s；超时后不 stop 是否真的留下 Profile。
6. V2 在旧客户端上的真实状态码（404？还是 200 + `code != 0`）。
7. `/status` 是否要求鉴权、是否返回版本字段。
8. V2 最低可用版本；`active` 在 Inactive / 多设备模式下的 `data` 形状。

### 13.3 外部阻塞

本机 `/Applications` 无 AdsPower，50325 未监听；真实 smoke 无法执行。设计与离线实现不受阻；09 保持 open。

---

## 14. 与现有 MLX / 本地模式的兼容性声明

1. 未设置 `ADSPOWER_API_KEY` 时，本地模式与 MLX 的参数解析、默认值、错误码保持不变。
2. 本 effort 唯一改变 MLX 可观察行为的是 429：`1` → `11`；其余 MLX 行为逐字不变。
3. 同时设置 `MLX_API_TOKEN` 与 `ADSPOWER_API_KEY` → `1`，不是 `2`。
4. `verify` / `delete` / `article` 不受托管模式影响，仍走本地。
5. `sau_commands/multilogin.py` 保留同名导出，`tests/test_multilogin_cli.py` 的旧 helper 断言继续通过。
6. uploader 只依赖 `BrowserSession` 与 `utils.errors`；不引入 provider 依赖。
7. 本地 `launch_kwargs` / `context_kwargs` / `init_script` / `context_setup` / cookie 写回语义冻结。

---

## 15. 验收清单

实现完成后逐项确认：

- [ ] `ADSPOWER_API_KEY` 非空激活；空/空白不激活；base 不激活。
- [ ] 双 key 冲突 → `1`，文案精确。
- [ ] `--profile-id` 必填；`--folder-id` 忽略；`--account` 可选。
- [ ] `login` → `1`；bilibili → `1`；`verify`/`delete`/`article` 本地。
- [ ] `check` 未登录 → `10`；成功 → `0` + `valid`。
- [ ] 退出码 `0/1/2/9/10/11/130` 全部有测试锁住。
- [ ] 429 → `11`；stop 阶段 429 不改变主结果。
- [ ] `probe → start → connect → contexts==1 → yield → disconnect → stop` 顺序正确。
- [ ] start 失败不停；`StartIncompleteError` 先 stop 再抛；CDP 失败 finally stop。
- [ ] 取消时 shield stop；stop 失败只 warning。
- [ ] start body 固定 `last_opened_tabs=0`、`proxy_detection=0`、`delete_cache=0`、`cdp_mask=1`。
- [ ] ws URL 原样传给 `connect_over_cdp`，不拼 http。
- [ ] key 不出现在 stdout/stderr/异常/`repr`/日志。
- [ ] 28 处 `session.mode` 清零；静态守卫绿。
- [ ] 本地与 MLX 回归全绿（仅 429 行为变更 + 2 处测试签名迁移）。
- [ ] 文档清单（ticket 06）逐项存在；旧锚点有效。
- [ ] `acceptance.md` 写明真实 AdsPower 冒烟未执行（09）。
