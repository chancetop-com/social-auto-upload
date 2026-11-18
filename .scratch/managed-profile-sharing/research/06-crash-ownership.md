# CLI 崩溃后，还能认出它启动的浏览器吗？

2026-11-18 在 macOS 上验证，**AdsPower 可以用单次启动参数识别上一次 CLI 打开且仍在运行的浏览器**。同一个 Profile 从桌面重开后，旧参数消失。Multilogin X 的已有 Profile 尚无同等证据。单凭活动状态只能确认 Profile 已打开。[AdsPower 启动参数](https://localapi-doc-en.adspower.com/docs/Open-Browser-V2) · [Multilogin 官方 Launcher 集合](https://documenter.getpostman.com/view/28533318/2s946h9Cv9#531a1370-6ac3-49d5-8914-d9c07dc98636)

本记录保留当时对启动者识别方案的调查。用户随后选定按使用中的 CLI 数量关闭 Profile，实施与验收以[谁负责加入、离开和停止共享托管会话](../issues/02-process-lifecycle.md)为准。

## AdsPower 实机结果

AdsPower Global 8.9.23，桌面窗口显示组件版本 2.9.0.7，浏览器报告 Chrome 156.0.8078.36。经用户授权，选用一个起初处于 `Inactive` 的现有 Profile。将随机 UUID 作为单个 `--sau-owner-test=<UUID>` 参数，仅放进这次 Start 的 `launch_args`，保留默认 CDP 设置。各次检查在独立的本机进程中执行。

| 顺序 | 观察结果 |
| --- | --- |
| CLI 冷启动，启动脚本退出，新进程连接 | 新进程从当前浏览器读到第一次启动的随机标记 A。 |
| 浏览器仍开着，第二次 Start 带另一个标记 B | 两次 Start 都返回成功并给出同一浏览器连接。浏览器进程参数仍有 A，没有 B。随后通过核验过的浏览器连接关闭，桌面显示已打开数归零。 |
| 在 AdsPower 桌面点击同一行的「打开」 | 当前浏览器连接已更换。A 和 B 均消失。再次调用带 B 的 Start 也返回成功，但手动打开的浏览器仍不带 B。临时版本页用完关闭，桌面仍显示 Profile 活动。最后从桌面关闭该对照会话。 |
| CLI 将新标记写入本机，再启动并被 `SIGKILL` | Start 响应到达后，启动脚本在保存连接地址前被终止，退出状态为 137。新进程重新查询当前 Profile，在自己的版本页读到新标记，也在该浏览器的进程参数中核对成功。它通过同一条已经验证的浏览器级 CDP 连接调用 `Browser.close`。AdsPower 随后报告 `Inactive`，Profile 回到测试前状态。 |

**读取方法。** 所测默认配置下，`Browser.getBrowserCommandLine` 返回 CDP 错误 `-32000`。有效的方法是在 CLI 新开的 `chrome://version/` 页面读取 `#command_line`，按完整参数核对预期随机值并关闭该页。另用 `SystemInfo.getProcessInfo` 找出当前连接的浏览器主进程，在 macOS 核对该进程的启动参数，两种读法在手动会话和崩溃恢复对照中一致。记录只保留是否匹配，不保存完整命令行或调试地址。生产实现宜将随机值绑定到当前用户、provider 和 Profile，在 Start 前保存，只在新建浏览器时传入。[Chromium Browser 协议](https://raw.githubusercontent.com/ChromeDevTools/devtools-protocol/master/pdl/domains/Browser.pdl)

**实测范围。** 本次证明了这个版本的启动归属、桌面重开识别和本机活动状态回收。已有 Profile 自定义启动参数的合并效果、其他系统和内核版本、云端数据同步未测。核验后的连接若断开，应放弃关闭；重新查询后按 Profile ID 调 Stop 仍可能影响之后手动重开的浏览器。[AdsPower Stop](https://localapi-doc-en.adspower.com/docs/Close-Browser-V2)

## 接口证据

| 来源 | 可以获得的证据 | 对桌面启动或重开的判断 |
| --- | --- | --- |
| AdsPower Local API V2 | 单次 `POST /api/v2/browser-profile/start` 支持 `launch_args`，API 参数优先于 Profile 配置。启动响应和本机 `active` 的示例都给出浏览器 WebSocket 与端口。 | 值得用一次性随机值标记启动请求。官方未承诺任意自定义参数会传到最终浏览器、重复 Start 会如何处理，或下一次桌面启动一定移除参数。需在目标内核验证，且须确认原有 Profile 启动选项仍生效。[Start](https://localapi-doc-en.adspower.com/docs/Open-Browser-V2) · [Active](https://localapi-doc-en.adspower.com/docs/Check-Browser-Status-V2) |
| AdsPower 审计 | 桌面 Action Logs 的 Open Log 记录打开方式和设备 IP。跨设备状态可给出打开者账号；开启 Multi Device 后可能返回空列表。 | 可由操作者查历史。公开说明未列出打开方式的具体枚举、与本次 CLI 请求对应的 ID，或将日志原子地关联到当前浏览器的接口。即使知道经 API 打开，同一账号也可能运行多个 API 客户端。[Open Log](https://help.adspower.com/docs/action_logs) · [跨设备状态](https://localapi-doc-en.adspower.com/docs/Check-Browser-Status-crossdevices) |
| Multilogin X 已保存的 Profile | 官方 Postman 集合的 Start v2 列出路径参数 `folder_id`、`profile_id`，查询参数 `automation_type`、`headless_mode`，未列请求体。`X-Strict-Mode` 控制参数校验。成功示例的 `data.id` 与请求的 `profile_id` 相同。 | 普通 Start 未公布一次性启动参数或每次启动唯一的 ID。Mimic 的 `cmd_params` 支持创建、修改及启动 Quick Profile；写入原 Profile 会让后来的桌面启动也可能带上标记。Quick Profile 另建会话，不能代表原有 Profile。[普通 Start](https://documenter.getpostman.com/view/28533318/2s946h9Cv9#531a1370-6ac3-49d5-8914-d9c07dc98636) · [官方 JSON 原件](https://documenter.gw.postman.com/api/collections/28533318/2s946h9Cv9?segregateAuth=true&versionTag=latest) · [命令行参数的支持范围](https://multilogin.com/help/en_US/postman/mimic-command-flags) |
| Multilogin X 状态 | `Get Profile Status` 示例含 `in_use_by`、`last_launched_by`、`last_launched_at`、`last_launched_on`。Agent 重启会丢失这组会话状态。按自动化类型启动时，状态的 `message` 可含端口。 | 同机同账号的两种启动可有相同的用户和机器。时间变化是复核线索；时间或端口一致都不足以指认这个 CLI。官方 Launcher 集合的状态接口没有列出本次启动的不可变代号或调用方请求 ID。[状态接口](https://documenter.getpostman.com/view/28533318/2s946h9Cv9#0ad3f26d-ae66-459c-8db6-7c5fa5a90198) · [v5.3 发布说明](https://t.me/s/multilogin?before=783) |

## 当时调查的恢复方案

1. **AdsPower 可从 Start 之前开始记录。** 先将 provider、Profile 和单次随机值写入本地，再仅在本次 Start 的 `launch_args` 中传入它。这样即便响应尚未落盘，恢复时仍有预期值。Chromium 实验命令 `Browser.getBrowserCommandLine` 仅在浏览器带有 `--enable-automation` 时返回参数。若目标内核支持回读、标记没有持久化且桌面重开不会继承它，当前进程回显随机值才支持这次启动的归属。参数不可读或不匹配时，保持归属未知。不要从页面、Cookie 或可恢复的标签 URL 认领进程。[AdsPower 启动参数与标签恢复](https://localapi-doc-en.adspower.com/docs/Open-Browser-V2) · [Chromium Browser 协议](https://chromium.googlesource.com/chromium/src.git/+/5c0ea30b10bd15e08e52adc16c6a3619c071ec28/third_party/blink/public/devtools_protocol/domains/Browser.pdl)
2. **两家的 Chromium 内核都可试验实例连续性。** 当最初的归属已经确认，可记录浏览器级 WebSocket 的完整标识。上游 Chromium 的 DevTools 服务可在创建时生成随机 UUID，也有使用固定路径的分支。只有验证过会随实例更换的标识才有判断价值。不同或缺失时放弃认领；旧标识匹配只能延续当初的判断。若 CLI 在取得并保存标识之前退出，Multilogin 普通 Start 本身未提供可供事后补查的单次标记。[Chromium DevTools 服务实现](https://chromium.googlesource.com/chromium/src/+/c686e8f4fd379312469fe018f5c390e9c8f20d0d/content/browser/devtools/devtools_http_handler.cc) · [Multilogin 普通 Start](https://documenter.getpostman.com/view/28533318/2s946h9Cv9#531a1370-6ac3-49d5-8914-d9c07dc98636)
3. **识别与关闭各有自己的竞态。** 两家 Stop 都按 Profile 定位，请求中没有预期实例 ID。查询匹配后，桌面仍可在 Stop 到达前关闭旧实例、打开新实例。候选做法是从已经验证的同一条浏览器级 CDP 连接发 `Browser.close`。连接断开即停止，不按 Profile ID 重试。部署前还要确认 provider 为每个 Profile 隔离浏览器、能正确更新状态、释放锁和保存数据；归属证据也不能说明此刻有无人正在用这个窗口。[AdsPower Stop](https://localapi-doc-en.adspower.com/docs/Close-Browser-V2) · [Multilogin Stop](https://documenter.getpostman.com/view/28533318/2s946h9Cv9#a9ffc89c-9c09-4afd-80c8-d071cc0e52bb) · [Chromium Browser 协议](https://chromium.googlesource.com/chromium/src.git/+/5c0ea30b10bd15e08e52adc16c6a3619c071ec28/third_party/blink/public/devtools_protocol/domains/Browser.pdl) · [Multilogin 数据同步](https://multilogin.com/help/en_US/opening-browser-sessions)

Multilogin X 本次仅核对接口，当前环境未配置 Launcher 的自动化 token，未对真实 MLX Profile 发出 Start 或 Stop。启动者识别调查至此结束。[桌面和 CLI 先后启动时能观察到什么](../issues/06-manual-start-race.md) · [进程中断后怎样识别和恢复遗留会话](../issues/04-abandoned-session.md)
