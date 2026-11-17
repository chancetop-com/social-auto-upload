# 05: 小红书全流程接入

**What to build:** 小红书用户通过同一 Profile 完成登录、检查和视频/图文发布，摆脱旧 Cookie 文件及 UA 修改；每次动作复用一个会话和同一份生效配置。

**Blocked by:** [02：TikTok 全流程接入持久化 Profile](./02-tiktok-persistent-profile.md)

**Status:** resolved

**批次：** 第一批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 完成本票范围内所有已注册正式动作及可达独立启动、内部预检和直接 uploader 调用的接入，预检与业务复用同一 Browser session 和 Profile 占用；注入会话的业务不另开同目录或自行关闭会话。同步开放本平台 reset-profile，保持 01 的精确目标、无需 binary、占用防护和部分失败契约。
- [x] 正式 CLI 与直接调用采用 02 的来源和 headless 优先级，区分未提供与显式 False；默认 Chrome 有头，允许 Chromium 与自定义路径。只使用所选来源及按实际种类隔离的持久化 Profile，no_viewport，失败不回退；切换同种路径/模式复用资料，未选浏览器无需安装。
- [x] Profile 是唯一登录态来源，删除本平台正式路径的旧 JSON 存在检查、Cookie 预检、storage_state 恢复/导出及旧身份门槛。只有 login 引导登录；缺少 Profile、明确未登录或业务中登录失效退出 10，结束本次业务；探测、页面、权限或必需字段故障退出 1，人机验证保留 reason=verification 与补救提示。正常命令不承担 19 的一次性迁移。
- [x] 允许同别名重新登录不同真实账号及两种浏览器使用不同账号，不新增永久绑定、跨 Profile 身份同步或仅为防换号的比较；原有显式请求目标与历史作品证据继续校验，历史结果不改写或删除。
- [x] 覆盖 login、check、upload-video、upload-note，以及独立登录、check、上传启动和 JSON preflight；删除本地旧登录态恢复、预检与写回，保持正向登录证据、验证原因及探测故障分类。
- [x] 退出为读取改写 UA 创建的 probe context 及相关覆盖；不以另开浏览器处理内部检查。相关窗口、滚动、iframe/popup 和覆盖层交互在 no_viewport 基线下得到验证。
- [x] 保留视频/图文选项、内容声明、定时及结果判断；离线确认两种正式入口 no-publish 参数到达素材上传、编辑、发布就绪后的最终提交前停止点，保护缺失先补齐。真实不发布回归由 20 执行，本票不真实提交或删除。
- [x] 本地移除项目增加的 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化、locale/语言和无业务依据的权限；保留 Patchright 默认、必要业务脚本、二维码、现有代理、超时、人类化交互、响应监听、发布预算、not-before 及结果文件，不修改界面语言。
- [x] 初始化、正常完成、异常、取消、超时与登录失效按所有权有界清理，取消继续传播，失败不回滚或重建 Profile。已有业务错误、成功、发布结果未知（9）及 publish_attempted 不被清理覆盖；提交后登录/验证异常保留原语义，不自动恢复旧任务或重发。
- [x] 本平台 MLX/AdsPower 仅采用新 headless 来源；忽略本地浏览器选择/路径且不额外报错或警告，不访问本地安装、Profile、锁或旧资料。保留原动作路由、login 限制、provider 参数/日志、CDP 所有权、停止/断开与限流退出 11；尚未迁移的平台保持旧行为。
- [x] 从正式 CLI dispatch 经真实配置解析和共享编排，复用浏览器/平台/provider 边界替身完成相关离线回归；覆盖本票动作、配置传播、旧文件无关、换号、登录分类、重建、资源所有权和提交结果保护，不把 session 整体替换成 parser 测试。直接调用只补缺口，共享能力变化时补跑受影响的跨进程/真实浏览器检查。
- [x] 同步本平台 CLI/平台 skill、配置及登录说明、Agent Bootstrap 和运行依赖说明；只在本平台接入后更新其行为描述，保留未迁移平台的准确说明。交付记录列出覆盖入口、验证命令/实际结果、未迁移平台和未执行项，离线结果不表述为真实平台验收。


