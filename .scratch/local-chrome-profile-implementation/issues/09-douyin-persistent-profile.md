# 09: 抖音全流程接入

**What to build:** 抖音用户使用同一 Profile 完成登录、检查、视频和图文发布，内部检查遵守所选浏览器配置；提交后的异常仍准确表达是否可能已发布。

**Blocked by:** [06：YouTube 全流程接入](./06-youtube-persistent-profile.md)；[07：Facebook 全流程与作品管理接入](./07-facebook-persistent-profile.md)；[08：Facebook Page 全流程接入](./08-facebook-page-persistent-profile.md)

**Status:** resolved

**批次：** 第三批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 完成本票范围内所有已注册正式动作及可达独立启动、内部预检和直接 uploader 调用的接入，预检与业务复用同一 Browser session 和 Profile 占用；注入会话的业务不另开同目录或自行关闭会话。同步开放本平台 reset-profile，保持 01 的精确目标、无需 binary、占用防护和部分失败契约。
- [x] 正式 CLI 与直接调用采用 02 的来源和 headless 优先级，区分未提供与显式 False；默认 Chrome 有头，允许 Chromium 与自定义路径。只使用所选来源及按实际种类隔离的持久化 Profile，no_viewport，失败不回退；切换同种路径/模式复用资料，未选浏览器无需安装。
- [x] Profile 是唯一登录态来源，删除本平台正式路径的旧 JSON 存在检查、Cookie 预检、storage_state 恢复/导出及旧身份门槛。只有 login 引导登录；缺少 Profile、明确未登录或业务中登录失效退出 10，结束本次业务；探测、页面、权限或必需字段故障退出 1，人机验证保留 reason=verification 与补救提示。正常命令不承担 19 的一次性迁移。
- [x] 允许同别名重新登录不同真实账号及两种浏览器使用不同账号，不新增永久绑定、跨 Profile 身份同步或仅为防换号的比较；原有显式请求目标与历史作品证据继续校验，历史结果不改写或删除。
- [x] 覆盖正式 login、check、视频和图文发布，包含 setup、上传 seam 和内部探测；移除本地 Cookie 存在/内容依赖以及内部固定无头，不能仅改 CLI 外层而保留 uploader 的旧启动链。
- [x] 复用既有 session 注入边界，证明预检与业务使用同一会话和占用；直接 uploader 缺省/显式参数遵守新语义，业务函数不接管调用者会话所有权。
- [x] 扩展已有提交后登录/验证异常回归，确保 publish_attempted=true 与既有退出语义穿过 uploader、命令派发及清理层，结果未知和已确认成功均不触发自动重发。
- [x] 保留视频/图文特有选项、定时、预算和人类化交互；验证受参数清理影响的滚动、弹窗或覆盖层。与第三批其余票独立推进，以相关离线证据验收。
- [x] 本地移除项目增加的 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化、locale/语言和无业务依据的权限；保留 Patchright 默认、必要业务脚本、二维码、现有代理、超时、人类化交互、响应监听、发布预算、not-before 及结果文件，不修改界面语言。
- [x] 初始化、正常完成、异常、取消、超时与登录失效按所有权有界清理，取消继续传播，失败不回滚或重建 Profile。已有业务错误、成功、发布结果未知（9）及 publish_attempted 不被清理覆盖；提交后登录/验证异常保留原语义，不自动恢复旧任务或重发。
- [x] 本平台 MLX/AdsPower 仅采用新 headless 来源；忽略本地浏览器选择/路径且不额外报错或警告，不访问本地安装、Profile、锁或旧资料。保留原动作路由、login 限制、provider 参数/日志、CDP 所有权、停止/断开与限流退出 11；尚未迁移的平台保持旧行为。
- [x] 从正式 CLI dispatch 经真实配置解析和共享编排，复用浏览器/平台/provider 边界替身完成相关离线回归；覆盖本票动作、配置传播、旧文件无关、换号、登录分类、重建、资源所有权和提交结果保护，不把 session 整体替换成 parser 测试。直接调用只补缺口，共享能力变化时补跑受影响的跨进程/真实浏览器检查。
- [x] 同步本平台 CLI/平台 skill、配置及登录说明、Agent Bootstrap 和运行依赖说明；只在本平台接入后更新其行为描述，保留未迁移平台的准确说明。交付记录列出覆盖入口、验证命令/实际结果、未迁移平台和未执行项，离线结果不表述为真实平台验收。


## Comments

- 2026-11-17：按批准的 CLI → 实际配置/Profile/session → 浏览器/平台/provider 边界执行 TDD，覆盖全部正式动作与直接 setup/probe/video/note 入口。逐步记录旧 JSON gate、验证分类、login 旧启动链、编辑中失效、提交后断开及 QR 清理覆盖成功的 red→green，见 [09 验证记录](../research/09-douyin-validation.md)。
- 234 项相关离线回归通过（17.824s），最终公共 CLI 声明失败及占用观察补充后 14 项公共测试通过（1.042s）；系统 Chrome 157.0.8103.79 的 2 项隔离受控 DOM 测试通过（15.057s）。共享配置/Profile/session 生产实现未改，保留 02 浏览器矩阵证据。受控页面全部拦截请求，不是真实平台验收。
- 保留托管动作、历史 ignored-option 日志及所有权，仅接入 headless 来源；本地发布不再等待短信输入。直接注入 session 的调用不打开/关闭调用者资源。提交后的登录/验证保留 reason 与 publish_attempted=true，断开/未知结果为 9，不重发。
- 未执行真实账号登录、发布、删除或旧资料迁移；19/20 留待各票。未迁移平台沿用旧行为。无本票未解决阻塞。

- 最终合入检查：集成分支 `821e161` 已是祖先，merge 报告 already up to date；合入后 52 项 Douyin 公共/注入、Profile 与默认参数回归通过（3.739s）。

- 合入 Tencent 11 后（父提交 `a9626ca`）：6 个共享文档/配置说明与 reset-profile 测试文件的冲突按两平台并集合并。首次 74 项检查发现主目录 conf.py 未设置可选 `LOCAL_BROWSER` 时，Douyin 测试的 patch.object 清理报 AttributeError；改为 patch.dict 临时移除并还原配置，保留缺省配置断言，未改生产逻辑。随后 Douyin/Tencent/Profile/cleanup/ambiguity/defaults 共 74 项离线检查通过（9.890s），`git diff --check` 通过。

## Answer

抖音 login/check/视频/图文、直接 uploader/setup/probe 与 reset-profile 全部接入原始别名和实际浏览器种类隔离的持久化 Profile。内部预检和业务复用同一会话与占用，旧 JSON 不再参与，只有 login 引导登录或验证；本地异常分类、提交阶段、取消及有界清理按契约保留。CLI、独立平台 Skill、配置/安装、Bootstrap、README 与术语同步完成；相关离线及真实受控浏览器证据见验证记录。
