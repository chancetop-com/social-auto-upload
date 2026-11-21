# 比特浏览器本机 API 与既有窗口

截至 2026-11-21，桌面客户端的公开接口支持按窗口 ID 打开、查询调试端口和关闭窗口。要连接已运行的窗口，可以先按 ID 查调试端口，避开再次启动的副作用。以下依据官方接口文档、响应示例和版本日志，未连接真实客户端。[窗口接口](https://doc2.bitbrowser.cn/jiekou/liu-lan-qi-jie-kou.html) · [调试端口响应示例](https://doc.bitbrowser.net/api-docs/browser-profiles)

## 访问本机服务

- 安装并登录桌面客户端，在系统设置的浏览器设置中查看 Local API。默认地址为 `http://127.0.0.1:54345`，端口可改，以客户端显示值为准。官方说明由主账号启用服务，子账号需获授权。[本地服务指南](https://doc2.bitbrowser.cn/jiekou/ben-di-fu-wu-zhi-nan.html) · [地址与设置](https://www.bitbrowser.net/news/how-to-connect-bitbrowser-to-mcp) · [权限说明](https://www.bitbrowser.net/local-api)
- 6.0.4 引入可选 Token 控制。启用后以 `x-api-key` 请求头提交客户端生成的 Token，重置后旧值失效。7.1.5 起的 MCP 服务另有强制启用鉴权的要求。本文使用普通本机 HTTP 接口。[6.0.4 变更](https://www.bitbrowser.cn/blog/btllq_6_0_4_sjrz) · [请求头](https://www.bitbrowser.net/news/how-to-connect-bitbrowser-to-mcp) · [密钥重置](https://www.bitbrowser.net/local-api)
- 接口使用 POST，参数放在 JSON 请求体中。无参数的 `POST /health` 检查 Local Server 连通性。业务调用要读 JSON 中的 `success`，成功时按接口取 `data`，业务失败从 `msg` 取说明。健康检查文档没有给出可用于验证具体窗口的返回字段。[本地服务指南](https://doc2.bitbrowser.cn/jiekou/ben-di-fu-wu-zhi-nan.html) · [健康检查](https://doc.bitbrowser.cn/api-jie-kou-wen-dang/liu-lan-qi-jie-kou)

## 从窗口标识到 CDP 连接

| 需要回答的问题 | 官方行为及证据 |
| --- | --- |
| 选定哪个窗口？ | 以字符串 `id` 绑定现有配置。可在客户端点“复制 ID”，或用 `/browser/list` 分页查找，再以 `/browser/detail` 核对。列表从第 0 页开始，每页最多 100 条。整数 `seq` 是可精确查询的展示序号，单窗打开和关闭使用 `id`。官方未承诺复制或重建配置会沿用原 ID。[窗口接口](https://doc2.bitbrowser.cn/jiekou/liu-lan-qi-jie-kou.html) · [字段示例](https://doc.bitbrowser.cn/api-jie-kou-wen-dang/liu-lan-qi-jie-kou) |
| 它已经运行吗？ | 7.1.0 新增 `/browser/opened/ids`，7.1.2 新增列表筛选 `opened`。官方提醒列表状态可能因网络而滞后。要核实本机进程，可向 `/browser/pids/alive` 提交 `ids` 数组，或无参数查询 `/browser/pids/all`，后者过滤已退出进程。[7.1.0 日志](https://www.bitbrowser.cn/updatelog/bitbrowser-7.1.0-upgrade-log) · [7.1.2 日志](https://www.bitbrowser.cn/updatelog/bitbrowser-7.1.2-upgrade-log) · [窗口接口](https://doc2.bitbrowser.cn/jiekou/liu-lan-qi-jie-kou.html) |
| 如何接上同一实例？ | `/browser/ports` 查询当前已打开窗口的远程调试端口。官方响应示例中，`data` 以窗口 ID 为键，端口为字符串。本机默认配置下，可将同一 ID 对应的端口与回环地址组成 HTTP 调试端点。端口归属需在连接时查询，官方没有承诺重启后沿用。[端口查询与示例](https://doc.bitbrowser.net/api-docs/browser-profiles) · [本机默认调试地址](https://doc2.bitbrowser.cn/jiekou/liu-lan-qi-jie-kou.html) |
| 关闭的窗口如何启动？ | `/browser/open` 接受必填的 `id` 和可选的 `args`。普通启动可只传 ID。成功响应的 `data.ws` 是浏览器级 WebSocket 调试地址，`data.http` 是 HTTP 调试地址，另有 `coreVersion` 和 `driver`。官方示例中的 `http` 只有主机与端口，接收 URL 的调用方需补协议。[打开窗口及响应示例](https://doc.bitbrowser.cn/api-jie-kou-wen-dang/liu-lan-qi-jie-kou) |
| 如何关闭？ | `/browser/close` 按同一字符串 ID 关闭窗口。官方要求关闭后等待 5 秒，让进程彻底退出，再重新打开。只有在确认进程已退出且状态卡在打开中或关闭中时，官方才描述重置窗口状态的用途。[关闭与状态重置](https://doc2.bitbrowser.cn/jiekou/liu-lan-qi-jie-kou.html) |

## 有界面、无头与重复打开

按次无头启动时，官方指南要求 `args` 传 `["--headless"]`，`ignoreDefaultUrls` 设为 `true`，省略 `newPageUrl`，连接后再打开所需页面。示例还设置了 `queue`。启动时传入多个页面可能导致 `Multiple targets are not supported in headless mode`。指南也允许在窗口配置中预设无头参数，因此只传 ID 时，界面是否可见取决于既有配置。[无头模式指南](https://doc2.bitbrowser.cn/headless.html)

对已经运行的 ID 再次调用 `open`，公开接口未承诺能复用同一个 PID、返回相同端点或切换界面模式。也未给出证明当前调用者启动了该进程的字段。连接已运行实例可走 `ports`。仅凭一次 `open` 成功，无法判断任务结束时是否应代用户关窗。[窗口接口](https://doc2.bitbrowser.cn/jiekou/liu-lan-qi-jie-kou.html) · [响应示例](https://doc.bitbrowser.net/api-docs/browser-profiles)

## 并发、错误及待实测项

2.3.1 / 2.7.7 的历史日志写明本机 API 并发调用每秒最多 10 次。6.0.4 增加 `open.queue=true` 来排队启动，日志写明队列间隔最多 1 秒。7.1.2 仍提到打开中、关闭中的过渡态报错。7.2.0 的日志仅笼统提到接口优化。所查资料未给出当前各端点的保证配额、固定 HTTP 429、`Retry-After` 或可稳定区分鉴权、并发、窗口占用的错误码。[历史限额](https://doc.bitbrowser.cn/updatelog) · [启动队列](https://www.bitbrowser.cn/blog/btllq_6_0_4_sjrz) · [过渡态](https://www.bitbrowser.cn/updatelog/bitbrowser-7.1.2-upgrade-log) · [7.2.0 日志](https://www.bitbrowser.cn/updatelog/bitbrowser-7.2.0-upgrade-log)

真机验证应记录桌面客户端及 Chromium 内核版本。在专用测试窗口上比较手工打开后与再次请求打开后的 PID、端口和界面可见性，核对关闭后两种运行状态查询收敛的时间。鉴权失败和限流也需记录实际的 HTTP 状态及脱敏业务错误。以上均为待验证项。
