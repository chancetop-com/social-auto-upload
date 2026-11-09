# 03 — Provider 抽象与 uploader 接缝

Status: resolved
Type: grilling
Blocked by: 01, 02, 10
Assignee: LukeChen

## Question

设计一个能在不改变本地模式与 MLX 可观察行为的前提下，同时承载 Multilogin 与 AdsPower 的 managed browser provider 接缝。需要确认：

1. 抽象边界：`ManagedBrowserTarget`、`ManagedBrowserClient`、`BrowserProvider` 各自职责；哪些是协议/ABC，哪些是 dataclass。
2. 生命周期归一化：MLX 返回 `port`，AdsPower 返回 `ws.puppeteer`；由 client 统一返回“可连接端点”，还是由 target 携带 endpoint 类型。
3. `browser_session` 签名：保留 `multilogin: MultiloginTarget | None` 并新增 `adspower: AdsPowerTarget | None`，还是改为单个 `managed: ManagedBrowserTarget | None` / `provider: BrowserProvider | None`。
4. provider 选择与环境解析放在哪里：`sau_commands/multilogin.py` 扩展、新建 `sau_commands/browser.py`，还是 `utils/browser_session.py`。
5. uploader keyword：现有 `multilogin=target` 是否改名为中性的 `browser=` / `managed=`；改名会触及多少平台、多少测试；是否保留兼容别名。
6. `BrowserSession.mode` 的取值：`"local" | "multilogin" | "adspower"`，还是 provider 名。
7. 共用逻辑：probe、start、connect 重试、`contexts[0]` 校验、disconnect、stop、cancellation shield、日志脱敏，哪些进基类/模板方法，哪些留给 provider。
8. 错误类型：是否新增 `ProviderUnavailableError` / `ProfileBusyError`，还是继续用 `RuntimeError` + 文案；`LoginRequiredError` / `UsageError` 不变。
9. 本地分支：`_local_session` 是否完全不动；`launch_kwargs` / `context_kwargs` / `init_script` / `context_setup` 的语义不变。
10. 注入点：provider/client 如何注入 fake；现有 `tests/fakes.py` 如何扩展；是否保留 `http_get` 注入。
11. 迁移顺序：先抽象 MLX 再接入 AdsPower，还是一次性改完；如何保证中途测试可跑。
12. 依赖方向：`sau_cli → sau_commands → utils`；uploader 不 import `sau_commands`。

## Context

- 现有接缝：`utils/browser_session.py`（`browser_session` / `_local_session` / `_multilogin_session`）。
- 现有 client：`utils/multilogin.py`（`MultiloginTarget` / `MultiloginClient`）。
- 现有 CLI helper：`sau_commands/multilogin.py`。
- 参考上一个 effort 的 provider 决策：`.scratch/multilogin-browser-mode/issues/06-provider-contract.md`。
- 目标：第二个 provider 不需要复制 `_multilogin_session` 的生命周期代码。
- Research 01 §12.2：AdsPower 返回 `ws.puppeteer`，MLX 返回 `port`；建议 client 暴露统一 `connect_url`，`browser_session` 只做 `connect_over_cdp(connect_url, timeout=10_000, no_defaults=True)`。
- AdsPower 的 `code` / `msg` 解析、`data.ws.puppeteer` 提取、`profile_id` 选择器封装在 `AdspowerClient`，不泄漏到 `browser_session`。

## Answer

决议日期：2026-11-09（HITL grilling，逐题确认）。一句话结论：**在 `utils/managed_browser.py` 定义 `ManagedBrowserProvider` Protocol，把 target 身份与 client HTTP 组合成一个 provider；`browser_session(managed=provider)` 保留唯一的生命周期模板，provider 只实现 `probe/start/stop/status` 并负责端点归一化。**

### 1. Provider 抽象（Q1）

```python
# utils/managed_browser.py
ProviderMode = Literal["multilogin", "adspower"]

class ManagedBrowserProvider(Protocol):
    @property
    def mode(self) -> ProviderMode: ...
    @property
    def profile_id(self) -> str: ...
    def probe(self) -> None: ...
    def start(self, headless: bool) -> str: ...   # 返回可连接端点
    def stop(self) -> None: ...
    def status(self) -> str: ...
```

- `start` 返回**可直接交给 `connect_over_cdp` 的字符串**，这是端点归一化的唯一出口：
  - `MultiloginProvider.start` 调 `client.start(folder_id, profile_id, headless)` 得到 port，返回 `f"http://127.0.0.1:{port}"`。
  - `AdspowerProvider.start` 调 `client.start(profile_id, headless)`，原样返回 `data.ws.puppeteer`（`ws://...`）。**不反推 http**：`cdp_mask=1` 下路径被遮蔽，多开时 http 入口可能落到另一个实例。
