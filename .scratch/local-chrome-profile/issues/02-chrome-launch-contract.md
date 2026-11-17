# 本地 Chrome 启动参数与失败契约

Label: wayfinder:grilling
Type: grilling
Status: resolved
Blocked by: —
Assignee: Codex（本会话）

## Question

在用户已确定的 Chrome 优先、Chromium 按需启用的配置下，怎样选择浏览器，哪些配置入口继续有效，无法启动时怎样报告？

- 默认使用 `channel="chrome"`，同时保留 Chromium 方案。按需启用 Chromium 的配置入口是什么，与现有 `LOCAL_CHROME_PATH`、默认 Chrome 选择的优先级如何安排？区分用户选择与启动失败处理，不把“保留 Chromium”直接解释为静默自动回退。
- Chromium 如何使用持久化 Profile，并遵守已经确定的默认有头、无指纹注入、无 UA/请求头覆盖等本地约束？Chromium 按需安装、不作为默认安装依赖已确定；需明确浏览器来源、可选安装步骤与缺失提示，如需新增外部事实，补充研究。
- `--headless` 必须保留，默认有头已确定；直接调用 uploader 的默认值、旧 `LOCAL_CHROME_HEADLESS` 与 CLI 参数如何保持一致？明确显式值的优先级。
- 所选 Chrome / Chromium 缺失、显示服务缺失、可执行文件不可用或版本不兼容分别使用什么错误提示与现有退出码？Chrome 由用户安装，项目不自动下载 Chrome，提示应指向 README 手动安装说明；仅使用 Chrome 时不检查或要求安装 Chromium，选择 Chromium 时的缺失提示应指向可选安装步骤。
- 当前平台的权限、launch args、窗口尺寸等选项哪些确有业务必要，哪些应去掉？UA、手写请求头、语言设置和指纹注入已经确定移除，不再重新选择。
- no_viewport 下平台自定义 viewport 与现有配置如何退场？README 需补充 CI 环境按需安装 Chrome 或 Chromium 的说明；Chrome 的官方 DEB + Xvfb 安装依据已确定，不要求新增 GitHub workflow。

回答应形成覆盖默认 Chrome 与可选 Chromium 的参数与错误矩阵。Chrome 安装事实使用已有研究，不要求用户重新选择已确定的方案；Chromium 的安装与运行依据按需补充。

## Context

- 所属地图：[本地 Chrome 持久化 Profile 迁移](../map.md)。
- 已有资料：[Chrome ARM64 安装与 CI 运行依据](../research/chrome-arm64-installation.md)。
- 补充资料：[Patchright 配套 Chromium 的安装与启动契约](../research/chromium-runtime-contract.md)：核对固定版本的完整浏览器、headless shell、安装选项与 channel / executable_path 选择行为；尚未实际安装或启动验证。
- 后续依赖：[本地 Profile 的生命周期与并发占用](./03-profile-lifecycle-and-concurrency.md)。

## Comments

### 2026-11-17 — 用户补充约束

用户明确：“虽然优先chrome但是保留chromium方案，按需启用”。Chrome 仍是默认优先选择，Chromium 支持必须保留；具体参数名、选择优先级和失败时的切换行为尚未决定。

用户进一步明确：“Chromium自然也就变成按需安装”。Chromium 不作为默认安装依赖，默认 Chrome 路径不能因未安装 Chromium 而受阻；本票只需确定具体可选安装方式与提示，不再讨论是否强制安装。

### 2026-11-17 — 启动契约会话：第一轮待确认

本票已认领，尚未形成决议。以下是向用户提出的建议，不是已确认的实施要求：

- 默认 Chrome 启动失败直接报告具体错误；只在用户显式选择 Chromium 时切换，不自动回退。
- 新增 `--local-browser chrome|chromium` 与 `conf.py` 的 `LOCAL_BROWSER`，优先级为命令行（直接调用时为显式参数）> 配置 > Chrome。
- 已迁移入口不再读取旧 `LOCAL_CHROME_HEADLESS`，统一默认有头；保留 `--headed` / `--headless` 和 uploader 显式 `headless` 参数。未迁移平台随各自批次切换。

