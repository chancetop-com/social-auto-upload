# 调用方怎样选中比特浏览器并定位已有窗口

Label: wayfinder:grilling
Type: grilling
Status: resolved
Assignee: LukeChen
Blocked by: 01

## Question

在已定的 `--profile-id` 用法下，调用方应使用哪个环境变量明确启用比特浏览器？窗口 ID 对应桌面端哪个标识？地址或凭据怎样传入，空值、纯空白、仅设置地址、与其他托管凭据并存时各是什么结果？用一个有效的 `check` 调用和一组冲突案例定下对外契约。

普通 Local API 允许关闭 Token 鉴权，而现有两个提供方都按非空凭据激活。首版是否覆盖无 Token 配置？若覆盖，调用方如何显式选中比特浏览器并避免误用本地模式？[当前激活与优先级规则](../../../docs/CLI.md#激活与优先级) · [比特浏览器本机 API 能为既有窗口提供哪些能力](01-local-api.md)

## Answer

用户选定首版只支持已开启 Token 鉴权的比特浏览器。调用方把桌面端生成的 Token 放入 `BITBROWSER_API_KEY`。CLI 去掉首尾空白后，以非空值选中比特浏览器，并通过 `x-api-key` 请求头发送 Token。无需额外的启用开关。

窗口由桌面端“复制 ID”得到的字符串 `id` 指定。将该值传给 `--profile-id`。显示序号 `seq` 和窗口名称均不能用来查找或替换 ID。比特浏览器模式下，缺少 ID 或去掉首尾空白后为空，按用法错误退出 `2`。`--account` 和 `--folder-id` 沿用 AdsPower 行为，均可省略。[窗口标识与本机服务](../research/01-local-api.md)

以下调用使用进程环境中的 `BITBROWSER_API_KEY`，其中 `WINDOW_ID` 保存复制的窗口 ID。

```sh
sau tiktok check --profile-id "$WINDOW_ID"
```

`BITBROWSER_API_BASE` 仅覆盖已选中比特浏览器时的本机服务地址。未设置、空串或纯空白时使用 `http://127.0.0.1:54345`。客户端改过端口时，使用桌面端显示的地址。

对支持托管模式的命令，三种凭据都先去掉首尾空白。下表中未列出的凭据均为空或未设置。

| 非空的环境变量 | CLI 行为 |
| --- | --- |
| 无，或仅 `BITBROWSER_API_BASE` | 本地模式，即使传了 `--profile-id` 也按本地参数规则处理 |
| 仅 `BITBROWSER_API_KEY`，可另设地址 | 比特浏览器模式 |
| 仅 `ADSPOWER_API_KEY` 或仅 `MLX_API_TOKEN`，可另设比特浏览器地址 | 分别选择 AdsPower 或 Multilogin X |
| `BITBROWSER_API_KEY` 与 `ADSPOWER_API_KEY` | 凭据冲突，退出 `1` |
| `BITBROWSER_API_KEY` 与 `MLX_API_TOKEN` | 凭据冲突，退出 `1` |
| `ADSPOWER_API_KEY` 与 `MLX_API_TOKEN`，或三种凭据齐全 | 凭据冲突，退出 `1` |

冲突检查沿用 CLI 现有顺序，在参数解析成功后、分发命令前结束调用。错误提示指出冲突的变量名，凭据值不进入输出。[现有 CLI 约定](../../../docs/CLI.md#激活与优先级)
