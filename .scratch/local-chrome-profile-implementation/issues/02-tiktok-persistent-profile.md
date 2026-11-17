# 02: TikTok 全流程接入持久化 Profile

**What to build:** TikTok 用户可用同一个本地浏览器 Profile 完成登录、检查、视频和图文发布及重建；默认 Chrome 有头，显式选择的浏览器和运行模式在整个动作中保持一致。以该完整流程交付其余平台复用的持久化 Browser session，并取得真实浏览器证据。

**Blocked by:** [01：安全定位、占用与重建本地 Profile](./01-profile-ownership-and-reset.md)

**Status:** ready-for-agent

**批次：** 第一批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [ ] 覆盖 TikTok 已注册 login、check、upload-video、upload-note、reset-profile，以及正式 CLI 可达的独立上传、内部预检和直接 uploader 调用；平台正向登录证据和页面交互留在平台层，新共享入口输出真实 local 模式的 Browser session。
- [ ] 浏览器配置遵守：非空 LOCAL_CHROME_PATH 作为 executable_path 优先；无路径覆盖时显式 local-browser > LOCAL_BROWSER > chrome。Chrome 使用系统 chrome channel，Chromium 使用项目固定 Patchright 配套完整 chromium channel，有头/无头均不改用 headless shell，仅要求实际选择来源可用。
- [ ] headless 采用显式 headed/headless 或直接调用显式布尔值 > LOCAL_CHROME_HEADLESS > False，区分未提供和显式 False；新示例默认 False，保留用户已有 True。同一动作的登录探测、内部预检和业务使用同次解析结果。
- [ ] 生效配置非法或互斥参数冲突退出 2；所选来源失败立即停止，不切换 binary、种类或无头模式。诊断只据实际证据区分浏览器缺失、路径/权限、显示服务、系统库或兼容性故障，并标明实际来源。
- [ ] 标准 channel 提供已知浏览器种类；自定义可执行文件在打开任何账号 Profile 前，以限时的可靠产品信息识别种类，无法识别或证据冲突退出 1。文件名、配置名、UA 或 CDP Chrome 字样不能单独作证据；记录已知来源、指定/可靠解析路径及版本，未知如实标注。
- [ ] 使用持久化 context、已选 Profile、解析后的 headless 和 no_viewport；接入 01 的归属与占用，锁覆盖元数据、启动、初始化、预检、业务、关闭和结果处理。内部检查复用 session 和锁，注入 session 的业务不重开或关闭它。
- [ ] 同种浏览器改变来源路径、版本或有头模式仍复用资料；不同种类隔离且不复制凭据，版本变化不自动重建。缺少另一种类 Profile 的非 login 动作提示先登录。
- [ ] Profile 是唯一登录态来源，正式流程不检查、恢复或导出旧 JSON，也不包含一次性迁移。只有 login 引导登录；Profile 缺少、明确未登录或业务中失效退出 10，不在业务中等待重新登录后续跑。目录存在不代替当前正向登录证据。
- [ ] 同别名允许重新登录其他真实账号，两种浏览器允许不同账号；不引入永久绑定或仅为防换号的前后比较。网络、权限、页面结构或必要字段提取失败退出 1；人机验证保留 reason=verification、退出 10 及补救提示。
- [ ] 移除本地 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化和语言覆盖，包括 TikTok 语言导航参数及站点 change_language；保留 Patchright 默认、二维码、业务脚本、超时、DOM 稳定检测、人类化交互、响应监听及现有业务配置。
- [ ] 取得资源后立即建立清理保护，覆盖部分初始化、setup、正常完成、异常、取消、超时和登录失效；清理可重复调用且有界，取消继续传播。正常关闭 persistent context 后不重复关闭其 browser，故障不回滚或重建 Profile，不抢占残留浏览器。
- [ ] 保留发布预算、not-before、结果文件和提交至多一次的边界；publish_attempted、退出 9 的发布结果未知、提交后登录/验证异常保持原语义，主业务错误优先，已确认成功后的关闭故障仅独立警告。崩溃、重新登录或重建不自动恢复旧任务或重发。
- [ ] MLX/AdsPower 只调整本平台 headless 默认来源；忽略本地浏览器选择与路径且不为其报错/警告，不检查安装或触碰本地资料、锁与旧文件。原 provider 参数、CDP、所有权、日志、退出 11 及 login 托管限制保持。
- [ ] 新共享能力由本票显式接入；其他平台保留旧 parser、构造器和运行默认，避免提前切换。第一批以 01–05 全部完成为交付边界，不能仅改共享旧入口就宣称覆盖四平台。
- [ ] 从正式 CLI dispatch 驱动真实配置解析、Profile 编排和生命周期，只替换浏览器/平台外部边界；复用既有 FakePlaywright、context、browser 和 provider。覆盖选定/非选定来源、显式/缺省参数、登录分类、别名换号、资源失败、结果保护及托管隔离；直接 uploader 只补 CLI 不能证明的契约。
- [ ] 由实施 Agent 在隔离临时 Profile 和具有正常 origin 的受控页面上实测 Chrome/Chromium 各自有头、无头、自定义路径、关闭重开后存储复用、主 Profile 与匿名 context 状态隔离；记录实际浏览器、配置、命令和结果，不用模拟替代。系统 Chrome 仍由用户自行安装，环境或必要交互缺失时明确记录阻塞。
- [ ] 确认 TikTok 视频/图文 no-publish 参数传到实际停止点；缺少保护时先补齐并离线验证，在素材上传、编辑和发布就绪后、最终提交前停止。本票不执行真实平台发布或删除，四平台真实不发布回归留给 20。
- [ ] 同步配置示例、TikTok CLI/平台 skill、登录说明、Agent Bootstrap 和安装依赖说明；浏览器按需准备，系统 Chrome 官方安装与项目配套完整 Chromium 两条路线清晰，保留未迁移平台所需说明。更新本地模式术语的阶段现状，记录覆盖入口、离线/浏览器结果及尚未迁移平台。