已核对的当前代码事实：

- `conf.example.py:4-5` 的 `LOCAL_CHROME_PATH` 默认为空、`LOCAL_CHROME_HEADLESS` 默认为 `True`；这是 Python 配置模块，不是同名环境变量。
- `sau_commands/arguments.py:125-130` 的 `--headed` / `--headless` 互斥且 CLI 默认为有头。部分 uploader 默认仍取旧配置；部分内部检查直接固定无头。CLI 已传参不代表内部检查已遵守它。
- 具体例外包括 TikTok login 固定有头（`sau_commands/tiktok.py:527-529`）、大鱼号本地 check 固定无头（`uploader/dayu_uploader/session.py:165-167`）。迁移验收须覆盖内部预检和独立登录路径。
- `sau_cli.py:75-104` 已区分一般异常 `1`、用法错误 `2`、登录失效 `10`、限流 `11`、发布结果未知 `9`；启动失败的分类不能覆盖后续发布提交契约。
- Instagram 的独立 check 固定无头（`uploader/meta_uploader/insgraph_uploader/main.py:477-483`）；独立 login 使用 `--start-maximized` 与 `no_viewport=not headless`（同文件 `493-511`）。微博的 `1280×2000` viewport 注释用于让发布按钮留在屏幕上（`uploader/weibo_uploader/main.py:84`），尚未证明固定尺寸是必要条件。
- 大鱼号、雪球、知乎的文章粘贴实际使用剪贴板，并按平台 origin 授予 `clipboard-read/write`（分别见 `uploader/dayu_uploader/article.py:133`、`uploader/xueqiu_uploader/article.py:33`、`uploader/zhihu_uploader/article.py:35`）。不能把业务权限与已决定移除的指纹、UA、请求头和语言覆盖一并删除。
- 多个平台配置了 geolocation permission，但本次没有找到足以证明应普遍保留的业务依据；百家号注释明确发布不依赖它。抖音、虎扑的 `--disable-blink-features=AutomationControlled`，以及小红书、Rednote 对 `HeadlessChrome` 的 UA 替换属于掩饰自动化标记，应受地图既定的移除约束。
- 当前没有 `--local-browser`。`sau_commands/browser.py:125-136` 只注册 folder/profile；新增本地选项在托管模式下拒绝还是忽略，尚需明确。现有托管启动不使用本地 launch/context 配置，但仍接收 `headless`，迁移不能改变其既有行为。
- 当前 TikTok cookie check 把启动/读取/Playwright 故障折叠成 False（`uploader/tk_uploader/main_chrome.py:1082-1113`），发布前预检又将其表述为 Cookie 不存在或失效（`sau_commands/tiktok.py:448-455`）。迁移后须保持故障原因，不能只统一最外层退出码。

### 2026-11-17 — 启动契约第一轮用户决定

- 用户确认 Chrome 启动失败直接报告错误，由用户显式选择 Chromium；不自动回退。
- 用户确认新增 `--local-browser chrome|chromium` 和 `conf.py` 的 `LOCAL_BROWSER`；优先级为命令行 > 配置 > Chrome。直接调用 uploader 时使用显式参数 > 配置 > Chrome。
- 用户选择“保留旧配置作为未传参时的默认值”，未采纳停用 `LOCAL_CHROME_HEADLESS` 的建议。已迁移本地入口应让显式 `--headed` / `--headless`（或显式 `headless` 参数）覆盖旧配置；不能让 parser 的字面量 False 掩盖“未传参”。
- 新配置示例的默认值、已有 `True` 是否对所有本地命令（含 login）生效、缺项时的默认值，以及托管路径的隔离细节在下一轮明确；上述建议中的停用旧配置不构成实施要求。

### 2026-11-17 — 启动契约第二轮用户决定

