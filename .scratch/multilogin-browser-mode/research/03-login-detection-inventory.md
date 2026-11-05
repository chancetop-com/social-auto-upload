# 03 — 各平台登录态检测清单（MLX 模式）

> 范围：所有走 Playwright/Patchright 的上传平台；不含 Bilibili（`biliup` 子进程）与旧 `uploader/xhs_uploader` 的 `sign_local`（只算签名）。
> 方法：只读代码，未启动浏览器、未访问真实平台。所有结论均附 `文件:行`。

## 0. 先给结论

1. **没有任何平台现有检测接受外部 `context`。** 全部 `cookie_auth()` / `check_*_account()` 都自己 `launch()` + `new_context(storage_state=...)`；页面级判断本身大多可以抽出，但入口必须重写。
2. **判断逻辑大多只依赖 `page`，不依赖 `storage_state`。** 真正与账号文件耦合的是四类“身份绑定”：知乎、雪球、大鱼号、Instagram；它们还要读 `.identity.json` / 账号 JSON 里的用户 ID，MLX 模式无 `--account` 时无法照搬。
3. **最可靠的是 URL/明确业务锚点型检测**：YouTube（`/channel/`）、Instagram（`/direct/inbox/`）、知乎/雪球/大鱼号（页头身份元素）、Facebook（composer 文件输入）。
4. **最不可靠的是 TikTok 与支付宝/百家号**：TikTok 用“有没有 `SelectFormContainer` 下拉框”反推，登录页也可能没有下拉框；支付宝/百家号只有“没看到登录标记”的反向判断，空白页或慢加载会假阳性。
5. **MLX 适配不要直接调现有 `cookie_auth`。** 应把每个平台的页面判断抽成 `async def is_logged_in(context) -> bool`：在传入 context 上 `new_page()` → `goto` → 判定 → `page.close()`；禁止 `new_context()`、`storage_state(path=...)`、`set_init_script()`（后者是否可用取决于 ticket 02）。网络错误/HTTP 错误应与“未登录”区分，前者抛异常，后者返回 `False`，否则会把网络故障误报成退出码 10。
6. **本清单内没有任何平台以 API/外部二进制作为登录检测主路径**；全部是浏览器页面检测。仅少量平台把 cookie 名作为兜底信号（虎扑 `u`、微博 `SUB`、百家号 `BDUSS/STOKEN`、Instagram `ds_user_id`）。Bilibili 走 `biliup` 子进程，不在本清单。

## 1. 总表

