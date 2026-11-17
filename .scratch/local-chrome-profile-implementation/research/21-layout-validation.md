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

待 root 集成代码检查点后执行。原 19/20 的旧路径与平台 no-publish 记录保留为历史；本记录只追加本次布局变化的移动及四个普通 check 证据。没有因目录变化增加真实素材上传。

### 受控矩阵结果

| 来源 | Chrome 157.0.8103.79 | Chromium 156.0.8078.4 |
| --- | --- | --- |
| 标准 channel 有头 | 通过 | 通过 |
| 标准 channel 无头 | 通过 | 通过 |
| 自定义 executable 有头 | 通过 | 通过 |
| 自定义 executable 无头 | 通过 | 通过 |

每项在隔离本机 HTTP 页面写入合成 Cookie/localStorage，正常关闭并重开验证持久化；临时匿名 context 不继承也不反向污染主 Profile。断言新的 kind/platform/account 路径、账号数据叶子无项目 `.sau-owner.json`、最终占用释放。完整日志位于实施临时记录 `/private/tmp/sau-profile21-browser-serial.log`；永久保留本摘要与可复跑的 `browser-smoke.py`。这不是平台账号验证。
