# 02 — patchright 1.58.2 与 Mimic CDP 兼容性调研

> 调研日期：2026-11-05  
> 范围：只读调研；未修改业务代码、地图或 ticket。  
> 证据等级标记：  
> - **【源码可证】**：本机安装/解包的 patchright / Playwright 源码中可直接读到。  
> - **【官方文档】**：Playwright 或 Multilogin 官方文档/发行说明。  
> - **【实测】**：本机用 patchright 1.58.2 + 真实 Chrome 156 做的隔离实验。  
> - **【社区报告】**：GitHub issue 等公开报告，未复现。  
> - **【推断】**：由上述证据推导，非直接声明。  
> - **【未知】**：查不到可靠依据。

## 0. 结论摘要

| # | 问题 | 结论 | 主要依据 |
|---|---|---|---|
| 1 | `connect_over_cdp` 是否可用 | **可用**，Python API 与上游同签名；但 patchright 的驱动补丁会改变 attach/init-script 行为，不是完全等价 | 源码 + 实测 |
| 2 | `contexts[0]` 是否一定存在 | **CDP 连接下默认 context 一定存在**，正常为 1 个；只有 1 个时 `contexts[0]` 就是默认 context。**可能多于 1 个**，此时 Python 客户端用 `Set` 保存、顺序不保证，不能假设 index 0 仍是默认；**不应为空**，空则 fail-fast | 源码 + 实测 |
| 3 | `browser.close()` 是断开还是关浏览器 | **只断开 CDP WebSocket，不关 Chrome/Profile**；官方示例也是 close 后再 MLX Stop | 源码 + 实测 + 官方示例 |
| 4 | `context.new_page()` 是否安全 | **不会创建新 context**，只创建默认 context 里的新 tab；但会留下真实标签页，需自行清理 | 源码 + 实测 |
| 5 | `add_init_script` 对已有 context 的行为 | **只影响之后的 http(s) 文档导航，不影响已加载文档**；patchright 通过路由改 HTML 注入，副作用大。**MLX 模式应跳过 `set_init_script`** | 源码 + 实测 |
| 6 | 哪些调用隐式建 context / 改 cookie | `browser.new_context()`、`browser.new_page()` 建 context；`storage_state` 可能临时建 page；`add_cookies` / `clear_cookies` 直接改 Profile cookie | 源码 |
| 7 | Chromium/Mimic 版本兼容 | 1.58.2 = Chromium **145**；Mimic 最新 **156** core，落后 11 个大版本。**官方没有给出 1.58.2 与 Mimic 156 的兼容声明**；建议升级 patchright **1.64.1**（Chromium 156） | 官方文档 + 源码 + 推断 |
| 8 | stealth 注入是否与 Mimic 指纹冲突 | **patchright 驱动不做 canvas/WebGL/字体/TLS/UA 等指纹伪造**；但本仓库的 `utils/stealth.min.js` 会覆盖 webdriver/chrome/plugins/WebGL 等，和 Mimic 引擎级指纹**直接冲突**，应禁用 | 源码 + 社区报告 + 推断 |
| 9 | 只读验证用 `pages[0]` 还是 `new_page()` | **优先按 URL 找已有 page；其次 `pages[0]`；最后才 `new_page()`**。`new_page()` 不破坏已有页面，但会多一个 tab 和一次导航 | 源码 + 实测 |
| 10 | `contexts[0]` 是否包含手动开的标签页 | **包含**（默认 context 的所有 page target）；但顺序不稳定，且不含其他 context / service worker / devtools 等非 page target | 源码 + 实测 |

**一句话建议**：MLX 分支使用 `connect_over_cdp` + `contexts[0]`，只复用/新建 page，不建 context、不碰 cookie/storage、不调 `add_init_script` 与 `set_init_script`；结束 `browser.close()` 后单独调 MLX Stop。若继续用 patchright，至少升到 **1.62.1**（修掉 CDP attach 的 `Frame was detached` 崩溃），**推荐 1.64.1**以匹配 Mimic 156 的 Chromium 156。

---

## 1. 调研方法与证据来源

### 1.1 本机源码

项目本身没有安装 patchright（`python -c "import patchright"` 失败），因此从 PyPI 下载 wheel 解包到临时目录检查：

- `patchright==1.58.2`（macOS arm64 wheel，2026-03-05 发布）
  - `patchright/_impl/_browser_type.py`
  - `patchright/_impl/_browser.py`
  - `patchright/_impl/_browser_context.py`
  - `patchright/driver/package/lib/server/chromium/chromium.js`
  - `patchright/driver/package/lib/server/chromium/crBrowser.js`
  - `patchright/driver/package/lib/server/chromium/crPage.js`
  - `patchright/driver/package/lib/server/chromium/crNetworkManager.js`
  - `patchright/driver/package/lib/server/browser.js`
  - `patchright/driver/package/lib/server/browserContext.js`
  - `patchright/driver/package/lib/server/dispatchers/browserDispatcher.js`
  - `patchright/driver/package/browsers.json`
- 对照上游 `playwright==1.58.0` wheel（PyPI 上 1.58 线只有 1.58.0；patchright 1.58.2 对应 Playwright 1.58.2 driver，Chromium 同为 145.0.7632.6）。
- 为确认修复边界，又解包了 patchright `1.60.1`、`1.61.1`、`1.62.1`、`1.63.0`、`1.64.1` 的 wheel，检查 `_eventBelongsToStaleFrame` 与 `browsers.json`。

### 1.2 本机隔离实验

在临时目录（不在仓库内）用 `uv` 创建 venv，安装 `patchright==1.58.2`，连接本机 Chrome：

- Chrome：`Chrome/156.0.8078.80`（stable，2026-11 本机）
- patchright：1.58.2（Chromium 145 驱动）
- 临时 `--user-data-dir`，`--remote-debugging-port=9333`
- 连接前用 CDP HTTP `/json/new` 打开 3 个 tab，然后 `connect_over_cdp`

实测结果：

```text
contexts after connect: 1
pages after connect: 3 ['...tab2...', 'about:blank', '...tab3...']
after context.new_page: contexts 1 pages 4
after browser.new_page: contexts 2 delta 1
after browser.new_context: contexts 3
after c2.close: contexts 2
after browser.close: chrome alive True
after browser.close: cdp version Chrome/156.0.8078.80
reconnect contexts: 1 pages: 4
```

第二组实验测 `add_init_script`：

```text
before add: None
after add, existing document: None
after add + navigation (data: URL): None
pages: 1 contexts: 1
```

说明见 Q5：1.58.2 的 init script 依赖路由注入 http(s) 文档，`data:`/`about:` 和已加载文档不会生效。

### 1.3 外部资料

- Playwright `BrowserType.connect_over_cdp` 与 `Browser.close` 官方 API 文档
- Playwright 1.58 / 1.64 release notes
- Multilogin 官方 Playwright 示例、release notes、core update 说明
- patchright GitHub releases 与相关 issue
- Playwright GitHub 相关 issue

---

## 2. 逐题回答

### Q1. patchright 1.58.2 的 `connect_over_cdp` 是否可用？与上游差异？

**结论：可用，API 同签名；但驱动层不是完全等价。**

【源码可证】`patchright/_impl/_browser_type.py` 中：

