# 06 — Provider 接口与 uploader 改造契约

Status: resolved
Type: grilling
Blocked by: —
Assignee: —

## Question

方案 A（显式 `browser_session`）已定，需要把接口与数据流定死，避免实现时各平台各写一套：

1. **目标对象**：`MultiloginTarget` / `MlxProfile` 放哪个模块？字段是否只有 `folder_id`、`profile_id`、`headless`、`api_token`？token 是否只从环境变量读、绝不进 dataclass 的可序列化字段？
2. **上下文管理器签名**：
   ```python
   async with browser_session(playwright, *, headless, account_file=None,
                              multilogin=None, launch_kwargs=None) as (browser, context):
   ```
   还是返回一个 `BrowserSession` 对象（含 `browser`、`context`、`owned`、`stop()`）？哪个更利于测试与异常处理？
3. **谁负责 start/stop**：`browser_session` 内部调用 MLX，还是 CLI 层先 `async with mlx_profile(...)` 再传 cdp_url？两种职责边界如何选？
4. **本地分支等价性**：`browser_session` 必须完全复刻现有 `launch(**kwargs)` + `new_context(storage_state=..., **kwargs)` 的默认参数；如何保证各平台传入的 kwargs 不丢失？
5. **参数流**：`sau_cli` 解析出的 `folder_id/profile_id` 如何流到 uploader？
   - 加进每个 `sau_commands/*.py` 的 request dataclass？
   - 直接作为 `uploader.__init__` 的 keyword-only 参数？
   - 现有 legacy positional 参数被测试固定，新增必须 keyword-only。
6. **登录检测契约**：`async def is_logged_in(context) -> bool` 放哪、抛出什么、由谁调用？MLX 模式下 upload 前是否总是先检测？
7. **退出码 10 的落点**：定义 `LoginRequiredError`（或 `MlxLoginRequired`）在哪个模块；`sau_cli.main` 如何只把这一类映射到 10，且不吞掉 `argparse` 的 2？
8. **login 命令**：MLX 模式下 `sau <platform> login` 的行为文案与退出码（建议退出 1，提示去 MLX 登录）；是否需要在 parser 层直接拒绝？
9. **account 缺省**：`--account` 在 MLX 模式可省略；argparse 不能条件必填，在哪一层校验（`run()`）？缺省标签用 `profile_id` 还是 `platform:profile_id`？
10. **向后兼容**：不传 `MLX_API_TOKEN` 时，新增参数必须完全无感；如何用测试锁住？

## Context

- 现有上传类在 `uploader/*/main.py`，入口方法签名各异（`upload(playwright)`、`douyin_upload_video()` 等）。
- CLI 请求对象在 `sau_commands/*.py` 的 dataclass。
- 测试风格 `unittest`，大量 `AsyncMock`；参考 `tests/test_douyin_declaration.py`、`tests/test_sau_browser_cli.py`。
- 结合 02 的“允许/禁止 API 清单”与 03 的登录检测清单。

## Answer

决策（2026-11-05）。术语沿用 `GLOSSARY.md`：Browser session / Profile / Owned session / Login required / Account label。

### 1. 模块与目标对象

新增三个模块，均不修改 `sau_backend.py`、`myUtils/`、前端：

| 模块 | 内容 | 说明 |
|---|---|---|
| `utils/multilogin.py` | `MultiloginTarget`、`MultiloginClient`、`MultiloginError` | Launcher HTTP 细节（Start/Stop/status）只在这里；token 只从环境变量读 |
| `utils/browser_session.py` | `BrowserSession`、`browser_session()` | 唯一“取得浏览器并交还”的实现；本地与 MLX 两个分支 |
| `utils/errors.py` | `LoginRequiredError`、`UsageError` | 无依赖的叶子模块，uploader 与 CLI 共用 |
| `sau_commands/multilogin.py` | `add_multilogin_flags()`、`resolve_multilogin_target()`、`resolve_account_label()`、`reject_multilogin_login()` | 纯 CLI 层：参数、激活判定、账号标签 |

`MultiloginTarget` 只承载 Profile 身份：

```python
@dataclass(frozen=True, slots=True)
class MultiloginTarget:
    folder_id: str
    profile_id: str
```

- **`api_token` 不是字段。** token 由 `MultiloginClient` 在调用时从 `MLX_API_TOKEN` 读取，不进入 dataclass、不进请求对象、不进日志、不可序列化；测试通过 `patch.dict(os.environ, ...)` 注入。
- **`headless` 不是 Target 字段。** 它是运行时开关，作为 `browser_session(headless=...)` 参数传入，避免“同一个 Profile 两种 headless 身份”的歧义。
- 模式判定：`os.environ.get("MLX_API_TOKEN", "").strip() != ""` → MLX 模式；空串/纯空白按本地模式处理（与 charter“环境变量存在”一致，但排除误设空值）。

