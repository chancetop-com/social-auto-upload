# 07 — 测试策略（离线契约 + opt-in 冒烟）

Status: open
Type: grilling
Blocked by: 02
Assignee: —

## Question

在**没有 GoLogin 账号、云端可能不可用**的前提下，定义可交付的测试矩阵：

1. **离线层**
   - client 注入 `http_get` / `http_post` 的手写 fake；响应样本放哪个 fixtures 目录、如何脱敏。
   - 是否复用 `tests/fakes.py` 的 provider fake，还是新增 GoLogin 专用 fake。
   - 需要覆盖哪些契约：激活/冲突、runtime 解析、start 响应坏、401/429、stop 幂等、连接重试、contexts 数量异常。
2. **云端特有**
   - 远程 CDP 不可离线模拟时，哪些用 fake 覆盖、哪些只能标「未验证」。
   - 是否需要 `SAU_GOLOGIN_SMOKE=1` 的 opt-in 冒烟（只读或 dry-run），以及它验证什么。
3. **回归层**
   - 现有 `tests/test_mlx_*` / `tests/test_adspower_*` 必须零改动；平台层回归怎么证明 `session.managed` 仍成立。
   - 是否加静态守卫禁止平台层直接判 `mode == "gologin"`。
4. **不做的事**
   - 真实发布、风控、验证码、代理指纹不自动化；覆盖率不设数字。

## Context

- 现有策略见 `.scratch/adspower-browser-mode/issues/05-test-strategy.md` 与 `tests/`。
- 本轮只交 spec，测试策略要写成「实现时新增哪些文件、各覆盖什么」，不要求现在写测试。
