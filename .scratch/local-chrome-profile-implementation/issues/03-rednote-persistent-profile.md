# 03: Rednote 全流程接入

**What to build:** Rednote 用户在同一平台、别名和浏览器种类下，用 Profile 完成登录、检查、视频和图文发布；已有登录不再依赖 Cookie JSON，检查和发布使用一致的浏览器配置。

**Blocked by:** [02：TikTok 全流程接入持久化 Profile](./02-tiktok-persistent-profile.md)

**Status:** resolved

**批次：** 第一批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 完成本票范围内所有已注册正式动作及可达独立启动、内部预检和直接 uploader 调用的接入，预检与业务复用同一 Browser session 和 Profile 占用；注入会话的业务不另开同目录或自行关闭会话。同步开放本平台 reset-profile，保持 01 的精确目标、无需 binary、占用防护和部分失败契约。
- [x] 正式 CLI 与直接调用采用 02 的来源和 headless 优先级，区分未提供与显式 False；默认 Chrome 有头，允许 Chromium 与自定义路径。只使用所选来源及按实际种类隔离的持久化 Profile，no_viewport，失败不回退；切换同种路径/模式复用资料，未选浏览器无需安装。
- [x] Profile 是唯一登录态来源，删除本平台正式路径的旧 JSON 存在检查、Cookie 预检、storage_state 恢复/导出及旧身份门槛。只有 login 引导登录；缺少 Profile、明确未登录或业务中登录失效退出 10，结束本次业务；探测、页面、权限或必需字段故障退出 1，人机验证保留 reason=verification 与补救提示。正常命令不承担 19 的一次性迁移。
- [x] 允许同别名重新登录不同真实账号及两种浏览器使用不同账号，不新增永久绑定、跨 Profile 身份同步或仅为防换号的比较；原有显式请求目标与历史作品证据继续校验，历史结果不改写或删除。
- [x] 覆盖 login、check、upload-video、upload-note，消除独立 check、上传和 setup 路径中的重复启动、JSON preflight 及写回；沿用平台正向登录/验证证据，网络或页面结构异常不得折叠成 invalid。
- [x] 删除为读取或改写 UA 创建的 probe context；业务探测、素材上传与编辑使用主会话。无固定 viewport 后，按已有滚动、iframe/popup 和覆盖层处理能力验证相关交互，不扩展完整多语言选择器。
- [x] 保留视频/图文发布选项、内容声明、定时与结果判断；离线证明两种正式入口 no-publish 真实传到素材上传、编辑、发布就绪后的提交前停止点。缺少保护先补齐，不在本票进行真实提交或作品删除；真实不发布回归由 20 执行。
- [x] 本地移除项目增加的 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化、locale/语言和无业务依据的权限；保留 Patchright 默认、必要业务脚本、二维码、现有代理、超时、人类化交互、响应监听、发布预算、not-before 及结果文件，不修改界面语言。
- [x] 初始化、正常完成、异常、取消、超时与登录失效按所有权有界清理，取消继续传播，失败不回滚或重建 Profile。已有业务错误、成功、发布结果未知（9）及 publish_attempted 不被清理覆盖；提交后登录/验证异常保留原语义，不自动恢复旧任务或重发。
- [x] 本平台 MLX/AdsPower 仅采用新 headless 来源；忽略本地浏览器选择/路径且不额外报错或警告，不访问本地安装、Profile、锁或旧资料。保留原动作路由、login 限制、provider 参数/日志、CDP 所有权、停止/断开与限流退出 11；尚未迁移的平台保持旧行为。
- [x] 从正式 CLI dispatch 经真实配置解析和共享编排，复用浏览器/平台/provider 边界替身完成相关离线回归；覆盖本票动作、配置传播、旧文件无关、换号、登录分类、重建、资源所有权和提交结果保护，不把 session 整体替换成 parser 测试。直接调用只补缺口，共享能力变化时补跑受影响的跨进程/真实浏览器检查。
- [x] 同步本平台 CLI/平台 skill、配置及登录说明、Agent Bootstrap 和运行依赖说明；只在本平台接入后更新其行为描述，保留未迁移平台的准确说明。交付记录列出覆盖入口、验证命令/实际结果、未迁移平台和未执行项，离线结果不表述为真实平台验收。

## Comments

- 2026-11-17: 开始实施。沿用规格 Testing Decisions 已确认的正式 CLI → 真实配置/Profile/session 边界，只替换浏览器/平台/provider 外部行为；直接调用补足 setup 和 uploader 契约。

- 2026-11-17: 完成 20 项 Rednote 公开边界测试；正式 CLI 经真实配置/Profile/session，外部页面、浏览器和 provider client 替身。单独记录 check/login/视频/图文/故障分类/无头登录/有界探测清理的先红后绿证据。
- 2026-11-17: 152 项相关离线回归通过（3.941s）；18 项真实完整 Chromium 合成 DOM 回归在自然 viewport 下通过（40.510s）。首次沙箱内浏览器权限失败已改用隔离沙箱外执行；话题 JSON parser import 回归已修复并复验。没有真实账号操作。
- 2026-11-17: 旧 JSON/UA/临时 context 路径删除；本地页交由 persistent context 有界清理，避免独立 page.close 卡住生命周期。托管 probe 默认清理、忽略项日志、客户端/所有权与限流保留。共享 01/02 实现未改动，不重复无关跨进程和配置浏览器矩阵。

- 2026-11-17: 提交 `1432316` 后先后合并集成 `9120889` 和 `6d0ead1`（合并提交 `85e2b00`）。冲突仅在共享交付列表、术语和 CLI/安装文档，按 TikTok、Rednote、Instagram 三平台已迁移状态合并，保留 Instagram 作品动作例外。合并后原 152 项加 publish ambiguity 为 **161 tests 全通过（4.375s）**；另跑 **14 项 Instagram Profile CLI 全通过（0.596s）**。工作树差异检查通过，无共享生产 API 改动。

## Answer

Rednote 已完整接入独立持久化 Profile：login/check/视频/图文及直接 setup/uploader 均按新来源/headless 优先级运行，内部预检与业务共用会话和锁。Profile 是唯一登录态；旧 JSON 不参与读写或清理，允许别名重登，两种实际浏览器分别隔离。no-publish 离线证明真实传到上传、编辑、ARM 就绪后停止；取消、清理错误、未知结果及提交后登录/验证保留原语义。

覆盖入口、实际命令、TDD 失败证据、通过结果、文档及未执行范围见 [03 验证记录](../research/03-rednote-validation.md)。新的真实账号验收留待票 20，本票不声明真实平台通过。其他平台继续按实施票分批迁移。