```python
async def connect_over_cdp(
    self,
    endpointURL: str,
    timeout: float = None,
    slowMo: float = None,
    headers: Dict[str, str] = None,
    isLocal: bool = None,
) -> Browser:
    params = locals_to_params(locals())
    if params.get("headers"):
        params["headers"] = serialize_headers(params["headers"])
    response = await self._channel.send_return_as_dict(
        "connectOverCDP", TimeoutSettings.launch_timeout, params
    )
    browser = cast(Browser, from_channel(response["browser"]))
    browser._connect_to_browser_type(self, None)
    return browser
```

与上游 `playwright==1.58.0` 的同名方法逐行一致（仅包名/格式差异）。驱动侧 `chromium.js` 的 `_connectOverCDPInternal` 也与上游一致：`persistent = { noDefaultViewport: true }`，`browserProcess = { close: doClose, kill: doClose }`，`doClose = chromeTransport.closeAndWait() + artifacts cleanup`。

**真正需要知道的差异（都会影响 CDP 场景）**：

1. **`Page.enable` 发送顺序不同**  
   【源码可证】patchright `crPage.js::FrameSession._initialize` 先 `const pageEnablePromise = this._client.send("Page.enable")`，再发 `Page.getFrameTree`；上游把两者放在同一个 `Promise.all` 里并发发送。  
   这导致 patchright 在 attach 已有很多 tab/正在导航的浏览器时更容易触发 `Frame was detached` 竞态（见 Q8、patchright #213）。

2. **`add_init_script` 改为路由注入**  
   【源码可证】patchright `_browser_context.py::add_init_script` 先 `install_inject_route()`，再发 `addInitScript`；驱动侧 `_evaluateOnNewDocument` 只把脚本放进 `_evaluateOnNewDocumentScripts`，由 `crNetworkManager` 在 HTML 响应里插入 `<script>`。上游是标准 CDP `Page.addScriptToEvaluateOnNewDocument`。详见 Q5。

3. **Console / Runtime 补丁**  
   【源码可证 + 官方 README】patchright 避免 `Runtime.enable`、禁用 Console API（README 明说 “console functionality will not work in Patchright”）。这些补丁对 CDP 连接同样生效，不是只在 launch 时生效。

4. **命令 flag 补丁不适用**  
   【推断】patchright 的 `--disable-blink-features=AutomationControlled` 等 flag 补丁只作用于它自己 launch 的浏览器；Mimic 的启动参数由 Multilogin 控制，这些补丁不会生效。

5. **`evaluate` 默认走 isolated world**  
   【源码可证】patchright 1.58.2 的 `Page.evaluate` / `Frame.evaluate` 签名新增 `isolated_context: bool = True`；上游默认在主 world。读 `window` 上的全局变量时要注意，必要时显式传 `isolated_context=False`。

**实测**：patchright 1.58.2 可以连接 Chrome 156 并完成 `contexts[0]`、`new_page`、`goto`、`close` 等基本操作；版本不匹配没有导致“完全连不上”。但这只能证明基本路径可用，不能证明长时间/复杂页面稳定。

---

### Q2. 连接后 `browser.contexts[0]` 是否一定存在？可能多个/为空吗？

**结论：在 `connect_over_cdp` 的 CDP 连接下，默认 context 一定存在，正常是 1 个；只有 1 个时 `contexts[0]` 就是默认 context。可能多于 1 个；多个时 Python 客户端的顺序不保证，不能假设 index 0 一定是默认。不应为空。MLX 分支遇到空数组应直接报错，绝不能 fallback 到 `new_context()`。**

【源码可证】连接路径：

- `chromium.js::_connectOverCDPInternal` 设置 `persistent = { noDefaultViewport: true }`
- `crBrowser.js::CRBrowser.connect`：
  ```js
  browser._defaultContext = new CRBrowserContext(browser, void 0, options.persistent);
  await Promise.all([
    session.send("Target.setAutoAttach", ...).then(...),
    browser._defaultContext._initialize()
  ]);
  await browser._waitForAllPagesToBeInitialized();
  ```
- `dispatchers/browserDispatcher.js` 构造时：
  ```js
  if (browser._defaultContext)
    this._dispatchEvent("context", { context: BrowserContextDispatcher.from(this, browser._defaultContext) });
  for (const context of browser.contexts())
    this._dispatchEvent("context", { ... });
  ```
  默认 context **先**被派发，然后是额外 context。但客户端 `patchright/_impl/_browser.py` 用 `self._contexts: Set[BrowserContext]` 保存，`contexts` 返回 `list(self._contexts)`；**Set 不保证顺序**。因此：
  - 只有 1 个 context 时，`contexts[0]` 一定是默认 context（实测正常 profile 即如此）；
  - 有多个 context 时，`contexts[0]` 不保证是默认 context，不能靠索引判断；
  - 正常至少 1 个。

**可能多个的情况**：

- 【源码可证】调用 `browser.new_context()` 会走 `Target.createBrowserContext`（`disposeOnDetach: true`），加入 `_contexts`，于是 `contexts` 变成 2、3……；
- 【推断】另一个 CDP 客户端/自动化工具在同一个 Chrome 上创建了额外 browser context；
- 【推断】某些扩展/特殊页面可能让 Chrome 暴露额外 context（Mimic 正常 profile 未见）。

额外 context 是“隔离/无痕”性质，**不共享 Mimic profile 的 cookie 和指纹设置**；MLX 分支绝不能使用它们。实测正常 profile 只有 1 个。

**MLX 分支建议**：连接后要求 `len(browser.contexts) == 1`；如果大于 1，最好直接报错/重连，而不是猜哪个是默认 context。若产品上必须容忍多 context，只能通过“哪个 context 的页面命中目标 URL/cookie”来选，但这已经超出“只用 contexts[0]”的设计，风险更高。

**空数组**：从源码看 `connect_over_cdp` 必然创建 `_defaultContext` 并派发，正常不会为空（前提：传入的是浏览器级 CDP endpoint，即 Multilogin 返回的 `http://127.0.0.1:{port}`，不是某个 page 的 ws URL）。若真的为空，说明连接对象异常（非 Chromium、协议不完整、驱动/浏览器不兼容），应 fail-fast。现有代码的：

```python
context = browser.contexts[0] if browser.contexts else await browser.new_context()
```

在 MLX 分支必须改成“为空就抛错”，因为 `new_context()` 会创建无指纹、无 cookie 的新 context。

---

### Q3. `browser.close()` 在 CDP 连接下是断开还是关闭浏览器？是否等价于 disconnect？

**结论：在 `connect_over_cdp` 下，`browser.close()` 只关闭 CDP WebSocket 连接并清理 Playwright artifacts，不会关闭 Chrome/Profile；语义上等价于“断开”。官方 Multilogin 示例也是 `browser.close()` 后再调 Stop。**

【源码可证】关键在 `Browser._should_close_connection_on_close`：

- `patchright/_impl/_browser.py` 构造函数里默认 `False`；
- 只有 `connect()`（Playwright 协议连接）和 Android 才设 `True`；`connect_over_cdp()` **没有设**；
- 因此 `Browser.close()` 走 `else` 分支，向驱动发 `close` channel，而不是直接 `connection.stop_async()`。

驱动侧：

- `server/browser.js::Browser.close` → `this.options.browserProcess.close()`
- `connectOverCDP` 的 `browserProcess` 是：
  ```js
  const doClose = async () => {
    await chromeTransport?.closeAndWait();
    await doCleanup();
  };
  const browserProcess = { close: doClose, kill: doClose };
  ```
- 即只关闭 WebSocket transport + 删除临时 artifacts 目录；**没有向 Chrome 发送 `Browser.close` / `Target.closeTarget`**。

【实测】`browser.close()` 之后：

