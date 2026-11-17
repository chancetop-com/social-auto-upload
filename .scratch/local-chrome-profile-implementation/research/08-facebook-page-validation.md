# 08 Facebook Page 验证记录

日期：2026-11-17。工作树 `/private/tmp/sau-local-profile-08`，分支 `codex/local-profile-08`。初始基线 ec6ea39，提交实现后合入集成 c5a3141（含 YouTube 06、Instagram 04 测试修复），合并提交 02b7a1f。工作树 conf.py 来自示例，已确认 conf、sau_cli 与 BASE_DIR 均指向工作树；未读取真实账号 Cookie 内容。

## 交付边界

正式 login/check/upload-video/upload-note/verify/delete/reset-profile 均已覆盖。直接 meta_setup、meta_cookie_auth、MetaBusinessUploader.upload、meta_post_action 也使用真实配置解析、Profile 取得和共享持久化会话。旧 account_file 参数只提取明确前缀文件名中的别名以兼容直接调用，不读取文件；正式 CLI 直接使用原始 account_name。

资料定位固定为 facebook-page/原始别名/实际浏览器种类，与 facebook 隔离，Page 名和 ID 不参与登录容器定位。显式 Page 名须读回；本地请求 Page A 不可由 Page AB 前缀匹配满足。未指定时保留当前主体。作品操作保留 Page ID、Page 名、内容编号、配文和排期证据；换号不会重写历史结果。作品操作在 MLX/AdsPower 环境中仍是本地动作。

正常命令没有 JSON 存在门槛、storage_state 恢复/导出、旧资料迁移或永久主体绑定。只有 login 创建 Profile 并引导人工登录。本地缺 Profile/未登录/验证为 10（验证保留 reason），网络、HTTP、未知 DOM/权限故障为 1。业务登录失效立即结束；提交后保留 publish_attempted，未知提交仍是 9，禁止重发。代理、定时、not-before、媒体、作品证据与结果文件保留。

本地只向共享 resolver 提供 browser/headless 与原有代理，没有额外 UA、locale、viewport、stealth 或掩饰参数。托管保留旧探测、启动选项忽略日志、所有权和路由，仅采用批准的 headless 来源。共享 Profile/session 生产实现未修改。

## TDD 记录

以正式 CLI dispatch 经真实 config/Profile/session 为主，浏览器、平台 DOM、provider 使用外部边界替身；临时目录不触碰真实账号。主要红→绿切片：

- check + 损坏旧 JSON：原路径失败；接入 persistent context 后成功、旧 JSON 不变、无 storage_state。
- 登录分类：facebook.com/login 与 checkpoint 原先被当成域名故障 1；本地分类改为 10 并保留 verification，空白/未知页仍为 1。
- login：原流程先检查不存在 Profile 导致 10；login 独占创建并等待后，同别名重复登录和 Chrome/Chromium 资料复用通过。
- 视频/图文：原上传仍调用旧临时 opener；迁移后两个不同 Page 请求共享同一登录 Profile，每次仅启动一个 context，并走完整假 DOM 提交流程。
- 提交阶段：原本地流程没有拦截提交后登录；增加本地阶段检查后，成功/9/10 与提交至多一次、关闭失败保护通过。
- works：独立旧 opener 退出后，正式 verify/delete 迁移；Page/编号不匹配拒绝，证据保存失败不掩盖原异常。删除后验证重定向原先返回成功，新增提交后检查后保留 10 和阶段信息。
- reset：原 parser 未注册；共享重建接入后只删目标种类，保留 Chromium、Facebook 和历史资料，拒绝占用且无需 binary。
- 探测成功后的业务 HTTP 503 原先仍可提交/删除；本地业务导航显式检查后退出 1，提交计数为 0。
- 显式 Page A / 当前 Page AB 原先成功提交；本地精确读回后失败且提交计数为 0。受控真实浏览器也验证此路径。

补充回归覆盖直接调用、缺省配置与显式 False、自定义可执行文件的实际种类、缺少可选 LOCAL_BROWSER、无回退、代理、借用 session 不关闭、初始化/取消/超时/关闭失败、挂起 page.close 不阻塞拥有者关闭、两种 provider 对无关本地配置的隔离和原日志。已移除仅证明旧 Cookie 写回/opener 的 Page 专属测试，替换为上述 CLI 行为证据。共享测试的迁移平台集合与 YouTube 合并取并集。

## 实际执行

Python：项目原 checkout 的 `.venv/bin/python`（3.11.11），所有命令 cwd 为本工作树。

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_facebook_page_profile_cli tests.test_mlx_meta tests.test_facebook_page_humanize tests.test_publish_cleanup tests.test_review_regressions tests.test_adspower_video_platforms tests.test_local_profile tests.test_adspower_article_identity_platforms tests.test_adspower_platform_contract tests.test_adspower_cli tests.test_multilogin_cli tests.test_youtube_profiles tests.test_mlx_youtube tests.test_humanize.PlatformWideGateTests -q
```

合入 c5a3141 后：**252 tests，16.798s，OK**。其中共享 local_profile 测试包含真实临时目录和跨进程占用。迁移中的旧 resolver 夹具已按 Page 范围更新；未通过放宽生产接口来保留旧资料访问。

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_facebook_page_profile_dom tests.test_meta_uploader tests.test_facebook_posts -v
```

合并后受控浏览器回归：**10 tests，17.805s，OK**。使用已安装系统 Chrome **157.0.8103.79**，新测试运行真实 persistent context、headless=True、no_viewport=True、隔离临时 Profile。站点响应由合成 DOM 拦截，验证正向导航、登录表单、未知页、checkpoint 的 verification 以及 Page 前缀错配在上传/提交前失败；已有受控 works DOM 测试验证原内容编号错配拒绝删除。首次 checkpoint 夹具的 302 跳转未可靠模拟目标，改成拦截文档内 history.replaceState 后通过；没有把该夹具失败描述为平台结果。

共享来源、持久化和匿名隔离能力没有变化，因此沿用 [02 的 8/8 浏览器矩阵](02-browser-validation.md)，不无故重跑。最后仅保持托管原有 Page 文本读取语义的局部调整，另跑 Page CLI/托管/人类化回归；结果记录在票 Comments。

## 未执行与后续

未登录真实 Facebook Page 账号、发布、上传真实素材或删除真实作品；不声称新 Profile 已获真实平台验收。Facebook Page 没有 --no-publish，本票没有增设或绕过此开关。两种 provider 均为离线边界验证，没有操作真实桌面账号。未执行旧资料一次性迁移（19）或四平台真实不发布回归（20）。

本工作树在 c5a3141 上，Facebook 07 仍为并行票；抖音、快手、视频号、百家号、微博、虎扑、支付宝生活号、大鱼号、知乎、雪球仍保留各自待迁移路径。本文不扩大本票平台范围。没有未解决的本票阻塞。
