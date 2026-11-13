# 05 — Provider 接缝：运行时是第二维度还是两个 mode

Status: open
Type: grilling
Blocked by: 02
Assignee: —

## Question

决定 GoLogin 如何嵌进 `ManagedBrowserProvider`，这是 spec 的结构核心：

1. **mode 的形状**
   - `ProviderMode` 扩成 `Literal["multilogin", "adspower", "gologin"]` + provider 内部 `runtime: Literal["local", "cloud"]`，还是扩成 `"gologin-local"` / `"gologin-cloud"` 两个 mode？
   - `BrowserSession.mode` 的手写 `Literal` 与 `session.managed` 判定怎么跟着变；38 处 `browser_session(` / 25 处 `.mode ==` 是否要动。
   - 平台层只看 `session.managed` 的既有约束是否仍成立。
2. **Protocol 是否够用**
   - `probe()` / `start(headless) -> connect_url` / `stop()` / `status()` 在云端运行时是否语义不变；若云端需要额外步骤（换 token、心跳、延长会话），是加可选方法还是让 provider 内部吸收。
   - `start` 返回的 connect URL 在云端是 `wss://` 时，`connect_over_cdp` 与现有错误文案（`endpoint=` / `port=`）怎么处理。
3. **构造与解析**
   - `resolve_managed_provider()` 里 runtime 从哪里读、在哪校验；provider 对象是否暴露 `runtime` 供启动行与文案使用。
   - `_PROVIDER_WORDINGS` 如何为 GoLogin 提供 label / login 拒绝 / 平台拒绝三段文案；本地与云端是否共用 label。
4. **启动行与日志**
   - `_managed_extras()` 现在按 mode 分支；GoLogin 应输出 `runtime=`、`endpoint=` 还是 `port=`。
   - `provider_label()` / `_PROVIDER_LABELS` / `_CONNECTION_HINTS` 的扩展方式。

## Context

- 现有接缝见 `utils/managed_browser.py`、`utils/browser_session.py`、`sau_commands/browser.py`。
- 这张 ticket 的结论决定 spec 的模块图与时序图，必须给出「最小改动面」与「若选另一方案要改哪些文件」。