### 2. 上下文管理器返回对象，不返回元组

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
) -> AsyncIterator[BrowserSession]:
```

- 选择对象而非 `(browser, context)` 元组：调用点需要 `mode`（微博等平台要分支），元组解包会把模式丢掉。
- **不提供 `owned` 字段，也不暴露 `stop()`。** 所有权在 ticket 05 已定为“谁启动谁停止”，且 teardown 无条件执行；再加一个布尔量只会成为死状态。生命周期只由 `async with` 保证，防止调用方重复 Stop 或提前 Stop。
- `mode` 用于两类显式分支：上传器里的平台特例（ticket 04 的微博视口等）和测试断言。除 ticket 04 列出的例外，上传器业务代码不得读取 `mode`。

### 3. Start / Stop 由 `browser_session` 负责

CLI 层永远不直接调用 Launcher：

```python
async with async_playwright() as playwright:
    async with browser_session(playwright, headless=..., account_file=..., multilogin=target) as session:
        ...
```

- `browser_session` 内部：MLX 分支 `client.start()` → `connect_over_cdp()` → yield → 断开 → `client.stop()`；本地分支 `launch()` → `new_context()` → yield → 保存 cookie → close。
- 只有一个 owner，`finally` 语义只在 `browser_session` 实现一次，完全复用 ticket 05 的连接重试、`started` 标记、`asyncio.shield` Stop、Stop 失败仅 warning。
- `MultiloginClient` 不向上暴露端口以外的状态；CLI 不感知 HTTP。

### 4. 本地分支等价性

把现有上传器的启动参数**拆成三个显式入参**，由调用点原样搬运，不做任何“默认值推断”：

- `launch_kwargs`：`channel`、`executable_path`、`args`、`proxy`、`timezone_id` 等 **不含 `headless`**；`headless` 由 `browser_session` 统一注入。若调用方误传 `headless` → `ValueError`（开发期早失败）。
- `context_kwargs`：`new_context()` 的其余参数（`permissions`、`viewport`、`timezone_id`、`no_viewport` 等）；**不含 `storage_state`**，由 `account_file` 决定。
- `init_script: bool`：原 `set_init_script(context)` 的开关。默认 `False`，逐平台显式传 `True`（抖音/快手/小红书/视频号/虎扑/YouTube 等）。

本地分支算法固定为：

```python
browser = await playwright.chromium.launch(headless=headless, **launch_kwargs)
context = await browser.new_context(
    storage_state=str(account_file) if account_file else None,
    **context_kwargs,
)
if init_script:
    context = await set_init_script(context)
```

退出时（**仅正常完成**）：`context.storage_state(path=account_file)` → `context.close()` → `browser.close()`；异常路径不写 cookie，直接 close。

- `alipay` / `baijiahao` 的 `context.grant_permissions(["geolocation"])` 统一改写为 `context_kwargs={"permissions": ["geolocation"]}`（Playwright 等价能力，避免再引入 setup 回调）。
- MLX 分支**静默忽略** `launch_kwargs` / `context_kwargs` / `init_script` / `account_file`（ticket 04）。
- 等价性由“参数搬运表 + 每平台契约测试”共同锁住：spec（ticket 09）逐平台列出迁移前后的 kwargs 原文，实现时只允许原样复制，不允许重写默认值。
- 已知且接受的差异：本地模式下 cookie 写回从“上传方法内联”变成“session 正常退出时统一写回”。成功路径完全等价；上传抛异常时不再刷新 cookie（旧代码同样在内联语句之前的异常路径不写，只有“确认发布后、后续语句失败”这一窄窗口不同）。

### 5. 参数流

- `sau_commands/multilogin.py::add_multilogin_flags(parser)` 给所有**可在 MLX 运行的 action**（`check`、`upload-*`）追加 `--folder-id`、`--profile-id`；`login` action 不追加（MLX 下直接拒绝，见第 8 条）。
- `--account` 改为 `required=False`（default `None`）。条件必填在 `run()` 层校验：
  - 本地模式缺 `--account` → 抛 `UsageError` → 退出 **2**（保持 argparse 的参数错误语义）；
  - MLX 模式缺 `--folder-id` / `--profile-id` → 抛 `UsageError` → 退出 **2**。
- `run()` 只解析一次：`target = resolve_multilogin_target(args)`、`label = resolve_account_label(args)`。**`MultiloginTarget` 不进入任何 `*Request` dataclass**：请求对象描述业务数据，target 是运行时资源，混在一起会让测试和序列化变脏。
- **uploader 构造函数不变**（legacy positional 继续被测试锁定）；`str | None` 只放宽 `account_file` 的类型注解。MLX 模式传 `None`，本地模式传 `str(resolve_account_file(...))`。
- session 通过**上传入口方法的 keyword-only 参数**下传，不经构造函数：

```python
# sau_commands/douyin.py::run
async with async_playwright() as playwright:
    async with browser_session(playwright, headless=args.headless, account_file=account_file,
                               multilogin=target, launch_kwargs={...}, context_kwargs={...},
                               init_script=True) as session:
        await app.douyin_upload_video(session=session)
