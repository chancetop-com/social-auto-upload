# 使用 Rednote 账号核实登录与发布页面差异

Type: task
Status: resolved
Blocked by: 01, 02

## Question

用户人工登录 Rednote 后，第一版适配器能否识别登录态并完成视频、图文发布前的准备？记录实际 URL、语言、选择器和能力差异，再调整适配器；验证到点击发布之前为止。

## Comments

- 已确认普通 Chrome 有登录态，但它与 CLI 测试浏览器不同；尚未保存 CLI 的本地 Rednote 会话。
- 初次浏览器启动受沙箱限制，已在沙箱外获准启动。
- 真实登录发现 `goto` 默认等待 load 会因外部资源超时而关闭窗口，已改为等待 domcontentloaded；修复后的窗口正常停在登录页，等待用户登录。
- 用户已在测试窗口完成登录，CLI 成功保存会话。真实 cookie 元数据只有 Rednote 的 `web_session` / `id_token`，没有小红书 `galaxy_creator_session_id`；已修正预检并新增回归用例。只记录名称与域名，不记录值。
- 新进程 `sau rednote check --account rednote --headless` 返回 `valid`，退出 `0`。
- 用户明确授权 `--no-publish` 干跑；两张中性图上传、英文标题/正文填写与 ARM 就绪通过，退出 `0`，没有点击发布。
- 3 秒中性视频上传、英文标题/正文填写与 ARM 就绪通过，退出 `0`，没有点击发布。

## Answer

本地真实账号登录、无头新进程 `check`、双图和视频的 `--no-publish` 全部通过。核心 DOM 可复用小红书结构；Rednote 的真实登录 cookie 名称不同，已修正为 `web_session`。本地统一使用 `en-US` context，但这不代表服务端提供纯英文 UI。

验证记录见 [第一版验收](../acceptance.md)。最终提交未经授权也未执行；高级选项和纯英文页面的控件差异作为后续验证票据保留。
