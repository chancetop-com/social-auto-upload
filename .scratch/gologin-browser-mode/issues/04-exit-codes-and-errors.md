# 04 — 退出码与错误面

Status: open
Type: grilling
Blocked by: 01
Assignee: —

## Question

把 GoLogin 的每一种失败映射到现有退出码契约，写成一张表：

1. **复用现有码**
   - `10`（登录失效 / 人机验证）、`11`（429）、`1`（运行失败）、`2`（用法错误）、`9`（发布结果未知）、`130`（中断）在 GoLogin 下是否原样沿用；有无需要新增的码。
2. **Local API / Cloud API 的错误形状**
   - GoLogin 用 HTTP 状态还是 JSON 业务码表达失败；`probe` / `start` / `stop` / `status` 各自怎么判定成功。
   - token 无效（401/403）、Profile 不存在、Profile 已运行、Local API 未开启、桌面应用未启动、云端鉴权过期，分别落在哪个码、文案怎么写。
   - 429 是否真实存在；若存在，是否与 MLX/AdsPower 共用 `11` 且 CLI 不自动重试。
3. **云端特有失败**
   - 远程 CDP 连不上、连接中途断开、云端会话超时/被回收，分别映射到哪个码；是否需要 `9`（结果未知）。
   - 云端出口与本地不一致导致的平台风控（登录失效/验证码）是否仍走 `10`。
4. **生命周期阶段的失败**
   - start 成功但响应坏（`StartIncompleteError` 语义）在 GoLogin 下怎么定义。
   - stop 失败是否仍只 warning、保持原退出码。
   - 断开 CDP 失败是否只 warning。
5. **机器信号**
   - `publish_attempted=true` 的既有规则不变；GoLogin 不得新增第二套 stderr 信号。

## Context

- 现有契约见 `docs/CLI.md` 的「退出码」与 `utils/errors.py`。
- 结论要能直接填进 spec 的退出码表（本地 / MLX / AdsPower / GoLogin-local / GoLogin-cloud 五列）。