| 平台 | 模块/文件:行 | 检测 URL | 标记 | 可复用函数 | 可靠性 | 备注 |
|---|---|---|---|---|---|---|
| douyin | `uploader/douyin_uploader/main.py:112-135` | `https://creator.douyin.com/creator-micro/content/upload` | URL 含 `content/upload` 且无“手机号登录/扫码登录”；3 次重试 | 抽 125-129 为 `is_logged_in(context)`（约 8 行）；已有 `_is_douyin_login_completed(page)` 210-232 更强 | 中高 | 2.5s 等待对慢 SPA 偏短；上传前 `validate_base_args` 353 又调一次 `cookie_auth` |
| xiaohongshu | `uploader/xiaohongshu_uploader/main.py:177-217` | `https://creator.xiaohongshu.com/publish/publish?from=homepage&target=video` | 非 `/login`；`div[class*='login-box']` 不可见 | `_is_xhs_login_completed(page)` 163-175 已可复用，加 3 行 goto 即可 | 中高 | 3s 固定等待；登录框未挂载时会误判为已登录 |
| ks | `uploader/ks_uploader/main.py:224-267` | `https://cp.kuaishou.com/article/publish/video` | 非 `passport.kuaishou.com`；无“立即登录”；正向 `button[class^='_upload-btn']` 可见 | 抽 238-262（约 25 行）；`_is_ks_cookie_invalid(page)` 147-153 可复用 | 中高 | 正向按钮是主证据；兜底“机构服务”选择器来自旧版页面 |
| tencent / weixin | `uploader/tencent_uploader/main.py:114-146` | `https://channels.weixin.qq.com/platform/post/create` | 8s 内跳 `**/login.html**`；`open.weixin.qq.com/connect/qrconnect` iframe | 抽 122-137（约 16 行）；`_is_tencent_login_completed(page)` 238-268 也可复用 | 中 | 8s 内未跳转即判有效，慢跳转/延迟 iframe 会假阳性；`weixin_setup` 477-491 只是代理到 `tencent_setup` |
| weibo | `uploader/weibo_uploader/main.py:222-251` | `https://weibo.com/` | URL 含 `newlogin`/`passport`；可见“登录”按钮 | 抽 230-241（约 12 行）；`_is_login_completed(page)` 137-154 有头像/`SUB` 正向信号 | 中低 | 首页游客态与登录态都可能出现“登录”文字；固定等 5s |
| hupu | `uploader/hupu_uploader/main.py:242-277` | `https://bbs.hupu.com/newpost?tabkey=2` | URL 含 `passport`/`login`；`get_by_role("button", name="上传视频")`；兜底 cookie `u` | 抽 250-268（约 19 行）；`_create_stealth_context` 89-99 / `_new_stealth_page` 101-104 需改为接收外部 context | 中 | `u` cookie 兜底可能残留旧值；URL 的 `login` 子串判断过宽 |
| tk（main.py） | `uploader/tk_uploader/main.py:15-39` | `https://www.tiktok.com/tiktokstudio/upload?lang=en` | 页面存在 class 匹配 `tiktok-.*-SelectFormContainer.*` 的 `select` 即失效，否则有效 | 需新写；可保留 23-24 的 goto/networkidle，判定重写 | 低 | Firefox launch；登录页/空白页没有 select 时直接假阳性；该平台未接入 `sau_cli` |
| tk（main_chrome.py） | `uploader/tk_uploader/main_chrome.py:16-40` | 同上 | 同上 | 同上 | 低 | Chromium 版本；上传流程有 `wait_for_url` 153/157-160 可作辅助信号，但登录检测本身要重写 |
| youtube | `uploader/youtube_uploader/main.py:50-68` | `https://studio.youtube.com` | URL 不含 `accounts.google.com`/`/signin`，且含 `/channel/` | 抽 58-63（约 6 行）；上传流程 213 已有同样的内联检查 | 高 | 3s 后仍在 `studio.youtube.com` 会假阴性；多频道选择页 URL 可能不是 `/channel/` |
| facebook | `uploader/meta_uploader/facebook_uploader/main.py:34-47,71-84` | `https://www.facebook.com/` | URL 含 `/login`/`checkpoint`/`two_step_verification`/`/authentication/`；可见 `input[name="email"]`；正向 `FACEBOOK_MEDIA_INPUT` 数量为 1 | `_is_logged_out(page)` 34-47 可直接复用，加 goto 约 10 行 | 高 | composer 未挂载时 `count()!=1` 会假阴性；已覆盖二次验证 URL |
| facebook-page | `uploader/meta_uploader/facebook_page_uploader/main.py:69-93` | `https://business.facebook.com/latest/composer/` | URL 含 `/login`/`checkpoint`/`two_step_verification`；可见 `input[name="email"]`；正向 `a[href*="/latest/home"]` 可见 | `_is_business_logged_out(page)` 69-78 可直接复用，加 goto 约 10 行 | 中高 | Business Suite A/B/地区跳转可能没有 `/latest/home` 导航；引导卡不阻塞 |
| instagram | `uploader/meta_uploader/insgraph_uploader/main.py:56-61,83-97` | `https://www.instagram.com/` | 等待三者之一：`a[href^="/direct/inbox/"]`、`input[name="username"]`、`a[href^="/accounts/login/"]`；有无 inbox 决定 | `_is_instagram_logged_out(page)` 56-61 可复用；`instagram_identity` 64-81 依赖账号文件，MLX 需去掉 | 高 | 60s 等待；挑战页可能三个锚点都不出现而抛超时；不要照搬 `instagram_identity` |
| zhihu | `uploader/zhihu_uploader/session.py:71-95` | `https://www.zhihu.com/creator` | 路径非 `/signin`/`/account/unlogin`；页头 `PROFILE_IMAGE` 存在且与 `.identity.json` 一致 | `read_zhihu_identity(page)` 17-32 可复用；`load_zhihu_identity` 76 的绑定比较在 MLX 不可用 | 高 | 页头 30s 超时会抛错；`verification.py` 39 也 new_context，仅用于发布后核验 |
| xueqiu | `uploader/xueqiu_uploader/session.py:68-92` | `https://mp.xueqiu.com/` | 路径非 `/account/login`；正向 `nav .header-user[data-id]`，且 uid 与绑定一致 | `read_xueqiu_identity(page)` 15-26 可复用；uid 比较 88 在 MLX 不可用 | 高 | HTTP 403/网络错误会抛异常而非 false；`verification.py` 117 也 new_context |
| dayu | `uploader/dayu_uploader/session.py:69-91` | `https://mp.dayu.com/dashboard/index` | 无 `iframe[src*="uop.dayu.com/cas/"]`；正向 `.header-info .name` + 内联脚本 `wmid` 与绑定一致 | `read_dayu_identity(page)` 16-29 可复用；wmid 比较 87 在 MLX 不可用 | 中高 | 登录 iframe 异步出现，过早读取会抛错；`sau_commands/dayu.py:130` 的 verify 也 new_context |
| alipay | `uploader/alipay_uploader/main.py:226-252` | `https://c.alipay.com/page/life-account/index?_appScene=CONTENT&appId=2030022469359777` | URL 非 `auth.alipay.com` 且不含 `login`；无 `iframe[title="login"]` | 抽 233-243（约 11 行）；`_is_alipay_login_completed` 213-224 是登录流程版 | 低 | 只有反向信号；空白页/重定向中页会假阳性；5s 等待对异步 iframe 偏短 |
| baijiahao | `uploader/baijiahao_uploader/main.py:186-208` | `https://baijiahao.baidu.com/builder/rc/home` | 无“注册/登录百家号”文本即有效 | 抽 194-202（约 9 行） | 低 | 没有 URL 跳转/正向业务锚点；空白页会假阳性；`_is_login_completed` 108-118 可提供 `BDUSS/STOKEN` 兜底 |

