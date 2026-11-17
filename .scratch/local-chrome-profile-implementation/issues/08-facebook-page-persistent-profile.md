# 08: Facebook Page 全流程接入

**What to build:** Facebook Page 用户以一个 Page 登录 Profile 管理多个发布目标，完成登录、检查、视频/图文发布和已有作品管理；目标核验保持，资料与 Facebook 独立。

**Blocked by:** [03：Rednote 全流程接入](./03-rednote-persistent-profile.md)；[04：Instagram 全流程与作品管理接入](./04-instagram-persistent-profile.md)；[05：小红书全流程接入](./05-xiaohongshu-persistent-profile.md)

**Status:** resolved

**批次：** 第二批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 完成本票范围内所有已注册正式动作及可达独立启动、内部预检和直接 uploader 调用的接入，预检与业务复用同一 Browser session 和 Profile 占用；注入会话的业务不另开同目录或自行关闭会话。同步开放本平台 reset-profile，保持 01 的精确目标、无需 binary、占用防护和部分失败契约。
- [x] 正式 CLI 与直接调用采用 02 的来源和 headless 优先级，区分未提供与显式 False；默认 Chrome 有头，允许 Chromium 与自定义路径。只使用所选来源及按实际种类隔离的持久化 Profile，no_viewport，失败不回退；切换同种路径/模式复用资料，未选浏览器无需安装。
- [x] Profile 是唯一登录态来源，删除本平台正式路径的旧 JSON 存在检查、Cookie 预检、storage_state 恢复/导出及旧身份门槛。只有 login 引导登录；缺少 Profile、明确未登录或业务中登录失效退出 10，结束本次业务；探测、页面、权限或必需字段故障退出 1，人机验证保留 reason=verification 与补救提示。正常命令不承担 19 的一次性迁移。
- [x] 允许同别名重新登录不同真实账号及两种浏览器使用不同账号，不新增永久绑定、跨 Profile 身份同步或仅为防换号的比较；原有显式请求目标与历史作品证据继续校验，历史结果不改写或删除。
- [x] 覆盖 login、check、视频/图文发布及已有 verify/delete，包括独立作品操作启动和读写清理；沿用各动作既有本地/托管路由。
- [x] 按正式平台 facebook-page、账号别名和实际浏览器种类定位 Profile，与 Facebook 隔离；多个 Page 发布目标复用该登录 Profile，不按 Page 另建登录容器。
- [x] 显式 page 等目标请求必须核对，未指定时保留既有目标选择语义；作品操作继续核对原 Page、作品、作者及原操作要求的当前主体一致性，不以账号别名替代这些证据。
- [x] 保留已注册定时、作品标识和内容证据参数、原代理及结果输出；以离线行为证明不同 Page 复用登录、显式目标不匹配被拒绝、历史作品不被换号重新解释，不实际删除作品。
- [x] 本地移除项目增加的 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化、locale/语言和无业务依据的权限；保留 Patchright 默认、必要业务脚本、二维码、现有代理、超时、人类化交互、响应监听、发布预算、not-before 及结果文件，不修改界面语言。
- [x] 初始化、正常完成、异常、取消、超时与登录失效按所有权有界清理，取消继续传播，失败不回滚或重建 Profile。已有业务错误、成功、发布结果未知（9）及 publish_attempted 不被清理覆盖；提交后登录/验证异常保留原语义，不自动恢复旧任务或重发。
- [x] 本平台 MLX/AdsPower 仅采用新 headless 来源；忽略本地浏览器选择/路径且不额外报错或警告，不访问本地安装、Profile、锁或旧资料。保留原动作路由、login 限制、provider 参数/日志、CDP 所有权、停止/断开与限流退出 11；尚未迁移的平台保持旧行为。
- [x] 从正式 CLI dispatch 经真实配置解析和共享编排，复用浏览器/平台/provider 边界替身完成相关离线回归；覆盖本票动作、配置传播、旧文件无关、换号、登录分类、重建、资源所有权和提交结果保护，不把 session 整体替换成 parser 测试。直接调用只补缺口，共享能力变化时补跑受影响的跨进程/真实浏览器检查。
- [x] 同步本平台 CLI/平台 skill、配置及登录说明、Agent Bootstrap 和运行依赖说明；只在本平台接入后更新其行为描述，保留未迁移平台的准确说明。交付记录列出覆盖入口、验证命令/实际结果、未迁移平台和未执行项，离线结果不表述为真实平台验收。


## Comments

- 2026-11-17：按批准的 CLI → 真配置/Profile/session → 浏览器/平台/provider 边界执行 TDD。逐步记录了旧 JSON check、登录/验证分类、login 创建、上传独立启动、提交后失效、作品操作、reset 注册、业务 HTTP 错误及 Page 前缀错配的失败，再完成最小接入并复验；详见 [08 验证记录](../research/08-facebook-page-validation.md)。不替换整个 session 来测试 parser。
- 入口核对：正式 login/check/upload-video/upload-note/verify/delete/reset-profile；直接 meta_setup/meta_cookie_auth/MetaBusinessUploader.upload/meta_post_action；预检与业务共享一个 Profile 占用。保持已有 Page/内容编号/配文、排期、not-before、代理、结果文件及托管路由。
- 最终证据：合入集成 c5a3141 后 252 项离线/所有权/跨平台回归通过（16.798s），10 项受控真实 Chrome/DOM 回归通过（17.805s）。最后对托管 Page 文本读取保留原语义的小调整又跑 74 项 Page CLI/托管/人类化测试，全部通过（1.059s）。共享 Profile/session 生产代码未改，02 的浏览器来源矩阵不重复执行。
- 未执行真实 Page 登录、素材上传、发布或删除；MLX/AdsPower 只做离线回归。旧资料作业 19 与四平台真实不发布验收 20 留待各自票执行；不将本票离线结果冒充真实平台结果。无本票未解决阻塞。

- 2026-11-17 最终集成复验：e4a21a8（含 Facebook 07）已合入为 cab66b3，合并共享平台集合后 270 项 Page/Facebook/YouTube/托管/所有权相关回归通过（16.668s）；Page 生产路径未因合并改变，沿用已完成的 10 项受控浏览器结果。

## Answer

Facebook Page 全部正式动作与可达直接调用使用按正式平台 facebook-page、原始账号别名和实际浏览器种类隔离的持久化 Profile；多个 Page 目标复用登录容器且与 facebook 隔离。只有 login 引导登录，旧 JSON 不再读取/导出；本地登录分类、提交阶段、资源所有权与显式重建完整接入。显式 Page 目标及历史作品证据继续核验，Page 名前缀错配在本地提交前拒绝。托管只采用批准的 headless 来源，原路由、参数日志、探测与所有权保留。CLI、独立平台 skill、安装/配置、Bootstrap、README 与术语同步完成，验证与未执行范围见记录。