- Chrome 进程仍存活；
- `http://127.0.0.1:9333/json/version` 仍返回 `Chrome/156.0.8078.80`；
- 重新 `connect_over_cdp` 成功，原有 tab 仍在（pages=4）。

【官方文档/示例】

- Playwright `Browser.close` 文档的措辞是“connected to, clears all created contexts ... and disconnects from the browser server”，这句话主要描述 `browser_type.connect()` 的 Playwright 协议连接；CDP 连接的实现以上面的源码为准。
- Multilogin 官方 JS 示例注释明确写：
  > `// Disconnect Playwright so the script can exit`
  > `await browser.close();`
  > `// Stop the profile`
  > `await axios.get(.../profile/stop/...)`
  这证明官方预期就是“close = 断开，Stop 才关 Profile”。

**注意**：

- `browser.close()` 会让客户端所有 Page/Context 对象失效，不能继续用；
- 通过 `browser.new_context()` 创建的额外 context 因为 `disposeOnDetach: true`，会在断开时被 Chrome 销毁（实测重连后 contexts 回到 1）；
- 默认 context 里用户手动打开的 tab **不会**被关闭（实测重连仍在）；
- 不要在流程中途调用；只在 `finally` 里断开。

`async with async_playwright()` 退出时也会停掉驱动、断开连接；显式 `browser.close()` 更可控，两者都不会杀 Chrome。

**`context.close()` 的区别**：

【源码可证】默认 context 的 `CRBrowserContext.doClose` 在 `!this._browserContextId` 时执行：

```js
await this._browser.close({ reason });
```

即关闭默认 context 等价于 `browser.close()`（断开），不是关 Chrome；但它会让该 context 的所有 Page 对象失效。MLX 分支不应调用 `context.close()`，只调用 `browser.close()`。

---

### Q4. `context.new_page()` 是否安全？会不会触发新 context？

**结论：安全，不会创建新 context；只在默认 context 里创建一个新 tab。但它是真实标签页，会在断开后继续留在 Profile 里，需自行关闭。**

【源码可证】`patchright/_impl/_browser_context.py::BrowserContext.new_page`：

```python
async def new_page(self) -> Page:
    if self._owner_page:
        raise Error("Please use browser.new_context()")
    return from_channel(await self._channel.send("newPage", None))
```

驱动侧 `CRBrowserContext.doCreateNewPage`：

```js
const { targetId } = await this._browser._session.send("Target.createTarget", {
  url: "about:blank",
  browserContextId: this._browserContextId
});
```

默认 context 的 `_browserContextId` 是 `undefined`，所以 `Target.createTarget` 落在 Chrome 默认 context，**不会** `Target.createBrowserContext`。

【实测】`context.new_page()` 后 `contexts` 仍为 1，`pages` 从 3 变 4；断开重连后这个新 tab 仍然在（pages=4），说明它不是临时的。

**对比 `browser.new_page()`（禁止）**：

【源码可证】`patchright/_impl/_browser.py::Browser.new_page`：

```python
async def inner() -> Page:
    context = await self.new_context(**params)
    page = await context.new_page()
    page._owned_context = context
    context._owner_page = page
    return page
```

即 `browser.new_page()` = `new_context()` + `context.new_page()`，会隐式创建一个额外 context。实测 `contexts` 从 1 变 2。MLX 分支禁止。

【官方文档】Multilogin 官方 Playwright 示例本身就用 `context.new_page()` 打开页面，并在结束时 `page.close()`；这说明 `context.new_page()` 是官方支持的路径。但它只关闭“自己创建的 page”，并没有关闭用户已有 tab。

**使用建议**：

- 上传流程优先复用已有 page；
- 只有找不到合适 page 时才 `context.new_page()`；
- 自己创建的 page 在 `finally` 里 `page.close()`；不要关闭用户手动开的 tab；
- 新 page 会出现在用户浏览器里，可能抢焦点/被用户误关，需接受这个产品行为。

---

### Q5. `context.add_init_script()` 对已存在 context/页面的行为？MLX 是否应跳过 `set_init_script`？

**结论：1.58.2 下 `add_init_script` 不会影响已经加载的文档；只对之后的 http(s) 文档导航生效，而且是通过“路由改写 HTML + 注入 `<script>`”实现。MLX 模式应跳过 `utils/base_social_media.py::set_init_script`。**

【源码可证】Python 侧：

```python
async def add_init_script(self, script=None, path=None):
    await self.install_inject_route()     # 关键：注册 **/* 路由
    if path:
        script = (await async_readfile(path)).decode()
    ...
    await self._channel.send("addInitScript", None, dict(source=script))
```

`install_inject_route()` 注册 `**/*` 路由，对每个 `resource_type == "document"` 且 `url.startswith("http")` 的请求：

```python
await route.fallback(url=f"{protocol}://patchright-init-script-inject.internal/")
```

驱动侧 `crNetworkManager.js` 看到 internal URL 后：

- 发 `Fetch.continueRequest({ requestId, interceptResponse: true })`（不改变真实网络 URL，但进入响应拦截）；
- 在 `fulfill` 阶段把 HTML body 改写，插入带随机 class 的 `<script>`，并修改 CSP 头/`<meta>` CSP（放宽 `script-src` 等）。

驱动侧 `crPage.js::FrameSession._evaluateOnNewDocument` 在 1.58.2 中**只是**：

```js
async _evaluateOnNewDocument(initScript, world, runImmediately) {
  this._evaluateOnNewDocumentScripts.push(initScript);
}
```

没有调用 `Page.addScriptToEvaluateOnNewDocument` 来注入用户脚本（那个调用在此版本只用于空的 utility world 初始化）。所以：

- **已加载文档**：不会重新执行 init script；
- **之后的 http/https 文档导航**：由路由拦截 HTML 并插入脚本；
- **`data:` / `about:` 等非 http(s) 文档**：不会被路由处理，脚本不生效（【实测】`data:` 导航后 `window.__pr` 仍为 `undefined`）；
- **iframe/动态文档**：取决于是否走 http(s) 文档请求，行为不完全等同于标准 init script。

**对 MLX 的影响**：

1. `set_init_script(context)` 即使当前页面看起来“没变化”，也会在默认 context 上安装一个 `**/*` 路由，改变后续所有文档请求的处理路径；
2. 会放宽 CSP、改写 HTML、注入 `<script>`，对依赖 CSP/流式响应/签名的站点可能直接破坏；
3. patchright 官方 README 自己警告：init script 通过 route 注入，“may cause some bugs”，且可被 timing attack 检测；
4. 本仓库的 `utils/stealth.min.js` 是 2024-06-10 由 `extract-stealth-evasions` 生成的 puppeteer-extra stealth 脚本，会改 `navigator.webdriver`、`window.chrome`、plugins、languages、WebGL vendor、hardwareConcurrency 等，和 Mimic 引擎级指纹**重复且冲突**（见 Q8）。

**结论**：MLX 分支应完全跳过 `set_init_script`；不仅“对已存在页面无效”，更重要的是它安装了全局路由和注入了与 Mimic 冲突的脚本。本地 launch 分支可以继续使用。

特别注意：现有登录流程在 `set_init_script(context)` 之后才 `page.goto("https://creator.douyin.com/")` / 快手登录页，因此 MLX 分支下首次导航就会命中 patchright 的文档路由并被注入 `stealth.min.js`，**不是“对已加载页面无效”就等于无操作**。

现有代码：

