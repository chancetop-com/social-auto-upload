# 本地 Chrome 持久化 Profile 迁移 — 决策地图

Label: wayfinder:map
Status: resolved

## Destination

形成覆盖所有正式 CLI 本地浏览器流程、可分五批实施的迁移规格：保留 Patchright，默认优先采用原生 Chrome 持久化 Profile，同时保留按需启用的 Chromium 方案，明确旧登录态迁移、生命周期和平台接入边界。托管模式除用户明确指定的有头/无头配置来源调整外，可观察行为保持不变。

本地图用于完成实施前的决策；实现代码不在本次 charting 会话中修改。

实施规格：[本地浏览器持久化 Profile 迁移](./spec.md)。

## Notes

### 用户已确定的约束（2026-11-17）

- 范围包括各平台本地登录、检查、发布、验证及其他正式 CLI 浏览器入口。Bilibili 通过 biliup 工作，不参与本次迁移。
- 保留 Patchright；本地默认采用 `launch_persistent_context(user_data_dir=..., channel="chrome", headless=False, no_viewport=True)`。专用 Profile 的身份映射与迁移方式见 Decisions so far 中的对应决策票。
- **默认优先选择 Chrome，Chrome 与 Chromium 均按需安装**（用户补充，2026-11-17）。二者均不是无条件安装依赖；本地仅要求实际选定的浏览器可用，也可复用自定义路径中的可执行文件。选择、路径覆盖、安装与错误契约见 Decisions so far 中的启动契约票；切换浏览器时已有 Profile 的处理由生命周期票确定。
- **保留显式 `--headless`**；本地默认配置采用有头，包括目前硬编码无头的检查入口。用户补充保留 `LOCAL_CHROME_HEADLESS` 作为未传参时的默认来源；该配置与显式参数的优先级及兼容细节由[本地 Chrome 启动参数与失败契约](./issues/02-chrome-launch-contract.md)确定。Best Practice 是默认配置，无头仍是用户可选项。
- 本地不增加指纹注入，不覆盖 UA 或浏览器请求头。迁移路径移除 `utils/stealth.min.js` 注入、小红书 UA 替换，以及其他平台同类覆盖；辅助文件是否可删，以所有剩余调用方为准。
- 不修改 Chrome、Profile 或站点的界面语言；现有选择器无法处理页面时停止并给出明确错误。不能把普通选择器失败直接断言为语言问题，也不能据此误报登录失效。无需为这次迁移新增完整的多语言选择器体系。
- **选择系统 Chrome 且尚未安装时，由用户自行安装**，README 说明官方安装路径；项目不自动下载安装 Chrome。**README 需补充 CI 环境下按需安装 Chrome 或 Chromium 的方法**；这是安装文档要求。Chrome 路线不依赖 `patchright install chrome`，Chromium 路线使用项目配套版本，二者独立可选。已有依据见[Chrome ARM64 安装与 CI 运行依据](./research/chrome-arm64-installation.md)及[Patchright 配套 Chromium 的安装与启动契约](./research/chromium-runtime-contract.md)。
- MLX / AdsPower 的启动、连接、Profile 和会话行为保持不变，只有用户明确要求的有头/无头配置来源调整为例外；本地浏览器选择与路径在托管模式下忽略且不专门报告。详细契约由[本地 Chrome 启动参数与失败契约](./issues/02-chrome-launch-contract.md)记录。
- 保留现有发布结果和重试契约，尤其是提交后结果未知不得自动重发。浏览器配置调整不等同于防封禁效果保证。
- **旧 Cookie JSON 及对应身份旁文件只做一次性迁移**（规格会话用户修正，2026-11-17）：重启复验和定向清理仅在迁移阶段执行；迁移完成后删除相关识别、编排、清理和兼容代码，不保留在日常 login/session 中，也不保留为永久迁移工具。后续命令不检查旧文件是否存在，不再触发这套流程。Profile 正常生命周期与显式 reset-profile 继续保留。

### 实施顺序

| 批次 | 平台 | 交付边界 |
| --- | --- | --- |
| 第一批 | TikTok、Rednote、Instagram、小红书 | 共享本地 Chrome / Profile 能力与四个平台接入一起完成；用户明确指定 |
| 第二批 | YouTube、Facebook、Facebook Page | 其余海外平台；用户明确指定 |
| 第三批 | 抖音、快手、视频号、百家号 | 国内视频发布流程 |
| 第四批 | 微博、虎扑、支付宝生活号 | 其余国内媒体发布流程 |
| 第五批 | 大鱼号、知乎、雪球 | 文章及混合内容流程，包含相应验证入口 |

第三至第五批由本会话按平台流程安排。共享层改动在前几批实施期间不得提前改变尚未迁移平台的行为；临时兼容入口及最终收口方式由相关决策票确定。

### 验收约束