## 2. 分平台明细

### 2.1 国内

#### douyin

1. **检测 URL**：`https://creator.douyin.com/creator-micro/content/upload`（`uploader/douyin_uploader/main.py:125`）。
2. **标记**：`page.url` 含 `content/upload`，且 `get_by_text("手机号登录")` 与 `get_by_text("扫码登录")` 都无匹配（`main.py:127-128`）。最多重试 3 次（`main.py:118`）。
3. **上下文依赖**：判定只看 `page`；但入口 `cookie_auth` 在 122 行 `new_context(storage_state=account_file)`，并 `set_init_script`（123）。
4. **可复用性**：可以。把 125-129 抽成 `is_logged_in(context)`，内部 `page = await context.new_page()`，约 8 行；`cookie_auth` 保留为本地模式 wrapper。更推荐直接复用 210-232 的 `_is_douyin_login_completed(page)`：它同时检查 `creator-micro` URL 和二维码/登录文字是否可见，是现有最完整的页面级判断。
5. **可靠性**：中高。误判场景：SPA 慢加载（固定等 2500ms，`main.py:126`）、登录提示延迟注入、地区/风控跳转；3 次重试降低偶发。若页面停在根路径而不是 `content/upload`，会判失效；异常会被吞掉并在 133 行返回 false。
6. **备选信号**：创作者中心首页 `https://creator.douyin.com/creator-micro/home`、页头头像、内容管理页 `content/manage`、发布页 file input。上传流程自身在 984-987 等待 `content/upload`，也可作为辅助证据。

#### xiaohongshu

1. **检测 URL**：`https://creator.xiaohongshu.com/publish/publish?from=homepage&target=video`（`uploader/xiaohongshu_uploader/main.py:191-193`，由 `_build_xhs_creator_url` 拼装，33-41）。
2. **标记**：URL 不以 `/login` 开头（197）；`div[class*='login-box']`（`XHS_LOGIN_BOX_SELECTOR`，27）不存在或不可见（201-207）。
3. **上下文依赖**：判定只看 `page`；入口 187 `new_context(storage_state=account_file)`，188 `set_init_script`。
4. **可复用性**：可以。`_is_xhs_login_completed(page)` 163-175 已经是纯页面函数，`is_logged_in(context)` 只需 goto + 调它，约 8-12 行。
5. **可靠性**：中高。误判场景：固定等 3000ms（195）对慢加载不足；登录框选择器是 `class*='login-box'`，前端改版会失效；发布页若被重定向到 `/login` 可正确判 false。
6. **备选信号**：创作者中心首页、页头头像、发布页的 file input、`/api/galaxy/...` 用户信息接口（需实测确认路径）。注意 `uploader/xhs_uploader` 是旧签名器，不属于本检测。

#### ks

1. **检测 URL**：`https://cp.kuaishou.com/article/publish/video`（`uploader/ks_uploader/main.py:25`，goto 236）。
2. **标记**：URL 不含 `passport.kuaishou.com`（238）；无“立即登录”（243）；正向 `button[class^='_upload-btn']` 可见（250-253）；兜底 `_is_ks_cookie_invalid(page)` 的“机构服务”元素（147-153、256）。
3. **上下文依赖**：判定只看 `page`；入口 231 `new_context(storage_state=account_file)`。
4. **可复用性**：可以。抽 238-262 为 `is_logged_in(context)`，约 25 行；`_is_ks_cookie_invalid` 可直接复用。上传前 `validate_base_args` 394 又调 `cookie_auth`，MLX 必须改。
5. **可靠性**：中高。正向按钮是最强证据；误判场景：按钮 class 改版、页面未渲染完就进入 10s 兜底、介绍页文案变化。
6. **备选信号**：`cp.kuaishou.com` 首页用户信息、页头头像、上传页 file input、`/rest/infra/sts` 相关响应。

#### tencent / weixin

