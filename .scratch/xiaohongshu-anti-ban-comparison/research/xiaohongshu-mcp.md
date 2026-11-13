# xiaohongshu-mcp 当前防风控相关实现核查

核查日期：2026-11-13。只做源码研究，没有登录账号、发布内容或运行平台风控实验。

## 范围与版本

- 上游 `xpzouying/xiaohongshu-mcp` main 固定为 [`bb6fa2e208719ee634fec37881be29d3aa4699b3`](https://github.com/xpzouying/xiaohongshu-mcp/commit/bb6fa2e208719ee634fec37881be29d3aa4699b3)，提交时间 2026-11-11 01:43:13 +08:00。不是 README 推荐的另一个浏览器插件 `x-mcp`。
- 主项目固定依赖 `go-rod/rod v0.116.2`、`xpzouying/headless_browser v0.4.0`，`go-rod/stealth v0.4.9` 虽列为间接依赖，但不能由此认定运行时启用 stealth JS。[依赖声明](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/go.mod#L5-L30)
- `headless_browser v0.4.0` 解析为 [`d28e37c7448672550580fca8ff26404aed09a21f`](https://github.com/xpzouying/headless_browser/commit/d28e37c7448672550580fca8ff26404aed09a21f)；Rod v0.116.2 解析为 [`01a50b925312b71fc59f6eb0d8f489a5195ec448`](https://github.com/go-rod/rod/commit/01a50b925312b71fc59f6eb0d8f489a5195ec448)。下列行号来自这些提交的原始文件。

## 结论摘要

当前上游已经具备默认指纹浏览器、持久 seed、UA/Client Hints 一致性处理、实际调用中的人类化动作和搜索风控页识别，不能按旧印象描述为“普通 Rod、固定 sleep、仅 cookies、无任何反检测”。但它仍是单会话配置、每次业务请求新建临时浏览器、主要持久化 cookies 与 seed；没有账号级发布锁、频率预算、风控冷却或发布幂等协议。发布成功判据过宽，也没有把搜索路径上的风控识别复用到发布路径。以上是工程能力核查，不是封号概率测量。

## 浏览器、指纹、默认配置

服务默认 `-headless=true`，允许显式有头。主项目强制 `EnsureBrowser()` 返回的内置二进制，不允许缺失时悄悄退回普通 Chromium；其构造器启用 Fingerprint、关闭 `StealthJS`、设置 `zh-CN` 和 Chrome 品牌。浏览器版本文件为 `148.0.7778.215`，从项目指定 CDN 下载并校验 SHA256。[入口默认](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/main.go#L16-L44)、[主构造器](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/browser/browser.go#L50-L100)、[版本](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/browser/browser_version.txt#L1)、[下载及校验](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/browser/browser_download.go#L24-L35)

依赖中存在真实执行逻辑：把 `fingerprint=<seed>`、`fingerprint-platform=<platform>` 及额外品牌 flag 写入 launcher；macOS 选择 `macos`，其他系统选择 `windows`。因此，“传入指纹启动参数”已由代码证实，不只是注释。[依赖启动逻辑](https://github.com/xpzouying/headless_browser/blob/d28e37c7448672550580fca8ff26404aed09a21f/headless_browser.go#L168-L224)

依赖还调用 `Browser.getVersion` 获取真实版本，构造 `NetworkSetUserAgentOverride`，回填 UA、brands、fullVersionList、uaFullVersion 和 Accept-Language，并在每个新页执行；平台字段留给浏览器自身补丁。[UA/CH 构造](https://github.com/xpzouying/headless_browser/blob/d28e37c7448672550580fca8ff26404aed09a21f/headless_browser.go#L259-L300)、[逐页应用](https://github.com/xpzouying/headless_browser/blob/d28e37c7448672550580fca8ff26404aed09a21f/headless_browser.go#L317-L334)

证据边界：依赖注释称其为 CloakBrowser 源码级指纹引擎；本次确认了指定二进制的下载、启动 flags、UA/CH 协调，但这两个仓库不含完整 Chromium 补丁源码，本次也没有运行该二进制检查 Canvas/WebGL/Audio/WebRTC 等输出。可以说“默认指纹浏览器集成更系统”，不能仅凭 flags 声称所有指纹面已经独立验证，更不能推导实际防封率。

## 身份连续性、cookies、profile、多账号

默认 seed 并非每次请求随机：启动时按 `XHS_FP_SEED > 会话文件 seed > 新生成并保存` 解析一次。会话文件 v2 包含 `version/seed/saved_at/cookies`，登录程序与服务共用路径和解析逻辑。因此 seed 与 cookies 可在重启后保持一致，前提是会话文件正常保留且写入成功。[seed 规则](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/configs/seed.go#L14-L43)、[会话结构及保存](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/cookies/cookies.go#L12-L31)、[登录入口](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/cmd/login/main.go#L19-L26)

主项目为图文、视频、搜索等业务请求各自 `newBrowser()`，操作后 `Close()`；依赖使用 `launcher.New()`，没有配置持久 UserDataDir，关闭时调用 `Cleanup()`。Rod 默认生成随机临时 userdata 目录，Cleanup 删除它。因此正常默认路径保留的是文件中的 cookies 与 seed，未持久复用完整 profile、localStorage、IndexedDB 或缓存。[图文实例生命周期](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/service.go#L278-L292)、[依赖创建](https://github.com/xpzouying/headless_browser/blob/d28e37c7448672550580fca8ff26404aed09a21f/headless_browser.go#L179-L187)、[依赖关闭](https://github.com/xpzouying/headless_browser/blob/d28e37c7448672550580fca8ff26404aed09a21f/headless_browser.go#L311-L315)、[Rod 默认目录](https://github.com/go-rod/rod/blob/01a50b925312b71fc59f6eb0d8f489a5195ec448/lib/launcher/launcher.go#L46-L62)、[Rod 删除目录](https://github.com/go-rod/rod/blob/01a50b925312b71fc59f6eb0d8f489a5195ec448/lib/launcher/launcher.go#L550-L556)

生产代码中 `saveCookies` 的调用只有服务扫码成功、独立 login 程序登录完成；常规浏览/发布结束没有刷新 cookies 落盘。创作者中心会话缺失时会打开首页等待 `galaxy_creator_session_id`，这是当前临时浏览器内的会话建立，并未在发布收尾保存。[扫码后保存](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/service.go#L177-L205)、[登录后保存](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/cmd/login/main.go#L45-L53)、[通用构造与存储函数](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/service.go#L626-L656)、[creator session](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/creator_session.go#L18-L49)

一个服务实例只有一个全局 seed、一个全局 proxy 与一个 `COOKIES_PATH`，请求没有 account/profile 标识。可通过不同进程、目录/端口、cookies 路径和代理做部署级隔离，但这属于外部配置，不是内置多账号管理或账号锁。[全局配置](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/configs/browser.go#L10-L60)、[cookies 路径优先级](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/cookies/cookies.go#L127-L148)、[发布请求结构](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/service.go#L21-L42)

## 代理

`XHS_PROXY` 进入浏览器构造器，依赖实际调用 `l.Proxy(cfg.Proxy)`；没有根据账号自动分配代理、IP 信誉校验或出口稳定性验证。README 给出带用户名密码的代理例子，但依赖注释明确 Chrome proxy-server 不支持嵌入认证，且实际调用链只传原值，本次未发现页面级认证处理。因此只确认普通代理传参能力，带认证代理是否可用应单独实测。[配置](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/configs/browser.go#L50-L60)、[依赖认证限制](https://github.com/xpzouying/headless_browser/blob/d28e37c7448672550580fca8ff26404aed09a21f/headless_browser.go#L112-L123)、[实际代理传入](https://github.com/xpzouying/headless_browser/blob/d28e37c7448672550580fca8ff26404aed09a21f/headless_browser.go#L219-L224)

## 人类化动作：已实现，也接入实际业务

`humanize` 默认采用有上下限的对数正态等待，含输入间隔 30–400 ms、点击按住 45–250 ms、导航后 600 ms–6 s 等分布。鼠标三次贝塞尔轨迹、随机控制点、缓动、10–40 步；普通 Click 有元素内随机落点、移动后停留和按住时长。Type 逐 Unicode rune 调用 CDP InsertText，并随机等待；它不等同于完整真实键盘/中文输入法事件链。[时间分布](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/humanize/provider.go#L25-L68)、[轨迹](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/humanize/mouse.go#L36-L100)、[点击](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/humanize/input.go#L107-L132)、[输入](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/humanize/input.go#L247-L278)

调用覆盖图文/视频标题正文、标签、评论、搜索筛选、点赞收藏等，不能说它只是未接入的工具文件。发布也仍混有固定 sleep；定义了 BeforeSubmit 分布不代表图文/视频提交前会调用它（生产使用处主要是通知回复）。新版发布 widget 选固定相对坐标 x=65%/y=50%，走 ClickAt；它有曲线路径与按住延时，但没有普通 Click 的随机落点和 PointerSettle。因此不宜说“每个动作都完整人类化”。[图文填写](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/publish.go#L385-L425)、[视频填写](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/publish_video.go#L108-L138)、[widget 点击](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/publish.go#L595-L634)、[ClickAt](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/humanize/input.go#L237-L245)

## 并发、频控、冷却与重试

未发现账号级发布互斥、队列、每日预算、token bucket、风控后冷却/熔断。唯一生产 `sync.Mutex` 在 `loginSessions`，只保证一个待扫码登录会话，不能当作普通业务请求锁；路由直接进入服务，每个请求独立开浏览器。[扫码锁范围](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/login_session.go#L5-L42)、[路由](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/routes.go#L47-L70)、[发布调用链](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/service.go#L278-L292)

存在局部 DOM/导航重试与抖动，也有点赞收藏状态核验后最多再点一次；这些不是账号风控退避策略。图文/视频最终发布只调用一次 clickPublishButton，没有内部整单自动重发。但是调用方重放整个 MCP/API 请求没有幂等键、去重记录或 publish_attempted/unknown 结构化契约阻止重复发布。[局部重试](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/feed_detail.go#L108-L126)、[点赞收藏重试](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/like_favorite.go#L69-L88)、[发布一次点击](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/publish.go#L455-L499)

## 风控/验证码检测与发布结果

`CheckPageBlocked` 实际存在：读取主框架 URL pathname，将 `/website-login/captcha[/...]` 与 `/website-login[/...]` 分为安全验证、登录失效。错误提示建议用户用手机 App 扫码核验；没有自动破解验证码。读不到 URL 时直接返回 nil。[检测规则与调用](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/page_check.go#L14-L68)、[错误文案](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/errors/errors.go#L8-L16)

关键覆盖缺口：该函数生产调用局限于 search.go/search_ready.go；图文/视频发布的导航、输入、提交和成功等待没有调用它。搜索能返回相对明确的风险类型，不等于发布具备同等保护。[搜索检查](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/search.go#L120-L133)、[图文初始化](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/publish.go#L74-L105)、[视频提交](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/publish_video.go#L161-L171)

当前版本不再是“点击无报错就成功”：图文与视频都等待 15 秒，直到 URL 不含 `/publish/publish`。但是此判据没有校验目标 host/path、没有排除登录/验证码页、没有平台发布响应或笔记 ID 证据；据代码推断，跳去这些页面也会被判成成功。若提交已发生但未观察到跳转，返回普通错误，API 归类 `PUBLISH_FAILED`/`PUBLISH_VIDEO_FAILED`，没有单独的“结果未知、禁止自动重试”状态。[成功判据](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/publish.go#L464-L477)、[API 结果](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/handlers_api.go#L87-L122)

## 作者经验不等于可验证的防封效果

README 提供作者长期使用未封号的经验陈述、每天 50 篇的实操说法以及避免同账号多网页端登录的建议。这些没有对照样本、账号分层、统一环境、流量/内容/账号历史控制或公开封禁统计；不得作为平台安全额度或两项目封号概率排序依据。README 对“常用浏览器、本地网络、无服务器 IP 风险”的宣传属于独立 `x-mcp` 插件，不应移植给本次核查的 Go MCP 服务。[作者运营及风险经验](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/README.md#L293-L309)、[独立插件说明](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/README.md#L20-L25)

## 与当前项目比较时适用的表述

以下仅是本研究向主比较提供的上游基准，本文件没有独立检查本仓实现：

- 本地模式应拆开比较指纹、会话持久化、动作模拟、发布失败保护，不能仅用 Playwright/Patchright vs Rod 工具名判断谁更难检测。
- 托管 profile 的完整存储与账号隔离，相对上游 cookies+seed+临时 profile 是明确可比较的架构维度；真实内核质量、代理出口和最终账号风险仍依赖实际环境与测量。
- 上游默认指纹浏览器集成、seed 持久化和 UA/CH 协调已经比较系统；普通本地 UA/JS 修改不能直接宣称覆盖等价。
- 上游 humanize 已真实进入发布路径，随机延迟本身不是差异；覆盖面、使用的输入协议与最终提交安全才有比较价值。
- 如果本仓已有发布风险页识别、提交一次及 unknown 状态，属于发布失败保护上的实际差异；这不等于保证不封号。
- 两边若都没有账号锁、频控预算与风险后冷却，则不能把这项写成任何一方已实现的优势。
