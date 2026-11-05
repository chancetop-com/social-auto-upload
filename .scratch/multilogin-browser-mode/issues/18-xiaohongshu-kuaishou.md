# 18 — 平台迁移：小红书 + 快手

**What to build:** 小红书与快手的 `check`、`upload-video`、`upload-note` 在 MLX 模式下可用，复用各自现有业务逻辑，登录检测与退出码符合统一契约；本地模式行为不变。沿用 17 已验证的 seam 模式。

**Blocked by:** 17.

**Status:** ready-for-agent

- [ ] 两个平台的上传入口都支持 keyword-only `session`，MLX 分支只执行 `upload_in(session)`。
- [ ] 两个平台各自新增 `is_logged_in(context)`：明确未登录返回 False，网络/5xx/超时/结构异常抛异常；预算 15–30s。
- [ ] 小红书 MLX 分支不调用 `grant_permissions`；若发布依赖定位，在验收记录中明确说明。
- [ ] 快手 MLX 分支静默忽略 `executable_path=LOCAL_CHROME_PATH` 与 `channel="chromium"`；Profile 决定浏览器。
- [ ] 两个平台的 `launch_kwargs` / `context_kwargs` / `init_script` 用 golden dict 锁定，本地模式与迁移前等价。
- [ ] `check` 返回 0 / 10 / 1 / 2；`upload-*` 返回 0 / 10 / 1，成功后 Stop 恰好一次。
- [ ] MLX 全程不读写 `cookies/*.json`，不调用 spec §6.2 的禁止 API。
- [ ] 新增表驱动测试覆盖两个平台的登录检测 True / False / 抛异常，以及禁止 API 负向断言。
