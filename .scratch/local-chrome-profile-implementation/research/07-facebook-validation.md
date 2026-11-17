# 07 Facebook Profile 验证

日期：2026-11-17。实现 worktree：`/private/tmp/sau-local-profile-07`；基线：ec6ea39。使用原项目 `.venv/bin/python`（Python3.11），工作目录与 conf.BASE_DIR 均为本 worktree，测试均改用临时 Profile 根目录。

## 入口与行为证据

- CLI login/check/upload-video/upload-note/verify/delete/reset-profile 真实 dispatch；直接 `facebook_setup` / `facebook_cookie_auth` / `FacebookVideo`（FacebookPost 同类）/ `facebook_post_action` 全部接入同一持久化会话。login 才创建 Profile，上传的预检与编辑提交共用一次会话；注入 session 不另启浏览器也不关闭借用资源。
- 配置采用02解析器：缺省/显式布尔值、Chrome/完整 Chromium、自定义产品种类优先、未选来源无要求、启动失败不回退、旧 conf.py 可缺 LOCAL_BROWSER。代理保留；无 storage_state 读写、无 JSON 存在检查、无 sidecar 绑定。
- 真实目录/锁覆盖 Profile 占用、清理后可再取、无 binary 的精确 reset；Facebook 与 Facebook Page、Chrome 与 Chromium 隔离。原别名可换真实用户，不同步账号；works 仍核对当前 c_user、owner-id、作者链接、原作品编号与正文。
- 登录/验证为10，网络/HTTP/结构故障为1；延迟首页 composer 挂载会等待。提交至多一次，成功/9/10及 publish_attempted 经关闭失败保持；取消传播；local operation page 留给 persistent context 有界关闭，避免单页 close 挂起阻塞外层清理。
- MLX/AdsPower 采用新 headless 来源，其他边界及忽略项日志保持；无本地配置解析/安装/Profile 要求。verify/delete 在 provider 环境下仍是本地动作，raw account 保留。

## 已执行

解释器前缀：`/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest`。

1. `tests.test_facebook_profile_cli tests.test_facebook_humanize tests.test_mlx_meta tests.test_publish_cleanup tests.test_review_regressions tests.test_adspower_cli tests.test_adspower_platform_contract tests.test_adspower_article_identity_platforms tests.test_adspower_browser_session tests.test_local_profile tests.test_local_browser_session tests.test_publish_timeout tests.test_publish_gate -q`：207 项通过（补入延迟挂载前）。后续最终结果见下文。
2. `tests.test_facebook_profile_dom tests.test_facebook_uploader tests.test_facebook_posts -v`：13 项通过，29.851s；沙箱外使用已安装系统 Chrome157.0.8103.79 与完整 Chromium156.0.8078.4。全部请求本地 fulfill，无真实账户。新增公共 CLI DOM 用例在两种浏览器执行各一次 login、一次视频和一次图片 composer，共6次临时持久化会话；natural viewport、遮罩/对话框、文件输入、人类化点击、正文读回和单次提交事件均通过，浏览器均关闭。旧作品测试同时验证同文案不能替代作品 ID，作者不一致拒绝。
3. DOM 初版把多段正文放入通用 contenteditable，浏览器原生 Enter 产生额外空行而读回失败；夹具收窄到单行标题后通过，未为模拟页面改变平台正文逻辑。现有人类化测试仍覆盖多行/标签/CRLF/超长正文。该合成 DOM 不能证明真实 Facebook 编辑器或登录有效。
4. `tests.test_humanize tests.test_sau_browser_cli tests.test_multilogin_cli tests.test_publish_ambiguity -q` 初次114项因共享旧 Instagram/Facebook fixture 假设报4项错误；Facebook对应删除的 opener/resolve_account_file测试已迁移，Instagram修复已在集成7646984。最终合并后重跑结果见下文。

## 范围与未执行

没有真实登录、发布、作品删除、旧 Cookie 导入/清理，未进行 Facebook 平台真实账号验收。本票无共享生产 API 改动；01/02 的跨进程/真实浏览器基础证据继续有效，相关共享生命周期回归已重跑。YouTube06现已合入，Facebook Page仍由08独立接入；后续09–18的平台仍保留各自既有行为，Bilibili不属本地浏览器Profile范围。普通命令不会启动19迁移作业。

## 最终合并后结果

- 已合并集成 `7646984`（Instagram测试修复）与 `c5a3141`（YouTube06）；共享文档、重建名单和旧 Cookie 测试按平台相加合并，无共享生产 API 改动。
- 最终命令：

```bash
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_facebook_profile_cli tests.test_facebook_humanize tests.test_mlx_meta tests.test_publish_cleanup tests.test_review_regressions tests.test_adspower_cli tests.test_adspower_platform_contract tests.test_adspower_article_identity_platforms tests.test_adspower_browser_session tests.test_local_profile tests.test_local_browser_session tests.test_publish_timeout tests.test_publish_gate tests.test_humanize tests.test_sau_browser_cli tests.test_multilogin_cli tests.test_publish_ambiguity tests.test_youtube_profiles tests.test_mlx_youtube tests.test_adspower_video_platforms -q
```

结果：**365 tests，18.296s，OK**。包含14项新增 Facebook Profile CLI 测试，provider check与视频/图文均穿过真实 BrowserSession，补测显式headed、忽略本地来源及provider所有权。最后一次 Facebook专属旧MLX测试门槛改为监测真实作品入口，缺账号仍在动作前退出2。

- 最终受控浏览器复验：`tests.test_facebook_profile_dom tests.test_facebook_uploader tests.test_facebook_posts -v`，**13 tests，35.745s，OK**。这次在新增首页异步挂载等待之后运行，包含两种浏览器共6次独立持久化生命周期；后续合并仅引入YouTube生产代码及共享测试/说明，不改变Facebook路径。
- `git diff --check` 通过；Facebook正式源码检索没有 storage_state、独立 launch/new_context、旧文件存在检查、固定viewport/locale/stealth。旧形参名仅作为直接调用者的别名输入适配，不执行文件I/O。已记录的初始失败已全部解决；没有本票遗留阻塞。
