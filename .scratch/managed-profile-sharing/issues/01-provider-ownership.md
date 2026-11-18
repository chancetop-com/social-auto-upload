# 两家 provider 怎样证明 Profile 由 CLI 启动

Label: wayfinder:research
Type: research
Status: resolved
Assignee: LukeChen

## Question

AdsPower Local API V2 与 Multilogin X Launcher 分别提供哪些证据，可以区分 CLI 新启动、已由桌面用户打开、状态未知三种情形？重点核实在“查询空闲”和“请求启动”之间有人手动打开时，两家的 Start、状态、CDP 地址和 Stop 响应能证明什么。记录官方依据、已有仓库证据与需要真机验证的情形，供共享会话决定何时允许操作和停止 Profile。

## Answer

AdsPower 的活动状态和 WebSocket、Multilogin X 的锁、启动用户、机器和自动化端口均可用于诊断。两家的公开契约都未将成功 Start 绑定到本次请求独有的浏览器实例。CLI 的本机记录可证明收到了响应。桌面关闭并重开后，这份记录仍会存在。两家的 Stop 都按 Profile ID 生效，不能检查要关闭的是哪一次启动。

上述观察保留为接口依据。当前关闭条件见[谁负责加入、离开和停止共享托管会话](02-process-lifecycle.md)。后续在 AdsPower 真机验证了冷启动、对活动会话重复 Start、桌面重开及崩溃恢复。[当时的实机调查记录](../research/06-crash-ownership.md)。[研究记录](../research/01-provider-ownership.md) · [研究提交](https://github.com/chancetop-com/social-auto-upload/commit/842157091cac1321c12b126e6928cd388696ae2a)