- `stop()` / `status()` 无参：provider 自己持有 `profile_id`，session 不传递身份。
- `MultiloginTarget` / `MultiloginClient` / `AdspowerTarget` / `AdspowerClient` 保持既有契约（ticket 10）：MLX `start -> port`，AdsPower `start -> ws_url`。Provider 是纯组合，不复制 HTTP 细节。
- 用结构化 Protocol，不用 ABC、不加 `@runtime_checkable`：两个实现靠结构契合，`browser_session` 永不做 `isinstance`，测试用 duck-typed fake。

### 2. 模块与依赖（Q3 / Q8）

| 模块 | 变化 | 内容 |
|---|---|---|
| `utils/managed_browser.py` | 新增（叶子） | `ManagedBrowserProvider` Protocol、`ProviderMode`；只依赖 `typing` |
| `utils/multilogin.py` | 追加 | `MultiloginProvider(target, client)`；现有 Target/Client 不动 |
| `utils/adspower.py` | 新增 | `AdspowerTarget(profile_id)`、`AdspowerClient(key, base, http_get=None)`、`AdspowerProvider(target, client)` |
| `utils/browser_session.py` | 重构 managed 分支 | 通用 `_managed_session` 模板；`_local_session` 冻结；`BrowserSession.managed` |
| `sau_commands/browser.py` | 新增 | 激活判定、flags、provider 构造、account label、login/platform 拒绝、`login_required_error` |
| `sau_commands/multilogin.py` | 降为 shim | 从 `sau_commands.browser` re-export 同名符号 |

- 依赖方向仍是 `sau_cli → sau_commands → utils`；`utils/managed_browser.py` 不 import 任何 provider/client/HTTP。
- uploader 只继续 import `utils.browser_session.BrowserSession` 与 `utils.errors`，不 import Protocol。
- `sau_commands/multilogin.py` 保留 `__all__` 同名导出，17 个平台的 import 与 `tests/test_multilogin_cli.py` 不需要改；是否迁移 import 到 `sau_commands.browser` 由 07 决定。

### 3. `browser_session` 契约（Q3 / Q5）

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

`_managed_session` 模板顺序固定：

1. `await asyncio.to_thread(provider.probe)`
2. `connect_url = await asyncio.to_thread(provider.start, headless)`
3. 日志只打 `provider.mode`、`profile_id` 与 endpoint 的 `host:port`（不打 token，不打完整 ws 路径）
4. `_connect_over_cdp(playwright, provider, connect_url)`：3 次尝试，backoff 2s / 4s；最终失败时调 `provider.status()` 补诊断，然后抛 `RuntimeError`
5. `len(browser.contexts) != 1` → `RuntimeError`，文案 provider 中立（带 `mode` 与 `profile_id`）
6. `yield BrowserSession(browser=browser, context=browser.contexts[0], mode=provider.mode)`
7. `finally`：`_disconnect(browser)`（失败仅 warning）→ `asyncio.shield(asyncio.to_thread(provider.stop))`（失败仅 warning）

- probe/start 失败绝不停 Profile（沿用“谁启动谁停止”）。
- `browser_session` 不再读环境变量；“未设置 token”的防御检查搬进 `resolve_managed_provider()`，用户可观察行为不变（仍退出 1）。
- `_local_session`、`launch_kwargs`、`context_kwargs`、`init_script`、`context_setup` 语义逐字冻结；唯一改动是分发条件从 `multilogin is None` 改为 `managed is None`。

### 4. CLI 组合根（Q3）

- `resolve_managed_provider(args) -> ManagedBrowserProvider | None`：
  - `ADSPOWER_API_KEY`（strip 后非空）→ `AdspowerProvider(AdspowerTarget(profile_id), AdspowerClient(key, base))`
  - 否则 `MLX_API_TOKEN`（strip 后非空）→ `MultiloginProvider(MultiloginTarget(folder_id, profile_id), MultiloginClient(token))`
  - 两者都非空 → `RuntimeError`（退出 1，ticket 02）
  - 都为空 → `None`（本地模式）
  - AdsPower 下 `--profile-id` 必填、`--folder-id` 忽略；MLX 下两者都必填（ticket 02）
- `sau_commands/browser.py` 提供、并按激活的 provider 选择文案：`add_browser_flags`（`add_multilogin_flags` 继续作为导出别名）、`resolve_account_label`、`require_local_account`、`reject_managed_login`、`reject_managed_platform`、`login_required_error`。
- 文案沿用 ticket 02 已定值，例如 `AdsPower 模式不支持 CLI 登录；请在 AdsPower 中登录 Profile {profile} 后重试。`
- key/token 只在 client 内持有；`__repr__` 保持 `token=<redacted>`。