- 用户确认 Q4 按推荐：新配置示例 `LOCAL_CHROME_HEADLESS=False`，缺项也按 False；不改写已有配置，已有 True 继续有效。显式 `--headed` / `--headless` 或直接调用的显式 `headless` 参数优先。规则覆盖已迁移平台的本地 login、check、发布及内部预检；已有 True 时人工登录须用 `--headed` 显示窗口。
- 用户对 Q5 询问“以前是什么样的”，尚未决定 `LOCAL_CHROME_PATH` 的新适用范围；不能把先前建议当作已采纳。
- 用户修正 Q6：“忽略这些本地配置不用特意报告，只有是否有头取配置”。MLX / AdsPower 忽略本地浏览器选择（含显式 `--local-browser`）和本地可执行文件路径，不因该选择专门报错或警告；是否有头同样采用显式参数 > `LOCAL_CHROME_HEADLESS` > False。该默认来源变化是对地图原先“托管行为不变”约束的明确例外；不修改 provider 的启动/连接协议、Profile、所有权或其他会话行为。
- 用户确认 Q7 按推荐：统一 `no_viewport=True`，移除项目额外添加的固定 viewport、最大化及无已知业务必要性的启动参数和权限。保留已证实用于文章粘贴、限定平台 origin 的剪贴板权限；必要的平台例外由「分批接入的共享边界与平台例外」明确。Patchright 自身默认参数不改。此项只适用于迁移中的本地路径，不改托管 Profile 的页面配置。

Q5 的当前实现依据（用于解释旧行为，不是新契约）：

- 目前没有统一的 Chrome / Chromium 选择项。`LOCAL_CHROME_PATH` 是 executable_path 覆盖，且不同平台是否读取它、空值时采用哪个浏览器并不一致。
- TikTok 非空用指定路径，空值不传 channel，落到配套 Chromium（`uploader/tk_uploader/main_chrome.py:57-66`）；快手非空用指定路径，空值显式 `channel="chromium"`（`uploader/ks_uploader/main.py:62-71`）。
- 视频号非空用指定路径，空值 `channel="chrome"`（`uploader/tencent_uploader/main.py:114`）；大鱼号、知乎、雪球配置 `channel="chrome"` 并用非空路径覆盖。
- Facebook、Facebook Page、Instagram、YouTube 指定 `channel="chrome"`；抖音、小红书、Rednote 指定 `channel="chromium"`。已核对的这些正式启动路径没有统一用 `LOCAL_CHROME_PATH` 覆盖，因此改这一项不能保证各平台同步切换。

### 2026-11-17 — 自定义路径对 Chromium 的适用性澄清

- 用户追问“以前是 Chromium 这个也生效吧？”。已再次核对 TikTok 的 `TIKTOK_LAUNCH_KWARGS`（`uploader/tk_uploader/main_chrome.py:60-62`）和快手 `_build_ks_launch_kwargs`（`uploader/ks_uploader/main.py:62-66`）：非空路径直接传给 `executable_path`，并不限制为 Google Chrome；指向兼容的 Chromium 可执行文件也适用。配置名中的 CHROME 不代表已有品牌限制。
- 先前建议“只在选择 Chrome 时使用该路径，选择 Chromium 时忽略”会收窄旧配置用途，并非保持现状。新的统一路径规则仍待用户决定；可保留通用覆盖语义，即非空路径优先决定实际可执行文件，为空时再使用选定的 Chrome / Chromium channel。

### 2026-11-17 — 最终路径规则与可选安装确认

- 用户确认按最新建议保留通用路径覆盖：`LOCAL_CHROME_PATH` 非空时使用指定的 Chrome 或兼容 Chromium 可执行文件；为空时才按 `--local-browser` / `LOCAL_BROWSER` / Chrome 默认值选择。
- 用户进一步明确“Chrome 和 Chromium 依赖都是可选安装”。默认选择 Chrome 是配置缺省值，不是无条件安装依赖；本地运行只要求本次实际选择的浏览器可用。已有可用自定义路径时，不要求另装系统 Chrome 或 Patchright 配套 Chromium；托管路径不要求安装这两套本地浏览器。
- 各项产品选择已通过以上交流确定。本票下方汇总最终契约；历史讨论中“停用旧 headless 配置”“Chromium 忽略自定义路径”“托管显式本地选项报错”的建议均未采纳。

