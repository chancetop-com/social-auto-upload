# 12: 百家号正式流程接入

**What to build:** 百家号用户复用 Profile 完成登录、检查和视频发布，获得清晰的登录失效与运行故障结果，并能独立重建所选浏览器资料。

**Blocked by:** [06：YouTube 全流程接入](./06-youtube-persistent-profile.md)；[07：Facebook 全流程与作品管理接入](./07-facebook-persistent-profile.md)；[08：Facebook Page 全流程接入](./08-facebook-page-persistent-profile.md)

**Status:** resolved

**批次：** 第三批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 完成本票范围内所有已注册正式动作及可达独立启动、内部预检和直接 uploader 调用的接入，预检与业务复用同一 Browser session 和 Profile 占用；注入会话的业务不另开同目录或自行关闭会话。同步开放本平台 reset-profile，保持 01 的精确目标、无需 binary、占用防护和部分失败契约。
- [x] 正式 CLI 与直接调用采用 02 的来源和 headless 优先级，区分未提供与显式 False；默认 Chrome 有头，允许 Chromium 与自定义路径。只使用所选来源及按实际种类隔离的持久化 Profile，no_viewport，失败不回退；切换同种路径/模式复用资料，未选浏览器无需安装。
- [x] Profile 是唯一登录态来源，删除本平台正式路径的旧 JSON 存在检查、Cookie 预检、storage_state 恢复/导出及旧身份门槛。只有 login 引导登录；缺少 Profile、明确未登录或业务中登录失效退出 10，结束本次业务；探测、页面、权限或必需字段故障退出 1，人机验证保留 reason=verification 与补救提示。正常命令不承担 19 的一次性迁移。
- [x] 允许同别名重新登录不同真实账号及两种浏览器使用不同账号，不新增永久绑定、跨 Profile 身份同步或仅为防换号的比较；原有显式请求目标与历史作品证据继续校验，历史结果不改写或删除。
- [x] 覆盖百家号正式 login、check、视频发布及其可达 setup、预检和独立启动，消除旧登录态文件前置条件与内部固定无头。
- [x] 保持视频业务、现有发布参数、预算、原生定时及结果判断；只有明确未登录或验证才走对应退出 10，网络、页面结构、权限和必要字段错误保留故障原因及退出 1。
- [x] 离线验证全部正式动作、配置传播、Profile 重用和重建边界，以及提交前/后异常与清理优先级；通过受影响窗口交互回归验收，不新增真实账号要求。
- [x] 本地移除项目增加的 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化、locale/语言和无业务依据的权限；保留 Patchright 默认、必要业务脚本、二维码、现有代理、超时、人类化交互、响应监听、发布预算、not-before 及结果文件，不修改界面语言。
- [x] 初始化、正常完成、异常、取消、超时与登录失效按所有权有界清理，取消继续传播，失败不回滚或重建 Profile。已有业务错误、成功、发布结果未知（9）及 publish_attempted 不被清理覆盖；提交后登录/验证异常保留原语义，不自动恢复旧任务或重发。
- [x] 本平台 MLX/AdsPower 仅采用新 headless 来源；忽略本地浏览器选择/路径且不额外报错或警告，不访问本地安装、Profile、锁或旧资料。保留原动作路由、login 限制、provider 参数/日志、CDP 所有权、停止/断开与限流退出 11；尚未迁移的平台保持旧行为。
- [x] 从正式 CLI dispatch 经真实配置解析和共享编排，复用浏览器/平台/provider 边界替身完成相关离线回归；覆盖本票动作、配置传播、旧文件无关、换号、登录分类、重建、资源所有权和提交结果保护，不把 session 整体替换成 parser 测试。直接调用只补缺口，共享能力变化时补跑受影响的跨进程/真实浏览器检查。
- [x] 同步本平台 CLI/平台 skill、配置及登录说明、Agent Bootstrap 和运行依赖说明；只在本平台接入后更新其行为描述，保留未迁移平台的准确说明。交付记录列出覆盖入口、验证命令/实际结果、未迁移平台和未执行项，离线结果不表述为真实平台验收。


## Comments

- 2026-11-17：完成批准的 TDD 边界：正式 CLI dispatch → 真实 config/Profile/session → 浏览器/DOM/provider 外部替身。实际红→绿覆盖旧 launch、错误浏览器预检、登录/验证分类、提交后阶段、必填封面/进度故障、二次诊断覆盖主异常和 login 等待验证；详见 [12 验证记录](../research/12-baijiahao-validation.md)。
- 全入口核对：login/check/upload-video/reset-profile；直接 baijiahao_setup/baijiahao_cookie_gen/cookie_auth/BaiJiaHaoVideo.main/upload/upload_in。预检和业务仅一个持久化 context/锁；注入 session 不重开或清理所有者。旧 JSON、地理位置权限及硬编码内部 headless 已从本地运行链退出。
- 行为修正证据：明确传入必需封面后 PermissionError 原可被自动封面掩盖并提交，现本地保留故障并不提交；无自定义封面时的原内部自动封面分支、托管封面与现有 AI/合集可选容错保留。自然 macOS 窗口中 Control+A 留下原文件名，受控 DOM 红测后仅本地改为 ControlOrMeta+A；托管序列不变。
- 实际结果：372 项离线/所有权/跨进程/provider/发布预算/人类化/CLI 回归通过（12.925s）。真实受控 DOM 1 项、Chrome 有头与完整 Chromium 无头两条合成登录/视频流程通过（最终 117.795s），验证自然窗口滚动、标题/封面/声明/合集和单次模拟提交。共享 Profile/config/session 生产代码未修改，沿用 02 的浏览器来源矩阵。
- 同步 CLI 文档、平台独立 skill、配置说明、README、安装依赖、Bootstrap 与术语表。百家号仍无原生 schedule/no-publish；没有以真实发布验收。未登录真实账号、上传真实素材、发布或删除作品，托管仅离线测试；19/20 留待各票。无本票未解决阻塞。

- 最终集成：实现提交 a7034da 后合入 Tencent 11（a9626ca → 0cfd5f2），207 项相关回归通过（17.816s）；再合入最新集成 02f2362（含 Douyin 09），累计平台列表与共享守卫均取并集，221 项三平台/共享回归通过（20.416s）。百家号生产/受控 DOM 路径未因合并变化，沿用真实合成浏览器证据。

## Answer

百家号全部正式动作及可达直接调用使用按原始别名和实际浏览器种类隔离的持久化本地 Profile。只有 login 引导登录/验证，旧 JSON 不再读写；check 和视频预检要求当前正向业务证据，故障、登录与验证保持独立结果。视频预检/业务共用 Profile 占用，提交阶段和有界清理保护成功、9、10 与 publish_attempted；reset 仅重建指定资料。托管只采用批准的 headless 来源，原探测、参数日志、路由与所有权保留。全部验收和未执行范围见验证记录。