### 5. mode 与上传器改造（Q2）

- `mode` 取值 `"local" | "multilogin" | "adspower"`；MLX 的旧值不变。
- 新增 `BrowserSession.managed`；约 30 处 `session.mode == "multilogin"` 改看 `session.managed`（douyin / kuaishou / xiaohongshu / weibo / tencent / alipay / baijiahao / hupu / zhihu / xueqiu / dayu / youtube / tiktok / meta 系列）。
- 上传器内部页面 helper 的 `multilogin: bool` 参数本轮不改名，只把“传值来源”从 `session.mode == "multilogin"` 换成 `session.managed`；改名登记为 07 的可选清理。
- 因此 AdsPower 自动继承 MLX 的全部托管行为（登录检测、权限与 workaround 分支），与 charter“平台覆盖与 MLX 对齐”一致。

### 6. 错误面（Q6）

- provider/client 继续抛 `RuntimeError` + 分类文案（HTTP / 业务 `code` / 协议漂移）。
- `utils/errors.py` 只新增 `RateLimitedError`（HTTP 429 → 退出 11，ticket 02/10）；其余仍 → 1。
- 不新增 `ProviderUnavailableError` / `ProfileBusyError`：它们没有独立退出码，只会增加类层次与需要维护的断言面。
- `LoginRequiredError` / `UsageError` / `PublishResultUnknownError` 不变。

### 7. 测试接缝（Q7）

- `tests/fakes.py` 新增 `FakeManagedProvider`：可配 `mode`、`profile_id`、`connect_url`、各阶段异常与 `events` 列表；session 测试直接传 `managed=fake`，断言 `probe → start → connect → stop` 顺序。
- 保留 `FakeMultiloginClient`；AdsPower client 用 `http_get` 注入合成响应（可选新增 `FakeAdspowerClient`，但不是必需）。
- client 层的 `http_get` 注入对两个 client 都保留。
- 现有 `tests/test_mlx_*` 只把 `multilogin=target` 换成 `managed=MultiloginProvider(target, FakeMultiloginClient(...))`，业务断言不变；不再 patch `utils.browser_session.MultiloginClient`。

### 8. 迁移顺序（Q4）

阶段 1（纯重构，可观察行为不变）：

1. 新增 `utils/managed_browser.py` 与 `MultiloginProvider`；
2. 改为 `browser_session(managed=...)`，新增 `BrowserSession.managed`；
3. 35 个调用点 + 59 处测试断言改 `managed=`；
4. 全套 `unittest` 绿，MLX 行为不变。

阶段 2（新增能力）：

1. 新增 `utils/adspower.py`（V2 client + provider）；
2. 新增 `sau_commands/browser.py` 的激活与组合；
3. 补 AdsPower 离线契约测试与退出码矩阵；
4. `sau_commands/multilogin.py` 降为 re-export shim。

不做 `multilogin=` 弃用别名：阶段 1 一次性原子改名，避免多一条需要测试、以后还要删的兼容路径。

### 对下游 ticket 的约束

- **04（生命周期）**：模板顺序与所有权以本文 §3 为准；`status` 只用于诊断；不做 start 前预检（ticket 02 已裁决）。
- **05（测试策略）**：以 provider 为第一层替身、client 为第二层；不启动真实浏览器；`FakeManagedProvider` 是核心 fake。
- **07（平台清单）**：迁移表要覆盖 35 个 `browser_session` 调用点与约 30 个 `session.mode` 判定；内部 `multilogin: bool` 标为可选清理。
- **08（汇总规格）**：本文的模块图、Protocol、`browser_session` 签名与迁移顺序直接进入规格；`RateLimitedError` 与退出码 11 引用 ticket 02/10。

### 补充（2026-11-09，来自 ticket 04）

- §6“错误面只加 `RateLimitedError`”被受控扩展：`utils/errors.py` 另加 `StartIncompleteError(RuntimeError)`，只由 `AdspowerClient.start` 在 **HTTP 2xx + `code == 0` + `data.ws.puppeteer` 缺失/空，或 2xx 但非法 JSON / 缺 `code`** 时抛出。
- 它只是内部生命周期信号：`_managed_session` 捕获后 best-effort stop（失败仅 warning）再原样抛出；`sau_cli` 不单独映射，退出码仍 `1`。
- Protocol 不变（仍 `start(headless) -> str`）；MLX 缺失 `data.port` 的行为不变（普通 `RuntimeError`、不 stop）。
