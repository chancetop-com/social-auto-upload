# 持久化 Profile 生命周期与兼容性依据

核对日期：2026-11-17。为[本地 Profile 的生命周期与并发占用](../issues/03-profile-lifecycle-and-concurrency.md)提供外部事实；不是实施结果或已批准的产品政策。未安装、启动或修改用户浏览器，未验证真实账号。

## 会话与并发

- `launch_persistent_context(user_data_dir)` 返回该浏览器唯一的持久化 context；关闭它会关闭对应浏览器。同一 user data directory 不允许同时启动多个浏览器实例。[Playwright API](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context)
- 同一 context 可以创建多个页面；通过 CDP 连接已有 Chromium 浏览器也是另一种架构，但需要独立协调跨命令的资源所有权和页面操作。它不使重复 launch 同一目录变得可行。[多页面 API](https://playwright.dev/python/docs/api/class-browsercontext#browser-context-new-page)、[CDP 连接 API](https://playwright.dev/python/docs/api/class-browsertype#browser-type-connect-over-cdp)
- Patchright 提供 Playwright 的替代实现并引用其 API 文档；具体实现仍需对项目锁定版本验证。[Patchright API 说明](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python#documentation-and-api-reference)
- 应用层互斥只能协调遵守同一协议的项目进程，不能替代浏览器对用户手动打开的实例所做的目录占用处理。Chromium 的 POSIX singleton 代码包含向既有进程转发请求及无响应时恢复的分支；不能把“应用不主动删锁或杀其他进程”扩大成“底层浏览器永不处理锁或进程”。[Chromium singleton 实现](https://raw.githubusercontent.com/chromium/chromium/main/chrome/browser/process_singleton_posix.cc)

## 浏览器与版本切换

- Chromium 的数据政策支持新版本读取旧版本数据；降级不具有同样的完整保证，同一 release branch 内才有更明确的逆向读取保证。不兼容缓存可能被重建。[User Data Storage](https://chromium.googlesource.com/chromium/src/+/main/docs/user_data_storage.md)
- 默认数据目录按操作系统、品牌和渠道区分；此资料没有提供 Chrome 与 Chromium 共用同一目录的完整登录态兼容保证。[User Data Directory](https://chromium.googlesource.com/chromium/src/+/main/docs/user_data_dir.md)
- 敏感数据依赖操作系统凭据保护；Windows App-Bound 加密还关联应用身份与机器。因此不能承诺任意替换可执行文件或跨机器复制目录后 Cookie 都可用。[Chrome Cookie 加密说明](https://security.googleblog.com/2024/07/improving-security-of-chrome-cookies-on.html)

推论：正常升级可按浏览器的原生机制继续；跨浏览器、任意路径切换或降级是否允许尝试沿用目录，是需要用户明确选择的支持政策。无论选择什么，都不应声称已经证明无损兼容或能自动回滚。

## 持久化验收

- context 的关闭 API 与关闭事件没有承诺下一次平台认证必然成功；关闭事件也可来自浏览器崩溃。[关闭 API](https://playwright.dev/python/docs/api/class-browsercontext#browser-context-close)、[关闭事件](https://playwright.dev/python/docs/api/class-browsercontext#browser-context-on-close)
- 关闭后重新启动并验证，是可以选择的迁移验收策略，不是 Playwright 强制要求。它能证明当时不借助旧 JSON 可以恢复登录，不能保证未来会话永久有效。是否作为删除旧 JSON 的前置条件由决策票确认。

## 来源与版本记录的限制

- `browser.version` 提供版本；CDP `Browser.getVersion` 的 product 字段不能单独证明品牌，Chromium 实现也会生成 `Chrome/<version>`。[版本 API](https://playwright.dev/python/docs/api/class-browser#browser-version)、[Chromium product 实现](https://raw.githubusercontent.com/chromium/chromium/main/components/version_info/version_info_with_user_agent.cc)
- `browser_type.executable_path` 是预计的配套浏览器路径，不是当前 channel 或自定义路径的可靠实际运行路径。[executable_path API](https://playwright.dev/python/docs/api/class-browsertype#browser-type-executable-path)
- `Browser.getBrowserCommandLine` 要求 `--enable-automation`，而 Patchright 默认移除此参数，不能为获取诊断信息擅自改回启动参数。[CDP 协议](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/json/browser_protocol.json)、[Patchright 参数说明](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python#command-flags-leaks)

推论：应区分生效的启动来源、用户指定/解析出的路径、浏览器报告的版本和可证实的产品信息。无法查明的实际路径或品牌明确记为未知，不从配置名或 UA 猜测；启动后的版本记录也不是打开 Profile 前的降级防护。

### 打开既有 Profile 前识别产品

- 未被自定义路径覆盖的标准 channel 可提供已知产品种类；自定义路径必须按最终选中的 executable 判断，不能继续沿用被覆盖的选择值。
- macOS / Linux 可调用所选 executable 的 `--version`，产品名前缀来自构建的 `PRODUCT_FULLNAME_STRING`；官方代码在基本启动阶段返回，早于用户数据目录初始化。参数应独立传递、设置有限超时，不传任何账号 Profile 路径。[Chromium 启动源码](https://raw.githubusercontent.com/chromium/chromium/main/chrome/app/chrome_main_delegate.cc)
- Windows 可直接读取 exe 的 VERSIONINFO `ProductName`，无需启动浏览器；Chromium 模板以 `PRODUCT_FULLNAME` 填入该字段。没有版本资源或识别失败不证明产品种类。[资源模板](https://raw.githubusercontent.com/chromium/chromium/main/chrome/app/chrome_version.rc.version)、[Microsoft ProductName 文档](https://learn.microsoft.com/en-us/dotnet/api/system.diagnostics.fileversioninfo.productname)
- Chromium branding 使用 `Chromium`，Google Chrome 的官方参考构建使用 `Google Chrome`。这可区分普通发行包，不构成对任意伪装可执行文件的安全认证。[Chromium branding](https://raw.githubusercontent.com/chromium/chromium/main/chrome/app/theme/chromium/BRANDING)、[Google Chrome branding](https://chromium.googlesource.com/chromium/reference_builds/chrome_linux64/+/5186d1b279358de0d9a581399281f2268932cd37/installer/theme/BRANDING)
- Windows 的 `--version` 支持有版本差异，不能简单写成永远不支持或所有版本都支持。未知 wrapper、修改 branding 的构建或读取失败应保留 unknown，不猜测、不自动删除任何 Profile。

以上为源码与文档核对，未实际启动项目固定版本或自定义浏览器；实现时仍需对受支持系统验证识别路径。
