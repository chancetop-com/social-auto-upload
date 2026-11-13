# 小红书账号风控能力对比

审阅日期：2026-11-13（Asia/Shanghai）。本项目基线：`71842898bf0fa1431db736abb3c8fc6d1397b3a9`；审阅开始时工作树干净。上游基线：`xpzouying/xiaohongshu-mcp@bb6fa2e208719ee634fec37881be29d3aa4699b3`。

范围是两者共有的**小红书图文、视频发布**，不会把当前项目其他平台的风控能力算到小红书上。这里的托管模式指 Multilogin X / AdsPower 的 Profile，由本机桌面应用启动，经 CDP 接管；不是“放在云服务器上”。上游 README 另行推荐的 `x-mcp` 浏览器插件不属于此次比较对象。

方法：源码及一手文档审阅，没有对真实账号进行发布或封禁率实验。下文的“更完整”指机制覆盖度，不能换算为实际封禁概率。上游源码依据另见 [上游专项研究](research/xiaohongshu-mcp.md)。

## 核心判断

1. **本项目本地模式与上游各有优势。** 当前本地模式已有 Patchright、人类化交互、登录状态持久化及发布异常保护；上游最新版已有内置指纹浏览器，不能按“普通 Rod 加几个 sleep”的旧印象判断。本地模式的优势主要在失败语义和会话写回，浏览器身份的一致性仍有验证缺口。
2. **本项目托管模式在持久身份与多账号隔离方面更完整。** 它使用已有 Profile，保持其中的浏览器状态及配置，避免本地路径重复创建临时上下文。这是架构优势，依赖 Profile 正确配置和调度侧履约，不是已经测出的防封率优势。
3. **两种本项目模式均不是完整的自动风控系统。** 账号串行、频次限制、失败冷却和熔断明确交给调用 App；不能仅凭 CLI 的人类化动作推导出频控保护已经存在。

## 对照表

下表是源码能力比较；本项目的逐项证据见后文，上游证据见紧接表格的说明。

| 维度 | 本项目本地模式 | 本项目托管模式 | xiaohongshu-mcp 当前版 |
| --- | --- | --- | --- |
| 自动化与指纹配置 | Patchright + Chromium + UA 改写 + stealth.js；组合一致性未验证 | 复用 MLX / AdsPower Profile；不再叠加本地 JS/UA 配置 | 内置指纹浏览器，固定并持久保存 seed；同步构造 UA / UA-CH，关闭 stealth JS |
| 默认显示方式 | CLI 默认有头 | 默认有头，传递给 provider | 服务默认无头，可改有头；显示方式本身不能证明防封强弱 |
| 会话连续性 | cookies + localStorage 的 storage_state；成功后原子写回；新建 context | 完整 Profile 中的状态持续保留 | cookies + seed 持久化；每次业务使用临时 userdata，常规发布结束不写回更新后的 cookies |
| 多账号隔离 | 按账号文件分离登录状态，不是每账号完整指纹 Profile | 按 Profile 分离身份及存储，可分别配置代理 | 一个服务实例一个全局会话配置；多账号依赖外部多实例部署 |
| IP/代理 | 小红书路径未提供专用代理参数，取决于运行环境网络 | 使用 Profile 代理；CLI 不管理或验证出口 | 有全局 XHS_PROXY 参数；没有按账号管理或验证出口 |
| 人类化动作 | 逐字输入、随机等待、曲线鼠标、落点复核；提交前停顿 | 与本地共用同一层 | 已接入逐字插入、随机等待与曲线鼠标；提交 widget 的动作覆盖略有不同 |
| 发布中登录/验证处理 | 多检查点；退出 10，区分是否已经派发 | 同左，并提示到对应 Profile 人工处理 | 有风险页分类函数，但当前接在搜索路径，发布链路未复用 |
| 发布结果不明 | 单次至多一次提交；退出 9 / publish_attempted 契约，禁止盲目重跑 | 同左 | 同样单次提交；未观察到跳转时为普通发布错误，没有同等结构化 unknown 契约 |
| 平台级限流、冷却、同账号锁 | CLI 不实现，交调用 App | 同左 | 未发现对应业务保护，需要调用方实现 |
| 封禁率证据 | 无可比较的长期对照数据 | 无可比较的长期对照数据；最新人类化验收未覆盖托管 | README 为作者经验，未提供可比较的防封率实验 |

