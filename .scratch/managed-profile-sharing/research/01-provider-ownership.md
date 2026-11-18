# 两家 provider 能否证明是本次 CLI 启动了浏览器？

2026-11-18 查阅官方接口和仓库规格。两家的公开接口都没有承诺「同时检查空闲并只创建新实例」，也没有公布只对某次启动有效的 Stop 参数。因此，在同机桌面和 CLI 争用时，仅凭「先查到空闲，随后 Start 成功」不能判定本次 CLI 启动了浏览器。本次未操作真实 Profile，重复 Start 的实际行为仍待验证。[AdsPower Start](https://localapi-doc-en.adspower.com/docs/Open-Browser-V2) · [AdsPower Stop](https://localapi-doc-en.adspower.com/docs/Close-Browser-V2) · [Multilogin Start](https://documenter.getpostman.com/view/28533318/2s946h9Cv9#531a1370-6ac3-49d5-8914-d9c07dc98636) · [Multilogin Stop](https://multilogin.com/help/stopping-a-profile-with-postman)

| 观察时点 | AdsPower Local API V2 | Multilogin X Launcher |
| --- | --- | --- |
| 查询占用 | 本机 `active` 返回 `Active` 或 `Inactive`。打开时也能查到 WebSocket 和调试端口。另一个跨设备接口可以返回打开者账号，但开启 Multi Device 后，可返回与未打开相同的空列表。[本机状态](https://localapi-doc-en.adspower.com/docs/Check-Browser-Status-V2) · [跨设备状态](https://localapi-doc-en.adspower.com/docs/Check-Browser-Status-crossdevices) | 单 Profile 状态限于当前 Agent 会话，重启后可能无数据。状态可包含使用者、上次启动用户、机器和时间。自动化启动后，状态的 `message` 可含端口。同机同用户可以同时符合这些条件。[状态接口](https://documenter.getpostman.com/view/28533318/2s946h9Cv9#0ad3f26d-ae66-459c-8db6-7c5fa5a90198) · [官方 v5.3 公告](https://t.me/s/multilogin?before=783) |
| 桌面在预检和 Start 之间打开 | Start 成功示例给出 `code=0`、`data.ws.puppeteer` 和 `debug_port`。文档未说明已有实例会报错还是返回原地址。地址可用于连接，缺少“本次新建”标记。[Start](https://localapi-doc-en.adspower.com/docs/Open-Browser-V2) | Start 成功可返回 `data.port`。官方说明活动锁用于提示其他设备正在使用，也可能在异常退出后残留。仓库引用社区观察到的 `can't lock profile`。同机桌面抢先时是否必然报此错，没有官方保证。[Start](https://multilogin.com/help/starting-a-profile-with-postman) · [活动锁](https://multilogin.com/help/en_US/how-to-use-active-session-lock) · [仓库原始调研 §3.5](../../multilogin-browser-mode/research/01-mlx-launcher-api.md) |
| 准备停止 | Stop 接受 Profile ID 或编号，成功用 `code=0` 表示。请求没有预期 WebSocket 或实例编号。[Stop](https://localapi-doc-en.adspower.com/docs/Close-Browser-V2) | Stop 按 Profile ID 发出。200 表示请求成功。官方亦给出 500 `profile already stopped` 的示例。两种响应都不能回溯谁启动了浏览器。[Stop](https://multilogin.com/help/stopping-a-profile-with-postman) · [官方错误示例](https://multilogin.com/help/en_US/getting-started-with-multilogin-x-automation/run-in-docker) |

## 研究时对共享会话的建议

下列建议记录了最初仅允许使用 CLI 自有实例时的判断。当前按使用中的 CLI 数量关闭 Profile 的规则见[谁负责加入、离开和停止共享托管会话](../issues/02-process-lifecycle.md)。

- **已占用。** 看到活动 Profile 而没有可核验的 CLI 会话，或 Start 明确报占用，报告占用并保留现有浏览器。锁可能来自异常退出，诊断只报告观察到的状态，不指认具体用户。[AdsPower 状态](https://localapi-doc-en.adspower.com/docs/Check-Browser-Status-V2) · [Multilogin 活动锁](https://multilogin.com/help/en_US/how-to-use-active-session-lock)
- **CLI 新启动。** 需要能把本次请求与新浏览器实例关联的独立证据。CLI 本地记录可以证明某次收到了成功响应。同机进程锁可以协调遵守协议的 CLI。它们各自都无法证明桌面没有抢先启动，也无法证明现在运行的仍是当时的实例。已建立归属的共享会话还需核对实例连续性，端口或持有者计数本身不足以授权最后一个 CLI 调 Stop。[AdsPower Start](https://localapi-doc-en.adspower.com/docs/Open-Browser-V2) · [Multilogin Start](https://documenter.getpostman.com/view/28533318/2s946h9Cv9#531a1370-6ac3-49d5-8914-d9c07dc98636)
- **归属未知。** 预检后桌面抢先、超时或响应不完整、Agent 无记录、原浏览器关闭后桌面重开，都应保留现场并报告“无法确认归属”。在此状态下不连接、不操作页面、不调用 Stop 或解锁。即使在 Stop 前刚核对过地址，桌面也可能在核对和按 ID 停止之间替换实例。[AdsPower Stop](https://localapi-doc-en.adspower.com/docs/Close-Browser-V2) · [Multilogin Stop](https://multilogin.com/help/stopping-a-profile-with-postman)

旧 AdsPower 规格将成功 Start 计为自有，部分不完整响应也会触发补偿 Stop。旧 Multilogin 规格要求调度方保证同一 Profile 串行。两者都不能作为桌面竞态已验证的依据。[AdsPower 规格 §6.2](../../adspower-browser-mode/spec.md) · [Multilogin 规格 §§5.5、11](../../multilogin-browser-mode/spec.md)

## 待真机核对

用同机专用测试 Profile 对照三组。第一组由 CLI 单独冷启动。第二组由桌面先打开再发 Start。第三组在 CLI 读到空闲后暂停，由桌面打开再放行 Start。记录产品与内核版本、设置、先后顺序、响应码、状态，以及调试地址是否相同。再由操作者关闭已知的 CLI 实例并用桌面重开，核对旧记录能否识别替换。桌面或归属不明的实例由操作者收尾，不用 Stop 试探。以上是验证设计。一组观察只支持所测版本和配置。[AdsPower 既有冒烟票](../../adspower-browser-mode/issues/09-real-smoke.md) · [Multilogin 既有冒烟票](../../multilogin-browser-mode/issues/08-mlx-smoke-test.md)
