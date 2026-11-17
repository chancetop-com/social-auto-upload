# 本地浏览器持久化 Profile 迁移

Status: ready-for-agent
Date: 2026-11-17
Source: [决策地图](./map.md)

## Problem Statement

目前本地浏览器流程依赖 Cookie JSON 恢复和导出登录态，登录、检查、发布与作品管理又分散在共享会话和平台独立启动入口中。用户无法只配置一次浏览器和账号别名，就确保所有动作使用同一份完整浏览器资料；部分内部检查还会忽略用户选择的有头/无头模式。

用户希望保留 Patchright，以原生 Chrome 的专用持久化 Profile 作为默认本地运行方式，同时按需使用 Chromium 或已有的自定义可执行文件。当前固定窗口、语言修改、stealth、UA 和请求头覆盖不符合这一运行方式。旧身份旁文件还把部分账号别名固定到真实账号，与“别名只用于管理资料、可以重新登录其他账号”的需求冲突。

迁移必须覆盖正式 CLI 的全部本地浏览器调用链，保持发布结果和禁止自动重发的契约，并允许五批交付期间尚未迁移的平台继续工作。旧 Cookie 资料只需处理一次，用户明确要求迁移后移除相关代码，避免常规登录和会话永久承担兼容旧状态的职责。

## Solution

为每个平台、账号别名和实际浏览器种类维护一个项目专用的本地浏览器 Profile。登录、检查、发布和作品管理复用这一 Profile；Cookie、站点存储与浏览器偏好由浏览器保存。默认选择 Chrome、有头运行且不固定 viewport，允许显式选择 Chromium、自定义路径和无头模式，失败时给出实际来源的诊断。

只有 login 引导登录。其他依赖登录的动作在 Profile 尚未建立或平台明确未登录时结束并提示 login；网络、页面结构和浏览器运行故障单独报告。同一别名可以重新登录任意真实账号，Chrome 与 Chromium 可以使用不同账号；显式发布目标及历史作品核验继续生效。

旧账号在一次性迁移阶段重新登录，不导入旧 Cookie。通过关闭、同配置重开、登录复验和再次正常关闭后，定向删除对应旧资料，不留备份。迁移完成即删除这套旧资料识别、复验、清理和重试代码；后续命令只使用 Profile。永久保留的 reset-profile 只负责用户明确指定的一个本地 Profile 重建。

按既定五批交付。每批由 Agent 执行相关离线回归，第一批执行无平台账号的真实浏览器验证，五批完成后执行四个指定平台的真实 no-publish 回归。MLX / AdsPower 只采用已批准的 headless 默认来源调整，以及下述 24 追加要求指定的 no-publish 成功摘要，其余行为保持原契约。

## User Stories

