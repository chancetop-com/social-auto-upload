# 21：浏览器种类首层布局验证

## 当前运行契约

`browser_profiles/<chrome|chromium>/<platform>/<raw_account>` 的账号叶子是浏览器 user data directory。项目归属、进程锁、未完成重建标记在账号资料之外；`.guards/<kind>/<platform>/<raw_account>/` 保存账号 guard，种类/平台元数据也避开任意别名所在层。Chrome/Chromium 独立，raw alias 不裁剪或编码，只有归属中的原值决定等价路径是否冲突。

reset 持有与 session 相同的非等待跨进程锁，删除账号数据及其数据归属记录；保留 guard 的原始别名归属与锁。删除不完整时外置 marker 阻止后续正常取得，重跑显式 reset 才能解除；残存冲突元数据仍拒绝。外部 singleton 不清除、不接管。

## 代码与离线证据

测试使用原仓库 `.venv/bin/python`，cwd/PYTHONPATH 指向 `/private/tmp/sau-local-profile-21`；`conf.BASE_DIR` 与 Profile 模块文件路径已断言属于该工作树。所有测试 Profile 均为临时合成资料。

- TDD：公开 `local_browser_session` 的新路径断言先在旧顺序失败，布局实现后通过。
- TDD：数据目录消失但外置归属冲突时 login 不得覆盖记录；测试先失败，修复后通过。
- TDD：小红书公开 login 的 QR 回调断言新 Profile 内的图片路径，先发现旧路径再修复；异常回调后仍删除临时 QR、关闭 context 并释放占用。
- `python -m unittest tests.test_local_profile tests.test_local_browser_session`：30 通过。覆盖真实竞争进程、不同种类并行、synthetic holder 崩溃释放、路径/别名等价与重建后的碰撞、重建期间竞争与部分失败后的跨进程拒绝、归属缺失/损坏/冲突、guard/数据 symlink、singleton、无效及内部文件名别名。
- `python -m unittest tests.test_tiktok_local_mode tests.test_local_browser_session`：12 通过，补足非 `*profile*` 命名文件中的路径断言。
- 合入 24 后 `python -m unittest tests.test_tiktok_profile_cli tests.test_rednote_profile_cli tests.test_xhs_profile_cli`：58 通过，新路径与新 no-publish 摘要同时保留。
- 合入 22 与 24 后的共享/Profile/session/managed/三平台 CLI 组合：121 通过（4.256s）；latest integration `6e6e416` 已合入本工作树。
- `git check-ignore browser_profiles/chrome/tiktok/synthetic` 命中忽略规则；`git diff --check` 通过。

## 浏览器验证与限制

首次 `unittest discover -s tests -p '*profile*.py'` 在 sandbox 内运行：352 项，337 通过；14 项浏览器启动 error，1 项 Facebook 测试捕获启动失败后产生断言失败。相同集合在 sandbox 外串行执行，352 项全部通过（610.800s）。

首次隔离 `browser-smoke.py` 中 Chrome headed 已保存并恢复合成 Cookie/localStorage，匿名 context 隔离通过；第二次正常关闭超过已有 10 秒界限，下一次取得因 singleton 残留被正确拒绝。该次 smoke 不算整组通过；没有删除 singleton、重置实际资料或终止外部浏览器。工具进程结束后未发现该临时路径的浏览器进程。其他 DOM 批次停止后串行重跑完整矩阵：8/8 通过，没有关闭超时；每一行结束后重新取得 Profile，确认项目锁和 native singleton 均释放。未更改运行时关闭策略或放松 guard。

## 实际资料搬迁

代码检查点 `6f831fd` 已集成为原仓库 `3455f1f`，root 明确放行后执行一次性搬迁。先列出原目录及四个精确目标，确认专用目录、归属、无 singleton 与无实际账号浏览器进程，再同时取得四个旧 guard、四个新 guard 和短时 layout 锁。使用 macOS `renamex_np(RENAME_EXCL)` 原子移动，已有目标即拒绝；合成测试已验证即使目标为空目录也不覆盖。没有复制/合并资料、跨种类复制、reset、重新登录、直接读取 Cookie/History 内容、清 singleton 或杀外部进程。

[原始搬迁事件](./21-relocation-events.jsonl)保留旧/新路径和移动前 inode；四个目录移动后及真实 check 后 inode 均未改变。只有核验归属的旧 `.sau-owner.json`、旧 guard 文件和空父目录按计划退出；未知 `browser_profiles/instagram/.DS_Store` 及其父目录/平台记录保留，未读取其内容。原 `instagram/luke/chrome` 等四个精确旧目标全部不存在；常规代码只使用新布局，没有旧路径回退。

初次事后验证把“所有旧平台父目录不存在”写成了过严断言，在发现 `.DS_Store` 时停止；此前 TikTok、Rednote、Instagram 的 guard 已成功重新取得并释放。修正为精确目标不存在且保留未知文件后，完成小红书 guard 验证；没有删除未知文件来满足断言。Instagram 随后交还票 23，21 不再访问该 Profile。

原 `conf.py` 的 device/inode/size/mtime_ns 前后相同；核对未读取其内容，历史发布结果不在搬迁操作范围内。临时 `/private/tmp/sau-local-profile-notes/21-relocate.py` 与临时配置 stat 记录已实际删除；临时实现及专用合成测试没有进入仓库。原 19/20 的旧路径和八个真实 no-publish 结果保留为历史，本次没有新增素材上传。

实际检查从原仓库运行 `.venv/bin/python sau_cli.py <platform> check --account <alias> --headed`，不传浏览器选择，正常解析为 `channel=chrome`、Chrome `157.0.8103.79`、`headless=False`；四次输出均为 `valid` 且进程退出 `0`：

| 平台 | 别名 | 新路径（相对原仓库） | 启动日志时间（Asia/Shanghai） | 结果 |
| --- | --- | --- | --- | --- |
| TikTok | lukechen | `browser_profiles/chrome/tiktok/lukechen` | 2026-11-17 19:56:21 | valid / 0 |
| Rednote | rednote | `browser_profiles/chrome/rednote/rednote` | 2026-11-17 19:56:39 | valid / 0 |
| Instagram | luke | `browser_profiles/chrome/instagram/luke` | 2026-11-17 19:57:13 | valid / 0 |
| 小红书 | 180 | `browser_profiles/chrome/xiaohongshu/180` | 2026-11-17 19:57:40 | valid / 0 |

每份资料在 check 后都成功重新取得项目占用、通过原有 native singleton 检查并释放。没有关闭超时。此证据只证明已搬迁资料仍可用于普通登录检查，不扩大为真实发布或其他平台的账号验收。

### 受控矩阵结果

| 来源 | Chrome 157.0.8103.79 | Chromium 156.0.8078.4 |
| --- | --- | --- |
| 标准 channel 有头 | 通过 | 通过 |
| 标准 channel 无头 | 通过 | 通过 |
| 自定义 executable 有头 | 通过 | 通过 |
| 自定义 executable 无头 | 通过 | 通过 |

每项在隔离本机 HTTP 页面写入合成 Cookie/localStorage，正常关闭并重开验证持久化；临时匿名 context 不继承也不反向污染主 Profile。断言新的 kind/platform/account 路径、账号数据叶子无项目 `.sau-owner.json`、最终占用释放。完整日志位于实施临时记录 `/private/tmp/sau-profile21-browser-serial.log`；永久保留本摘要与可复跑的 `browser-smoke.py`。这不是平台账号验证。
