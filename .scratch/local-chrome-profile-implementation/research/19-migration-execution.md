# 19 一次性旧资料迁移执行与代码移除记录

日期：2026-11-17。执行代码基于集成 `c13bea6`，临时作业与合成测试先以 `3a6c7bf` 提交，Instagram 两次启动代理一致性及正常 Profile 回归以 `4c560d1` 提交。本文只保留执行证据，不是迁移入口。

## 执行边界与证据

- 实际资料根是 `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload`；源码来自 `/private/tmp/sau-local-profile-19`。临时入口显式加载原仓库 `conf.py` 并校验 `BASE_DIR`，没有改写用户配置。
- 四个实际目标：TikTok `lukechen`、Rednote `rednote`、Instagram `luke`、小红书 `180`。默认系统 Chrome：`channel=chrome`、`headless=False`、`no_viewport=True`；没有浏览器来源回退、Cookie 导入、账号身份绑定、备份、发布或作品删除。
- 打开浏览器前重新确认每个精确旧文件名只有一个大小写/Unicode 等价匹配且是普通文件，拒绝目录与符号链接；不读取旧文件内容。旧资料不参与新账号身份判断。
- 每个目标一次 `acquire_local_profile` 占用贯穿登录、关闭、同配置同目录重开、正向复验、第二次关闭及定向清理。严格关闭上限 10 秒，任何异常/超时/取消均否决删除；这里没有使用常驻会话的 best-effort 关闭结果充当成功证据。
- TikTok 使用既有 `login_in` 与本地 `is_logged_in`；Rednote 使用注入真实本地 session 的 `rednote_setup` 与 `probe_session`；Instagram 使用既有导航、登录后 inbox 锚点与 `instagram_identity`；小红书使用既有二维码及 `probe_session` 能力。复验只做探测，不再次引导登录、不比较真实账号身份。
- Instagram 在两次启动前只解析一次原有 `_proxy_options(None)`，本次结果是未配置代理（`proxy=None`）。用户名、用户 ID、Cookie、token 等未写入此记录。
- 原始不含凭据的逐阶段事件见 [19-live-events.jsonl](./19-live-events.jsonl)。所有时间为 UTC。

| 平台 / 别名 | 登录正向证据 | 第一次严格关闭 | 重开正向证据 | 第二次严格关闭 | 旧文件清理 |
| --- | --- | --- | --- | --- | --- |
| TikTok / lukechen | 10:52:35.595606 | 10:52:35.898994 | 10:52:40.493762 | 10:52:41.654179 | 10:52:41.655385 成功，退出 0 |
| Rednote / rednote | 10:53:49.478983 | 10:53:49.801192 | 10:53:54.383551 | 10:53:54.504629 | 10:53:54.506824 成功，退出 0 |
| Instagram / luke | 10:55:02.874727 | 10:55:03.281473 | 10:55:08.935147 | 10:55:09.054092 | 10:55:09.056451 成功，退出 0 |
| 小红书 / 180 | 10:57:00.059255 | 10:57:00.453631 | 10:57:08.130799 | 10:57:08.258340 | 10:57:08.260887 成功，退出 0 |

实际 Profile：

- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/browser_profiles/tiktok/lukechen/chrome`
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/browser_profiles/rednote/rednote/chrome`
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/browser_profiles/instagram/luke/chrome`
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/browser_profiles/xiaohongshu/180/chrome`

定向旧文件（没有其他清理目标）：

- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/cookies/tiktok_lukechen.json`
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/cookies/rednote_rednote.json`
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/cookies/instagram_luke.json`
- `/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/cookies/xiaohongshu_180.json`

Rednote 及之后的启动事件记录浏览器版本 `157.0.8103.79`；TikTok 首轮临时日志未记录版本，仅记录已解析的 Chrome channel，不能由后续版本反推其具体版本证据。

## 合成验证与永久回归

TDD 合成资料位于隔离临时根，未拿真实账号文件测试破坏行为。先红后绿：

1. 缺少临时迁移模块时首测导入失败；实现两次正向探测/关闭后，仅删除选定旧文件的流程后通过。
2. 仅旁文件残留和不安全路径用例失败；补齐精确安全定位与有限身份旁文件范围后通过。
3. 吞取消的关闭会突破时限、部分删除不能报告剩余路径；改为有界严格关闭及准确剩余项报告后通过。
4. Instagram 代理选项一致性用例因尚不接受 context 选项失败；两次启动复用同一解析结果后通过。

最终临时合成测试 **11/11 通过**，覆盖缺失/损坏/不同主体、仅身份旁文件、安全唯一匹配、两阶段证据、持续占用、两次关闭失败、取消与严格超时、部分清理失败及剩余目标重试收敛。红/绿日志保留于 `/private/tmp/sau-local-profile-notes/19-red-1.log`、`19-red-2.log`、`19-red-3.log`、`19-red-proxy.log`、`19-green.log`、`19-green-proxy.log`；临时测试代码在作业完成后删除。

永久保留四平台正式 CLI 回归，验证旧文件重新出现后无法被打开/重写、内容保留且每个 login/check 仅一次持久化启动。运行命令：

```sh
/Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_tiktok_profile_cli tests.test_rednote_profile_cli tests.test_instagram_profile_cli tests.test_xhs_profile_cli tests.test_local_browser_session tests.test_local_profile -q
```

首次结果 **97 项通过**，5.120 秒；日志 `/private/tmp/sau-local-profile-notes/19-normal-regression.log`。移除临时目录后再次运行同一命令，**97 项通过**，4.384 秒；日志 `19-after-removal-regression.log` 位于同一目录。这是隔离目录及浏览器边界替身的正常 Profile 回归，真实平台证据仅取上表。

## 代码移除

四个实际目标全部成功后，从工作树**实际删除** `migration19/migration.py`、`migration19/run_live.py`、`migration19/test_migration.py` 以及整个目录内的缓存；不是停用开关，没有添加常驻迁移入口或共享会话分支。代码历史可在 `3a6c7bf` 与 `4c560d1` 审查，最终提交包含上述文件删除。

执行后逐项检查：四个旧 Cookie 文件均不存在，四个原仓库 Profile 目录仍存在，小红书临时二维码已清理；剩余目标 **0**，具体阻塞 **无**。没有清空 Profile、操作其他别名/浏览器种类/托管资料/历史结果，也没有续跑旧发布任务。此成功仅证明 2026-11-17 当次可以恢复登录，不承诺未来不会过期。

最终交付只保留本记录、逐阶段事件和正常 CLI/Profile 回归。后续 20 可使用同一原仓库四个 Chrome Profile 执行已批准的 no-publish 验收。

最终静态核对：`git diff --check` 通过；Python 源码中未发现 `migration19`、临时严格关闭错误文本或临时旧资料清理错误文本。临时目录整体不存在，不留下停用实现。
