# 07 — 没有真实 MLX 时的测试策略

Status: resolved
Type: grilling
Blocked by: 02, 06
Assignee: —

## Question

CI 和开发机上都没有 Multilogin 账号，测试必须能在“没有 MLX”的情况下覆盖关键契约。需要决定分层与替身：

1. **单元层**：如何 fake Launcher HTTP？
   - `unittest.mock.patch` 掉 `requests.get`？
   - 起一个本地 `http.server` 冒充 launcher，返回固定 JSON？
2. **Provider 层**：如何 fake `connect_over_cdp` 与 `browser.contexts[0]`？
   - 用 `AsyncMock` 造 browser/context？
   - 还是用真实 Chromium + `--remote-debugging-port` 模拟 CDP 端点？
3. **契约测试**：
   - `MLX_API_TOKEN` 存在/缺失时的模式判定；
   - 缺 `--folder-id` / `--profile-id` 的报错；
   - `--account` 可省略；
   - 登录失效 → 退出码 10；其他失败 → 1；argparse 错误 → 2；
   - 本地模式参数与行为完全不变。
4. **回归测试**：如何证明“没有 token 时走的还是原来的 launch/new_context/storage_state 路径”？
   - 是否需要把现有 upload 流程抽出可注入的 fake playwright？
5. **集成层**：是否值得做一个可选的、需要真实 MLX 的 `@skipUnless` 测试？如何标记与运行？
6. **测试数据**：假 Launcher 响应样本放哪里？是否记录真实响应（等有账号后）？
7. **不测什么**：各平台真实发布（平台风控、验证码）不在自动化测试范围，如何明确边界？

## Context

- 测试框架是 `unittest`；现有测试大量 mock。
- 参考：`tests/test_sau_browser_cli.py` 已覆盖 parser 与命令分发；`tests/test_douyin_declaration.py` 覆盖构造函数兼容性。
- 02 会给出允许/禁止的 Playwright API 清单，测试应锁住“MLX 模式绝不调用 new_context / storage_state”。

## Answer

决策（2026-11-05）。测试框架保持 `unittest`，默认命令 `python -m unittest discover -s tests`；**不引入 pytest，不新增依赖，默认套件不启动真实浏览器、不访问网络**。

### 1. Launcher HTTP：在 Client seam 上打桩，不起 `http.server`

`utils/multilogin.py::MultiloginClient` 的 HTTP 调用可注入：

```python
class MultiloginClient:
    def __init__(self, *, token: str, http_get: Callable[..., HttpResponse] | None = None):
        self._token = token                      # 只存在实例内，不进 repr、不进日志
        self._http_get = http_get or requests.get
```

- 单元测试传入一个 `FakeHttpGet`（记录 `(url, headers, timeout, verify)`，按 URL 返回预置的 `FakeResponse(status_code, payload)`），**不 patch `requests.get` 全局**、不起本地 `http.server`。
- 理由：`launcher.mlx.yt:45001` 是 HTTPS + 自签证书（ticket 01），本地 HTTP server 无法复刻 TLS/证书路径；起 server 还会引入端口占用与 CI 不稳定。注入点同时让我们精确断言 URL、`Authorization` 头、`verify=False`、超时值。
- 只测“我们发出的请求”和“我们对响应的解析”，不测 `requests` 本身。
- 例外：可选的真实 HTTP 冒烟归入第 5 条（需真实 MLX），不在默认套件。

### 2. Provider 层：结构化 async fake，不用真实 CDP 端点

在 `tests/fakes.py` 提供一组手写 fake，而不是裸 `AsyncMock`：

```python
class FakeContext:      # new_page / pages / storage_state / close 记录调用
class FakeBrowser:      # contexts: list[FakeContext] / close()
class FakeBrowserType:  # launch() / connect_over_cdp()
class FakePlaywright:   # chromium: FakeBrowserType
```

- 手写 fake 的原因：需要可控的 `browser.contexts` 长度、可断言的 `close()` 顺序、以及“禁止调用”的负向断言（`new_context` 在 fake 上直接 `raise AssertionError`）。裸 `AsyncMock` 对任意属性都返回新 mock，会把拼写错误和非法调用一起吞掉。
- 叶子方法（`context.new_page`、`page.goto`）仍可用 `AsyncMock`/`MagicMock` 组合，保持与现有测试风格一致。
- **不在默认套件启动真实 Chromium**（`--remote-debugging-port` 方式）。理由：CI 无浏览器、启动慢、端口/时序不稳定；而本 ticket 要锁的是生命周期与调用面，不是 Playwright 驱动本身。真实 CDP 兼容性由第 5 条的 opt-in 冒烟覆盖（ticket 02 的结论也来自真实环境）。
- 所有等待可缩短：`browser_session` 的重试退避通过 patch `asyncio.sleep` 校验（断言 `[2, 4]`），测试不真睡。

### 3. 契约测试矩阵

新增测试文件（与现有 `test_sau_*.py` 命名风格一致）：

