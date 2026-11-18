# 12: Multilogin X 支持正常加入与退出

Status: resolved

Blocked by: 08

批次：第一批 · [托管 Profile 默认共享规格](../spec.md)

## What to build

MLX 用户沿用现有参数运行不同平台的命令，复用同一套共享规则。用模拟 Launcher 经正式 CLI 验证本轮行为。

## Acceptance criteria

- [x] 在模拟 Launcher 上并发运行第一批中两个不同平台的 CLI。冷启动时合计一次 Start；已有可用连接时直接加入现有上下文。各命令新开自己的页面，启动者先退不会中断同行，最后离开时一次 Stop，包括桌面先打开的 Profile。
- [x] 按同一用户、provider 和 Profile ID 协调，核对 MLX 的 folder 与当前连接。改变 folder、凭据或账号别名不能借同一 Profile 取得第二份资格。无法确认资源或明确的启动设置冲突时，在开页前拒绝加入。
- [x] 对同一 Profile、同一平台同时申请，后来者立即以 `1` 退出并报告平台名；不同 Profile 各自独立。检查或发布命令在清理前始终持有本平台资格。
- [x] 用各进程的环境凭据访问 Launcher，验证记录与日志的脱敏及当前用户读取权限。回归 MLX 既有登录失效和 Launcher 429 的退出码。真实 MLX 桌面验收待有账号后补做。

## Comments

通过两个独立安装的 CLI、模拟 Launcher 和本机 Chromium 跑过 9 个场景。并发冷启动合计一次 Start，已打开的 Profile 直接加入。首个进程退出后，另一页还能编辑；最后离开合计一次 Stop。验证了同平台互斥、不同 Profile 独立、不同进程各用自己的凭据、folder 与浏览器实例的身份核对，以及设置冲突和无效端口的拒绝。结果检查包括私有记录、登录失效退出码 10 与 HTTP 429 退出码 11。既有 BrowserSession 和客户端回归通过 57 项及 11 个子用例。场景见 `tests/test_shared_multilogin_process.py`，验收提交为 `4850994`。真实 MLX 桌面验收按规格待有账号后补做。