1. As a local CLI user, I want Chrome to be the default browser, so that I can reuse a standard browser installation.
2. As a local CLI user, I want to select Chromium explicitly, so that I can use the browser supplied for the project's Patchright version.
3. As a local CLI user, I want my custom executable path to take precedence, so that the application runs the browser I selected.
4. As a local CLI user, I want only my selected browser to be required, so that installing an unused browser is unnecessary.
5. As a local CLI user, I want launch failures to identify the selected source, so that I can fix the actual installation or configuration problem.
6. As a local CLI user, I want failed launches to stop without switching browsers, so that my choice and Profile remain predictable.
7. As a local CLI user, I want headed operation by default, so that I can observe the browser and complete login interactions.
8. As a local CLI user, I want explicit headed or headless flags to override configuration, so that I can control each invocation.
9. As an existing user, I want my configured headless default to remain effective, so that upgrading does not silently discard my preference.
10. As an uploader caller, I want omitted and explicit browser options to have consistent meanings, so that direct calls and CLI calls behave alike.
11. As a local CLI user, I want internal checks to use the same browser configuration as the requested action, so that hidden launches do not behave differently.
12. As a local CLI user, I want dedicated automation Profiles, so that automation does not modify my everyday browser profile.
13. As an account operator, I want readable account aliases in Profile directories, so that I can identify the browser data I manage.
14. As an account operator, I want unsafe or colliding aliases to fail clearly, so that distinct aliases cannot silently share browser data.
15. As an account operator, I want each platform and alias to have isolated data, so that one account's session does not affect another.
16. As an account operator, I want Chrome and Chromium to have separate Profiles, so that switching browser kinds does not mix their state.
17. As an account operator, I want changes within the same browser kind to reuse its Profile, so that changing a path or headed mode does not force a rebuild.
18. As an account operator, I want an unidentifiable executable to be rejected before opening a Profile, so that the application cannot guess which data to use.
19. As a Facebook operator, I want Facebook and Facebook Page to remain isolated, so that their existing account separation is preserved.
20. As a Facebook Page operator, I want multiple Page targets to use the selected Page login Profile, so that each target does not require another login container.
21. As a local CLI user, I want browser state to persist across sessions, so that later commands can reuse my login.
22. As a local CLI user, I want only login to guide authentication, so that business commands do not pause and resume through an unexpected login flow.
23. As a local CLI user, I want missing or expired login state to produce a distinct result, so that I know when to run login.
24. As a local CLI user, I want network and page failures to remain distinguishable from login expiry, so that I can choose the appropriate remedy.
25. As a local CLI user, I want verification challenges to retain their existing reason and guidance, so that I can resolve the actual challenge.
26. As an account operator, I want to log into another real account under the same alias, so that aliases remain organizational labels.
27. As an account operator, I want Chrome and Chromium under one alias to allow different real accounts, so that their independent sessions remain usable.
28. As a content publisher, I want explicitly requested targets and names to be checked, so that my current request is honored.
29. As a content operator, I want historical works to retain their original author and target checks, so that changing an alias's login cannot reinterpret old results.
30. As an existing user, I want to establish Profile login without importing old Cookie JSON, so that the new browser becomes the sole session source.
31. As an existing user, I want old data removed only after a successful restart verification during migration, so that cleanup follows evidence that the Profile can restore login.
32. As an existing user, I want migration cleanup to affect only the selected platform and alias, so that other accounts and historical results remain intact.
33. As an existing user, I want failed migration cleanup to report remaining work, so that I can resolve it without losing the valid new Profile.
34. As a maintainer, I want old-data migration code removed after the one-time migration, so that normal commands carry no permanent legacy migration behavior.
35. As a local CLI user, I want old files that reappear after migration to be ignored, so that they cannot trigger additional restarts or cleanup.
36. As an account operator, I want concurrent commands for one Profile to fail immediately, so that they cannot race over its state.
37. As an account operator, I want different Profiles to operate concurrently, so that unrelated accounts are not unnecessarily serialized.
38. As an account operator, I want stale lock records distinguished from live ownership, so that abandoned diagnostic files do not permanently block a Profile.
39. As an account operator, I want external browser ownership reported without forcibly taking over, so that another browser session is not disrupted.
40. As a local CLI user, I want owned resources cleaned up after errors and cancellation, so that failed commands do not intentionally leave browser resources behind.
41. As a content publisher, I want cleanup failures to preserve the primary publication result, so that a successful or uncertain submission is not treated as safe to repeat.
42. As a content publisher, I want crashes, relogin and Profile rebuilds to preserve the no-automatic-resubmission rule, so that recovery cannot create duplicate posts.
43. As an account operator, I want to reset one explicitly selected browser Profile, so that I can recover its state without deleting another browser's data.
44. As an account operator, I want reset-profile to work without launching a browser, so that I can clean up an unusable installation's Profile.
45. As an account operator, I want reset-profile to report partial failure accurately, so that incomplete deletion is not presented as a usable Profile.
46. As a local CLI user, I want my browser and site language left unchanged, so that automation respects the current interface settings.
47. As a local CLI user, I want page interactions to work without a forced viewport or added fingerprint overrides, so that the browser uses the agreed native configuration.
48. As an article publisher, I want required clipboard permissions and editor scripts preserved, so that removing browser disguise settings does not break article editing.
49. As an Instagram user, I want my existing local proxy option preserved, so that migrating browser storage does not change my network route.
50. As a Dayu operator, I want public verification to use an isolated anonymous context, so that visitor results are not influenced by my logged-in Profile.
51. As a managed-browser user, I want local browser settings ignored, so that my provider workflow does not acquire local installation or Profile requirements.
52. As a managed-browser user, I want the approved headless precedence applied through the existing provider, so that the configuration change preserves ownership and connection behavior.
53. As a user of a platform awaiting migration, I want its existing commands to keep working, so that incremental delivery does not switch it prematurely.
54. As a maintainer, I want each migrated platform's complete formal CLI surface covered, so that independent login, check and works-management launches are not overlooked.
55. As a maintainer, I want behavior tests at the existing CLI and session boundaries, so that refactoring internals does not require duplicating implementation details in tests.
56. As a maintainer, I want real cross-process and browser checks performed by the implementation Agent, so that mocks are not mistaken for evidence of persistence or locking.
57. As an account owner, I want the four designated platforms tested with no-publish enabled, so that validation stops before submitting real content.
58. As an account owner, I want no real works deleted for this regression, so that testing does not modify my published content.
59. As a maintainer, I want offline, browser and platform results reported separately, so that the evidence accurately describes what was exercised.
60. As a developer setting up the project, I want optional local and CI installation instructions for both browsers, so that I can prepare my chosen runtime without a new CI system.

