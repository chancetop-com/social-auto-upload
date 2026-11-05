# 21 — 平台迁移：虎扑 + 大鱼号

**What to build:** 虎扑与大鱼号在 MLX 模式下可 `check` 与上传。虎扑不再设置自定义 UA / stealth，大鱼号不再写时区；两者都由 Profile 决定浏览器身份。

**Blocked by:** 17.

**Status:** resolved

- [x] 两个平台的上传入口支持 keyword-only `session`，MLX 分支只执行 `upload_in(session)`。
- [x] 虎扑的本地 `context_setup`（自定义 UA + 1920×1080 + stealth 脚本）只在本地分支执行；MLX 分支静默忽略。
- [x] 虎扑的 `is_logged_in` 补齐正向信号；MLX 下若布局变化只允许改选择器，不通过修改 Profile 规避。
- [x] 大鱼号的本地 `timezone_id="Asia/Shanghai"` 只在本地分支执行；MLX 分支静默忽略，并记录“Profile 时区建议设为 Asia/Shanghai”。
- [x] 大鱼号的 `is_logged_in` 放在其 `session` 模块，且 MLX 下不读取 `.identity.json`、不做用户 ID 比对。
- [x] 两个平台的 `launch_kwargs` / `context_kwargs` / `init_script` / `context_setup` 用 golden dict 锁定。
- [x] `check` 返回 0 / 10 / 1 / 2；`upload-*` 返回 0 / 10 / 1，成功后 Stop 恰好一次。
- [x] 新增登录检测、context_setup 只在本地执行、禁止 API 的测试。
