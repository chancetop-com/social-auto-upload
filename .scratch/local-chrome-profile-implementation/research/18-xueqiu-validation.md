# 18：雪球持久化 Profile 验证记录

日期：2026-11-17。工作树 `/private/tmp/sau-local-profile-18`，分支 `codex/local-profile-18`；基于集成 `9b7ef7a`。解释器为主仓库已有 `.venv/bin/python`，已确认 `conf.__file__` 与 `conf.BASE_DIR` 都绑定本工作树。所有新测试使用临时目录，不读取真实账号资料。

## 覆盖入口及实现

- 正式 CLI `login`、`check`、`upload-article`、`verify`、`reset-profile`；直接 `login_xueqiu_account`、`check_xueqiu_account`、`XueqiuArticle.main` 和 `verify_xueqiu_result`。只改已注册路径，无视频或其他历史入口扩展。
- 本地调用共享真实配置解析、Profile 定位/锁和 `local_browser_session`。注入 session 不重开、不关闭；login 才创建 Profile 并引导登录，业务页面由 persistent context 有界清理。
- 删除 `load_xueqiu_identity`、身份旁文件读写/防换号比较、JSON 存在检查及 storage_state 恢复/导出。login/check/verify 连旧账号文件路径也不定位。文章保留 `account_file` 作为历史结果目录提示，正式结果仍写 `cookies/xueqiu_results/`。
- 当前页面读取并验证非空 name 与正整数 uid；显式 expected-name、本次受理响应作者及历史作品作者/标题/可见性/正文证据保留。verify 拒绝当前账号或服务端原作品作者不符，不把历史 identity 改为新账号。
- Chrome/Chromium、headless 显式/配置优先级及自定义路径通过共享入口执行；optional LOCAL_BROWSER 缺失使用 fallback。托管保留原 launch kwargs/logs、所有权、身份/授权行为，仅 headless 采用新解析；verify 仍走本地原始别名。
- 保留创作站点 origin 限定剪贴板、ClipboardItem、原生粘贴、选区/图片标记、文件选择器、封面裁剪、结构读回、人类化交互、not-before、发布预算和单次提交。未增加 stealth、UA、语言、固定 viewport 或地理权限。

## TDD 证据

主要 seam 为正式 CLI dispatch → 真实配置/Profile/session；替身仅位于浏览器、页面与 provider 外部边界，未把 session 整体替换为 parser 断言。

1. login/check + 同别名换号：首轮失败 `temporary browser forbidden`；迁移后通过，损坏旧 Cookie/identity 文件保持原样。
2. 登录分类：先检出 403 误报有效、验证码丢失 reason 和导航中验证码被误报故障；修复后登录/验证为 10，字段/网络/HTTP 故障为 1。
3. 完整文章 prepare：先失败 `请先执行 sau xueqiu login 保存账号`；迁移后通过完整填写/剪贴板/预览/结果写入，只有一次 persistent launch。
4. verify：先失败读取不存在的 `.identity.json`；迁移后以结果中的原作者核对当前 Profile，并保留历史作者；当前主体和服务端记录作者不符均拒绝且不改结果。
5. HTTP 403 位于登录形状 URL：verify 首轮错误返回 10；加入访问失败分类后 check/verify/article 都保持 1，login 超时仍识别已观察的验证码并返回 10。
6. login/check/verify 旧路径退出：禁止旧路径定位的测试首轮失败；只为文章结果保留路径提示后通过。

## 实际执行结果

在工作树中运行（下方 `python` 指主仓库已有 `.venv/bin/python`）：

```sh
python -m unittest tests.test_xueqiu_profiles tests.test_xueqiu_humanize tests.test_mlx_zhihu_xueqiu tests.test_adspower_article_identity_platforms tests.test_publish_cleanup tests.test_sau_browser_cli tests.test_local_profile tests.test_local_browser_session tests.test_adspower_cli tests.test_adspower_platform_contract tests.test_multilogin_cli tests.test_review_regressions tests.test_humanize tests.test_article_render -q
```

结果：**299 tests，28.274s，OK**。涵盖本地/托管配置、浏览器种类隔离、自定义路径与启动失败、缺省可选配置、lease/reset、成功/未知/提交后登录、验证 reason、清理失败、取消及挂起关闭的有界释放。之后扩充原作品服务端作者不符断言，重跑 `tests.test_xueqiu_profiles`：**14 tests，0.780s，OK**。

```sh
python -m unittest tests.test_xueqiu_profile_dom tests.test_xueqiu_uploader -v
```

结果：**16 tests，16.656s，OK**。浏览器运行使用环境需要的沙箱外执行授权，测试隔离临时根、拦截全部平台/图片请求，未访问真实账号。

| 真实浏览器配置 | 版本 | 结果 |
| --- | --- | --- |
| 系统 Chrome，有头，no_viewport | 157.0.8103.79 | login → 正常关闭 → check → 正常关闭 → 完整文章 prepare 通过 |
| 配套完整 Chromium，无头，no_viewport | 156.0.8078.4 | 同上，通过 |

每条合成文章流程包括真实 ClipboardItem/HTML 粘贴、两张原位置图片的选区替换/上传、独立封面/裁剪、私人分享、AI 声明、预览与文字/图片/结构读回；共六次 persistent launch，context 正常关闭后 browser 都断开，未生成旧 Cookie/identity 文件。现有内容测试也验证错图、段间图片移动、标题结构和链接目标错误。

首轮浏览器/内容组合有一项 Markdown 测试因工作树缺少 `utils/article_renderer/node_modules` 失败；复用主仓库已安装依赖的忽略目录符号链接后该项通过，再执行上面的完整 16 项组合通过。未安装新依赖、未改用户配置。

提交后执行 `git merge codex/local-chrome-profile`：最新集成仍为 `9b7ef7a`，返回 Already up to date。随后重跑 Xueqiu Profile、MLX/AdsPower 文章身份与共享 Profile 测试：**106 tests，3.983s，OK**。

`git diff --check` 通过；CLI/平台说明、独立可安装平台 skill、配置示例、安装/Bootstrap/术语及共享 reset 平台测试已同步。

## 范围与未执行项

本记录是离线与受控合成浏览器证据，不是雪球真实平台登录或发表验收。未执行任何真实账号操作、真实发布、作品删除、旧资料迁移。19 的一次性旧资料作业和 20 的四平台真实 no-publish 验收由后续票完成。本票基线中同批大鱼号/知乎仍待各自 16/17 接入；Bilibili 和未注册历史入口不扩入本票。