## 上游当前版为何不能按旧版评估

### 指纹能力已经加强，但完整 Profile 仍未持久化

上游固定依赖 `headless_browser v0.4.0`，构造时选内置指纹浏览器、关闭 stealth JS，并设置语言与品牌。依赖的实际实现传入 fingerprint 相关启动参数，同时按浏览器版本构造 UA 与 Client Hints。可以确认这是运行路径上的机制，而非只有 README 宣传；不过依赖仓库没有完整 Chromium 补丁，本次未测试其所有指纹输出。来源：[上游构造器](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/browser/browser.go#L50-L100)、[依赖 UA/CH](https://github.com/xpzouying/headless_browser/blob/d28e37c7448672550580fca8ff26404aed09a21f/headless_browser.go#L259-L300)。

默认 seed 会保存到 cookies v2 文件并复用，不能说每次请求都随机更换身份。与此同时，它没有配置持久 user-data-dir，依赖默认临时目录且 Close 时删除；持久 seed 不等于完整 Profile。常规发布未保存刷新后的 cookies，本项目本地模式在 localStorage 恢复及成功后会话写回上更完整，托管模式则保留更完整的浏览器状态。来源：[seed 规则](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/configs/seed.go#L14-L43)、[请求生命周期](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/service.go#L278-L292)、[依赖关闭](https://github.com/xpzouying/headless_browser/blob/d28e37c7448672550580fca8ff26404aed09a21f/headless_browser.go#L311-L315)、[临时目录默认值](https://github.com/go-rod/rod/blob/01a50b925312b71fc59f6eb0d8f489a5195ec448/lib/launcher/launcher.go#L46-L62)。

单实例只有全局 seed / proxy / cookies 路径。`XHS_PROXY` 能传给浏览器，但不提供账号级网络身份管理，也不能等同于出口质量验证。默认服务无头可调整；本次不据此直接判定封禁风险。来源：[全局配置](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/configs/browser.go#L10-L60)、[默认无头](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/main.go#L16-L44)。

### 人类化接近，不能把随机延迟算成本项目独占优势

上游的逐字 InsertText、对数正态等待、贝塞尔鼠标轨迹、随机落点已经接入发布字段，并非未使用的工具类。本项目参数与其同源。实际差异是：上游新版发布 widget 使用固定相对位置的 ClickAt，缺少普通 Click 的随机落点及 PointerSettle；发布路径也未调用所定义的 BeforeSubmit。当前本项目 FIRE 明确调用提交前停顿及带复核的 Humanizer.click。两者都无法因此宣称动作不可检测。来源：[上游时间分布](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/humanize/provider.go#L25-L68)、[字段填写](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/publish.go#L385-L425)、[提交 widget](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/publish.go#L595-L634)、[本项目 FIRE](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uploader/xiaohongshu_uploader/main.py:644)。

### 发布异常保护是本项目的明确差异

上游已不是“点完按钮就成功”：也会等待最多 15 秒，看 URL 是否离开 `/publish/publish`。但它未排除登录或验证页；从条件推断，发布后跳到这类页面也可能报成功。上游存在 CheckPageBlocked，但当前调用覆盖集中在搜索，不能据此认为发布路径已有同等保护。来源：[上游成功判据](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/publish.go#L464-L477)、[搜索检查](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/search.go#L120-L133)。

双方每次发布都只做一次最终点击，不应说上游在不停重发。本项目多出的保护是跨 CLI / 调用 App 的错误语义：已提交但不确定时明确返回 9、点击后遇登录/验证则附 publish_attempted；上游归普通发布失败，没有同样的“先核对再重试”机器契约。这个差异有助于外部系统避免误重试，但外部系统仍必须遵守它。来源：[上游提交与等待](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/xiaohongshu/publish.go#L455-L499)、[上游 API 错误](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/handlers_api.go#L87-L122)。

上游未发现业务账号级锁、发布预算或冷却熔断；loginSessions 的 mutex 仅管理待扫码会话。README 中作者“未封号”和“每天 50 篇”的陈述属于经验，不能当作平台认可的安全额度或对照实验。来源：[扫码锁](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/login_session.go#L5-L42)、[作者经验](https://github.com/xpzouying/xiaohongshu-mcp/blob/bb6fa2e208719ee634fec37881be29d3aa4699b3/README.md#L293-L309)。

## 本项目：本地模式

### 浏览器与指纹

- 固定依赖 Patchright `1.64.4`，小红书上传器直接从 `patchright.async_api` 导入。实际路径是 `chromium.launch(channel="chromium")` 后 `new_context(storage_state=...)`；**没有使用每账号持久化 user-data-dir**。图文和视频各自启动自己的浏览器，不能只看通用 `browser_session` 的本地分支。来源：[依赖](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/pyproject.toml:14)、[视频路径](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uploader/xiaohongshu_uploader/main.py:2966)、[图文路径](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uploader/xiaohongshu_uploader/main.py:3175)。
- 通过 `_xhs_user_agent()` 读取真实浏览器 UA，再把 `HeadlessChrome` 替换为 `Chrome`；另设置 `zh-CN`、Accept-Language、定位权限，并注入 `stealth.min.js`。CLI 默认有头，也允许无头。来源：[UA](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uploader/xiaohongshu_uploader/main.py:1276)、[上下文参数](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uploader/xiaohongshu_uploader/main.py:471)、[脚本注入](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/base_social_media.py:21)、[默认有头](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/docs/CLI.md:188)。
- JS 脚本包含固定的 CPU 线程数及 WebGL vendor / renderer 默认值。这证明项目叠加了驱动补丁与 JS 属性修补；**不证明它与实际设备、UA-CH 等一定冲突，也不证明更安全**。需要浏览器实际观测才能判断。来源：[脚本](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/stealth.min.js:7)。Patchright 维护者推荐持久化 Chrome、有头、无指纹注入且不自定义 UA / headers；当前本地路径没有完整遵循这一推荐。该推荐同样不能当作小红书平台验证结果。来源：[Patchright 最佳实践](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python#best-practice---use-chrome-without-fingerprint-injection)。

新建上下文不等于“每次所有设备指纹都随机改变”。可以确定的是：Cookie / localStorage 可由 storage_state 恢复，但它不等于包含浏览器历史、缓存等状态的完整持久 Profile。当前项目没有展示本地配置和平台风控结果之间的对照实验。

本地配置暂不改造是已有明确决策，不能当成这次比较授权修改代码。来源：[本地浏览器配置决议](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.scratch/xhs-publish-reliability/issues/19-local-browser-hygiene.md:37)。

补充 Git 历史核查：注入来自原仓库普通 Playwright 阶段，2024 年提交明确说明“avoid detect”；2026 年小红书迁移到 Patchright 时保留。当前脚本与 2024 年公共化版本的 Git blob 完全相同。原仓库另有报告固定 CPU / WebGL 信息造成设备不一致的 PR，但该 PR 关闭且未合并，不能把报告当作本项目已完成的修复或封禁因果证明。见 [Git 历史与原仓库证据](research/stealth-git-history.md)。

### 会话与行为

- 发布前先检查本地会话 Cookie 是否存在、是否已知过期，不额外启动浏览器做网络预探测；成功后原子保存 storage_state。这个机制减少不必要的失败尝试，并保留更新后的会话。来源：[本地预检与原子写回](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uploader/xiaohongshu_uploader/main.py:1470)、[上传成功写回](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uploader/xiaohongshu_uploader/main.py:3198)。
- 默认启用逐字符输入、随机停顿、贝塞尔鼠标路径、随机落点与点击前目标复核；超出 1000 字符时会整段插入，`HUMANIZE=0` 可关闭。许多时间参数沿用上游，因此不应宣称本项目独有人类化技术。来源：[参数与开关](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/humanize.py:82)、[输入](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/humanize.py:218)、[点击](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/humanize.py:254)、[轨迹](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/humanize.py:371)。

## 本项目：托管模式

- `browser_session` 启动指定 Profile，经 CDP 取得已有的唯一 context；不会从本地 cookies 文件创建新 context。两种托管 provider 使用相同的小红书发布逻辑，因此仍保留上述人类化交互及下述异常保护。来源：[托管 session](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/browser_session.py:323)、[小红书托管入口](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/sau_commands/xiaohongshu.py:348)。
- 连接使用 `no_defaults=True`，跳过本地 launch/context/init-script 参数。UA、指纹、时区、定位和代理依赖 Profile 本身；不是把本地 stealth.js 再叠加到指纹浏览器上。来源：[连接](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/browser_session.py:380)、[模式分流](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/browser_session.py:198)。
- AdsPower 启动参数明确为 `delete_cache="0"`、`cdp_mask="1"`；同时 `proxy_detection="0"`。这说明代码保留缓存并请求 CDP 掩蔽，**不能说明实际代理出口已验证或一定合适**。来源：[AdsPower 启动参数](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/adspower.py:213)。
- Profile 的创建、代理管理和参数维护不属于该 CLI。Profile 隔离不等于 IP 自动隔离，也不等于目标平台账号正确绑定。项目只检查登录状态；同一 Profile 的串行由调度 App 保证。来源：[调度责任与部署边界](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/docs/CLI.md:241)。
- 当前证据不足以给 Multilogin 与 AdsPower 排“谁更不容易封号”。它们共享 CLI 行为与错误契约，浏览器内核及配置效果则需要各自真机验证。

## 两种本项目模式共用的保护与缺口

### 对异常的处置优于盲目重试

发布路径在导航、上传、提交前后检查登录/验证状态。已识别状态退出 `10`，发布后发现异常会标记 `publish_attempted=true`。提交拆成 ARM / FIRE / OBSERVE：只在就绪阶段重试检查，FIRE 单次运行至多派发一次点击；派发后未确认成功返回 `9`，约定必须先核对帖子，禁止自动重发。来源：[分类规则](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uploader/xiaohongshu_uploader/main.py:487)、[FIRE](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uploader/xiaohongshu_uploader/main.py:644)、[OBSERVE](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uploader/xiaohongshu_uploader/main.py:687)、[调用契约](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/docs/CLI.md:241)。

这是一层发布可靠性与风险止损机制，不是使自动化不可检测的机制。保护只保证本次调用不会继续点击，不包含跨进程、跨次调用的持久幂等记录；调用 App 若忽略 `9` 或点击后的 `10` 而重跑，保护仍会失效。

### 检测覆盖有限

小红书分类依赖 `/login`、`/website-login`、`/website-login/captcha` 与登录框可见性。它不是任意滑块、弹窗、封号提示或平台业务错误码的完整检测器。页面读取失败时分类器可返回 None。来源：[小红书规则](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uploader/xiaohongshu_uploader/main.py:487)、[共享分类器](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/blocked.py:42)。

发布后只观察 URL：排除已识别的登录/验证页后，离开 `/publish/publish` 即算成功。因此仍有将未识别错误页当成功的可能，也没有帖子 ID、作品列表等自动对账。15 秒仍在发布页则是结果未知，不能区分平台明确拒绝、限流与慢成功。项目已明确决定不扫描“操作频繁”等提示文案。来源：[结果观察](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/uploader/xiaohongshu_uploader/main.py:687)、[提示处理决议](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.scratch/xhs-publish-reliability/issues/04-rate-limit-and-rejection.md:20)。

### 频控与并发属于外部依赖

CLI 没有默认账号发布间隔、日限额、失败冷却、连续失败熔断或同账号进程锁；这些是明确留给调用 App 的职责。`--not-before` 是本次提交的时间闸门，不是账号级节流器。来源：[调度责任](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/docs/CLI.md:241)、[频控决议](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.scratch/xhs-publish-reliability/issues/18-publish-pacing.md)。

退出 `11` 的 HTTP 429 来自 Multilogin Launcher / AdsPower Local API。它保护的是浏览器管理接口，不代表已经识别小红书平台限流。来源：[错误定义](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/errors.py:45)、[AdsPower 检查](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/utils/adspower.py:167)。

## 效果证据的边界

本仓 2026-11-12 人类化验收记录覆盖本地有头模式的发布前干跑，明确没有验托管模式，也没有在该轮实际点击发布。几个流程没有遇到验证码只能证明这几次流程可运行，不能证明长期封禁率或哪种方案更安全。来源：[验收范围](/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.scratch/humanize-rollout/acceptance.md:3)。

实际系统的判断还缺少调用 App 的频控/互斥实现、Profile 配置与网络出口、真实内容和账号历史、长期平台结果。未审阅这些外部条件，不能给出“每天多少篇安全”、封禁概率百分比或无条件的整体排名。
