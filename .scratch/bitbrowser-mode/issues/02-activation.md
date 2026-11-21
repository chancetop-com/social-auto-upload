# 调用方怎样选中比特浏览器并定位已有窗口

Label: wayfinder:grilling
Type: grilling
Status: open
Blocked by: 01

## Question

在已定的 `--profile-id` 用法下，调用方应使用哪个环境变量明确启用比特浏览器？窗口 ID 对应桌面端哪个标识？地址或凭据怎样传入，空值、纯空白、仅设置地址、与其他托管凭据并存时各是什么结果？用一个有效的 `check` 调用和一组冲突案例定下对外契约。

普通 Local API 允许关闭 Token 鉴权，而现有两个提供方都按非空凭据激活。首版是否覆盖无 Token 配置？若覆盖，调用方如何显式选中比特浏览器并避免误用本地模式？[当前激活与优先级规则](../../../docs/CLI.md#激活与优先级) · [比特浏览器本机 API 能为既有窗口提供哪些能力](01-local-api.md)
