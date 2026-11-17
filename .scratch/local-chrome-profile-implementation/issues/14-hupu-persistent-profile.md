# 14: 虎扑全流程接入

**What to build:** 虎扑用户使用一个持久化 Profile 完成正式登录、检查和发布，浏览器资料和会话不会因指纹参数调整被另一个 context 替换。

**Blocked by:** [09：抖音全流程接入](./09-douyin-persistent-profile.md)；[10：快手全流程接入](./10-kuaishou-persistent-profile.md)；[11：视频号正式流程接入](./11-tencent-persistent-profile.md)；[12：百家号正式流程接入](./12-baijiahao-persistent-profile.md)

**Status:** resolved

**批次：** 第四批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 完成本票范围内所有已注册正式动作及可达独立启动、内部预检和直接 uploader 调用的接入，预检与业务复用同一 Browser session 和 Profile 占用；注入会话的业务不另开同目录或自行关闭会话。同步开放本平台 reset-profile，保持 01 的精确目标、无需 binary、占用防护和部分失败契约。
- [x] 正式 CLI 与直接调用采用 02 的来源和 headless 优先级，区分未提供与显式 False；默认 Chrome 有头，允许 Chromium 与自定义路径。只使用所选来源及按实际种类隔离的持久化 Profile，no_viewport，失败不回退；切换同种路径/模式复用资料，未选浏览器无需安装。
- [x] Profile 是唯一登录态来源，删除本平台正式路径的旧 JSON 存在检查、Cookie 预检、storage_state 恢复/导出及旧身份门槛。只有 login 引导登录；缺少 Profile、明确未登录或业务中登录失效退出 10，结束本次业务；探测、页面、权限或必需字段故障退出 1，人机验证保留 reason=verification 与补救提示。正常命令不承担 19 的一次性迁移。
- [x] 允许同别名重新登录不同真实账号及两种浏览器使用不同账号，不新增永久绑定、跨 Profile 身份同步或仅为防换号的比较；原有显式请求目标与历史作品证据继续校验，历史结果不改写或删除。
- [x] 覆盖虎扑正式注册登录、检查和发布及其 setup、预检和独立启动；移除为 UA、viewport、webdriver 调整而重建 context 的流程。
- [x] 保留实际业务初始化和页面交互所需脚本，按用途区分后再删除指纹覆盖；平台准备步骤不得悄悄替换持久化 context 或泄漏原资源。
- [x] 离线验证登录、检查、发布始终使用已取得的 Profile 会话，覆盖 setup 失败、窗口/弹窗适配和取消清理；旧上下文重建断言随行为调整，不把旧实现当业务契约。
- [x] 本地移除项目增加的 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化、locale/语言和无业务依据的权限；保留 Patchright 默认、必要业务脚本、二维码、现有代理、超时、人类化交互、响应监听、发布预算、not-before 及结果文件，不修改界面语言。
- [x] 初始化、正常完成、异常、取消、超时与登录失效按所有权有界清理，取消继续传播，失败不回滚或重建 Profile。已有业务错误、成功、发布结果未知（9）及 publish_attempted 不被清理覆盖；提交后登录/验证异常保留原语义，不自动恢复旧任务或重发。
- [x] 本平台 MLX/AdsPower 仅采用新 headless 来源；忽略本地浏览器选择/路径且不额外报错或警告，不访问本地安装、Profile、锁或旧资料。保留原动作路由、login 限制、provider 参数/日志、CDP 所有权、停止/断开与限流退出 11；尚未迁移的平台保持旧行为。
- [x] 从正式 CLI dispatch 经真实配置解析和共享编排，复用浏览器/平台/provider 边界替身完成相关离线回归；覆盖本票动作、配置传播、旧文件无关、换号、登录分类、重建、资源所有权和提交结果保护，不把 session 整体替换成 parser 测试。直接调用只补缺口，共享能力变化时补跑受影响的跨进程/真实浏览器检查。
- [x] 同步本平台 CLI/平台 skill、配置及登录说明、Agent Bootstrap 和运行依赖说明；只在本平台接入后更新其行为描述，保留未迁移平台的准确说明。交付记录列出覆盖入口、验证命令/实际结果、未迁移平台和未执行项，离线结果不表述为真实平台验收。

## Comments

- 2026-11-17: Claimed ticket 14 on `codex/local-profile-14` from integration `b8be345`. Approved test seams are formal CLI dispatch through real configuration/Profile/session orchestration with browser/platform/provider boundary fakes, plus direct uploader gaps and isolated browser DOM evidence. TDD uses one vertical slice at a time. `conf.__file__` and BASE_DIR both resolve to this isolated worktree. No ADR directory exists.

- 2026-11-17: Implemented all registered Hupu local actions and direct setup/uploader paths. Removed context recreation, Cookie JSON flows and hidden precheck launch; all local business uses the acquired persistent context. Managed ignored-option startup logs and probe/ownership behavior remain; optional conf attributes are no longer module import requirements. See [14 validation](../research/14-hupu-validation.md) for exact entry points and red/green evidence.
- 2026-11-17: Executed 323 related offline/shared/provider/CLI tests, all passed in 17.825s. Executed actual Chrome headed/full Chromium headless controlled DOM test: 1 test, two flows, four persistent launches, passed in 90.141s. No real platform account operations; temporary roots and locally fulfilled requests only. Updated Hupu CLI/skill, bootstrap, install/config docs and completed-platform lists. Final latest-integration merge remains before delivery.

- 2026-11-17: Merged integration `fb9be5d` (Weibo ticket 13) into this branch as `4706bef`; resolved shared docs/reset lists by retaining both platforms. Post-merge affected suite (the 323-test command plus `tests.test_weibo_profiles tests.test_weibo_humanize`) passed **364 tests in 20.355s**. `git diff --check` passed. No shared runtime API changes.

## Answer

Hupu's complete formal local surface and direct uploader/setup routes now use one persistent Profile session, with reset support, source/headless defaults and strict login/fault separation. Removed the old context replacement and Cookie state paths, while retaining QR/popup and business interactions. Owned cleanup is bounded by the shared session, cancellation propagates, and submission outcome/attempt semantics are protected. Managed behavior and historical ignored-option logs remain except for approved headless resolution.

Evidence: [14 validation](../research/14-hupu-validation.md), 364 final related offline checks and two actual controlled browser flows. No Hupu account or real publication/deletion was performed. Remaining un-migrated platforms at final merge: Alipay, Dayu, Zhihu and Xueqiu; Bilibili biliup remains excluded. One-time legacy-state work and final real four-platform no-publish acceptance remain tickets 19 and 20.
