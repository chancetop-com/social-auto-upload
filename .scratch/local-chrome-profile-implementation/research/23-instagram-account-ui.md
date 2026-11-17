# 23：Instagram 账号创建界面兼容

## 已观察依据

只读取原仓库 20 留存的两次失败页面和截图，没有读取 Chrome Cookies/History 等资料。原始私人页面仍在 ignored `.local`，不提交到 Git：

- `.local/instagram-results/2583bc453668410dbcbacded7bd01d9f.json` 指向 `.local/instagram-errors/7f2bff01c1554967b5fc0adc16ed45eb/`：导航创建入口为 `a[href="#"]` 下的 `svg[aria-label="新帖子"]`；点击后出现 `div[aria-hidden="false"]` 内的三个链接，图标分别有 `aria-label="帖子"`、`"直播视频"`、`"广告"`，均为 `a[href="#"]`。菜单不含稳定专用 test id，也没有 menu/menuitem role；因此按实际图标语义识别“帖子”，不能假造 menu role 或取第一个链接。
- `.local/instagram-results/6e8bd685b68d4362971559041612fbeb.json` 指向 `.local/instagram-errors/cbff651cfd17477683054739ae81077a/`：裁剪 dialog 中标题为 `role="heading"`，推进动作是 `div[role="button"][tabindex="0"]`，完整名称“继续”。没有稳定专用 data/aria 动作属性；标题栏有多层无语义 div，不以祖先层数或位置代替按钮意义。保留 dialog 内 role+完整已观察按钮名，并分别限定推进与发布阶段。
- 普通号沿用已有 `_NAVIGATION_HTML` / composer / Humanizer 受控页面证据，创建图标含 `New post`；直接进入文件输入、两次 Next 后配文。旧夹具部分只写四个无语义导航项，不能继续把“第二项”当作安全定位依据，改为保留已观察图标语义。

## 验证边界

主要公共测试通过 `InstagramUploader.upload(session=BrowserSession(...))` 驱动完整业务，使用真实 Chrome 与隔离 context、合成身份和拦截所有远程请求的受控 DOM。既有正式 CLI → 真实配置/Profile/session 的测试继续覆盖生命周期与 provider 契约。受控普通号成功不是第二个真实账号验收；没有新建账号、登录或发布作品。

实际 creator 的新视频/图文 no-publish 等待 21 的新布局切换和 root 放行，完成后另附命令与结果，保留 20 的旧路径历史。

## TDD 记录（进行中）

- 真实 Chrome 的首轮受控测试先复现不同创建图标标签同时出现仍被任选一个；同批夹具使用了 Patchright 隔离世界读不到的页面全局变量，并遗漏中文 UTF-8 标记。已修正夹具为 DOM 数据记录和明确 charset，该批不能作为完整矩阵证明，原日志 `23-account-ui-red.log` 保留。
- 正式 CLI 的 early-Share 受控页面对视频、图文各复现一次合成 Share 点击（`23-stage-red.log`，2 failures）。这是新测试发现的旧选择器缺陷，不是此前任何实际运行发布的证据。将推进/提交的完整名称按阶段分离后两者保持零 Share，相关测试通过。
- 公开 `upload(session=...)` 的 creator 页面在 MLX、AdsPower × 两种媒体先报素材入口超时（`23-managed-menu-red.log`，4 errors，失败现场替身自身不支持截图也如实记录）；本地同用例通过。移除按 provider 限制业务 UI 的分支后，当前相关 92 项离线测试全部通过（9.135s，`23-offline-green.log`）。provider 生命周期、路由、ignored-option 日志未改。

- 发布就绪遮挡的独立受控 Chrome 用例先红：按钮存在且 enabled、但被覆盖时错误返回 prepared（`23-readiness-red.log`，1 failure）。改为共享 `utils.dom.check(..., 'interactive')`，只读可交互判定且不派发点击。
- 修正夹具后的新 Chrome 矩阵 6 项测试 / 19 个场景全部通过（174.853s，`23-account-ui-green.log`）：local/managed × ordinary/creator × video/note 共 8 条完整 Humanizer 流程；两种账号 HUMANIZE=0；缺失/混合标签重复创建入口、缺失/重复/禁用帖子菜单、菜单与编辑器同时出现、重复 Next、提前 Share、Share 遮挡。真实受控鼠标与按键事件、素材名称、配文回读、上下文保持可用及 Share/直播/广告零点击均有断言。
- 加入 shared interactive 判定后的离线集合为 101 项全部通过（9.520s，`23-offline-final.log`）：`tests.test_instagram_profile_cli tests.test_mlx_meta tests.test_instagram_humanize tests.test_publish_ambiguity`。
