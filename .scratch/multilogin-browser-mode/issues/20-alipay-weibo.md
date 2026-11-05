# 20 — 平台迁移：支付宝 + 微博

**What to build:** 支付宝与微博在 MLX 模式下可 `check` 与上传；微博不再依赖 2000px 高视口，发布按钮改为滚动到可视区。本地模式保持原样。

**Blocked by:** 17.

**Status:** ready-for-agent

- [ ] 两个平台的上传入口支持 keyword-only `session`，MLX 分支只执行 `upload_in(session)`。
- [ ] 支付宝基于现有页面行为新写 `is_logged_in`；微博补齐/加强正向登录信号；两者都能区分未登录与网络/结构异常。
- [ ] 支付宝 MLX 分支不调用 `grant_permissions`，也不注入 stealth init script（保持现有刻意选择）；若发布依赖定位，在验收记录中确认。
- [ ] 微博 MLX 分支不假设 2000px 视口；发布按钮使用 `scroll_into_view_if_needed()`，不依赖本地 viewport 参数。
- [ ] 两个平台的本地 `launch_kwargs` / `context_kwargs` / `init_script` 用 golden dict 锁定，迁移前后等价。
- [ ] `check` 返回 0 / 10 / 1 / 2；`upload-*` 返回 0 / 10 / 1，成功后 Stop 恰好一次。
- [ ] MLX 全程不读写 `cookies/*.json`，不调用 spec §6.2 的禁止 API。
- [ ] 新增登录检测与禁止 API 的表驱动测试。
