# 04: Instagram 全流程与作品管理接入

**What to build:** Instagram 用户可复用 Profile 登录、检查、发布视频/图文和管理已有作品；账号别名可换号，作品管理仍依据原作品证据，原有本地代理继续有效。

**Blocked by:** [02：TikTok 全流程接入持久化 Profile](./02-tiktok-persistent-profile.md)

**Status:** resolved

**批次：** 第一批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 完成本票范围内所有已注册正式动作及可达独立启动、内部预检和直接 uploader 调用的接入，预检与业务复用同一 Browser session 和 Profile 占用；注入会话的业务不另开同目录或自行关闭会话。同步开放本平台 reset-profile，保持 01 的精确目标、无需 binary、占用防护和部分失败契约。
- [x] 正式 CLI 与直接调用采用 02 的来源和 headless 优先级，区分未提供与显式 False；默认 Chrome 有头，允许 Chromium 与自定义路径。只使用所选来源及按实际种类隔离的持久化 Profile，no_viewport，失败不回退；切换同种路径/模式复用资料，未选浏览器无需安装。
- [x] Profile 是唯一登录态来源，删除本平台正式路径的旧 JSON 存在检查、Cookie 预检、storage_state 恢复/导出及旧身份门槛。只有 login 引导登录；缺少 Profile、明确未登录或业务中登录失效退出 10，结束本次业务；探测、页面、权限或必需字段故障退出 1，人机验证保留 reason=verification 与补救提示。正常命令不承担 19 的一次性迁移。
- [x] 允许同别名重新登录不同真实账号及两种浏览器使用不同账号，不新增永久绑定、跨 Profile 身份同步或仅为防换号的比较；原有显式请求目标与历史作品证据继续校验，历史结果不改写或删除。
- [x] 覆盖 login、check、upload-video、upload-note、verify、delete，包括候选 JSON 登录、独立作品操作启动、作品操作写回和异常包装路径；删除候选旧登录态尝试与旧 Cookie 提取历史预期 ID 的行为。
- [x] 按当前会话取得 ds_user_id 等业务必需字段并验证格式与正向登录证据，不将字段提取变成永久账号门槛；已有作品作者/目标要求仍按原契约核对，同别名换号不重新解释历史结果。
- [x] 本地代理在登录、检查、发布及作品操作中继续生效；verify/delete 在设置托管环境变量时仍沿用原本的本地动作路由，不能错误进入 provider 或丢失本地配置。普通托管发布的代理所有权保持原契约。
- [x] 离线覆盖作品核验/删除、旧 JSON 写回退出、字段缺失与提交后异常传播，verify/delete 的验证使用替身而不删除真实作品。视频/图文 no-publish 参数及提交前停止点均经离线验证，保护缺失先补齐，真实回归由 20 执行。
- [x] 本地移除项目增加的 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化、locale/语言和无业务依据的权限；保留 Patchright 默认、必要业务脚本、二维码、现有代理、超时、人类化交互、响应监听、发布预算、not-before 及结果文件，不修改界面语言。
- [x] 初始化、正常完成、异常、取消、超时与登录失效按所有权有界清理，取消继续传播，失败不回滚或重建 Profile。已有业务错误、成功、发布结果未知（9）及 publish_attempted 不被清理覆盖；提交后登录/验证异常保留原语义，不自动恢复旧任务或重发。
- [x] 本平台 MLX/AdsPower 仅采用新 headless 来源；忽略本地浏览器选择/路径且不额外报错或警告，不访问本地安装、Profile、锁或旧资料。保留原动作路由、login 限制、provider 参数/日志、CDP 所有权、停止/断开与限流退出 11；尚未迁移的平台保持旧行为。
- [x] 从正式 CLI dispatch 经真实配置解析和共享编排，复用浏览器/平台/provider 边界替身完成相关离线回归；覆盖本票动作、配置传播、旧文件无关、换号、登录分类、重建、资源所有权和提交结果保护，不把 session 整体替换成 parser 测试。直接调用只补缺口，共享能力变化时补跑受影响的跨进程/真实浏览器检查。
- [x] 同步本平台 CLI/平台 skill、配置及登录说明、Agent Bootstrap 和运行依赖说明；只在本平台接入后更新其行为描述，保留未迁移平台的准确说明。交付记录列出覆盖入口、验证命令/实际结果、未迁移平台和未执行项，离线结果不表述为真实平台验收。


## Answer

Instagram 的 login、check、upload-video、upload-note、verify、delete 及其直接调用已完整接入 02 的 `local_browser_session`；reset-profile 复用 01。配置/锁/持久化生命周期共用已交付 API，无共享核心改动。原始别名用于本地 Profile，当前正向登录证据、有效 ds_user_id 与当前主页提供业务身份；旧 JSON 预检、候选导出、历史期望 ID 和作品操作写回已退出正式路径。原作品作者、编号与正文核验继续生效。

本地只额外传原有代理，不施加 locale、请求头、固定 viewport、最大化或 stealth。登录/探测/业务始终在同一持久化 context 下，注入 session 不启动或关闭其浏览器。仅 login 引导登录；verification 保留 reason，HTTP/页面/字段故障为 1；提交后异常保留 stage、publish_attempted、未知结果和禁止自动重发。作品操作在 provider 环境下仍强制本地配置与原始账号，普通托管流程只改变 headless 来源，其既有常量/忽略参数日志/所有权不变。

