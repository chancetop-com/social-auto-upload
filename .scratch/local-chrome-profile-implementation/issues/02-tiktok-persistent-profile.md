# 02: TikTok 全流程接入持久化 Profile

**What to build:** TikTok 用户可用同一个本地浏览器 Profile 完成登录、检查、视频和图文发布及重建；默认 Chrome 有头，显式选择的浏览器和运行模式在整个动作中保持一致。以该完整流程交付其余平台复用的持久化 Browser session，并取得真实浏览器证据。

**Blocked by:** [01：安全定位、占用与重建本地 Profile](./01-profile-ownership-and-reset.md)

**Status:** resolved

**批次：** 第一批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 覆盖 TikTok 已注册 login、check、upload-video、upload-note、reset-profile，以及正式 CLI 可达的独立上传、内部预检和直接 uploader 调用；平台正向登录证据和页面交互留在平台层，新共享入口输出真实 local 模式的 Browser session。
- [x] 浏览器配置遵守：非空 LOCAL_CHROME_PATH 作为 executable_path 优先；无路径覆盖时显式 local-browser > LOCAL_BROWSER > chrome。Chrome 使用系统 chrome channel，Chromium 使用项目固定 Patchright 配套完整 chromium channel，有头/无头均不改用 headless shell，仅要求实际选择来源可用。
- [x] headless 采用显式 headed/headless 或直接调用显式布尔值 > LOCAL_CHROME_HEADLESS > False，区分未提供和显式 False；新示例默认 False，保留用户已有 True。同一动作的登录探测、内部预检和业务使用同次解析结果。
- [x] 生效配置非法或互斥参数冲突退出 2；所选来源失败立即停止，不切换 binary、种类或无头模式。诊断只据实际证据区分浏览器缺失、路径/权限、显示服务、系统库或兼容性故障，并标明实际来源。
- [x] 标准 channel 提供已知浏览器种类；自定义可执行文件在打开任何账号 Profile 前，以限时的可靠产品信息识别种类，无法识别或证据冲突退出 1。文件名、配置名、UA 或 CDP Chrome 字样不能单独作证据；记录已知来源、指定/可靠解析路径及版本，未知如实标注。
- [x] 使用持久化 context、已选 Profile、解析后的 headless 和 no_viewport；接入 01 的归属与占用，锁覆盖元数据、启动、初始化、预检、业务、关闭和结果处理。内部检查复用 session 和锁，注入 session 的业务不重开或关闭它。
- [x] 同种浏览器改变来源路径、版本或有头模式仍复用资料；不同种类隔离且不复制凭据，版本变化不自动重建。缺少另一种类 Profile 的非 login 动作提示先登录。
- [x] Profile 是唯一登录态来源，正式流程不检查、恢复或导出旧 JSON，也不包含一次性迁移。只有 login 引导登录；Profile 缺少、明确未登录或业务中失效退出 10，不在业务中等待重新登录后续跑。目录存在不代替当前正向登录证据。
- [x] 同别名允许重新登录其他真实账号，两种浏览器允许不同账号；不引入永久绑定或仅为防换号的前后比较。网络、权限、页面结构或必要字段提取失败退出 1；人机验证保留 reason=verification、退出 10 及补救提示。
- [x] 移除本地 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化和语言覆盖，包括 TikTok 语言导航参数及站点 change_language；保留 Patchright 默认、二维码、业务脚本、超时、DOM 稳定检测、人类化交互、响应监听及现有业务配置。
- [x] 取得资源后立即建立清理保护，覆盖部分初始化、setup、正常完成、异常、取消、超时和登录失效；清理可重复调用且有界，取消继续传播。正常关闭 persistent context 后不重复关闭其 browser，故障不回滚或重建 Profile，不抢占残留浏览器。
- [x] 保留发布预算、not-before、结果文件和提交至多一次的边界；publish_attempted、退出 9 的发布结果未知、提交后登录/验证异常保持原语义，主业务错误优先，已确认成功后的关闭故障仅独立警告。崩溃、重新登录或重建不自动恢复旧任务或重发。
- [x] MLX/AdsPower 只调整本平台 headless 默认来源；忽略本地浏览器选择与路径且不为其报错/警告，不检查安装或触碰本地资料、锁与旧文件。原 provider 参数、CDP、所有权、日志、退出 11 及 login 托管限制保持。
- [x] 新共享能力由本票显式接入；其他平台保留旧 parser、构造器和运行默认，避免提前切换。第一批以 01–05 全部完成为交付边界，不能仅改共享旧入口就宣称覆盖四平台。
- [x] 从正式 CLI dispatch 驱动真实配置解析、Profile 编排和生命周期，只替换浏览器/平台外部边界；复用既有 FakePlaywright、context、browser 和 provider。覆盖选定/非选定来源、显式/缺省参数、登录分类、别名换号、资源失败、结果保护及托管隔离；直接 uploader 只补 CLI 不能证明的契约。
- [x] 由实施 Agent 在隔离临时 Profile 和具有正常 origin 的受控页面上实测 Chrome/Chromium 各自有头、无头、自定义路径、关闭重开后存储复用、主 Profile 与匿名 context 状态隔离；记录实际浏览器、配置、命令和结果，不用模拟替代。系统 Chrome 仍由用户自行安装，环境或必要交互缺失时明确记录阻塞。
- [x] 确认 TikTok 视频/图文 no-publish 参数传到实际停止点；缺少保护时先补齐并离线验证，在素材上传、编辑和发布就绪后、最终提交前停止。本票不执行真实平台发布或删除，四平台真实不发布回归留给 20。
- [x] 同步配置示例、TikTok CLI/平台 skill、登录说明、Agent Bootstrap 和安装依赖说明；浏览器按需准备，系统 Chrome 官方安装与项目配套完整 Chromium 两条路线清晰，保留未迁移平台所需说明。更新本地模式术语的阶段现状，记录覆盖入口、离线/浏览器结果及尚未迁移平台。


