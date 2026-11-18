# 桌面和 CLI 先后启动时能观察到什么

Label: wayfinder:task
Type: task
Status: resolved
Blocked by: 01

## Question

用两家桌面应用各自的专用测试 Profile，记录冷启动、桌面已打开、桌面在预检后抢先打开、用户关闭后手动重开四种情形。Start 和状态响应、原 CDP 连接的存活情况及新实例标识能区分哪些情形？按产品与版本记录观察，以便确定怎样保护手动会话。由操作者关闭手动实例，避免用 Stop 试探归属。[验证步骤与官方依据](../research/01-provider-ownership.md)

桌面先打开或重开时，先保留一个带可辨认内容的原标签页。能否仅凭 provider 对指定本机 Profile 提供的当前连接，新开再关闭一个测试标签页，并观察到原标签页和 Profile 仍在？逐产品记录有无可用连接、需要的桌面配置和实际观察。借用场景与刻意制造 Start 竞争的场景分别记录。[进程中断后怎样识别和恢复遗留会话](04-abandoned-session.md)

让所有 CLI 进程退出，保留 CLI 启动的测试浏览器。分别观察「浏览器持续运行」和「用户中途关闭并手动重开同一 Profile」。新进程能取得哪些证据，既证明最初是 CLI 启动，又能区分这两种情形？若识别成功，关闭操作能否限定于已确认的那次运行，即使用户在核验后重开也能保留新开的浏览器？结果按 provider 和版本记录。

## Comments

2026-11-18，在用户授权的现有 AdsPower Profile 上，已验证单次启动标记可跨 CLI 崩溃回读，同一 Profile 从桌面重开时标记消失。对手动会话再发带标记的 Start，返回成功但标记不会生效。新进程经已核验的连接关闭了 CLI 启动的浏览器，provider 状态恢复为 `Inactive`。当时未在 Multilogin X 复测启动参数。[调查方法、版本与结果](../research/06-crash-ownership.md)

## Answer

此调查因范围变更关闭。用户已决定最后一条托管命令退出时关闭 Profile，启动者身份不影响该决定。关于两家 provider 怎样加入当前 Profile 和最后退出的验证已归入[哪些证据足以验收托管 Profile 默认共享](05-acceptance.md)。