同步 README、CLI、安装/配置说明、Agent Bootstrap、术语与可独立安装的 Instagram Skill。未做真实账号登录、发布或删除；四平台真实 no-publish 留给 20，一次性旧资料作业留给 19。此票无阻塞；共享真实浏览器来源/持久化 smoke 沿用 02，本票未改变共享实现。03/05 与第二至五批按各自票据交付，本票仅声明 Instagram 已接入。

## Comments

### 2026-11-17 — 实施与验证

- 在 `/private/tmp/sau-local-profile-04`、`codex/local-profile-04` 实施，使用已批准 CLI → 真实 config/Profile/session → browser/platform/provider 边界替身 seam；应用 TDD 与 writing-for-agents。未启用子 Agent。主分支源码、用户配置、真实 Cookie/Profile 未作为修改目标。
- Red → green：首个正式 check 因旧 JSON 路径退出 1，接入共享 Profile 后成功；login 旧候选路径不能创建 Profile、无效 ds_user_id 被接受，迁移后同别名可换号且非法字段退出 1；视频/图文原来独立临时启动，迁移后真实编排通过素材/编辑/配文并停在 Share 前；verify/delete 仍找旧 resolver，迁移后在两类 provider 环境下都使用本地原始别名、所选种类和代理；编辑中的验证重定向原来误报 prepared，现退出 10 且零提交；HTTP 503 原来可能被残留导航误认有效，现退出 1；提交后登录异常原来缺少已保存 stage，现保留 publish 阶段，含点击可能已发出的 publish_attempted=true。
- `tests/test_instagram_profile_cli.py` **14 项通过**：覆盖全部六动作与 reset、旧文件无关、换号/两种浏览器、配置/headless/custom 来源、借用会话、setup 异常/取消/锁释放、作品作者拒绝、作品失败现场保护、no-publish 真实停止点、提交成功/未知/登录/验证及关闭故障。替身只在 Playwright/provider/页面行为与 expect 边界；没有替换整套 session。
- 初次回归发现已废弃的 `_open_instagram_page`、storage_state 写回及 cookie resolver 内部 mock 断言。仅退休 Instagram 对应旧断言；其配置、清理与结果保护由上述公开 CLI 测试替代。其他平台用例保持。
- 最终 import 审计发现工作树最初缺少 conf.py，因此初轮 interpreter 曾回退原仓 conf 模块。新 Profile 用例始终 patch BASE_DIR 到临时目录，受控浏览器用例始终用隔离 context/路由页面，没有实际账号操作。随后以 conf.example.py 创建工作树 conf.py，验证 conf.__file__、BASE_DIR、sau_cli.__file__ 均在本工作树；下面最终 219 项和 62 项在隔离配置下执行。原 conf.py 未修改。

执行 interpreter 均为 `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python`，cwd 均为本工作树：

```sh
python -m unittest tests.test_instagram_profile_cli tests.test_mlx_meta tests.test_adspower_article_identity_platforms tests.test_instagram_options tests.test_instagram_no_publish.InstagramNoPublishParserTests tests.test_instagram_no_publish.InstagramNoPublishPlumbingTests tests.test_publish_cleanup tests.test_review_regressions tests.test_sau_browser_cli tests.test_adspower_cli tests.test_local_browser_session tests.test_local_profile -v
```

最终 **219 tests passed，8.711 秒**。包含共享真实子进程占用/重建回归；没有用内存锁替代。

```sh
python -m unittest tests.test_instagram_posts tests.test_instagram_uploader tests.test_instagram_no_publish tests.test_instagram_humanize tests.test_instagram_alt_text_option tests.test_instagram_comments_option tests.test_instagram_location_option tests.test_instagram_ai_label_option -v
```

**141 tests passed，172.211 秒**。这是无真实账号的 Chrome DOM/拦截网络夹具与纯逻辑回归，不是平台发布验收。后续错误传播和导航 guard 更新后，重跑受影响边界：

```sh
python -m unittest tests.test_instagram_humanize tests.test_instagram_uploader.InstagramContractTests tests.test_instagram_no_publish tests.test_instagram_posts -v
```

最终 **62 tests passed，65.495 秒**。真实浏览器夹具在 sandbox 外运行；所有作品请求都由替身/路由响应，无真实删除。中间包含最终导航改动的 224 项组合也通过（25.024 秒），以最终隔离配置的上述命令为交付依据。

- 已将 integration `9120889` 合入本票工作树；仅新增 TikTok 已认证 ambiguity fixtures，无冲突。`git diff --check` 通过。Instagram 本地 probe/login/works 都把页面交给有界 persistent-context owner 清理，不存在先等待无界 page.close 的本地路径；managed-only `is_logged_in` 保留原关闭行为。

- 合入最新 integration 后执行 `python -m unittest tests.test_publish_ambiguity tests.test_instagram_profile_cli tests.test_mlx_meta tests.test_adspower_article_identity_platforms -v`：**84 tests passed，4.139 秒**。新的提交阶段保护与托管兼容断言均通过。