## Implementation Decisions

### 1. 生效范围、职责与接口

- 覆盖已注册正式 CLI 的全部本地浏览器动作及调用链：login、check、视频/图文/文章发布、已有 verify/delete，以及独立启动入口和内部预检。Bilibili 的 biliup 流程及正式 CLI 不可达的历史入口不参与迁移。
- 常驻共享层负责生效配置解析、实际浏览器种类识别、Profile 定位和归属校验、跨进程占用、资源取得与关闭、定向 reset-profile。它产出能接入现有注入接口的 `BrowserSession`，保持真实 local 模式，不通过伪装 managed 借用错误处理。
- 平台层负责登录引导、正向登录证据、登录/验证页面识别、页面交互、发布和结果判断、显式目标及历史作品核验。共享层不持有平台选择器或发布业务。
- 同一动作的内部预检和业务复用同一个 session 及占用权；注入 session 的业务函数不自行重开或关闭它。正常 session 管理不包含旧资料迁移；临时迁移编排仅在迁移期间复用这些资源与平台探测接口。
- 直接支撑正式 CLI 的 uploader 调用同步采用新配置语义；不要求改造所有历史脚本。具体函数签名和模块拆分由实施决定，边界以本节行为为准。

### 2. 浏览器来源与 headless

| 条件 | 实际运行来源与要求 |
| --- | --- |
| `LOCAL_CHROME_PATH` 非空 | 作为 `executable_path` 使用；优先于浏览器选择，不依赖 channel 查找，也不检查另一种浏览器是否安装。 |
| 无自定义路径，选择 chrome | 使用 `channel="chrome"` 的系统 Chrome。 |
| 无自定义路径，选择 chromium | 使用项目固定 Patchright 版本配套的完整 Chromium，显式指定 `channel="chromium"`，有头与无头均不改用 headless shell。 |

- 无路径覆盖时，选择优先级为显式 `--local-browser chrome|chromium` > Python 配置 `LOCAL_BROWSER` > chrome；直接 uploader 调用的显式浏览器参数与 CLI 等价。已有 `LOCAL_CHROME_PATH` 名称保留，仍允许兼容 Chromium。
- headless 优先级为显式 `--headed` / `--headless` 或直接调用的显式布尔值 > `LOCAL_CHROME_HEADLESS` > False。必须保留“未提供”与显式 False 的区别；新配置示例用 False，不覆盖用户已有 True。login、check、业务及内部探测都用同次解析结果。
- 所有新本地入口使用 `launch_persistent_context`、所选 Profile、解析后的 headless 和 `no_viewport=True`。所选来源失败即报告，不自动切换 binary、浏览器种类或无头模式。
- 生效选择值、headless 配置非法或互斥参数冲突为用法错误；运行诊断区分实际可确认的浏览器缺失、路径/权限、显示服务、系统库及兼容性问题，不无证据猜测。

### 3. Profile 定位、元数据与别名

- 使用项目专用 browser_profiles 根目录，依次按正式平台名、原始账号别名、实际浏览器种类组织；chrome/chromium 叶子目录分别作为 user data directory。父账号目录和浏览器内部 Default 子目录不作为本项目 Profile 根。整个根目录不纳入版本控制，不使用用户日常 Chrome 资料。
- 别名保持原值和可读性，不裁剪、改大小写、Unicode 归一化、哈希化或转义。拒绝空白名称、路径分隔符、`.`、`..` 等改变目录含义的输入；文件系统不支持时明确失败。解析后的目标始终位于专用根内。
- 元数据保存平台、原始别名、浏览器种类并核对归属；大小写或 Unicode 等价路径造成别名碰撞时拒绝合并。已有目录归属元数据缺失、损坏或冲突属于故障，不将其默认为当前身份。
- 先选实际启动来源，再识别种类和定位 Profile。未被路径覆盖的标准 channel 提供已知种类；自定义路径在打开任何账号 Profile 前读取可靠产品信息，可使用受支持系统的产品版本输出或可执行文件产品资源，并限制探测时间。文件名、配置名、UA、CDP 的 Chrome 字样不能单独作种类证据；无法识别或信息冲突时停止。
- 记录生效来源、指定路径、可靠取得的解析路径及版本用于诊断；未知明确记未知，不用配套浏览器的预计路径冒充实际来源。元数据在互斥保护下安全创建或更新，不存完整 Cookie、token、登录态副本或长期真实账号绑定。
- 同种浏览器的来源路径、版本、有头/无头改变仍复用其 Profile；版本改变不自动重建，也不承诺任意构建或降级兼容。Chrome 与 Chromium 各用自己的目录，不复制凭据；尚未建立另一种类 Profile 的非 login 动作提示登录。
- Facebook 与 Facebook Page 的 Profile 独立；Facebook Page 下多个发布目标复用该别名、种类的 Page 登录 Profile，不按目标再拆目录。

