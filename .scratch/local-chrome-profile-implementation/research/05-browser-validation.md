# 05 — 小红书持久化 Profile 验证

2026-11-17；独立 worktree `/private/tmp/sau-local-profile-05`；基于票 02 integration `c6edef0`。使用主 checkout 的 Python 3.11 interpreter，模块和 `conf.py` 来自本 worktree；测试 Profile、旧 JSON、素材均为临时合成资料。未读取或操作用户真实账号资料，未发布或删除作品。

## 覆盖入口

| 入口 | 会话及证据 |
| --- | --- |
| CLI login / `xiaohongshu_setup(handle=True)` / `xiaohongshu_cookie_gen` | 一次共享 persistent session，按所选配置创建 Profile；保留二维码、callback、登录后正向探测；无 JSON 写回，无 UA probe。 |
| CLI check / `check_xiaohongshu_account` / `xiaohongshu_setup(handle=False)` | 同配置取得已存在 Profile，发布页上传锚点证明登录；缺失/登录/验证 10，网络/结构故障 1；本地探测页交给有界 context cleanup。 |
| CLI upload-video / upload-note / 两类 uploader `main`、upload、注入 session | 一个持久化会话覆盖业务检查、上传、编辑、ARM/FIRE/OBSERVE 和清理；注入 session 不另开、不自行关闭；旧文件只可作历史位置参数的别名转换，不读取。 |
| reset-profile | 复用 01 的精确目标与占用；选择 browser-kind，不解析本地 binary；另一种浏览器资料保留。 |
| MLX / AdsPower | 真实共享托管会话 + provider/browser 边界替身；仅 headless 来源变化；旧 ignored-options 日志、CDP 和 owned stop 保留，本地路径/种类不校验、不访问。 |

## TDD 记录

- 首个正式 check 带有效 Profile 和损坏旧 JSON：red 退出 10；迁移后 green，真正启动参数只有 user_data_dir、channel、headless、no_viewport，旧文件未变。
- 正式 QR login：red 仍进入旧临时浏览器并失败；接入同一 persistent context 后 green。分别覆盖再次登录、显式 headed、Chromium，始终一次启动。
- 两种正式 no-publish 入口：red 仍引用已移除 UA 探测；迁移 uploader 所有权后 green，DOM 记录证明素材派发、标题编辑、ARM 几何检查以及零提交。
- QR callback 失败：red 遗留临时二维码；清理后 green。二维码删除失败：red 覆盖登录成功；best-effort 清理后 green，同时保留 callback 原异常。
- 本地 probe 的 page.close 挂起：red 在 CLI dispatch 的 50ms 上限触发 TimeoutError；本地探测页交给外层有界 context close 后 green。默认 probe page-close 保留给托管，不改变其生命周期。

## 真实浏览器：受控页面，无平台账号

命令（工作目录如上，因 sandbox 阻止 Chromium 启动而在已授权的 sandbox 外执行）：

```bash
PYTHONPATH=/private/tmp/sau-local-profile-05 /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python .scratch/local-chrome-profile-implementation/research/05-no-viewport-smoke.py
```

脚本：[05-no-viewport-smoke.py](./05-no-viewport-smoke.py)。仅拦截/提供 `http://127.0.0.1:8765/**` 合成页面；Profile 与文件都在 TemporaryDirectory 中，结束时关闭并清除。页面包含覆盖层、900px 间隔、文件输入、标题/正文和发布按钮；执行真实 uploader 业务，显式 no-publish。

| 浏览器 | 版本 | 模式 | 视频 | 图文 |
| --- | --- | --- | --- | --- |
| 系统 Chrome | 157.0.8103.79 | headed | PASS | PASS |
| Patchright 完整 Chromium | 156.0.8078.4 | headless | PASS | PASS |

四项均验证：`page.viewport_size is None`；覆盖层移除；实际滚动；一个文件选择；标题与正文填写；ARM 就绪；提交计数为零。业务页面没有 iframe/popup 分支；封面等弹窗继续由现有离线 cover/controls 测试覆盖。首次脚本观测使用 window 自定义变量受到 Patchright 隔离 world 影响，改为 DOM data 属性；随后 contenteditable 的正常尾部换行改按语义文本核对。这两次是观测夹具问题，未修改生产业务来迁就它。

既有 `test_dynamic_candidate_snapshots` 的 **7 项真实本地 DOM 浏览器测试通过**（13.139 秒），覆盖动态话题候选、重排/替换和回读。第一轮 sandbox 启动失败为已知 EPERM/SIGABRT，授权环境重跑通过。既有 XHS DOM 静默 observer 测试也单独重跑通过（1 项，2.804 秒）。

共享来源识别、跨种类持久化与匿名隔离没有改动；沿用 [02 的 8/8 浏览器配置证据](./02-browser-validation.md)。本票实测补充平台滚动与覆盖层的 no_viewport 场景，不声称真实站点登录、发布成功或风控效果。

## 未执行范围

真实小红书账号 login/check 和真实素材 no-publish 回归留给票 20；旧资料的一次性迁移与删除留给票 19。本票没有外部账号操作、真实提交、作品删除或技能源市场发布。其他平台按各自票据推进，未全局切换尚未迁移的平台。

## 最终离线/集成结果

- `python -m unittest discover -s tests -p 'test_xhs*.py' -q`：324 passed（20.855s，含隔离 DOM 浏览器测试）。
- 平台 uploader、MLX/Kuaishou、cleanup/review、AdsPower、CLI、Profile、配置和 persistent-session 联合套件：165 passed（22.996s）。完整模块清单在 [票据 Comments](../issues/05-xiaohongshu-persistent-profile.md#comments)。
- 合并 integration `6d0ead1`（含 TikTok ambiguity 修正与 Instagram 04）后，XHS/Instagram 公共 CLI、ambiguity、cleanup/review、AdsPower 与 CLI 契约：90 passed（3.354s）。共用文档已合并三平台状态，其他平台保持原行为。
