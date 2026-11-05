# 17 — 上传器 seam + 抖音 upload（视频/图文）

**What to build:** 抖音的 `upload-video` 与 `upload-note` 在 MLX 模式下复用现有上传业务逻辑完成发布，全程不读不写本地 cookie，也不创建或覆盖浏览器 context；本地模式仍走原来的 launch / storage_state 路径。本票验证的是后续所有平台都会复制的 seam 模式。

**Blocked by:** 16.

**Status:** resolved

- [x] 上传入口新增 keyword-only `session: BrowserSession | None = None`；`session is None` 时完全走旧代码（Flask / 本地登录路径），构造函数与既有 positional 参数不变。
- [x] 拆出 `upload_in(session)` 业务主体；MLX 分支只执行它，不 launch、不 `new_context`、不 `set_init_script`、不读写 `storage_state`、不 close。
- [x] MLX 下 `account_file` 为 `None`；cookie 存在性校验、内容校验、cookie 读写、身份绑定全部只留在本地分支。
- [x] MLX 分支不触碰 spec §6.2 的禁止 API；`context.new_page()`、`context.pages`、`browser.contexts`（只读）可用。
- [x] 用 golden dict 锁定抖音的 `launch_kwargs` / `context_kwargs` / `init_script`，防止本地模式迁移时丢参数。
- [x] 上传前调用一次 `is_logged_in`；False 时抛 `LoginRequiredError`（10）；上传途中遇到登录页/验证码/2FA 同样映射为 10。
      - 上传途中检测基于 URL 标记（login/captcha/verify/2FA + 创作者中心根路径回跳）；页面内不改变 URL 的验证码浮层不在覆盖范围。
- [x] 上传成功时 Stop 恰好调用一次；上传失败或取消时 finally 仍 Stop；Stop 失败不把成功上传变成失败。
- [x] 现有抖音 declaration / positional 回归测试保持绿；新增测试证明 MLX 路径未写任何 `cookies/*.json`。

**下游模板：** `tests/test_douyin_upload_seam.py`、`uploader/douyin_uploader/main.py` 的 `upload_in` / `session` 分支、`sau_commands/douyin.py` 的 `target` 分支即 ticket 18–25 要复制的模式。