### 4. 登录、当次身份与业务状态

- 持久化 Profile 是已迁移本地流程的唯一登录态来源。正式流程移除旧 JSON 文件存在检查、Cookie 内容预检、storage_state 恢复和导出；目录存在或历史初始化完成记录不证明当前登录有效。
- 只有 login 引导登录。check、发布及需要登录的作品操作，在 Profile 未建立或明确未登录时退出 `10`；业务过程中登录失效同样结束，不等待用户登录后续跑。再次 login 后的业务调用属于新流程。
- 账号别名不约束真实账号；允许同别名 A→B 重新登录，也允许两种浏览器使用不同账号。不迁移或新增永久身份绑定、换号暂停、重绑命令、跨 Profile 身份同步及仅防中途换号的账号前后比较。
- Instagram 从当前会话取得业务所需 `ds_user_id` 等字段，不从旧 Cookie 提取预期 ID，也不继续候选 JSON 登录流程。大鱼号、雪球、知乎退出旧身份旁文件读写和防换号比较；按实际操作需要读取当前 `wmid/name`、`uid/name`、`name/avatar_path`。必要字段格式与正向登录证据仍须校验，不以字段提取之名恢复全局身份门槛。
- 显式 `--page`、`--expected-name` 等请求继续校验；Page 未指定时遵循既有目标选择语义。verify/delete 继续核对原作品、作者、Page 等证据；原操作要求当前主体与作者一致时保留该检查。历史结果不删除、不改写为新账号；知乎的名称/头像证据不宣称为永久 ID。
- 网络、页面结构、权限、必需字段提取或 Profile 运行故障退出 `1`，不折叠成 invalid。人机验证保留 `reason="verification"` 和现有补救提示。选择器失败报告有依据的平台、动作、步骤，不直接归因语言或登录失效。

### 5. 一次性迁移及代码退出

本节仅属于实施期间的一次性作业，不能成为常驻 login/session 行为。旧资料处理失败时在迁移阶段解决并重试，不以永久兼容分支代替收口。

1. 仅对当次迁移平台、别名明确匹配的旧 Cookie 及大鱼号/知乎/雪球旧身份旁文件处理；不导入 Cookie，不解析旧身份作为新账号约束。旧文件缺失、损坏或属于其他真实账号均不妨碍新 Profile 登录。路径不能安全、唯一定位时报告故障，不猜测删除目标。
2. 在所选 Profile 中重新登录并取得平台正向登录证据；正常关闭后，按同目录、同种类及同次启动配置重开，复验登录并再次正常关闭。整个序列持有该 Profile 的占用权；复验不自动引导再次登录、不比较前后账号、不借助旧文件。
3. 两次核验及关闭均成功才定向删除旧资料，不建备份。仅身份旁文件残留也适用。失败、取消或无法可靠判定时保留尚未删除的文件；删除失败退出 `1`、列明剩余目标并保留有效 Profile。部分删除不回滚，迁移重试只处理剩余目标，已经不存在视为清理完成；两种浏览器清理同一旧文件也据此收敛。
4. 完成一次性迁移后，删除旧资料定位/存在检测、额外重启复验、清理/重试、临时入口及仅服务这些功能的测试代码，保留执行记录。不能仅关闭开关，不能保留永久迁移工具、待迁移状态或未来 login 自动处理的分支。
5. 最终正式命令不访问旧资料，旧文件后来重新出现也不触发迁移、额外重启或删除。普通 Profile 的创建、登录探测、关闭、持久化复用与 reset-profile 仍保留，持久化回归测试仍保留。

迁移不处理其他别名、未迁移平台、托管资料或历史发布结果。旧文件清理和 reset-profile 是两种不同动作，后者不负责旧资料迁移。一次复验只证明当时可恢复，不保证未来永不失效；迁移失败也不是发布重试依据。

### 6. 占用、生命周期与发布结果