```

```python
# uploader/douyin_uploader/main.py
async def douyin_upload_video(self, *, session: BrowserSession | None = None):
    if session is not None:
        await self.upload(None, session=session)   # 不打开第二个 async_playwright
        return
    async with async_playwright() as playwright:   # legacy：Flask / 本地登录路径，原样保留
        await self.upload(playwright)

async def upload(self, playwright: Playwright | None, *, session: BrowserSession | None = None):
    ...
```

- 供 CLI 使用的业务主体必须从 `upload()` 中拆出为 `upload_in(session)`（或等价方法），只包含“页面操作 + 发布”；**cookie 校验、文件存在性、cookie 读写、close 全部留在本地分支**。这样 MLX 传 `account_file=None` 时不会触发 `os.path.exists(None)` 一类失败，也不会误读 cookie。
- 各平台 wrapper（`douyin_upload_video` / `ks_upload_video` / `baijiahao_upload_video` …）统一接受 `*, session=None` 并透传；Flask 不传 session，行为不变。

### 6. 登录检测契约

- 位置：每个 `uploader/<platform>_uploader/` 内，紧挨现有 `cookie_auth`（zhihu/xueqiu/dayu 放 `session.py`）。
- 签名：`async def is_logged_in(context: BrowserContext) -> bool`。
  - 明确的登录页/登录表单/未登录锚点 → `False`；
  - 网络错误、超时、5xx、无法判定的结构异常 → **抛异常**（退出 1），绝不 `except: return False`；
  - 只允许 `context.new_page()` / `goto()` / `close()`，禁止 `new_context` / `storage_state` / `add_init_script`（ticket 02 允许清单）。
- 调用点（CLI 层，仅 MLX 模式）：
  - `check`：`is_logged_in` → `False` 抛 `LoginRequiredError`（10）；`True` 返回 0。
  - `upload-*`：进入上传器**之前**先检测一次，`False` → `LoginRequiredError`（10）。
  - 本地模式完全沿用现有 `*_setup` / `check_*_account`，不调用 `is_logged_in`。
- 上传中途遇到验证码/二次验证/被踢回登录页：由上传器抛 `LoginRequiredError`（ticket 04），不要在平台代码里返回 bool 或 `sys.exit`。

### 7. 退出码 10 的落点

`LoginRequiredError(Exception)` 与 `UsageError(Exception)` 都定义在 `utils/errors.py`。`sau_cli.main` 按固定顺序映射：

```python
def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    try:
        return asyncio.run(dispatch(args))
    except LoginRequiredError as exc:      # 10
        print(str(exc), file=sys.stderr)
        return 10
    except UsageError as exc:              # 2
        parser.print_usage(sys.stderr)
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:               # 1
        print(str(exc), file=sys.stderr)
        return 1
