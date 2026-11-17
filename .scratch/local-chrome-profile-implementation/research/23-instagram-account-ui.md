# 23：Instagram 账号创建界面兼容

## 已观察依据

只读取原仓库 20 留存的两次失败页面和截图，没有读取 Chrome Cookies/History 等资料。原始私人页面仍在 ignored `.local`，不提交到 Git：

- `.local/instagram-results/2583bc453668410dbcbacded7bd01d9f.json` 指向 `.local/instagram-errors/7f2bff01c1554967b5fc0adc16ed45eb/`：导航创建入口为 `a[href="#"]` 下的 `svg[aria-label="新帖子"]`；点击后出现 `div[aria-hidden="false"]` 内的三个链接，图标分别有 `aria-label="帖子"`、`"直播视频"`、`"广告"`，均为 `a[href="#"]`。菜单不含稳定专用 test id，也没有 menu/menuitem role；因此按实际图标语义识别“帖子”，不能假造 menu role 或取第一个链接。
- `.local/instagram-results/6e8bd685b68d4362971559041612fbeb.json` 指向 `.local/instagram-errors/cbff651cfd17477683054739ae81077a/`：裁剪 dialog 中标题为 `role="heading"`，推进动作是 `div[role="button"][tabindex="0"]`，完整名称“继续”。没有稳定专用 data/aria 动作属性；标题栏有多层无语义 div，不以祖先层数或位置代替按钮意义。保留 dialog 内 role+完整已观察按钮名，并分别限定推进与发布阶段。
- 普通号沿用已有 `_NAVIGATION_HTML` / composer / Humanizer 受控页面证据，创建图标含 `New post`；直接进入文件输入、两次 Next 后配文。旧夹具部分只写四个无语义导航项，不能继续把“第二项”当作安全定位依据，改为保留已观察图标语义。

## 验证边界

主要公共测试通过 `InstagramUploader.upload(session=BrowserSession(...))` 驱动完整业务，使用真实 Chrome 与隔离 context、合成身份和拦截所有远程请求的受控 DOM。既有正式 CLI → 真实配置/Profile/session 的测试继续覆盖生命周期与 provider 契约。受控普通号成功不是第二个真实账号验收；没有新建账号、登录或发布作品。

实际 creator 的新视频/图文 no-publish 在 21 的新布局切换、四次 check 和 guard 释放后，经 root 放行完成，见下方执行记录。20 的旧路径历史原样保留。

## TDD 与回归记录

- 真实 Chrome 的首轮受控测试先复现不同创建图标标签同时出现仍被任选一个；同批夹具使用了 Patchright 隔离世界读不到的页面全局变量，并遗漏中文 UTF-8 标记。已修正夹具为 DOM 数据记录和明确 charset，该批不能作为完整矩阵证明，原日志 `23-account-ui-red.log` 保留。
- 正式 CLI 的 early-Share 受控页面对视频、图文各复现一次合成 Share 点击（`23-stage-red.log`，2 failures）。这是新测试发现的旧选择器缺陷，不是此前任何实际运行发布的证据。将推进/提交的完整名称按阶段分离后两者保持零 Share，相关测试通过。
- 公开 `upload(session=...)` 的 creator 页面在 MLX、AdsPower × 两种媒体先报素材入口超时（`23-managed-menu-red.log`，4 errors，失败现场替身自身不支持截图也如实记录）；本地同用例通过。移除按 provider 限制业务 UI 的分支后，当前相关 92 项离线测试全部通过（9.135s，`23-offline-green.log`）。provider 生命周期、路由、ignored-option 日志未改。

- 发布就绪遮挡的独立受控 Chrome 用例先红：按钮存在且 enabled、但被覆盖时错误返回 prepared（`23-readiness-red.log`，1 failure）。改为共享 `utils.dom.check(..., 'interactive')`，只读可交互判定且不派发点击。
- 修正夹具后的新 Chrome 矩阵 6 项测试 / 19 个场景全部通过（174.853s，`23-account-ui-green.log`）：local/managed × ordinary/creator × video/note 共 8 条完整 Humanizer 流程；两种账号 HUMANIZE=0；缺失/混合标签重复创建入口、缺失/重复/禁用帖子菜单、菜单与编辑器同时出现、重复 Next、提前 Share、Share 遮挡。真实受控鼠标与按键事件、素材名称、配文回读、上下文保持可用及 Share/直播/广告零点击均有断言。
- 加入 shared interactive 判定后的离线集合为 101 项全部通过（9.520s，`23-offline-final.log`）：`tests.test_instagram_profile_cli tests.test_mlx_meta tests.test_instagram_humanize tests.test_publish_ambiguity`。
- 已有 `tests.test_instagram_uploader tests.test_instagram_no_publish` 真实 Chrome 受控回归 33 项全部通过（159.730s，`23-browser-regression.log`），覆盖提示、封面、选项、配文与提交保护。保持原有普通界面夹具，只补齐其已有语义图标，未新增真实账号操作。
- 合并集成 `3455f1f`（包含 21 新布局、22 清理、24 文案）后，101 项相关离线再跑全部通过（9.170s，`23-offline-integrated.log`）。冲突仅为 spec/index 追加段落，保留各票并集；21 的 Instagram 路径断言与本票行为用例一起保留。interactive 检查整体用 `asyncio.wait_for` 限在本轮剩余预算/200ms 内，防止目标在计数后消失导致超出发布就绪预算；最终受影响浏览器就绪子集另列。
- 最终预算包裹后的受影响浏览器子集 5 项全部通过（44.203s，`23-bounded-readiness-green.log`）：新 Share 遮挡用例及既有 `InstagramNoPublishFlowTests`，包括 options、not-before 不等待、disabled 超时和正常提交对照。