- 对实际 Profile 目录建立跨进程互斥，覆盖归属读取/创建、启动、初始化、内部预检、业务、关闭和最终状态处理；一次性迁移期间也覆盖两次启动之间。等价目录不得绕过互斥。内部探测复用已有占用权，不竞争自己。
- 同 Profile 被占用时立即退出 `1`，不等待、不自动重试；不同 Profile 包括同别名的两种浏览器可并行。父级别名元数据安全创建和核对，不引入共享真实账号绑定。
- 互斥有效性由跨进程原语决定；PID、时间戳、锁文件存在只作诊断。锁与可重建的 Profile 数据分离，reset 不删除其自身互斥保护。残留诊断文件不永久阻断使用，也不靠删除锁文件取得占用权。
- 区分项目持有者、外部手动浏览器及无法分类的运行错误，只报告可证实信息。应用不删除浏览器 singleton 锁、不杀其他浏览器、不接管手动打开的实例。进程退出释放应用占用不证明浏览器子进程已退出；确有残留时提示用户关闭，不自动抢占。
- session 所有者在取得资源后立即建立清理保护，覆盖部分初始化、平台 setup、正常完成、异常、取消、超时和登录失效；清理可安全重复调用，取消继续传播。正常关闭 persistent context 后不重复关闭其已关闭的 browser；清理失败报告并尽力处理本次拥有的资源，不无限等待。
- Cookie、站点存储和偏好保留浏览器已落盘状态；失败不回滚、删目录或重建。硬终止、断电不保证 finally 或最新落盘。页面对象、草稿、任务进度和内存提交标记不作为自动恢复执行的依据。
- 保持现有发布预算、提交边界、`publish_attempted`、结果未知和禁止自动重发语义。已有业务错误优先于后续清理错误；已确认发布成功的关闭故障仅作独立警告。一次性迁移的关闭失败则不能通过旧资料删除验收。

| 结果类别 | 退出与恢复语义 |
| --- | --- |
| 参数/生效配置非法 | `2`，说明允许值或冲突。 |
| 来源识别、浏览器启动、Profile 占用/归属/损坏、网络/探测、文件操作故障 | `1`，保留实际原因；不自动清空、回退或解释为失效。 |
| 缺少 Profile、明确未登录或登录失效、人机验证 | 使用既定 `10`；保留验证 reason、提交阶段信息和对应补救提示。 |
| 已提交但结果未知 | 保持 `9`，禁止自动重发。 |
| 提交后登录/验证异常 | 保持原退出语义及 `publish_attempted=true`，先核查作品再决定后续动作。 |
| 托管限流 | 保持 `11` 及原有不等待、不自动重试契约。 |

### 7. 显式 Profile 重建

- 新增本地动作 `sau <平台> reset-profile --account <别名> --browser-kind chrome|chromium`，随平台批次开放。种类是明确的删除目标，不从 LOCAL_BROWSER、自定义路径或安装状态推导；无需安装或启动浏览器。
- 路径边界、归属和占用验证后，只删对应浏览器叶子目录及专属状态；保留父级别名归属、另一种类 Profile、其他别名、历史结果和旧资料。目标被占用或归属冲突时拒绝执行。
- 显式调用即清除意图，不增加交互确认或备份。显示目标和结果；目标不存在视为已清空。成功退出 `0` 并提示 login，不启动登录、不续跑业务、不创建看似有效的 Profile。
- 部分删除失败退出 `1` 并报告未完成状态，不能把残缺资料当有效 Profile 使用；用户修复后可重跑同一显式命令。托管模式拒绝此动作且不调用 provider；Bilibili 不提供此入口。

### 8. 本地参数清理与平台例外

- 移除项目增加的 stealth、UA/请求头替换、自动化标记掩饰参数、固定 viewport、额外最大化、locale/语言参数和无业务依据的权限。TikTok 的语言导航参数和站点 change_language、Rednote/小红书为读取改写 UA 创建的 probe context、虎扑为 UA/viewport/webdriver 重建 context 的流程一并退出。
- 保持 Patchright 自身默认参数；不修改 Chrome、Profile 或站点界面语言，不新增完整多语言选择器体系。平台按现有滚动、iframe/popup、覆盖层和元素可用性能力适应窗口；微博不再以固定大 viewport 保持发布按钮可见。
- 保留业务二维码、页面超时、DOM 稳定检测、人类化交互层、响应监听、发布预算、not-before、结果文件及现有代理等业务配置，包括 Instagram 本地代理。脚本按用途区分，不能把所有初始化脚本当作指纹注入删除。
- 大鱼号、知乎、雪球文章编辑保留各自创作站点 origin 限定的剪贴板授权，以及粘贴、ClipboardItem、选区/图片标记、上传和内容读回脚本。地理位置权限不作为默认权限；托管原有授权行为不随本地清理改变。
- 大鱼号 verify 先在主登录 context 核对后台作品，显式 `--public` 时再用同一已选 browser 创建独立临时匿名 context。它不绑定账号目录、不复制主会话状态、不传旧 storage state、不向主 Profile 写回，遵守相同来源、headless 与 no_viewport 基线。匿名步骤负责自身成功/失败/取消清理，主会话和锁仍由外层管理。具体 API 必须实测；有真实限制时调整实现以保持这些隔离和所有权语义，不回退旧 JSON。