## Answer

TikTok 的 login、check、upload-video、upload-note 与直接 uploader 调用已成套接入持久化 Profile；reset-profile 复用票 01。新共享入口 `utils.local_browser_session.local_browser_session` 返回真实 local BrowserSession，并用票 01 的公开 lease 覆盖创建/校验、启动、setup、探测、业务与有界关闭。原 `browser_session` 保留给未迁移平台和托管流程。

配置由 `utils.local_browser.resolve_local_browser` 解析，公开 `LocalBrowserConfig.launch_options` 可在调用方持续持有 lease 时用于严格关闭/重开。`resolve_headless` 独立供托管使用；`add_local_runtime_flags` 仅让本票平台 opt-in。标准 channel 种类已知；custom 使用限时系统产品信息，路径/文件名/UA 不构成身份依据。正常会话不包含旧 JSON 读取、导出、删除或一次性迁移。

平台探测和登录交互留在 TikTok 层。业务预检和上传共享 session；local/managed 的登录、验证及提交阶段错误保持 10/9 与 publish_attempted，真实 no-publish 停止点保持。本地路径删除语言切换、lang=en、locale 等额外覆盖，不改变 Patchright 默认。新配置示例默认 False，用户原 conf.py 的 True 未修改。

[验证记录](../research/02-browser-validation.md)列出全部浏览器来源与证据。无本票阻塞。第一批其余三个平台仍待 03–05 接入；后续所有平台、一次性旧资料迁移和四平台真实 no-publish 验收不在本票完成声明内。

## Comments

### 2026-11-17 — 实施与实际验证

