# 10 — 部署拓扑：桌面应用、Docker launcher，还是跨机

Status: resolved
Type: grilling
Blocked by: —
Assignee: —

## Question

调研确认：`launcher.mlx.yt:45001` 解析到 `127.0.0.1`；CDP 端口由 launcher 在本机分配；官方**不支持跨机 launcher**；Docker launcher 的 CDP 端口如何暴露到宿主机，官方文档没有闭环。需要选一个 v1 支持的拓扑：

1. **本机桌面应用**（Mac/Windows 上同时跑 social-auto-upload 与 Multilogin 桌面应用）
   - 作为唯一支持路径？
   - CLI 启动前是否强制 `GET /api/v1/version` 探活？
2. **本机 Docker launcher**（social-auto-upload 也在同一台机器，但 MLX 跑在容器里）
   - 是否值得支持？需要解决容器 CDP 端口映射（官方 compose 只映射 45001/45003）。
   - 如果支持，设计要求是什么（network_mode、端口段、容器内跑 Playwright）？
3. **跨机**（social-auto-upload 在另一台机器/云服务器，MLX 在桌面机）
   - 明确不支持，还是允许用户自己搭 SSH/VPN 隧道？后者属于未文档化用法。
4. **Linux 无桌面**场景：MLX 官方有 headless/agent 方案，是否纳入？
5. CLI 需要给出什么样的前置条件错误提示（launcher 未运行 / 版本不匹配 / 跨机）？

## Context

- 调研 01：远程 launcher 官方不支持；Docker + CDP 未验证；Docker 镜像仅 amd64。
- 用户当前环境：Mac（本仓库所在机器），但部署目标“还没定”。
- 调度 App 可能部署在云上；如果如此，CLI 与 MLX 必须同机，调度 App 通过远程调用该机器。

## Answer

决策（2026-11-05）。

### 结论：v1 只支持“同一台机器 + Multilogin 桌面应用”

| 拓扑 | v1 | 说明 |
|---|---|---|
| 本机桌面应用（Mac/Windows） | **唯一支持** | `launcher.mlx.yt:45001` → `127.0.0.1`，CDP 端口由本机 launcher 分配，官方唯一闭环路径 |
| 本机 Docker launcher | **不支持** | 官方 compose 只映射 45001/45003，CDP 端口段未映射；无官方 Playwright 示例；镜像仅 amd64。留待 ticket 08 真机验证后再评估 |
| 跨机（CLI 在云上，MLX 在桌面机） | **明确不支持** | 官方要求 `127.0.0.1`；不支持用户自建 SSH/VPN 隧道作为契约，文档只写“不支持” |
| Linux 无桌面（MLX headless/agent） | **不纳入 v1** | 无桌面应用拓扑，属于另一套部署形态；保持 out of scope |

**硬前提（写入 ticket 09 的部署前提）**：执行 `sau` 的进程必须与 Multilogin 桌面应用在同一台 macOS/Windows 机器；桌面应用已启动并占用 45001；Profile 使用 Mimic 内核；Profile 已由人工登录且无待处理验证码。

调度 App 若部署在云上，**调度侧通过远程方式在“MLX 那台机器”上执行 CLI**，而不是把 CLI 指向远程 launcher。这条只写进文档，不在代码里实现远程能力。

### 启动前探活：强制 `GET /api/v1/version`

`MultiloginClient` 在每次 MLX `browser_session` 的 Start 之前先探活一次（无 Authorization，与官方健康检查一致）：

- `verify=True`（ticket 01：当前证书是公网 DV），超时 3s；
- 失败（连接拒绝 / DNS / TLS / 超时 / 非 200）→ 抛 `RuntimeError`，退出 1，不进入 Start；
- 探活成功不打印 version、不做版本门禁（避免把“桌面应用版本旧”变成硬失败）；版本信息只在 `--debug` 时可查，不写入默认日志；
- 每次 CLI 调用探活一次，不做进程内缓存（一个进程只会有一次会话）；
- 探活失败文案固定，包含三个检查项：

```
无法连接 Multilogin Launcher（https://launcher.mlx.yt:45001）。
请确认：1) Multilogin 桌面应用已启动；2) CLI 与 Multilogin 在同一台机器；
3) 45001 端口未被占用或被防火墙拦截。
```

### Base URL 与逃生开关

- Base URL 固定为 `https://launcher.mlx.yt:45001`，**不提供环境变量覆盖**（官方无此约定，ticket 01）。
- 不引导用户改用 `https://127.0.0.1:45001`（证书 SAN 不含 IP，必然 hostname 校验失败）。
- 不做 launcher 进程检测、不自动启动桌面应用、不管理 Docker：CLI 只负责“连不上就说清楚”。

### Docker 与跨机的错误提示

不实现拓扑探测（无法可靠区分 Docker / 跨机 / 桌面应用），只在两类失败上追加提示：

1. **探活失败**：使用上面的固定文案（已覆盖跨机与未启动）。
2. **Start 成功但 CDP 连接 3 次重试均失败**（ticket 05）：在原始错误后追加一句：
   `若你使用 Docker launcher，CDP 端口默认未映射到宿主机；v1 请改用 Multilogin 桌面应用。`
   不改变退出码（仍为 1）。

### 对下游 ticket 的约束

- **ticket 09**：部署前提小节必须包含上表与“同机”硬要求；验收清单里加一条“launcher 未启动时 CLI 退出 1 且文案可操作”。
- **ticket 11**：不因 Docker 拓扑放宽 patchright 版本要求。
- **ticket 08**：真机验证时额外记录“桌面应用 + 本机”的探活到 Start 的耗时；Docker 验证只作为附录风险，不作为 v1 验收项。
