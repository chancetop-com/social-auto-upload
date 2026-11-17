# 17：知乎持久化 Profile 验证记录

日期：2026-11-17。实现分支 `codex/local-profile-17`，隔离工作树 `/private/tmp/sau-local-profile-17`，起点 integration `9b7ef7a`。未操作真实知乎账号、发布或删除作品。

## 覆盖入口

| 正式入口 | 直接调用与资源所有权 |
| --- | --- |
| login | `login_zhihu_account`，仅此入口 create=True；浏览器自行保存 Profile，允许同别名换号 |
| check | `check_zhihu_account` / `is_logged_in(managed=False)`，明确登录/验证为 10，页面/HTTP/字段/网络故障为 1 |
| upload-article | `ZhihuArticle.main`，预检和编辑共用一个 session/占用，保留原稿粘贴、配图、内容读回和 origin 剪贴板权限 |
| upload-video | `ZhihuVideo.main`，预检、上传、实时选项、字段读回和提交共用 Profile |
| verify | `verify_zhihu_result`，provider 环境下仍使用原始本地别名；保留原 URL/标题/历史账号证据，换号失败不改写结果 |
| reset-profile | 共享精确重建；无需 binary、占用保护、另一种类与历史结果保留 |

注入本地 session 时只借用 context，不启动或关闭它。独立入口通过共享有界 context 清理释放占用；本地 probe 不提前 await page.close。旧 `.json` 和 `.identity.json` 不检查、不读取、不导出、不清理；旧位置参数只解析别名并保留结果目录约定。CLI 结果继续保存在 `cookies/zhihu_results/`，直接调用传 account_file 时仍在其父目录的 `zhihu_results/`。name/avatar_path 来自当次页面，不作为未来登录的永久身份；删除视频仅防中途换号的前后比较。知乎原来没有 expected-name 选项，本票未新增；已有菜单/标题/原作品请求继续校验。

MLX/AdsPower 保留原路径、权限、日志、CDP 所有权和限流码，仅使用统一 headless 来源；local-browser/LOCAL_BROWSER/LOCAL_CHROME_PATH 不触发本地解析。verify 保持本地例外。没有共享运行时改动。

## TDD 实际红绿

先写 `tests/test_zhihu_profiles.py`，从正式 CLI dispatch 进入真实配置、Profile 和 session 编排，仅替换 Playwright、页面/媒体读取与 provider 边界。

- 登录/换号首轮红：旧代码调用非持久 launch，退出 1，诊断 `use persistent Profile`；接入共享 session 后绿。
- 登录分类首轮红：验证码缺 reason，403 被误判有效，登录重定向后的导航异常返回 1；实现 local 分类后绿。
- 文章/视频首轮分别红：旧 JSON 不存在时报“请先执行 sau zhihu login 保存账号”；移除预检和旁文件门槛后完整准备流程绿。
- 原作品 verify 首轮红：尝试读取旧 `.identity.json`；改用结果文件历史证据后，换号拒绝、同主体核验通过，历史身份不变。
- reset/托管默认首轮红：reset 未注册、provider 收到 None 而非配置 True；注册和统一 headless 后绿。
- 文章提交阶段首轮 3 个红：提交前验证码返回 1，提交后/点击报错验证码返回 9；改为 exit 10 + 正确 publish_attempted 后绿，真正未知仍为 9。
- 登录证据首轮红：登录 URL 上的伪阳性头像仍被接受；登录/头像格式检查后绿。
- verify 读回时登录失效首轮红：返回 1；改为 exit 10/reason=verification，结果文件字节不变后绿。

补充覆盖 Chrome/Chromium 分目录、显式/缺省 headless、旧损坏文件无关、custom binary 实际种类覆盖与不回退、缺少可选配置、borrowed session、取消/挂起关闭、预检失败不进入业务、视频已确认成功后的详情故障、请求至多提交一次、托管 login/reset 限制及 429。

## 已执行验证

解释器：`/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python`，所有命令 cwd 为本隔离工作树，`PYTHONPATH=.`。导入前断言 conf.__file__ 和 BASE_DIR 绑定本工作树，未读取或修改原工作树配置/账号资料。

```bash
PYTHONPATH=. /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_zhihu_profiles tests.test_mlx_zhihu_xueqiu tests.test_adspower_article_identity_platforms tests.test_zhihu_humanize tests.test_publish_cleanup tests.test_local_profile tests.test_adspower_platform_contract tests.test_multilogin_cli tests.test_adspower_cli tests.test_humanize tests.test_review_regressions tests.test_publish_timeout tests.test_local_browser_session tests.test_browser_session tests.test_sau_browser_cli -q
```

结果：**347 passed，11.110s**，其中新 Profile 测试 16 项（含多种场景 subtests）。更新的旧断言仅移除 Zhihu 旧启动/身份旁文件假设；其余平台断言保留。

```bash
PYTHONPATH=. /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_zhihu_uploader -v
```

结果：**6 passed，2.232s**。其中 1 项为真实 Chrome 无头本地合成 DOM 测试，验证全文、图片交错顺序、格式及链接；其余 5 项是 CLI/媒体参数测试。使用隔离临时目录和本地 set_content，未访问知乎账号。此项不代表知乎真实发布验收，也不是新的浏览器持久化矩阵；共享 02 的实际浏览器证据仍适用，本票未改变共享生命周期或启动 API。

另在新 Python 进程中仅给 conf 提供 BASE_DIR，导入知乎 command/session/article/video/verification 与共享解析器成功，默认解析 Chrome + headless=False；确认三个可选浏览器配置均不是本平台 import 硬依赖。`git diff --check` 通过。

## 未执行与范围

本票未执行真实知乎登录/发表/删除，不要求新增知乎账号。原有非 PNG 真实上传、完整线上文章链路及定时受理尚未因此得到验收；离线和合成 DOM 不冒充这些结果。Dayu/Xueqiu 分别由 16/18 交付；本票不改它们运行时。一次性旧资料作业属于 19，四指定平台真实 no-publish 与最终全入口收口属于 20。Bilibili 及正式 CLI 不可达历史入口不在范围内。

## 合入第五批并行交付

合入 integration `be16eb5`（雪球 18）后，合并共享平台列表、provider 本地路由断言，并移除两个平台都已被公共 CLI 测试取代的旧 local-launch 测试类。上述离线命令增加 `tests.test_xueqiu_profiles` 后，**357 passed / 11.360s**；未修改 Xueqiu 运行时。

随后合入 integration `03b6865`（大鱼号 16），共享平台列表采用 Dayu/Zhihu/Xueqiu 并集，保留各自 provider/local-action 测试。离线命令再增加 `tests.test_dayu_profiles` 后，最终 **376 passed / 14.831s**。Bilibili 未迁移 reset 的单项集合保留为真正 tuple，避免字符串逐字符测试；其专项检查再次通过。`git diff --check` 通过，未改动 Dayu/Xueqiu 运行时。