1. **检测 URL**：`https://channels.weixin.qq.com/platform/post/create`（`uploader/tencent_uploader/main.py:24`，goto 122）。
2. **标记**：8s 内 `wait_for_url("**/login.html**")`（127）；之后遍历 `page.frames`，发现 `open.weixin.qq.com/connect/qrconnect` 即失效（135）。`_is_tencent_login_completed(page)` 238-268 另有“发表视频/保存草稿/二维码”多标记。
3. **上下文依赖**：判定只看 `page`/frames；入口 119 `new_context(storage_state=account_file)`。`weixin_setup` 477-491 只是调用 `tencent_setup`，没有独立检测。
4. **可复用性**：可以。抽 122-137 约 16 行；或复用 238-268 的 `_is_tencent_login_completed(page)`（更完整，包含正向发布按钮）。上传前 `validate_base_args` 514 仍调 `cookie_auth`。
5. **可靠性**：中。误判场景：前端跳登录页超过 8s（会先判有效）、二维码 iframe 延迟挂载、地区/网络导致空白页；`_is_tencent_login_completed` 的正向标记可显著改善。
6. **备选信号**：`https://channels.weixin.qq.com/platform` 首页、发布页“发表视频/保存草稿”按钮、页头账号区、登录二维码 `div.login-qrcode-wrap`。

#### weibo

1. **检测 URL**：`https://weibo.com/`（`uploader/weibo_uploader/main.py:31`，goto 230）。
2. **标记**：URL 含 `newlogin`/`passport`（233-236）；`get_by_text("登录", exact=True)` 可见（239-241）。
3. **上下文依赖**：判定只看 `page`；入口 228 `new_context(storage_state=account_file)`，未调用 `set_init_script`。
4. **可复用性**：可以。抽 230-241 约 12 行。建议改为复用 137-154 的 `_is_login_completed(page)`：它要求 URL 回首页且有 `Nav_avatar`/`woo-avatar`，或以 `SUB` cookie 兜底，正向证据比“登录”文字强。
5. **可靠性**：中低。误判场景：未登录游客首页也有“登录”按钮；登录后页面其他位置也可能出现“登录”文字；固定等 5s（231）；`SUB` cookie 兜底会把残留 cookie 当有效。
6. **备选信号**：`[class*="Nav_avatar"]`、`[class*="woo-avatar"]`、首页 feed 流、`SUB` cookie（仅 context 内读取，不读文件）。

#### hupu

1. **检测 URL**：`https://bbs.hupu.com/newpost?tabkey=2`（`uploader/hupu_uploader/main.py:34`，goto 250）。
2. **标记**：URL 含 `passport` 或 `login`（254）；正向 `get_by_role("button", name="上传视频")`（259）；兜底 `context.cookies()` 中存在非空 `u`（266）。
3. **上下文依赖**：判定只看 `page` + `context.cookies()`；入口通过 `_create_stealth_context(browser, account_file)` 89-99 创建 `new_context(storage_state=...)`（97），并用 `_new_stealth_page(context)` 101-104 添反检测脚本。
4. **可复用性**：可以。抽 250-268 约 19 行；需要把 `_new_stealth_page` 改成接收外部 context（或直接在外部 page 上 `add_init_script`）。`u` cookie 兜底在 MLX 可读 context cookie，但不建议作为主证据。
5. **可靠性**：中。误判场景：按钮文案改版、URL 中无关 `login` 参数、`u` cookie 过期但仍有值；固定等 5s（251）。
6. **备选信号**：发布页编辑器/上传 file input、页头头像、`bbs.hupu.com` 个人中心。

### 2.2 海外

#### tk（`main.py` 与 `main_chrome.py`）

1. **检测 URL**：`https://www.tiktok.com/tiktokstudio/upload?lang=en`（`uploader/tk_uploader/main.py:23`；`main_chrome.py:24`）。
2. **标记**：`wait_for_load_state('networkidle')` 后遍历所有 `select`，若 class 匹配 `tiktok-.*-SelectFormContainer.*` 判失效，否则判有效（`main.py:24-35`；`main_chrome.py:25-36`）。
3. **上下文依赖**：判定只看 `page`；入口 `main.py:18` / `main_chrome.py:19` `new_context(storage_state=account_file)`。`main.py` 用 `playwright.firefox.launch`（17），`main_chrome.py` 用 Chromium（18）。
4. **可复用性**：**必须新写**。现有判定无法可靠区分登录页/空白页/已登录页；建议 `is_logged_in(context)` 用：URL 是否被重定向到 `/login`、页头头像 `a[href*="/@"]`、上传 file input、`data-e2e` 上传控件、用户信息 API。约 30 行。
5. **可靠性**：低。误判场景：登录页没有 `SelectFormContainer` → 假阳性；页面未加载完 → 假阳性；地区/语言跳转、CAPTCHA。`main_chrome.py` 上传流程 157-160 的 `wait_for_url` 只能证明上传页可达，不能证明登录。
6. **备选信号**：`https://www.tiktok.com/@<user>` 头像/昵称、studio 上传页的 file input、`/api/user/detail/` 响应、页面右上角头像菜单。注意：`sau_cli.py:16-34` 的 `PLATFORMS` 没有 tiktok/tk，当前未接入 CLI；若 MLX 只服务 CLI，这个平台可先不纳入。

#### youtube

