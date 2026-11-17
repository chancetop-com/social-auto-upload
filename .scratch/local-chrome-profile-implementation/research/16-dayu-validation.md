# 16 大鱼号验证记录

日期：2026-11-17。实施基线 `9b7ef7a`，隔离 worktree `/private/tmp/sau-local-profile-16`。保留用户配置与真实账号资料；所有 Profile 均使用临时根，未登录真实大鱼号账号、未发布或删除作品。

## 接入与所有权

- 正式 `login`、`check`、`upload-video`、`upload-article`、`verify`、`reset-profile` 及直接 `login_dayu_account` / `check_dayu_account` / `DayuVideo.main` / `DayuArticle.main` 接入共享 Profile/config/session。注入会话由调用者管理；同次操作不另开主 Profile。
- 旧 Cookie 存在检查、storage_state 恢复/导出、`load_dayu_identity` 与身份旁文件写入全部退出。当前业务需要时读取格式有效的 wmid/name，check 只等待正向登录锚点；别名可换号。显式 expected-name、历史结果 wmid、原作品编号/标题/排期和公开作者核验保留。
- 视频/文章保留提交预算、not-before、人类化、响应监听、结果文件与 prepare-only；文章保留创作站点限定剪贴板授权、ClipboardItem/原生粘贴、图文位置及内容读回，不新增地理位置/语言/指纹/固定 viewport。
- `verify --public` 在登录后台核对后调用同一 `session.browser.new_context(no_viewport=True)`，无目录绑定或状态复制。匿名 context 使用已有有界关闭；外层仍拥有主 context 与锁。文章预览页由本地 persistent context 统一关闭，避免嵌套 page.close 阻塞外层清理；托管保留原关闭路径。
- 托管 check/视频/文章仍走原 provider 与 CDP 所有权；本地来源完全忽略，只采用新 headless 默认来源。verify 在 provider 环境中仍使用原始本地别名。

## TDD 与离线结果

已确认测试边界来自原 spec 的 Testing Decisions。新测试通过正式 CLI dispatch、真实配置、真实 Profile 文件系统/锁与共享 session；仅替换浏览器 DOM/API 和 provider 边界。直接入口与已有注入会话只补 CLI 无法覆盖的所有权。

实际 red → green：

1. login/check 旧实现触发 `Use the persistent Profile`；接入后同别名重登、旧损坏 JSON 不变、无 storage_state 调用通过。
2. 认证分类原来把 CAS 跳转/verify 返回 1、错误域名返回 0；修正后缺少 Profile/明确登录/验证为 10，权限/网络/结构为 1。
3. 视频/文章原来被旧账号文件门槛拦住；移除后从真实 CLI 到达当前身份、媒体/创作站点剪贴板边界。
4. verify 原来依赖被删除的 sidecar loader；接入后后台先行、匿名成功/失败/取消、有界关闭、主锁/所有权及历史结果拒绝换号全部通过。
5. 完整视频边界流程原来把提交后的登录/验证/API 认证跳转当成功；修正后保留 10 + publish_attempted、单次提交、未知 9 和关闭失败下的原结果。
6. 原稿 API 登录跳转原来是字段故障 1，等待页头期间跳转也返回 1；修正后明确认证证据返回 10，提交前不标 attempted。

最终离线命令（本机 `.venv` 只复用解释器依赖，cwd 和导入配置为本 worktree）：

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest \
  tests.test_dayu_profiles tests.test_dayu_humanize \
  tests.test_dayu_schedule.DayuScheduleTests tests.test_dayu_schedule.DayuScheduleReadbackTests \
  tests.test_dayu_article.DayuArticleFileTests tests.test_dayu_article.DayuPublicationDispatchGuardTests \
  tests.test_dayu_article.DayuPublicationResponseTests tests.test_dayu_uploader.DayuMediaTests \
  tests.test_mlx_hupu_dayu tests.test_adspower_article_identity_platforms \
  tests.test_local_browser_session tests.test_local_profile -q
