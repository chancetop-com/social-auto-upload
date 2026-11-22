# 比特浏览器托管模式决策地图

Label: wayfinder:map

## Destination

明确 `sau` 如何用 `--profile-id` 打开或加入已有的比特浏览器窗口，复用其中的登录态，完成现有七个平台的检查和发布。地图完成时，开发者能从已决工单查到调用方式、窗口共享规则、失败处理和验收依据。

## Notes

- 本轮交付决策地图。用户已确认沿用 AdsPower 和 Multilogin X 的使用方式：用户在桌面端建好窗口、配置并登录，调用方把窗口 ID 传给 CLI。
- 截至 2026-11-22，用户暂无比特浏览器账号。当前 API 结论来自官方资料，真机验收项均待验证。[哪些证据足以验收比特浏览器托管模式](issues/05-acceptance.md)
- 对齐现有 20 个入口：七个平台均支持登录检查和视频发布，除 YouTube 外的六个平台另有图文发布。两个小红书平台、Facebook 个人与 Facebook Page 分别计数。[命令矩阵](../../docs/CLI.md#平台支持范围)
- 共享行为以现行契约为准：同一窗口允许不同平台并行，同平台同时限一条命令。每条命令清理自己的页面，最后离开的命令关闭整个窗口，包括用户从桌面打开的窗口。[共享托管 Profile](../../docs/CLI.md#共享托管-profile)
- 延用本地模式及两种现有托管模式的参数和退出码。调度方需要区分调用错误、登录失效、API 限流和发布结果未知。[CLI 契约](../../docs/CLI.md#托管浏览器模式通用) · [领域术语](../../GLOSSARY.md)
- 后续会话使用 Wayfinder，依照[本地工单约定](../../docs/agents/issue-tracker.md#wayfinding-operations)选取可开始的决策。以当前 CLI 为准。
- 实现交付：07–13 已合并到 `feat/bitbrowser-managed-mode`（最终集成 HEAD `6b5d490`），离线契约测试通过。14 保持 `ready-for-human`，待真实比特浏览器客户端验收。

### 实现参照

- 用户指定以 AdsPower 为实现范本。沿用 `AdspowerTarget`、`AdspowerClient`、`AdspowerProvider` 的职责划分：窗口 ID 标识目标，HTTP 客户端处理比特浏览器的请求与响应，provider 向共享会话层提供窗口状态、连接地址和关闭能力。[AdsPower 实现](../../utils/adspower.py) · [共享 provider 接口](../../utils/managed_browser.py)
- 在现有 `resolve_managed_provider` 入口接入比特浏览器。各平台继续通过 `browser_session` 使用浏览器，跨平台并行、页面归属和最后退出的协调沿用共享会话层。[CLI 选择入口](../../sau_commands/browser.py) · [浏览器会话](../../utils/browser_session.py) · [共享协调](../../utils/managed_sharing.py)
- 鉴权头、已开窗口的调试端口、关闭后进程退出的时机均按比特浏览器的行为适配。离线验证参照 AdsPower 的客户端、CLI 和会话测试，使用比特浏览器自己的响应样例。[本机 API 研究笔记](research/01-local-api.md) · [客户端测试](../../tests/test_adspower_client.py) · [CLI 测试](../../tests/test_adspower_cli.py) · [会话测试](../../tests/test_adspower_browser_session.py)

## Decisions so far

- [比特浏览器本机 API 能为既有窗口提供哪些能力](issues/01-local-api.md) — 已有窗口可按 ID 打开、查调试端口和关闭。普通 Local API 的 Token 可选。
- [调用方怎样选中比特浏览器并定位已有窗口](issues/02-activation.md) — 首版通过非空 `BITBROWSER_API_KEY` 选中比特浏览器，`--profile-id` 使用桌面端复制的窗口 ID。
- [冷启动、加入和最后退出时怎样识别同一个窗口](issues/03-shared-window.md) — 沿用 AdsPower 的规则，加入时核对浏览器实例，最后一条命令直接按窗口 ID 关闭。
- [窗口启动选项和 API 错误怎样映射到 CLI 契约](issues/04-failure-contract.md) — 沿用 AdsPower 的启动、加入和退出码规则。冷启动信任启动请求，加入时核对显式模式，清理失败保留主结果。
- [哪些客户端版本和配置属于首版支持范围](issues/06-client-compatibility.md) — 首版按所需 Local API 能力界定兼容性，不设最低版本号。CLI 按失败的操作和实际响应给出诊断。
- [哪些证据足以验收比特浏览器托管模式](issues/05-acceptance.md) — 20 个入口离线通过即可交付实现。有账号后实测七个平台的登录检查，以及 TikTok 视频和 Instagram 图文的发布前停止与窗口共享。

## Not yet specified

<!-- 当前可明确表述的问题均已建单。后续实测发现新的版本差异时再补充。 -->

## Out of scope

- 比特浏览器窗口的创建、批量管理、代理与指纹配置，以及平台账号登录，均由使用者在桌面端完成。
- 本轮范围限于已有托管入口。`verify`、`delete`、`article` 和独立素材管理命令沿用各自的现有路径。实现和真实发布操作留给后续开发与验收。