- `uploader/douyin_uploader/main.py:273` 在 CDP 分支取 `contexts[0]`，随后无条件 `context = await set_init_script(context)`；
- `uploader/ks_uploader/main.py:289` 同样。

MLX 分支应改成：`if not cdp_url: context = await set_init_script(context)`（或等价的显式条件），CDP/MLX 路径不调用。

---

### Q6. 还有哪些 Playwright 调用会隐式创建 context 或覆盖 cookie？

**结论：除了明显的 `new_context`，`browser.new_page()` 会隐式建 context；`storage_state()` 可能临时建 page；`add_cookies` / `clear_cookies` 会直接改 Profile cookie。MLX 分支应全部禁止。**

#### 6.1 会创建 context

| API | 行为 | 依据 |
|---|---|---|
| `browser.new_context()` | `Target.createBrowserContext`，创建隔离 context（`disposeOnDetach: true`），不共享 Mimic cookie/指纹 | 【源码可证】`crBrowser.js::doCreateNewContext` |
| `browser.new_page()` | 内部先 `new_context()` 再 `context.new_page()`，隐式建 context | 【源码可证】`_browser.py::Browser.new_page`；【实测】contexts +1 |
| `browser_type.launch_persistent_context()` | 启动新浏览器，不是“连接已有 Mimic”；MLX 不用 | 【源码可证】 |
| `connect_over_cdp()` 自身 | 会创建“默认 context”的客户端表示；这是连接本身的一部分，不是额外 context，不能避免 | 【源码可证】 |

#### 6.2 不会创建 context，但会创建 page

| API | 行为 | 依据 |
|---|---|---|
| `context.new_page()` | 默认 context 内新建 tab；无新 context | 【源码可证】`Target.createTarget`，`browserContextId: undefined` |
| `context.storage_state()` | 读取 cookie/localStorage；若某些已访问 origin 没有打开的 page，会临时 `newPage(..., forStorageState=true)` 去读 localStorage，然后关闭 | 【源码可证】`browserContext.js::storageState` |
| `context.storage_state(path=...)` | 同上，并把结果写文件 | 【源码可证】 |

注意：`context.storage_state()` 对浏览器是“读”，不是写；但它可能临时开 page，而且设计上禁止读写 storage_state，所以 MLX 分支应禁用。1.58.2 没有 `context.set_storage_state()` 这个 API。

#### 6.3 会覆盖/删除 cookie 或 Profile 状态

| API | 行为 | 依据 |
|---|---|---|
| `context.add_cookies()` | 直接写默认 context 的 cookie store，等于改用户登录态 | 【源码可证】`Storage.setCookies` / `Network.setCookies` 路径 |
| `context.clear_cookies()` | 默认 context 的 `browserContextId` 为空，`Storage.clearCookies` 作用于整个 Profile 的 cookie；Playwright 之后会把“不匹配过滤条件”的 cookie 加回去，但匹配的会被删 | 【源码可证】`crBrowser.js::doClearCookies`、`browserContext.js::clearCookies` |
| `context.storage_state()` | 只读；不要和写混淆 | 【源码可证】 |
| `new_context(storage_state=...)` | 在新 context 里灌 cookie，不写 Profile；但创建 context 本身已禁止 | 【源码可证】 |
| `context.close()` | 关闭默认 context → `browser.close()`（断开），所有 Page 对象失效 | 【源码可证】`crBrowser.js::doClose` |
| `page.close()` | 关闭该 tab；如果是用户的 tab，等于替用户关页面 | 【源码可证】 |
| `context.grant_permissions()` / `clear_permissions()` | 改默认 context 的权限覆盖（geolocation/notifications 等），可能影响指纹/站点行为 | 【源码可证】 |
| `context.set_geolocation()` / `set_offline()` | 改 Emulation 状态，覆盖 Mimic 的 geolocation/网络设置 | 【源码可证】 |
| `context.set_extra_http_headers()` | 给所有请求加头，可能暴露自动化/破坏站点 | 【源码可证】 |
| `context.route()` / `unroute()` / `route_from_har()` | 安装请求拦截，改变网络行为；patchright 的 init script 也依赖 route | 【源码可证】 |
| `context.add_init_script()` / `page.add_init_script()` | 安装 `**/*` 路由并注入脚本 | 【源码可证】 |
| `context.expose_binding()` / `expose_function()` | 同样走 `install_inject_route()`，注入脚本/绑定 | 【源码可证】 |
| `page.emulate_media()` | 覆盖 `prefers-color-scheme` 等，可能覆盖 Mimic 的 profile 媒体设置 | 【源码可证】`crPage.js::_updateEmulateMedia` |
| `page.set_viewport_size()` | 覆盖窗口/视口；Mimic 正常不应被改 | 【源码可证】 |
| `page.clock.install()` | 安装 clock 脚本；patchright + CDP 有已知导航失败报告（#197） | 【社区报告】 |
| `context.tracing.start()` / `browser.start_tracing()` | 写 trace 文件、注入 tracing；非必要不要用 | 【源码可证】 |
| `browser.new_browser_cdp_session()` / `context.new_cdp_session()` | 原始 CDP；只读诊断可以，但写命令会绕过所有保护 | 【源码可证】 |

#### 6.4 只读安全

| API | 说明 |
|---|---|
| `browser.contexts` / `browser.is_connected` / `browser.version` | 纯客户端只读 |
| `context.pages` / `page.url` / `page.title()` | 只读（title 需要执行 JS，但不改状态） |
| `context.cookies()` | 只读，返回 cookie；敏感信息不要打印 |
| `page.locator()` / `get_by_*()` / `wait_for_*()` / `screenshot()` | 只读 DOM/截图 |
| `context.set_default_timeout()` / `set_default_navigation_timeout()` | 纯客户端超时设置，不改浏览器状态 |

---

### Q7. patchright 1.58.2 对应 Chromium 与 Mimic core 的兼容性；官方 release notes 有无说明？

**结论：1.58.2 对应 Chromium 145；Mimic 最新 156 core（2026-11-03）大致对应 Chrome 156。落后 11 个大版本。官方没有给出 1.58.2 与 Mimic 156 的兼容性声明；建议升级到 patchright 1.64.1（Chromium 156）。**

#### 7.1 版本映射

| patchright | 对应 Playwright 线 | 发布日期 | 内置 Chromium | 依据 |
|---|---|---|---|---|
| **1.58.2（当前）** | 1.58.2 driver | 2026-03-05 | **145.0.7632.6** | 【源码可证】`browsers.json` |
| 1.60.1 | 1.60.1 | 2026-06 | **148.0.7778.96** | 【源码可证】 |
| 1.61.1 | 1.61.1 | 2026-06-23 | **149.0.7827.55** | 【源码可证】 |
| **1.62.1** | 1.62.1 | 2026-08-17 | **151.0.7922.34** | 【源码可证】 |
| 1.63.0 | 1.63.0 | 2026-09-08 | **153.0.8010.12** | 【源码可证】 |
| **1.64.1** | 1.64.1 | 2026-10-15 | **156.0.8078.4** | 【源码可证】 |

- Playwright 1.58 release notes：`Chromium 145.0.7632.6`，并注明 tested against `Google Chrome 144` / `Microsoft Edge 144`【官方文档】。
- Playwright 1.64 release notes：`Chromium 156.0.8078.4`，tested against `Google Chrome 155` / `Microsoft Edge 155`【官方文档】。
- Multilogin release notes：2026-11-03 “Mimic got the new 156 core”；2026-10-20 “155 core”；2026-10-06 “154 core”……【官方文档】。
- Multilogin core update 说明：Chrome 新 core 发布后，Multilogin 测试 1–2 周再推送 Mimic core；Stealthfox 固定在 146（对应 Firefox 146）【官方文档】。因此 **Mimic 156 ≈ Chromium/Chrome 156** 是合理推断【推断】；Mimic 具体 build 号未公开【未知】。

