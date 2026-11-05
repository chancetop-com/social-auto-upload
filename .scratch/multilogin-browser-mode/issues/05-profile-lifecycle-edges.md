# 05 — Profile 生命周期与失败边界

Status: resolved
Type: grilling
Blocked by: 01
Assignee: LukeChen

## Question

“谁启动谁停止”已定，但边界行为还需逐项拍板：

1. **连接策略**：官方 demo 是 Start 200 后直接 `connect_over_cdp`。是否需要超时 + 少量退避重试？重试次数/总预算多少？失败后是否查 `/api/v1/profile/status/p/{id}` 做诊断？
2. **启动失败分类**：token 401、429、404 profile 不存在、500、CDP 连不上——分别退出码 1 还是可重试信号？错误文案是否必须包含 MLX `error_code`？
3. **Profile 已在运行**：CLI 直接失败（退出 1）并在消息里带 MLX 原始错误，交给调度 App 判断；是否需要额外调用 `/api/v1/profile/statuses` 提供诊断信息？
4. **停止失败**：上传成功但 Stop 失败时，整体算成功还是失败？
   - 选项：成功（仅 warning）/ 失败（退出 1）/ 只在 `--strict` 下失败。
5. **异常路径**：上传中途抛异常（含 KeyboardInterrupt？）时，是否 `finally` 里一定 Stop？
6. **check 的副作用**：MLX 模式的 `check` 是否也 start → 检测 → stop？还是允许 attach 已运行 Profile？
7. **stop 等待**：Stop 后是否需要轮询 `/api/v1/profile/statuses` 确认已停止，还是 fire-and-forget？
8. **日志**：是否记录 profile_id、folder_id、port、耗时（start / upload / stop）？是否会泄露 token（必须不记录）？

## Context

- 已确认：库内不做并发锁；同一 profile 的并发由调度 App 串行。
- 已确认：登录失效退出码 10；其他失败 1；argparse 2。
- 需结合 01 的 API 事实决定可重试与幂等语义。

## Answer

决策（2026-11-05）：

1. **连接策略**：Start 200 拿到 `data.port` 后直接 `connect_over_cdp("http://127.0.0.1:{port}")`；单次连接超时 10s，最多 3 次，退避 2s→4s（总预算约 16–20s）。只对“连接被拒/超时”重试；401/403/lock 冲突不重试。3 次耗尽后调一次 `GET /api/v1/profile/status/p/{id}` 取 `data.status`，把状态并入错误消息，退出 1。不把“先轮询 statuses”写成前置步骤。
2. **启动失败分类**：全部沿用现有异常路径——抛 `RuntimeError`，由 `sau_cli` 打到 stderr，退出 1；**不新增退出码，不加 `retryable=` 之类结构化字段**。消息保留 MLX 原始 `status.error_code` / `message` / HTTP 码，让调度侧自行判断。401 / 403 / 404 / 429 / 5xx / CDP 连不上 / lock 冲突一律退出 1；429 不在 CLI 内等待。
3. **Profile 已在运行**：不额外调 `/statuses`；把 Start 的原始错误（HTTP 500 `can't lock profile`）包成 `RuntimeError` 退出 1，可附一句“Profile 可能已在运行，由调度 App 处理”。**绝不自动 stop 别人的 profile**。
4. **停止失败**：上传已成功时整体退出 **0**，stderr 输出警告（含 MLX 原始错误）：上传已完成但 Stop 失败，Profile 可能仍在运行，需调度侧清理。避免调度按“失败=重传”造成重复发布。
5. **异常路径**：`browser_session` 用 `try/finally`；只要 Start 返回 200（已标记 started）就一定尝试 Stop，覆盖普通异常、`KeyboardInterrupt`、`CancelledError`。Stop 自身失败只 warning，不覆盖原异常/退出码。取消路径上 Stop 需用 `asyncio.shield`（或独立 task）确保请求发出。Start 失败（含 lock 冲突）**不** Stop。SIGKILL/断电等进程级死亡无法保证。`KeyboardInterrupt` 保留 Python 默认退出码（130），不属于调度契约，但 finally 必须先执行 Stop。
6. **check**：MLX check 与普通 check 语义一致——start → 进受保护页面判断登录态 → finally Stop。`0`=已登录；`10`=未登录/验证码/2FA；`1`=MLX 或生命周期错误。不做身份 ID 比对（由 ticket 12 定）。Profile 被占用时按第 3 条报错退出 1。
7. **Stop 后确认**：**fire-and-forget**。Stop 成功或返回 500 `profile already stopped` 后立即返回，不轮询 statuses、不做端口探活、不 sleep。若下一个任务 Start 撞锁，由调度 App 重试。
8. **日志**：复用现有平台 loguru（console + `logs/<platform>.log`），新增普通中文 INFO 行：启动成功（`profile_id` / `folder_id` / `port`）、开始停止。**不加耗时**。`MLX_API_TOKEN` 与 `Authorization` 头**永不记录**（连截断也不打）。错误行可带 MLX error_code/message，但不带 token。

补充边界：

- Stop 判定成功：HTTP 200，或 HTTP 500 且 `status.message` 含 `profile already stopped`。
- Stop 的 warning 只走 stderr，不改变退出码 0。
- 只有“Start 200 且拿到 port”才置 started 标记；之后无论连接、登录检测还是上传失败，finally 都要 Stop。