1. **检测 URL**：`https://studio.youtube.com`（`uploader/youtube_uploader/main.py:31`，goto 58）。
2. **标记**：URL 不含 `accounts.google.com` 且不含 `/signin`（61），并且含 `/channel/`（63）。
3. **上下文依赖**：判定只看 `page`；入口 55 `new_context(storage_state=account_file)`，硬编码 `channel="chrome"`（53）。上传流程 205 也自己 new_context，并在 213 内联检查 `accounts.google.com`/`signin`。
4. **可复用性**：可以。抽 58-63 约 6 行；这是全仓库最容易抽的一个。上传流程 213 的检查也可改为调用同一 helper。
5. **可靠性**：高。误判场景：3s 后仍停在 `studio.youtube.com` 未跳到 `/channel/` → 假阴性；多频道选择页/账号选择页 URL 不是 `/channel/`；Google 同意页/地区跳转。
6. **备选信号**：`ytcp-avatar`、`ytcp-navigation-drawer`、频道切换器、Studio 首页 URL。

#### facebook

1. **检测 URL**：`https://www.facebook.com/`（`uploader/meta_uploader/facebook_uploader/main.py:19`，goto 62）。
2. **标记**：`_is_logged_out(page)` 34-47：URL 含 `/login`、`checkpoint`、`two_step_verification`、`/authentication/` → 失效；`input[name="email"]` 可见 → 失效；正向 `FACEBOOK_MEDIA_INPUT`（24）数量为 1 → 已登录。
3. **上下文依赖**：判定只看 `page`；入口 `_open_facebook_page` 59 `new_context(storage_state=str(account_file))`，goto 62。
4. **可复用性**：可以。`_is_logged_out(page)` 已是纯页面函数；`is_logged_in(context)` = `new_page` + goto + `not await _is_logged_out(page)`，约 10 行。
5. **可靠性**：高。误判场景：首页 composer 未挂载时 `count()!=1` → 假阴性；页面有多个同类型 file input → 假阴性；cookie 同意弹窗可能挡住 composer。二次验证页已显式处理。
6. **备选信号**：`[aria-label="Your profile"]`、`div[role="navigation"]`、composer 的 “What's on your mind?”、`c_user` cookie。

#### facebook-page

1. **检测 URL**：`https://business.facebook.com/latest/composer/`（`uploader/meta_uploader/facebook_page_uploader/main.py:19`，goto 51）。
2. **标记**：`_is_business_logged_out(page)` 69-78：URL 含 `/login`、`checkpoint`、`two_step_verification` → 失效；`input[name="email"]` 可见 → 失效；正向 `a[href*="/latest/home"]` 可见 → 已登录。
3. **上下文依赖**：判定只看 `page`；入口 `_open_business_page` 48 `new_context(storage_state=str(account_file))`，goto 51。
4. **可复用性**：可以。`_is_business_logged_out(page)` 已是纯页面函数；加 goto 约 10 行。
5. **可靠性**：中高。误判场景：Business Suite 地区/A/B 跳转后没有 `/latest/home` 导航 → 假阴性；引导卡/权限弹窗；多主页选择页。`dismiss_guidance_cards` 59-67 只处理已知 GeoGuidanceCard，不能解决登录判断。
6. **备选信号**：`business.facebook.com/latest/home`、账号切换器、主页头像、`c_user` cookie。

#### instagram

1. **检测 URL**：`https://www.instagram.com/`（`uploader/meta_uploader/insgraph_uploader/main.py:14`，goto 49）。
2. **标记**：`_is_instagram_logged_out(page)` 56-61：等待三者之一出现——`a[href^="/direct/inbox/"]`、`input[name="username"]`、`a[href^="/accounts/login/"]`；有 inbox 即已登录。`instagram_identity` 64-81 还会比对 `ds_user_id` 并读自己的主页链接。
3. **上下文依赖**：登录判断只看 `page`；`instagram_identity` 额外读账号 JSON（69），依赖 `account_file`。入口 `_open_instagram_page` 46 `new_context(storage_state=str(account_file))`。
4. **可复用性**：部分可以。`_is_instagram_logged_out(page)` 56-61 可直接复用；`instagram_cookie_auth` 83-97 里的 `instagram_identity`（90）在 MLX 无账号文件时不能调用，应只保留“是否登录”。
5. **可靠性**：高。误判场景：挑战/验证页三个锚点都不出现 → `expect` 超时抛错（不是 false）；60s 等待较长；登录表单 `input[name="username"]` 出现即判未登录，但某些弹窗登录也可能有该字段。
6. **备选信号**：`a[href^="/direct/inbox/"]`、导航头像 `[aria-selected] img`、`ds_user_id` cookie（只从 context 读）。

### 2.3 图文

#### zhihu（session / video / article / verification）