#### 7.2 官方有没有说兼容性？

- Multilogin 官方 Playwright 示例明确要求：
  > “Make sure Playwright is compatible with the current Mimic core version – check the release notes for Playwright and Mimic”
  但它**没有给出版本矩阵**，也没有说 1.58.2 是否兼容 156【官方文档】。
- Multilogin release notes 中提到 Playwright 的地方主要是“让网站更难检测 Playwright”（Mimic 133，2025-02-26），不是版本兼容声明【官方文档】。
- patchright 的 release 是“跟随 Playwright 自动重发”，没有逐版本 Mimic 兼容说明【官方文档/社区】。

**所以：1.58.2 vs Mimic 156 的官方兼容性 = 未知；只能靠 CDP 实测和版本对齐推断。**

#### 7.3 实测与风险

【实测】patchright 1.58.2 连接 Chrome 156.0.8078.80 可以完成基本的 `contexts[0]`、`new_page`、`goto`、`browser.close`、重连。这说明 CDP 协议在 145→156 之间没有发生“完全不可用”的破坏。

但风险仍在：

- Playwright 官方说 CDP 连接“significantly lower fidelity than the Playwright protocol connection”，且 Playwright 只对自己捆绑的浏览器版本做保证【官方文档】；
- Chromium CDP 不是稳定的公开 API，Chrome 新版本可能改 domain/事件/时序【官方文档/社区】；
- 1.58.2 缺少 1.60+ 的 `no_defaults` 选项，连接时会对默认 context 施加一些默认覆盖（download behavior、focus emulation、media 等），可能和 Mimic profile 设置冲突【源码可证/推断】；
- 1.58.2 有 patchright 特有的 attach 竞态（Q8），Mimic 如果启动时已有多个 tab/正在导航，可能触发。

#### 7.4 推荐版本

**首选：`patchright==1.64.1`（Chromium 156.0.8078.4）**

- 与 Mimic 156 的 Chromium 大版本对齐；
- 已包含 `_eventBelongsToStaleFrame` 的 try/catch 修复（Q8）；
- `connect_over_cdp` 新增 `noDefaults` / `artifactsDir`，可以传 `no_defaults=True` 减少对 Mimic 默认 context 的覆盖；
- Python 要求 `>=3.10`，项目 `>=3.10,<3.13` 满足。

**最低可行（仅修 CDP 崩溃）：`patchright>=1.62.1`**

- 【源码可证】1.61.1 的 `_eventBelongsToStaleFrame` 没有 try/catch；1.62.1 已有：
  ```js
  let session;
  try {
    session = this._crPage._sessionForFrame(frame);
  } catch {
    return true;
  }
  ```
- 但 1.62.1 是 Chromium 151，仍比 Mimic 156 落后 5 个大版本；能用不等于最优。

**备选：MLX 路径改用上游 `playwright==1.64.1`**

- 上游 1.64.1 也是 Chromium 156.0.8078.4，`connect_over_cdp` 有 `no_defaults`；
- 没有 patchright 的 `Page.enable` 竞态和 `add_init_script` 路由机制；
- 但本地 launch 分支如果还需要 patchright 的防检测，就要同时保留两个包（或只在 MLX 路径 import playwright）。  
  注意：不要在一个进程里对同一个浏览器同时用两个客户端连接；二选一。

**如果必须留在 1.58.2**

- 连接前让 Mimic profile 尽量少开 tab，避免 attach 时有正在导航/卸载的 frame；
- 连接失败时重试（`Frame was detached` 是驱动进程崩溃，重试需要重新起 `async_playwright`）；
- 不要调用 `add_init_script` / `set_init_script`；
- 接受“官方无兼容声明”的风险，先在小号 profile 上灰度。

---

### Q8. patchright stealth 注入与 Mimic 指纹是否冲突？已知 `Target.attachToTarget` / `Runtime.evaluate` 类错误？

**结论：patchright 驱动本身不做 canvas/WebGL/字体/TLS/UA 等指纹伪造，只处理自动化 tell（webdriver、命令 flag、Runtime/Console），不会直接覆盖 Mimic 的指纹值；但本仓库的 `utils/stealth.min.js` 会覆盖多项指纹，和 Mimic 直接冲突。已知错误主要不是“指纹冲突”，而是 patchright/CDP 在自定义 Chromium 上的 attach/execution-context 兼容问题；Mimic 专项的公开报告目前没有。**

#### 8.1 stealth 注入的层次

| 层次 | 是否改指纹 | 与 Mimic 的关系 |
|---|---|---|
| patchright 驱动补丁（避免 `Runtime.enable`、禁用 Console、去 `--enable-automation` 等） | **不改** canvas/WebGL/UA；只减少 CDP/自动化 tell | 不直接覆盖 Mimic 指纹；但 Mimic 自己也可能在 core 层处理 Playwright 检测，二者可能重复 |
| `utils/stealth.min.js`（puppeteer-extra `extract-stealth-evasions`，2024-06-10） | **改** `navigator.webdriver`、`window.chrome`、plugins、languages、WebGL vendor、hardwareConcurrency 等 | **直接冲突**：Mimic 按 profile 生成的指纹会被脚本覆盖，或出现属性描述符/toString 不一致 |
| patchright init script 的路由注入 | 不一定改指纹，但改 HTML/CSP/网络时序 | 可能被站点/反bot 检测（timing、`document.scripts`），也可能破坏 CSP/流式页面 |

【源码可证】`utils/stealth.min.js` 头部：

```js
/*!
 * Note: Auto-generated, do not update manually.
 * Generated by: https://github.com/berstend/puppeteer-extra/tree/master/packages/extract-stealth-evasions
 * Generated on: Mon, 10 Jun 2024 06:21:08 GMT
 */
```

文件里确实包含 `webdriver`、`chrome`、`plugins`、`languages`、`WebGL`、`hardwareConcurrency` 等覆盖逻辑。

【官方文档/README + 推断】patchright 的 patch 列表主要是 `Runtime.enable`、`Console.enable`、命令 flags、closed shadow roots；列表中没有 canvas/WebGL/字体/TLS/输入指纹伪造。因此：

- **patchright 驱动 + Mimic**：不会因为“patchright 自己注入指纹”而冲突；
- **patchright 驱动 + 本仓库 stealth.min.js + Mimic**：三层叠加，冲突风险高，且 stealth.min.js 是 2024 年的老脚本，现代反bot 很容易识别。

#### 8.2 已知错误/报告

