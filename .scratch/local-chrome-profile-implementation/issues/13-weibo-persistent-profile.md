# 13: 微博全流程与窗口交互适配

**What to build:** 微博用户在浏览器实际窗口尺寸下，通过 Profile 完成正式登录、检查和发布；发布按钮可通过正常页面交互触达，不依赖固定大 viewport。

**Blocked by:** [09：抖音全流程接入](./09-douyin-persistent-profile.md)；[10：快手全流程接入](./10-kuaishou-persistent-profile.md)；[11：视频号正式流程接入](./11-tencent-persistent-profile.md)；[12：百家号正式流程接入](./12-baijiahao-persistent-profile.md)

**Status:** resolved

**批次：** 第四批

**依据：** [原始规格](../../local-chrome-profile/spec.md)；[实施顺序与共同约束](../README.md)。

- [x] 完成本票范围内所有已注册正式动作及可达独立启动、内部预检和直接 uploader 调用的接入，预检与业务复用同一 Browser session 和 Profile 占用；注入会话的业务不另开同目录或自行关闭会话。同步开放本平台 reset-profile，保持 01 的精确目标、无需 binary、占用防护和部分失败契约。
- [x] 正式 CLI 与直接调用采用 02 的来源和 headless 优先级，区分未提供与显式 False；默认 Chrome 有头，允许 Chromium 与自定义路径。只使用所选来源及按实际种类隔离的持久化 Profile，no_viewport，失败不回退；切换同种路径/模式复用资料，未选浏览器无需安装。
- [x] Profile 是唯一登录态来源，删除本平台正式路径的旧 JSON 存在检查、Cookie 预检、storage_state 恢复/导出及旧身份门槛。只有 login 引导登录；缺少 Profile、明确未登录或业务中登录失效退出 10，结束本次业务；探测、页面、权限或必需字段故障退出 1，人机验证保留 reason=verification 与补救提示。正常命令不承担 19 的一次性迁移。
- [x] 允许同别名重新登录不同真实账号及两种浏览器使用不同账号，不新增永久绑定、跨 Profile 身份同步或仅为防换号的比较；原有显式请求目标与历史作品证据继续校验，历史结果不改写或删除。
- [x] 覆盖微博所有正式注册登录、检查和发布动作及可达独立启动/预检；每种正式内容入口都切换，不能只迁移主视频路径。
- [x] 移除以固定大 viewport 保持发布按钮可见的策略；使用已有滚动、元素可用性和覆盖层处理能力完成交互，不用额外最大化或新固定尺寸替代。
- [x] 在小窗口、需要滚动或存在覆盖层的相关场景验证发布就绪和元素可交互判断；保留原选项、响应监听和提交边界，交互失败不得误报登录失效或重复提交。
- [x] 本地移除项目增加的 stealth、UA/请求头、自动化掩饰、固定 viewport、额外最大化、locale/语言和无业务依据的权限；保留 Patchright 默认、必要业务脚本、二维码、现有代理、超时、人类化交互、响应监听、发布预算、not-before 及结果文件，不修改界面语言。
- [x] 初始化、正常完成、异常、取消、超时与登录失效按所有权有界清理，取消继续传播，失败不回滚或重建 Profile。已有业务错误、成功、发布结果未知（9）及 publish_attempted 不被清理覆盖；提交后登录/验证异常保留原语义，不自动恢复旧任务或重发。
- [x] 本平台 MLX/AdsPower 仅采用新 headless 来源；忽略本地浏览器选择/路径且不额外报错或警告，不访问本地安装、Profile、锁或旧资料。保留原动作路由、login 限制、provider 参数/日志、CDP 所有权、停止/断开与限流退出 11；尚未迁移的平台保持旧行为。
- [x] 从正式 CLI dispatch 经真实配置解析和共享编排，复用浏览器/平台/provider 边界替身完成相关离线回归；覆盖本票动作、配置传播、旧文件无关、换号、登录分类、重建、资源所有权和提交结果保护，不把 session 整体替换成 parser 测试。直接调用只补缺口，共享能力变化时补跑受影响的跨进程/真实浏览器检查。
- [x] 同步本平台 CLI/平台 skill、配置及登录说明、Agent Bootstrap 和运行依赖说明；只在本平台接入后更新其行为描述，保留未迁移平台的准确说明。交付记录列出覆盖入口、验证命令/实际结果、未迁移平台和未执行项，离线结果不表述为真实平台验收。