## Answer

### 浏览器选择与路径覆盖

适用于已迁移平台的所有正式 CLI 本地浏览器入口，包含 login、check、发布、验证及其内部预检。保留 Patchright，统一使用专用本地 Profile 的 `launch_persistent_context`；Profile 目录和身份映射遵循[本地 Profile 的身份与旧登录态迁移](./01-profile-identity-and-migration.md)。

实际可执行文件的选择分两步，路径覆盖优先于 channel 选择：

| 条件 | 实际启动来源 | 其他浏览器要求 |
| --- | --- | --- |
| `LOCAL_CHROME_PATH` 非空 | 作为 `executable_path` 使用指定文件，可以是 Chrome 或兼容的 Chromium；不依赖 channel 查找默认安装。 | 不检查或要求系统 Chrome、配套 Chromium；不因 `--local-browser` 取值改用另一个 binary。 |
| 路径为空，最终浏览器选择为 `chrome` | `channel="chrome"`，使用标准位置的系统 Chrome。 | 不要求安装配套 Chromium。 |
| 路径为空，最终浏览器选择为 `chromium` | `channel="chromium"`，使用当前 Patchright 配套的完整浏览器。 | 不要求安装系统 Chrome。 |

路径为空时，浏览器选择优先级为 `--local-browser chrome|chromium` > `conf.py` 的 `LOCAL_BROWSER` > `chrome`。直接调用 uploader 时用显式浏览器参数替代 CLI 参数，后两级一致。新配置示例采用 `LOCAL_BROWSER="chrome"`、`LOCAL_CHROME_PATH=""`；保留旧路径配置名和通用覆盖语义，不把它重新解释成仅允许 Google Chrome。

有头、无头使用同一选择规则。配套 Chromium 显式指定 `channel="chromium"`，避免省略 channel 时无头分支改用 headless shell；自定义路径始终指向同一个指定文件。选择值和配置名不证明实际浏览器品牌：例如路径指向 Chromium 时，即使默认选择为 chrome，也不能将实际运行来源记作系统 Chrome。更换路径、binary 或版本对已有 Profile 的影响留给[本地 Profile 的生命周期与并发占用](./03-profile-lifecycle-and-concurrency.md)。

任何选定来源启动失败均报告该来源的错误，不自动改用其他路径、Chrome 或 Chromium。此规则同样适用于自定义路径失败；不以默认安装可用为理由静默忽略用户指定的路径。

### 有头/无头配置

统一优先级：显式 `--headed` / `--headless`（直接调用时为显式 `headless` 参数）> `LOCAL_CHROME_HEADLESS` > False。

| 输入 | 最终 headless |
| --- | --- |
| 显式 `--headed` 或 `headless=False` | False，即使配置为 True。 |
| 显式 `--headless` 或 `headless=True` | True，即使配置为 False。 |
| 未显式传参，配置为 True / False | 使用配置值。 |
| 未显式传参且配置缺项 | False。 |

- CLI 和直接调用须能区分“未传参”与“显式 False”；不能用 parser 或构造器的默认 False 提前遮住配置。
- 新配置示例改为 `LOCAL_CHROME_HEADLESS=False`；不覆盖用户已有的 True。保留 `--headed` 和 `--headless` 的互斥关系。
- 本地 login、check、发布、验证以及内部预检都服从同一次请求的解析结果，移除既有硬编码有头/无头和不一致默认值。人工登录若配置为 True，用户可用 `--headed` 显示窗口；不静默替用户改模式。
- 这项优先级也适用于托管模式，是用户明确批准的唯一托管默认行为调整；其余托管行为按下节隔离。

### 参数基线与业务例外

