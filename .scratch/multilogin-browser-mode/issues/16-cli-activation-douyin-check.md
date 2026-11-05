# 16 — CLI 激活 + 退出码契约 + douyin check 垂直打通

**What to build:** 用户第一次能仅凭 `MLX_API_TOKEN` 把 CLI 切到 Multilogin 模式，并用 `sau douyin check --folder-id ... --profile-id ...` 得到调度 App 可依赖的退出码。这是本 feature 的第一个用户可演示切片，同时把 CLI 契约一次性铺到所有平台命令上。

**Blocked by:** 15.

**Status:** ready-for-agent

- [ ] 激活语义：token 非空且非纯空白才进入 MLX 模式；空串/未设置仍是本地模式，`--folder-id` / `--profile-id` 被静默忽略。
- [ ] 所有可在 MLX 运行的 action（`check`、`upload-*`）注册 `--folder-id` / `--profile-id`；`login` 不注册。
- [ ] `--account` 改为可选：本地模式缺失仍在 `run()` 层报用法错误并退出 2；MLX 模式缺省以 `profile_id` 作为日志标签。
- [ ] `sau_cli.main` 映射 `UsageError → 2`、`LoginRequiredError → 10`；argparse 自身错误保持 2，且入口不捕获 `SystemExit`。
- [ ] MLX 模式下 `login` 运行时拒绝并退出 1；`bilibili` 在 MLX 下直接拒绝并退出 1；TikTok 尚未注册时仍退出 2。
- [ ] 新增 douyin 的 `is_logged_in(context)`：明确登录页/表单/未登录锚点返回 False；网络错误、5xx、超时、结构异常抛异常；只用 `context.new_page()` / `goto` / `close`，总预算 15–30s。
- [ ] `sau douyin check` 在 MLX 下按 spec §5.4 走 start → 检测 → stop：已登录 0、未登录 10、Launcher/CDP/网络故障 1、缺参 2；Stop 在成功与失败路径都只调用一次。
- [ ] 本地模式所有旧命令的解析与行为不变，现有回归测试保持绿。
- [ ] token 不出现在 stdout、stderr、异常文本或日志中。
