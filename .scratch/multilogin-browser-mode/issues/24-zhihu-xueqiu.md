# 24 — 平台迁移：知乎 + 雪球

**What to build:** 知乎（图文/视频）与雪球在 MLX 模式下可 `check` 与上传；时区不再由 CLI 写入，身份完全由 Profile 决定。本地模式保持原样。

**Blocked by:** 17.

**Status:** ready-for-agent

- [ ] 知乎图文、知乎视频、雪球的上传入口都支持 keyword-only `session`，MLX 分支只执行 `upload_in(session)`。
- [ ] 两个平台的 `is_logged_in` 放在各自 `session` 模块：明确未登录返回 False，网络/5xx/超时/结构异常抛异常；预算 15–30s。
- [ ] 本地 `timezone_id="Asia/Shanghai"`、`executable_path` / `channel="chrome"` 只在本地分支生效；MLX 分支静默忽略，并在文档提醒 Profile 时区设为 Asia/Shanghai。
- [ ] MLX 下不读取 `.identity.json`、不做用户 ID 比对；会话建立后输出“账号一致性未校验”的 INFO。
- [ ] 本地 `launch_kwargs` / `context_kwargs` / `init_script` 用 golden dict 锁定。
- [ ] `check` 返回 0 / 10 / 1 / 2；`upload-*` 返回 0 / 10 / 1，成功后 Stop 恰好一次。
- [ ] MLX 全程不读写 `cookies/*.json`，不调用 spec §6.2 的禁止 API。
- [ ] 新增登录检测、身份 reader 未被调用、禁止 API 的测试。
