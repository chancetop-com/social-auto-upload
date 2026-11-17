# 06: YouTube 全流程接入

**What to build:** YouTube 用户使用持久化 Profile 完成正式登录、检查和发布，并可明确重建所选浏览器资料；登录探测与发布沿用同一次配置和资源所有权。

**Blocked by:** [03：Rednote 全流程接入](./03-rednote-persistent-profile.md)；[04：Instagram 全流程与作品管理接入](./04-instagram-persistent-profile.md)；[05：小红书全流程接入](./05-xiaohongshu-persistent-profile.md)

**Status:** resolved

**批次：** 第二批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 完成本票范围内所有已注册正式动作及可达独立启动、内部预检和直接 uploader 调用的接入，预检与业务复用同一 Browser session 和 Profile 占用；注入会话的业务不另开同目录或自行关闭会话。同步开放本平台 reset-profile，保持 01 的精确目标、无需 binary、占用防护和部分失败契约。
- [x] 正式 CLI 与直接调用采用 02 的来源和 headless 优先级，区分未提供与显式 False；默认 Chrome 有头，允许 Chromium 与自定义路径。只使用所选来源及按实际种类隔离的持久化 Profile，no_viewport，失败不回退；切换同种路径/模式复用资料，未选浏览器无需安装。
- [x] Profile 是唯一登录态来源，删除本平台正式路径的旧 JSON 存在检查、Cookie 预检、storage_state 恢复/导出及旧身份门槛。只有 login 引导登录；缺少 Profile、明确未登录或业务中登录失效退出 10，结束本次业务；探测、页面、权限或必需字段故障退出 1，人机验证保留 reason=verification 与补救提示。正常命令不承担 19 的一次性迁移。
- [x] 允许同别名重新登录不同真实账号及两种浏览器使用不同账号，不新增永久绑定、跨 Profile 身份同步或仅为防换号的比较；原有显式请求目标与历史作品证据继续校验，历史结果不改写或删除。
- [x] 逐项覆盖 YouTube 已注册登录、检查、发布及已有作品管理动作，连同这些动作实际可达的 setup、内部预检与独立启动；以正式注册清单为边界，不新增历史脚本入口或无关业务功能。
- [x] 保留现有视频上传、频道/显式目标选择、原生定时、结果判断和作品证据规则；去掉浏览器/语言覆盖后，按实际改动验证页面滚动、弹窗或覆盖层处理。
- [x] 本票依赖第一批平台全部完成是已批准的批次顺序；与 07、08 无相互依赖。通过相关离线回归验收，无需新增 YouTube 真实账号或托管服务回归。
- [x] 本地移除项目增加的 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化、locale/语言和无业务依据的权限；保留 Patchright 默认、必要业务脚本、二维码、现有代理、超时、人类化交互、响应监听、发布预算、not-before 及结果文件，不修改界面语言。
- [x] 初始化、正常完成、异常、取消、超时与登录失效按所有权有界清理，取消继续传播，失败不回滚或重建 Profile。已有业务错误、成功、发布结果未知（9）及 publish_attempted 不被清理覆盖；提交后登录/验证异常保留原语义，不自动恢复旧任务或重发。
- [x] 本平台 MLX/AdsPower 仅采用新 headless 来源；忽略本地浏览器选择/路径且不额外报错或警告，不访问本地安装、Profile、锁或旧资料。保留原动作路由、login 限制、provider 参数/日志、CDP 所有权、停止/断开与限流退出 11；尚未迁移的平台保持旧行为。
- [x] 从正式 CLI dispatch 经真实配置解析和共享编排，复用浏览器/平台/provider 边界替身完成相关离线回归；覆盖本票动作、配置传播、旧文件无关、换号、登录分类、重建、资源所有权和提交结果保护，不把 session 整体替换成 parser 测试。直接调用只补缺口，共享能力变化时补跑受影响的跨进程/真实浏览器检查。
- [x] 同步本平台 CLI/平台 skill、配置及登录说明、Agent Bootstrap 和运行依赖说明；只在本平台接入后更新其行为描述，保留未迁移平台的准确说明。交付记录列出覆盖入口、验证命令/实际结果、未迁移平台和未执行项，离线结果不表述为真实平台验收。


## Comments

- 2026-11-17：按已批准 CLI→真实配置/Profile/session 边界使用 TDD；红绿证据、入口清单、执行命令和限制见 [06 验证记录](../research/06-youtube-validation.md)。首轮登录/上传旧路径、权限/验证分类、点击可能派发后的阶段标记、上传跳登录后的超时分类均先出现失败，再通过实现修正。
- 2026-11-17：最终针对性离线回归 **240 项通过**，其中新 YouTube Profile CLI/直接调用测试 22 项；共享 Profile 回归包含真实进程互斥和 reset 部分失败。`git diff --check` 与修改文件编译检查通过。
- 2026-11-17：隔离完整 Chromium 156.0.8078.4 的自然 viewport 合成页面实测两次通过（末次为最终导航实现）：756×469，真实人类化交互完成标题/简介回读、播放列表选择及浮层关闭、页面滚动、单次合成提交。首次 sandbox 启动被 EPERM/SIGABRT 阻止；reviewed outside-sandbox 执行成功。所有请求均由本地 HTML 响应；未操作任何真实账号、上传、发布或删除。
- 扩大到 272 项的中间回归曾暴露两项已有 Instagram `resolve_account_file` 替身错误；04 独立修复，06 未改相关 hunk。合并 integration `7646984` 后连同 `tests.test_multilogin_cli` 复验 **273 项通过（8.902 秒）**，无剩余失败。原生 `--schedule` 在本平台原本未实现，仍提前退出 2；本票保留 not-before，没有新增原生定时或 no-publish 功能。

## Answer

YouTube 全部正式动作 login/check/upload-video 与新增 reset-profile 已迁移；setup、旧名兼容调用与直接 uploader 只用持久化 Profile。预检和业务共用 context/锁，注入会话不重开或自行关闭；本地代理、字段/可见性/播放列表、人类化层、预算与 not-before 保留。JSON 恢复/存在检查/导出、stealth 和固定本地窗口参数已退出；常规命令不承担一次性迁移。

本地缺资料/登录/验证为 10，故障为 1；未知提交为 9，提交后登录仍保留 publish_attempted。托管只改 headless 来源，保留原探测、忽略参数日志、资源所有权、登录限制和限流契约。配置示例、CLI、平台独立 skill、README、安装、Bootstrap 与术语已同步。此票的离线与合成浏览器验收完成；07/08 为并行平台票，后续平台保持旧路径，旧资料作业及四平台真实不发布验收分别留给 19/20。