所有已迁移本地入口均使用持久化 context、上文解析出的 headless 和 `no_viewport=True`，包括 Chrome、配套 Chromium 和自定义路径。

| 选项类别 | 最终要求 |
| --- | --- |
| 平台固定 viewport、额外最大化参数 | 移除；不以固定 viewport 替换 `no_viewport=True`。现有页面依赖须在该平台批次验证，按页面交互需要滚动或处理元素可用性。 |
| 语言设置 | 不额外设置 locale、`--lang`、Accept-Language 或修改 Profile/站点语言。选择器不适配时报告具体故障，不自动改语言或推断登录失效。 |
| 指纹与自动化标记覆盖 | 移除本地 stealth 注入、UA/请求头替换及项目额外添加的自动化标记掩饰参数，包括已有 `HeadlessChrome` 替换。 |
| 无已知业务必要性的项目额外参数和权限 | 移除，不因历史代码存在而全量继承；geolocation 不作为通用默认权限。 |
| 已证实的业务权限 | 保留大鱼号、雪球、知乎文章粘贴所需的剪贴板权限，并限定到对应平台 origin。其他例外由接入票依据业务用途列明。 |
| Patchright 自身默认启动参数 | 保持原样；移除的是项目额外添加项，不承诺或要求重写 driver 默认参数。 |

不因移除指纹注入而一并删除业务初始化脚本或匿名验证 context；按用途判断，具体清单由[分批接入的共享边界与平台例外](./04-platform-integration-boundaries.md)落实。仍有未迁移调用方使用的辅助文件不能提前删除。

### 安装与文档契约

Chrome 和 Chromium 浏览器均为按需安装的可选运行依赖。项目默认选择 Chrome，但基础安装不得无条件下载、检查或强制安装任一浏览器；本地执行时才要求实际选择的那一项可用。Patchright 仍保留为项目 Python 依赖，“浏览器可选安装”不表示移除自动化库。

- **系统 Chrome 路线**：用户已有标准安装即可复用；缺少时由用户按 README 的 Google 官方安装指引安装。项目不自动安装或更新 Chrome，不以 `patchright install chrome` 作为默认安装步骤。
- **配套 Chromium 路线**：提供显式可选步骤 `uv run patchright install --no-shell chromium`，使用本项目固定版本的 Patchright。普通 `uv run patchright install chromium` 也可用，只是还会安装 shell；仅安装 headless shell 不能满足这里统一的完整浏览器契约。安装与运行使用一致的浏览器缓存配置。依据见[Chromium 安装与启动研究](../research/chromium-runtime-contract.md)。
- **自定义路径路线**：用户提供兼容的现有可执行文件即可；不额外要求系统 Chrome 或配套 Chromium。可执行文件及所需系统库仍须实际可用，兼容性故障按下表报告。
- **托管路线**：不要求本地 Chrome 或配套 Chromium，也不进行相关缺失检查。
- README、`docs/install.md`、Agent Bootstrap、平台 skill 和打包说明须随批次同步，把两种浏览器安装都列为可选路线。尚未迁移的平台仍须保留准确的旧依赖说明，不能提前移除它们仍需的安装步骤。

README 必须补充 **CI 环境下按需安装 Chrome 或 Chromium** 的两条独立路线。这是用户原有的文档要求，其本身不包含新增 GitHub workflow 或 CI 验收任务；实施阶段的浏览器验证由 Agent 执行，具体范围见[分批接入的共享边界与平台例外](./04-platform-integration-boundaries.md)，不要求用户手动跑测试。Chrome 示例采用已核对的 Ubuntu 24.04 x64、Google 官方 amd64 DEB、系统依赖；需要无显示有头运行时说明 Xvfb。Chromium 示例按上文安装项目固定 Patchright 版本配套的完整浏览器，并说明相应系统依赖及安装/运行环境一致性。选择某一路线不要求安装另一个浏览器；具体依据及未运行验证的限制见[Chrome 安装研究](../research/chrome-arm64-installation.md)与[Chromium 安装研究](../research/chromium-runtime-contract.md)。若附启动示例，使用临时 Profile 和空白页，不依赖平台账号；文档示例不代表已经运行成功。用户在接入会话中澄清了文档范围并指定验证执行者，先前相关文字以本段及接入票 Answer 为准。