### 9. 托管隔离与五批实施

- MLX / AdsPower 忽略本地浏览器选择、LOCAL_BROWSER 和 LOCAL_CHROME_PATH，不为这些无关值专门报错或警告，不检查本地浏览器、不进行种类识别、不触碰本地 Profile/锁/旧资料。headless 解析结果交给原 provider，保持原动作路由、参数映射、CDP、所有权、停止、断开、错误与既有日志。
- headless 新优先级随平台批次同时应用到该平台托管动作；尚未迁移的平台沿用旧解析和默认。保留动作级例外：第一批 login 的既有托管限制不变，Instagram verify/delete 在有托管环境变量时仍走原本的本地动作路由。
- 第一批建立新共享入口，由本批平台显式接入；旧本地入口继续服务未迁移调用方。不能全局改 parser、构造器或运行默认而使后续平台提前切换。一个平台进入某批时，其正式动作、内部预检、读写及清理成套迁移。

| 批次 | 平台 | 必须覆盖的接入边界 |
| --- | --- | --- |
| 第一批 | TikTok、Rednote、Instagram、小红书 | 共享能力与四平台一起交付；login/check、正式视频/图文，Instagram verify/delete；覆盖 TikTok 独立上传/预检、Rednote/小红书独立启动与 JSON preflight、Instagram 候选 JSON/历史预期 ID/作品写回及异常包装。 |
| 第二批 | YouTube、Facebook、Facebook Page | 全部正式登录、检查、发布和已有作品管理；覆盖 Facebook 与 Page 的独立作品操作启动入口，保留账号隔离及显式目标核验。 |
| 第三批 | 抖音、快手、视频号、百家号 | 正式 login/check/视频，抖音与快手正式图文；内部固定无头退出。视频号未注册的 note 不扩大为本批范围。 |
| 第四批 | 微博、虎扑、支付宝生活号 | 正式登录、检查和发布；覆盖虎扑重建 context 与微博窗口交互差异。 |
| 第五批 | 大鱼号、知乎、雪球 | 正式登录、检查、已注册视频/文章及验证；旧身份约束退出、剪贴板业务与大鱼号匿名验证；完成正式 CLI 路径收口。 |

- 对应一次性迁移完成后删除迁移代码；第五批最终核对所有正式 CLI 路径已移除临时新旧分流、旧 JSON 预检/导出和旧身份防错配逻辑。范围外调用方仍需的辅助资源按实际引用保留；这不允许保留本次新增的一次性迁移实现。

### 10. 安装与交付文档

- Patchright 保持项目依赖；浏览器按需准备。最终基础安装不强制下载或检查 Chrome/Chromium，本地运行只要求实际选定来源可用，托管不要求两者。分批期间准确保留未迁移平台仍需的依赖说明。
- 系统 Chrome 缺少时由用户按 Google 官方安装指引准备，项目不自动安装或更新，不把 patchright install chrome 作为默认路线。配套完整 Chromium 提供可选 `uv run patchright install --no-shell chromium`；普通 chromium 安装也可用，仅 headless shell 不满足契约。安装与运行保持项目版本及缓存配置一致。
- README 与安装指南提供两条独立 CI 环境安装路线：已有研究中的 Ubuntu 24.04 x64 官方 Chrome amd64 DEB 路线，以及项目固定 Patchright 配套 Chromium 路线；各自说明系统依赖和无显示有头运行的 Xvfb。自定义路径说明复用兼容现有 binary。文档示例不是已执行的验收结果。
- 每批同步配置示例、本批 CLI/平台 skill、登录说明、Agent Bootstrap 和运行依赖说明。最终核对打包资源及剩余调用方；“本地模式”术语的现状定义在实现落地时更新。安装完成、浏览器可启动、平台已登录分别表述。

## Testing Decisions

### 已确认的测试边界

用户于 2026-11-17 确认：以现有正式 CLI → BrowserSession 流程为主要入口，复用 FakePlaywright/provider 测试；跨进程占用用真实临时目录和子进程验证；保留 Agent 浏览器实测及四平台 no-publish 回归。随后的一次性迁移修正适用于测试生命周期：临时迁移实现及专用测试完成使命后删除，保留执行证据与正常 Profile 回归。

