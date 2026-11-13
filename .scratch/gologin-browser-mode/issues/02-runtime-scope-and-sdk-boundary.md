# 02 — 运行时收口：端口发现、未文档化 API 的脆弱性、headless、云端寿命

Status: resolved
Type: grilling
Blocked by: 01
Assignee: LukeChen

## Question

ticket 01 与 10 已把两条运行时的事实钉死：**本地与云端都可以零依赖实现，SDK 不需要**。本 ticket 只剩三个收口决定：

1. **本地端口发现**
   - 从 `36912` 起逐个 `GET /service/check-server`，最多试 N 个（建议 16），每个 0.2s 超时；找不到就退出 `1` 并给固定排查文案（应用未启动 / 未登录 / 版本过旧）。
   - 是否同时读应用配置里的 `appPort` 作为快路径；不读的话就纯扫描。
2. **未文档化 API 的脆弱性**
   - spec 里怎么表述：按应用版本回归、端点缺失时 fail-fast、不静默回退到 SDK 或本地 cookie 模式。
   - 是否要求启动行打印 `gologin local api port=<port>` 便于排障。
3. **headless 语义**
   - 本地 API 没有 headless 参数 → `--headless` 在本地运行时静默忽略并进 `ignored=`，还是拒绝（退出 `2`）。
   - 云端 `isHeadless` 是 `POST /browser/{id}/web` 的字段，但 `/connect` 不保证继承；是「先 POST 再 connect」还是「直接 connect 且忽略 headless」。
4. **云端 15 分钟寿命**
   - 长视频上传超过 `maxLifeTimeMinutes` 默认 15 分钟时：POST 调大、预算重连、还是拒绝超长任务。这条会影响「云端能否覆盖 16 个平台」的结论。

## Answer

**两条运行时都保留，都零依赖，不使用 SDK。**

1. **本地端口发现**：从 `36912` 起逐个 `GET /service/check-server`，最多 16 个，每个 0.2s 超时；找不到 → 退出 `1`，固定文案「GoLogin 应用未启动 / 未登录 / 版本过旧」。启动行打印 `gologin local api port=<port>`。
2. **未文档化 API 的脆弱性**：端点缺失一律 fail-fast，不静默回退到 SDK、桌面应用手动模式或本地 cookie 模式。spec 写明「按 GoLogin 应用版本回归」，并把「改用 `gologin` SDK 作为启动器」列为**风险备用方案**，不是实现路径。
3. **headless**：本地 API 无此参数 → `--headless` 静默忽略，并进启动行 `ignored=`；云端用 `POST /browser/{id}/web` 的 `isHeadless`。
4. **云端寿命**：先 `POST /browser/{id}/web`（`isHeadless` + `maxLifeTimeMinutes=120`），优先用响应的 `remoteOrbitaUrl` 走 `/json/version` 取 `webSocketDebuggerUrl` 再连（避免 `/connect` 另起会话）；若 `remoteOrbitaUrl` 缺失，回退到文档化的 `/connect` URL 并接受默认寿命。会话中途被回收**不重连**，退出 `1` 并给明确文案。
5. **SDK 结论**：不引入。`pyproject.toml` 零新增依赖。

## Caveats

- `remoteOrbitaUrl` 只见于 SDK 源码，不在 OpenAPI；属于**推断**，实现阶段必须 live smoke 确认。若不可用，云端退回 `/connect` + 默认 15 分钟寿命，并在 spec 标注该限制。
- 云端 `maxLifeTimeMinutes` 是否被后续 `/connect` 继承未知；因此优先走 `remoteOrbitaUrl` 路径。
