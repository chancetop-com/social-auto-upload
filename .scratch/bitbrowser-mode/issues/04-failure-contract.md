# 窗口启动选项和 API 错误怎样映射到 CLI 契约

Label: wayfinder:grilling
Type: grilling
Status: open
Blocked by: 01

## Question

冷启动或加入已开窗口时，怎样处理 `--headless` 和 `--headed`？客户端不可达、凭据无效、窗口不存在、CDP 连接失败、HTTP 或业务层限流和停止失败，各应给调用方什么退出码或提示？区分有官方依据的信号与未知响应，延用现有平台登录失效、发布结果未知及清理时保留主结果的约定。

对照[现有退出码](../../../docs/CLI.md#退出码)与[比特浏览器的本机 API 能力](01-local-api.md)。
