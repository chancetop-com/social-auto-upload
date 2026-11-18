# 08: AdsPower 共享 Profile 的启动与退出

Status: ready-for-agent
Resolution: completed

Blocked by: 20

批次：第一批 · [托管 Profile 默认共享规格](../spec.md)

## What to build

同一用户从两个终端用 Instagram 和 TikTok 检查登录态。两条 CLI 默认加入同一个 AdsPower Profile，各自得到检查结果；最后离开的命令归还整个 Profile。

| 平台 | 本单负责的托管入口 |
| --- | --- |
| Instagram、TikTok | `check` |

## Acceptance criteria

- [x] 在 macOS 用模拟 AdsPower 从不同工作目录、不同 Python 虚拟环境并发运行两个正式 CLI。Profile 空闲时合计一次 Start，两条命令在现有上下文各开检查页；启动者先结束时 Stop 为零，同行仍能使用自己的页，最后离开时合计一次 Stop。
- [x] 桌面先打开 Profile 并留有带标记的标签页时，两条检查直接加入。各自的登录探针只关闭自己的临时页。第一条退出后原标签和同行页面仍可用，最后一条退出时整个 Profile 关闭。
- [x] 两个同平台 `check` 同时到达时仅一个成功取得资格，另一条在开页前报告具体平台并以 `1` 退出。不同 Profile 上的同平台检查可以同时运行。
- [x] 同一用户、provider 和 Profile ID 在不同安装位置共用同一组进程锁，兼容 Python 3.10–3.12。改变等价的服务地址拼法、凭据或账号别名不能取得第二组锁。确认为不同资源或无法核对请求目标时，拒绝加入原会话。
- [x] 新命令明确要求的启动设置与当前会话冲突，或当前连接无法确认时，在开页前退出，已有命令继续。加入失败者不发 Stop。
- [x] 在 Mac 检查会话目录和连接记录的实际所有者与权限。每个进程使用自己的环境凭据，只有当前用户可读连接记录；记录不含 token 或 API key，日志不含凭据或 CDP 地址。无法可靠加锁或安全读取记录时，在接管浏览器前退出。
- [x] 沿用现有 CLI 参数与两种检查的结果语义，共享无需 `--share-profile`。用本地模式回归确认已有检查入口、退出码和本地 Profile 生命周期。

## Comments

macOS 上以两个独立安装的 CLI 验证了同时冷启动、桌面已打开、同平台抢占、不同 Profile 和设置冲突。两个测试进程分别使用 Python 3.10.16 和 3.12.9；冷启动合计 1 次 Start，桌面先打开时为 0。两种场景均在先退出者离开后实际编辑了同行原页，最后一次 Stop 后确认关闭。模拟 AdsPower 的请求、Chromium 的页面和退出码由进程外观测。权限测试覆盖 POSIX 所有者、模式、链接与 macOS 扩展 ACL，日志与记录均检查了敏感字段。Windows 私有目录与锁另有平台测试，原生运行留待 Windows 环境。

两进程用例见 `tests/test_shared_adspower_process.py`。共享入口见 `d1ed1bf`，权限补充见 `8b8e314` 与 `27b9329`。
