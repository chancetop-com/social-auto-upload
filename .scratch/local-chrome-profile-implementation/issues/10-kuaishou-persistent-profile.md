# 10: 快手全流程接入

**What to build:** 快手用户登录后可从同一持久化 Profile 检查账号并发布视频或图文，内部预检不再以旧 Cookie 或固定无头模式决定运行方式。

**Blocked by:** [06：YouTube 全流程接入](./06-youtube-persistent-profile.md)；[07：Facebook 全流程与作品管理接入](./07-facebook-persistent-profile.md)；[08：Facebook Page 全流程接入](./08-facebook-page-persistent-profile.md)

**Status:** resolved

**批次：** 第三批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 完成本票范围内所有已注册正式动作及可达独立启动、内部预检和直接 uploader 调用的接入，预检与业务复用同一 Browser session 和 Profile 占用；注入会话的业务不另开同目录或自行关闭会话。同步开放本平台 reset-profile，保持 01 的精确目标、无需 binary、占用防护和部分失败契约。
- [x] 正式 CLI 与直接调用采用 02 的来源和 headless 优先级，区分未提供与显式 False；默认 Chrome 有头，允许 Chromium 与自定义路径。只使用所选来源及按实际种类隔离的持久化 Profile，no_viewport，失败不回退；切换同种路径/模式复用资料，未选浏览器无需安装。
- [x] Profile 是唯一登录态来源，删除本平台正式路径的旧 JSON 存在检查、Cookie 预检、storage_state 恢复/导出及旧身份门槛。只有 login 引导登录；缺少 Profile、明确未登录或业务中登录失效退出 10，结束本次业务；探测、页面、权限或必需字段故障退出 1，人机验证保留 reason=verification 与补救提示。正常命令不承担 19 的一次性迁移。
- [x] 允许同别名重新登录不同真实账号及两种浏览器使用不同账号，不新增永久绑定、跨 Profile 身份同步或仅为防换号的比较；原有显式请求目标与历史作品证据继续校验，历史结果不改写或删除。
- [x] 覆盖 login、check、upload-video、upload-note 及可达 setup/上传入口；视频与图文均移除 Cookie 缺失/过期的旧前置路径，内部探测与业务同会话、同配置。
- [x] 保留原生定时、发布策略、合集、封面等各正式入口已有选项和结果契约，不因统一会话改变视频/图文业务差异。
- [x] 离线验证两个内容入口的配置、登录状态、初始化失败、注入会话所有权和提交后结果保护；无固定 viewport 后验证本票实际受影响的控件可用性。
- [x] 本地移除项目增加的 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化、locale/语言和无业务依据的权限；保留 Patchright 默认、必要业务脚本、二维码、现有代理、超时、人类化交互、响应监听、发布预算、not-before 及结果文件，不修改界面语言。
- [x] 初始化、正常完成、异常、取消、超时与登录失效按所有权有界清理，取消继续传播，失败不回滚或重建 Profile。已有业务错误、成功、发布结果未知（9）及 publish_attempted 不被清理覆盖；提交后登录/验证异常保留原语义，不自动恢复旧任务或重发。
- [x] 本平台 MLX/AdsPower 仅采用新 headless 来源；忽略本地浏览器选择/路径且不额外报错或警告，不访问本地安装、Profile、锁或旧资料。保留原动作路由、login 限制、provider 参数/日志、CDP 所有权、停止/断开与限流退出 11；尚未迁移的平台保持旧行为。
- [x] 从正式 CLI dispatch 经真实配置解析和共享编排，复用浏览器/平台/provider 边界替身完成相关离线回归；覆盖本票动作、配置传播、旧文件无关、换号、登录分类、重建、资源所有权和提交结果保护，不把 session 整体替换成 parser 测试。直接调用只补缺口，共享能力变化时补跑受影响的跨进程/真实浏览器检查。
- [x] 同步本平台 CLI/平台 skill、配置及登录说明、Agent Bootstrap 和运行依赖说明；只在本平台接入后更新其行为描述，保留未迁移平台的准确说明。交付记录列出覆盖入口、验证命令/实际结果、未迁移平台和未执行项，离线结果不表述为真实平台验收。


## Comments

- 2026-11-17：按批准的 CLI dispatch → 真配置/Profile/session → 外部浏览器/平台/provider 边界完成 TDD；check、login、双内容入口、登录分类、提交后信号、导航超时和 QR 结果均记录红绿过程。见 [10 验证记录](../research/10-kuaishou-validation.md)。
- 完成 login/check/upload-video/upload-note/reset-profile 与可达 setup/get_ks_cookie/cookie_auth/直接 uploader。预检与业务共用会话和 Profile 占用；仅 login 创建资料。旧 JSON 不读写，不绑定真实账号。
- 实际结果：219 项离线/托管/所有权/人类化/预算回归通过（8.091s）；真实临时 Chrome 560×420 no_viewport 受控页面的两个内容子场景通过（1 项、10.347s）。视频封面/合集、两种内容的正文/定时/单次提交均有 DOM 回读。未执行真实快手账号或发布操作。
- CLI、独立平台 skill、配置/安装/登录、Agent Bootstrap、README 与术语同步；共享生产能力未修改，不重复 02 来源矩阵。未迁移平台保持原行为，详见验证记录。无本票未解决阻塞。

- 2026-11-17 集成复验：合并视频号 11 的 a9626ca，冲突按已迁移平台取并集；加入视频号相关检查后 288 项通过（16.737s）。

- 2026-11-17 最终集成：再合入抖音 09 的 02f2362，累计保留抖音、快手、视频号的迁移/重建清单；302 项相关回归通过（18.299s），快手真实 DOM 结果继续适用。

## Answer

快手所有正式动作与直接调用已接入按原始别名和真实浏览器种类隔离的持久化 Profile；只有 login 引导扫码并在同会话复验。保留视频/图文的发布差异、定时、合集、封面、not-before、QR 回调和提交结果保护。错误、取消与清理遵守所有权，托管仅采用 headless 新来源并保留原路由与生命周期。重建入口、离线与受控真实浏览器验证、平台独立文档均已完成。