### 错误与退出码矩阵

沿用既有用法错误、运行故障、登录失效和发布结果契约，不新增退出码。诊断指出实际选择的来源、已知失败原因和相应补救步骤；无证据时保留普通启动故障，不猜测具体原因。

| 情形 | 退出码与提示 | 禁止的处理 |
| --- | --- | --- |
| 生效的浏览器选择值或 headless 配置非法、CLI 参数冲突 | `2`，说明参数/配置问题及允许值。 | 不静默改成默认值。 |
| 选择系统 Chrome 但标准安装不存在 | `1`，说明 Chrome 缺失，指向手动安装或显式选择其他可用来源的步骤。 | 不要求安装 Chromium，不自动下载安装或回退。 |
| 选择配套 Chromium 但匹配的完整浏览器不存在 | `1`，指向上述可选 Chromium 安装步骤，并提示核对安装/运行环境。 | 不把系统 Chrome 当作自动替代，不强制两者都安装。 |
| 自定义路径不存在、不可执行或无法访问 | `1`，报告该路径问题，提示修正路径、权限或用户自行准备可执行文件。 | 不改用标准 Chrome/Chromium，也不以安装另一个浏览器遮住路径错误。 |
| 有头启动缺少可用显示服务 | `1`，依据实际错误说明显示环境问题；Linux 提示 Xvfb，或由用户显式选择无头。 | 不自动改成无头。 |
| 系统库、运行权限、可执行文件兼容性或版本问题 | `1`，保留可判断的原因和诊断信息；确认是兼容性问题时提示核对版本/依赖。 | 不把普通启动失败一概断言为版本不兼容，不自动替换用户浏览器。 |
| 未能可靠分类的启动/连接故障 | `1`，报告原始故障上下文。 | 不折叠成 Cookie invalid 或退出 `10`。 |
| 未建 Profile、平台明确未登录/登录失效 | 遵循身份迁移票：依赖登录的非 login 命令退出 `10` 并提示 login；探测故障仍为 `1`。 | 目录存在不能证明已登录；浏览器故障不能当登录失效。 |
| 发布提交后的异常 | 保留现有 `publish_attempted`、登录/验证和结果未知契约；可能已提交但结果未知仍为 `9`，不得自动重发。 | 不因浏览器配置或清理失败覆盖提交边界，也不将其重新解释成可安全重试的启动失败。 |

Profile 占用、损坏、异常退出和关闭故障的细化处理由生命周期票决定，不借本票自动删除 Profile、清锁或终止其他浏览器。

### 托管隔离与分批验收

- MLX / AdsPower 忽略 `LOCAL_BROWSER`、`LOCAL_CHROME_PATH` 和显式本地浏览器选择，不为这些无关设置专门报错或警告，不做本地浏览器可用性检查。仅 headless 按本票优先级解析后交给原 provider；不重写 provider 的启动协议或已运行浏览器状态。
- 本地 persistent context、viewport、语言、权限和脚本调整不应用到托管 Profile。托管连接、参数映射、所有权、停止/断开及退出契约除已批准的 headless 默认来源外保持不变。
- 未迁移平台保留原行为，不能因共享配置解析或安装说明先改而提前切换；托管 headless 默认来源的分批应用也须由接入票明确。
- 各批离线检查至少覆盖自定义路径优先、两种 channel、未安装非选定浏览器、有头/无头显式值与配置、内部预检、启动错误分类及托管忽略规则。测试须验证传递到启动/provider 的实际参数，不能只测 CLI parser。
- 本次仅记录决策和资料；没有修改实现、安装浏览器、启动浏览器或验证平台登录/发布。生命周期与分批平台例外仍由地图中的相应未决票推进。
