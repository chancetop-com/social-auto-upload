# 25 — TikTok CLI 接入（仅 MLX 模式）

**What to build:** 用户可以在 MLX 模式下用 `sau tiktok check` 和 `sau tiktok upload-video` 操作 TikTok，复用 Chromium 版上传实现；本地模式调用任何 TikTok action 都直接失败退出 1。完成后 TikTok 成为受支持的平台，但只支持 MLX。

**Blocked by:** 17.

**Status:** resolved

- [x] `tiktok` 平台注册 `check`、`upload-video`、`login` 三个 action；参数与仓库命名对齐：`--file`、`--title`、`--tags`、`--schedule`、`--thumbnail`、`--account`（可选）、`--headless/--headed`、`--debug`；不引入 `--video-file` / `--publish-date` / `upload-note`。
- [x] 本地模式任何 action 退出 1；MLX 下 `login` 退出 1；未注册子命令仍退出 2。
- [x] Chromium 版上传实现改用 `patchright.async_api`，并接入 keyword-only `session`；Firefox 版实现不接入。
- [x] `TiktokVideo.__init__` 的 positional 参数不变，`account_file` 允许 `None`。
- [x] MLX 分支跳过 `change_language`，并在文档中记录“Profile 界面需为 English (US)”这一部署前提。
- [x] 新增 `is_logged_in`：访问 TikTok Studio 上传页，20s 预算，只开 1 个 page；上传入口返回 True，`/login` 或登录表单返回 False，网络错误抛异常。
- [x] 发布循环总超时 15 分钟；验证码/登录页/2FA 映射为 `LoginRequiredError`（10）。
- [x] `check` 返回 0 / 10 / 1 / 2；`upload-video` 返回 0 / 10 / 1，成功后 Stop 恰好一次。
- [x] MLX 全程不读写 `cookies/*.json`，不调用 spec §6.2 的禁止 API。
- [x] 新增 TikTok 参数解析、本地拒绝、登录检测与禁止 API 的测试。