- 独立 worktree `/private/tmp/sau-local-profile-02`，分支 `codex/local-profile-02`，基于 integration `508967f`（包含 01）；所有 Python 运行使用该 worktree conf.py 与共享 Python 3.11.11 interpreter。原用户配置/真实 Cookie/Profile 不作夹具。
- 应用 TDD skill 的已批准 seam：首个 session 测试因缺少模块为 red，补 native persistent lifecycle 后 green；关闭故障覆盖成功为 red，补有界 best-effort cleanup 后 green；正式 check 的旧 JSON 行为/错误码为 red，接入真实 config/Profile/session 后 green；直接 uploader 仍依赖 cookie 和 verification 被误报 1 为 red，迁移后 green；本地登录表单在发布页仍提交并退出 0 为 red，平台 guard 覆盖 local 后退出 10 且零提交为 green。
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_tiktok_local_mode tests.test_tiktok_note_cli tests.test_tiktok_no_publish tests.test_tiktok_exit_codes tests.test_tiktok_settings tests.test_mlx_tiktok tests.test_browser_session tests.test_adspower_browser_session tests.test_runtime_defaults tests.test_publish_cleanup tests.test_local_browser_session tests.test_tiktok_profile_cli tests.test_tiktok_cover tests.test_tiktok_overlays tests.test_tiktok_humanize -v`：**353 tests passed**（9.031 秒）。之后补未配置默认行为和来源诊断，受影响的下面命令另通过。
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_local_browser_session tests.test_tiktok_profile_cli tests.test_local_profile -v`：**39 tests passed**（1.379 秒），包含核心真实子进程争用/释放回归。未重复全仓测试；基线由主 Agent 单独负责。
- 初次旧测试回归为 313 tests、8 failures / 26 errors，均涉及已废弃 Cookie helper/session 内部 mocks、旧 headless/default/语言常量断言；其中旧测试触发 isolated worktree synthetic Profile 的真实 browser 启动，因已知 sandbox EPERM 失败。已移除该测试依赖，改为真实公开编排 + browser boundary fakes。没有把这些失败标为真实平台结果。
- 真实浏览器 smoke 首轮发现 macOS 产品元数据命名差异并安全失败；修复后 **8/8 configurations passed**，每项覆盖两次 normal close、Cookie/localStorage 复用及匿名隔离。脚本见研究记录；整个实测只访问受控 localhost，无真实账号或作品操作。
- 文档同步：配置示例、术语、README、CLI、安装路线、Agent Bootstrap、可独立安装的 TikTok Skill。仅更新技能源，未发布市场。

- 最终托管兼容核验发现原跨平台测试仍 patch 已移除的 TikTok cookie resolver，已改为禁止取得本地 session，并将 headless 配置固定为字面 False。另以 red→green 保留托管原 English 登录探测 URL 与 `ignored=context_kwargs` 启动日志；本地 URL 无 lang 参数、local session 不接收 locale。托管路径/种类仍完全忽略，不新增相关警告。
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_tiktok_profile_cli tests.test_mlx_tiktok tests.test_adspower_video_platforms tests.test_sau_browser_cli tests.test_adspower_cli tests.test_adspower_platform_contract -v`：最终 **123 tests passed**（2.271 秒），包含托管 legacy probe URL / ignored 日志以及本地 language-free URL 外部边界断言。

### 2026-11-17 — 后续重复发布按钮回归修复

- 先在 ticket 02 worktree 合并 integration `c6edef0`，复现 `tests.test_publish_ambiguity.OtherPlatformAmbiguityTests.test_duplicate_publish_buttons_never_pass_media_or_publish_gates` 的 **3 个 TikTok error**：原 DOM fixture 对每个 selector/text 均返回两个匹配，错误地表示登录表单和登录文字也存在；真实 `_guard_login` 因此正确抛出 LoginRequiredError，未进入重复发布按钮检查。
- 仅修改该测试内的 TikTok DOM fixture：发布按钮仍返回两个匹配，登录及其他无关锚点为零。没有修改生产源码、绕开登录 guard、改变 `ambiguous:2` 断言、关闭 no-retry 保护或削弱零点击断言；其他平台 fixture 保持原样。
- Red：上述单测试 **FAILED (errors=3)**，日志 `/private/tmp/sau-local-profile-notes/02-ambiguity-red.log`。Green：同一单测试 **1 passed**（0.035 秒），日志 `02-ambiguity-green.log`。
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_publish_ambiguity tests.test_tiktok_profile_cli tests.test_tiktok_exit_codes tests.test_tiktok_no_publish -v`：**63 tests passed**（1.712 秒），日志 `/private/tmp/sau-local-profile-notes/02-ambiguity-regression.log`。包含其他平台歧义检查、TikTok 登录表单停止、真实 uploader no-publish 停止点与提交后退出码保护；没有浏览器或账号操作。`git diff --check` 通过。