1. **检测 URL**：`https://www.zhihu.com/creator`（`uploader/zhihu_uploader/constants.py:5`；`session.py:84`）。
2. **标记**：HTTP >= 400 抛错（85-86）；路径以 `/signin` 或 `/account/unlogin` 开头 → 失效（88）；否则读页头 `button.AppHeader-profileEntry img[alt^='点击打开'][alt$='的主页']`（`PROFILE_IMAGE`，14；`read_zhihu_identity` 17-32），并与 `.identity.json` 比对（76、90-92）。
3. **上下文依赖**：检测入口 82 `new_context(storage_state=..., timezone_id="Asia/Shanghai")`；身份绑定依赖 `load_zhihu_identity` 35-41 读 `.identity.json`。`video.py:207-209` / `article.py:197-199` 上传时也各自 new_context + storage_state；`verification.py:39` 发布后核验同样 new_context。
4. **可复用性**：部分可以。`read_zhihu_identity(page)` 17-32 是纯页面函数；`is_logged_in(context)` = goto + `read_zhihu_identity(page)` 不抛错即为已登录，约 10 行。但现有 `check_zhihu_account` 在 76 行先读绑定文件，MLX 必须把这段移出或改成可选。
5. **可靠性**：高（对“是否登录”）；身份一致性在 MLX 无法验证。误判场景：页头 30s 超时抛出而不是 false；创作中心改版导致 `PROFILE_IMAGE` 失效；地区/CDN 慢加载。
6. **备选信号**：`/creator/manage/creation` 内容管理页、页头显示名、创作中心 API。`video.py:213`、`article.py:202` 上传时也调用 `read_zhihu_identity(page)`，可复用同一页面判断。

#### xueqiu

1. **检测 URL**：`https://mp.xueqiu.com/`（`uploader/xueqiu_uploader/constants.py:3`；`session.py:81`）。
2. **标记**：HTTP >= 400 抛错（82-83）；路径 `/account/login` → 失效（85）；否则读 `nav .header-user[data-id]`（18；`read_xueqiu_identity` 15-26），并比较 uid（88）。
3. **上下文依赖**：检测入口 79 `new_context(storage_state=str(account_file))`；uid 绑定依赖 `.identity.json`（73、29-35）。`article.py:210` 上传也 new_context + storage_state，`verification.py:117` 核验同样。
4. **可复用性**：部分可以。`read_xueqiu_identity(page)` 15-26 是纯页面函数；`is_logged_in(context)` = goto + 读取 header-user 存在即可，约 10 行。uid 比较在 MLX 无绑定文件时去掉。
5. **可靠性**：高（是否登录）；误判场景：403/风控/网络错误抛异常；页头结构改版；MP 站与主站登录态不同步。
6. **备选信号**：`mp.xueqiu.com` 首页 header、创作者中心、`/account/login` 跳转。

#### dayu

1. **检测 URL**：`https://mp.dayu.com/dashboard/index`（`uploader/dayu_uploader/session.py:12`，goto 82）。
2. **标记**：存在 `iframe[src*="uop.dayu.com/cas/"]` → 失效（84）；否则读 `.header-info .name` 和内联脚本里的 `wmid`（`read_dayu_identity` 16-29），并比较 wmid（87）。
3. **上下文依赖**：检测入口 80 `new_context(storage_state=str(account_file))`；wmid 绑定依赖 `.identity.json`（74、32-38）。`main.py:198` 视频、`article.py:267` 文章上传也 new_context；`sau_commands/dayu.py:130` 的 verify 也 new_context。
4. **可复用性**：部分可以。`read_dayu_identity(page)` 16-29 是纯页面函数；`is_logged_in(context)` = goto + 检查 CAS iframe + header name 存在，约 12 行。wmid 比较在 MLX 需要去掉或另找 Profile 元数据。
5. **可靠性**：中高。误判场景：CAS iframe 延迟挂载，过早读取 `.header-info .name` 抛错；页面脚本结构变化导致无法提取 wmid；后台改版。
6. **备选信号**：`https://mp.dayu.com/dashboard/index` 页头、`uop.dayu.com/cas/` iframe、创作中心作品列表。

#### alipay

1. **检测 URL**：`https://c.alipay.com/page/life-account/index?_appScene=CONTENT&appId=2030022469359777`（`uploader/alipay_uploader/main.py:22`，goto 233）。
2. **标记**：URL 以 `https://auth.alipay.com/` 开头或含 `login` → 失效（238）；`iframe[title="login"]` 存在 → 失效（241）。没有正向“已登录”标记。
3. **上下文依赖**：判定只看 `page`；入口 231 `new_context(storage_state=account_file)`，未 set_init_script。`_is_alipay_login_completed` 213-224 是登录流程版，逻辑同样是“iframe 消失 + URL 回到 c.alipay.com”。
4. **可复用性**：可以。抽 233-243 约 11 行；但需要补正向锚点，否则只是“没看到登录框”。
5. **可靠性**：低。误判场景：5s 内登录 iframe 还没注入（登录态失效但 iframe 慢）→ 假阳性；空白页/重定向中页 → 假阳性；`login` 子串可能出现在无关 URL。
6. **备选信号**：`https://c.alipay.com/page/content-creation/posts`（`ALIPAY_POSTS_URL`，23）能打开作品列表、页头账号/头像、生活号后台信息、登录 iframe 消失。

