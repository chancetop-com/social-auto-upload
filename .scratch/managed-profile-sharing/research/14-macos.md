# macOS AdsPower 实机验收记录

## 历史 Profile 的首次尝试

2026-11-18，macOS 26.6.2，AdsPower Global 8.9.23。运行版本为 `3936aae79cf4761bbf9314b396b7a2520327b3b0`。本轮仅尝试了冷启动，未通过。[工单 #14](../issues/14-adspower-macos-acceptance.md)

| 本地时间（UTC+8） | 实际观察 |
| --- | --- |
| 20:08:28 | 按历史测试 Profile ID 查询 AdsPower，状态为 `Inactive`。 |
| 20:08:29.237 / 20:08:29.247 | TikTok `upload-video`、Instagram `upload-note` 两个独立进程相隔约 10 毫秒进入正式 CLI，均带 `--no-publish`。 |
| 20:08:29.665 | TikTok 发出唯一一次 Start。AdsPower 桌面日志确认收到针对该 Profile 的请求。首轮未采集 Start 的响应体，无法确定失败原因。 |
| 20:08:30.486 / 20:08:30.513 | TikTok 以 `1` 退出，提示启动状态或连接无法确认。Instagram 随后以 `1` 退出，提示上次启动或当前连接尚未确认。两条命令均未到达编辑器就绪点。 |
| 退出后 | 合计 1 次 Start、0 次 Stop。两次按 ID 查询均返回 `Inactive`。没有可核对的编辑页或草稿标记，未执行发布。 |

所选 ID 是历史 Instagram、TikTok 和 Rednote 验收日志中的唯一交集。随后使用当前 AdsPower 凭据，分别通过 V1 的 `user_id` 和 V2 的 `profile_id` 精确查询列表。两者均请求成功，返回零条匹配记录。单独的 `Inactive` 响应无法确认该 Profile 目前可用。核对两种启动环境时，项目进程默认继承的凭据收到鉴权拒绝；交互式 shell 配置的凭据通过鉴权，上述两次成功的列表查询使用了这组配置。

## 操作者确认测试 Profile 后的实测

2026-11-18，macOS 26.6.2，AdsPower Global 8.9.23。以下均为本地时间（UTC+8）。Instagram 使用 `upload-note`，TikTok 使用 `upload-video`，两条命令均带 `--no-publish`。

### 冷启动

| 轮次 | 命令与编辑器 | Start / Stop 与结束状态 |
| --- | --- | --- |
| 首轮，未通过 | 21:13:52 两条命令进入，Instagram 启动 Profile。Instagram 点击前发现落点偏移（`point-drift`），21:14:12 以 `1` 退出。TikTok 在 21:14:32 到达发布前就绪点，随后以 `0` 退出。两份草稿未同时就绪。 | 1 / 1。TikTok 最后请求 Stop 并收到成功响应。下一轮开始前查询为 `Inactive`。 |
| 复测，通过 | TikTok 和 Instagram 分别在 21:15:03.211、21:15:03.215 进入。TikTok 启动 Profile。21:15:38 在两张不同平台的编辑页分别读到对应的草稿标记。TikTok 在 21:15:38.818 以 `0` 先退，此时 Stop 为 0。21:15:39 在 Instagram 原编辑页追加并回读文字，随后 Instagram 以 `0` 退出。 | 1 / 1。Instagram 发出唯一的 Stop，21:15:42 确认为 `Inactive`。 |

### 强杀全部 CLI 后保留浏览器，通过

21:27:59，Instagram 和 TikTok 从空闲 Profile 同时进入，TikTok 发出唯一一次 Start。21:28:31，在两张独立编辑页读到各自的草稿标记后，对两个进程发送 `SIGKILL`。两进程均被终止，Stop 为 0。Profile 仍为 `Active`，两份旧草稿仍在原标签。

21:28:32，新的 Instagram 命令加入同一浏览器，通过第三张标签页准备新草稿。21:29:00，现场同时读到新草稿和两个原标签的标记。从就绪点至该次观察，旧编辑页记录的点击和表单提交事件均为 0。恢复命令以 `0` 退出，原 Instagram `prepared` 结果的 SHA-256 摘要保持一致。恢复阶段共 0 次 Start、1 次 Stop，21:29:03 确认 `Inactive`。

### 强杀全部 CLI 后手动关闭再重开，通过

21:29:50，TikTok 和 Instagram 从空闲 Profile 进入。TikTok 发出一次 Start，于 21:30:11 就绪。Instagram 于 21:30:26 就绪。分别读到两张编辑页的草稿标记后，对两个进程发送 `SIGKILL`。21:30:27 确认两进程已终止，Stop 为 0，Profile 为 `Active`。两份草稿仍在原标签中，可编辑。截至该次观察，两个编辑页记录的点击和表单提交事件均为 0。

操作者确认从 AdsPower 桌面关闭并重开了同一测试 Profile。两次操作之间未采到 `Inactive`。21:44:28 状态接口报告 `Active`，已取得与强杀前不同的浏览器连接。重开后的桌面标记页与两个新编辑页各有独立的标签标识，均与强杀前的旧编辑页不同。Instagram 和 TikTok 的新命令分别在 21:45:01、21:45:03 以 `0` 退出。原 Instagram `prepared` 结果的 SHA-256 摘要保持一致。恢复阶段共 0 次 Start、1 次 Stop，21:46:06 复核为 `Inactive`。

### 桌面预先打开与原标签保留

| 轮次 | 加入与首条退出后的观察 | 末条退出与最终状态 |
| --- | --- | --- |
| 操作者手动打开，与上一节共用一次重开 | 21:44:29 在 CLI 进入前读到桌面原标签的唯一标记。21:44:30 TikTok 和 Instagram 进入。21:45:01 同时读到桌面原标记及两个平台的草稿标记。Instagram 先以 `0` 退出，TikTok 原编辑器仍有草稿标记且可编辑。本轮检查器未能回读预期的完整追加文本，也未在首条退出后再次读取桌面标签。 | 该对命令共 0 次 Start、1 次 Stop。TikTok 以 `0` 退出，随后确认 `Inactive`。 |
| CLI 外通过 Local API 预开，补验首条退出后的页面 | 从 `Inactive` 预先发出 1 次准备 Start。21:55:39 读到本轮桌面标记，21:55:40 两条 CLI 加入。21:56:08 三份标记分别在三张标签页。Instagram 于 21:56:08.844 以 `0` 先退，此时命令发出的 Stop 为 0。21:56:09 在原标签再次读到桌面标记，同时定位到 TikTok 原编辑页，实际追加并回读成功。观察期间两页的点击和表单提交计数均为 0。 | 两条 CLI 合计 0 次 Start、1 次 Stop，准备 Start 单独计数。TikTok 于 21:56:11 以 `0` 最后退出，21:56:12 确认 `Inactive`。 |

在第二轮的已开 Profile 中，21:56:07 还以只读方式找到了第一轮桌面原标签的唯一标记，该页面可编辑。期间没有重建该标记。这补充验证了第一轮桌面原标签的内容能在整次 Profile 关闭并再次启动后恢复。

**再次从桌面手动打开，单轮通过。** 操作者在 AdsPower 桌面打开 2 号后，22:03:46 状态接口返回 `Active`。22:03:47 在两条 CLI 进入前读到本轮桌面标记。两条命令随后加入，均带 `--no-publish`。22:04:14 在三张不同标签分别读到桌面、Instagram 图文和 TikTok 视频的标记。

Instagram 于 22:04:14.385 以 `0` 退出，此时 Stop 为 0。22:04:14.974 复核桌面原标签和 TikTok 原编辑页仍在，标签标识均与退出前一致。22:04:15.533 在 TikTok 原页追加并回读文字，同时读回桌面标记。TikTok 于 22:04:15.721 发出唯一的 Stop，随后以 `0` 退出。22:04:18.244 确认 `Inactive`。本轮两条 CLI 合计 0 次 Start、1 次 Stop，均停在最终发布前。
