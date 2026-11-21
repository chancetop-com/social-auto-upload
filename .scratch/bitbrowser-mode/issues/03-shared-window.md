# 冷启动、加入和最后退出时怎样识别同一个窗口

Label: wayfinder:grilling
Type: grilling
Status: open
Blocked by: 01

## Question

用户先在桌面打开窗口，Instagram 与 TikTok 两条 CLI 先后加入，再按不同顺序离开。比特浏览器提供的哪些信号足以找到当前实例和 CDP 端点、复用已有上下文，并让最后一条命令归还窗口？如果桌面端中途关闭并重开窗口、首个命令在启动时中断，或无法确认当前实例，应怎样保留现有共享规则和各命令的结果？

结合[共享会话接口](../../../utils/managed_browser.py)里的 `observe`、`resource_identity` 和 `asynchronous_stop`，对照[现行会话规则](../../managed-profile-sharing/spec.md)与[比特浏览器的本机 API 能力](01-local-api.md)。