| 报告 | 现象 | 与 MLX 的相关性 |
|---|---|---|
| patchright #213（2026-06-09，1.60.1，macOS） | `connect_over_cdp` 到“有已打开 tab 的真实 Chrome”时，驱动崩溃：`Error: Frame was detached` at `CRPage._sessionForFrame` / `_eventBelongsToStaleFrame`；上游 Playwright 同场景正常 | **高**：1.58.2 源码同样把 `Page.enable` 提前发送，存在同一竞态；1.62.1 已含 try/catch 修复（1.61.1 不含；1.62.0 未单独验证） |
| patchright #18 / #28（2025-02） | 连接 Dolphin Anty（另一款 Chromium 反检测浏览器）后 `page.goto()` 崩溃：`TypeError: Cannot read properties of undefined (reading 'object')` in `frames.js`；维护者回复“只支持正常 Chrome，不支持付费第三方浏览器” | **中**：Mimic 也是第三方 Chromium；说明 patchright 对非标准 Chromium 的 execution-context 处理有风险；但 Mimic 未有公开同类报告 |
| Playwright #43638 | `connectOverCDP` 在 attach 到“没有 browserContextId 的 target”（如 shared worker）时触发未捕获 assertion，整个驱动进程退出；错误出现在 `Target.attachedToTarget` 处理里 | **中**：Mimic 若暴露 shared worker/特殊 target，可能触发；未知 |
| Playwright #41093 | 任一已打开 tab 有“已开始但未 commit”的导航时，`connectOverCDP` 可能一直挂起 | **中**：Mimic profile 若有很多 tab/慢代理，连接可能超时；建议连接前减少 tab |
| patchright #197（2026-05） | WebView2 / Edge 145+ 上 `connect_over_cdp` + `page.clock.install()` 导致 `ERR_NAME_NOT_RESOLVED`；上游 Playwright 不复现 | **低–中**：说明 patchright 的 CDP/clock 组合有已知导航问题；MLX 分支不要用 `page.clock` |
| patchright #41（2025-03） | 使用 `addInitScript` 时被 Cloudflare 检测；维护者后续修复 | **中**：说明 init script 路由注入本身可被检测；支持“MLX 跳过 set_init_script” |

**关于 `Target.attachToTarget`**：

- 常见的 `Target.attachToTarget: Target with given ID not found` 多与 endpoint 错误/页面级 ws URL/端口过期有关（社区经验），不是 Mimic 特有；
- 更值得关注的是 Playwright #43638 的 `Target.attachedToTarget` assertion：它会在 attach 阶段直接杀死驱动进程，属于“连接后立刻崩”的硬错误；
- Mimic 是否暴露无 `browserContextId` 的 target：**未知**，没有公开报告。

**关于 `Runtime.evaluate`**：

- patchright 为了避免 `Runtime.enable`，用手动 execution context 管理；它会用 `Runtime.evaluate("globalThis")` 等命令解析 main world（patchright 源码/文档）；
- 在自定义 Chromium（Dolphin）上就出现过 `frames.js` 里 `resolvedNode.object` 为 `undefined` 的崩溃（#18/#28）；
- Mimic 是否会让 `Runtime.evaluate` 返回异常结构：**未知**；目前没有 Mimic 专项 issue。

**综合判断**：

- 不要加 `stealth.min.js`；Mimic 的指纹应由 Mimic core 独占。
- patchright 驱动层补丁可以保留（它不做 canvas/WebGL/字体/TLS/UA 伪造），但要接受“第三方浏览器不受维护者支持”的风险。
- 如果 Mimic 环境下出现 attach 崩溃/执行上下文错误，优先切上游 `playwright` 做对照，而不是继续叠加 stealth 脚本。

---

### Q9. 只读验证登录态：用 `context.pages[0]` 还是 `context.new_page()`？

**结论：优先在 `context.pages` 里按 URL/origin 找已有 page；找不到再退 `pages[0]`；最后才 `new_page()`。`new_page()` 不会破坏已有页面，但会新增 tab、产生导航和 cookie 副作用，不是“只读”。**

【源码可证/实测】

- `page.url` 读取不需要导航；已有 page 是最“只读”的。
- `context.pages` 的顺序**不是**打开顺序，也不是固定顺序；实测 3 个 tab 返回 `[tab2, about:blank, tab3]`。所以不要假设 `pages[0]` 是某个特定页面。
- `pages[0]` 可能是 `chrome://newtab`、扩展页、用户正在用的页面；直接 `goto` 会覆盖用户当前页面状态（历史、表单、滚动位置）。
- `context.new_page()` 只在默认 context 内建 tab，不会建 context，但会：
  - 在用户浏览器里多一个可见 tab；
  - 触发一次导航（可能写 cookie、localStorage、history）；
  - 如果忘记关，会留在 Profile 里（实测断开重连仍在）。
- `new_page()` **不会**关闭或破坏已有 page；它只是新增。真正“破坏现有页面状态”的是在已有 page 上 `goto/reload`，而不是 `new_page()`。

**推荐逻辑**：

```python
def pick_page(context, target_host):
    for p in context.pages:
        try:
            if target_host in (p.url or ""):
                return p, False
        except Exception:
            pass
    if context.pages:
        return context.pages[0], False
    return await context.new_page(), True
```

- 用 URL 命中目标域名的已有 tab：最安全，不新增 tab；
- 没有匹配时，若必须导航，`new_page()` 比覆盖用户当前 tab 更可控；但要 `finally: if created: await page.close()`；
- 只读检查登录态时，优先用 DOM locator（`page.get_by_text` / `locator.is_visible`）而不是 `page.evaluate("window.xxx")`，因为 patchright 的 `evaluate` 默认 isolated world（1.58.2 签名 `isolated_context=True`），看不到主 world 的全局变量；确实需要时传 `isolated_context=False`。

**注意**：如果页面正在导航/未 commit，`pages` 里可能出现“hollow page”（URL 为空、操作超时），这是 Playwright connectOverCDP 的已知问题（#39483）。连接后先等 `page.url` 非空 / `wait_for_load_state`，再判断。

---

### Q10. `contexts[0]` 是否包含用户手动打开的标签页？上传能否复用已有页面？

**结论：在正常只有 1 个 context 的前提下，`contexts[0]` 就是默认 context，包含该 Mimic profile 的所有普通 tab（手动打开的和自动打开的）。上传可以复用已有页面，但要按 URL 选择、注意顺序不稳定和用户并发操作。**

【源码可证】`crBrowser.js::_onAttachedToTarget`：

```js
let context = this._contexts.get(targetInfo.browserContextId) || null;
if (!context)
  context = this._defaultContext;

if (targetInfo.type === "page" || treatOtherAsPage) {
  const crPage = new CRPage(session, targetInfo.targetId, context, ...);
  this._crPages.set(targetInfo.targetId, crPage);
}
```

Chrome 默认 context 的 tab（无论手动开还是脚本开）都会落到 `_defaultContext`，因此 `contexts[0].pages` 能看到它们。实测连接前用 `/json/new` 开的 3 个 tab 全部出现在 `contexts[0].pages`。

**不包含/可能缺失的情况**：

- 其他 browser context（`Target.createBrowserContext` 创建的隔离 context）里的 tab：不在默认 context；
- `type != "page"` 的 target：service worker、shared worker、devtools、扩展 background 等，不会作为 Page；
- 连接时正在导航/未 commit 的 tab：可能暂时不在 `pages` 或为 hollow page（#39483）；
- 页面被关闭/崩溃/被用户切走：状态会变，脚本要容错；
- `context.pages` 的顺序不保证，不能靠索引定位。

**上传复用建议**：

- 按目标站点 URL（如 `creator.douyin.com` / `cp.kuaishou.com`）在 `context.pages` 里找 page；
- 找到后确认 `page.url` 非空、`page.is_closed()` 为 false，再操作；
- 不要对用户正在编辑的 tab 直接 `goto`；如果必须导航，优先新建 page（并负责关闭）；
- 上传过程中用户可能手动切 tab/关 tab，操作要用 try/except 包围，失败时重新选 page；
- 关闭时只关“自己创建的 page”，不要关用户 tab。

---

## 3. MLX 分支 Playwright API 白名单/黑名单