## Answer

小红书全部正式 login、check、upload-video、upload-note、reset-profile 与支撑它们的直接 setup/uploader 入口已接入持久化本地 Profile。采用票 02 的真实配置解析及共享有界会话所有权；每次动作只有一次选定来源启动，预检与业务保持同一占用，注入会话不另开或关闭。删除旧 JSON 存在/会话 cookie 前置、恢复/导出和 UA probe；原位置参数仅作别名转换，不读写旧文件。

保留二维码、人类化交互、声明/定时/封面、发布预算、not-before 与 ARM/FIRE/OBSERVE。两种正式 no-publish 入口实际到达素材上传、元数据编辑与 ARM 就绪后停止。二维码 cleanup 不覆盖主结果；本地 probe 页交给外层有界 context cleanup，避免 page.close 挂起。托管仍保持原参数/ignored 日志、页面关闭与 owned stop，只采用批准的 headless 来源。

详见 [05 浏览器与入口验证记录](../research/05-browser-validation.md)。本票无未解决阻塞；真实平台账号与素材回归留给 20，一次性旧资料迁移留给 19。本票的受控 DOM 浏览器实测与离线替身结果均不是小红书真实站点验收。

## Comments

### 2026-11-17 — 实施和验证

- worktree `/private/tmp/sau-local-profile-05`，分支 `codex/local-profile-05`，基于 `c6edef0`；Python 来自主 checkout 的 `.venv/bin/python`，`conf.py` 是隔离工作副本（保留 True 默认以匹配未迁移平台旧测试），没有修改原用户配置或真实身份资料。
- 应用已批准的 TDD seam：正式 CLI → 实际 config/Profile/session，仅替换外部浏览器/DOM/provider。check、login、两种 no-publish、QR callback/清理故障和本地 probe.close 挂起均记录 red→green；详情见研究记录。新 `test_xhs_profile_cli` **15 tests passed**，涵盖来源/实际种类、headless 显式与缺省、旧 JSON 无关、同别名重新登录、错误分类、取消、重建、托管隔离与主结果保护。
- 最终 `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest discover -s tests -p 'test_xhs*.py' -q`：**324 tests passed**（20.855 秒）。含实际浏览器的 DOM 测试在已授权 sandbox 外执行；纯离线部分不依赖真实平台账号。
- 最终 `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_xiaohongshu_uploader tests.test_mlx_xhs_kuaishou tests.test_publish_cleanup tests.test_review_regressions tests.test_adspower_platform_contract tests.test_adspower_video_platforms tests.test_multilogin_cli tests.test_publish_ambiguity.PublishAmbiguityTests tests.test_sau_browser_cli tests.test_local_profile tests.test_runtime_defaults tests.test_local_browser_session -q`：**165 tests passed**（22.996 秒），包含共享 Profile 真子进程锁、未迁移 Kuaishou 行为和 managed 兼容检查。
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_dynamic_candidate_snapshots -q`：**7 tests passed**（13.139 秒，授权 sandbox 外本地 DOM）。额外真实 no_viewport 脚本：Chrome headed / Chromium headless 的 video+note **4/4 passed**，版本和命令见研究记录。
- 历史本地 JSON/UA/临时双关闭测试随删除行为退役；相应主结果保护迁入真实 Profile CLI 测试，保留探测、内容/声明/定时、提交与托管测试。初次交叉回归发现已移除 resolver 的 AdsPower 测试 fixture，按本平台改为禁止 local session；旧 Namespace 缺少新增字段使用 getattr 兼容。另有错误模块名 `test_local_browser`，更正为 `test_local_browser_session` 后验证。TikTok ambiguity 的旧 fake 登录锚点问题交给票 02 修复，未在本票修改其源代码。
- 按 writing-for-agents 同步独立平台 Skill 及其运行前提/CLI/排障引用、配置示例、README、CLI、安装、Bootstrap、术语及分发说明。浏览器安装按所选来源；同目录各项动作保持同配置。未发布技能源市场。
- 尚未迁移平台保持各自既有行为；Rednote/Instagram 由同批 03/04 独立推进，第二至第五批依赖仍按实施计划执行。
