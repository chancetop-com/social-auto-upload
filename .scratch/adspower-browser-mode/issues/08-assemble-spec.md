# 08 — 汇总 AdsPower 模式设计规格

Status: resolved
Type: task
Blocked by: 01, 02, 03, 04, 05, 06, 07, 10
Assignee: OpenCode

## Question

把已解决的 ticket 汇总成 `.scratch/adspower-browser-mode/spec.md`，作为本次 effort 的最终交付物。规格至少包含：

1. 摘要、目标/非目标、术语。
2. 模式与激活：`ADSPOWER_API_KEY`、与 `MLX_API_TOKEN` 的冲突（退出 1）、`ADSPOWER_API_BASE`。
3. CLI 契约：参数矩阵（本地/MLX/AdsPower）、退出码、示例命令、`login` 拒绝。
4. 运行时架构：`sau_cli → sau_commands → utils`；provider 协议、`browser_session`、`AdsPowerClient`、错误类型。
5. 生命周期与所有权：probe、start、connect、context 校验、disconnect、stop、重试、取消、幂等、已运行 Profile。
6. 逐平台表：支持/不支持、action、平台特有限制。
7. 登录检测与身份绑定：Profile 即身份、退出 10、不读 cookie。
8. 安全：API key 脱敏、base URL、日志。
9. 部署前提与调度责任。
10. 测试矩阵与验收清单。
11. 实施阶段拆分（如果规格要交给后续 Builder）。
12. 风险、置信度与外部阻塞（真实 AdsPower 冒烟）。
13. 与现有 MLX/本地模式的兼容性声明。
14. AdsPower API 版本与端点选择：V2 / V1 fallback、`profile_id` 字段、start 固定参数。

## Context

- 参考结构：`.scratch/multilogin-browser-mode/spec.md`。
- 每个结论链接到对应 ticket；不要在规格里重复未解决的 fog。
- 置信度标注沿用上一个 effort：`[官方]` / `[社区]` / `[实测]` / `[设计]`。

## Answer

规格已写入 [`spec.md`](../spec.md)。覆盖 ticket 要求的 14 项：摘要/目标/术语、激活与冲突、CLI 参数与退出码、运行时架构（Provider Protocol / AdsPowerClient / BrowserSession / 错误分层）、生命周期与所有权、逐平台表、登录与身份、安全、部署与调度、测试矩阵与验收、三阶段实施、风险与 09 未知项、MLX/本地兼容性、V2 端点选择。

汇总时吸收并显式记录了 07 的两个发现：

1. 阶段 1 的迁移范围以 07 实测为准（17 个 import 模块、36 个 `browser_session` 调用点、41 个 flags 落点、28 处 `session.mode`）；map 的 32/35 数字作废。
2. “8 个 `test_mlx_*.py` 零改动”修正为“业务断言零改动；`test_mlx_smoke.py:377` 与 `test_mlx_hupu_dayu.py:405` 各允许 1 行 `browser_session` 签名迁移”，避免与 ticket 03 的“不做别名”冲突。
3. bilibili 的 `reject_multilogin_* → reject_managed_*` 写入阶段 2 必做项，防止 AdsPower 模式下静默走本地 `biliup`。

最终交付物就绪；真实 AdsPower 冒烟仍由 09 外部阻塞，不影响本规格的可实施性。