上述原始日志均保留在 `/private/tmp/sau-local-profile-notes/`。测试命令：

```sh
<original>/.venv/bin/python -m unittest tests.test_instagram_account_ui -v
<original>/.venv/bin/python -m unittest tests.test_instagram_uploader tests.test_instagram_no_publish -q
<original>/.venv/bin/python -m unittest tests.test_instagram_profile_cli tests.test_mlx_meta tests.test_instagram_humanize tests.test_publish_ambiguity -q
<original>/.venv/bin/python -m unittest tests.test_instagram_account_ui.InstagramAccountUiTests.test_no_publish_requires_an_interactive_share_button tests.test_instagram_no_publish.InstagramNoPublishFlowTests -q
```

cwd 均为 `/private/tmp/sau-local-profile-23`；真实受控 Chrome 启动使用 sandbox escalation；新增 19 场景拦截全部远程请求，既有回归继续使用合成 DOM，均不使用真实 Profile。重复的受影响子集不相加冒充唯一测试总数。


## 当前真实 creator 复验

21 已将四个原 Profile 同 inode 移到新布局并正常 check。root 于执行前确认目录与释放状态，21 最后重新取得/释放 guards 后明确停止其所有 Instagram 操作。此后仅执行以下两条获批 demo 命令；无额外登录、账号创建、发布或删除。

使用代码 `1127e4b`，数据/配置/cwd 均绑定原仓库 `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload`；外部 allowlist harness 为 `/private/tmp/sau-local-profile-notes/run23_live.py`，不是项目运行入口。原 `conf.py` 未写入；`--headed` 明确覆盖原配置，无 provider 环境，`HUMANIZE=1`。日志确认系统 Chrome 157.0.8103.79、`channel=chrome`、headless=False，Profile 为原仓库 `browser_profiles/chrome/instagram/luke`。

```sh
HUMANIZE=1 <original>/.venv/bin/python <harness> instagram upload-video --account luke --headed --file <original>/videos/demo.mp4 --title Profile验收 --no-publish
HUMANIZE=1 <original>/.venv/bin/python <harness> instagram upload-note --account luke --headed --images <original>/videos/demo.png --title Profile验收 --no-publish
```

完整参数与 UTC 开始/完成事件见 [23-live-events.jsonl](./23-live-events.jsonl)。两个命令首次均成功：

| 动作 | 开始 UTC | 完成 UTC | 退出码 | 实际结果 |
| --- | --- | --- | --- | --- |
| 视频 | 2026-11-17 12:00:07.835 | 12:00:31.709 | 0 | 素材、裁剪、编辑、配文和可交互 Share 就绪检查完成；prepared，Share 前停止 |
| 图文 | 2026-11-17 12:00:44.763 | 12:01:06.983 | 0 | 素材、裁剪、编辑、配文和可交互 Share 就绪检查完成；prepared，Share 前停止 |

两个日志均明确记录“Instagram 发布就绪，--no-publish 停在 Share 前（未点击发布）”，没有 cleanup 警告。对应原仓库 ignored 结果为 `.local/instagram-results/a98762429bec479e8f343ecb42ebadad.json`（视频）和 `.local/instagram-results/d2fccfac5202467b9552675071b379af.json`（图文），均为 `status=prepared` 且无 `content_id/post_id/post_url/schedule/media_count` 发布字段。原始控制台日志保留于 `/private/tmp/sau-local-profile-notes/23-instagram-video.log`、`23-instagram-note.log`。结束后只读进程检查未发现 live harness 或持有该 Instagram Profile 的 Chrome；未终止任何进程。

**证据限制：** 当前真实账号为 creator；普通号此次只有受控 DOM 和公开边界回归，没有另一个真实普通号 Profile，未创建账号。本次只证明素材上传、编辑、配文及发布前停止，不证明实际发布、全部高级选项、not-before 等待、发布后结果或风控效果；真实素材可能留下临时素材或草稿。四项高级选项不由本次 creator 演示扩大验证范围。原 Profile、结果和 19/20 历史证据继续保留在原仓库。