#### baijiahao

1. **检测 URL**：`https://baijiahao.baidu.com/builder/rc/home`（`uploader/baijiahao_uploader/main.py:28`，goto 194）。
2. **标记**：`get_by_text("注册/登录百家号")` 存在 → 失效（197）；否则有效。没有 URL 跳转判断，也没有正向业务锚点。
3. **上下文依赖**：判定只看 `page`；入口 192 `new_context(storage_state=account_file)`。`_is_login_completed` 108-118 是登录流程版（URL 离开 login 或 `BDUSS`/`STOKEN` cookie）。
4. **可复用性**：可以。抽 194-202 约 9 行；建议同时加 URL 跳转检查和正向元素。
5. **可靠性**：低。误判场景：空白页/HTTP 错误页没有“注册/登录百家号” → 假阳性；文本延迟渲染；百家号后台改版。
6. **备选信号**：`builder/rc/home` 首页侧栏/账号区、发布页 `builder/rc/edit?type=videoV2`、头像、`BDUSS`/`STOKEN` cookie（仅 context 读）。

## 3. 必须新写检测的平台

严格按“现有判定逻辑不可用、必须重写”的标准：

- **TikTok（`uploader/tk_uploader/main.py` 与 `main_chrome.py`）**：现有 `select` class 反推既不能证明已登录，也不能证明未登录；登录页/空白页/慢加载都会假阳性（`main.py:24-35`、`main_chrome.py:25-36`）。需要新写 `is_logged_in(context)`。注意它当前未接入 `sau_cli.PLATFORMS`（`sau_cli.py:16-34`）。
- **支付宝（`uploader/alipay_uploader/main.py:226-252`）**：现有逻辑只有反向信号，建议按“新写”对待，至少补正向 URL/元素。
- **百家号（`uploader/baijiahao_uploader/main.py:186-208`）**：同上，只有反向文本信号，建议按“新写”对待。

需要“补正向信号”但骨架可保留：**微博**（用 `_is_login_completed` 的头像/feed）、**虎扑**（按钮选择器 + 头像）、**视频号**（用 `_is_tencent_login_completed`）。

## 4. 无法可靠检测、只能靠上传失败归类的平台

- **TikTok**：即使重写，TikTok Studio 的登录页/地区跳转/CAPTCHA 仍可能让页面既没有头像也没有登录表单。若 `is_logged_in` 仍无法给出稳定正向证据，建议 MLX 模式只做“URL 是否被踢到 `/login`”+ 上传后失败归类，不把假阳性当成功。
- **支付宝、百家号（若不做正向补强）**：现有检测只有“没看到登录标记”，空白页/错误页会假阳性；在补上 `ALIPAY_POSTS_URL` / 百家号后台正向锚点之前，只能靠上传阶段失败（找不到发布控件/跳登录）归类。
- 其余平台都有可用的正向锚点（URL、头像、发布控件），不建议归入此类。

## 5. 绝不能直接用于 MLX 模式的调用点（会 `new_context` / 写 cookie）

现有检测函数本身只“建 context”，一般不写 `storage_state`；`new_context(storage_state=account_file)` 同时会**读取 cookie 文件**，是 MLX 的双重违规。写 cookie 主要发生在 `*_setup`/`*_cookie_gen` 的登录收尾和上传流程末尾；两类都必须从 MLX 调用链里排除。

### 5.1 检测函数本身会创建新 context

| 检测函数 | `new_context` 位置 |
|---|---|
| `myUtils/auth.py:cookie_auth_douyin/tencent/ks/xhs`（legacy Flask 后台，`sau_backend.py:242`） | 18 / 46 / 64 / 83 |
| `uploader/douyin_uploader/main.py:cookie_auth` | 122 |
| `uploader/xiaohongshu_uploader/main.py:cookie_auth` | 187 |
| `uploader/ks_uploader/main.py:cookie_auth` | 231 |
| `uploader/tencent_uploader/main.py:cookie_auth` | 119 |
| `uploader/weibo_uploader/main.py:cookie_auth` | 228 |
| `uploader/hupu_uploader/main.py:cookie_auth` | 248 → `_create_stealth_context` 89-99，`new_context` 97 |
| `uploader/tk_uploader/main.py:cookie_auth` | 18 |
| `uploader/tk_uploader/main_chrome.py:cookie_auth` | 19 |
| `uploader/youtube_uploader/main.py:cookie_auth` | 55 |
| `uploader/meta_uploader/facebook_uploader/main.py:facebook_cookie_auth` | 71 → `_open_facebook_page` 50-69，`new_context` 59 |
| `uploader/meta_uploader/facebook_page_uploader/main.py:meta_cookie_auth` | 81 → `_open_business_page` 37-57，`new_context` 48 |
| `uploader/meta_uploader/insgraph_uploader/main.py:instagram_cookie_auth` | 83 → `_open_instagram_page` 42-53，`new_context` 46 |
| `uploader/zhihu_uploader/session.py:check_zhihu_account` | 82；`verification.py:verify_zhihu_result` 39 |
| `uploader/xueqiu_uploader/session.py:check_xueqiu_account` | 79；`verification.py:verify_xueqiu_result` 117 |
| `uploader/dayu_uploader/session.py:check_dayu_account` | 80；`sau_commands/dayu.py` verify 130 |
| `uploader/alipay_uploader/main.py:cookie_auth` | 231 |
| `uploader/baijiahao_uploader/main.py:cookie_auth` | 192 |

