# 02 — patchright 1.58.2 与 Mimic CDP 的兼容性

Status: resolved
Type: research
Blocked by: —
Assignee: —

## Question

项目使用 `patchright==1.58.2`（Playwright 的防检测分支），Multilogin 的 Mimic 内核官方示例用的是上游 `playwright`。需要确认 MLX 模式下能否直接复用现有补丁版客户端：

1. `patchright.async_api.async_playwright().chromium.connect_over_cdp(url)` 是否可用？与上游 `connect_over_cdp` 有无差异？
2. `connect_over_cdp` 连接到 Mimic 后，`browser.contexts[0]` 是否**一定存在**？是否可能返回空数组？是否存在多个 context？
3. `browser.close()` 的语义：在 CDP 连接下是“断开连接”还是“关闭浏览器/Profile”？官方示例先 `browser.close()` 再调 Stop，是否能确认不会提前杀掉浏览器？
4. `context.new_page()` 是否安全？会不会触发新 context？
5. `context.add_init_script()` 对**已存在**的 context/页面是否生效？现有 `utils/base_social_media.py::set_init_script` 在 MLX 模式是否应跳过？
6. `context.storage_state()` / `browser.new_context(storage_state=...)` 在 MLX 模式下必须不调用；还有哪些 Playwright 调用会隐式创建 context 或覆盖 cookie？
7. CDP 协议版本 / Chromium 内核版本兼容性：patchright 1.58.2 对应的 Chromium 版本与 Mimic 最新 core 是否兼容？官方 release notes 有无说明？
8. 已知问题：patchright 的 stealth 注入与 Mimic 自带指纹是否冲突？是否会触发 `Target.attachToTarget` / `Runtime.evaluate` 类错误？
9. 如果要**只读**验证登录态，推荐用 `context.pages[0]` 还是 `context.new_page()`？新页面是否会破坏现有页面状态？
10. `browser.contexts[0]` 内是否已经包含用户手动打开的标签页？上传流程能否复用已有页面？

## Context

- 当前依赖：`pyproject.toml` → `patchright==1.58.2`。
- 现有 CDP 用法只出现在登录流程：`uploader/douyin_uploader/main.py:273`、`uploader/ks_uploader/main.py:289`，都是 `connect_over_cdp(cdp_url)` + `browser.contexts[0]`。
- 官方 Playwright 示例：<https://multilogin.com/help/en_US/puppeteer-selenium-and-playwright/playwright-automation-example>
- Multilogin release notes：<https://multilogin.com/release-notes/>

产物写到 `.scratch/multilogin-browser-mode/research/02-patchright-mimic-cdp.md`，要求：

- 区分“官方文档/源码可证”“社区报告”“推断”；
- 给出 `browser_session` 在 MLX 分支里**允许调用**与**禁止调用**的 Playwright API 清单；
- 如果存在版本不兼容，给出最低可行版本或切换上游 playwright 的建议。

## Answer

详见 [research/02-patchright-mimic-cdp.md](../research/02-patchright-mimic-cdp.md)。要点：

- `patchright 1.58.2` 的 `connect_over_cdp` 可用，API 与上游同签名；但驱动补丁（`Page.enable` 顺序、init-script 路由注入、Console/Runtime 补丁）会改变 attach 行为。
- 正常 profile 连接后只有 1 个 context，`contexts[0]` 即默认 context；**可能多于 1 个**（此时索引顺序不保证），**不应为空**。MLX 分支遇到空数组必须 fail-fast，绝不能 fallback `new_context()`。
- `browser.close()` 在 CDP 下**只断开 WebSocket**，不关闭 Chrome/Profile；官方示例也是 close 后再 Stop。`context.close()` 不应用于 MLX。
- `context.new_page()` 安全（不建 context），但会在 Profile 留下真实 tab；应优先按 URL 复用已有 page，其次 `pages[0]`，最后才新建并负责关闭。
- `add_init_script` 在 1.58.2 通过 `**/*` 路由改写 HTML 注入，只影响后续 http(s) 文档；本仓库 `utils/stealth.min.js` 会覆盖 webdriver/plugins/WebGL 等，与 Mimic 指纹直接冲突。**MLX 分支必须跳过 `set_init_script`**。
- 禁止清单：`browser.new_context()`、`browser.new_page()`、`storage_state()`、`add_cookies()`、`clear_cookies()`、`context.add_init_script()`、`context.route()`、`grant_permissions()`、`set_geolocation()`、`set_extra_http_headers()`、`emulate_media()`、`set_viewport_size()`、`page.clock` 等（完整表见研究文件 3.2）。
- 版本风险：1.58.2 对应 Chromium 145，Mimic 最新 core 是 156；官方无兼容声明。建议至少 `patchright>=1.62.1`（修 CDP `Frame was detached` 崩溃），首选 `1.64.1`（Chromium 156，支持 `no_defaults=True`）。是否升级另开 ticket 11 决定。

**对设计的直接影响：** 采用研究文件 3.1 的允许清单；`browser_session` 的 MLX 分支不接收 `launch_kwargs`、不调用 `set_init_script`、不写 `storage_state`；page 选择单独封装。
