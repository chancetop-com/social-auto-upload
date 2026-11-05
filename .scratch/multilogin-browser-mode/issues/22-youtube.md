# 22 — 平台迁移：YouTube

**What to build:** YouTube 在 MLX 模式下可 `check` 与上传视频；`YT_PROXY` 与本地 launch 假设被静默丢弃，出口 IP 完全由 Profile 决定。本地模式保持原样。

**Blocked by:** 17.

**Status:** ready-for-agent

- [ ] YouTube 上传入口支持 keyword-only `session`，MLX 分支只执行 `upload_in(session)`。
- [ ] 新增 `is_logged_in(context)`：明确未登录返回 False，网络/5xx/超时/结构异常抛异常；预算 15–30s。
- [ ] MLX 分支静默忽略 `channel="chrome"`、`proxy={"server": YT_PROXY}` 与 init script。
- [ ] 本地 `launch_kwargs` / `context_kwargs` / `init_script` 用 golden dict 锁定，迁移前后等价。
- [ ] `check` 返回 0 / 10 / 1 / 2；`upload-video` 返回 0 / 10 / 1，成功后 Stop 恰好一次。
- [ ] MLX 全程不读写 `cookies/*.json`，不调用 spec §6.2 的禁止 API。
- [ ] 新增登录检测与禁止 API 的表驱动测试。