- 每批做与变更相关的离线回归；托管模式只做离线回归，暂不要求托管账号或真实浏览器服务。
- 第一批的 Chrome / Chromium 启动、持久化和匿名隔离验证由实施 Agent 直接执行，不交给用户手动跑；具体范围见[分批接入的共享边界与平台例外](./issues/04-platform-integration-boundaries.md)。
- 五批完成后，TikTok、Rednote、Instagram、小红书用用户已有账号做真实回归；视频/图文流程统一使用 **`--no-publish`**，不提交发布，也不为本轮回归删除真实作品。由实施 Agent 执行，具体素材和账号在执行时落实。
- 其余平台仅要求离线回归，不把没有真实账号当作阻塞。
- CI 相关要求仅为 README 的 Chrome / Chromium 安装说明，不要求新增 GitHub workflow 或 CI 验收任务；实施 Agent 执行验证与此是两回事。若文档附启动检查示例，使用隔离的临时 Profile 和空白页，不依赖平台账号；Linux 无显示环境的有头运行说明 Xvfb 用法。
- 离线回归证明参数、生命周期及流程契约；不将它表述为已验证平台登录、发布或风控结果。`--no-publish` 真实回归覆盖登录和发布前流程，不证明实际提交或发布后结果，也不证明不会封禁。

### 已有事实与文档落点

- 当前共享本地入口是 `utils/browser_session.py::_local_session`，使用临时 browser + `new_context(storage_state=...)`；小红书、Rednote 等还有独立启动路径。只修改共享函数不能覆盖全范围。
- 旧登录态由 `cookies/<platform>_<account>.json` 承担，多处 CLI 和平台预检直接依赖文件存在或 Cookie 内容。切换为 Profile 后须一并处理。
- Chrome 持久化目录与一次 Browser session 是不同概念；当前根词汇表中的本地模式仍描述 JSON 现状，实施切换时再更新其现状定义。
- 安装说明需同步 README 与 `docs/install.md`，README 明确给出 CI 环境按需安装 Chrome 或 Chromium 的步骤，并核对 Agent Bootstrap、平台 skill 中与浏览器安装及本地登录态有关的说明；迁移后的基础安装不强制安装 Chrome 或 Chromium，两者分别列为可选路线。先保留当前运行方式的准确说明，随相应实现落地更新。
- 外部依据：用户给定的 [Patchright Best Practice](https://github.com/Kaliiiiiiiiii-Vinyzu/patchright-python#best-practice---use-chrome-without-fingerprint-injection)、[persistent context API](https://playwright.dev/python/docs/api/class-browsertype#browser-type-launch-persistent-context)，以及上述安装研究。
- 本地图后续会话使用 `wayfinder`、`grilling`、`domain-modeling`；新增外部事实需求时使用 `research`。

## Decisions so far

<!-- 每项结论的完整细节仅保存在对应已关闭决策票中；此处仅记录摘要与链接。 -->

- [本地 Profile 的身份与旧登录态迁移](./issues/01-profile-identity-and-migration.md)：按浏览器种类、平台和原始账号使用可读专用目录，一次性迁移中重新登录并复验后删除对应旧 Cookie JSON，统一已迁移本地流程的登录态来源与状态规则。
- [本地 Chrome 启动参数与失败契约](./issues/02-chrome-launch-contract.md)：自定义路径优先，Chrome/Chromium 均按需安装；统一选择、headless 与失败契约，托管仅调整 headless 默认来源。
- [本地 Profile 的生命周期与并发占用](./issues/03-profile-lifecycle-and-concurrency.md)：按 Chrome/Chromium 分目录复用、同 Profile 独占；显式定向清理后重新登录。旧资料的重启复验与清理仅用于一次性迁移，迁移完成即删除相关代码。
- [账号别名与登录态校验](./issues/05-account-binding-migration.md)：同别名可换号，退出身份防错配约束与旧身份文件；登录失效结束业务，保留显式目标及历史作品核验。
- [分批接入的共享边界与平台例外](./issues/04-platform-integration-boundaries.md)：明确共享职责、逐批接入和匿名验证；Agent 执行验证，真实流程使用 `--no-publish`；README 补 CI 安装说明，不新增 workflow。

## Not yet specified

- 无。各批入口、业务例外及验收边界已收敛；具体实现、账号与素材在实施阶段落实。

## Out of scope

- 更换 Patchright、引入指纹浏览器产品或新增托管 provider。
- 除上述有头/无头配置来源调整以外的托管模式行为修改，以及要求托管真实账号回归。
- Bilibili 的 biliup 流程，以及未由正式 CLI 使用的历史入口全面改造。
- 自动安装或更新用户机器上的 Chrome、自动修改界面语言、自动发布重试、额外指纹伪装或新的人类化交互方案。
- 为其他平台获取真实账号或执行真实回归。
- 新增 GitHub CI workflow 或由 CI 安装说明扩展出的自动验收体系；从未属于用户请求。
- 本次建图会话直接实现迁移；实施阶段在决策完成后按上述五批推进。

### 2026-11-17 — 用户目录顺序修正

当前布局为 `browser_profiles/<chrome|chromium>/<platform>/<raw_account>`，覆盖原决策中的目录顺序；归属与 guard 位于可删除账号叶子之外，合法别名不因内部文件名受限。既有四份资料由[实施票 21](../local-chrome-profile-implementation/issues/21-browser-kind-first-layout.md)安全移动并正常 check，历史证据保留原路径。