> 原则：**只用 `contexts[0]`；不建 context；不读写 storage_state；不碰 cookie；不改 Mimic 指纹/网络；结束只 `browser.close()` 断开，再 MLX Stop。**

### 3.1 允许调用

| API | 说明 |
|---|---|
| `p.chromium.connect_over_cdp(url, timeout=..., ...)` | 唯一连接入口；升级后可加 `no_defaults=True` |
| `browser.contexts` / `browser.is_connected` / `browser.version` | 只读 |
| `browser.contexts[0]` | 默认 context；空则报错，不 fallback |
| `context.pages` / `page.url` / `page.title()` | 只读 |
| `context.cookies()` | 只读；注意敏感信息 |
| `page.locator()` / `get_by_*()` / `wait_for_selector()` / `wait_for_load_state()` / `wait_for_url()` | 只读 DOM/等待 |
| `page.screenshot()` | 只读，写本地文件 |
| `page.goto()` / `page.reload()` | **条件允许**：只对“自己创建的 page”或“明确可覆盖的 page”使用；不要覆盖用户正在用的 tab |
| `context.new_page()` | **条件允许**：只用于找不到合适 page 时；创建后记录 `created=True`，结束时 `page.close()` |
| `page.close()` | **条件允许**：只关自己创建的 page；不要关用户 tab |
| `context.set_default_timeout()` / `set_default_navigation_timeout()` | 纯客户端，安全 |
| `page.on("console")` / `page.on("request")` 等事件监听 | 只读；但 patchright 禁用了 Console API，console 事件可能不工作 |
| `browser.close()` | **只允许在 finally 做断开**；不是 MLX Stop |
| `context.new_cdp_session(page)` | **仅诊断**，只发只读 CDP 命令；不要写 |

### 3.2 禁止调用

| API | 原因 |
|---|---|
| `browser.new_context()` | 创建隔离 context：无 Mimic cookie、无指纹、无意义 |
| `browser.new_page()` | 隐式 `new_context()`；实测 contexts +1 |
| `browser_type.launch()` / `launch_persistent_context()` | 启动新浏览器，不是 Mimic |
| `new_context(storage_state=...)` | 创建 context + 灌 cookie |
| `context.storage_state()` / `storage_state(path=...)` | 设计禁止；可能临时开 page；path 还会写文件 |
| `context.add_cookies()` | 直接改 Profile cookie/登录态 |
| `context.clear_cookies()` | 默认 context 下清整个 Profile cookie |
| `context.close()` | 关闭默认 context → 断开并让所有 Page 失效；应只 `browser.close()` |
| `context.add_init_script()` / `page.add_init_script()` | 安装 `**/*` 路由、改 HTML/CSP、注入 stealth.min.js；与 Mimic 冲突 |
| `context.expose_binding()` / `expose_function()` | 同样安装路由/注入脚本 |
| `context.route()` / `unroute()` / `route_from_har()` / `page.route()` | 改网络拦截，可能破坏 Mimic/站点 |
| `context.grant_permissions()` / `clear_permissions()` | 改默认 context 权限覆盖 |
| `context.set_geolocation()` / `set_offline()` | 覆盖 Mimic 的 geolocation/网络 |
| `context.set_extra_http_headers()` / `page.set_extra_http_headers()` | 改所有请求头，暴露自动化/破坏站点 |
| `page.emulate_media()` / `page.set_viewport_size()` | 覆盖 Mimic profile 的媒体/视口设置 |
| `page.clock.install()` | patchright + CDP 有已知导航失败（#197） |
| `context.tracing.start()` / `browser.start_tracing()` | 写 trace、注入 tracing；非必要不用 |
| `browser.new_browser_cdp_session()` | 原始 CDP；写命令会绕过保护 |
| `page.close()`（对用户 tab） | 关闭用户页面 |
| `browser.close()`（流程中途） | 会让 Page 失效，上传中断 |

### 3.3 条件允许

| API | 条件 |
|---|---|
| `context.new_page()` | 仅在找不到目标 URL 的已有 page 时；创建后必须关闭（只关自己的） |
| `page.goto()` / `reload()` | 仅对“自己创建的 page”或“明确允许覆盖的 page”；不要对用户正在编辑的 tab 导航 |
| `page.evaluate()` | 只读表达式；patchright 默认 isolated world；需要主 world 时显式 `isolated_context=False`，且不要改页面状态 |
| `context.new_cdp_session()` | 仅只读诊断（如 `Target.getTargetInfo`）；不要发 `Runtime.evaluate` 写操作 |
| `browser.close()` | 只在 finally，断开 CDP；之后必须单独调 MLX Stop |

---

## 4. 对现有代码的具体影响（不改代码，仅指出）

### 4.1 登录流程的 `contexts[0]` fallback

`uploader/douyin_uploader/main.py:273`、`uploader/ks_uploader/main.py:289` 当前写法：

```python
context = browser.contexts[0] if browser.contexts else await browser.new_context()
```

- 非 MLX 分支（本地 launch）没问题；
- MLX 分支必须改成“为空就抛错”，不能 fallback 到 `new_context()`；
- 理由：`new_context()` 会创建隔离 context，没有 Mimic cookie/指纹，登录态验证一定失败，而且违反设计要求。

### 4.2 `set_init_script` 无条件调用

两个登录流程在 CDP 分支之后都有：

```python
context = await set_init_script(context)
```

- MLX 分支必须跳过；
- 非 MLX 的本地 launch 分支可以保留；
- 理由见 Q5/Q8：它会安装 `**/*` 路由、注入 2024 年的 stealth 脚本、放宽 CSP，与 Mimic 引擎级指纹冲突。

### 4.3 `context.new_page()` 的使用

登录流程目前用 `context.new_page()` 打开登录页。MLX 分支可以继续用，但：

- 它会新增真实 tab，断开后留在 Profile；
- 如果登录流程结束不关闭，下次连接会看到多余 tab；
- 建议：登录/上传只使用一个 page；用完关闭自己创建的 page；或者直接复用已有目标页。

### 4.4 关闭顺序

推荐：

```python
try:
    ...
finally:
    if created_page and not page.is_closed():
        await page.close()
    await browser.close()   # 只断开 CDP
# 然后
mlx.stop_profile(profile_id)
```

不要：

```python
await context.close()   # 等价于断开 + 让 page 失效
await browser.close()   # 重复
# 或者把 browser.close() 当成 MLX Stop
```

---

## 5. 版本建议（汇总）

| 方案 | 版本 | 优点 | 缺点/风险 |
|---|---|---|---|
| **推荐** | `patchright==1.64.1` | Chromium 156 对齐 Mimic 156；包含 #213 修复；支持 `no_defaults` | 需要回归测试；1.64 与 1.58 API 有少量新增参数 |
| 最低修 CDP 崩溃 | `patchright>=1.62.1` | 修复 `Frame was detached` 竞态 | Chromium 151，仍落后 Mimic 156 |
| 备选（MLX 专用） | `playwright==1.64.1` | 无 patchright 的 CDP 竞态；Chromium 156；`no_defaults` | 需要与本地 patchright 并存/切换；上游也有 #43638 等 attach 问题 |
| 维持现状 | `patchright==1.58.2` | 不改依赖 | Chromium 145 vs Mimic 156；有 `Frame was detached` 风险；无 `no_defaults`；官方无兼容声明 |

**建议落地顺序**：

