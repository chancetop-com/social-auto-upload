# 09 — 真实 AdsPower 冒烟验证

Status: open
Type: task
Blocked by: 01
Assignee: —

## Question

提供并执行一套默认跳过、需要真实 AdsPower 桌面应用才能运行的冒烟验证，把 research ticket 01 中标注“官方/示例”置信度的结论落成实测证据。要求：

1. 新增 opt-in 测试（如 `SAU_ADSPOWER_SMOKE=1`），默认在 CI/本地套件中跳过。
2. 只验证浏览器生命周期，不上传任何内容：探活 → start → connect_over_cdp → 读取当前 URL/title → disconnect → stop。
3. 若安全可行，验证：已运行 Profile 的 start 行为、重复 stop 的幂等性、`contexts` 数量、`headless=1`、`ws.puppeteer` 直连、401/403 与 429 的真实响应、V2 最低可用版本、`cdp_mask=1` 与 patchright 的兼容性。不要测试 `delete_cache=1` / 清缓存，避免破坏测试 Profile 的登录态。
4. 失败时输出脱敏诊断（不含 API key、不含真实账号/Profile 名称）。
5. 运行前提：AdsPower 付费版、桌面应用运行、API 开启、有效 API Key、一个已登录的测试 Profile。
6. 当前机器未安装 AdsPower，ticket 保持 open，等待外部环境；不得用 mock 冒充实测。
7. 结果写到 `.scratch/adspower-browser-mode/research/09-smoke-findings.md`，并回填 ticket 01/04/08 中需要修正的结论。

## Context

- 外部阻塞：本机 `/Applications` 无 AdsPower，50325 未监听。
- 参考 MLX 冒烟 ticket：`.scratch/multilogin-browser-mode/issues/08-mlx-smoke-test.md`、`27-mlx-smoke.md`。

## Answer

待执行（外部依赖）。
