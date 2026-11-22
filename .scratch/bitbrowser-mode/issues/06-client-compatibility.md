# 哪些客户端版本和配置属于首版支持范围

Label: wayfinder:grilling
Type: grilling
Status: resolved
Assignee: LukeChen
Blocked by: 02, 03, 04

## Question

官方变更记录表明，Token 鉴权、已开窗口列表和列表筛选在不同版本引入，窗口本身也可以预设启动参数。结合最终选用的鉴权、窗口观察和启动方式，应按客户端版本还是实际必需的 API 能力界定支持范围？当必要能力缺失时，调用方靠什么现象和诊断确认当前客户端超出范围？[本机 API 研究笔记](../research/01-local-api.md)

## Answer

用户确认首版沿用 AdsPower 的兼容策略。CLI 固定使用已选定的 Local API 接口，在执行相应操作时检查响应。首版不设桌面客户端最低版本号，也不在启动时探测版本或回退到旧接口。真机验收记录实际使用的桌面客户端和 Chromium 内核版本。[AdsPower CLI 约定](../../../docs/CLI.md#adspower-参数) · [哪些证据足以验收比特浏览器托管模式](05-acceptance.md)

支持的配置须启用 Local API 和 Token 鉴权，能按窗口 ID 查询进程和调试端口、经 CDP 连接现有 Chromium 上下文，并按 ID 打开和关闭窗口。缺少「已打开窗口」列表或 `opened` 筛选的旧客户端，只要具备上述能力，也在支持范围内。窗口预设了启动参数时，沿用已定的冷启动与加入规则。[调用方怎样选中比特浏览器并定位已有窗口](02-activation.md) · [冷启动、加入和最后退出时怎样识别同一个窗口](03-shared-window.md) · [窗口启动选项和 API 错误怎样映射到 CLI 契约](04-failure-contract.md)

例如，`check` 查到窗口进程在运行，随后请求 `/browser/ports` 收到 HTTP 404，应在打开平台页面前以 `1` 退出，保留现有窗口，并提示「查询窗口调试端口失败（HTTP 404），请检查 Local API 地址及客户端是否支持该接口」。如果请求超时，则提示「查询窗口调试端口超时」。调用方可依据失败的操作和实际响应排查原因，单次 404 或超时都不足以判定客户端版本过旧。