| 文件 | 覆盖 |
|---|---|
| `tests/test_multilogin_client.py` | Start URL/查询参数、Bearer 头、`verify=False`、超时；200 取 `data.port`；401/403/404/429/5xx 异常消息；Stop 200；Stop 500 `profile already stopped` 视为成功；其他 500 抛错；token 不出现在 `str(exc)` / `repr` |
| `tests/test_browser_session.py` | 本地分支参数等价（第 4 条）；MLX 生命周期 start→connect→yield→close→stop；connect 10s×3、退避 2→4；3 次失败查一次 status 并退出 1；`contexts` 为空或多于 1 个 → fail-fast 且仍 Stop；yield 抛异常仍 Stop；取消路径 Stop 被 shield；Stop 失败只 warning 不覆盖退出码；Start 失败不 Stop；本地 storage_state 仅在正常退出时写 |
| `tests/test_mlx_cli_contract.py` | 模式判定（缺失/空/空白/非空）；缺 `--folder-id`/`--profile-id` → 2；本地缺 `--account` → 2；MLX 缺 `--account` 可运行且标签 = `profile_id`；`LoginRequiredError` → 10；普通异常 → 1；argparse 缺参 → 2；成功 → 0；MLX 下 `login` 运行时拒绝 → 1；`--folder-id/--profile-id` 在本地模式被忽略且不报错 |
| `tests/test_mlx_platform_contract.py` | 逐平台（表驱动）：MLX upload 路径绝不调用 `launch` / `new_context` / `storage_state` / `add_init_script` / `grant_permissions` / `route` / `set_geolocation` / `set_viewport_size`；`context.new_page()` 是唯一建页方式；`account_file=None` 时不触碰 cookie 路径；`is_logged_in` 的 True/False/抛异常三分支；上传中途 `LoginRequiredError` 原样冒泡 |
| `tests/test_multilogin_smoke.py` | 第 5 条 opt-in 真实冒烟 |

现有 `tests/test_sau_browser_cli.py`、`test_douyin_declaration.py` 保留为回归基线，不重写。

### 4. “没有 token 时还是原路径”的证明

分两层，缺一不可：

1. **CLI 层**：`test_mlx_cli_contract` 用 `patch.dict(os.environ, {}, clear=False)` 删除 `MLX_API_TOKEN`，以 fake `Playwright` 跑 `sau_cli.dispatch(["douyin", "upload-video", ...])`，断言 `browser_session` 走 `local`、`launch(headless=..., **launch_kwargs)` 与 `new_context(storage_state=..., **context_kwargs)` 的参数与**迁移基线 golden dict** 完全相等，且正常退出写回 cookie。
2. **Uploader 层**：不传 `session` 直接调用 `DouYinVideo.upload(playwright)`（即 Flask 路径），断言 `async_playwright` 仍由上传器自己打开、`set_init_script` 仍被调用、cookie 仍写回。该用例防止“为 CLI 重构时顺手改坏 Flask”。

**Golden dict 防漂移**：每个平台的 `launch_kwargs` / `context_kwargs` / `init_script` 在测试中写死为期望值（来源于 ticket 09 的参数迁移表）。实现阶段若改了上传器里的字面量而没同步，测试失败。

### 5. 真实 MLX 集成层（opt-in，默认跳过）

`tests/test_multilogin_smoke.py`：

```python
RUN = os.environ.get("SAU_MLX_SMOKE") == "1"
FOLDER = os.environ.get("SAU_MLX_FOLDER_ID")
PROFILE = os.environ.get("SAU_MLX_PROFILE_ID")

@unittest.skipUnless(RUN and FOLDER and PROFILE and os.environ.get("MLX_API_TOKEN"), "needs real MLX")
```

- 行为限定为**只读生命周期**：Start → connect → 断言恰好 1 个 context → `browser.close()` → Stop；不导航、不登录、不上传。
- 默认 `unittest discover` 永远 skip；文档（ticket 09）写明 `SAU_MLX_SMOKE=1 ... python -m unittest tests.test_multilogin_smoke`。
- 结果（端口、耗时、状态码）记录到 ticket 08，不回写测试断言；测试只做结构性断言（能连上、能断开、能停止）。

### 6. 测试数据

- 目录：`tests/fixtures/multilogin/`，JSON 文件，一文件一类响应：`start_ok.json`、`start_locked.json`、`start_unauthorized.json`、`stop_ok.json`、`stop_already_stopped.json`、`status_running.json`、`status_stopped.json`。
- 来源：先按官方文档构造（ticket 01）；拿到真实账号后（ticket 08）用脱敏副本替换/补充，保留 `status.error_code`、`message`、`data.port` 等字段形状。
- 脱敏规则：token、cookie、代理地址、真实 `folder_id`/`profile_id` 一律替换为固定假 UUID。
- 不在测试里内联大段 JSON；小 payload 可内联，重复出现的走 fixture。

### 7. 不测什么（明确边界）

不自动化、由 ticket 08 / 人工验收覆盖：

- 各平台真实发布成功、平台风控、验证码、扫码、短信 2FA、地区跳转；
- Profile 指纹、代理出口 IP、Mimic 内核版本兼容（patchright 版本见 ticket 11）；
- MLX 云端 API、Docker launcher 端口映射、跨机拓扑（ticket 10）；
- Windows/macOS 桌面应用差异、SIGKILL/断电；
- `sau_backend.py` / Vue 前端（charter 明确不改）。

默认套件的判定标准不是覆盖率数字，而是上表每个契约至少一条正向 + 一条负向断言；`python -m unittest discover -s tests` 失败即阻断合并。

### 对下游 ticket 的约束

- **ticket 09**：spec 必须包含“测试矩阵”小节，逐条对应本文件第 3 节的表；不得把真实 MLX 作为默认验收前提。
- **ticket 08**：产出脱敏响应样本 + 冒烟结果；样本落入 `tests/fixtures/multilogin/`，结果只更新文档，不改测试结构。
- **ticket 11**：patchright 升级若改变 `connect_over_cdp` 行为，`test_browser_session` 的 fake 不变，另加一条 opt-in 真实 CDP 用例验证 attach/close。