1. 先在测试 profile 上把 patchright 升到 `1.64.1`，用 `connect_over_cdp(..., no_defaults=True)`；
2. MLX 分支跳过 `set_init_script`，改为只复用 page；
3. 用真实 Mimic profile 做 3 类验证：
   - 有 1 个/多个手动 tab 时能否稳定连接；
   - 上传后 `browser.close()` 再 MLX Stop，Profile 是否正常关闭；
   - 登录态页面是否未被 stealth 脚本覆盖（检查 `navigator.webdriver`、WebGL、plugins 与 Mimic 预期一致）。
4. 如果 1.64.1 仍出现 attach/execution-context 错误，切上游 `playwright==1.64.1` 做 A/B，确认是 patchright 驱动问题还是 Mimic 侧问题。

**关于 `no_defaults`**：

- Playwright 1.60+ 的 `connect_over_cdp(..., no_defaults=True)` 用于“附加到用户日常浏览器”时避免 Playwright 对默认 context 施加默认覆盖（acceptDownloads、focus emulation、media 等）【官方文档】；
- 对 Mimic 同理，建议在 1.64.1 上传 `no_defaults=True`，减少对 profile 设置的干扰；
- 1.58.2 没有这个参数，无法关闭这些默认覆盖。

---

## 6. 明确未知/待验证

1. **Mimic 156 的具体 Chromium build 号**：官方只写 “156 core”，没有公开 `156.0.xxxx.xx`【未知】。按 Chrome 156 推断，但不能保证与 Playwright 1.64.1 的 `156.0.8078.4` 完全同 build。
2. **Mimic 是否存在无 `browserContextId` 的 target / shared worker**：没有公开报告；若存在，可能触发 Playwright #43638 的 attach assertion【未知】。
3. **Mimic 是否对 CDP 客户端做限制/混淆**：官方只说支持 Playwright over CDP；没有协议细节【未知】。
4. **patchright 1.64.1 + Mimic 156 的长时间稳定性**：未实测；本报告只验证了 1.58.2 + 普通 Chrome 156 的基本路径【未知】。
5. **Mimic 官方是否测试过 patchright**：官方示例只用上游 `playwright`；没有提到 patchright【官方文档】。patchright 维护者也明确不对第三方反检测浏览器提供支持（#18）【社区报告】。

---

## 7. 参考

### 7.1 官方文档

- Playwright `BrowserType.connect_over_cdp`：  
  <https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-c-d-p>
- Playwright `Browser.close`：  
  <https://playwright.dev/python/docs/api/class-browser#browser-close>
- Playwright release notes（1.58 / 1.64 的 Chromium 版本）：  
  <https://playwright.dev/python/docs/release-notes>
- Multilogin Playwright 示例：  
  <https://multilogin.com/help/en_US/puppeteer-selenium-and-playwright/playwright-automation-example>
- Multilogin release notes（Mimic 152–156 core）：  
  <https://multilogin.com/release-notes/>
- Multilogin core update 说明（Mimic core 跟随 Chrome，1–2 周延迟）：  
  <https://multilogin.com/help/en_US/core-updates-and-how-they-work>
- patchright PyPI / GitHub releases：  
  <https://pypi.org/project/patchright/>  
  <https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python/releases>
- patchright README（patch 列表、Stealth、Init Script Shenanigans）：  
  <https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python>  
  <https://github.com/Kaliiiiiiiiii-Vinyzu/patchright>

### 7.2 源码（本机解包）

- `patchright==1.58.2` wheel：
  - `patchright/_impl/_browser_type.py::BrowserType.connect_over_cdp`
  - `patchright/_impl/_browser.py::Browser.new_page` / `Browser.close`
  - `patchright/_impl/_browser_context.py::BrowserContext.new_page` / `add_init_script` / `install_inject_route`
  - `patchright/driver/package/lib/server/chromium/chromium.js::_connectOverCDPInternal`
  - `patchright/driver/package/lib/server/chromium/crBrowser.js::CRBrowser.connect` / `_onAttachedToTarget` / `doCreateNewPage` / `doClose` / `doClearCookies`
  - `patchright/driver/package/lib/server/chromium/crPage.js::FrameSession._initialize` / `_eventBelongsToStaleFrame` / `_evaluateOnNewDocument`
  - `patchright/driver/package/lib/server/chromium/crNetworkManager.js::RouteImpl.continue` / `fulfill`
  - `patchright/driver/package/lib/server/browser.js::Browser.close`
  - `patchright/driver/package/lib/server/browserContext.js::BrowserContext.storageState` / `clearCookies`
  - `patchright/driver/package/lib/server/dispatchers/browserDispatcher.js`
  - `patchright/driver/package/browsers.json`
- 对照上游 `playwright==1.58.0` wheel：同名文件 diff。
- 修复边界对照：patchright `1.61.1` / `1.62.1` / `1.63.0` / `1.64.1` 的 `_eventBelongsToStaleFrame` 与 `browsers.json`。

### 7.3 社区报告

- patchright #213 — connect_over_cdp 到有 tab 的真实 Chrome 崩溃 `Frame was detached`：  
  <https://github.com/Kaliiiiiiiiii-Vinyzu/patchright/issues/213>
- patchright-python #18 — Dolphin Anty CDP `frames.js` TypeError：  
  <https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python/issues/18>
- patchright-python #28 — CDP 连接后 `page.goto` `Cannot read properties of undefined`：  
  <https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python/issues/28>
- patchright #41 — `addInitScript` 被 Cloudflare 检测：  
  <https://github.com/Kaliiiiiiiiii-Vinyzu/patchright/issues/41>
- patchright #197 — WebView2/Edge 145+ `connect_over_cdp` + clock 导致 `ERR_NAME_NOT_RESOLVED`：  
  <https://github.com/Kaliiiiiiiiii-Vinyzu/patchright/issues/197>
- Playwright #43638 — `Target.attachedToTarget` 缺 `browserContextId` 导致未捕获 assertion：  
  <https://github.com/microsoft/playwright/issues/43638>
- Playwright #41093 — 未 commit 的 tab 导致 `connect_over_cdp` 挂起：  
  <https://github.com/microsoft/playwright/issues/41093>
- Playwright #39483 — connectOverCDP 后 page 对象 hollow/URL 为空：  
  <https://github.com/microsoft/playwright/issues/39483>

---

## 8. 附：本次实测原始输出

### 8.1 连接/context/close

```text
chrome pid 88204 alive True
version Chrome/156.0.8078.80
tab2 148C207F2E1C262DECA848B9921320C6
tab3 F3874F5FFD1925767C804CBC72F8ED60
contexts after connect: 1
pages after connect: 3 ['data:text/html,<title>tab2</title>tab2', 'about:blank', 'data:text/html,<title>tab3</title>tab3']
after context.new_page: contexts 1 pages 4
after browser.new_page: contexts 2 delta 1
after browser.new_context: contexts 3
after c2.close: contexts 2
closing CDP connection via browser.close()
after browser.close: chrome alive True
after browser.close: cdp version Chrome/156.0.8078.80
reconnect contexts: 1 pages: 4 ['data:text/html,<title>tab2</title>tab2', 'data:text/html,<title>newpage</title>newpage', 'about:blank', 'data:text/html,<title>tab3</title>tab3']
```

### 8.2 add_init_script

```text
before add: None
after add, existing document: None
after add + navigation (data: URL): None
pages: 1 contexts: 1
chrome alive True Chrome/156.0.8078.80
```

> 注意：这组实验只证明“1.58.2 + Chrome 156 的基本 CDP 路径可用”，不代表 Mimic 156 的所有页面/长时间行为；Mimic 专项仍需真机验证。