### 5.2 登录/setup 流程会建 context 并写 `storage_state`

这些函数在 MLX 模式下一律不能调用（会覆盖 Profile cookie）：

- douyin：`douyin_cookie_gen` `new_context` 280 / `storage_state(path=...)` 301；上传写 1112、1253。
- ks：`get_ks_cookie` 304 / 320；上传写 743、908。
- tencent：`tencent_cookie_gen` 396 / 422；上传写 1133、1233。
- xiaohongshu：`xiaohongshu_cookie_gen` 257 / 272；上传写 715、838。
- weibo：`weibo_cookie_gen` 169 / 208；上传写 367。
- hupu：`hupu_cookie_gen` 120（helper）/ 177；上传写 378。
- youtube：`youtube_cookie_gen` 75 / 88；上传写 325。
- tk：`get_tiktok_cookie` `main.py` 62 / 69；`main_chrome.py` 63 / 70；上传写 `main.py` 180、`main_chrome.py` 192。
- facebook：`facebook_setup` 121 / 131；上传写 270；`posts.py` 185。
- facebook-page：`meta_setup` 119 / 126；上传写 439；`posts.py` 148。
- instagram：`instagram_setup` 114 / 119；上传写 331；`posts.py` 105。
- zhihu：`login_zhihu_account` 54 / 64；`video.py` 207-209 和 `article.py` 197-199 上传建 context（未写回）；`verification.py` 39 建 context。
- xueqiu：`login_xueqiu_account` 48 / 61；上传写 `article.py` 269；`verification.py` 117。
- dayu：`login_dayu_account` 50 / 62；上传写 `main.py` 221、`article.py` 284；`sau_commands/dayu.py:130` verify。
- alipay：`alipay_cookie_gen` 149 / 192；上传写 696。
- baijiahao：`baijiahao_cookie_gen` 133 / 172；上传写 320。

### 5.3 CLI check 包装器还依赖 `account_file` 存在

MLX 模式 `--account` 可省略，但这些包装器先检查本地文件，不能直接复用：

`sau_commands/douyin.py:108-112`、`xiaohongshu.py:90-94`、`kuaishou.py:91-95`、`tencent.py:77-81`、`weibo.py:56-60`、`hupu.py:54-58`、`youtube.py:63-67`、`facebook.py:110-116`、`facebook_page.py:109-111`、`alipay.py:56-60`、`baijiahao.py:60-64`；`zhihu/xueqiu/dayu` 的 `check_*` 在各自 `session.py` 内部也先 `is_file()`（`zhihu session.py:74-75`、`xueqiu session.py:71-72`、`dayu session.py:72-73`）。Instagram 的 `check_instagram_account` 不先查文件，但 `instagram_cookie_auth` 83-86 会查。

## 6. 给后续设计的落点建议

- 统一签名：`async def is_logged_in(context: BrowserContext) -> bool`，放在各平台模块或 `utils/login_detection.py`；内部只允许 `context.new_page()`、`page.goto()`、`page.close()`。
- 统一错误语义：网络错误/HTTP 5xx/超时 → 抛异常（CLI 退出 1）；明确的登录页/登录表单/未登录锚点 → `False`（CLI 退出 10）。现有大量 `except: return False`（如 `douyin main.py:129-133`、`alipay main.py:247-249`、`baijiahao main.py:203-205`）会把网络故障误判为未登录，MLX 不能照搬。
- 统一超时：建议 15-30s，按平台调整；不要沿用 2.5s/3s/5s 的固定 `wait_for_timeout`。
- 身份绑定：知乎/雪球/大鱼号/Instagram 的 `.identity.json` 比较在 MLX 下没有 `--account` 映射，只能验证“已登录”，不能验证“是哪个账号”；若要保留账号绑定，需要另行定义 Profile 元数据来源（不在本 ticket 范围）。
- 初始化脚本：`utils/base_social_media.py:21-24` 的 `set_init_script` 会 `context.add_init_script`；MLX 下是否调用取决于 ticket 02，若 Mimic 自带指纹，建议跳过。
