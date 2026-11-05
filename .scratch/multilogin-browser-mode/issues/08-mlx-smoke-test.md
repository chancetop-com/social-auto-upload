# 08 — 开通 MLX 并做真机冒烟

Status: open
Type: task
Blocked by: 01, 02
Assignee: —

## Question

在真实环境验证文档结论，为设计提供一手数据（当前**没有账号，无法执行**，保留为实施前的阻塞项）：

1. 生成 Workspace Automation Token，记录有效期与权限要求（不要把 token 写进仓库）。
2. 建一个测试 Profile：
   - 指定 Mimic 内核；
   - 配置一个住宅/移动代理；
   - 手动登录一个平台（建议抖音或小红书）。
3. 用 `curl` 验证：
   - `GET /api/v1/version`
   - `GET /api/v2/profile/f/{folder}/p/{profile}/start?automation_type=playwright&headless_mode=false`
   - 记录完整响应（脱敏）与耗时；
   - 再次 start 同一 profile，记录“已在运行”的响应；
   - `GET /api/v1/profile/statuses`，记录结构；
   - `GET /api/v1/profile/stop/p/{profile}`，重复 stop，记录幂等行为。
4. 用 patchright 1.58.2 连接 `http://127.0.0.1:{port}`：
   - 打印 `len(browser.contexts)`、`len(context.pages)`；
   - 访问平台创作者中心，确认登录态仍在；
   - 确认 `browser.close()` 后 profile 仍在运行；
   - 再调 Stop。
5. 记录异常：证书、401、429、CDP 连不上、headless 下登录页表现。

产物写到 `.scratch/multilogin-browser-mode/research/08-smoke-findings.md`（脱敏：不含 token、不含真实账号信息）。

## Answer

（待填）