```

实际 **143 tests passed**，其中新增 20 项 Dayu Profile 行为测试。覆盖默认/显式模式、Chrome/Chromium/custom 来源、缺少 optional config、失败不回退、精确重建/占用、取消/挂起清理、显式名称/历史主体保护、全部正式入口、直接入口、托管两种 provider 的隔离/限流及提交结果。退役了旧 Dayu Cookie 启动与 parser-only 本地断言；托管当前身份跳过、权限与发布行为回归保留。

`compileall` 与 `git diff --check` 通过。日志保存在本机 `/private/tmp/dayu-final-offline.log`；各 red 记录在 `/private/tmp/dayu-red-*.log`。

## 真实浏览器受控证据

以 [02 的八配置持久化/匿名证据](./02-browser-validation.md) 为基础，本票没有修改共享浏览器 resolver 或 session API。补跑 Dayu 实际 `verify_dayu_article` 的受控匿名流程，脚本 [16-dayu-browser-smoke.py](./16-dayu-browser-smoke.py)，无真实平台请求（页面全部 route 为合成 HTML，后台 API 使用离线响应）。

| 浏览器 | 模式 | 实际版本 | 结果 |
| --- | --- | --- | --- |
| 系统 Chrome | 有头 | 157.0.8103.79 | 通过 |
| Patchright 完整 Chromium revision 1248 | 无头 | 156.0.8078.4 | 通过 |

脚本实际输出 `PASS 2 Dayu controlled configurations`。观察到主/匿名页面均无固定 viewport；匿名初始 Cookie/localStorage 不含主 Profile 内容；匿名写入不污染主资料；匿名关闭后主页面可用，主锁在整个公开检查中仍占用；正常关闭重开后主状态保存，匿名状态未出现。记录版本、模式和隔离结果的日志为 `/private/tmp/dayu-browser-smoke.log`。

另外执行已有真实浏览器合成 DOM/内容/播放测试：

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest \
  tests.test_dayu_article.DayuArticleBrowserTests \
  tests.test_dayu_uploader.DayuBrowserTests \
  tests.test_dayu_schedule.DayuScheduleBrowserTests -q
```

实际 **15 tests passed**，覆盖匿名公开视频/图文内容、顺序与样式、真实媒体播放、服务端预览、仅一次确认、处理等待与定时控件。浏览器启动按本环境要求使用 sandbox escalation。首次运行暴露 worktree 缺少已有 Markdown 依赖及一个 test fixture kwargs 转发错误；修复 fixture，并仅在 worktree 建立指向原已安装 node_modules 的忽略链接，使用现有 Node.js v22.22.3，未下载依赖。最终完整重跑通过，日志 `/private/tmp/dayu-browser-regressions.log`。

## 范围限制

以上是离线和真实浏览器合成页面验证，不是大鱼号真实账号/平台验收。未执行任何真实登录、素材上传、发布、删除、旧资料迁移或 Windows/Linux 浏览器实测。旧资料一次性处理仍属 19，四平台真实 no-publish 属 20。合入 `be16eb5` 后，雪球 18 已接入；当前本分支尚未接入知乎（17 并行实施）；Bilibili 在此次 Profile 范围外。

集成同步：实施提交 `f76a532` 后合入 `be16eb5`（18 雪球）。冲突限于迁移平台清单、文档追加段落和 reset 注册测试；保留双方条目及身份迁移说明。共享 article/provider 测试按平台范围自动合并。

合并后验证：上面的完整离线命令再追加 `tests.test_xueqiu_profiles`，实际 **157 tests passed**（`/private/tmp/dayu-merged-regressions.log`）。共享 reset 清单和 Dayu/Xueqiu 的 provider 测试均通过；本次合并未改 Dayu 浏览器业务，15 项受控 DOM 与 2/2 匿名实测证据仍适用。
