# Rednote Profile 接入验证（03）

日期：2026-11-17。工作树 `/private/tmp/sau-local-profile-03`；本票不操作真实账号，不发布、不删除作品。测试配置以临时 `conf.BASE_DIR`、临时 Profile 和合成素材隔离；未修改主工作树的配置、Cookie 或浏览器资料。

## 覆盖入口与实现

- 正式 CLI：login、check、upload-video、upload-note，以及 01 已开放的 reset-profile。
- 直接调用：rednote_setup、rednote_cookie_gen、RednoteVideo/RednoteNote 的 upload、upload_in、main 与命名上传入口。旧位置参数 `account_file` 仅转换为别名，不读取该文件；新调用可传 `account_name`、`local_browser`、`headless=None|bool`。
- 本地 Profile 是唯一登录态。内部发布页预检与业务共用持久化 context 和占用权；本地探测页和登录页交由外层有界 context 关闭，避免单独 page.close 卡住生命周期。托管默认保留原探测页清理。
- 删除 Rednote JSON Cookie 预检/恢复/写回、UA probe context 和本地 stealth/locale/header/permission 覆盖。原托管忽略项常量仅保留用于既有日志，不进入本地启动。
- 未修改共享 Profile、配置解析或 session 实现。01 的跨进程锁和 02 的 8 项真实浏览器配置/持久化/匿名隔离证据仍适用，无需无理由重跑整套浏览器矩阵。

## TDD 证据

按单个纵向切片先红后绿，主要入口为正式 CLI dispatch，经真实配置、Profile、session，只替换外部浏览器/页面/provider client。

| 切片 | 实现前观察到的失败 | 完成后的行为 |
| --- | --- | --- |
| check 不依赖旧 JSON | 损坏 JSON 导致退出 10 | 同一 Profile 检查成功，旧文件原样保留 |
| login 来源及复用 | 旧临时 context 登录超时/失败 | 一次持久化启动，同别名复用、异种类隔离 |
| 视频 no-publish | 旧 Cookie 前置导致 10 | 真实上传/编辑/ARM 后停止，零发布点击 |
| 图文 no-publish | 旧临时 context 到达不匹配页面 | 同一持久化会话完成素材/编辑/ARM，零发布点击 |
| 探测故障分类 | 网络/结构错误打印 invalid | 故障为 1；登录/验证为 10 |
| 已登录无头 login | 不存在二维码导致退出 1 | 已有会话通过正向发布页探测 |
| 无头验证页 | 不存在二维码导致退出 1 | reason=verification 的退出 10 和补救提示 |
| 本地探测清理 | 独立 page.close 阻塞触发 50ms 测试超时 | 由外层有界 persistent context 清理 |

## 实际测试结果

在该工作树执行，使用原仓库 Python 3.11 环境：

```bash
PYTHONPATH=. /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest \
  tests.test_rednote_profile_cli tests.test_rednote \
  tests.test_review_regressions tests.test_publish_cleanup tests.test_runtime_defaults \
  tests.test_browser_session tests.test_adspower_browser_session \
  tests.test_adspower_cli tests.test_adspower_platform_contract -q
```

**152 tests，全部通过（3.941s）**。其中 20 项新的 Rednote Profile 边界测试覆盖来源/模式、路径优先、缺失资料、旧 JSON 无关、扫码临时图片、同别名重登、Chrome/Chromium 隔离、setup 和独立 uploader、取消、锁、reset、主结果/未知/提交后登录与验证、托管日志/所有权/限流。既有旧 JSON/UA 专用断言已由公开入口覆盖替代。

```bash
PYTHONPATH=. /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_rednote_options -q
```

**18 tests，全部通过**。在沙箱外运行完整 `channel="chromium"`、headless、`no_viewport=True` 的真实浏览器 DOM；所有网页为合成 HTML，外部请求全部阻断。覆盖自然窗口、滚动长表单/固定底栏遮挡、声明弹窗、封面及话题回读。初次沙箱内运行因系统浏览器进程权限产生 18 个 TargetClosedError；改在沙箱外执行。自然 viewport 首轮发现清理 Cookie JSON 时误删了话题解析的 json import；恢复后通过，再以完整 Chromium 通道复验通过。

`git diff --check` 通过。后续集成合并后的受影响检查另记于票据 Comments。

## 验证边界

这是离线 CLI/session 回归和隔离浏览器 DOM 验证，不是真实 Rednote 平台验收。新 Profile 的真实 login/check、视频/图文 no-publish 由票 20 执行；不把 2026-11-16 旧 Cookie/context 账号记录当作新 Profile 登录证据。

本票仅迁移 Rednote；此前完成 TikTok，其余平台按分批票执行。没有新 API、一次性迁移工具、跨账号同步或永久真实账号绑定。文档同步了 Rednote CLI、独立 skill 及其随包引用、配置、安装、Bootstrap 和术语。