- 好的测试从调用方输入、退出码、诊断、文件状态、浏览器/provider 边界、提交动作及资源所有权观察行为；不锁定私有函数拆分、元数据序列化排版或全部内部调用顺序。关闭后才能复验/删除、提交至多一次等有业务意义的顺序应检验。
- 主要从正式 CLI dispatch 驱动到真实配置解析和共享资源编排，仅在浏览器与平台外部行为边界使用替身；不能把全部 session 替换掉后只断言 parser。直接 uploader 入口仅补充 CLI 不能证明的显式/缺省参数契约，不复制整套矩阵。
- 复用现有 BrowserSession 注入边界及 FakePlaywright、FakeContext、FakeBrowser、FakeManagedProvider，按新公开浏览器 API 扩展持久化能力。跨进程互斥使用同一公开 Profile 取得入口配合真实临时目录和子进程，不为锁的内部函数新增测试专用公开接口。
- 已有先例包括 `LocalBrowserSessionTests` 的启动边界/退出行为、托管 BrowserSession 与 AdsPower 测试的禁止 API 和所有权断言、抖音 upload seam 测试的注入 session 与提交后登录异常、`PublishCleanupTests` / `CleanupCliTests` 的主结果及退出码保护。这些先例中旧 JSON 写回、非持久化双重关闭或旧启动参数断言随平台迁移更新，不能当作必须保留的业务契约。

### 每批离线回归

| 被测行为 | 必须取得的证据 |
| --- | --- |
| CLI 与直接调用配置 | 选择优先级、路径覆盖、两种 channel、headless 缺省/显式值真实传到启动或 provider；内部探测一致，缺少非选定浏览器不影响运行，失败不回退。 |
| Profile 定位与占用 | 可读别名、越界/等价路径/归属冲突、未知种类、同种复用/异种隔离；两个真实进程争用同 Profile 立即失败、不同 Profile 可并行、残留诊断文件不等于活锁。 |
| 登录与别名语义 | 有效 Profile 不依赖旧文件；同别名换号、两浏览器不同账号可用；未登录/验证/探测故障分类正确，业务不等待重新登录后续跑；显式目标和历史作品核验保持。 |
| 生命周期与结果 | 初始化失败、取消、超时、关闭故障均按所有权清理；主业务异常、成功、结果未知和 publish_attempted 不被清理覆盖；业务不重复启动同目录或关闭注入会话。 |
| reset-profile | 精确目标、无需 binary、占用与路径防护、已不存在、部分失败、另一种类与历史结果保留；不操作 provider，不迁移旧文件。 |
| 平台参数与例外 | 去除指纹/语言/viewport 覆盖，保留业务脚本、代理、人类化交互与剪贴板 origin；按改动验证滚动、iframe/popup、小窗口及覆盖层；第五批覆盖匿名 context 的隔离和关闭。 |
| 分批与托管 | 本批正式动作全部进入新路径，未迁移平台仍用旧行为；托管只改变约定 headless 默认来源及 24 指定的成功摘要，其余 provider 参数、所有权、启动/ignored-option 日志与错误保持；动作级本地例外不被覆盖。 |

一次性迁移执行前验证旧文件缺失/损坏/不同主体、仅旁文件残留、两阶段登录验收、任何阶段取消/失败不提前删除、定向清理、部分删除及重试；使用合成资料，避免把真实账号文件当测试夹具。迁移结束后移除专用代码和测试，最终用外部行为验证旧文件重新出现仍不会被读取或清理，也不会导致日常 login 额外重启。代码收口检查确认没有遗留迁移入口或停用分支，不通过保留这些代码来运行历史迁移测试。

每批只跑与本批变更相关的回归，覆盖重要分支而非完整笛卡尔组合。最终核对正式 CLI 注册动作及可达启动链，避免独立 check、内部预检或作品操作漏接；按实际引用检查范围外资源未被误删。

### Agent 执行的浏览器验证

- 第一批由实施 Agent 在隔离临时 Profile 和空白页/受控本地页面上实际运行 Chrome、Chromium 的有头/无头启动、自定义可执行文件路径、关闭重开后的存储复用，以及主 Profile 与匿名 context 的状态隔离。持久化数据验证使用有正常 origin 的受控页面。
- 这些检查不需要平台账号，不以新增 CI 为前提，也不交给用户手动跑。Agent 检查环境并记录实际浏览器、配置、命令和结果；缺少环境或必须由用户完成的交互时报告具体阻塞。系统 Chrome 仍遵守用户自行安装的决定。
- 模拟测试不替代真实浏览器证据；后续共享能力有变化时补跑受影响项，无新变化时不无理由重复全部检查。未运行的环境或来源明确标记，不声称已验证。

### 五批完成后的真实平台回归