## Comments

2026-11-17 — Implemented in `/private/tmp/sau-local-profile-13`, based on integration `b8be345`. Applied the TDD skill and its approved spec seams; no added subagents, actual account operations, publishing or deletion. `conf.BASE_DIR` was verified against this worktree before tests; user configuration was not read or changed. No applicable ADR directory exists.

Red/green evidence:

- First CLI login/check tracer failed because the browser fake rejected the legacy transient launch (`Use the persistent Profile`); after the persistent path was introduced it passed with one selected Profile per command and malformed legacy JSON unchanged.
- Video CLI tracer failed on the remaining legacy account-file route; after migrating the direct uploader it passed with one persistent launch for preflight + video flow, a single submission, and no JSON export.
- Post-submit verification tracer initially returned 9; the local operation guard now preserves verification reason and `publish_attempted=true`, returning 10 without repeating submission.
- Unexpected-domain and diagnostic-failure tracers initially returned 10 / replaced the original navigation fault; they now return 1 and preserve the primary failure.
- Observation disconnection after submit initially returned 1; it now returns 9 with one dispatch, preserving the no-automatic-resubmission boundary.

Validation commands/results (interpreter `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python`, cwd this worktree):

```sh
python -m unittest tests.test_weibo_profiles tests.test_weibo_humanize tests.test_mlx_alipay_weibo tests.test_publish_cleanup tests.test_local_profile tests.test_sau_browser_cli tests.test_multilogin_cli tests.test_adspower_cli tests.test_humanize tests.test_adspower_platform_contract tests.test_adspower_video_platforms tests.test_publish_ambiguity tests.test_review_regressions -q
```

**282 passed in 13.269 s**. Includes 25 new Weibo CLI/config/Profile/session tests, existing interaction regressions, both provider paths, source/headless priority and absent optional config, browser/alias isolation and relogin, missing/invalid/verification/fault classification, precise reset without binary and live occupation, direct filename-as-alias calls, QR callback/temporary-image cleanup, cancellation/hung cleanup, not-before with the lease held, and pre/post-submit outcome preservation. Shared old transient cleanup/launch assertions were retired only for Weibo; the unaffected platforms retain their expectations. `git diff --check` passed.

```sh
python -m unittest tests.test_weibo_profile_dom -v
```

**1 passed in 210.553 s**, comprising eight real persistent launches and six full video scenarios across Chrome headed / Chromium headless. See [browser evidence](../research/13-browser-validation.md) for versions, sandbox restriction, fixture correction, and observed scrolling/overlay/submission results. No real platform acceptance is claimed.

## Answer

All registered Weibo actions (login, check, upload-video, new reset-profile), command wrappers, cookie-named compatibility calls, WeiBoVideo.upload/main and injected-session work now use the agreed Profile/source/headless contract. Local preflight and upload share one session/lease; local pages belong to the bounded persistent context owner. Normal commands never restore/export/read/delete old JSON. Managed provider routes retain prior navigation/options/logging/ownership with only resolved headless changed. The fixed 1280×2000 local viewport is removed; existing scrolling, Escape, hit-test and safe fallback click behavior handles the natural window. No shared runtime API changed.

CLI, self-contained platform skill, README, GLOSSARY, conf.example, installation and Agent Bootstrap descriptions are synchronized. At this branch baseline, Hupu, Alipay, Dayu, Zhihu and Xueqiu remain on their own pending tickets; Bilibili is outside migration. Tickets 19/20 and real platform account/no-publish acceptance were not performed by this ticket.