```

- `argparse` 自身的错误发生在 `try` 之前，仍由 argparse 退出 2（`SystemExit` 不被 `except Exception` 捕获）。
- `KeyboardInterrupt` / `SystemExit` 不映射（保留 130 / 2），但 `browser_session` 的 `finally` 必须先发 Stop（ticket 05）。
- 不允许用“返回码字符串”或 `sys.exit` 在深处表达 10；唯一来源是 `LoginRequiredError`。

### 8. MLX 模式下的 login 命令

- **保留注册**，不在 parser 层隐藏。理由：`sau <platform> login` 在两种模式下都存在，隐藏会让 MLX 用户得到 argparse 的 2，而契约要求“明确拒绝 = 1”。
- 在 `run()` 开头调用共享 helper：

```python
reject_multilogin_login("douyin", args)  # MLX 激活时抛 RuntimeError → 退出 1
```

文案固定：`Multilogin 模式不支持 CLI 登录；请在 Multilogin 应用中登录 Profile {profile_id} 后重试。`
- `login` 不需要 `--folder-id/--profile-id` 也能给出这句话（profile 缺失时用“指定 Profile”占位），确保退出码恒为 1。

### 9. Account label 缺省

- MLX 模式：`args.account or args.profile_id`，即缺省**就是 `profile_id`**（charter 第 14 行），不拼 `platform:` 前缀。
- 本地模式：`--account` 必填，缺省即 `UsageError`（2）。
- 该 label 只用于日志与输出，不参与身份校验（身份一致性由 ticket 12 决定）；MLX 模式下不得用它生成 cookie 路径。

### 10. 向后兼容的锁定测试

均为 `unittest`，不依赖真实 MLX：

1. **本地等价**：mock `playwright.chromium.launch` / `browser.new_context`，断言 `headless` 注入与 `launch_kwargs` / `context_kwargs` 原样传递；`init_script=True` 时调用 `set_init_script`；正常退出写 `storage_state`，异常退出不写；`close()` 顺序为 context → browser。
2. **MLX 禁用面**：`multilogin=MultiloginTarget(...)` 时，断言从未调用 `launch` / `new_context` / `storage_state` / `add_init_script`，且 `connect_over_cdp` 使用 `http://127.0.0.1:{port}`。
3. **模式判定**：env 缺失/空/空白 → local；非空 → MLX；MLX 下 `--folder-id` / `--profile-id` 缺失 → 2；本地缺 `--account` → 2。
4. **退出码矩阵**：`LoginRequiredError` → 10；`UsageError` → 2；普通异常 → 1；argparse 缺参 → 2；成功 → 0。
5. **legacy 签名**：现有 `tests/test_douyin_declaration.py` 一类的 positional 断言全部保留；新增字段/参数只用 keyword-only。
6. **parser 全平台回归**：表驱动，对每个平台用旧参数集调用 `build_parser().parse_args(...)`，断言解析结果不变（`--account` 由必填改可选不改变已有调用的结果）。
7. **token 卫生**：构造 target / 触发错误时，断言 `str(exc)`、`repr(target)`、日志捕获中都不含 token。
8. **Flask 路径不变**：直接实例化 uploader 且不传 `session` 时，仍走原有 `async_playwright()` + `launch()` 路径（mock 断言 `async_playwright` 被调用）。

### 补充（2026-11-05，汇总 ticket 09 时发现）

- 虎扑的本地 context 不是简单的 `set_init_script`：`uploader/hupu_uploader/main.py::_create_stealth_context` 会设置自定义 UA（`_CHROME_UA`）、`viewport=1920×1080` 并注入 `_STEALTH_SCRIPT`。为保持本地等价，`browser_session` 增加一个**仅本地分支执行**的可选 hook：

  ```python
  context_setup: Callable[[BrowserContext], Awaitable[BrowserContext | None]] | None = None
  ```

  规则：`mode == "local"` 时在 `new_context` 之后、`init_script` 之后调用；`mode == "multilogin"` 时**静默忽略**（与 ticket 04 一致）。平台把该逻辑暴露为公开 helper（如 `hupu_uploader.main.prepare_local_context`），由 `sau_commands/hupu.py` 传入；不允许在 MLX 分支调用。
- 抖音/小红书：`permissions=["geolocation"]` 已能通过 `context_kwargs` 表达，不需要 hook。
- 支付宝/百家号：`grant_permissions(["geolocation"])` 仍按上文改写为 `context_kwargs={"permissions": ["geolocation"]}`，不新增 hook。
- 测试：`context_setup` 只允许在本地分支被调用一次；MLX 分支断言未被调用。

### 对下游 ticket 的约束

- **ticket 07**：替身层次按本文件的三个 seam 划分——`MultiloginClient`（HTTP）、`browser_session`（生命周期）、`is_logged_in`（页面）。契约测试优先 mock 前两层，不启动真实 Chromium。
- **ticket 09**：必须包含（a）模块图与依赖方向；（b）每平台 `launch_kwargs` / `context_kwargs` / `init_script` 迁移表；（c）每个上传器“业务主体拆分 vs legacy 分支”的改动清单；（d）退出码矩阵与 `LoginRequiredError` 出现点；（e）`--account` 条件必填规则。
- **ticket 12**：身份校验只能发生在 `is_logged_in` 之后、上传之前；本契约不预留 `--account` 作为身份输入的语义。
- **ticket 13**：TikTok 的 wrapper 同样接受 `*, session=None`，本地模式不提供路径（`sau tiktok ...` 直接退出 1），因此其 legacy 分支可以只保留给 `uploader` 内部复用，不暴露 CLI 本地模式。