- Agent 使用用户已有账号，按默认 Chrome 有头路径回归 TikTok、Rednote、Instagram、小红书的 login、关闭重开后的 check，以及正式视频/图文发布前流程；账号和素材在执行时落实。其他平台与托管只要求离线回归，不以没有真实账号阻塞。
- 所有真实视频/图文命令显式传 `--no-publish`，并核对参数传递及实际停止点。保留现有素材上传、编辑和发布就绪检查后停止的语义；发现某入口缺少保护，先补齐并离线验证，再运行真实回归。
- 不实际提交发布、不删除真实作品、不为验证作品管理先发帖。verify/delete、提交后的错误和结果观察通过相关离线回归覆盖；Chromium、无头和路径覆盖通过浏览器实测及离线回归覆盖，不扩成每种配置的全平台真实矩阵。
- 分别报告离线结果、浏览器结果及 no-publish 平台结果。no-publish 可以上传真实素材并留下临时素材/草稿，只证明到达提交前停止点，不证明实际发布、not-before 等待、发布后验证或防封禁效果。

## Out of Scope

- 替换 Patchright、引入新的托管 provider、指纹伪装方案或人类化交互体系。
- Bilibili 的 biliup 流程、正式 CLI 不可达历史入口的全面改造。
- 除批准的 headless 配置来源及 24 指定的 no-publish 成功摘要外的 MLX / AdsPower 行为变更，以及托管账号或真实服务回归。
- Cookie 导入/导出、迁移后的旧文件兼容与自动清理、永久迁移工具、长期真实账号绑定或防中途换号体系。
- 自动安装/更新系统 Chrome、失败后自动换浏览器或无头模式、自动修改界面语言、完整多语言选择器支持。
- 自动清锁、结束外部浏览器、跨种类复制凭据、自动 Profile 重建、跨机器或任意降级兼容保证。
- 自动恢复旧任务、自动重发、真实发布或删除作品来验收，以及为其他平台获取真实账号。
- 新增 GitHub workflow、CI 验收系统或超出两条安装路线说明的 CI 建设。
- 在本次规格整理中实现迁移、安装/启动浏览器、处理真实账号资料或执行平台操作。

## Further Notes

- 本规格综合[决策地图](./map.md)及五张已解决决策票：[身份与旧登录态](./issues/01-profile-identity-and-migration.md)、[启动契约](./issues/02-chrome-launch-contract.md)、[生命周期与并发](./issues/03-profile-lifecycle-and-concurrency.md)、[平台接入边界](./issues/04-platform-integration-boundaries.md)、[别名与登录校验](./issues/05-account-binding-migration.md)。以最新 Answer 和本次用户修正为准，Comments 中撤回的方案仅是历史。
- 本次用户新增的收口约束是“旧 Cookie 迁移只发生一次，迁移后不留相关代码”，已同步到地图和相关决策票；这不删除正常 Profile 生命周期、重建能力或持久化测试。
- 安装及 API 依据沿用已有[Chrome 安装研究](./research/chrome-arm64-installation.md)、[Chromium 运行研究](./research/chromium-runtime-contract.md)和[生命周期研究](./research/profile-lifecycle-evidence.md)。这些资料属于源码/文档核对，不能替代本规格要求的实施实测；实施依赖有变化时重新核对对应事实。
- 使用根术语表中的“本地浏览器 Profile”“Profile 占用”“Profile 重建”“账号别名”“发布目标”“Browser session”“不发布模式”和“发布结果未知”。当前术语表的本地模式仍描述运行代码现状，随实现落地更新。
- 本次已核对当前共享本地入口仍使用临时 browser、storage_state 与 JSON 写回，且平台存在独立启动和旧身份依赖；已有测试可供扩展。未发现本领域 ADR 目录。本次发布规格不代表这些行为已迁移或测试已通过。
- 每批交付记录列出已覆盖入口、验证命令与实际结果、尚未迁移平台；一次性迁移另留执行与代码移除记录。最终完成条件是五批接入、一次性迁移收口及代码删除、相关文档和约定验证全部落实；确有阻塞的未执行项须明确报告，不能用模拟结果代替。

## 2026-11-17 追加要求：明确 no-publish 成功摘要（24）

用户指出 Rednote、TikTok、小红书的 `prepared (not published)` 摘要容易误解；三个平台的视频与图文在媒体上传、编辑及发布就绪检查成功返回后，统一输出 `素材已上传，发布前检查已通过；已停止，未点击发布按钮。`。保留视频路径或图片数量信息，失败/登录失效不输出成功摘要。

本次明确文案要求同时适用于本地和托管 no-publish；仅此摘要覆盖原有托管输出保持条款。正常发布输出、provider 启动/ignored-option 日志、退出码、机器结果字段、显式 no-publish 参数及真实提交前停止边界保持原契约。通过公开 CLI、真实配置/Profile/session 编排和外部页面/provider 替身验证六个动作的摘要、零提交及失败分支；文案调整不要求额外真实上传。过去实测日志保留当时原文。交付与证据见 [24](../local-chrome-profile-implementation/issues/24-clarify-no-publish-output.md)。
