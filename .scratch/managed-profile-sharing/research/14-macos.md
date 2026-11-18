# macOS AdsPower 实机验收记录

2026-11-18，macOS 26.6.2，AdsPower Global 8.9.23。运行版本为 `3936aae79cf4761bbf9314b396b7a2520327b3b0`。本轮仅尝试了冷启动，未通过。[工单 #14](../issues/14-adspower-macos-acceptance.md)

| 本地时间（UTC+8） | 实际观察 |
| --- | --- |
| 20:08:28 | 按历史测试 Profile ID 查询 AdsPower，状态为 `Inactive`。 |
| 20:08:29.237 / 20:08:29.247 | TikTok `upload-video`、Instagram `upload-note` 两个独立进程相隔约 10 毫秒进入正式 CLI，均带 `--no-publish`。 |
| 20:08:29.665 | TikTok 发出唯一一次 Start。AdsPower 桌面日志确认收到针对该 Profile 的请求。首轮未采集 Start 的响应体，无法确定失败原因。 |
| 20:08:30.486 / 20:08:30.513 | TikTok 以 `1` 退出，提示启动状态或连接无法确认。Instagram 随后以 `1` 退出，提示上次启动或当前连接尚未确认。两条命令均未到达编辑器就绪点。 |
| 退出后 | 合计 1 次 Start、0 次 Stop。两次按 ID 查询均返回 `Inactive`。没有可核对的编辑页或草稿标记，未执行发布。 |

所选 ID 是历史 Instagram、TikTok 和 Rednote 验收日志中的唯一交集。随后使用当前 AdsPower 凭据，分别通过 V1 的 `user_id` 和 V2 的 `profile_id` 精确查询列表。两者均请求成功，返回零条匹配记录。单独的 `Inactive` 响应无法确认该 Profile 目前可用。核对两种启动环境时，项目进程默认继承的凭据收到鉴权拒绝；交互式 shell 配置的凭据通过鉴权，上述两次成功的列表查询使用了这组配置。

待确认当前同时登录 Instagram 和 TikTok 的测试 Profile 后，需重新执行冷启动，并补验桌面先打开、强杀后保留浏览器、强杀后手动关闭再重开三种场景。
