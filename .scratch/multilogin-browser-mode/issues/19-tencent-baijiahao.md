# 19 — 平台迁移：腾讯 + 百家号

**What to build:** 腾讯与百家号的 `check`、`upload-video`、`upload-note` 在 MLX 模式下可用，登录检测能给出可靠的正向信号；本地模式的 launch 参数与现在等价。

**Blocked by:** 17.

**Status:** resolved

> 注：TencentNote 已获得 `session` seam，但腾讯目前没有 `upload-note` CLI action；百家号没有图文（note）发布路径。本节不新增 CLI action。

- [x] 两个平台的上传入口支持 keyword-only `session`，MLX 分支只执行 `upload_in(session)`。
- [x] 腾讯的 `is_logged_in` 在现有页面判断基础上补齐正向信号；百家号新写 `is_logged_in`；两者都能区分“未登录”与“网络/结构异常”。
- [x] 腾讯 MLX 分支静默忽略 `AutomationControlled` 相关 args 与 `LOCAL_CHROME_PATH`；`init_script` 不在 MLX 下使用。
- [x] 百家号 MLX 分支不调用 `grant_permissions`；若发布依赖定位，在验收记录中确认。
- [x] 两个平台的 `launch_kwargs` / `context_kwargs` / `init_script` 用 golden dict 锁定。
- [x] `check` 返回 0 / 10 / 1 / 2；`upload-*` 返回 0 / 10 / 1，成功后 Stop 恰好一次。
- [x] MLX 全程不读写 `cookies/*.json`，不调用 spec §6.2 的禁止 API。
- [x] 新增登录检测与禁止 API 的表驱动测试。
