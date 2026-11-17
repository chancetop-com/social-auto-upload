# 24: 明确三个平台 no-publish 的实际停止点

**What to build:** 用户指出 `prepared (not published)` 易产生误解；Rednote、TikTok、小红书的 no-publish 成功输出明确区分素材上传与最终发布。

**Blocked by:** [19：一次性迁移](./19-one-time-legacy-migration.md)（已完成）。基于 20 已验证基线 `a61628c`，与 21、22、23 并行。

**Status:** resolved

**依据：** 用户 2026-11-17 追加文案要求。采用 `素材已上传，发布前检查已通过；已停止，未点击发布按钮。`

- [x] 三个平台的视频、图文 no-publish 成功输出统一明确说明素材已上传、发布前检查通过、未点击发布按钮，移除该用户可见摘要中的含糊 `prepared (not published)`。
- [x] 覆盖适用的本地及托管 no-publish 入口，正常发布输出、provider 启动/ignored-option 日志、退出码、机器结果字段及真实停止边界保持不变。
- [x] 仅在实际完成媒体、编辑和发布就绪检查后才打印成功摘要；失败/登录失效不误报就绪。保持 no-publish 显式参数和不提交契约。
- [x] 补公开 CLI 的视频/图文与必要托管回归，证明文案及零提交；文案调整无需重新上传真实素材。
- [x] 同步引用旧文案的当前文档/帮助和工单记录；保留过去实测日志原文，不改写历史证据。

## Comments

- 2026-11-17：领取 24。按已确认的公开 CLI → 真实配置/Profile/session 编排 seam 使用浏览器/provider 边界替身；先写新摘要期望再改输出。仅变更成功摘要，不改提交守卫、退出码或 provider 日志；不额外操作真实账号。

- 2026-11-17：逐平台 red → green。Rednote 两个公开 CLI 媒体流程先因缺少新摘要失败，最小输出修复后 2/2 通过；TikTok 两个本地流程与原有托管图文流程先 3/3 失败（托管仍显示 submitted），修复后 3/3 通过；小红书本地视频/图文和托管视频先出现 3 个失败子例，修复后两个测试方法覆盖本地及托管两个媒体均通过。失败均是新摘要断言失败，上传、编辑及零点击证据保留。
- 2026-11-17：扩展公开 CLI 回归为三个平台 × 视频/图文 × 本地/托管的 12 个成功入口；托管覆盖 MLX 与 AdsPower，保留既有启动、ignored-option、关闭所有权与 TikTok 探测 URL 断言。每项检查发布按钮点击为零；本地用真实临时 Profile/会话编排，页面与 provider 为外部边界替身。
- 2026-11-17：新增三个平台 × 视频/图文 × 发布就绪失败/本地登录失效/托管登录失效的 18 个失败子例；退出分别为 1/10/10、stdout 无成功摘要、零提交且没有 `publish_attempted=true`。正常发布回归仍保持 submitted 文案，既有提交后 9/10 及 machine marker 断言通过。
- 2026-11-17：最终离线命令从本票 worktree 运行，使用原仓库已有虚拟环境：

  ```sh
  /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_rednote_profile_cli tests.test_tiktok_profile_cli tests.test_xhs_profile_cli tests.test_rednote tests.test_tiktok_no_publish tests.test_tiktok_note_cli tests.test_tiktok_exit_codes tests.test_xhs_submit tests.test_mlx_tiktok tests.test_browser_session tests.test_adspower_browser_session -q
  ```

  实际结果：**305 tests / OK，4.802s**。首次组合命令误写两个模块名，且 18 个 `test_rednote_options` 浏览器测试被沙箱拒绝启动；这些不是通过证据。更正模块名后得到上述离线结果，并以允许浏览器启动的执行环境单独运行下列既有受控 DOM 测试：

  ```sh
  /Users/chancetio/Desktop/Web/social-media-auto-upload/social-auto-upload/.venv/bin/python -m unittest tests.test_rednote_options -q
  ```

  实际结果：**18 tests / OK，36.662s**。这些是真实浏览器合成页面测试，没有真实平台账号。`git diff --check` 通过。
- 2026-11-17：当前引用旧摘要的 `docs/rednote.md`、Rednote 独立技能参考已更新；公共 CLI 文档说明三个平台及两种模式，原规格明确 24 是托管摘要保持条款的特定追加例外，实施索引登记 24。既有 19/20 原始日志、研究证据没有改写。未额外真实上传，未修改用户配置或真实 Profile。

## Answer

已完成 24。三个平台的视频/图文 no-publish 在真实上传流程成功返回后保留媒体标识，再统一打印 `素材已上传，发布前检查已通过；已停止，未点击发布按钮。`；本地和托管一致。生产改动仅涉及六个最终摘要分支，不改 no-publish 守卫、provider 日志、正常发布输出、退出码或机器结果字段。

相关验证共 305 项离线与 18 项真实浏览器受控 DOM 测试通过；没有真实账号操作或额外素材上传。无本票阻塞；Profile 布局、历史代码清理及 Instagram 兼容由 21–23 各自交付，父规格整体仍待汇总。
