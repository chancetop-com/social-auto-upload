# 11: 视频号正式流程接入

**What to build:** 视频号用户通过本地浏览器 Profile 登录、检查并发布视频，能显式重建指定浏览器资料；预检与视频发布使用相同配置和登录会话。

**Blocked by:** [06：YouTube 全流程接入](./06-youtube-persistent-profile.md)；[07：Facebook 全流程与作品管理接入](./07-facebook-persistent-profile.md)；[08：Facebook Page 全流程接入](./08-facebook-page-persistent-profile.md)

**Status:** resolved

**批次：** 第三批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 完成本票范围内所有已注册正式动作及可达独立启动、内部预检和直接 uploader 调用的接入，预检与业务复用同一 Browser session 和 Profile 占用；注入会话的业务不另开同目录或自行关闭会话。同步开放本平台 reset-profile，保持 01 的精确目标、无需 binary、占用防护和部分失败契约。
- [x] 正式 CLI 与直接调用采用 02 的来源和 headless 优先级，区分未提供与显式 False；默认 Chrome 有头，允许 Chromium 与自定义路径。只使用所选来源及按实际种类隔离的持久化 Profile，no_viewport，失败不回退；切换同种路径/模式复用资料，未选浏览器无需安装。
- [x] Profile 是唯一登录态来源，删除本平台正式路径的旧 JSON 存在检查、Cookie 预检、storage_state 恢复/导出及旧身份门槛。只有 login 引导登录；缺少 Profile、明确未登录或业务中登录失效退出 10，结束本次业务；探测、页面、权限或必需字段故障退出 1，人机验证保留 reason=verification 与补救提示。正常命令不承担 19 的一次性迁移。
- [x] 允许同别名重新登录不同真实账号及两种浏览器使用不同账号，不新增永久绑定、跨 Profile 身份同步或仅为防换号的比较；原有显式请求目标与历史作品证据继续校验，历史结果不改写或删除。
- [x] 覆盖视频号正式注册的 login、check、视频发布及其内部探测与独立启动；未注册的 note 不扩为本票范围，不为迁移新增图文业务入口。
- [x] 去除本地 Cookie 预检和内部固定无头；保留扫码登录、已有发布选项、原生定时与结果判断，页面/网络故障不得包装为登录失效。
- [x] 离线覆盖登录、检查、视频发布和 reset-profile 的正式派发，证明选择配置传到实际启动边界、缺少 Profile 提示登录、取消/关闭故障不破坏业务结果。
- [x] 本地移除项目增加的 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化、locale/语言和无业务依据的权限；保留 Patchright 默认、必要业务脚本、二维码、现有代理、超时、人类化交互、响应监听、发布预算、not-before 及结果文件，不修改界面语言。
- [x] 初始化、正常完成、异常、取消、超时与登录失效按所有权有界清理，取消继续传播，失败不回滚或重建 Profile。已有业务错误、成功、发布结果未知（9）及 publish_attempted 不被清理覆盖；提交后登录/验证异常保留原语义，不自动恢复旧任务或重发。
- [x] 本平台 MLX/AdsPower 仅采用新 headless 来源；忽略本地浏览器选择/路径且不额外报错或警告，不访问本地安装、Profile、锁或旧资料。保留原动作路由、login 限制、provider 参数/日志、CDP 所有权、停止/断开与限流退出 11；尚未迁移的平台保持旧行为。
- [x] 从正式 CLI dispatch 经真实配置解析和共享编排，复用浏览器/平台/provider 边界替身完成相关离线回归；覆盖本票动作、配置传播、旧文件无关、换号、登录分类、重建、资源所有权和提交结果保护，不把 session 整体替换成 parser 测试。直接调用只补缺口，共享能力变化时补跑受影响的跨进程/真实浏览器检查。
- [x] 同步本平台 CLI/平台 skill、配置及登录说明、Agent Bootstrap 和运行依赖说明；只在本平台接入后更新其行为描述，保留未迁移平台的准确说明。交付记录列出覆盖入口、验证命令/实际结果、未迁移平台和未执行项，离线结果不表述为真实平台验收。


## Comments

- 2026-11-17：从集成 `821e161` 创建独立工作树；读取批准的 Testing Decisions，按 CLI → 真实配置/Profile/session → 浏览器/平台/provider 边界执行 TDD。login/check、严格正向登录分类、视频单会话、提交后失效、提交后页面故障、QR callback 取消、QR 刷新路径均记录 red → green；详见 [11 验证记录](../research/11-tencent-validation.md)。
- 入口核对：正式 login/check/upload-video/reset-profile；直接 tencent_setup/weixin_setup/tencent_cookie_gen/get_tencent_cookie/cookie_auth/TencentVideo 的 upload/tencent_upload_video/main。视频预检与操作共用 Profile 占用，注入会话不自行启动/关闭。未注册 note 没有新增 CLI 入口，其旧独立启动链属于范围外。
- 浏览器证据：2 项真实 Chrome 157.0.8103.79、独立临时持久化 Profile、no_viewport 受控 DOM 测试通过（21.362s）；QR iframe、正向/空白/验证分类、iframe 文件输入、元数据填写、视口外提交滚动均实际运行。既有实名验证截图/恢复 DOM 测试另 1 项通过。全部网页请求本地 fulfill 或 set_content，没有真实平台访问。
- 最终离线 233 tests 通过（10.416s），其中 Tencent CLI/Profile 22 tests；命令见验证记录。`sau tencent --help` 仅注册 reset-profile/login/check/upload-video。共享 Profile/session 生产代码不变，保留 02 已完成的来源矩阵实测。旧 JSON 写回/双重关闭测试只替换 TencentVideo 部分，provider 与 TencentNote 既有覆盖保留。
- 未执行真实账号登录、视频上传/发布、草稿或作品删除；MLX/AdsPower 仅离线回归。旧资料作业 19、四平台 no-publish 真实验收 20 留待各票；本票不把离线或受控 DOM 结果表述为平台发布验收。无未解决阻塞。

## Answer

视频号全部正式本地动作与可达直接视频调用已使用按平台、原始别名和实际浏览器种类隔离的持久化 Profile。只有 login 引导扫码，旧 JSON 不再访问；内部预检与视频共用会话/占用，配置优先级和显式重建完整接入。保留二维码/iframe、发布选项、定时、人类化与结果语义；本地明确失效/验证、网络/页面故障及提交后结果区分正确，取消和关闭故障不改写主要结果。托管仅采用批准的 headless 来源，其余行为/日志保留。CLI、平台独立 skill、配置/安装、Bootstrap、README 与术语已同步。
