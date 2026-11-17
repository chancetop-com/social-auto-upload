# 10 快手持久化 Profile 验证记录

日期：2026-11-17。工作树 `/private/tmp/sau-local-profile-10`，分支 `codex/local-profile-10`，集成起点 `821e161`。使用原仓 `.venv/bin/python`（3.11）；已确认 conf.BASE_DIR、sau_cli、utils、uploader、tests 均从本工作树加载。未读取真实 Cookie 内容、登录账号、上传真实素材或发布作品。

## 入口与行为

- 正式 CLI：login、check、upload-video、upload-note、reset-profile；直接 ks_setup、cookie_auth、get_ks_cookie、KSVideo/KSNote 的 main/upload/upload_in。
- 本地 login 才创建 Profile；预检与业务共用真实 local BrowserSession 与锁。旧 JSON 只可作为兼容参数名称解析别名，不读写/迁移文件。删除 ks_uploader 包导入时创建 cookies 目录的副作用。
- 默认 Chrome 有头；显式 bool/CLI > headless 配置 > False。自定义路径按真实产品种类隔离，CLI/config 种类与缺省 Chrome 的优先级由 02 共享解析器提供；no_viewport，无 stealth、UA、语言或权限覆盖。选定来源失败不回退。
- 明确登录失效/缺少 Profile 为 10；verification 保留 reason 与补救提示；4xx/5xx、网络、缺失结构为 1。业务中的初始导航、页面准备及提交后跳转沿用本地语义；提交后保留 publish_attempted=true、未知结果 9、禁止自动重发。
- 视频和图文保留既有不同发布策略、原生定时、not-before；视频保留合集与封面。QR 刷新、回调、结果信息及临时文件清理保留，扫码后在同一 Profile 会话验证。
- MLX/AdsPower 仅改 headless 来源；保持 ignored-option 元数据、探测 URL、参数日志、连接/停止所有权和 11 限流契约。局部 browser/path 无论有效与否均不解析。直接 cdp_url 登录明确拒绝，避免绕过所选本地 Profile；托管登录继续由桌面应用完成。

## TDD 记录

采用已批准的 CLI dispatch → 真配置/Profile/session → 浏览器、平台、provider 外部替身边界；补充直接 API 与受控真实浏览器场景。不以替换整个 session 来测试参数。

1. check 旧行为返回 invalid/1，无法使用已有 Profile；红 1 项 → 接入真实持久化会话后绿。
2. login/config 红：触发旧临时浏览器禁用断言；改为单会话扫码/复验后绿。
3. 两个内容入口红：仍依赖旧账号文件定位；上传进入同一持久化会话后绿，观察真实正文/标签输入及单次提交。
4. 预检分类红 6 个子场景：captcha 被判有效、403 被忽略；本地分类修复后绿。
5. 提交后登录/验证红 4 个子场景：旧本地行为返回 9 且缺少登录阶段信号；改为 10 + publish_attempted=true 后绿，关闭失败不覆盖。
6. 导航等待时跳转红 2 个子场景：原返回 1；扩展本地异常分类后绿。
7. 登录验证码页缺 QR 红：原返回 1；保留 verification reason 后绿。
8. QR 结果字段回归红：迁移初版丢失 qrcode/current_url；恢复现有结果信息后绿。

附加回归覆盖缺少 Profile/旧 JSON 无关、两种浏览器隔离、自定义路径及无回退、缺省可选配置、明确 False、直接调用、注入会话所有权、精确重建/占用、初始化故障与取消、挂起页面/上下文关闭、成功/失败/未知清理保护、not-before 期间锁占用、两种托管 provider 的 check/两类上传和限流。

## 实际执行

```bash
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_kuaishou_profiles tests.test_kuaishou_humanize tests.test_mlx_xhs_kuaishou tests.test_adspower_video_platforms tests.test_publish_cleanup tests.test_local_profile tests.test_runtime_defaults tests.test_sau_browser_cli tests.test_review_regressions tests.test_publish_timeout tests.test_publish_gate tests.test_humanize tests.test_local_browser_session -q
```

最终 **219 项通过，8.091s**。其中新增 CLI/Profile 回归 20 项。旧的快手 storage_state/双重关闭 golden assertions 已用公开 Profile 回归替代，其他未迁移平台旧断言保留。`git diff --check` 通过。

```bash
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_kuaishou_profile_dom -v
```

使用临时专用 Profile 的实际系统 Chrome **157.0.8103.79**、headless=True、no_viewport=True，CDP 只调整测试窗口为 560×420；所有请求由本地 synthetic HTML 拦截。**1 项（视频、图文两个子场景）通过，10.347s**。真实人类化鼠标滚动点击、文件选择、正文写入、原生定时均完成；视频还完成封面上传与合集选择，DOM 回读证明每种内容仅一次提交且未设置 viewport。提交只作用于合成页面。

首次 sandbox 内启动按环境已知限制失败（EPERM/SIGABRT），已在允许 browser 启动的环境执行。过程中修正三处测试夹具问题：请求暂停期间 CDP detach、全局 fake sleep 误缩短 Playwright event deadlines、Patchright 隔离世界下的 window 变量回读；改用 DOM data 属性确认结果。它们均未导致生产代码调整。

## 未执行与边界

- 没有真实快手账号操作、线上发布/删除或平台 UI 验收；离线与受控 DOM 不是线上登录有效的证明。快手没有 --no-publish。
- 共享 Profile/session/config 生产能力未更改，沿用 01 的跨进程及 02 的 Chrome/Chromium、路径、headed/headless 持久化实测；本票未重复整个来源矩阵。
- 19 的一次性旧资料作业、20 的四平台真实不发布验收仍留在各自票。
- 本工作树集成基线中抖音、视频号、百家号、微博、虎扑、支付宝、大鱼号、知乎、雪球尚未接入；09/11/12 由同批独立任务推进，最终集合随合并取并集。Bilibili 不在本次迁移范围。

最终核对把新 request.local_browser 字段放在既有可选字段之后，保留直接调用的旧位置参数顺序；20 项快手 CLI/Profile 回归再次通过（3.174s）。合入最新集成分支检查显示 already up to date（821e161），工作树无其他改动。
